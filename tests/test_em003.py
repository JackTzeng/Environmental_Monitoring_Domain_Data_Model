import csv
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from em_mvp import store
from em_mvp.domain import FIELDS
from em_mvp.importers import PARSER_VERSION, parse_file
from tests.test_importers import word_file


class EM003ParserTests(unittest.TestCase):
    def test_checked_methods_and_explicit_room_points(self):
        data = word_file([
            ["監測位置", "結果(CFU)"],
            ["C11_BSC01-1", "0"],
            ["C11_GTP1：P06(上)", "1"],
            ["C19F_GTP1-6-入口走道：P03(下)", "2"],
        ], ["監測日期：2026-06-03", "監測方式：▓落菌法 □培養皿接觸"])
        records = parse_file("三廠-20260603.docx", data)
        values = [row["values"] for row in records]
        self.assertEqual({row["method"] for row in values}, {"落菌法"})
        self.assertEqual([(row["room"], row["point_id"]) for row in values], [
            ("C11", "BSC01-1"), ("C11", "P06(上)"), ("C19F", "P03(下)"),
        ])

    def test_scoped_mapping_only_fills_exact_2026_three_factory_points(self):
        data = word_file([
            ["監測位置", "結果(CFU)"],
            ["GTP7：BSC07-01-1", "0"],
            ["GTP7：BSC07-99-1", "0"],
        ], ["監測日期：2026-06-03", "監測方式：▓落菌法 □培養皿接觸"])
        exact_record, unknown_record = parse_file("三廠-20260603.docx", data)
        exact, unknown = exact_record["values"], unknown_record["values"]
        self.assertEqual((exact["room"], exact["point_id"]), ("C17", "BSC07-01-1"))
        self.assertTrue(any("第 41–50、52–56 列" in warning for warning in exact_record["warnings"]))
        self.assertEqual(unknown["room"], "")
        out_of_scope = parse_file("report.docx", data, {"site": "一廠"})
        self.assertEqual(out_of_scope[0]["values"]["room"], "")
        other_year = word_file([["監測位置", "結果(CFU)"], ["GTP7：BSC07-01-1", "0"]],
                               ["監測日期：2025-06-03", "監測方式：▓落菌法 □培養皿接觸"])
        self.assertEqual(parse_file("三廠-20250603.docx", other_year)[0]["values"]["room"], "")
        other_method = word_file([["監測位置", "結果(CFU)"], ["GTP7：BSC07-01-1", "0"]],
                                 ["監測日期：2026-06-03", "監測方式：□落菌法 ▓培養皿接觸"])
        self.assertEqual(parse_file("三廠-20260603.docx", other_method)[0]["values"]["room"], "")

    def test_explicit_room_wins_and_gpt_bsc_prefix_conflict_waits_for_review(self):
        data = word_file([
            ["監測位置", "房間", "結果(CFU)"],
            ["GTP7：BSC07-01-1", "C99", "0"],
            ["GTP8：BSC07-01-1", "", "0"],
        ], ["監測日期：2026-06-03", "監測方式：▓落菌法 □培養皿接觸"])
        source_room, prefix_mismatch = parse_file("三廠-20260603.docx", data)
        self.assertEqual((source_room["values"]["room"], source_room["values"]["point_id"]),
                         ("C99", "BSC07-01-1"))
        self.assertTrue(any("來源明確填寫 C99" in warning and "保留來源值" in warning
                            for warning in source_room["warnings"]))
        self.assertEqual(prefix_mismatch["values"]["room"], "")
        self.assertEqual(prefix_mismatch["values"]["point_id"], "GTP8：BSC07-01-1")
        self.assertTrue(any("GTP8 與 BSC07 點位前綴不一致" in warning
                            for warning in prefix_mismatch["warnings"]))

    def test_cleanroom_selection_source_context_standard_and_tail_rows(self):
        data = word_file([
            ["監測位置", "Grade", "標準(CFU)", "結果(CFU)", "判定"],
            ["胸前", "C", "≤ 5", "", "□合格 □不合格"],
            ["Negative control", "NA", "0", "0", "■合格 □不合格"],
            ["-以下空白-", "", "", "", ""],
            ["", "", "", "", "□合格 □不合格"],
        ], ["類型：□製程監測 □人員監測 ▓無塵衣月監測 □無塵衣季監測",
            "監測方式：□落菌法 ▓培養皿接觸 □培養皿指壓", "批次編碼：BATCH",
            "監測日期：2026-06-03"])
        records = parse_file("無塵衣報告.docx", data, {"site": "三廠"})
        self.assertEqual(len(records), 2)
        sample, control = [row["values"] for row in records]
        self.assertEqual(sample["monitoring_type"], "無塵衣月監測")
        self.assertEqual(sample["method"], "培養皿接觸法")
        self.assertEqual(sample["batch_no"], "BATCH")
        self.assertEqual(sample["site"], "三廠")
        self.assertEqual((sample["room"], sample["operator"], sample["organism_name"]), ("", "", ""))
        self.assertEqual(sample["result_type"], "missing")
        self.assertEqual((sample["alert_raw"], sample["action_raw"]), ("", ""))
        self.assertTrue(any("標準(CFU)=≤ 5" in warning for warning in records[0]["warnings"]))
        self.assertTrue(any("依匯入資料夾脈絡補為 三廠" in warning for warning in records[0]["warnings"]))
        self.assertEqual(control["room"], "")

    def test_ambiguous_checkbox_is_not_guessed(self):
        data = word_file([["監測位置", "結果(CFU)"], ["P01", "0"]],
                         ["監測方式：▓落菌法 ▓培養皿接觸"])
        record = parse_file("report.docx", data)[0]
        self.assertEqual(record["values"]["method"], "")
        self.assertTrue(any("勾選數量為 2" in warning for warning in record["warnings"]))

    def test_explicit_factory_wins_over_conflicting_folder_context(self):
        data = word_file([["監測位置", "結果(CFU)"], ["P01", "0"]], ["監測日期：2026-06-03"])
        record = parse_file("一廠報告.docx", data, {"site": "三廠"})[0]
        self.assertEqual(record["values"]["site"], "一廠")
        self.assertTrue(any("與匯入資料夾脈絡 三廠 不同" in warning for warning in record["warnings"]))


