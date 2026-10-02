import csv
import html
import io
import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from em_mvp import store
from em_mvp.app import create_app
from em_mvp.domain import FIELDS
from em_mvp.importers import PARSER_VERSION, _result, parse_file
from em_mvp.reporting import _limit_status, monthly_matrix


def word_file(rows, paragraphs=()):
    from xml.sax.saxutils import escape

    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    table = "".join("<w:tr>" + "".join(
        f"<w:tc><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:tc>" for text in row
    ) + "</w:tr>" for row in rows)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body>{body}<w:tbl>{table}</w:tbl></w:body></w:document>')
    return data.getvalue()


def matrix_record(record_id, day, raw, count, alert="<5", action="<10", **changes):
    current = {field: "" for field in FIELDS}
    current.update({
        "sample_date": day, "site": "一廠", "monitoring_type": "例行環測",
        "method": "落菌法", "room": "C06D", "grade": "C", "point_id": "a11",
        "result_raw": raw, "result_type": "count", "cfu_count": str(count),
        "unit": "CFU/plate", "alert_raw": alert, "action_raw": action,
    })
    current.update(changes)
    return {"id": record_id, "source_id": record_id, "source_name": f"source-{record_id}.docx",
            "source_location": f"Word table 1 row {record_id + 1}", "sha256": str(record_id),
            "original": dict(current), "current": current, "verified": {}, "warnings": [],
            "state": "draft", "is_manual": False}


def csrf_token(client):
    client.get("/")
    with client.session_transaction() as session:
        return session["csrf"]


