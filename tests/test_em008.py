import ast
import inspect
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from xml.etree.ElementTree import Element, SubElement, tostring
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from unittest.mock import patch

from em_mvp import store
from em_mvp.domain import FIELDS
from em_mvp.app import chart, create_app
from em_mvp.sheet_reconcile import (
    HEADER_ROW, SHEETS, match_word_candidates, parse_api_ranges, parse_xlsx_targets,
    google_authorize_url, missing_from_complete_snapshot, read_google_targets,
    sample_groups, snapshot_digest, summarize,
)


def values(**changes):
    row = [""] * 25
    row[0] = "data"
    row[1] = "B-001"
    row[2:5] = [2026, 6, 3]
    row[5:8] = ["落菌法", "環測", "H-001"]
    row[8:13] = ["王甲", "", "C01", "A", "P01"]
    row[13:17] = ["3", "2", "PA", "raw note"]
    for key, value in changes.items():
        index = {"batch_id": 1, "year": 2, "month": 3, "day": 4, "method": 5,
                 "purpose": 6, "batch_no": 7, "operator_1": 8, "operator_2": 9,
                 "room": 10, "grade": 11, "point_id": 12, "cfu": 13,
                 "colonies": 14, "organism": 20}[key]
        row[index] = value
    return row


def sheet_snapshot(rows, *, complete=True, title="三廠管理者更新"):
    header = list(HEADER_ROW) + [""] * (25 - len(HEADER_ROW))
    return {"rows_by_sheet": {title: [{"site": SHEETS[title]["site"], "row_number": 1, "values": header},
                                       *[{"site": SHEETS[title]["site"], "row_number": index + 2,
                                          "values": row} for index, row in enumerate(rows)]]},
            "complete": complete, "source": "google-api"}


def word_record(**changes):
    current = {field: "" for field in FIELDS}
    current.update(sample_date="2026-06-03", site="三廠", monitoring_type="例行環測",
                   method="落菌法", room="", grade="", point_id="P01", operator="",
                   batch_no="H-001", result_raw="3", result_type="count", cfu_count="3")
    current.update(changes)
    return {"id": 7, "version": 1, "state": "draft", "analysis_included": 1,
            "analysis_exclusion_reason": "", "current": current,
            "original": dict(current), "verified": {}, "source_id": 4,
            "origin_kind": "file", "is_manual": False}


def xlsx_bytes(tabs):
    """Build a minimal XLSX in memory, including formula caches, without temp files."""
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package = "http://schemas.openxmlformats.org/package/2006/relationships"
    types_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    output = io.BytesIO()

    def worksheet_xml(rows):
        root = Element(f"{{{main}}}worksheet")
        data = SubElement(root, f"{{{main}}}sheetData")
        for row_number, row in enumerate(rows, 1):
            row_node = SubElement(data, f"{{{main}}}row", r=str(row_number))
            for index, value in enumerate(row):
                if value is None or value == "":
                    continue
                reference = f"{chr(65 + index)}{row_number}"
                if isinstance(value, tuple):
                    cell = SubElement(row_node, f"{{{main}}}c", r=reference)
                    SubElement(cell, f"{{{main}}}f").text = str(value[0]).lstrip("=")
                    if value[1] is not None:
                        SubElement(cell, f"{{{main}}}v").text = str(value[1])
                elif isinstance(value, (int, float)):
                    cell = SubElement(row_node, f"{{{main}}}c", r=reference)
                    SubElement(cell, f"{{{main}}}v").text = str(value)
                else:
                    cell = SubElement(row_node, f"{{{main}}}c", r=reference, t="inlineStr")
                    SubElement(SubElement(cell, f"{{{main}}}is"), f"{{{main}}}t").text = str(value)
        return tostring(root, encoding="utf-8")

    with zipfile.ZipFile(output, "w") as archive:
        content_types = Element(f"{{{types_ns}}}Types")
        SubElement(content_types, f"{{{types_ns}}}Default", Extension="rels",
                   ContentType="application/vnd.openxmlformats-package.relationships+xml")
        SubElement(content_types, f"{{{types_ns}}}Default", Extension="xml", ContentType="application/xml")
        SubElement(content_types, f"{{{types_ns}}}Override", PartName="/xl/workbook.xml",
                   ContentType=f"{ct}.sheet.main+xml")
        for index in range(1, len(tabs) + 1):
            SubElement(content_types, f"{{{types_ns}}}Override", PartName=f"/xl/worksheets/sheet{index}.xml",
                       ContentType=f"{ct}.worksheet+xml")
        archive.writestr("[Content_Types].xml", tostring(content_types, encoding="utf-8"))
        package_rels = Element(f"{{{package}}}Relationships")
        SubElement(package_rels, f"{{{package}}}Relationship", Id="rId1",
                   Type=f"{rel}/officeDocument", Target="xl/workbook.xml")
        archive.writestr("_rels/.rels", tostring(package_rels, encoding="utf-8"))
        workbook = Element(f"{{{main}}}workbook")
        sheets = SubElement(workbook, f"{{{main}}}sheets")
        workbook_rels = Element(f"{{{package}}}Relationships")
        for index, (title, rows) in enumerate(tabs.items(), 1):
            SubElement(sheets, f"{{{main}}}sheet", name=title, sheetId=str(index),
                       attrib={f"{{{rel}}}id": f"rId{index}"})
            SubElement(workbook_rels, f"{{{package}}}Relationship", Id=f"rId{index}",
                       Type=f"{rel}/worksheet", Target=f"worksheets/sheet{index}.xml")
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet_xml(rows))
        archive.writestr("xl/workbook.xml", tostring(workbook, encoding="utf-8"))
        archive.writestr("xl/_rels/workbook.xml.rels", tostring(workbook_rels, encoding="utf-8"))
    return output.getvalue()


