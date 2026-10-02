"""SQLite persistence; source predictions never change when a record is corrected."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connection(data_dir, timeout=10):
    db = sqlite3.connect(Path(data_dir) / "em.sqlite3", timeout=timeout)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize(data_dir):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "sources").mkdir(exist_ok=True)
    (data_dir / "backups").mkdir(exist_ok=True)
    with closing(connection(data_dir)) as db, db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
            parser_version TEXT NOT NULL, created_at TEXT NOT NULL,
            latest_parser_version TEXT, context_json TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS import_log (
            id INTEGER PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY, source_id INTEGER REFERENCES sources(id),
            source_location TEXT NOT NULL, source_text TEXT NOT NULL,
            original TEXT NOT NULL, current TEXT NOT NULL, verified TEXT NOT NULL,
            original_parser_version TEXT,
            warnings TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'draft'
                CHECK(state IN ('draft','confirmed','void')),
            analysis_included INTEGER NOT NULL DEFAULT 1 CHECK(analysis_included IN (0,1)),
            analysis_exclusion_reason TEXT NOT NULL DEFAULT '',
            origin_kind TEXT NOT NULL DEFAULT 'file' CHECK(origin_kind IN ('file','manual','sheet')),
            version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_id, source_location));
        CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL REFERENCES records(id),
            changed_at TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
            before_json TEXT NOT NULL, after_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sheet_snapshots (
            id INTEGER PRIMARY KEY, source_name TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
            source_kind TEXT NOT NULL CHECK(source_kind IN ('xlsx','google-api')),
            complete INTEGER NOT NULL CHECK(complete IN (0,1)), created_at TEXT NOT NULL,
            rows_json TEXT NOT NULL, summary_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sheet_snapshot_reads (
            id INTEGER PRIMARY KEY, content_snapshot_id INTEGER NOT NULL REFERENCES sheet_snapshots(id),
            source_name TEXT NOT NULL, source_kind TEXT NOT NULL CHECK(source_kind IN ('xlsx','google-api')),
            complete INTEGER NOT NULL CHECK(complete IN (0,1)), created_at TEXT NOT NULL,
            summary_json TEXT NOT NULL, evidence_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sheet_adoptions (
            fingerprint TEXT PRIMARY KEY, record_id INTEGER NOT NULL UNIQUE REFERENCES records(id),
            snapshot_id INTEGER NOT NULL REFERENCES sheet_snapshots(id), created_at TEXT NOT NULL);
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(sources)")}
        if "latest_parser_version" not in columns:
            db.execute("ALTER TABLE sources ADD COLUMN latest_parser_version TEXT")
        if "context_json" not in columns:
            db.execute("ALTER TABLE sources ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}' ")
        db.execute("UPDATE sources SET latest_parser_version=parser_version WHERE latest_parser_version IS NULL")
        db.execute("""INSERT INTO sheet_snapshot_reads(
            content_snapshot_id,source_name,source_kind,complete,created_at,summary_json,evidence_json)
            SELECT s.id,s.source_name,s.source_kind,s.complete,s.created_at,s.summary_json,
                '{"source_kind":"legacy","spreadsheet_id":"","completeness_basis":"舊版快照完整性標記","tabs":{}}'
            FROM sheet_snapshots s WHERE NOT EXISTS (
                SELECT 1 FROM sheet_snapshot_reads r WHERE r.content_snapshot_id=s.id)""")
        record_columns = {row[1] for row in db.execute("PRAGMA table_info(records)")}
        if "original_parser_version" not in record_columns:
            db.execute("ALTER TABLE records ADD COLUMN original_parser_version TEXT")
        if "analysis_included" not in record_columns:
            db.execute("ALTER TABLE records ADD COLUMN analysis_included INTEGER NOT NULL DEFAULT 1 CHECK(analysis_included IN (0,1))")
        if "analysis_exclusion_reason" not in record_columns:
            db.execute("ALTER TABLE records ADD COLUMN analysis_exclusion_reason TEXT NOT NULL DEFAULT ''")
        if "origin_kind" not in record_columns:
            db.execute("ALTER TABLE records ADD COLUMN origin_kind TEXT NOT NULL DEFAULT 'file'")
            db.execute("UPDATE records SET origin_kind=CASE WHEN source_id IS NULL THEN 'manual' ELSE 'file' END")
        db.execute("""UPDATE records SET original_parser_version=(
            SELECT parser_version FROM sources WHERE sources.id=records.source_id)
            WHERE original_parser_version IS NULL AND source_id IS NOT NULL""")
        db.execute("PRAGMA user_version=6")


def backup(data_dir):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = Path(data_dir) / "backups" / (stamp + ".sqlite3")
    with closing(connection(data_dir)) as src, closing(sqlite3.connect(path)) as dst:
        src.backup(dst)
    return path


def decode(row):
    item = dict(row)
    for key in ("original", "current", "verified", "warnings"):
        item[key] = json.loads(item[key])
    item["is_manual"] = item.get("origin_kind", "manual" if item["source_id"] is None else "file") == "manual"
    return item


def records(data_dir):
    with closing(connection(data_dir)) as db:
        return [decode(row) for row in db.execute("""
            SELECT records.*, sources.name AS source_name, sources.sha256,
                sources.parser_version, sources.parser_version AS source_initial_parser_version,
                sources.latest_parser_version,
                sources.context_json FROM records
            LEFT JOIN sources ON records.source_id=sources.id ORDER BY records.id DESC
        """)]


def get(data_dir, record_id):
    with closing(connection(data_dir)) as db:
        row = db.execute("""SELECT records.*, sources.name AS source_name,
            sources.sha256, sources.parser_version,
            sources.parser_version AS source_initial_parser_version, sources.latest_parser_version,
            sources.context_json FROM records
            LEFT JOIN sources ON records.source_id=sources.id WHERE records.id=?""",
            (record_id,)).fetchone()
    return decode(row) if row else None


def add_import(data_dir, filename, content, parsed, parser_version, context=None):
    digest = hashlib.sha256(content).hexdigest()
    with closing(connection(data_dir)) as db:
        found = db.execute("SELECT id FROM sources WHERE sha256=?", (digest,)).fetchone()
    if found:
        return 0  # Same bytes, including renamed files: preserve earlier human corrections.
    locations = [r["source_location"] for r in parsed]
    if len(set(locations)) != len(locations):
        raise ValueError("來源位置重複；匯入停止，請檢查解析器。")
    backup(data_dir)
    extension = Path(filename).suffix.lower()
    archive = Path(data_dir) / "sources" / (digest + extension)
    archive.write_bytes(content)
    with closing(connection(data_dir)) as db, db:
        # A database unique constraint also protects two overlapping import requests.
        inserted = db.execute(
            "INSERT INTO sources(name,sha256,parser_version,created_at,latest_parser_version,context_json) VALUES(?,?,?,?,?,?) ON CONFLICT(sha256) DO NOTHING",
            (Path(filename).name, digest, parser_version, now(), parser_version,
             json.dumps(context or {}, ensure_ascii=False)),
        )
        if inserted.rowcount == 0:
            return 0
        source_id = inserted.lastrowid
        for row in parsed:
            values = json.dumps(row["values"], ensure_ascii=False)
            db.execute("""INSERT INTO records(source_id,source_location,source_text,
                original,current,verified,original_parser_version,warnings,created_at,updated_at)
                VALUES(?,?,?,?,?,'{}',?,?,?,?)""", (
                source_id, row["source_location"], row["source_text"], values, values,
                parser_version, json.dumps(row["warnings"], ensure_ascii=False), now(), now(),
            ))
    return len(parsed)


class StaleRecord(ValueError):
    pass


def _checked_update(db, sql, params, message):
    changed = db.execute(sql, params)
    if changed.rowcount != 1:
        raise StaleRecord(message)


def _warnings_for_current(warnings, current):
    resolved = {f"{field}: 未取得" for field, value in current.items() if value}
    return list(dict.fromkeys(warning for warning in warnings if warning not in resolved))


def reparse_source(data_dir, source_id, content, parsed, parser_version):
    """Update only untouched draft fields; keep source recognition and history."""
    digest = hashlib.sha256(content).hexdigest()
    with closing(connection(data_dir)) as db:
        source = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not source:
        raise ValueError("找不到匯入來源。")
    if digest != source["sha256"]:
        raise ValueError("保留來源副本的 SHA-256 不符；未重新解析。")
    if source["latest_parser_version"] == parser_version:
        return {"noop": True, "backup": "", "added": 0, "updated": 0, "conflicts": 0, "voided": 0}
    locations = [row["source_location"] for row in parsed]
    if len(locations) != len(set(locations)):
        raise ValueError("新版解析器產生重複來源位置；重新解析停止。")
    backup_path = backup(data_dir)
    summary = {"noop": False, "backup": backup_path.name, "added": 0, "updated": 0,
               "conflicts": 0, "voided": 0}
    with closing(connection(data_dir)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            source = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
            if not source:
                raise ValueError("找不到匯入來源。")
            if digest != source["sha256"]:
                raise ValueError("保留來源副本的 SHA-256 不符；未重新解析。")
            if source["latest_parser_version"] == parser_version:
                db.rollback()
                summary["noop"] = True
                return summary
            existing = {row["source_location"]: row for row in db.execute(
                "SELECT * FROM records WHERE source_id=?", (source_id,))}
            candidates = {row["source_location"]: row for row in parsed}
            for location, candidate in candidates.items():
                row = existing.get(location)
                values = candidate["values"]
                if row is None:
                    encoded = json.dumps(values, ensure_ascii=False)
                    _checked_update(db, """INSERT INTO records(source_id,source_location,source_text,
                        original,current,verified,original_parser_version,warnings,created_at,updated_at)
                        VALUES(?,?,?,?,?,'{}',?,?,?,?)""", (
                        source_id, location, candidate["source_text"], encoded, encoded, parser_version,
                        json.dumps(_warnings_for_current(candidate["warnings"], values), ensure_ascii=False),
                        now(), now()), "新增解析列失敗；來源版本未升級。")
                    summary["added"] += 1
                    continue
                original = json.loads(row["original"])
                current = json.loads(row["current"])
                verified = json.loads(row["verified"])
                old_warnings = json.loads(row["warnings"])
                manual_fields, parser_fields = set(), set()
                for change in db.execute("SELECT before_json,after_json,actor FROM changes WHERE record_id=?", (row["id"],)):
                    after = json.loads(change["after_json"])
                    if change["actor"] == "解析器":
                        parser_fields.update(after.get("auto_updated_fields", []))
                    else:
                        before, after = json.loads(change["before_json"]), json.loads(change["after_json"])
                        before_values, after_values = before.get("current", {}), after.get("current", {})
                        manual_fields.update(field for field in values if before_values.get(field) != after_values.get(field))
                protected = {field for field in values if field in manual_fields or
                             verified.get(field) in ("checked", "not_applicable")}
                inclusion = {"analysis_included": row["analysis_included"],
                             "analysis_exclusion_reason": row["analysis_exclusion_reason"]}
                before = {"current": json.loads(row["current"]), "verified": json.loads(row["verified"]),
                          "state": row["state"], "warnings": old_warnings, **inclusion}
                updated_fields, conflicts = [], {}
                if row["state"] == "draft":
                    for field, new_value in values.items():
                        if field not in protected and (current.get(field) == original.get(field) or field in parser_fields):
                            if current.get(field) != new_value:
                                current[field] = new_value
                                updated_fields.append(field)
                        elif current.get(field) != new_value:
                            conflicts[field] = new_value
                elif any(current.get(field) != value for field, value in values.items()):
                    conflicts = {field: value for field, value in values.items() if current.get(field) != value}
                warnings = _warnings_for_current(candidate["warnings"], current)
                if conflicts:
                    warnings.append("重新解析有差異待核對：" + ", ".join(sorted(conflicts)))
                    summary["conflicts"] += len(conflicts)
                warnings = list(dict.fromkeys(warnings))
                changed = bool(updated_fields or warnings != old_warnings or conflicts)
                if changed:
                    after = {"current": dict(current), "verified": dict(verified),
                             "state": row["state"], "warnings": warnings, "parser_version": parser_version,
                             **inclusion, "candidate_values": values, "auto_updated_fields": updated_fields,
                             "protected_conflicts": conflicts}
                    _checked_update(db, """UPDATE records SET current=?,warnings=?,version=version+1,updated_at=?
                        WHERE id=? AND version=?""", (json.dumps(current, ensure_ascii=False),
                        json.dumps(warnings, ensure_ascii=False), now(), row["id"], row["version"]),
                        f"紀錄 {row['id']} 在重新解析期間已變更；整批重新解析已回滾。")
                    db.execute("""INSERT INTO changes(record_id,changed_at,actor,reason,before_json,after_json)
                        VALUES(?,?,?,?,?,?)""", (row["id"], now(), "解析器",
                        f"重新解析 {source['latest_parser_version']} → {parser_version}；自動補值 {','.join(updated_fields) or '無'}；保護衝突 {','.join(conflicts) or '無'}",
                        json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)))
                    if updated_fields:
                        summary["updated"] += 1
            for location, row in existing.items():
                if location in candidates:
                    continue
                inclusion = {"analysis_included": row["analysis_included"],
                             "analysis_exclusion_reason": row["analysis_exclusion_reason"]}
                current, original = json.loads(row["current"]), json.loads(row["original"])
                verified = json.loads(row["verified"])
                manual_fields, parser_fields = set(), set()
                for change in db.execute("SELECT before_json,after_json,actor FROM changes WHERE record_id=?", (row["id"],)):
                    before, after = json.loads(change["before_json"]), json.loads(change["after_json"])
                    if change["actor"] == "解析器":
                        parser_fields.update(after.get("auto_updated_fields", []))
                    else:
                        before_values, after_values = before.get("current", {}), after.get("current", {})
                        manual_fields.update(field for field in original if before_values.get(field) != after_values.get(field))
                unexplained_difference = any(current.get(field) != original.get(field) and field not in parser_fields
                                             for field in original)
                manual_or_checked = bool(manual_fields or unexplained_difference or
                                         any(verified.get(field) in ("checked", "not_applicable") for field in original))
                old_warnings = json.loads(row["warnings"])
                reason = "新版解析判定此列為非資料；原紀錄保留，未刪除。"
                if row["state"] == "draft" and not manual_or_checked:
                    after = {"current": current, "verified": verified, "state": "void", "reason": reason,
                             **inclusion, "parser_version": parser_version}
                    _checked_update(db, "UPDATE records SET state='void',version=version+1,updated_at=? WHERE id=? AND version=?",
                                    (now(), row["id"], row["version"]),
                                    f"紀錄 {row['id']} 在重新解析期間已變更；整批重新解析已回滾。")
                    db.execute("""INSERT INTO changes(record_id,changed_at,actor,reason,before_json,after_json)
                        VALUES(?,?,?,?,?,?)""", (row["id"], now(), "解析器", reason,
                        json.dumps({"current": current, "verified": verified, "state": row["state"],
                                    "warnings": old_warnings, **inclusion}, ensure_ascii=False),
                        json.dumps(after, ensure_ascii=False)))
                    summary["voided"] += 1
                else:
                    warnings = _warnings_for_current(old_warnings, current)
                    warnings = list(dict.fromkeys(warnings + [reason + " 已核對或人工修改，保留原狀。"]))
                    _checked_update(db, "UPDATE records SET warnings=?,version=version+1,updated_at=? WHERE id=? AND version=?",
                                    (json.dumps(warnings, ensure_ascii=False), now(), row["id"], row["version"]),
                                    f"紀錄 {row['id']} 在重新解析期間已變更；整批重新解析已回滾。")
                    db.execute("""INSERT INTO changes(record_id,changed_at,actor,reason,before_json,after_json)
                        VALUES(?,?,?,?,?,?)""", (row["id"], now(), "解析器", reason,
                        json.dumps({"current": current, "verified": verified, "state": row["state"],
                                    "warnings": old_warnings, **inclusion}, ensure_ascii=False),
                        json.dumps({"current": current, "verified": verified, "state": row["state"],
                                    "warnings": warnings, **inclusion, "parser_version": parser_version}, ensure_ascii=False)))
                    summary["conflicts"] += 1
            _checked_update(db, "UPDATE sources SET latest_parser_version=? WHERE id=? AND latest_parser_version=?",
                            (parser_version, source_id, source["latest_parser_version"]),
                            "來源解析版本已變更；整批重新解析已回滾。")
            detail = (f"parser={parser_version}; added={summary['added']}; updated={summary['updated']}; "
                      f"conflicts={summary['conflicts']}; voided={summary['voided']}; backup={backup_path.name}")
            db.execute("INSERT INTO import_log(filename,sha256,created_at,status,detail) VALUES(?,?,?,?,?)",
                       (source["name"], digest, now(), "reparsed", detail))
            db.commit()
        except Exception:
            db.rollback()
            raise
    return summary


def add_manual(data_dir, values):
    backup(data_dir)
    with closing(connection(data_dir)) as db, db:
        return db.execute("""INSERT INTO records(source_location,source_text,origin_kind,
            original,current,verified,warnings,created_at,updated_at)
            VALUES('人工輸入','','manual','{}',?,'{}','[]',?,?)""",
            (json.dumps(values, ensure_ascii=False), now(), now())).lastrowid


def add_sheet_snapshot(data_dir, source_name, digest, source_kind, complete, rows_by_sheet, summary,
                       evidence=None):
    """Deduplicate snapshot content while preserving evidence for every read."""
    backup(data_dir)
    stamp, name = now(), Path(source_name).name
    with closing(connection(data_dir)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            found = db.execute("SELECT id FROM sheet_snapshots WHERE sha256=?", (digest,)).fetchone()
            duplicate = found is not None
            if found:
                content_id = found["id"]
            else:
                content = db.execute("""INSERT INTO sheet_snapshots(source_name,sha256,source_kind,complete,
                    created_at,rows_json,summary_json) VALUES(?,?,?,?,?,?,?)""",
                    (name, digest, source_kind, int(bool(complete)), stamp,
                     json.dumps(rows_by_sheet, ensure_ascii=False, separators=(",", ":")),
                     json.dumps(summary, ensure_ascii=False, separators=(",", ":"))))
                content_id = content.lastrowid
            detail = dict(evidence or {})
            detail.setdefault("source_kind", source_kind)
            detail.setdefault("spreadsheet_id", "")
            detail.setdefault("completeness_basis", "已確認完整" if complete else "未確認完整")
            read = db.execute("""INSERT INTO sheet_snapshot_reads(content_snapshot_id,source_name,
                source_kind,complete,created_at,summary_json,evidence_json) VALUES(?,?,?,?,?,?,?)""",
                (content_id, name, source_kind, int(bool(complete)), stamp,
                 json.dumps(summary, ensure_ascii=False, separators=(",", ":")),
                 json.dumps(detail, ensure_ascii=False, separators=(",", ":"))))
            db.commit()
            return {"id": read.lastrowid, "content_id": content_id, "duplicate": duplicate}
        except Exception:
            db.rollback()
            raise


def sheet_snapshot(data_dir, snapshot_id):
    with closing(connection(data_dir)) as db:
        row = db.execute("""SELECT r.id,r.content_snapshot_id,r.source_name,r.source_kind,
            r.complete,r.created_at,r.summary_json AS read_summary_json,r.evidence_json,
            s.sha256,s.rows_json FROM sheet_snapshot_reads r
            JOIN sheet_snapshots s ON s.id=r.content_snapshot_id WHERE r.id=?""",
            (snapshot_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["rows_by_sheet"] = json.loads(item.pop("rows_json"))
    item["summary"] = json.loads(item.pop("read_summary_json"))
    item["evidence"] = json.loads(item.pop("evidence_json"))
    item["content_id"] = item.pop("content_snapshot_id")
    for title, rows in item["rows_by_sheet"].items():
        tab = item["evidence"].get("tabs", {}).get(title, {})
        for source_row in rows:
            source_row["sheet_title"] = title
            source_row["sheet_id"] = tab.get("sheet_id")
            source_row["formula_cells"] = tab.get("formula_cells", {}).get(
                str(source_row["row_number"]), {})
    item["complete"] = bool(item["complete"])
    return item


def sheet_snapshots(data_dir):
    with closing(connection(data_dir)) as db:
        return [dict(row) for row in db.execute("""SELECT r.id,r.source_name,s.sha256,r.source_kind,
            r.complete,r.created_at,r.content_snapshot_id AS content_id
            FROM sheet_snapshot_reads r JOIN sheet_snapshots s ON s.id=r.content_snapshot_id
            ORDER BY r.id DESC""")]


def sheet_adoptions(data_dir):
    with closing(connection(data_dir)) as db:
        return {row["fingerprint"]: row["record_id"] for row in db.execute(
            "SELECT fingerprint,record_id FROM sheet_adoptions")}


def _records_in_transaction(db):
    return [decode(row) for row in db.execute("""SELECT records.*, sources.name AS source_name,
        sources.sha256, sources.parser_version,
        sources.parser_version AS source_initial_parser_version,
        sources.latest_parser_version, sources.context_json FROM records
        LEFT JOIN sources ON records.source_id=sources.id ORDER BY records.id""")]


def _manually_touched_fields(db, record_id):
    touched = set()
    for change in db.execute("SELECT actor,before_json,after_json FROM changes WHERE record_id=?", (record_id,)):
        if change["actor"] in ("解析器", "Sheet對帳"):
            continue
        before, after = json.loads(change["before_json"]), json.loads(change["after_json"])
        before_values, after_values = before.get("current", {}), after.get("current", {})
        touched.update(field for field in before_values.keys() | after_values.keys()
                       if before_values.get(field) != after_values.get(field))
    return touched


def _snapshot_for_reconcile(db, snapshot_id):
    row = db.execute("""SELECT r.id,r.content_snapshot_id,r.source_name,r.source_kind,
        r.complete,r.created_at,r.summary_json AS read_summary_json,r.evidence_json,
        s.sha256,s.rows_json FROM sheet_snapshot_reads r
        JOIN sheet_snapshots s ON s.id=r.content_snapshot_id WHERE r.id=?""", (snapshot_id,)).fetchone()
    if not row:
        raise ValueError("找不到 Sheet 快照；沒有寫入。")
    item = dict(row)
    item["rows_by_sheet"] = json.loads(item.pop("rows_json"))
    item["summary"] = json.loads(item.pop("read_summary_json"))
    item["evidence"] = json.loads(item.pop("evidence_json"))
    item["content_id"] = item.pop("content_snapshot_id")
    for title, rows in item["rows_by_sheet"].items():
        tab = item["evidence"].get("tabs", {}).get(title, {})
        for source_row in rows:
            source_row["sheet_title"] = title
            source_row["sheet_id"] = tab.get("sheet_id")
            source_row["formula_cells"] = tab.get("formula_cells", {}).get(
                str(source_row["row_number"]), {})
    item["complete"] = bool(item["complete"])
    latest = db.execute("SELECT MAX(id) FROM sheet_snapshot_reads").fetchone()[0]
    if item["id"] != latest:
        raise StaleRecord("已有較新的 Sheet 讀取；請刷新預覽後再操作，沒有寫入。")
    return item


def _sheet_evidence(snapshot, group):
    from .sheet_reconcile import field_source_trace

    sources = field_source_trace(group)
    species_cells = [{"tab": row.get("sheet_title", ""), "row": row["row_number"],
                      "cell": f"{column}{row['row_number']}", "raw_value": row["values"][index]}
                     for row in group["rows"] for index, column in enumerate("STUVWXY", 18)
                     if row["values"][index]]
    zero = ({"reason": group["zero_inference"], "rule_version": group.get("zero_rule_version", "em008-cfu-v2"),
             "evidence": {"N_O": sources["cfu_count"], "species_cells_S_Y": species_cells}}
            if group.get("zero_inference") else None)
    return {"snapshot_id": snapshot["id"], "content_snapshot_id": snapshot.get("content_id"),
            "source_name": snapshot["source_name"], "sha256": snapshot["sha256"],
            "source_kind": snapshot["source_kind"], "read_at": snapshot.get("created_at"),
            "read_evidence": snapshot.get("evidence", {}),
            "sample_identity": group["identity"], "rule_version": group.get("zero_rule_version", "em008-cfu-v2"),
            "zero_inference": zero, "field_sources": sources,
            "rows": [{"tab": row.get("sheet_title", ""), "sheet_id": row.get("sheet_id"),
                      "site": row["site"], "row_number": row["row_number"],
                      "cells_A_Y": row["values"], "formula_cells": row.get("formula_cells", {})}
                     for row in group["rows"]]}


def apply_sheet_supplements(data_dir, snapshot_id, selected):
    """Apply selected unique, version-checked blank-field fills in one transaction."""
    if not selected:
        return {"updated": 0, "fields": 0, "records": [], "backup": ""}
    from .sheet_reconcile import match_word_candidates, sample_groups

    with closing(connection(data_dir)) as db:
        latest = db.execute("SELECT MAX(id) FROM sheet_snapshot_reads").fetchone()[0]
    if snapshot_id != latest:
        raise StaleRecord("已有較新的 Sheet 讀取；請刷新預覽後再操作，沒有寫入。")
    backup_path = backup(data_dir)
    result = {"updated": 0, "fields": 0, "records": [], "backup": backup_path.name}
    with closing(connection(data_dir)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            snapshot = _snapshot_for_reconcile(db, snapshot_id)
            groups = {group["fingerprint"]: group for group in sample_groups(snapshot)}
            match_word_candidates(list(groups.values()), _records_in_transaction(db), {
                row["fingerprint"]: row["record_id"] for row in db.execute(
                    "SELECT fingerprint,record_id FROM sheet_adoptions")})
            for item in selected:
                group = groups.get(item["fingerprint"])
                if (not group or group["status"] != "supplement" or
                        group.get("word_record_id") != int(item["record_id"])):
                    raise StaleRecord("Sheet 候選已改變或不再是唯一補值；整批未寫入。")
                row = db.execute("SELECT * FROM records WHERE id=?", (item["record_id"],)).fetchone()
                if not row or row["version"] != int(item["version"]):
                    raise StaleRecord("Word 紀錄版本已改變；整批未寫入。")
                current, original = json.loads(row["current"]), json.loads(row["original"])
                verified = json.loads(row["verified"])
                manual = _manually_touched_fields(db, row["id"])
                fills = {field: value for field, value in group.get("suggested_fills", {}).items()
                         if field not in manual and verified.get(field) not in ("checked", "not_applicable")
                         and not current.get(field) and not original.get(field)}
                if not fills:
                    raise StaleRecord("可補欄位已變更或受人工核對保護；整批未寫入。")
                evidence = _sheet_evidence(snapshot, group)
                before = {"current": dict(current), "original": original, "verified": verified,
                          "state": row["state"], "analysis_included": row["analysis_included"],
                          "analysis_exclusion_reason": row["analysis_exclusion_reason"]}
                current.update(fills)
                after = {**before, "current": dict(current), "sheet_evidence": evidence,
                         "auto_updated_fields": sorted(fills)}
                _checked_update(db, """UPDATE records SET current=?,version=version+1,updated_at=?
                    WHERE id=? AND version=?""", (json.dumps(current, ensure_ascii=False), now(),
                    row["id"], row["version"]), "Word 紀錄版本已改變；整批未寫入。")
                db.execute("""INSERT INTO changes(record_id,changed_at,actor,reason,before_json,after_json)
                    VALUES(?,?,?,?,?,?)""", (row["id"], now(), "Sheet對帳",
                    "依完整管理者 Sheet 快照補入仍空白欄位", json.dumps(before, ensure_ascii=False),
                    json.dumps(after, ensure_ascii=False)))
                result["updated"] += 1
                result["fields"] += len(fills)
                result["records"].append(row["id"])
            db.commit()
        except Exception:
            db.rollback()
            raise
    return result


def adopt_sheet_candidate(data_dir, snapshot_id, fingerprint):
    """Create one version-1 draft from a unique, previously unadopted Sheet sample."""
    from .sheet_reconcile import match_word_candidates, sample_groups

    with closing(connection(data_dir)) as db:
        latest = db.execute("SELECT MAX(id) FROM sheet_snapshot_reads").fetchone()[0]
    if snapshot_id != latest:
        raise StaleRecord("已有較新的 Sheet 讀取；請刷新預覽後再操作，沒有寫入。")
    backup_path = backup(data_dir)
    with closing(connection(data_dir)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            snapshot = _snapshot_for_reconcile(db, snapshot_id)
            groups = {group["fingerprint"]: group for group in sample_groups(snapshot)}
            adopted = {row["fingerprint"]: row["record_id"] for row in db.execute(
                "SELECT fingerprint,record_id FROM sheet_adoptions")}
            match_word_candidates(list(groups.values()), _records_in_transaction(db), adopted)
            group = groups.get(fingerprint)
            if not group or group["status"] != "new" or not group.get("sample"):
                raise StaleRecord("此 Sheet 樣本已存在、配對不唯一或仍待核對；未新增。")
            evidence = _sheet_evidence(snapshot, group)
            values = group["sample"]
            location = (f"Sheet {group['identity']['site']} row " +
                        ",".join(str(row["row_number"]) for row in group["rows"]))
            source_text = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
            warnings = [group["zero_inference"]] if group.get("zero_inference") else []
            created = now()
            cursor = db.execute("""INSERT INTO records(source_location,source_text,original,current,
                verified,original_parser_version,warnings,state,origin_kind,created_at,updated_at)
                VALUES(?,?,?,?,'{}','sheet-adapter-0.1.0',?,'draft','sheet',?,?)""",
                (location, source_text, json.dumps(values, ensure_ascii=False),
                 json.dumps(values, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False),
                 created, created))
            record_id = cursor.lastrowid
            db.execute("INSERT INTO sheet_adoptions(fingerprint,record_id,snapshot_id,created_at) VALUES(?,?,?,?)",
                        (fingerprint, record_id, snapshot["content_id"], created))
            db.commit()
            return {"record_id": record_id, "backup": backup_path.name}
        except Exception:
            db.rollback()
            raise


def update(data_dir, record_id, expected_version, values, verified, state, reason):
    if not reason.strip():
        raise ValueError("請填寫核對／修正原因。")
    backup(data_dir)
    with closing(connection(data_dir)) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
            if not row or row["version"] != expected_version:
                raise StaleRecord("資料已變更，請重新開啟後核對；本次未覆蓋。")
            before = {k: json.loads(row[k]) for k in ("current", "verified")}
            before["state"] = row["state"]
            after = {"current": values, "verified": verified, "state": state}
            _checked_update(db, """UPDATE records SET current=?,verified=?,state=?,
                version=version+1,updated_at=? WHERE id=? AND version=?""", (
                json.dumps(values, ensure_ascii=False), json.dumps(verified, ensure_ascii=False),
                state, now(), record_id, expected_version,
            ), "資料已變更，請重新開啟後核對；本次未覆蓋。")
            db.execute("""INSERT INTO changes(record_id,changed_at,actor,reason,
                before_json,after_json) VALUES(?,?,?,?,?,?)""", (
                record_id, now(), "本機使用者", reason.strip(),
                json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
            ))
            db.commit()
        except sqlite3.OperationalError as error:
            db.rollback()
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                raise StaleRecord("資料正在重新解析，請重新開啟後核對；本次未覆蓋。") from error
            raise
        except Exception:
            db.rollback()
            raise


def set_analysis_inclusion(data_dir, record_id, expected_version, included, reason):
    """Toggle a record's business-analysis scope without changing review state or values."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("請填寫排除／恢復原因。")
    if len(reason) > 120:
        raise ValueError("原因最多 120 字。")
    included = bool(included)
    backup(data_dir)
    with closing(connection(data_dir)) as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
            if not row or row["version"] != expected_version:
                raise StaleRecord("資料已變更，請重新開啟後再操作；本次未覆蓋。")
            if bool(row["analysis_included"]) == included:
                db.rollback()
                return False
            before = {"analysis_included": row["analysis_included"],
                      "analysis_exclusion_reason": row["analysis_exclusion_reason"],
                      "state": row["state"], "current": json.loads(row["current"]),
                      "original": json.loads(row["original"]), "verified": json.loads(row["verified"])}
            exclusion_reason = "" if included else reason
            after = {"analysis_included": int(included),
                     "analysis_exclusion_reason": exclusion_reason,
                     "state": row["state"], "current": before["current"],
                     "original": before["original"], "verified": before["verified"]}
            _checked_update(db, """UPDATE records SET analysis_included=?,analysis_exclusion_reason=?,
                version=version+1,updated_at=? WHERE id=? AND version=?""",
                (int(included), exclusion_reason, now(), record_id, expected_version),
                "資料已變更，請重新開啟後再操作；本次未覆蓋。")
            db.execute("""INSERT INTO changes(record_id,changed_at,actor,reason,before_json,after_json)
                VALUES(?,?,?,?,?,?)""", (record_id, now(), "本機使用者", reason,
                json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)))
            db.commit()
            return True
        except sqlite3.OperationalError as error:
            db.rollback()
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                raise StaleRecord("資料正在重新解析，請重新開啟後再操作；本次未覆蓋。") from error
            raise
        except Exception:
            db.rollback()
            raise


def history(data_dir, record_id):
    with closing(connection(data_dir)) as db:
        return [dict(r) for r in db.execute(
            "SELECT * FROM changes WHERE record_id=? ORDER BY id DESC", (record_id,))]


def log_import(data_dir, filename, content, status, detail):
    digest = hashlib.sha256(content).hexdigest() if content is not None else ""
    with closing(connection(data_dir)) as db, db:
        db.execute("INSERT INTO import_log(filename,sha256,created_at,status,detail) VALUES(?,?,?,?,?)",
                   (Path(filename).name, digest, now(), status, detail))


def import_history(data_dir):
    with closing(connection(data_dir)) as db:
        return [dict(r) for r in db.execute("SELECT * FROM import_log ORDER BY id DESC LIMIT 20")]


def sources(data_dir):
    with closing(connection(data_dir)) as db:
        rows = [dict(row) for row in db.execute("""SELECT sources.*,
            (SELECT COUNT(*) FROM records WHERE records.source_id=sources.id) AS record_count
            FROM sources ORDER BY id DESC""")]
    for row in rows:
        row["context_site"] = json.loads(row["context_json"] or "{}").get("site", "")
    return rows
