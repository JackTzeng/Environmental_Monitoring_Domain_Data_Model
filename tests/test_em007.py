import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from em_mvp import store
from em_mvp.domain import FIELDS
from em_mvp.importers import _make_record, _selected_box, parse_file
from em_mvp.reporting import field_accuracy, monthly_matrix, monthly_report, process_matrices


def sample(**changes):
    record_id = changes.pop("id", 1)
    analysis_included = changes.pop("analysis_included", 1)
    exclusion_reason = changes.pop("analysis_exclusion_reason", "")
    current = {field: "" for field in FIELDS}
    current.update(sample_date="2026-06-03", site="一廠", monitoring_type="製程監測",
                   method="落菌法", room="GTP4", grade="A", point_id="P01",
                   operator="王甲", result_raw="0", result_type="count", cfu_count="0",
                   unit="CFU/plate")
    current.update(changes)
    return {"id": record_id, "state": "confirmed", "analysis_included": analysis_included,
            "analysis_exclusion_reason": exclusion_reason, "current": current, "original": dict(current),
            "verified": {}, "warnings": [], "source_name": "sample.docx", "source_location": "Table 1 row 2"}


def minimal_docx(paragraphs, headers, rows):
    return minimal_docx_tables(paragraphs, [(headers, rows)])


def minimal_docx_tables(paragraphs, tables):
    def paragraph(value):
        return f"<w:p><w:r><w:t>{escape(value)}</w:t></w:r></w:p>"

    table_xml = "".join(
        "<w:tbl>" + "".join(
            "<w:tr>" + "".join(f"<w:tc>{paragraph(value)}</w:tc>" for value in row) + "</w:tr>"
            for row in [headers, *rows]
        ) + "</w:tbl>"
        for headers, rows in tables
    )
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(paragraph(value) for value in paragraphs) + table_xml + "</w:body></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", document)
    return output.getvalue()


