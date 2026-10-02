import unittest

from em_mvp.reporting import FIELDS, field_accuracy, monthly_report


def record(**changes):
    current = {
        "sample_date": "2026-07-01", "site": "一廠",
        "monitoring_type": "製程監測", "method": "落菌法", "room": "GTP4",
        "grade": "A", "point_id": "P01", "operator": "王甲",
        "result_type": "count", "cfu_count": "0", "unit": "CFU/plate",
    }
    current.update(changes)
    return {"state": "confirmed", "current": current}


class ReportingTests(unittest.TestCase):
    def test_accuracy_tracks_original_and_pending_without_manual_bias(self):
        rows = field_accuracy([
            {"original": {"point_id": " P01 "}, "current": {"point_id": "P01"},
             "verified": {"point_id": "checked"}},
            {"original": {"point_id": "P02"}, "current": {"point_id": "P03"},
             "verified": {"point_id": "checked"}},
            {"original": {"point_id": "P04"}, "current": {"point_id": "P05"}},
            {"verified": {"point_id": "not_applicable"}},
            {"is_manual": True, "original": {}, "current": {"point_id": "P06"},
             "verified": {"point_id": "checked"}},
        ])
        point = next(row for row in rows if row["field"] == "point_id")
        self.assertEqual(point, {
            "field": "point_id", "total": 3, "checked": 2, "correct": 1,
            "incorrect": 1, "pending": 1, "accuracy": 50,
            "not_applicable": 1, "manual_excluded": 1,
        })
        date_row = next(row for row in rows if row["field"] == "sample_date")
        self.assertEqual(date_row["pending"], 4)
        self.assertIsNone(date_row["accuracy"])

    def test_no_data_and_confirmed_zero_are_distinct(self):
        empty = field_accuracy([])
        self.assertEqual(len(empty), len(FIELDS))
        self.assertTrue(all(row["accuracy"] is None and row["total"] == 0 for row in empty))
        self.assertEqual(monthly_report([]), {"points": [], "people": [], "months": []})
        report = monthly_report([record()])
        self.assertEqual(report["points"][0]["n"], 1)
        self.assertEqual(report["points"][0]["cfu"], 0)
        self.assertEqual(report["people"][0]["crr"], 0)

    def test_multiple_samples_and_methods_make_one_person_day(self):
        report = monthly_report([
            record(point_id="P01", cfu_count="0"),
            record(point_id="P02", cfu_count="2"),
            record(point_id="P01", method="培養皿接觸法", cfu_count=3),
            record(sample_date="2026-07-02", cfu_count=0),
        ])
        self.assertEqual(len(report["points"]), 3)
        self.assertEqual(sum(row["n"] for row in report["points"]), 4)
        self.assertEqual(sum(row["cfu"] for row in report["points"]), 5)
        person = report["people"][0]
        self.assertEqual((person["positive_days"], person["total_days"], person["crr"]), (1, 2, 50))

    def test_nonnumeric_result_excludes_entire_person_day(self):
        report = monthly_report([
            record(point_id="P01", cfu_count="2"),
            record(point_id="P02", result_type="tntc", cfu_count="999"),
            record(sample_date="2026-07-02", result_type="missing", cfu_count=""),
            record(sample_date="2026-07-03", result_type="less_than", cfu_count="1"),
        ])
        person = report["people"][0]
        self.assertEqual((person["total_days"], person["excluded_days"]), (0, 3))
        self.assertIsNone(person["crr"])
        self.assertEqual(sum(row["excluded"] for row in report["points"]), 3)
        self.assertEqual(sum(row["n"] for row in report["points"]), 1)

    def test_same_numeric_point_different_room_grade_and_unit_stay_separate(self):
        report = monthly_report([
            record(point_id="1", room="C23", grade="A", cfu_count="1"),
            record(point_id="1", room="C24", grade="A", cfu_count="2"),
            record(point_id="1", room="C23", grade="B", cfu_count="3"),
            record(point_id="1", room="C23", grade="A", unit="CFU/m3", cfu_count="4"),
        ])
        self.assertEqual(len(report["points"]), 4)
        values = {(p["room"], p["grade"], p["unit"]): p["cfu"] for p in report["points"]}
        self.assertEqual(values[("C23", "A", "CFU/plate")], 1)
        self.assertEqual(values[("C24", "A", "CFU/plate")], 2)
        self.assertEqual(values[("C23", "B", "CFU/plate")], 3)
        self.assertEqual(values[("C23", "A", "CFU/m3")], 4)

    def test_confirmed_finger_plate_alias_is_included_in_contact_crr(self):
        report = monthly_report([
            record(method="指壓", cfu_count="2"),
            record(method="培養皿接觸法", cfu_count="0"),
        ])
        self.assertEqual(len(report["points"]), 1)
        self.assertEqual(report["points"][0]["method"], "培養皿接觸法")
        self.assertEqual(report["points"][0]["n"], 2)
        person = report["people"][0]
        self.assertEqual((person["positive_days"], person["total_days"], person["crr"]), (1, 1, 100))

    def test_count_validation_and_isolator_without_operator(self):
        report = monthly_report([
            record(cfu_count=value, operator="N/A")
            for value in (0, " 12 ", -1, "-2", "1.0", 1.0, True, None, "TNTC", "<1")
        ])
        self.assertEqual(report["people"], [])
        point = report["points"][0]
        self.assertEqual((point["n"], point["cfu"], point["positive"], point["excluded"]), (2, 12, 1, 8))

    def test_unconfirmed_invalid_dates_and_other_grade_do_not_bias_crr(self):
        pending = record(cfu_count="99")
        pending["state"] = "pending"
        report = monthly_report([
            pending, record(sample_date="2026-02-30"), record(sample_date="20260701"),
            record(grade="B", cfu_count="9"), record(sample_date="2026-08-01", cfu_count="0"),
        ])
        self.assertEqual(report["months"], ["2026-07", "2026-08"])
        self.assertEqual(len(report["people"]), 1)
        self.assertEqual(report["people"][0]["month"], "2026-08")
        self.assertEqual(report["people"][0]["crr"], 0)


if __name__ == "__main__":
    unittest.main()
