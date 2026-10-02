"""Create the isolated, synthetic database used by the local MVP preview."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from em_mvp import store
from em_mvp.app import parse_file
from em_mvp.importers import PARSER_VERSION
from em_mvp.sheet_reconcile import HEADER_ROW, SHEETS, match_word_candidates, parse_xlsx_targets, sample_groups

PREVIEW_ID = "EM-MVP-Preview-EM008-20261002"
FIXTURE_DIR = ROOT / "preview" / "fixtures"
MANAGER_XLSX = FIXTURE_DIR / "manager-sheet-preview.xlsx"
CONFIRMED = {
    ("2026-06-19", "P-MOLD"), ("2026-06-21", "P-ALARM"),
    ("2026-07-19", "P-MOLD"), ("2026-07-21", "P-EXCLUDED"),
    ("2026-06-20", "P-HAND"), ("2026-07-20", "P-HAND"),
}


def _manager_row(batch, year, month, day, point, *, total, colonies, organism="",
                 purpose="環測", room="C06D", grade="A", lot="LOT-SHEET"):
    row = [""] * 25
    row[0], row[1] = "synthetic preview", batch
    row[2:8] = [year, month, day, "落菌法", purpose, lot]
    row[8], row[10], row[11], row[12] = "QA-MVP", room, grade, point
    row[13], row[14] = total, colonies
    if organism:
        row[18:25] = ["PREVIEW-1", "菌鑑", organism, "synthetic", "QA-MVP", "QA-MVP", "synthetic source"]
    return row


def build_manager_fixture():
    if MANAGER_XLSX.exists():
        parse_xlsx_targets(MANAGER_XLSX.read_bytes(), complete=True)
        return
    from openpyxl import Workbook

    workbook = Workbook()
    first = workbook.active
    first.title = "三廠管理者更新"
    second = workbook.create_sheet("一廠管理者更新")
    first.append(HEADER_ROW)
    second.append(HEADER_ROW)
    second.append(_manager_row("SHEET-001", 2026, 6, 19, "P-SHEET", total=3, colonies=1,
                               organism="Aspergillus niger", lot="LOT-SHEET"))
    second.append(_manager_row("SHEET-001", 2026, 6, 19, "P-SHEET", total="", colonies="",
                               organism="Penicillium chrysogenum", lot="LOT-SHEET"))
    second.append(_manager_row("SHEET-002", 2026, 7, 19, "P-XLSX-NEW", total=10, colonies=10,
                               lot="LOT-NEW"))
    second.append(_manager_row("SHEET-003", 2026, 7, 20, "P-UNMAPPED", total=2, colonies=1,
                               purpose="IC", lot="LOT-IC"))
    MANAGER_XLSX.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(MANAGER_XLSX)
    workbook.close()
    parse_xlsx_targets(MANAGER_XLSX.read_bytes(), complete=True)


def seed(data_dir: Path):
    data_dir = data_dir.expanduser().resolve()
    if data_dir.exists():
        raise FileExistsError(f"預覽資料目錄已存在；為避免覆寫，停止：{data_dir}")
    build_manager_fixture()
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir()
    store.initialize(data_dir)

    source_dir = FIXTURE_DIR / "seed"
    imported = []
    for source_path in sorted(source_dir.glob("*.csv")):
        content = source_path.read_bytes()
        parsed = parse_file(source_path.name, content)
        count = store.add_import(data_dir, source_path.name, content, parsed, PARSER_VERSION)
        imported.append({"name": source_path.name, "records": count})

    for record in store.records(data_dir):
        key = (record["current"].get("sample_date", ""), record["current"].get("point_id", ""))
        if key in CONFIRMED and record["state"] == "draft":
            store.update(data_dir, record["id"], record["version"], record["current"],
                         record["verified"], "confirmed", "合成 MVP 預覽範例；僅供介面檢視")

    excluded = [record for record in store.records(data_dir)
                if record["current"].get("point_id") == "P-EXCLUDED"]
    if len(excluded) != 1:
        raise RuntimeError("合成排除示例數量不符；預覽資料未標記完成。")
    store.set_analysis_inclusion(data_dir, excluded[0]["id"], excluded[0]["version"],
                                 False, "合成 MVP 預覽示範分析排除／還原")

    preview_xlsx = parse_xlsx_targets(MANAGER_XLSX.read_bytes(), complete=True)
    groups = sample_groups(preview_xlsx)
    match_word_candidates(groups, store.records(data_dir), store.sheet_adoptions(data_dir))
    if not any(group["status"] == "supplement" and group["identity"].get("point_id") == "P-SHEET"
               and {"room", "grade"}.issubset(group.get("suggested_fills", {})) for group in groups):
        raise RuntimeError("XLSX 示例沒有產生預期安全補欄候選；預覽資料未標記完成。")
    if not any(group["status"] == "pending" and group["identity"].get("point_id") == "P-UNMAPPED"
               for group in groups):
        raise RuntimeError("XLSX 未對照目的示例沒有維持待核；預覽資料未標記完成。")

    rows = store.records(data_dir)
    manifest = {
        "preview_id": PREVIEW_ID,
        "synthetic_only": True,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_version": "0.6.0",
        "parser_version": PARSER_VERSION,
        "data_dir": str(data_dir),
        "source_files": imported,
        "records": len(rows),
        "confirmed": sum(row["state"] == "confirmed" for row in rows),
        "draft": sum(row["state"] == "draft" for row in rows),
        "analysis_excluded": sum(not row["analysis_included"] for row in rows),
        "manager_xlsx": str(MANAGER_XLSX.resolve()),
        "note": "Only synthetic examples. Never connected to or copied from the production database or company sources.",
    }
    (data_dir / "preview-seed.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.environ.get("EM_MVP_DATA_DIR", ""),
                        help="New, isolated preview data directory; an existing path is never overwritten.")
    args = parser.parse_args()
    if not args.data_dir:
        args.data_dir = str(Path.home() / "AppData" / "Local" / "Packages" /
                            "OpenAI.Codex_2p2nqsd0c76g0" / "LocalCache" / "Local" /
                            "Codex" / PREVIEW_ID)
    seed(Path(args.data_dir))