class EM007Tests(unittest.TestCase):
    def test_checkbox_combo_is_exact_and_process_does_not_infer_factory_from_room(self):
        warnings = []
        self.assertEqual(_selected_box("■製程監測 ■人員監測 □無塵衣月監測", "monitoring_type", warnings), "製程監測")
        self.assertIn("來源多選原文", warnings[0])
        warnings = []
        self.assertEqual(_selected_box("■製程監測 ■人員監測 ■其他", "monitoring_type", warnings), "")
        self.assertIn("待核對", warnings[0])

        values = {field: "" for field in FIELDS}
        values.update(monitoring_type="製程監測", room="C06", point_id="P01", sample_date="2026-06-03")
        parsed = _make_record(values, "table 1 row 2", "test.docx", [])
        self.assertEqual(parsed["values"]["site"], "")
        self.assertTrue(any("不依房間推定" in warning for warning in parsed["warnings"]))

    def test_unknown_three_box_word_keeps_filename_process_guard(self):
        content = minimal_docx(
            ["類型：■製程監測 ■人員監測 ■無塵衣月監測"],
            ["房間", "點位", "Grade", "結果", "單位"],
            [["C06D", "落菌：P01", "A", "0", "CFU/plate"]],
        )
        row = parse_file("製程監控-report.docx", content)[0]
        self.assertEqual(row["values"]["monitoring_type"], "待分類")
        self.assertEqual(row["values"]["site"], "")
        self.assertTrue(any("不依房間推定" in warning for warning in row["warnings"]))

    def test_multiple_file_operators_do_not_last_win_and_row_context_can_resolve(self):
        common = ["類型：■製程監測 ■人員監測", "廠別：三廠",
                  "操作者：AAA", "操作者：BBB"]
        unassigned = parse_file("製程監控-report.docx", minimal_docx(
            common, ["房間", "點位", "Grade", "結果", "單位"],
            [["GTP4", "落菌：P01", "A", "0", "CFU/plate"]],
        ))[0]
        self.assertEqual(unassigned["values"]["operator"], "")
        self.assertTrue(any("多位操作者" in warning for warning in unassigned["warnings"]))

        row_scoped = parse_file("製程監控-report.docx", minimal_docx(
            common, ["房間", "操作者", "點位", "Grade", "結果", "單位"],
            [["GTP4", "AAA", "落菌：P01", "A", "0", "CFU/plate"],
             ["GTP4", "BBB", "落菌：P02", "A", "0", "CFU/plate"]],
        ))
        self.assertEqual([row["values"]["operator"] for row in row_scoped], ["AAA", "BBB"])
        self.assertFalse(any(any("多位操作者" in warning for warning in row["warnings"])
                             for row in row_scoped))

    def test_table_local_operator_metadata_does_not_leak_to_another_table(self):
        tables = [
            (["操作者", "AAA"], [["點位", "P01"]]),
            (["房間", "點位", "Grade", "結果"], [["GTP4", "P02", "A", "0"]]),
        ]
        local_only = parse_file("製程監控-report.docx", minimal_docx_tables([], tables))
        self.assertEqual(len(local_only), 1)
        self.assertEqual(local_only[0]["values"]["point_id"], "P02")
        self.assertEqual(local_only[0]["values"]["operator"], "")

        document_level = parse_file(
            "製程監控-report.docx", minimal_docx_tables(["操作者：DOC"], tables))
        self.assertEqual(document_level[0]["values"]["operator"], "DOC")

    def test_operator_cell_with_multiple_people_is_pending_without_row_duplication(self):
        row = parse_file("製程監控-report.docx", minimal_docx(
            ["類型：■製程監測 ■人員監測", "廠別：一廠"],
            ["房間", "操作者", "點位", "Grade", "結果", "單位"],
            [["GTP4", "AAA、BBB", "落菌：P01", "A", "4", "CFU/plate"]],
        ))[0]
        self.assertEqual(row["values"]["operator"], "")
        self.assertIn("AAA、BBB", row["source_text"])
        self.assertTrue(any("多位操作者" in warning for warning in row["warnings"]))
        report = process_matrices([{
            "id": 1, "current": row["values"], "state": "confirmed", "warnings": row["warnings"],
            "verified": {}, "analysis_included": 1,
        }], ["2026-06"])
        self.assertEqual(report["crr_rows"], [])
        self.assertEqual(len(report["pending"]), 1)

    def test_multiple_operator_cell_without_method_prefix_is_blank_and_pending(self):
        row = parse_file("製程監控-report.docx", minimal_docx(
            ["類型：■製程監測 ■人員監測", "廠別：一廠", "方法：落菌法", "採樣日期：2026-06-03"],
            ["房間", "操作者", "點位", "Grade", "結果", "單位"],
            [["GTP4", "AAA、BBB", "P01", "A", "4", "CFU/plate"]],
        ))[0]
        self.assertEqual(row["values"]["operator"], "")
        self.assertIn("AAA、BBB", row["source_text"])
        self.assertTrue(any("多位操作者" in warning for warning in row["warnings"]))
        report = process_matrices([{
            "id": 1, "current": row["values"], "state": "confirmed", "warnings": row["warnings"],
            "verified": {}, "analysis_included": 1,
        }], ["2026-06"])
        self.assertEqual(report["crr_rows"], [])
        self.assertEqual(len(report["pending"]), 1)

    def test_point_operator_conflict_is_blank_and_excluded_from_crr(self):
        row = parse_file("製程監控-report.docx", minimal_docx(
            ["類型：■製程監測 ■人員監測", "廠別：一廠", "操作者：BBB"],
            ["房間", "點位", "Grade", "結果", "單位"],
            [["GTP4", "指壓：操作後 AAA（右手）", "A", "4", "CFU/plate"]],
        ))[0]
        self.assertEqual(row["values"]["operator"], "")
        self.assertTrue(any("操作者欄位" in warning and "點位原文" in warning
                            for warning in row["warnings"]))
        result = process_matrices([{
            "id": 1, "current": row["values"], "state": "confirmed", "warnings": row["warnings"],
            "verified": {}, "analysis_included": 1,
        }], ["2026-06"])
        self.assertEqual(result["crr_rows"], [])
        self.assertTrue(any(item["record"]["id"] == 1 for item in result["pending"]))

    def test_analysis_toggle_is_versioned_reversible_and_preserves_review_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            values = {field: "" for field in FIELDS}
            values.update(sample_date="2026-06-03", site="一廠", monitoring_type="製程監測",
                          method="落菌法", grade="A", point_id="P01", operator="王甲",
                          result_raw="0", result_type="count", cfu_count="0", unit="CFU/plate")
            parsed = [{"values": values, "source_location": "Table 1 row 2",
                       "source_text": "raw value", "warnings": []}]
            store.add_import(path, "sample.docx", b"sample source", parsed, "0.1.4")
            before = store.records(path)[0]
            self.assertEqual(before["analysis_included"], 1)
            store.update(path, before["id"], before["version"], values,
                         {"cfu_count": "checked"}, "confirmed", "逐欄核對來源")
            before = store.get(path, before["id"])
            self.assertTrue(store.set_analysis_inclusion(path, before["id"], before["version"],
                                                         False, "無效採樣點位"))
            excluded = store.get(path, before["id"])
            self.assertEqual((excluded["analysis_included"], excluded["analysis_exclusion_reason"]),
                             (0, "無效採樣點位"))
            self.assertEqual((excluded["state"], excluded["current"], excluded["original"], excluded["verified"]),
                             (before["state"], before["current"], before["original"], before["verified"]))
            self.assertEqual(len(store.history(path, before["id"])), 2)
            with self.assertRaises(store.StaleRecord):
                store.set_analysis_inclusion(path, before["id"], before["version"], True, "舊版本操作")
            store.set_analysis_inclusion(path, before["id"], excluded["version"], True, "重新核對後恢復")
            restored = store.get(path, before["id"])
            self.assertEqual(restored["analysis_included"], 1)
            self.assertEqual(restored["analysis_exclusion_reason"], "")
            self.assertEqual(restored["state"], "confirmed")
            self.assertEqual([h["reason"] for h in store.history(path, before["id"])],
                             ["重新核對後恢復", "無效採樣點位", "逐欄核對來源"])
            self.assertTrue(list((path / "backups").glob("*.sqlite3")))

    def test_reparse_cannot_restore_manual_exclusion_or_change_source_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            store.initialize(path)
            values = {field: "" for field in FIELDS}
            values.update(sample_date="2026-06-03", site="一廠", monitoring_type="製程監測",
                          method="落菌法", grade="A", point_id="P01", operator="王甲",
                          result_raw="0", result_type="count", cfu_count="0", unit="CFU/plate")
            parsed = [{"values": values, "source_location": "Table 1 row 2",
                       "source_text": "raw value", "warnings": []}]
            store.add_import(path, "sample.docx", b"sample source", parsed, "0.1.4")
            before = store.records(path)[0]
            store.update(path, before["id"], before["version"], values,
                         {"cfu_count": "checked"}, "confirmed", "逐欄核對來源")
            before = store.get(path, before["id"])
            store.set_analysis_inclusion(path, before["id"], before["version"], False, "來源不符範圍")
            before = store.get(path, before["id"])
            new_values = dict(values, cfu_count="2", result_raw="2")
            updated = [{**parsed[0], "values": new_values}]
            result = store.reparse_source(path, before["source_id"], b"sample source", updated, "0.1.6")
            after = store.get(path, before["id"])
            self.assertGreater(result["conflicts"], 0)
            self.assertEqual((after["analysis_included"], after["analysis_exclusion_reason"]), (0, "來源不符範圍"))
            self.assertEqual((after["original"], after["verified"], after["state"]),
                             (before["original"], before["verified"], before["state"]))
            self.assertEqual(after["current"], before["current"])
            self.assertEqual((after["source_location"], after["sha256"]),
                             (before["source_location"], before["sha256"]))
            reparse_change = next(h for h in store.history(path, before["id"]) if h["actor"] == "解析器")
            self.assertEqual(json.loads(reparse_change["after_json"])["analysis_included"], 0)

    def test_analysis_exclusion_filters_matrix_reports_but_not_accuracy_or_raw_data(self):
        included = sample(cfu_count="0")
        excluded = sample(id=2, point_id="P02", operator="王乙", cfu_count="9",
                          result_raw="9", analysis_included=0,
                          analysis_exclusion_reason="非業務採樣")
        matrix = monthly_matrix([included, excluded], 2026)
        self.assertEqual({row["point_id"] for row in matrix}, {"P01"})
        report = monthly_report([included, excluded])
        self.assertEqual(sum(row["cfu"] for row in report["points"]), 0)
        self.assertEqual(sum(row["total_days"] for row in report["people"]), 1)
        self.assertEqual(len([r for r in [included, excluded] if r["analysis_included"] == 0]), 1)
        accuracy = field_accuracy([{
            "original": {"point_id": "P01"}, "current": {"point_id": "P01"},
            "verified": {"point_id": "checked"}, "analysis_included": 0,
        }])
        point = next(item for item in accuracy if item["field"] == "point_id")
        self.assertEqual((point["checked"], point["correct"], point["accuracy"]), (1, 1, 100))

    def test_process_monthly_sums_methods_separates_units_and_deduplicates_person_days(self):
        rows = [
            sample(id=1, cfu_count="0", point_id="settle"),
            sample(id=2, cfu_count="2", result_raw="2", method="培養皿接觸法", point_id="contact"),
            sample(id=3, cfu_count="4", result_raw="4", site="三廠", point_id="settle"),
            sample(id=4, cfu_count="8", result_raw="8", operator="王丙", unit="CFU/m3", point_id="P01"),
            sample(id=5, cfu_count="99", result_raw="99", room="Isolator A", point_id="Isolator-1",
                   operator="", site="一廠"),
            sample(id=6, result_type="less_than", cfu_count="", result_raw="<1", point_id="P02", operator="王乙"),
            sample(id=7, cfu_count="7", result_raw="7", point_id="P03", analysis_included=0,
                   analysis_exclusion_reason="排除測試"),
        ]
        result = process_matrices(rows, ["2026-06"])
        self.assertEqual(len(result["isolator_pending"]), 1)
        self.assertEqual(result["isolator_groups"][0]["pending_count"], 1)
        self.assertEqual(len(result["sampling_rows"]), 5)
        self.assertEqual(sum(total["sample_count"] for total in result["period_totals"]), 5)
        self.assertEqual(sum(total["non_addable"] for total in result["period_totals"]), 1)
        self.assertEqual(result["excluded_count"], 1)
        # Same site/person/day across settle and contact is one positive B.
        one = next(row for row in result["crr_rows"] if row["site"] == "一廠" and row["operator"] == "王甲")
        self.assertEqual((one["total"]["positive_days"], one["total"]["total_days"]), (1, 1))
        # Non-comparable result excludes that person-day; the raw row remains represented in the sample matrix.
        pending_day = next(day for day in result["person_days"] if day["operator"] == "王乙" and day["day"] == "2026-06-03")
        self.assertEqual(pending_day["status"], "待核對")
        self.assertEqual(result["crr_month_totals"]["2026-06"]["total_days"], 3)
        self.assertIsNone(process_matrices([], ["2026-06"])["crr_month_totals"]["2026-06"]["crr"])

    def test_unknown_site_or_operator_remains_pending_not_guessed(self):
        row = sample(site="", operator="")
        row["warnings"] = ["site: 製程來源未明確提供廠別；不依房間推定，待核對"]
        result = process_matrices([row], ["2026-06"])
        self.assertEqual(result["sampling_rows"], [])
        self.assertEqual(result["crr_rows"], [])
        self.assertIn("廠別待補", result["pending"][0]["reason"])
        self.assertIn("操作者待補", result["pending"][0]["reason"])

    def test_known_checkbox_provenance_note_does_not_block_reviewed_process_row(self):
        row = sample(cfu_count="2", result_raw="2")
        row["warnings"] = ["monitoring_type: 來源多選原文「製程監測＋人員監測」；依明確組合分類為製程監測"]
        result = process_matrices([row], ["2026-06"])
        self.assertEqual(len(result["sampling_rows"]), 1)
        self.assertEqual(result["sampling_rows"][0]["months"]["2026-06"]["cfu_sum"], 2)
        self.assertEqual(result["pending"], [])

    def test_selected_factory_scopes_pending_isolator_and_exclusion_counts(self):
        rows = [
            sample(id=1, site="一廠", point_id="A1"),
            sample(id=2, site="三廠", point_id="B1"),
            sample(id=3, site="", point_id="U1", warnings=["site: 廠別待補"]),
            sample(id=4, site="一廠", operator="", point_id="A-pending"),
            sample(id=5, site="三廠", operator="", point_id="B-pending"),
            sample(id=6, site="一廠", room="Isolator A", point_id="Iso-A", operator=""),
            sample(id=7, site="三廠", room="Isolator B", point_id="Iso-B", operator=""),
            sample(id=8, site="", room="Isolator ?", point_id="Iso-U", operator=""),
            sample(id=9, site="一廠", analysis_included=0, point_id="A-excluded"),
            sample(id=10, site="三廠", analysis_included=0, point_id="B-excluded"),
            sample(id=11, site="", analysis_included=0, point_id="U-excluded"),
            sample(id=12, site="一廠", monitoring_type="例行環測", analysis_included=0),
        ]
        result = process_matrices(rows, ["2026-06"], "一廠")
        self.assertEqual({row["site"] for row in result["sampling_rows"]}, {"一廠"})
        pending_ids = {item["record"]["id"] for item in result["pending"]}
        self.assertTrue({3, 4} <= pending_ids)  # unknown factory stays unassigned and visible
        self.assertFalse({2, 5} & pending_ids)  # known other factory is outside scope
        isolator_ids = {item["record"]["id"] for item in result["isolator_pending"]}
        self.assertEqual(isolator_ids, {6, 8})
        self.assertEqual({group["site"] for group in result["isolator_groups"]}, {"一廠", ""})
        self.assertEqual(result["excluded_count"], 1)  # only included-analysis scope for selected factory


if __name__ == "__main__":
    unittest.main()
