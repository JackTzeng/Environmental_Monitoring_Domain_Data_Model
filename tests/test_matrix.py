import html
import io
import re
import tempfile
import unittest
from pathlib import Path

from em_mvp import store
from em_mvp.app import create_app
from em_mvp.domain import FIELDS
from em_mvp.reporting import field_accuracy, monthly_matrix, monthly_report


def sample(record_id, day, result, count="", *, kind="count", site="三廠", monitoring_type="例行環測",
           method="空氣採樣法", room="C11", grade="C", point="A", unit="CFU/m3",
           alert="<50", action="<100", state="draft"):
    current = {field: "" for field in FIELDS}
    current.update(sample_date=day, site=site, monitoring_type=monitoring_type, method=method,
                   room=room, grade=grade, point_id=point, unit=unit,
                   result_raw=result, result_type=kind, cfu_count=count,
                   alert_raw=alert, action_raw=action)
    return {"id": record_id, "source_id": record_id, "source_name": f"source-{record_id}.docx",
            "source_location": "Word table 1 row 2", "source_text": result, "sha256": str(record_id),
            "parser_version": "0.1.1", "original": dict(current), "current": current,
            "verified": {}, "warnings": [], "state": state, "is_manual": False}


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.app = create_app(self.path / "data")
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def insert(self, day, result, count="", *, kind="count", name=None, **kwargs):
        values = {field: "" for field in FIELDS}
        values.update(sample(1, day, result, count, kind=kind, **kwargs)["current"])
        filename = name or f"source-{day}-{result}-{kwargs.get('point', 'A')}.docx"
        source = f"{filename}-{len(store.records(self.path / 'data'))}".encode("utf-8")
        added = store.add_import(self.path / "data", filename, source, [{
            "values": values, "source_location": "Word table 1 row 2",
            "source_text": result, "warnings": [],
        }], "0.1.1")
        if kwargs.get("state", "draft") != "draft":
            record = store.records(self.path / "data")[0]
            store.update(self.path / "data", record["id"], record["version"], record["current"],
                         {}, kwargs["state"], "測試狀態")
        return added

    def test_b1_default_database_is_year_matrix_and_includes_pending(self):
        self.insert("2026-06-03", "2", "2")
        page = self.client.get("/records").get_data(as_text=True)
        self.assertIn("資料庫逐月點位矩陣", page)
        self.assertIn("待核對", page)
        self.assertIn("01月", page)
        self.assertIn("12月", page)
        self.assertIn("2", page)
        self.assertIn("原始明細", page)

    def test_b2_earliest_calendar_date_zero_and_no_sample_are_distinct(self):
        matrix = monthly_matrix([
            sample(1, "2026-06-16", "8", "8"),
            sample(2, "2026-06-03", "2", "2"),
            sample(3, "2026-04-09", "0", "0"),
        ], 2026)
        row = matrix[0]
        self.assertEqual((row["months"][6]["first_date"], row["months"][6]["display"],
                          row["months"][6]["sample_count"]), ("2026-06-03", "2", 2))
        self.assertEqual((row["months"][4]["display"], row["months"][4]["numeric"]), ("0", 0))
        self.assertEqual((row["months"][5]["display"], row["months"][5]["has_samples"]), ("—", False))

    def test_b3_same_day_value_and_limit_conflicts_and_special_values(self):
        matrix = monthly_matrix([
            sample(1, "2026-06-03", "2", "2"), sample(2, "2026-06-03", "3", "3"),
            sample(3, "2026-07-02", "2", "2", alert="<50"),
            sample(4, "2026-07-02", "2", "2", alert="<40"),
            sample(5, "2026-08-02", "TNTC", kind="tntc"),
            sample(6, "2026-08-20", "5", "5"),
            sample(7, "2026-09-01", "<1", kind="less_than"),
            sample(8, "2026-10-01", "N/A", kind="not_applicable"),
            sample(9, "2026-11-01", "", kind="missing"),
        ], 2026)[0]
        self.assertTrue(matrix["months"][6]["first_conflict"])
        self.assertEqual(matrix["months"][6]["display"], "需核對")
        self.assertEqual(matrix["months"][7]["conflict_dates"], ["2026-07-02"])
        self.assertEqual((matrix["months"][8]["display"], matrix["months"][8]["numeric"]), ("TNTC", None))
        self.assertEqual((matrix["months"][9]["display"], matrix["months"][9]["numeric"]), ("<1", None))
        self.assertEqual(matrix["months"][10]["display"], "N/A")
        self.assertEqual(matrix["months"][11]["display"], "缺值")
        self.assertEqual(matrix["months"][12]["display"], "—")

    def test_b4_month_cell_links_to_every_sample_and_source(self):
        self.insert("2026-06-03", "2", "2", name="early.docx")
        self.insert("2026-06-16", "8", "8", name="late.docx")
        page = self.client.get("/records").get_data(as_text=True)
        match = re.search(r'href="(/records\?view=month&amp;year=2026&amp;month=06[^"]*)"', page)
        self.assertIsNotNone(match)
        detail = self.client.get(html.unescape(match.group(1))).get_data(as_text=True)
        self.assertIn("2026-06-03", detail)
        self.assertIn("2026-06-16", detail)
        self.assertIn("early.docx", detail)
        self.assertIn("late.docx", detail)
        self.assertIn("檢視／修正", detail)

    def test_b5_filters_year_site_method_type_and_status_and_excludes_void_by_default(self):
        self.insert("2025-06-03", "1", "1", name="old.docx")
        self.insert("2026-06-03", "2", "2", name="air.docx")
        self.insert("2026-06-03", "3", "3", name="contact.docx",
                    method="培養皿接觸法", unit="CFU/plate", state="confirmed")
        self.insert("2026-06-03", "4", "4", name="void.docx", point="Z", state="void")
        default = self.client.get("/records").get_data(as_text=True)
        self.assertIn("空氣採樣法", default)
        self.assertNotIn("Z", default)
        year = self.client.get("/records?year=2025").get_data(as_text=True)
        self.assertIn(">1</a>", year)
        self.assertNotIn(">2</a>", year)
        filtered = self.client.get("/records?year=2026&site=%E4%B8%89%E5%BB%A0&monitoring_type=%E4%BE%8B%E8%A1%8C%E7%92%B0%E6%B8%AC&method=%E5%9F%B9%E9%A4%8A%E7%9A%BF%E6%8E%A5%E8%A7%B8%E6%B3%95&state=confirmed").get_data(as_text=True)
        self.assertIn("培養皿接觸法", filtered)
        self.assertNotIn("空氣採樣法", filtered)
        void = self.client.get("/records?year=2026&state=void").get_data(as_text=True)
        self.assertIn("C11－Z", void)

    def test_b6_correction_updates_matrix_preserves_original_and_output_stays_confirmed_only(self):
        self.insert("2026-06-03", "2", "2", name="corrected.docx")
        record = store.records(self.path / "data")[0]
        before = self.client.get("/records").get_data(as_text=True)
        self.assertIn(">2</a>", before)
        current = dict(record["current"])
        current.update(result_raw="8", cfu_count="8")
        store.update(self.path / "data", record["id"], record["version"], current,
                     {"cfu_count": "checked"}, "confirmed", "依原始來源修正並核對")
        changed = store.get(self.path / "data", record["id"])
        after = self.client.get("/records").get_data(as_text=True)
        report = self.client.get("/reports?start=2026-06&end=2026-06").get_data(as_text=True)
        accuracy = {item["field"]: item for item in field_accuracy([changed])}
        self.assertIn(">8</a>", after)
        self.assertEqual((changed["original"]["cfu_count"], changed["current"]["cfu_count"]), ("2", "8"))
        self.assertEqual(monthly_report([changed])["points"][0]["cfu"], 8)
        self.assertIn("8", report)
        self.assertEqual((accuracy["cfu_count"]["checked"], accuracy["cfu_count"]["accuracy"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
