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
            version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_id, source_location));
        CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL REFERENCES records(id),
            changed_at TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
            before_json TEXT NOT NULL, after_json TEXT NOT NULL);
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(sources)")}
        if "latest_parser_version" not in columns:
            db.execute("ALTER TABLE sources ADD COLUMN latest_parser_version TEXT")
        if "context_json" not in columns:
            db.execute("ALTER TABLE sources ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}' ")
        db.execute("UPDATE sources SET latest_parser_version=parser_version WHERE latest_parser_version IS NULL")
        record_columns = {row[1] for row in db.execute("PRAGMA table_info(records)")}
        if "original_parser_version" not in record_columns:
            db.execute("ALTER TABLE records ADD COLUMN original_parser_version TEXT")
        db.execute("""UPDATE records SET original_parser_version=(
            SELECT parser_version FROM sources WHERE sources.id=records.source_id)
            WHERE original_parser_version IS NULL AND source_id IS NOT NULL""")
        db.execute("PRAGMA user_version=3")


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
    item["is_manual"] = item["source_id"] is None
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
                before = {"current": json.loads(row["current"]), "verified": json.loads(row["verified"]),
                          "state": row["state"], "warnings": old_warnings}
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
                             "candidate_values": values, "auto_updated_fields": updated_fields,
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
                             "parser_version": parser_version}
                    _checked_update(db, "UPDATE records SET state='void',version=version+1,updated_at=? WHERE id=? AND version=?",
                                    (now(), row["id"], row["version"]),
                                    f"紀錄 {row['id']} 在重新解析期間已變更；整批重新解析已回滾。")
                    db.execute("""INSERT INTO changes(record_id,changed_at,actor,reason,before_json,after_json)
                        VALUES(?,?,?,?,?,?)""", (row["id"], now(), "解析器", reason,
                        json.dumps({"current": current, "verified": verified, "state": row["state"],
                                    "warnings": old_warnings}, ensure_ascii=False),
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
                                    "warnings": old_warnings}, ensure_ascii=False),
                        json.dumps({"current": current, "verified": verified, "state": row["state"],
                                    "warnings": warnings, "parser_version": parser_version}, ensure_ascii=False)))
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
        return db.execute("""INSERT INTO records(source_location,source_text,
            original,current,verified,warnings,created_at,updated_at)
            VALUES('人工輸入','','{}',?,'{}','[]',?,?)""",
            (json.dumps(values, ensure_ascii=False), now(), now())).lastrowid


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
