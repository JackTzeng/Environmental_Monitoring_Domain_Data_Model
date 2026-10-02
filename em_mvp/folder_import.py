"""Single-process background import for a user-selected local or UNC folder."""
from __future__ import annotations

import copy
import os
import secrets
import threading
from pathlib import Path

from . import store
from .domain import FIELDS
from .importers import PARSER_VERSION, parse_file

MAX_FOLDER_FILE_BYTES = 25 * 1024 * 1024
_LOCK = threading.RLock()
_JOBS: dict[str, dict] = {}
_ACTIVE_JOB_ID: str | None = None


class FolderImportInProgress(ValueError):
    def __init__(self, job_id: str):
        super().__init__("已有資料夾匯入工作進行中，請等待完成後再啟動。")
        self.job_id = job_id


def validate_folder(raw_path: str) -> Path:
    if not raw_path.strip():
        raise ValueError("請輸入本機或公司共用資料夾路徑。")
    try:
        root = Path(raw_path.strip()).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("資料夾不存在或無法存取；請確認路徑及權限。") from error
    if not root.is_dir():
        raise ValueError("指定的路徑不是資料夾。")
    try:
        with os.scandir(root) as entries:
            next(entries, None)
    except OSError as error:
        raise ValueError("無法讀取資料夾；請確認共用資料夾權限。") from error
    return root


def _snapshot(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return copy.deepcopy(job) if job else None


def folder_import_status(job_id: str, data_dir=None) -> dict | None:
    job = _snapshot(job_id)
    if job is None or (data_dir is not None and job["data_dir"] != str(Path(data_dir).resolve())):
        return None
    return job


def latest_folder_import(data_dir) -> dict | None:
    data_dir = str(Path(data_dir).resolve())
    with _LOCK:
        jobs = [job for job in _JOBS.values() if job["data_dir"] == data_dir]
        return copy.deepcopy(max(jobs, key=lambda item: item["started_at"])) if jobs else None


def _update(job_id: str, **values) -> None:
    with _LOCK:
        _JOBS[job_id].update(values)


def _increment(job_id: str, key: str, amount: int = 1) -> None:
    with _LOCK:
        _JOBS[job_id][key] += amount


def _failure(job_id: str, path: str, reason: str) -> None:
    reason = (reason.strip() or "未知錯誤")[:500]
    with _LOCK:
        job = _JOBS[job_id]
        job["failed_count"] += 1
        job["failures"].append({"path": path, "reason": reason})


def _reparse_directory(path: Path) -> bool:
    try:
        return path.is_symlink() or os.path.isjunction(path)
    except OSError:
        return True


def _office_temporary(name: str) -> bool:
    folded = name.casefold()
    return folded.startswith(("~$", ".~lock."))


def _scan(root: Path, job_id: str, include_sheets: bool) -> list[Path]:
    extensions = {".docx", ".xlsx", ".csv"} if include_sheets else {".docx"}
    candidates: list[Path] = []

    def scan_error(error: OSError) -> None:
        _failure(job_id, getattr(error, "filename", "資料夾"), f"無法掃描：{error}")

    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False, onerror=scan_error):
        _increment(job_id, "scanned_directories")
        retained = []
        for name in directories:
            path = Path(current) / name
            if _reparse_directory(path):
                _increment(job_id, "skipped_directories")
            else:
                retained.append(name)
        directories[:] = retained
        for name in filenames:
            path = Path(current) / name
            if _office_temporary(name):
                _increment(job_id, "skipped_files")
            elif path.suffix.casefold() not in extensions:
                _increment(job_id, "skipped_files")
            elif path.is_symlink():
                _increment(job_id, "skipped_files")
            else:
                candidates.append(path)
                _increment(job_id, "candidate_count")
    return candidates


def _relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path, root)).as_posix()


