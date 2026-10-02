import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from threading import Event
from unittest.mock import patch

from openpyxl import Workbook

from em_mvp import store
from em_mvp.app import create_app, reparse_saved_source
from em_mvp.domain import FIELDS
from em_mvp.folder_import import MAX_FOLDER_FILE_BYTES, validate_folder
from em_mvp.reporting import field_accuracy


def word_file(sample_date="2026-06-03", result="2"):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    from xml.sax.saxutils import escape
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>"
        for text in (f"採樣日期：{sample_date}", "廠別：三廠", "監測類型：例行環測", "監測方式：空氣採樣法")
    )
    rows = [["監測位置", "Grade", "結果(CFU)", "Alarm Lv(CFU)", "Action Lv(CFU)"],
            ["C11: A", "C", result, "<50", "<100"]]
    table = "".join("<w:tr>" + "".join(
        f"<w:tc><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>" for cell in row
    ) + "</w:tr>" for row in rows)
    xml = f'<w:document xmlns:w="{ns}"><w:body>{paragraphs}<w:tbl>{table}</w:tbl></w:body></w:document>'
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def first_factory_folder_word_file():
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    from xml.sax.saxutils import escape
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>"
        for text in ("採樣日期：2026-05-19", "監測類型：例行環測", "監測方式：空氣採樣法")
    )
    rows = [["房間", "監測位置", "結果(CFU)"],
            ["C06D", "a11", "3(1mold)"], ["", "Negative control", "0"]]
    table = "".join("<w:tr>" + "".join(
        f"<w:tc><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>" for cell in row
    ) + "</w:tr>" for row in rows)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body>{paragraphs}<w:tbl>{table}</w:tbl></w:body></w:document>')
    return output.getvalue()


def csv_file():
    return ("日期,廠別,檢測目的,方法,房間,Grade,點位,結果,單位\n"
            "2026-06-03,三廠,環測,空氣採樣,C11,C,A,0,CFU/m3\n").encode("utf-8")


def xlsx_file():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["日期", "廠別", "檢測目的", "方法", "房間", "Grade", "點位", "結果(CFU)", "單位"])
    sheet.append(["2026-06-03", "三廠", "環測", "空氣採樣", "C11", "C", "A", 1, "CFU/m3"])
    data = io.BytesIO()
    workbook.save(data)
    return data.getvalue()


class FolderImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.app = create_app(self.path / "data")
        self.client = self.app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.token = session["csrf"]

    def tearDown(self):
        self.temp.cleanup()

    def start(self, folder, include_sheets=False):
        form = {"csrf": self.token, "folder_path": str(folder)}
        if include_sheets:
            form["include_sheets"] = "on"
        return self.client.post("/folder-import", data=form,
                                headers={"X-Requested-With": "XMLHttpRequest"})

    def wait(self, job_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = self.client.get(f"/folder-import/status/{job_id}")
            self.assertEqual(response.status_code, 200)
            job = response.get_json()
            if job["phase"] == "complete":
                return job
            time.sleep(0.02)
        self.fail("資料夾匯入未在期限內完成")

    def test_a1_recurses_two_levels_and_writes_directly_to_database(self):
        root = self.path / "reports"
        (root / "level1" / "level2").mkdir(parents=True)
        (root / "a.docx").write_bytes(word_file())
        (root / "level1" / "b.docx").write_bytes(word_file("2026-06-16", "8"))
        (root / "level1" / "level2" / "c.docx").write_bytes(word_file("2026-07-02", "0"))

        response = self.start(root)
        self.assertEqual(response.status_code, 202)
        job = self.wait(response.get_json()["job_id"])
        records = store.records(self.path / "data")
        self.assertEqual((job["new_files"], job["new_records"], job["failed_count"]), (3, 3, 0))
        self.assertEqual(len(records), 3)
        self.assertTrue(any("level1/level2/c.docx" in row["source_location"] for row in records))
        self.assertTrue(all(row["state"] == "draft" for row in records))

    def test_first_factory_folder_context_classifies_every_imported_row_once(self):
        root = self.path / "reports"
        folder = root / "一廠環測"
        folder.mkdir(parents=True)
        (folder / "report.docx").write_bytes(first_factory_folder_word_file())

        response = self.start(root)
        self.assertEqual(response.status_code, 202)
        job = self.wait(response.get_json()["job_id"])
        records = store.records(self.path / "data")
        sources = store.sources(self.path / "data")

        self.assertEqual((job["new_files"], job["new_records"], job["failed_count"]), (1, 2, 0))
        self.assertEqual({row["current"]["site"] for row in records}, {"一廠"})
        sample = next(row for row in records if row["current"]["point_id"] == "a11")
        control = next(row for row in records if row["current"]["point_id"] == "Negative control")
        self.assertEqual(sample["current"]["room"], "C06D")
        self.assertEqual(control["current"]["room"], "")
        self.assertEqual(sample["current"]["cfu_count"], "3")
        source_context = json.loads(sources[0]["context_json"])
        self.assertEqual(source_context["source_prefix"], "一廠環測/report.docx / ")
        self.assertEqual(source_context["source_folder"], "reports/一廠環測")
        self.assertNotIn("site", source_context)
        self.assertTrue(all(row["source_location"].startswith("一廠環測/report.docx / Word table 1 row ")
                            for row in records))
        self.assertEqual(len({row["source_location"] for row in records}), 2)

    def test_selected_factory_root_name_provides_folder_context(self):
        root = self.path / "一廠環測"
        root.mkdir()
        (root / "report.docx").write_bytes(first_factory_folder_word_file())

        response = self.start(root)
        self.assertEqual(response.status_code, 202)
        job = self.wait(response.get_json()["job_id"])
        records = store.records(self.path / "data")
        source = store.sources(self.path / "data")[0]
        source_context = json.loads(source["context_json"])
        prefix = "report.docx / "

        self.assertEqual((job["new_files"], job["new_records"], job["failed_count"]), (1, 2, 0))
        self.assertEqual({row["current"]["site"] for row in records}, {"一廠"})
        self.assertEqual(source_context["source_prefix"], prefix)
        self.assertEqual(source_context["source_folder"], "一廠環測")
        self.assertNotIn("site", source_context)
        self.assertTrue(all(row["source_location"].count(prefix) == 1 for row in records))

        with store.closing(store.connection(self.path / "data")) as db, db:
            db.execute("UPDATE sources SET latest_parser_version='0.1.3' WHERE id=?", (source["id"],))
        source = next(item for item in store.sources(self.path / "data") if item["id"] == source["id"])
        result = reparse_saved_source(self.path / "data", source)
        reparsed = store.records(self.path / "data")
        self.assertFalse(result["noop"])
        self.assertEqual(len(reparsed), 2)
        self.assertEqual({row["current"]["site"] for row in reparsed}, {"一廠"})
        self.assertEqual(next(row for row in reparsed if row["current"]["point_id"] == "Negative control")
                         ["current"]["room"], "")
        self.assertTrue(all(row["source_location"].count(prefix) == 1 for row in reparsed))

    def test_a2_rerun_preserves_manual_correction_and_history(self):
        root = self.path / "reports"
        root.mkdir()
        (root / "report.docx").write_bytes(word_file())
        first = self.start(root)
        first_job = self.wait(first.get_json()["job_id"])
        record = store.records(self.path / "data")[0]
        current = dict(record["current"])
        current["result_raw"], current["cfu_count"] = "9", "9"
        store.update(self.path / "data", record["id"], record["version"], current,
                     {"cfu_count": "checked"}, "draft", "使用者核對修正")

        second = self.start(root)
        second_job = self.wait(second.get_json()["job_id"])
        changed = store.get(self.path / "data", record["id"])
        self.assertEqual(first_job["new_records"], 1)
        self.assertEqual((second_job["new_files"], second_job["existing_files"]), (0, 1))
        self.assertEqual(changed["original"]["cfu_count"], "2")
        self.assertEqual(changed["current"]["cfu_count"], "9")
        self.assertEqual(len(store.history(self.path / "data", record["id"])), 1)

    def test_a3_bad_file_continues_and_temp_and_unsupported_files_are_skipped(self):
        root = self.path / "mixed"
        root.mkdir()
        (root / "bad.docx").write_bytes(b"not a Word file")
        (root / "good.docx").write_bytes(word_file())
        (root / "~$draft.docx").write_bytes(word_file())
        (root / "notes.txt").write_text("skip", encoding="utf-8")

        response = self.start(root)
        job = self.wait(response.get_json()["job_id"])
        self.assertEqual((job["candidate_count"], job["processed_count"]), (2, 2))
        self.assertEqual((job["new_files"], job["new_records"], job["failed_count"]), (1, 1, 1))
        self.assertEqual(job["skipped_files"], 2)
        self.assertIn("bad.docx", job["failures"][0]["path"])
        self.assertTrue(job["failures"][0]["reason"])

    def test_a3_reparse_directories_are_not_recursed(self):
        root = self.path / "with-link"
        linked = root / "junction"
        linked.mkdir(parents=True)
        (linked / "hidden.docx").write_bytes(word_file())
        with patch("em_mvp.folder_import.os.path.isjunction", side_effect=lambda value: Path(value).name == "junction"):
            response = self.start(root)
            job = self.wait(response.get_json()["job_id"])
        self.assertEqual((job["candidate_count"], job["skipped_directories"], job["new_files"]), (0, 1, 0))
        self.assertEqual(store.records(self.path / "data"), [])

    def test_a4_invalid_nonfolder_and_unreadable_paths_are_explicit(self):
        missing = self.start(self.path / "missing")
        self.assertEqual(missing.status_code, 400)
        self.assertIn("不存在", missing.get_json()["error"])
        file_path = self.path / "not-a-folder.txt"
        file_path.write_text("x", encoding="utf-8")
        not_folder = self.start(file_path)
        self.assertEqual(not_folder.status_code, 400)
        self.assertIn("不是資料夾", not_folder.get_json()["error"])
        unreadable = self.path / "unreadable"
        unreadable.mkdir()
        with patch("em_mvp.folder_import.os.scandir", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(ValueError, "權限"):
                validate_folder(str(unreadable))

    def test_a5_batch_exceeds_25mb_single_file_guard_and_duplicate_start(self):
        root = self.path / "large"
        root.mkdir()
        payload = word_file()
        with zipfile.ZipFile(io.BytesIO(payload)) as source:
            document_xml = source.read("word/document.xml")
        for name in ("a.docx", "b.docx"):
            with zipfile.ZipFile(root / name, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("word/document.xml", document_xml)
                archive.writestr("bulk.bin", os.urandom(13 * 1024 * 1024))
        oversized = root / "z-oversized.docx"
        with oversized.open("wb") as output:
            output.truncate(MAX_FOLDER_FILE_BYTES + 1)
        self.assertGreater(sum(item.stat().st_size for item in root.iterdir()), 25 * 1024 * 1024)

        entered, release = Event(), Event()
        from em_mvp.importers import parse_file
        def blocked_parse(filename, content, context=None):
            entered.set()
            self.assertTrue(release.wait(10))
            return parse_file(filename, content, context)

        with patch("em_mvp.folder_import.parse_file", side_effect=blocked_parse):
            first = self.start(root)
            self.assertEqual(first.status_code, 202)
            self.assertTrue(entered.wait(5))
            duplicate = self.start(root)
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(duplicate.get_json()["job_id"], first.get_json()["job_id"])
            release.set()
            job = self.wait(first.get_json()["job_id"])
        self.assertEqual((job["new_files"], job["new_records"], job["failed_count"]), (2, 2, 1))
        self.assertIn("25 MB", job["failures"][0]["reason"])

    def test_a6_sheet_files_are_included_only_when_selected(self):
        root = self.path / "exports"
        root.mkdir()
        (root / "word.docx").write_bytes(word_file())
        (root / "sheet.csv").write_bytes(csv_file())
        (root / "sheet.xlsx").write_bytes(xlsx_file())

        word_only = self.start(root)
        first = self.wait(word_only.get_json()["job_id"])
        self.assertEqual((first["candidate_count"], first["new_files"], first["skipped_files"]), (1, 1, 2))
        with_sheets = self.start(root, include_sheets=True)
        second = self.wait(with_sheets.get_json()["job_id"])
        self.assertEqual(second["candidate_count"], 3)
        self.assertEqual((second["new_files"], second["existing_files"], second["new_records"]), (2, 1, 2))

    def test_a7_database_source_and_accuracy_keep_import_pending(self):
        root = self.path / "reports"
        root.mkdir()
        (root / "report.docx").write_bytes(word_file())
        started = self.start(root)
        self.wait(started.get_json()["job_id"])
        record = store.records(self.path / "data")[0]
        page = self.client.get("/records").get_data(as_text=True)
        detail = self.client.get(f"/record/{record['id']}").get_data(as_text=True)
        reports = self.client.get("/reports?start=2026-01&end=2026-12").get_data(as_text=True)
        accuracy = {item["field"]: item for item in field_accuracy([record])}
        self.assertIn("待核對", page)
        self.assertIn(f"/source/{record['source_id']}", detail)
        self.assertEqual((record["state"], record["verified"]), ("draft", {}))
        self.assertEqual(accuracy["cfu_count"]["pending"], 1)
        self.assertIsNone(accuracy["cfu_count"]["accuracy"])
        self.assertIn("未評估", reports)
        self.assertIn("尚無已確認", reports)


if __name__ == "__main__":
    unittest.main()
