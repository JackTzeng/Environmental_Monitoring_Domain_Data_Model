import io
import json
import tempfile
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


if __name__ == "__main__":
    unittest.main()