class EM003ReparseTests(unittest.TestCase):
    def candidate(self, location, point, room, result="0"):
        values = {field: "" for field in FIELDS}
        values.update({"sample_date": "2026-06-03", "site": "三廠", "monitoring_type": "例行環測",
                       "method": "落菌法", "point_id": point, "room": room,
                       "result_raw": result, "result_type": "count", "cfu_count": result,
                       "unit": "CFU"})
        return {"values": values, "source_location": location, "source_text": point + " | " + result,
                "warnings": []}

    def test_reparse_preserves_original_manual_review_and_stale_form(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store.initialize(root)
            content = b"unchanged source bytes"
            location = "report.docx / Word table 1 row 2"
            old = self.candidate(location, "C11_BSC01-1", "")
            # The older parser retained the combined point and missed its room.
            store.add_import(root, "report.docx", content, [old], "0.1.0", {"site": "三廠"})
            record = store.records(root)[0]
            original = record["original"]
            edited = dict(record["current"])
            edited["operator"] = "synthetic-operator"
            verified = {"operator": "checked"}
            store.update(root, record["id"], record["version"], edited, verified, "draft", "人工核對結果")
            edited_record = store.get(root, record["id"])
            stale_version = edited_record["version"]

            result = store.reparse_source(root, 1, content,
                [self.candidate(location, "BSC01-1", "C11")], "0.1.2")
            after = store.get(root, record["id"])
            self.assertEqual(result["updated"], 1)
            self.assertTrue((root / "backups" / result["backup"]).is_file())
            self.assertEqual(after["original"], original)
            self.assertEqual(after["parser_version"], "0.1.0")
            self.assertEqual(after["latest_parser_version"], "0.1.2")
            self.assertEqual((after["current"]["room"], after["current"]["point_id"]), ("C11", "BSC01-1"))
            self.assertEqual(after["current"]["operator"], "synthetic-operator")
            self.assertEqual(after["verified"]["operator"], "checked")
            parser_history = store.history(root, record["id"])[0]
            history_before = json.loads(parser_history["before_json"])
            history_after = json.loads(parser_history["after_json"])
            self.assertEqual(history_before["current"], edited)
            self.assertEqual(history_before["current"]["room"], "")
            self.assertEqual(history_before["current"]["point_id"], "C11_BSC01-1")
            self.assertEqual(history_before["current"]["operator"], "synthetic-operator")
            self.assertEqual(history_before["verified"]["operator"], "checked")
            self.assertEqual(history_before["state"], "draft")
            self.assertEqual(history_before["warnings"], [])
            self.assertEqual(history_after["current"], after["current"])
            self.assertEqual(history_after["verified"], after["verified"])
            self.assertEqual(history_after["state"], after["state"])
            self.assertEqual(history_after["warnings"], after["warnings"])
            self.assertEqual(set(history_after["auto_updated_fields"]), {"room", "point_id"})
            self.assertEqual(history_after["protected_conflicts"]["operator"], "")

            later = store.reparse_source(root, 1, content,
                [self.candidate(location, "BSC01-1", "C17")], "0.1.3")
            self.assertEqual(later["updated"], 1)
            self.assertEqual(store.get(root, record["id"])["current"]["room"], "C17")
            changes_before = len(store.history(root, record["id"]))
            retry = store.reparse_source(root, 1, content,
                [self.candidate(location, "BSC01-1", "C17")], "0.1.3")
            self.assertTrue(retry["noop"])
            self.assertEqual(len(store.records(root)), 1)
            self.assertEqual(len(store.history(root, record["id"])), changes_before)
            with self.assertRaises(store.StaleRecord):
                store.update(root, record["id"], stale_version, edited, verified,
                             "draft", "舊表單模擬")
            from em_mvp.app import create_app
            client = create_app(root).test_client()
            detail = client.get(f"/record/{record['id']}")
            matrix = client.get("/records")
            accuracy = client.get("/accuracy.csv")
            self.assertEqual(detail.status_code, 200)
            self.assertIn("這筆原始辨認值解析版本 0.1.0", detail.get_data(as_text=True))
            self.assertIn("來源首次匯入解析版本 0.1.0", detail.get_data(as_text=True))
            self.assertIn("目前解析版本 0.1.3", detail.get_data(as_text=True))
            self.assertIn("BSC01-1", matrix.get_data(as_text=True))
            self.assertEqual(accuracy.status_code, 200)
            rows = {row["field"]: row for row in csv.DictReader(accuracy.get_data().decode("utf-8-sig").splitlines())}
            self.assertEqual(rows["room"]["pending"], "1")
            self.assertEqual((rows["operator"]["correct"], rows["operator"]["incorrect"]), ("0", "1"))

    def test_reparse_refreshes_current_warnings_but_keeps_old_warning_in_before_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store.initialize(root)
            content = b"source warnings"
            old = self.candidate("row 2", "BSC01-1", "")
            old["warnings"] = ["room: 未取得"]
            store.add_import(root, "report.docx", content, [old], "0.1.0")
            record_id = store.records(root)[0]["id"]
            candidate = self.candidate("row 2", "BSC01-1", "C11")
            store.reparse_source(root, 1, content, [candidate], "0.1.2")
            record = store.get(root, record_id)
            history_before = json.loads(store.history(root, record_id)[0]["before_json"])
            self.assertNotIn("room: 未取得", record["warnings"])
            self.assertEqual(history_before["warnings"], ["room: 未取得"])
            from em_mvp.app import create_app
            response = create_app(root).test_client().get(f"/record/{record_id}")
            page = response.get_data(as_text=True)
            history_start = page.index("<details><summary>修改歷程")
            self.assertNotIn("room: 未取得", page[:history_start])
            self.assertIn("room: 未取得", page[history_start:])

    def test_added_row_has_its_own_original_parser_version_in_detail_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store.initialize(root)
            content = b"source versions"
            store.add_import(root, "report.docx", content,
                             [self.candidate("row 2", "P1", "")], "0.1.0")
            result = store.reparse_source(root, 1, content,
                [self.candidate("row 2", "P1", ""), self.candidate("row 3", "P2", "C12")], "0.1.2")
            self.assertEqual(result["added"], 1)
            row = next(r for r in store.records(root) if r["source_location"] == "row 3")
            self.assertEqual(row["original_parser_version"], "0.1.2")
            self.assertEqual(row["source_initial_parser_version"], "0.1.0")
            from em_mvp.app import create_app
            client = create_app(root).test_client()
            detail = client.get(f"/record/{row['id']}").get_data(as_text=True)
            self.assertIn("這筆原始辨認值解析版本 0.1.2", detail)
            self.assertIn("來源首次匯入解析版本 0.1.0", detail)
            csv_rows = list(csv.DictReader(client.get("/records.csv").get_data().decode("utf-8-sig").splitlines()))
            csv_row = next(r for r in csv_rows if r["location"] == "row 3")
            self.assertEqual(csv_row["original_parser_version"], "0.1.2")
            self.assertEqual(csv_row["source_initial_parser_version"], "0.1.0")

    def test_reparse_rolls_back_if_a_conditional_update_changes_zero_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store.initialize(root)
            content = b"conditional update"
            store.add_import(root, "report.docx", content,
                             [self.candidate("row 2", "P1", "")], "0.1.0")
            before = store.records(root)[0]
            with closing(sqlite3.connect(root / "em.sqlite3")) as db:
                db.execute("""CREATE TRIGGER skip_record_update BEFORE UPDATE OF current ON records
                    BEGIN SELECT RAISE(IGNORE); END""")
            with self.assertRaises(store.StaleRecord):
                store.reparse_source(root, 1, content,
                    [self.candidate("row 2", "P1", "C11")], "0.1.2")
            with closing(sqlite3.connect(root / "em.sqlite3")) as db:
                db.execute("DROP TRIGGER skip_record_update")
            after = store.get(root, before["id"])
            self.assertEqual(after["current"]["room"], "")
            self.assertEqual(after["version"], before["version"])
            self.assertEqual(store.sources(root)[0]["latest_parser_version"], "0.1.0")
            self.assertEqual(store.history(root, before["id"]), [])
            self.assertFalse(any(row["status"] == "reparsed" for row in store.import_history(root)))

    def test_reparse_checks_omitted_row_and_source_version_updates(self):
        for failed_column in ("state", "warnings", "latest_parser_version"):
            with self.subTest(failed_column=failed_column), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store.initialize(root)
                content = ("source " + failed_column).encode()
                store.add_import(root, "report.docx", content,
                                 [self.candidate("row 2", "P1", "")], "0.1.0")
                before = store.records(root)[0]
                if failed_column == "state":
                    parsed = []
                    trigger = """CREATE TRIGGER skip_state_update BEFORE UPDATE OF state ON records
                        BEGIN SELECT RAISE(IGNORE); END"""
                elif failed_column == "warnings":
                    values = dict(before["current"])
                    values["operator"] = "human"
                    store.update(root, before["id"], before["version"], values,
                                 {"operator": "checked"}, "draft", "模擬已核對列")
                    before = store.get(root, before["id"])
                    parsed = []
                    trigger = """CREATE TRIGGER skip_warnings_update BEFORE UPDATE OF warnings ON records
                        BEGIN SELECT RAISE(IGNORE); END"""
                else:
                    parsed = [self.candidate("row 2", "P1", "C11")]
                    trigger = """CREATE TRIGGER skip_source_version BEFORE UPDATE OF latest_parser_version ON sources
                        BEGIN SELECT RAISE(IGNORE); END"""
                with closing(sqlite3.connect(root / "em.sqlite3")) as db:
                    db.execute(trigger)
                with self.assertRaises(store.StaleRecord):
                    store.reparse_source(root, 1, content, parsed, "0.1.2")
                with closing(sqlite3.connect(root / "em.sqlite3")) as db:
                    db.execute("DROP TRIGGER IF EXISTS skip_state_update")
                    db.execute("DROP TRIGGER IF EXISTS skip_warnings_update")
                    db.execute("DROP TRIGGER IF EXISTS skip_source_version")
                after = store.get(root, before["id"])
                self.assertEqual(after["version"], before["version"])
                self.assertEqual(after["current"]["room"], "")
                self.assertEqual(after["state"], "draft")
                self.assertEqual(store.sources(root)[0]["latest_parser_version"], "0.1.0")
                self.assertFalse(any(row["actor"] == "解析器" for row in store.history(root, before["id"])))
                if failed_column == "warnings":
                    self.assertEqual(after["current"]["operator"], "human")
                self.assertFalse(any(row["status"] == "reparsed" for row in store.import_history(root)))

    def test_human_save_cannot_commit_between_reparse_read_and_conditional_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store.initialize(root)
            content = b"serialized update"
            store.add_import(root, "report.docx", content,
                             [self.candidate("row 2", "P1", "")], "0.1.0")
            before = store.records(root)[0]
            original_connection = store.connection
            store.connection = lambda data_dir: original_connection(data_dir, timeout=0.1)
            updater_result = []
            started = threading.Event()
            original_checked_update = store._checked_update
            injected = False

            def try_user_update_before_auto_update(db, sql, params, message):
                nonlocal injected
                if not injected and sql.startswith("UPDATE records SET current="):
                    injected = True
                    values = dict(before["current"])
                    values["operator"] = "human"

                    def save():
                        started.set()
                        try:
                            store.update(root, before["id"], before["version"], values, {},
                                         "draft", "模擬並行人工儲存")
                        except Exception as error:
                            updater_result.append(error)

                    thread = threading.Thread(target=save)
                    thread.start()
                    self.assertTrue(started.wait(1))
                    thread.join(3)
                    self.assertFalse(thread.is_alive(), "並行儲存應在短暫鎖逾時內回報")
                return original_checked_update(db, sql, params, message)

            store._checked_update = try_user_update_before_auto_update
            try:
                result = store.reparse_source(root, 1, content,
                    [self.candidate("row 2", "P1", "C11")], "0.1.2")
            finally:
                store.connection = original_connection
                store._checked_update = original_checked_update
            after = store.get(root, before["id"])
            self.assertEqual(len(updater_result), 1)
            self.assertIsInstance(updater_result[0], store.StaleRecord)
            self.assertEqual(result["updated"], 1)
            self.assertEqual((after["current"]["room"], after["current"]["operator"]), ("C11", ""))
            parser_changes = [h for h in store.history(root, before["id"]) if h["actor"] == "解析器"]
            self.assertEqual(len(parser_changes), 1)
            self.assertEqual(store.sources(root)[0]["latest_parser_version"], "0.1.2")

    def test_omitted_unmodified_row_is_retained_as_void(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store.initialize(root)
            content = b"source"
            store.add_import(root, "report.docx", content,
                             [self.candidate("row 2", "P1", ""), self.candidate("row 3", "P2", "")],
                             "0.1.0")
            result = store.reparse_source(root, 1, content,
                [self.candidate("row 2", "P1", "C11")], "0.1.2")
            rows = {row["source_location"]: row for row in store.records(root)}
            self.assertEqual(result["voided"], 1)
            self.assertEqual(rows["row 3"]["state"], "void")
            self.assertEqual(len(rows), 2)
            self.assertEqual(store.history(root, rows["row 3"]["id"])[0]["actor"], "解析器")

    def test_old_schema_migration_keeps_original_parser_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(exist_ok=True)
            db = sqlite3.connect(root / "em.sqlite3")
            try:
                db.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, parser_version TEXT NOT NULL, created_at TEXT NOT NULL)")
                db.execute("INSERT INTO sources VALUES(1,'old.docx','sha','0.1.0','2026-01-01')")
                db.execute("""CREATE TABLE records (
                    id INTEGER PRIMARY KEY, source_id INTEGER, source_location TEXT NOT NULL, source_text TEXT NOT NULL,
                    original TEXT NOT NULL, current TEXT NOT NULL, verified TEXT NOT NULL, warnings TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'draft', version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
                db.execute("""INSERT INTO records(source_id,source_location,source_text,original,current,
                    verified,warnings,created_at,updated_at) VALUES(1,'row 2','P1','{}','{}','{}','[]','a','a')""")
                db.commit()
            finally:
                db.close()
            store.initialize(root)
            source = store.sources(root)[0]
            self.assertEqual(source["parser_version"], "0.1.0")
            self.assertEqual(source["latest_parser_version"], "0.1.0")
            self.assertEqual(source["context_json"], "{}")
            self.assertEqual(store.records(root)[0]["original_parser_version"], "0.1.0")

    def test_reparse_route_submits_with_csrf_and_updates_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = word_file([['監測位置','結果(CFU)'],['C11_BSC01-1','0']],
                                ['監測日期：2026-06-03','監測方式：▓落菌法 □培養皿接觸'])
            parsed = parse_file("三廠-20260603.docx", content, {"site":"三廠"})
            parsed[0]["values"]["room"] = ""
            parsed[0]["values"]["point_id"] = "C11_BSC01-1"
            store.initialize(root)
            store.add_import(root, "三廠-20260603.docx", content, parsed, "0.1.0", {"site":"三廠"})
            from em_mvp.app import create_app
            client = create_app(root).test_client()
            client.get("/")
            with client.session_transaction() as session:
                csrf = session["csrf"]
            response = client.post("/reparse/1", data={"csrf":csrf}, follow_redirects=True)
            record = store.records(root)[0]
            self.assertEqual(response.status_code, 200)
            self.assertIn("重新解析完成", response.get_data(as_text=True))
            self.assertEqual((record["current"]["room"], record["current"]["point_id"]), ("C11", "BSC01-1"))
            self.assertEqual(record["parser_version"], "0.1.0")
            self.assertEqual(record["latest_parser_version"], PARSER_VERSION)


if __name__ == "__main__":
    unittest.main()
