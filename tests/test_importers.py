import io
import unittest
import zipfile

from em_mvp.importers import FIELDS, parse_file


def word_file(rows, paragraphs=()):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    from xml.sax.saxutils import escape
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    table = "".join("<w:tr>" + "".join(
        f"<w:tc><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:tc>" for text in row
    ) + "</w:tr>" for row in rows)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body>{body}<w:tbl>{table}</w:tbl></w:body></w:document>')
    return data.getvalue()


class ImporterTests(unittest.TestCase):
    def test_word_preserves_special_results_and_trace(self):
        data = word_file([
            ["監測位置", "Grade", "結果(CFU)", "Alarm Lv(CFU)", "Action Lv(CFU)"],
            ["a12:C01", "C", "0", "<5", "<10"],
            ["a13:C01", "C", "<1", "<5", "<10"],
            ["a14:C01", "C", "TNTC", "<5", "<10"],
            ["a15:C01", "C", "N/A", "<5", "<10"],
            ["a16:C01", "C", "2(1 mold)", "<5", "<10"],
            ["a17:C01", "C", "", "<5", "<10"],
        ], ["監測日期：2025/01/27", "監測方式：■空氣取樣 □落菌法"])
        records = parse_file("一廠-環境微生物監控報告.docx", data)
        self.assertEqual([r["values"]["result_type"] for r in records],
                         ["count", "less_than", "tntc", "not_applicable", "count", "missing"])
        self.assertEqual([r["values"]["cfu_count"] for r in records], ["0", "", "", "", "2", ""])
        self.assertEqual(records[0]["values"]["sample_date"], "2025-01-27")
        self.assertEqual(records[0]["values"]["site"], "一廠")
        self.assertEqual(records[0]["values"]["point_id"], "a12")
        self.assertEqual(records[0]["values"]["room"], "C01")
        self.assertEqual(records[0]["values"]["method"], "空氣採樣法")
        self.assertEqual(records[0]["source_location"], "Word table 1 row 2")
        self.assertEqual(set(records[0]["values"]), set(FIELDS))
        self.assertTrue(all(isinstance(value, str) for value in records[0]["values"].values()))

    def test_csv_real_header_newlines_and_check_state(self):
        data = ('一廠環測製測 Raw data\n年,月,日,檢測目的,點位,"總菌數\n(CFU)","菌落數\n(CFU)",核,Grade\n'
                '2025,1,27,環測,a12,3,1,FALSE,C\n'
                '2025,2,30,環測,a13,<1,,TRUE,C\n').encode("utf-8-sig")
        records = parse_file("one_factory.csv", data)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["values"]["sample_date"], "2025-01-27")
        self.assertEqual(records[0]["values"]["cfu_count"], "3")
        self.assertEqual(records[0]["values"]["monitoring_type"], "例行環測")
        self.assertEqual(records[0]["values"]["site"], "一廠")
        self.assertTrue(any("不是 TRUE" in warning for warning in records[0]["warnings"]))
        self.assertTrue(any("總菌數與菌落數不同" in warning for warning in records[0]["warnings"]))
        self.assertEqual(records[1]["values"]["sample_date"], "")
        self.assertEqual(records[1]["values"]["cfu_count"], "")

    def test_multiple_word_result_columns_are_reviewed(self):
        data = word_file([["監測位置", "結果總菌", "結果黴菌"], ["a12", "3", "1"]])
        record = parse_file("一廠.docx", data)[0]
        self.assertEqual(record["values"]["result_type"], "unknown")
        self.assertEqual(record["values"]["cfu_count"], "")
        self.assertTrue(any("多個結果" in warning for warning in record["warnings"]))
        identical = word_file([["監測位置", "結果(CFU)", "結果(CFU)"], ["a12", "3", "3"]])
        self.assertEqual(parse_file("report.docx", identical)[0]["values"]["cfu_count"], "")

    def test_controls_and_exceptional_reports_wait_for_review(self):
        data = word_file([["監測位置", "結果(CFU)"], ["NegativeControl", "0"]])
        record = parse_file("污染後環境微生物監控報告.docx", data)[0]
        self.assertEqual(record["values"]["monitoring_type"], "待分類")
        self.assertTrue(any("對照組" in warning for warning in record["warnings"]))

    def test_room_labels_are_separated_from_air_point_identifiers(self):
        positions = ["C19B_GTP1-6-女更衣室(一)：01", "C11_GTP1：A", "C19B_GTP1：01 不確定"]
        data = word_file([["監測位置", "結果(CFU)"], *[[position, "0"] for position in positions]])
        records = parse_file("三廠-環境微生物監控報告.docx", data)
        self.assertEqual(records[0]["values"]["room"], "C19B")
        self.assertEqual(records[0]["values"]["point_id"], "01")
        self.assertEqual(records[1]["values"]["room"], "C11")
        self.assertEqual(records[1]["values"]["point_id"], "A")
        self.assertIn(positions[0], records[0]["source_text"])
        self.assertEqual(records[2]["values"]["point_id"], positions[2])
        self.assertEqual(records[2]["values"]["room"], "")

    def test_merged_cells_do_not_duplicate_rows(self):
        from xml.etree import ElementTree as ET
        from em_mvp.importers import NS, W
        data = word_file([["監測位置", "Grade", "結果(CFU)"],
                          ["指壓：操作後ABC -左手", "A", "0"],
                          ["指壓：操作後ABC -右手", "", "0"]])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            doc = ET.fromstring(archive.read("word/document.xml"))
        table_rows = doc.findall(".//w:tr", NS)
        for row, value in [(table_rows[1], "restart"), (table_rows[2], "continue")]:
            cell = row.findall("./w:tc", NS)[1]
            properties = ET.SubElement(cell, W + "tcPr")
            ET.SubElement(properties, W + "vMerge", {W + "val": value})
        merged = io.BytesIO()
        with zipfile.ZipFile(merged, "w") as archive:
            archive.writestr("word/document.xml", ET.tostring(doc))
        records = parse_file("製程監控.docx", merged.getvalue())
        self.assertEqual(len(records), 2)
        self.assertEqual([r["values"]["grade"] for r in records], ["A", "A"])
        self.assertEqual(records[0]["values"]["operator"], "ABC")
        self.assertEqual(records[0]["values"]["method"], "培養皿接觸法")
        self.assertIn("指壓：", records[0]["source_text"])

    def test_unrecognized_word_and_unsupported_file_fail(self):
        with self.assertRaises(ValueError):
            parse_file("report.docx", word_file([["something", "other"], ["x", "y"]]))
        with self.assertRaises(ValueError):
            parse_file("report.doc", b"old word")

    def test_xlsx_readonly_dates_and_formulas(self):
        from datetime import datetime
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["日期", "點位", "結果(CFU)"])
        sheet.append([datetime(2025, 1, 27), "a12", 2])
        sheet.append([datetime(2025, 1, 27), "a13", "=1+1"])
        data = io.BytesIO()
        workbook.save(data)
        records = parse_file("一廠.xlsx", data.getvalue())
        self.assertEqual(records[0]["values"]["cfu_count"], "2")
        self.assertEqual(records[0]["values"]["sample_date"], "2025-01-27")
        self.assertEqual(records[1]["values"]["cfu_count"], "")
        self.assertTrue(any("Excel 公式" in warning for warning in records[1]["warnings"]))

    def test_archive_bombs_and_macros_are_rejected_before_reading(self):
        import struct
        def claimed_size(member, size):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as archive:
                archive.writestr(member, b"small")
            payload = bytearray(data.getvalue())
            central_directory = payload.index(b"PK\x01\x02")
            struct.pack_into("<I", payload, central_directory + 24, size)
            return bytes(payload)
        with self.assertRaisesRegex(ValueError, "80 MB"):
            parse_file("large.xlsx", claimed_size("xl/workbook.xml", 80_000_001))
        with self.assertRaisesRegex(ValueError, "XML 過大"):
            parse_file("large.docx", claimed_size("word/document.xml", 20_000_001))
        macro = io.BytesIO()
        with zipfile.ZipFile(macro, "w") as archive:
            archive.writestr("xl/vbaProject.bin", b"macro")
        with self.assertRaisesRegex(ValueError, "VBA 巨集"):
            parse_file("renamed.xlsx", macro.getvalue())
        with self.assertRaises(ValueError):
            parse_file("macro.xlsm", macro.getvalue())


if __name__ == "__main__":
    unittest.main()
