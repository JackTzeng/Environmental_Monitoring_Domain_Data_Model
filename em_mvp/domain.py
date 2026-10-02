"""Visible field dictionary and exact method aliases, shared by input and output."""
FIELDS = (
    "sample_date", "site", "monitoring_type", "method", "room", "grade", "point_id",
    "operator", "batch_no", "result_raw", "result_type", "cfu_count", "unit",
    "organism_name", "alert_raw", "action_raw",
)
METHOD_ALIASES = {
    "落菌": "落菌法", "落菌法": "落菌法",
    "指壓": "培養皿接觸法", "指壓法": "培養皿接觸法", "培養皿": "培養皿接觸法",
    "培養皿接觸": "培養皿接觸法",
    "表面接觸": "培養皿接觸法", "表面接觸法": "培養皿接觸法", "接觸法": "培養皿接觸法",
    "培養皿接觸法": "培養皿接觸法", "空氣取樣": "空氣採樣法",
    "空氣取樣法": "空氣採樣法", "空氣採樣": "空氣採樣法", "空氣採樣法": "空氣採樣法",
}


def normalize_method(value):
    text = str(value or "").strip()
    return METHOD_ALIASES.get(text, text)