class EM008Tests(unittest.TestCase):
    def test_r1_01_unresolved_same_batch_positive_rows_block_zero_through_api_preview_and_adoption(self):
        initialize_tree = ast.parse(inspect.getsource(store.initialize))
        schema = next(node.args[0].value for node in ast.walk(initialize_tree)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr == "executescript")
        original_write_text, original_read_text = Path.write_text, Path.read_text

        def write_text(path, data, *args, **kwargs):
            return len(data) if path == Path("memory/session.key") else \
                original_write_text(path, data, *args, **kwargs)

        def read_text(path, *args, **kwargs):
            return "synthetic-test-session-key" if path == Path("memory/session.key") else \
                original_read_text(path, *args, **kwargs)

        for missing in ("method", "year"):
            with self.subTest(missing=missing):
                uri = f"file:em008_r1_01_{missing}?mode=memory&cache=shared"
                anchor = sqlite3.connect(uri, uri=True)
                anchor.executescript(schema)

                def memory_connection(*args, **kwargs):
                    db = sqlite3.connect(uri, uri=True)
                    db.row_factory = sqlite3.Row
                    db.execute("PRAGMA foreign_keys=ON")
                    return db

                try:
                    positive = values(cfu="3", colonies="3", organism="Bacillus")
                    positive[{"method": 5, "year": 2}[missing]] = ""
                    evidence = {"source_kind": "google-api", "spreadsheet_id": "synthetic",
                                "completeness_basis": "合成完整快照",
                                "tabs": {title: {"sheet_id": config["sheet_id"]}
                                         for title, config in SHEETS.items()}}
                    snapshot = parse_api_ranges({
                        "三廠管理者更新": [HEADER_ROW, values(cfu="", colonies="0"), positive],
                        "一廠管理者更新": [HEADER_ROW],
                    }, complete=True, evidence=evidence)
                    groups = sample_groups(snapshot)
                    zero, = [group for group in groups if group["identity"]["batch_id"] == "B-001"
                             and any(row["values"][13] == "" and row["values"][14] == "0"
                                     for row in group["rows"])]
                    self.assertEqual(zero["status"], "pending")
                    self.assertIsNone(zero["sample"])
                    related, = zero["related_pending_rows"]
                    self.assertEqual(related["row_number"], 3)
                    self.assertEqual(related["N_total_cfu"], "3")
                    self.assertEqual(related["O_colony_count"], "3")
                    self.assertEqual(related["species_cells_S_Y"][0]["raw_value"], "Bacillus")
                    self.assertIn("Bacillus", zero["reasons"][-1])

                    with patch.object(store, "connection", side_effect=memory_connection), \
                            patch.object(store, "backup", return_value=Path("MEMORY_BACKUP")), \
                            patch.object(store, "initialize"), \
                            patch.object(Path, "write_text", autospec=True, side_effect=write_text), \
                            patch.object(Path, "read_text", autospec=True, side_effect=read_text), \
                            patch("em_mvp.sheet_reconcile.google_oauth_status",
                                  return_value={"configured": False, "authorized": False}):
                        saved = store.add_sheet_snapshot("memory", "synthetic", snapshot_digest(snapshot),
                                                         "google-api", True, snapshot["rows_by_sheet"],
                                                         summarize(snapshot, groups), snapshot["evidence"])
                        client = create_app("memory").test_client()
                        page = client.get(f"/sheet-reconcile?snapshot={saved['id']}")
                        self.assertEqual(page.status_code, 200)
                        self.assertIn("Bacillus", page.get_data(as_text=True))
                        self.assertIn("related_pending_rows", page.get_data(as_text=True))
                        saved_snapshot = store.sheet_snapshot("memory", saved["id"])
                        saved_zero, = [group for group in sample_groups(saved_snapshot)
                                       if group["fingerprint"] == zero["fingerprint"]]
                        self.assertEqual(saved_zero["status"], "pending")
                        with self.assertRaises(store.StaleRecord):
                            store.adopt_sheet_candidate("memory", saved["id"], zero["fingerprint"])
                        with closing(memory_connection()) as db:
                            self.assertEqual(db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 0)
                            self.assertEqual(db.execute("SELECT COUNT(*) FROM sheet_adoptions").fetchone()[0], 0)
                finally:
                    anchor.close()

    def test_r1_01_partial_other_core_fields_stay_separate_and_different_B_is_not_a_zero_blocker(self):
        for missing in ("point_id", "batch_no", "room", "grade"):
            with self.subTest(missing=missing):
                positive = values(cfu="3", colonies="3", organism="Bacillus")
                index = {"point_id": 12, "batch_no": 7, "room": 10, "grade": 11}[missing]
                positive[index] = ""
                groups = sample_groups(sheet_snapshot([values(cfu="", colonies="0"), positive]))
                zero = next(group for group in groups if group["identity"]["batch_id"] == "B-001"
                            and any(row["values"][13] == "" and row["values"][14] == "0"
                                    for row in group["rows"]))
                self.assertEqual(zero["status"], "pending")
                self.assertIsNone(zero["sample"])

        groups = sample_groups(sheet_snapshot([
            values(cfu="", colonies="0"),
            values(batch_id="B-002", cfu="3", colonies="3", organism="Bacillus"),
        ]))
        zero = next(group for group in groups if group["identity"]["batch_id"] == "B-001")
        positive = next(group for group in groups if group["identity"]["batch_id"] == "B-002")
        self.assertEqual(zero["status"], "new")
        self.assertEqual(zero["sample"]["cfu_count"], "0")
        self.assertEqual(positive["status"], "new")
        self.assertEqual(positive["sample"]["cfu_count"], "3")

    def test_qa01_groups_unmapped_purpose_rows_before_assessing_positive_evidence(self):
        rows = [values(cfu="", colonies="0"),
                values(purpose="IC", cfu="3", colonies="3", organism="Bacillus")]
        group, = sample_groups(sheet_snapshot(rows))
        reverse, = sample_groups(sheet_snapshot(list(reversed(rows))))
        self.assertEqual(group["fingerprint"], reverse["fingerprint"])
        self.assertEqual(len(group["rows"]), 2)
        self.assertEqual(group["status"], "pending")
        self.assertEqual(group["metric_evidence"]["N"], ["", "3"])
        self.assertEqual(group["metric_evidence"]["O"], ["0", "3"])
        self.assertEqual(group["species_rows"], 1)

    def test_qa02_word_nonblank_result_and_monitoring_conflicts_block_supplement(self):
        group, = sample_groups(sheet_snapshot([values()]))
        current = word_record(monitoring_type="污染後環測", result_raw="0", cfu_count="0")["current"]
        result, = match_word_candidates([group], [{**word_record(), "current": current}])
        self.assertEqual(result["status"], "conflict")
        self.assertIn("monitoring_type", result["reasons"][0])
        self.assertIn("cfu_count", result["reasons"][0])
        self.assertNotIn("suggested_fills", result)

    def test_qa03_adopted_record_surfaces_changed_source_result(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            original = sheet_snapshot([values(cfu="0", colonies="0")])
            saved = store.add_sheet_snapshot(path, "first.xlsx", snapshot_digest(original), "xlsx", True,
                                             original["rows_by_sheet"], {})
            first, = sample_groups(original)
            record_id = store.adopt_sheet_candidate(path, saved["id"], first["fingerprint"])["record_id"]
            changed = sheet_snapshot([values(cfu="9", colonies="9")])
            newest = store.add_sheet_snapshot(path, "updated.xlsx", snapshot_digest(changed), "xlsx", True,
                                              changed["rows_by_sheet"], {})
            group, = sample_groups(store.sheet_snapshot(path, newest["id"]))
            match_word_candidates([group], store.records(path), store.sheet_adoptions(path))
            self.assertEqual(group["status"], "conflict")
            self.assertIn("cfu_count", group["reasons"][0])
            self.assertEqual(store.get(path, record_id)["current"]["cfu_count"], "0")

    def test_qa04_adopted_sheet_batch_identity_allows_distinct_B_repeats(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            snapshot = sheet_snapshot([values(), values(batch_id="B-002")])
            saved = store.add_sheet_snapshot(path, "repeat.xlsx", snapshot_digest(snapshot), "xlsx", True,
                                             snapshot["rows_by_sheet"], {})
            first, second = sample_groups(snapshot)
            adopted_first = store.adopt_sheet_candidate(path, saved["id"], first["fingerprint"])
            adopted_second = store.adopt_sheet_candidate(path, saved["id"], second["fingerprint"])
            self.assertNotEqual(adopted_first["record_id"], adopted_second["record_id"])
            self.assertEqual(len(store.records(path)), 2)
            again = sheet_snapshot([values(batch_id="B-002")])
            read = store.add_sheet_snapshot(path, "b002.xlsx", snapshot_digest(again), "xlsx", True,
                                            again["rows_by_sheet"], {})
            group, = sample_groups(store.sheet_snapshot(path, read["id"]))
            match_word_candidates([group], store.records(path), store.sheet_adoptions(path))
            self.assertEqual(group["status"], "already_adopted")
            self.assertEqual(group["record_id"], adopted_second["record_id"])

    def test_qa05_old_snapshot_cannot_adopt_or_supplement_after_new_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            word = word_record(room="", grade="", result_raw="", result_type="", cfu_count="")["current"]
            store.add_import(path, "word.docx", b"word", [{
                "values": word, "source_location": "table1-row2", "source_text": "synthetic", "warnings": [],
            }], "test-parser")
            word_row = store.records(path)[0]
            first = sheet_snapshot([values()])
            old = store.add_sheet_snapshot(path, "old.xlsx", snapshot_digest(first), "xlsx", True,
                                           first["rows_by_sheet"], {})
            newer = sheet_snapshot([values(cfu="9", colonies="9")])
            store.add_sheet_snapshot(path, "new.xlsx", snapshot_digest(newer), "xlsx", True,
                                     newer["rows_by_sheet"], {})
            group, = sample_groups(first)
            page = create_app(path).test_client().get(f"/sheet-reconcile?snapshot={old['id']}").get_data(as_text=True)
            self.assertIn("已有較新的 Sheet 讀取", page)
            self.assertNotIn("一次採用全部安全空欄補值", page)
            before_backups = sorted(item.name for item in (path / "backups").iterdir())
            with self.assertRaises(store.StaleRecord):
                store.adopt_sheet_candidate(path, old["id"], group["fingerprint"])
            with self.assertRaises(store.StaleRecord):
                store.apply_sheet_supplements(path, old["id"], [{
                    "fingerprint": group["fingerprint"], "record_id": word_row["id"], "version": word_row["version"],
                }])
            self.assertEqual(store.get(path, word_row["id"])["current"], word)
            self.assertEqual(store.history(path, word_row["id"]), [])
            self.assertEqual(sorted(item.name for item in (path / "backups").iterdir()), before_backups)

    def test_qa06_swapped_total_and_colony_headers_are_rejected_by_both_adapters(self):
        header = list(HEADER_ROW)
        header[13], header[14] = header[14], header[13]
        with self.assertRaisesRegex(ValueError, "標題列"):
            parse_api_ranges({title: [header] for title in SHEETS}, complete=True)
        with self.assertRaisesRegex(ValueError, "標題列"):
            parse_xlsx_targets(xlsx_bytes({title: [header] for title in SHEETS}), complete=True)
        wrong_species = list(HEADER_ROW)
        wrong_species[20], wrong_species[21] = wrong_species[21], wrong_species[20]
        with self.assertRaisesRegex(ValueError, "標題列"):
            parse_api_ranges({title: [wrong_species] for title in SHEETS}, complete=True)

    def test_qa07_chart_and_monthly_routes_render_adjacent_months(self):
        svg = str(chart(["2026-06", "2026-07"], [3, 4], "QA"))
        self.assertIn("<svg", svg)
        self.assertIn("stroke=\"#167a8c\"", svg)
        records = []
        for index, day in enumerate(("2026-06-03", "2026-07-03"), 1):
            row = word_record(sample_date=day, grade="A")
            row.update(id=index, state="confirmed")
            records.append(row)
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder)
            client = app.test_client()
            with patch("em_mvp.app.store.records", return_value=records):
                self.assertEqual(client.get("/reports?start=2026-06&end=2026-07").status_code, 200)
                self.assertEqual(client.get("/report.html?start=2026-06&end=2026-07").status_code, 200)

    def test_qa08_conflicting_purposes_stay_one_pending_group_in_any_row_order(self):
        rows = [values(cfu="3", colonies="1", organism="A"),
                values(purpose="汙染後環測", cfu="", colonies="1", organism="B")]
        forward, = sample_groups(sheet_snapshot(rows))
        backward, = sample_groups(sheet_snapshot(list(reversed(rows))))
        self.assertEqual(forward["fingerprint"], backward["fingerprint"])
        self.assertEqual(len(forward["rows"]), len(backward["rows"]))
        self.assertEqual(forward["status"], backward["status"])
        self.assertEqual(forward["status"], "pending")
        self.assertTrue(any("G 目的" in reason for reason in forward["reasons"]))
        self.assertEqual(sorted(forward["metric_evidence"]["N"]), sorted(backward["metric_evidence"]["N"]))

    def test_qa09_xlsx_formula_uses_cached_value_and_missing_cache_stays_pending(self):
        data = values(cfu=("SUM(1,2)", 3), colonies=("0", 0))
        parsed = parse_xlsx_targets(xlsx_bytes({
            "三廠管理者更新": [HEADER_ROW, data], "一廠管理者更新": [HEADER_ROW],
        }), complete=True)
        xlsx_group, = sample_groups(parsed)
        api_rows = {title: [HEADER_ROW, values(cfu="3", colonies="0")] if title == "三廠管理者更新"
                    else [HEADER_ROW] for title in SHEETS}
        api_group, = sample_groups(parse_api_ranges(api_rows, complete=True))
        self.assertEqual(xlsx_group["sample"]["cfu_count"], api_group["sample"]["cfu_count"])
        self.assertEqual(xlsx_group["rows"][0]["formula_cells"]["N"]["cached_value"], "3")
        no_cache = values(cfu="", colonies=("0", None))
        missing_snapshot = parse_xlsx_targets(xlsx_bytes({
            "三廠管理者更新": [HEADER_ROW, no_cache], "一廠管理者更新": [HEADER_ROW],
        }), complete=True)
        missing, = sample_groups(missing_snapshot)
        self.assertEqual(missing["status"], "pending")
        self.assertIn("公式缺少快取", missing["reasons"][0])
        self.assertIsNone(missing["sample"])

    def test_qa10_duplicate_content_keeps_each_read_completeness_and_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            source_rows = [HEADER_ROW, values(cfu="", colonies="0")]
            snapshot = parse_xlsx_targets(xlsx_bytes({
                "三廠管理者更新": source_rows, "一廠管理者更新": [HEADER_ROW],
            }), complete=False)
            api = parse_api_ranges({title: source_rows if title == "三廠管理者更新" else [HEADER_ROW]
                                    for title in SHEETS}, complete=True, evidence={
                                        "spreadsheet_id": "synthetic-sheet",
                                        "completeness_basis": "mock 完整唯讀 API",
                                        "tabs": {title: {"sheet_id": SHEETS[title]["sheet_id"], "range": "A1:Y2"}
                                                 for title in SHEETS},
                                    })
            digest = snapshot_digest(snapshot)
            self.assertEqual(snapshot_digest(api), digest)
            first = store.add_sheet_snapshot(path, "partial.xlsx", digest, "xlsx", False,
                                             snapshot["rows_by_sheet"], {}, snapshot["evidence"] | {
                                                 "completeness_basis": "使用者未確認完整",
                                             })
            second = store.add_sheet_snapshot(path, "complete-api", digest, "google-api", True,
                                              api["rows_by_sheet"], {}, api["evidence"])
            old_read, new_read = store.sheet_snapshot(path, first["id"]), store.sheet_snapshot(path, second["id"])
            self.assertTrue(second["duplicate"])
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(first["content_id"], second["content_id"])
            self.assertFalse(old_read["complete"])
            self.assertTrue(new_read["complete"])
            self.assertEqual(new_read["source_kind"], "google-api")
            self.assertEqual(new_read["evidence"]["spreadsheet_id"], "synthetic-sheet")
            group, = sample_groups(new_read)
            self.assertEqual(group["sample"]["cfu_count"], "0")
            self.assertEqual(group["rows"][0]["sheet_id"], SHEETS["三廠管理者更新"]["sheet_id"])
            legacy = path / "legacy"
            legacy.mkdir()
            rows_json = json.dumps(snapshot["rows_by_sheet"], ensure_ascii=False)
            db = sqlite3.connect(legacy / "em.sqlite3")
            try:
                db.execute("""CREATE TABLE sheet_snapshots(
                    id INTEGER PRIMARY KEY,source_name TEXT NOT NULL,sha256 TEXT NOT NULL UNIQUE,
                    source_kind TEXT NOT NULL,complete INTEGER NOT NULL,created_at TEXT NOT NULL,
                    rows_json TEXT NOT NULL,summary_json TEXT NOT NULL)""")
                db.execute("""INSERT INTO sheet_snapshots VALUES(1,'legacy.xlsx',?, 'xlsx',1,
                    '2026-01-01T00:00:00+00:00',?,'{}')""", (digest, rows_json))
                db.commit()
            finally:
                db.close()
            store.initialize(legacy)
            migrated = store.sheet_snapshot(legacy, store.sheet_snapshots(legacy)[0]["id"])
            self.assertEqual(migrated["evidence"]["source_kind"], "legacy")
            db = sqlite3.connect(legacy / "em.sqlite3")
            try:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 6)
            finally:
                db.close()

    def test_qa11_incomplete_current_read_does_not_report_removed_samples(self):
        earlier = sheet_snapshot([values()], complete=True)
        self.assertEqual(missing_from_complete_snapshot(sample_groups(sheet_snapshot([], complete=False)),
                                                        earlier, current_complete=False), [])
        old = {**earlier, "id": 1, "source_name": "older.xlsx", "sha256": "a" * 64,
               "source_kind": "xlsx", "created_at": "older"}
        current = {**sheet_snapshot([], complete=False), "id": 2, "source_name": "partial.xlsx",
                   "sha256": "b" * 64, "source_kind": "xlsx", "created_at": "current"}
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(folder).test_client()
            with patch("em_mvp.app.store.sheet_snapshots", return_value=[current, old]), \
                    patch("em_mvp.app.store.sheet_snapshot", side_effect=lambda _path, sid: {1: old, 2: current}[sid]), \
                    patch("em_mvp.app.store.records", return_value=[]), \
                    patch("em_mvp.app.store.sheet_adoptions", return_value={}), \
                    patch("em_mvp.app.sheet_reconcile.google_oauth_status",
                          return_value={"configured": False, "authorized": False}):
                html = client.get("/sheet-reconcile?snapshot=2").get_data(as_text=True)
        self.assertIn("完整性未確認", html)
        self.assertNotIn("較早完整快照未再出現 1", html)

    def test_qa12_empty_supplement_submission_is_clear_and_has_no_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            client = create_app(folder).test_client()
            client.get("/")
            with client.session_transaction() as session:
                csrf = session["csrf"]
            before = list((Path(folder) / "backups").iterdir())
            response = client.post("/sheet-reconcile/supplement", data={"csrf": csrf, "snapshot_id": "1"})
            self.assertEqual(response.status_code, 302)
            page = client.get(response.headers["Location"]).get_data(as_text=True)
            self.assertIn("尚未選取補值候選", page)
            self.assertEqual(list((Path(folder) / "backups").iterdir()), before)

    def test_xlsx_reads_only_two_named_target_sheets(self):
        parsed = parse_xlsx_targets(xlsx_bytes({
            "三廠管理者更新": [HEADER_ROW, values()],
            "一廠管理者更新": [HEADER_ROW], "其他分頁": [["DO NOT READ"]],
        }), complete=True)
        self.assertEqual(set(parsed["rows_by_sheet"]), set(SHEETS))
        self.assertEqual(parsed["rows_by_sheet"]["三廠管理者更新"][1]["values"][1], "B-001")
        self.assertFalse(any("DO NOT READ" in row["values"] for rows in parsed["rows_by_sheet"].values() for row in rows))

    def test_api_adapter_is_restricted_to_exact_tabs(self):
        payload = {title: [HEADER_ROW, values()] if title == "三廠管理者更新" else [HEADER_ROW]
                   for title in SHEETS}
        parsed = parse_api_ranges(payload, complete=True)
        self.assertEqual(set(parsed["rows_by_sheet"]), set(SHEETS))
        with self.assertRaises(ValueError):
            parse_api_ranges({**payload, "其他分頁": []}, complete=True)

    def test_google_reader_requests_metadata_then_values_for_only_two_target_tabs(self):
        calls = []

        def response(url, token):
            calls.append(url)
            if "/values/" not in url:
                return {"sheets": [{"properties": {"sheetId": SHEETS[title]["sheet_id"],
                            "title": title, "gridProperties": {"rowCount": 2, "columnCount": 25}}}
                        for title in SHEETS]}
            title = "三廠管理者更新" if "%E4%B8%89%E5%BB%A0" in url or "三廠" in url else "一廠管理者更新"
            return {"values": [HEADER_ROW, values()]} if title == "三廠管理者更新" else {"values": [HEADER_ROW]}

        with patch("em_mvp.sheet_reconcile._google_access_token", return_value="token"), \
                patch("em_mvp.sheet_reconcile._google_get", side_effect=response):
            parsed = read_google_targets(".")
        self.assertTrue(parsed["complete"])
        self.assertEqual(parsed["evidence"]["spreadsheet_id"], "1Bh1uNUIVBSQ2IuY2M5o_CDuLfqlPBsH35S_nyHg8XX8")
        self.assertEqual(parsed["rows_by_sheet"]["三廠管理者更新"][0]["sheet_id"], SHEETS["三廠管理者更新"]["sheet_id"])
        value_urls = [url for url in calls if "/values/" in url]
        self.assertEqual(len(value_urls), 2)
        self.assertTrue(all("A1%3AY2" in url or "A1:Y2" in url for url in value_urls))
        self.assertTrue(all(any(title in unquote(url) for title in SHEETS) for url in value_urls))
        self.assertFalse(any("其他分頁" in unquote(url) for url in calls))

    def test_oauth_authorization_uses_readonly_scope_only(self):
        with patch.dict("os.environ", {"EM_MVP_GOOGLE_CLIENT_ID": "client-id",
                                        "EM_MVP_GOOGLE_CLIENT_SECRET": "client-secret"}):
            url = google_authorize_url("http://127.0.0.1:8765/sheet-reconcile/oauth/callback", "state-value")
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["scope"], ["https://www.googleapis.com/auth/spreadsheets.readonly"])
        self.assertEqual(query["state"], ["state-value"])
        self.assertEqual(query["access_type"], ["offline"])

    def test_species_rows_count_once_and_keep_source_children(self):
        first = values(organism="Bacillus atrophaeus")
        second = values(organism="Micrococcus luteus")
        group, = sample_groups(sheet_snapshot([first, second]))
        self.assertEqual(group["sample"]["cfu_count"], "3")
        self.assertEqual(group["identity"]["batch_id"], "B-001")
        self.assertEqual(group["species_rows"], 2)
        self.assertEqual(len(group["rows"]), 2)
        self.assertEqual(group["sample"]["monitoring_type"], "例行環測")

    def test_zero_requires_complete_snapshot_o_zero_and_no_species_evidence(self):
        row = values(cfu="", colonies="0")
        complete, = sample_groups(sheet_snapshot([row], complete=True))
        self.assertEqual(complete["sample"]["cfu_count"], "0")
        self.assertIn("N 原空白", complete["zero_inference"])
        incomplete, = sample_groups(sheet_snapshot([row], complete=False))
        self.assertIsNone(incomplete["sample"])
        self.assertIn("完整快照", incomplete["reasons"][0])
        positive_colonies, = sample_groups(sheet_snapshot([values(cfu="", colonies="2")]))
        self.assertIsNone(positive_colonies["sample"])
        child_row, = sample_groups(sheet_snapshot([values(cfu="", colonies="0", organism="Bacillus")]))
        self.assertIsNone(child_row["sample"])
        explicit_zero_conflict, = sample_groups(sheet_snapshot([values(cfu="0", colonies="1")]))
        self.assertIsNone(explicit_zero_conflict["sample"])
        for raw in ("TNTC", "<1"):
            unknown_result, = sample_groups(sheet_snapshot([values(cfu=raw, colonies="0")]))
            self.assertIsNone(unknown_result["sample"])
            self.assertTrue(unknown_result["reasons"])
        unknown_purpose, = sample_groups(sheet_snapshot([values(purpose="IC")]))
        self.assertIsNone(unknown_purpose["sample"])
        self.assertIn("未有明確", unknown_purpose["reasons"][0])

    def test_distinct_B_repeats_and_reused_B_never_merge(self):
        distinct = sample_groups(sheet_snapshot([values(), values(batch_id="B-002")]))
        self.assertEqual(len(distinct), 2)
        self.assertTrue(all(group["status"] == "new" for group in distinct))
        repeated_word = match_word_candidates(distinct, [word_record()])
        self.assertTrue(all(group["status"] == "pending" for group in repeated_word))
        self.assertTrue(all("不同 B" in group["reasons"][-1] for group in repeated_word))
        reused = sample_groups(sheet_snapshot([values(), values(day=4)]))
        self.assertEqual(len(reused), 2)
        self.assertTrue(all(any("相同 B" in reason for reason in group["reasons"]) for group in reused))
        blank_batch, = sample_groups(sheet_snapshot([values(batch_id="")]))
        self.assertIn("B 批次", blank_batch["reasons"][0])

    def test_row_reordering_and_api_xlsx_share_sample_fingerprint_not_snapshot_digest(self):
        rows = [values(), values(organism="Bacillus")]
        first = sheet_snapshot(rows)
        reordered = sheet_snapshot(list(reversed(rows)))
        self.assertNotEqual(snapshot_digest(first), snapshot_digest(reordered))
        self.assertEqual([g["fingerprint"] for g in sample_groups(first)],
                         [g["fingerprint"] for g in sample_groups(reordered)])
        api = parse_api_ranges({title: [HEADER_ROW, *rows] if title == "三廠管理者更新" else [HEADER_ROW]
                                for title in SHEETS}, complete=True)
        xlsx = sheet_snapshot(rows)
        self.assertEqual(sample_groups(api)[0]["fingerprint"], sample_groups(xlsx)[0]["fingerprint"])

    def test_word_match_only_unique_and_suggests_blank_fields(self):
        group, = sample_groups(sheet_snapshot([values()]))
        result, = match_word_candidates([group], [word_record()])
        self.assertEqual(result["status"], "supplement")
        self.assertEqual(result["word_record_id"], 7)
        self.assertEqual(result["suggested_fills"]["room"], "C01")
        self.assertNotIn("result_raw", result["suggested_fills"])
        duplicate_group, = sample_groups(sheet_snapshot([values()]))
        duplicate, = match_word_candidates([duplicate_group], [word_record(), {**word_record(), "id": 8}])
        self.assertEqual(duplicate["status"], "pending")
        batch_group, = sample_groups(sheet_snapshot([values()]))
        other_batch = word_record(batch_no="H-002")
        other_batch["id"] = 8
        unique_batch, = match_word_candidates([batch_group], [word_record(), other_batch])
        self.assertEqual(unique_batch["status"], "supplement")
        self.assertEqual(unique_batch["word_record_id"], 7)
        conflict_group, = sample_groups(sheet_snapshot([values()]))
        conflict, = match_word_candidates([conflict_group], [word_record(site="一廠")])
        self.assertEqual(conflict["status"], "conflict")

    def test_snapshot_dedup_and_version_protected_supplement_preserve_review_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            values_word = word_record()["current"]
            parsed_word = [{"values": values_word, "source_location": "Word table 1 row 2",
                            "source_text": "raw Word source", "warnings": []}]
            store.add_import(path, "word.docx", b"word", parsed_word, "0.1.7")
            record = store.records(path)[0]
            store.update(path, record["id"], record["version"], values_word,
                         {"result_raw": "checked"}, "confirmed", "來源逐欄核對")
            record = store.get(path, record["id"])
            store.set_analysis_inclusion(path, record["id"], record["version"], False, "來源待補")
            record = store.get(path, record["id"])
            snapshot = sheet_snapshot([values()])
            digest = snapshot_digest(snapshot)
            saved = store.add_sheet_snapshot(path, "manager.xlsx", digest, "xlsx", True,
                                             snapshot["rows_by_sheet"], summarize(snapshot, sample_groups(snapshot)))
            again = store.add_sheet_snapshot(path, "renamed.xlsx", digest, "xlsx", True,
                                             snapshot["rows_by_sheet"], {})
            self.assertFalse(saved["duplicate"])
            self.assertTrue(again["duplicate"])
            group, = sample_groups(snapshot)
            selection = [{"fingerprint": group["fingerprint"], "record_id": record["id"],
                          "version": record["version"]}]
            applied = store.apply_sheet_supplements(path, again["id"], selection)
            updated = store.get(path, record["id"])
            self.assertGreater(applied["fields"], 0)
            self.assertEqual(updated["state"], "confirmed")
            self.assertEqual(updated["analysis_included"], 0)
            self.assertEqual(updated["analysis_exclusion_reason"], "來源待補")
            self.assertEqual(updated["verified"]["result_raw"], "checked")
            self.assertEqual(updated["current"]["room"], "C01")
            self.assertEqual(json.loads(store.history(path, record["id"])[0]["after_json"])["sheet_evidence"]["sha256"], digest)
            with self.assertRaises(store.StaleRecord):
                store.apply_sheet_supplements(path, saved["id"], selection)
            self.assertEqual(len(store.history(path, record["id"])), 3)

    def test_supplement_does_not_restore_a_manually_cleared_blank(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            values_word = word_record()["current"]
            parsed_word = [{"values": values_word, "source_location": "Word table 1 row 2",
                            "source_text": "raw Word source", "warnings": []}]
            store.add_import(path, "word.docx", b"word", parsed_word, "0.1.7")
            record = store.records(path)[0]
            edited = dict(values_word, room="C02")
            store.update(path, record["id"], record["version"], edited, {}, "draft", "先補房間")
            record = store.get(path, record["id"])
            cleared = dict(record["current"], room="")
            store.update(path, record["id"], record["version"], cleared, {}, record["state"], "人工清空欄位")
            record = store.get(path, record["id"])
            snapshot = sheet_snapshot([values()])
            saved = store.add_sheet_snapshot(path, "manager.xlsx", snapshot_digest(snapshot), "xlsx", True,
                                             snapshot["rows_by_sheet"], {})
            group, = sample_groups(snapshot)
            result = store.apply_sheet_supplements(path, saved["id"], [{
                "fingerprint": group["fingerprint"], "record_id": record["id"], "version": record["version"],
            }])
            updated = store.get(path, record["id"])
            self.assertGreater(result["fields"], 0)
            self.assertEqual(updated["current"]["room"], "")
            self.assertEqual(updated["original"]["room"], "")

    def test_alternate_snapshot_row_order_does_not_duplicate_adopted_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            rows = [values(organism="Bacillus"), values(organism="Micrococcus")]
            first = sheet_snapshot(rows)
            second = sheet_snapshot(list(reversed(rows)))
            first_saved = store.add_sheet_snapshot(path, "manager.xlsx", snapshot_digest(first), "xlsx", True,
                                                   first["rows_by_sheet"], {})
            group, = sample_groups(first)
            store.adopt_sheet_candidate(path, first_saved["id"], group["fingerprint"])
            second_saved = store.add_sheet_snapshot(path, "manager-reordered.xlsx", snapshot_digest(second), "xlsx", True,
                                                    second["rows_by_sheet"], {})
            group2, = sample_groups(second)
            rows_now = store.records(path)
            match_word_candidates([group2], rows_now, store.sheet_adoptions(path))
            self.assertEqual(group2["status"], "already_adopted")
            self.assertEqual(len(store.records(path)), 1)
            with self.assertRaises(store.StaleRecord):
                store.adopt_sheet_candidate(path, second_saved["id"], group2["fingerprint"])

    def test_missing_from_later_complete_snapshot_is_notice_only(self):
        earlier = sheet_snapshot([values()], complete=True)
        current_empty = sheet_snapshot([], complete=True)
        missing = missing_from_complete_snapshot(sample_groups(current_empty), earlier, current_complete=True)
        self.assertEqual(len(missing), 1)
        self.assertIn("不作廢或刪除", missing[0]["reasons"][0])
        incomplete = sheet_snapshot([values()], complete=False)
        self.assertEqual(missing_from_complete_snapshot([], incomplete), [])
        blank_batch = sheet_snapshot([values(batch_id="")], complete=True)
        self.assertEqual(missing_from_complete_snapshot([], blank_batch), [])

    def test_new_candidate_is_single_draft_and_repeated_snapshot_cannot_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            snapshot = sheet_snapshot([values()], complete=True)
            digest = snapshot_digest(snapshot)
            saved = store.add_sheet_snapshot(path, "manager.xlsx", digest, "xlsx", True,
                                             snapshot["rows_by_sheet"], {})
            group, = sample_groups(snapshot)
            adopted = store.adopt_sheet_candidate(path, saved["id"], group["fingerprint"])
            row = store.get(path, adopted["record_id"])
            self.assertEqual(row["state"], "draft")
            self.assertEqual(row["origin_kind"], "sheet")
            self.assertFalse(row["is_manual"])
            self.assertEqual(row["current"]["cfu_count"], "3")
            self.assertIn(digest, row["source_text"])
            evidence = json.loads(row["source_text"])
            self.assertEqual(evidence["field_sources"]["cfu_count"]["cells"][0]["cell"], "N2")
            self.assertEqual(evidence["field_sources"]["monitoring_type"]["cells"][0]["cell"], "G2")
            with self.assertRaises(store.StaleRecord):
                store.adopt_sheet_candidate(path, saved["id"], group["fingerprint"])
            self.assertEqual(len(store.records(path)), 1)

    def test_local_upload_preview_and_explicit_draft_adoption(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            app = create_app(path)
            client = app.test_client()
            client.get("/")
            with client.session_transaction() as session:
                csrf = session["csrf"]
            output = xlsx_bytes({
                "三廠管理者更新": [HEADER_ROW, values()],
                "一廠管理者更新": [HEADER_ROW], "不讀取的分頁": [["private other tab"]],
            })
            response = client.post("/sheet-reconcile/upload", data={
                "csrf": csrf, "complete_snapshot": "yes",
                "xlsx": (io.BytesIO(output), "manager.xlsx"),
            }, content_type="multipart/form-data")
            self.assertEqual(response.status_code, 302)
            page = client.get(response.headers["Location"])
            html = page.get_data(as_text=True)
            self.assertIn("新 draft 候選", html)
            self.assertNotIn("private other tab", html)
            snapshots = store.sheet_snapshots(path)
            snapshot = store.sheet_snapshot(path, snapshots[0]["id"])
            self.assertEqual(set(snapshot["rows_by_sheet"]), set(SHEETS))
            group, = sample_groups(snapshot)
            adopted = client.post("/sheet-reconcile/adopt", data={
                "csrf": csrf, "snapshot_id": snapshot["id"], "fingerprint": group["fingerprint"],
            })
            self.assertEqual(adopted.status_code, 302)
            self.assertEqual(len(store.records(path)), 1)
            self.assertEqual(store.records(path)[0]["state"], "draft")


if __name__ == "__main__":
    unittest.main()