class EM005ParsingTests(unittest.TestCase):
    def test_supported_annotated_counts_keep_only_the_prefix(self):
        cases = {
            "3(1mold)": "3", "8(1mold)": "8", "1(mold)": "1",
            "94(3白mold)": "94", "109(1 mold)": "109",
            "47 (3molds,2白,1黑)": "47", "15(1satellite)": "15",
            "9(1Satellite)": "9", "2（3 white molds；2 black）": "2",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(_result(raw), ("count", expected))
        self.assertEqual(_result("TNTC(mold)"), ("tntc", ""))
        for raw, expected_type in (("<1", "less_than"), ("N/A", "not_applicable"),
                                   ("-1", "unknown"), ("12 (3bacteria)", "unknown"),
                                   ("5 mold text", "unknown")):
            with self.subTest(raw=raw):
                kind, count = _result(raw)
                self.assertEqual(kind, expected_type)
                self.assertEqual(count, "")
        self.assertEqual(PARSER_VERSION, "0.1.4")

    def test_first_factory_rooms_are_exact_and_conflicts_remain_visible(self):
        rooms = ["C01", "C01A", "C02", "C03", "C04", "C05", "C06", "C06D"]
        rows = [["房間", "監測位置", "結果(CFU)"]] + [[room, "a11", "0"] for room in rooms]
        parsed = parse_file("report.docx", word_file(rows))
        self.assertEqual([row["values"]["site"] for row in parsed], ["一廠"] * len(rooms))
        unknown = ["C00", "C07", "C060", "C16"]
        parsed_unknown = parse_file("report.docx", word_file(
            [["房間", "監測位置", "結果(CFU)"]] + [[room, "a11", "0"] for room in unknown]))
        self.assertEqual([row["values"]["site"] for row in parsed_unknown], [""] * len(unknown))

        conflicting = parse_file("三廠-report.docx", word_file([
            ["房間", "監測位置", "結果(CFU)"], ["C06D", "a11", "0"]
        ]), {"source_prefix": "一廠 / 2026 /"})[0]
        self.assertEqual(conflicting["values"]["site"], "三廠")
        self.assertTrue(any("文件廠別 三廠 與匯入資料夾脈絡 一廠 不同" in warning
                            for warning in conflicting["warnings"]))
        self.assertTrue(any("房間 C06D 依規則屬於 一廠" in warning
                            for warning in conflicting["warnings"]))

    def test_factory_folder_labels_are_bounded_and_ignore_source_filename(self):
        content = word_file([["房間", "監測位置", "結果(CFU)"], ["C16", "a11", "1"]])
        cases = [
            ("一廠環測/report.docx / ", "一廠", False),
            ("一廠還測/report.docx / ", "一廠", False),
            ("2026/十一廠/report.docx / ", "", True),
            ("2026/13廠/report.docx / ", "", True),
            ("2026/比較/三廠-reference.docx / ", "", False),
        ]
        for prefix, expected_site, needs_review in cases:
            with self.subTest(prefix=prefix):
                parsed = parse_file("report.docx", content, {"source_prefix": prefix})[0]
                self.assertEqual(parsed["values"]["site"], expected_site)
                self.assertEqual(any("source_prefix" in warning for warning in parsed["warnings"]),
                                 needs_review)

        filename = parse_file("report-十一廠.docx", content)[0]
        self.assertEqual(filename["values"]["site"], "")
        self.assertEqual(parse_file("一廠-report.docx", content)[0]["values"]["site"], "一廠")

        room_in_unknown_folder = word_file(
            [["房間", "監測位置", "結果(CFU)"], ["C06D", "a11", "3(1mold)"]])
        for folder in ("十一廠", "13廠", "一廠環測/三廠"):
            with self.subTest(ambiguous_folder=folder):
                parsed = parse_file("report.docx", room_in_unknown_folder,
                                    {"source_folder": folder})[0]
                self.assertEqual(parsed["values"]["site"], "")
                self.assertTrue(any("不依房間推導" in warning for warning in parsed["warnings"]))

    def test_alarm_action_threshold_boundaries_and_unknowns(self):
        expected = {0: "normal", 3: "normal", 4: "normal", 5: "alarm", 8: "alarm",
                    9: "alarm", 10: "action", 11: "action"}
        for count, status in expected.items():
            with self.subTest(count=count):
                self.assertEqual(_limit_status(count, "<5", "<10")[0], status)
        for count, status in ((5, "normal"), (6, "alarm"), (10, "alarm"), (11, "action")):
            self.assertEqual(_limit_status(count, "≤5", "≤10")[0], status)
        for count, status in ((5, "normal"), (6, "alarm"), (10, "alarm"), (11, "action")):
            self.assertEqual(_limit_status(count, "5", "10")[0], status)
        self.assertEqual(_limit_status(0, "0", "N/A")[0], "normal")
        self.assertEqual(_limit_status(1, "0", "N/A")[0], "alarm")
        self.assertEqual(_limit_status(10, "N/A", "<10")[0], "action")
        self.assertEqual(_limit_status(3, "", "<10")[0], "review")
        self.assertEqual(_limit_status(3, "not a limit", "<10")[0], "review")
        self.assertEqual(_limit_status(5, "<5", "unknown")[0], "review")

    def test_month_uses_its_representative_source_limit_and_conflict_is_neutral(self):
        rows = [
            matrix_record(1, "2026-05-01", "5", 5, "≤5", "≤10"),
            matrix_record(2, "2026-06-01", "5", 5, "<3", "<10"),
        ]
        result = monthly_matrix(rows, 2026)[0]
        self.assertEqual(result["months"][5]["status"], "normal")
        self.assertEqual(result["months"][5]["alert_raw"], "≤5")
        self.assertEqual(result["months"][6]["status"], "alarm")
        self.assertEqual(result["months"][6]["alert_raw"], "<3")
        conflict = monthly_matrix([
            matrix_record(3, "2026-07-01", "5", 5, "<5", "<10"),
            matrix_record(4, "2026-07-01", "5", 5, "<4", "<10"),
        ], 2026)[0]["months"][7]
        self.assertTrue(conflict["first_conflict"])
        self.assertEqual((conflict["status"], conflict["status_text"]), ("review", "需核對"))

    def test_matrix_shows_manual_cfu_and_keeps_annotated_raw_value(self):
        record = matrix_record(1, "2026-05-19", "3(1mold)", 3)
        record["current"]["cfu_count"] = "9"
        month = monthly_matrix([record], 2026)[0]["months"][5]
        self.assertEqual(month["display"], "9（目前結果原文：3(1mold)）")
        self.assertEqual((month["numeric"], month["status"]), (9, "alarm"))
        self.assertEqual(monthly_matrix([record], 2026)[0]["trend_values"][4], 9)


class EM005FlowTests(unittest.TestCase):
    def test_room_site_annotation_csv_matrix_trend_and_report_share_one_cfu(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root)
            client = app.test_client()
            samples = [
                ("2026-05-19", "3(1mold)", "<5", "<10"),
                ("2026-09-15", "8(1mold)", "<5", "<10"),
            ]
            for day, raw, alert, action in samples:
                content = word_file([
                    ["房間", "監測位置", "結果(CFU)", "Alarm Lv", "Action Lv"],
                    ["C06D", "a11", raw, alert, action],
                ], [f"監測日期：{day}", "監測方式：落菌法"])
                parsed = parse_file(f"report-{day}.docx", content)
                self.assertEqual(parsed[0]["values"]["site"], "一廠")
                store.add_import(root, f"report-{day}.docx", content, parsed, PARSER_VERSION)
            for record in store.records(root):
                store.update(root, record["id"], record["version"], record["current"], {},
                             "confirmed", "合成驗收資料")

            rows = store.records(root)
            matrix = monthly_matrix(rows, 2026)[0]
            may, september = matrix["months"][5], matrix["months"][9]
            self.assertEqual((may["display"], may["numeric"], may["status"]), ("3(1mold)", 3, "normal"))
            self.assertEqual((september["display"], september["numeric"], september["status"]),
                             ("8(1mold)", 8, "alarm"))
            self.assertEqual((matrix["trend_values"][4], matrix["trend_values"][8]), (3, 8))

            page = client.get("/records?year=2026&site=%E4%B8%80%E5%BB%A0").get_data(as_text=True)
            self.assertIn("房間：C06D", page)
            self.assertIn("判定依據", page)
            self.assertIn("代表來源 report-2026-05-19.docx", page)
            self.assertIn("正常", page)
            self.assertIn("警戒", page)
            month_link = re.search(r'href="([^"]*view=month[^"]*)"', page)
            self.assertIsNotNone(month_link)
            month_detail = client.get(html.unescape(month_link.group(1))).get_data(as_text=True)
            self.assertIn("3(1mold)", month_detail)
            self.assertIn("一廠", month_detail)

            details = client.get("/records?view=detail&state=confirmed").get_data(as_text=True)
            self.assertIn("一廠", details)
            exported = client.get("/records.csv").get_data().decode("utf-8-sig")
            csv_rows = list(csv.DictReader(io.StringIO(exported)))
            self.assertEqual({row["site"] for row in csv_rows}, {"一廠"})
            self.assertEqual({row["result_raw"] for row in csv_rows}, {"3(1mold)", "8(1mold)"})
            self.assertEqual({row["cfu_count"] for row in csv_rows}, {"3", "8"})
            report = client.get("/reports?start=2026-05&end=2026-09&site=%E4%B8%80%E5%BB%A0")
            report_html = report.get_data(as_text=True)
            self.assertIn("class=\"number\">3</td>", report_html)
            self.assertIn("class=\"number\">8</td>", report_html)
            self.assertNotIn("class=\"positive\"", report_html)

            may_record = next(row for row in store.records(root)
                              if row["current"]["sample_date"] == "2026-05-19")
            corrected = dict(may_record["current"])
            corrected["cfu_count"] = "9"
            store.update(root, may_record["id"], may_record["version"], corrected, {},
                         may_record["state"], "合成更正 CFU")
            corrected_page = client.get("/records?year=2026&site=%E4%B8%80%E5%BB%A0").get_data(as_text=True)
            self.assertIn("9（目前結果原文：3(1mold)）", corrected_page)
            self.assertIn('class="matrix-cell matrix-alarm"', corrected_page)

    def test_batch_reparse_protects_manual_checked_confirmed_and_void_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = create_app(root).test_client()
            prefix = "一廠 / 2026 /"
            content = word_file([
                ["房間", "監測位置", "結果(CFU)"],
                *[["C06D", f"a1{index}", f"{index + 2}(1mold)"] for index in range(5)],
            ], ["監測日期：2026-05-19", "監測方式：落菌法"])
            candidates = parse_file("legacy.docx", content, {"source_prefix": prefix})
            for row in candidates:
                row["source_location"] = prefix + row["source_location"]
                row["values"]["site"] = ""
                row["values"]["result_type"] = "unknown"
                row["values"]["cfu_count"] = ""
                row["warnings"].append("site: 未取得")
            self.assertEqual(store.add_import(root, "legacy.docx", content, candidates, "0.1.3",
                                              {"source_prefix": prefix}), 5)
            before = store.records(root)
            original = [dict(row["original"]) for row in before]

            first = before[0]
            edited = dict(first["current"])
            edited["cfu_count"] = "99"
            store.update(root, first["id"], first["version"], edited, {}, "draft", "合成手動修改")
            first_after = store.get(root, first["id"])
            edited = dict(first_after["current"])
            edited["cfu_count"] = first_after["original"]["cfu_count"]
            store.update(root, first["id"], first_after["version"], edited, {}, "draft", "合成改回原值")

            second = before[1]
            store.update(root, second["id"], second["version"], second["current"],
                         {"cfu_count": "checked"}, "draft", "合成欄位核對")
            third = before[2]
            store.update(root, third["id"], third["version"], third["current"], {},
                         "confirmed", "合成確認狀態")
            fourth = before[3]
            store.update(root, fourth["id"], fourth["version"], fourth["current"], {},
                         "void", "合成作廢狀態")
            token = csrf_token(client)

            result_page = client.post("/reparse-batch", data={"csrf": token}).get_data(as_text=True)
            self.assertIn('data-success="0"', result_page)
            self.assertIn('data-conflict="1"', result_page)
            self.assertIn('data-skipped="0"', result_page)
            self.assertIn('data-failed="0"', result_page)
            self.assertIn("備份", result_page)

            after = store.records(root)
            self.assertEqual(len(after), 5)
            self.assertEqual(len(store.sources(root)), 1)
            self.assertEqual(store.sources(root)[0]["latest_parser_version"], PARSER_VERSION)
            self.assertEqual([row["original"] for row in after], original)
            self.assertEqual({row["source_location"] for row in after},
                             {candidate["source_location"] for candidate in candidates})
            for row in after:
                self.assertEqual(row["sha256"], store.sources(root)[0]["sha256"])
                self.assertEqual(row["original_parser_version"], "0.1.3")
            self.assertEqual(after[0]["current"]["cfu_count"], "")
            self.assertEqual(after[1]["current"]["cfu_count"], "")
            self.assertEqual(after[1]["verified"]["cfu_count"], "checked")
            self.assertEqual(after[2]["state"], "confirmed")
            self.assertEqual(after[2]["current"]["cfu_count"], "")
            self.assertEqual(after[3]["state"], "void")
            self.assertEqual(after[3]["current"]["cfu_count"], "")
            untouched = after[-1]
            self.assertEqual(untouched["current"]["cfu_count"], "2")
            self.assertEqual(untouched["current"]["site"], "一廠")
            self.assertTrue(any("site: 未取得" in json.loads(change["before_json"])["warnings"]
                                for change in store.history(root, untouched["id"])))
            self.assertGreaterEqual(len(list((root / "backups").glob("*.sqlite3"))), 2)

            changes_before = sum(len(store.history(root, row["id"])) for row in after)
            second_page = client.post("/reparse-batch", data={"csrf": token}).get_data(as_text=True)
            self.assertIn('data-outcome="none"', second_page)
            self.assertEqual(sum(len(store.history(root, row["id"])) for row in after), changes_before)

    def test_batch_failure_is_reported_and_other_sources_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = create_app(root).test_client()
            good_content = word_file([
                ["房間", "監測位置", "結果(CFU)"], ["C06D", "a11", "3(1mold)"]
            ], ["監測日期：2026-05-19", "監測方式：落菌法"])
            bad_content = b"not a docx file"
            for name, content in (("good.docx", good_content), ("bad.docx", bad_content)):
                if name.startswith("good"):
                    parsed = parse_file(name, content)
                else:
                    parsed = [{"values": {field: "" for field in FIELDS},
                               "source_location": "Word table 1 row 2", "source_text": "raw", "warnings": []}]
                store.add_import(root, name, content, parsed, "0.1.3")
            bad_source = next(row for row in store.sources(root) if row["name"] == "bad.docx")
            (root / "sources" / (bad_source["sha256"] + ".docx")).unlink()

            page = client.post("/reparse-batch", data={"csrf": csrf_token(client)}).get_data(as_text=True)
            self.assertIn('data-success="1"', page)
            self.assertIn('data-failed="1"', page)
            current_versions = {row["name"]: row["latest_parser_version"] for row in store.sources(root)}
            self.assertEqual(current_versions["good.docx"], PARSER_VERSION)
            self.assertEqual(current_versions["bad.docx"], "0.1.3")
            self.assertIn("reparse_failed", {item["status"] for item in store.import_history(root)})


if __name__ == "__main__":
    unittest.main()