def _run(job_id: str, root: Path, data_dir: Path, include_sheets: bool, context: dict) -> None:
    global _ACTIVE_JOB_ID
    try:
        files = _scan(root, job_id, include_sheets)
        _update(job_id, state="processing", phase="processing")
        for path in files:
            relative = _relative(path, root)
            content = None
            _update(job_id, current_file=relative)
            try:
                size = path.stat().st_size
                if size > MAX_FOLDER_FILE_BYTES:
                    raise ValueError("超過 25 MB 單檔限制；其他檔案會繼續處理。")
                content = path.read_bytes()
                file_context = {**context, "source_prefix": relative + " / "}
                parsed = parse_file(path.name, content, context) if context else parse_file(path.name, content)
                if not parsed:
                    raise ValueError("沒有可讀取的明細；未入庫。")
                for row in parsed:
                    row["values"] = {field: str(row["values"].get(field, "")) for field in FIELDS}
                    row["source_location"] = file_context["source_prefix"] + row["source_location"]
                count = store.add_import(data_dir, path.name, content, parsed, PARSER_VERSION, file_context)
                if count:
                    _increment(job_id, "new_files")
                    _increment(job_id, "new_records", count)
                    status, detail = "imported", f"新增 {count} 筆待核對。"
                else:
                    _increment(job_id, "existing_files")
                    _increment(job_id, "existing_records", len(parsed))
                    status, detail = "duplicate", "相同內容已存在；未新增或覆蓋。"
                try:
                    store.log_import(data_dir, relative, content, status, detail)
                except Exception as error:
                    _failure(job_id, relative, f"資料已入庫，但匯入記錄寫入失敗：{error}")
            except Exception as error:
                detail = str(error).strip() or type(error).__name__
                try:
                    store.log_import(data_dir, relative, content, "error", detail)
                except Exception as log_error:
                    detail += f"；匯入記錄寫入失敗：{log_error}"
                _failure(job_id, relative, detail)
            finally:
                _increment(job_id, "processed_count")
        _update(job_id, state="complete", phase="complete", current_file="")
    except Exception as error:
        _failure(job_id, str(root), f"資料夾掃描失敗：{error}")
        _update(job_id, state="complete", phase="complete", current_file="")
    finally:
        from datetime import datetime, timezone
        _update(job_id, finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        with _LOCK:
            if _ACTIVE_JOB_ID == job_id:
                _ACTIVE_JOB_ID = None


def start_folder_import(data_dir, raw_path: str, include_sheets: bool = False, context: dict | None = None) -> dict:
    global _ACTIVE_JOB_ID
    root = validate_folder(raw_path)
    data_dir = Path(data_dir).resolve()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK:
        if _ACTIVE_JOB_ID and _JOBS.get(_ACTIVE_JOB_ID, {}).get("state") in ("scanning", "processing"):
            raise FolderImportInProgress(_ACTIVE_JOB_ID)
        job_id = secrets.token_urlsafe(12)
        job = {
            "id": job_id, "data_dir": str(data_dir), "root": str(root),
            "include_sheets": bool(include_sheets), "state": "scanning", "phase": "scanning",
            "context": context or {},
            "started_at": now, "finished_at": "", "current_file": "",
            "scanned_directories": 0, "candidate_count": 0, "processed_count": 0,
            "skipped_files": 0, "skipped_directories": 0,
            "new_files": 0, "new_records": 0,
            "existing_files": 0, "existing_records": 0,
            "failed_count": 0, "failures": [],
        }
        _JOBS[job_id] = job
        _ACTIVE_JOB_ID = job_id
        # Keep only a short in-memory status history for this single-user process.
        finished = [key for key, value in _JOBS.items() if value["state"] == "complete" and key != job_id]
        for old_id in finished[:-19]:
            _JOBS.pop(old_id, None)
        thread = threading.Thread(target=_run, args=(job_id, root, data_dir, bool(include_sheets), context or {}), daemon=True)
        try:
            thread.start()
        except RuntimeError:
            _ACTIVE_JOB_ID = None
            _JOBS.pop(job_id, None)
            raise
        return copy.deepcopy(job)
