import io
import json
import re
import html
import tempfile
from urllib.parse import parse_qs, urlparse
import unittest
from pathlib import Path
from unittest.mock import patch

from em_mvp import store
from em_mvp.app import create_app
from em_mvp.reporting import FIELDS, field_accuracy


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.app = create_app(self.path)
        self.client = self.app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as session:
            self.token = session["csrf"]
        self.values = {f: "" for f in FIELDS}
        self.values.update(sample_date="2026-01-02",site="一廠",monitoring_type="製程監測",
                           method="落菌法",grade="A",point_id="P1",operator="ABC",
                           result_raw="1",result_type="count",cfu_count="1",unit="CFU/plate")

    def tearDown(self):
        self.temp.cleanup()

    def import_one(self):
        parsed = [{"values":self.values,"source_location":"table 1 row 2",
                   "source_text":"test source","warnings":[]}]
        with patch("em_mvp.app.parse_file", return_value=parsed):
            return self.client.post("/import",data={"csrf":self.token,
                "files":(io.BytesIO(b"test source bytes"),"test.docx")})

    def import_process_record(self, filename, values):
        content = (filename + " source").encode()
        store.add_import(self.path, filename, content, [{
            "values": values, "source_location": "Table 1 row 2",
            "source_text": filename, "warnings": [],
        }], "0.1.7")
        record = next(row for row in store.records(self.path) if row["source_name"] == filename)
        store.update(self.path, record["id"], record["version"], values, {}, "confirmed", "測試來源確認")
        return store.get(self.path, record["id"])

    def test_review_original_accuracy_idempotence_and_stale_edit(self):
        self.assertEqual(self.import_one().status_code,302)
        record = store.records(self.path)[0]
        form = {**self.values,"csrf":self.token,"record_version":"1","state":"confirmed",
                "reason":"核對來源實際是2","cfu_count":"2","review_cfu_count":"checked"}
        self.assertEqual(self.client.post(f'/record/{record["id"]}',data=form).status_code,302)
        changed = store.get(self.path,record["id"])
        self.assertEqual(changed["original"]["cfu_count"],"1")
        self.assertEqual(changed["current"]["cfu_count"],"2")
        accuracy = {a["field"]:a for a in field_accuracy([changed])}
        self.assertEqual(accuracy["cfu_count"]["accuracy"],0)
        self.assertEqual(accuracy["sample_date"]["accuracy"],None)
        self.assertEqual(len(store.history(self.path,record["id"])),1)
        self.import_one()
        self.assertEqual(len(store.records(self.path)),1)
        self.assertEqual(store.get(self.path,record["id"])["current"]["cfu_count"],"2")
        self.assertEqual(self.client.post(f'/record/{record["id"]}',data=form).status_code,409)
        self.assertEqual(len(store.history(self.path,record["id"])),1)
        page = self.client.get("/reports?start=2026-01&end=2026-03")
        self.assertEqual(page.status_code,200)
        self.assertIn("2026-02",page.get_data(as_text=True))
        self.assertEqual(self.client.get("/report.html").status_code,200)
        self.assertEqual(self.client.get("/accuracy.csv").status_code,200)
        self.assertTrue(list((self.path/"backups").glob("*.sqlite3")))

    def test_reject_csrf_and_keep_transaction_atomic(self):
        self.assertEqual(self.client.post("/manual").status_code,400)
        parsed = [{"values":self.values,"source_location":"same","source_text":"","warnings":[]}]*2
        with self.assertRaises(ValueError):
            store.add_import(self.path,"dup.docx",b"different",parsed,"test")
        self.assertEqual(store.records(self.path),[])
        self.assertEqual(self.client.get("/",headers={"Host":"untrusted.example"}).status_code,400)

    def test_incomplete_record_cannot_confirm_and_form_retains_values(self):
        self.client.post("/manual",data={"csrf":self.token})
        record = store.records(self.path)[0]
        form = {**self.values,"csrf":self.token,"record_version":"1","state":"confirmed",
                "reason":"測試","site":"","point_id":"edited point"}
        response = self.client.post(f'/record/{record["id"]}',data=form)
        self.assertEqual(response.status_code,200)
        self.assertIn("edited point",response.get_data(as_text=True))
        self.assertEqual(store.get(self.path,record["id"])["state"],"draft")

    def test_real_csv_input_review_report_and_cross_source_duplicate(self):
        content = ("日期,廠別,檢測目的,方法,房間,Grade,點位,操作者,批次,結果,單位\n"
                   "2026-01-02,一廠,製測,落菌,C01,A,P1,ABC,,0,CFU/plate\n").encode("utf-8")
        response = self.client.post("/import",data={"csrf":self.token,
            "files":(io.BytesIO(content),"test.csv")})
        self.assertEqual(response.status_code,302)
        first = store.records(self.path)[0]
        self.assertEqual(first["current"]["cfu_count"],"0")
        self.assertEqual(first["current"]["method"],"落菌法")
        form = {**first["current"],"csrf":self.token,"record_version":"1",
                "state":"confirmed","reason":"逐項核對測試","warnings_reviewed":"yes"}
        self.client.post(f'/record/{first["id"]}',data=form)
        self.assertEqual(store.get(self.path,first["id"])["state"],"confirmed")
        second_content = content.replace(b"ABC,,0", b"ABC,B123,0")
        self.client.post("/import",data={"csrf":self.token,
            "files":(io.BytesIO(second_content),"another.csv")})
        second = store.records(self.path)[0]
        form = {**second["current"],"csrf":self.token,"record_version":"1",
                "state":"confirmed","reason":"尚未對帳","warnings_reviewed":"yes"}
        response = self.client.post(f'/record/{second["id"]}',data=form)
        self.assertIn("候選紀錄",response.get_data(as_text=True))
        self.assertEqual(store.get(self.path,second["id"])["state"],"draft")
        html = self.client.get("/reports").get_data(as_text=True)
        self.assertIn("CFU/plate",html)
        self.assertIn('href="/reports"',html)

    def test_analysis_exclusion_form_filters_business_views_and_can_restore(self):
        self.assertEqual(self.import_one().status_code, 302)
        record = store.records(self.path)[0]
        confirmed = {**self.values, "csrf": self.token, "record_version": "1",
                     "state": "confirmed", "reason": "來源逐欄確認",
                     "review_cfu_count": "checked"}
        self.assertEqual(self.client.post(f'/record/{record["id"]}', data=confirmed).status_code, 302)
        current = store.get(self.path, record["id"])
        self.assertEqual(current["version"], 2)
        before_values = (current["current"], current["original"], current["verified"], current["state"])
        response = self.client.post(f'/analysis/{record["id"]}', data={
            "csrf": self.token, "record_version": "2", "included": "0", "reason": "非業務採樣",
        })
        self.assertEqual(response.status_code, 302)
        excluded = store.get(self.path, record["id"])
        self.assertEqual((excluded["analysis_included"], excluded["analysis_exclusion_reason"]), (0, "非業務採樣"))
        self.assertEqual((excluded["current"], excluded["original"], excluded["verified"], excluded["state"]),
                         before_values)

        matrix = self.client.get("/records?year=2026&view=matrix").get_data(as_text=True)
        self.assertIn("矩陣 0 組", matrix)
        self.assertIn("已排除分析，不計入矩陣及趨勢", matrix)
        self.assertIn("#1", self.client.get("/records?view=excluded").get_data(as_text=True))
        self.assertEqual(self.client.get("/records?view=process&start=2026-01&end=2026-01").status_code, 200)
        report = self.client.get("/reports?start=2026-01&end=2026-01").get_data(as_text=True)
        self.assertIn("手動排除紀錄 1 筆", report)
        exported = self.client.get("/records.csv").get_data(as_text=True)
        self.assertIn("analysis_included", exported)
        self.assertIn("非業務採樣", exported)

        stale = self.client.post(f'/analysis/{record["id"]}', data={
            "csrf": self.token, "record_version": "2", "included": "1", "reason": "過期版還原",
        })
        self.assertEqual(stale.status_code, 409)
        restored = self.client.post(f'/analysis/{record["id"]}', data={
            "csrf": self.token, "record_version": str(excluded["version"]),
            "included": "1", "reason": "已重新核對",
        })
        self.assertEqual(restored.status_code, 302)
        after = store.get(self.path, record["id"])
        self.assertEqual((after["analysis_included"], after["state"]), (1, "confirmed"))
        self.assertEqual(after["current"], before_values[0])
        self.assertEqual(self.client.get("/records?view=excluded").status_code, 200)

    def test_process_batch_reparse_only_targets_exact_checkbox_combo(self):
        exact_note = "monitoring_type: 來源多選原文「製程監測＋人員監測」；依明確組合分類為製程監測"
        exact = [{"values": dict(self.values), "source_location": "Table 1 row 2",
                  "source_text": "exact", "warnings": [exact_note]}]
        unknown_values = dict(self.values, monitoring_type="")
        unknown = [{"values": unknown_values, "source_location": "Table 1 row 2",
                    "source_text": "unknown", "warnings": ["monitoring_type: 勾選數量為 3，保留待核對"]}]
        store.add_import(self.path, "exact.docx", b"exact source", exact, "0.1.4")
        store.add_import(self.path, "unknown.docx", b"unknown source", unknown, "0.1.4")

        def parse_saved(_folder, source):
            return ((b"exact source", exact) if source["name"] == "exact.docx"
                    else (b"unknown source", unknown))

        with patch("em_mvp.app.parse_saved_source", side_effect=parse_saved):
            response = self.client.post("/reparse-process-batch", data={"csrf": self.token})
        self.assertEqual(response.status_code, 200)
        self.assertIn("動態檢視 2 個舊版本來源，明確組合命中 1 個來源", response.get_data(as_text=True))
        source_versions = {source["name"]: source["latest_parser_version"] for source in store.sources(self.path)}
        self.assertEqual(source_versions["exact.docx"], "0.1.7")
        self.assertEqual(source_versions["unknown.docx"], "0.1.4")

    def test_process_day_drilldown_only_shows_crr_eligible_records(self):
        eligible = dict(self.values, room="R1", point_id="eligible-A")
        out_of_scope = dict(self.values, room="R1", grade="B", point_id="grade-B")
        store.add_manual(self.path, eligible)
        store.add_manual(self.path, out_of_scope)

        response = self.client.get(
            "/records?view=process-day&day=2026-01-02&site=一廠&operator=ABC")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("eligible-A", html)
        self.assertNotIn("grade-B", html)

    def test_process_sample_drilldown_uses_exact_normalized_cell_ids_and_shows_current_and_raw(self):
        valid = dict(self.values, grade="Grade A", cfu_count="9", result_raw="3(1mold)")
        missing_operator = dict(valid, operator="", cfu_count="5", result_raw="5(1mold)")
        included = self.import_process_record("settle-source.docx", valid)
        self.import_process_record("missing-operator.docx", missing_operator)

        matrix = self.client.get("/records?view=process&start=2026-01&end=2026-02&site=%E4%B8%80%E5%BB%A0")
        self.assertEqual(matrix.status_code, 200)
        self.assertIn("GRADE A", matrix.get_data(as_text=True))
        detail = self.client.get(
            "/records?view=process-samples&month=2026-01&site=%E4%B8%80%E5%BB%A0&method=%E8%90%BD%E8%8F%8C%E6%B3%95"
            "&room=&grade=GRADE+A&point_id=P1&unit=CFU%2Fplate&start=2026-01&end=2026-02")
        self.assertEqual(detail.status_code, 200)
        page = detail.get_data(as_text=True)
        self.assertIn(f"#{included['id']}", page)
        self.assertIn("settle-source.docx", page)
        self.assertNotIn("missing-operator.docx", page)
        self.assertIn("目前 CFU：9", page)
        self.assertIn("結果原文（目前值）：3(1mold)", page)
        self.assertIn("start=2026-01&amp;end=2026-02", page)

    def test_process_person_month_drilldown_includes_comparable_and_pending_source_rows(self):
        day_one_settle = dict(self.values, sample_date="2026-01-02", method="落菌法",
                              point_id="settle", cfu_count="0", result_raw="0")
        day_one_contact = dict(self.values, sample_date="2026-01-02", method="培養皿接觸法",
                               point_id="contact-pending", cfu_count="", result_type="less_than",
                               result_raw="<1")
        day_two_contact = dict(self.values, sample_date="2026-01-03", method="培養皿接觸法",
                               point_id="contact-valid", cfu_count="2", result_raw="2")
        self.import_process_record("settle-source.docx", day_one_settle)
        self.import_process_record("pending-source.docx", day_one_contact)
        self.import_process_record("contact-source.docx", day_two_contact)

        matrix = self.client.get("/records?view=process&start=2026-01&end=2026-02&site=%E4%B8%80%E5%BB%A0")
        page = matrix.get_data(as_text=True)
        self.assertIn("view=process-person-month&amp;month=2026-01", page)
        self.assertIn("start=2026-01&amp;end=2026-02", page)
        detail = self.client.get(
            "/records?view=process-person-month&month=2026-01&site=%E4%B8%80%E5%BB%A0"
            "&operator=ABC&start=2026-01&end=2026-02")
        self.assertEqual(detail.status_code, 200)
        detail_page = detail.get_data(as_text=True)
        for filename in ("settle-source.docx", "pending-source.docx", "contact-source.docx"):
            self.assertIn(filename, detail_page)
        self.assertIn("待核對／不計分母", detail_page)
        back_link = html.unescape(next(link for link in detail_page.split('href="')
                                       if link.startswith("/records?view=process&")))
        self.assertIn("start=2026-01", back_link)
        self.assertIn("end=2026-02", back_link)
        self.assertIn("site=%E4%B8%80%E5%BB%A0", back_link)

    def test_process_matrix_has_independent_scrollbars_and_details_remain_normal_width(self):
        matrix = self.client.get("/records?view=process&start=2026-01&end=2026-02")
        page = matrix.get_data(as_text=True)
        self.assertIn('<main class="matrix-page">', page)
        self.assertIn('aria-label="製程採樣矩陣上方水平捲動條"', page)
        self.assertIn('aria-label="製程 CRR 矩陣上方水平捲動條"', page)
        self.assertEqual(page.count('class="matrix-top-scroll"'), 2)
        self.assertIn("bottom.scrollWidth", page)
        self.assertIn("bottom.clientWidth", page)
        detail = self.client.get(
            "/records?view=process-day&day=2026-01-02&site=%E4%B8%80%E5%BB%A0&operator=ABC"
            "&start=2026-01&end=2026-02")
        detail_page = detail.get_data(as_text=True)
        self.assertIn('<main class="">', detail_page)
        self.assertNotIn('class="matrix-top-scroll"', detail_page)
        self.assertIn("start=2026-01&amp;end=2026-02", detail_page)

    def test_all_site_process_drilldowns_preserve_empty_return_scope(self):
        self.import_process_record("all-site.docx", self.values)
        matrix = self.client.get("/records?view=process&start=2026-01&end=2026-02")
        links = [html.unescape(value) for value in re.findall(r'href="([^"]+)"',
                                                              matrix.get_data(as_text=True))]
        targets = {
            "process-samples": next(link for link in links if "view=process-samples" in link),
            "process-person-month": next(link for link in links if "view=process-person-month" in link),
            "process-day": next(link for link in links if "view=process-day" in link),
        }
        for view, target in targets.items():
            query = parse_qs(urlparse(target).query, keep_blank_values=True)
            self.assertEqual(query.get("return_site"), [""])
            page = self.client.get(target)
            self.assertEqual(page.status_code, 200, view)
            back = next(html.unescape(link) for link in re.findall(
                r'href="([^"]+)"', page.get_data(as_text=True))
                if "view=process&" in html.unescape(link))
            returned = parse_qs(urlparse(back).query, keep_blank_values=True)
            self.assertEqual(returned.get("site"), [""])
            self.assertEqual(returned.get("start"), ["2026-01"])
            self.assertEqual(returned.get("end"), ["2026-02"])


if __name__ == "__main__":
    unittest.main()
