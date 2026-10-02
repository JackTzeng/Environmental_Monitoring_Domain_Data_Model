"""Deterministic review accuracy and monthly summaries; no inferred limits."""

from datetime import date
import re
import unicodedata

from .domain import FIELDS, normalize_method


def _text(value):
    return "" if value is None else str(value).strip()


def _included(record):
    return record.get("analysis_included", 1) not in (0, False, "0")


def _isolator(current):
    return "isolator" in (_text(current.get("room")) + " " + _text(current.get("point_id"))).casefold()


def _process_pending_reasons(record):
    current = record.get("current", {})
    reasons = []
    factory = _text(current.get("site"))
    operator = _text(current.get("operator")).upper()
    method = normalize_method(current.get("method", ""))
    grade = _text(current.get("grade")).upper()
    if factory not in ("一廠", "三廠"):
        reasons.append("廠別待補")
    if not _text(current.get("point_id")):
        reasons.append("採樣點位待補")
    if not _text(current.get("unit")):
        reasons.append("單位待補")
    if method not in ("落菌法", "培養皿接觸法"):
        reasons.append("方法不在落菌／接觸範圍")
    if grade not in ("A", "GRADE A", "A級"):
        reasons.append("非 Grade A 或 Grade 待補")
    if not valid_process_date(_text(current.get("sample_date"))):
        reasons.append("實際採樣日待補")
    if operator in {"", "N/A", "NA", "N.A.", "NONE", "NULL", "-", "—", "不適用", "無"}:
        reasons.append("操作者待補")
    fields = {"site:": "site", "operator:": "operator", "point_id:": "point_id",
              "sample_date:": "sample_date", "method:": "method", "grade:": "grade",
              "monitoring_type:": "monitoring_type"}
    unresolved = []
    for warning in record.get("warnings", []):
        warning_text = _text(warning)
        prefix = next((key for key in fields if warning_text.casefold().startswith(key)), "")
        if not prefix:
            continue
        if prefix == "monitoring_type:" and "來源多選原文" in warning_text and "分類為製程監測" in warning_text:
            continue
        if record.get("verified", {}).get(fields[prefix]) in ("checked", "not_applicable"):
            continue
        unresolved.append(warning_text)
    if unresolved:
        reasons.append("來源欄位有待核對衝突")
    return reasons


def field_accuracy(records: list[dict]) -> list[dict]:
    """Compare original extraction with manually checked values, as percentages.

    Manual entries and explicitly inapplicable fields do not assess the parser.
    An unchecked correction remains pending; a checked correction is incorrect
    extraction, rather than a retrospectively correct parser result.
    """
    result = []
    for field in FIELDS:
        total = checked = correct = not_applicable = manual_excluded = 0
        for record in records:
            status = record.get("verified", {}).get(field)
            if record.get("is_manual"):
                manual_excluded += 1
                continue
            if status == "not_applicable":
                not_applicable += 1
                continue
            total += 1
            if status == "checked":
                checked += 1
                correct += _text(record.get("original", {}).get(field)) == _text(
                    record.get("current", {}).get(field)
                )
        result.append({
            "field": field, "total": total, "checked": checked,
            "correct": correct, "incorrect": checked - correct,
            "pending": total - checked,
            "not_applicable": not_applicable, "manual_excluded": manual_excluded,
            "accuracy": 100 * correct / checked if checked else None,
        })
    return result


def _count(current):
    if _text(current.get("result_type")) != "count":
        return None
    value = current.get("cfu_count")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = _text(value)
    return int(text) if re.fullmatch(r"[0-9]+", text) else None


def _matrix_signature(record):
    current = record.get("current", {})
    kind = _text(current.get("result_type"))
    value = ("count", _count(current)) if kind == "count" else (
        kind, _text(current.get("result_raw")).casefold()
    )
    return value, _text(current.get("alert_raw")), _text(current.get("action_raw"))


def _matrix_display(record):
    current = record.get("current", {})
    kind = _text(current.get("result_type"))
    raw = _text(current.get("result_raw"))
    if kind == "count":
        count = _count(current)
        annotated = re.fullmatch(r"\s*([0-9]+)\s*[（(].*[）)]\s*", raw)
        if count is not None and annotated:
            if count == int(annotated.group(1)):
                return raw
            return f"{count}（目前結果原文：{raw}）"
        return str(count) if count is not None else (raw or _text(current.get("cfu_count")) or "待核對")
    if kind == "missing":
        return raw or "缺值"
    if kind == "tntc":
        return raw or "TNTC"
    if kind == "less_than":
        return raw or "小於值"
    if kind == "not_applicable":
        return raw or "N/A"
    return raw or "未辨認"


def _parse_limit(value):
    raw = _text(value)
    if not raw:
        return "missing", None, raw
    normalized = unicodedata.normalize("NFKC", raw).replace("≦", "≤")
    if normalized.strip().casefold() in {"na", "n/a", "n.a.", "not applicable", "不適用"}:
        return "not_applicable", None, raw
    match = re.fullmatch(
        r"(?:(<=|≤|<)\s*)?([0-9]+(?:\.[0-9]+)?)\s*(?:CFU(?:\s*/\s*(?:m3|plate|皿))?)?",
        normalized.strip(), re.I,
    )
    if not match:
        return "unknown", None, raw
    operator, threshold = match.groups()
    return "valid", (operator or "max", float(threshold)), raw


def _limit_exceeded(count, parsed_limit):
    kind, parsed, _ = parsed_limit
    if kind != "valid":
        return False
    operator, threshold = parsed
    return count >= threshold if operator == "<" else count > threshold


def _limit_status(count, alert_raw, action_raw, conflict=False):
    if conflict:
        return "review", "需核對"
    if count is None:
        return "review", "需核對"
    alert = _parse_limit(alert_raw)
    action = _parse_limit(action_raw)
    action_exceeded = _limit_exceeded(count, action)
    alert_exceeded = _limit_exceeded(count, alert)
    if action_exceeded:
        return "action", "行動"
    if alert_exceeded:
        if action[0] in ("missing", "unknown"):
            return "review", "需核對"
        return "alarm", "警戒"
    if any(limit[0] in ("missing", "unknown") for limit in (alert, action)):
        return "review", "需核對"
    if not any(limit[0] == "valid" for limit in (alert, action)):
        return "review", "需核對"
    return "normal", "正常"


def monthly_matrix(records: list[dict], year: int) -> list[dict]:
    """Build a twelve-month preview; choose the earliest sample date, never a sum."""
    groups = {}
    for record in records:
        if not _included(record):
            continue
        current = record.get("current", {})
        sample_date = _text(current.get("sample_date"))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", sample_date):
            continue
        try:
            parsed_date = date.fromisoformat(sample_date)
        except ValueError:
            continue
        if parsed_date.year != year:
            continue
        key = (
            _text(current.get("site")), _text(current.get("monitoring_type")),
            normalize_method(current.get("method", "")), _text(current.get("room")),
            _text(current.get("grade")), _text(current.get("point_id")), _text(current.get("unit")),
        )
        group = groups.setdefault(key, {"key": key, "records": []})
        group["records"].append(record)

    output = []
    for key, group in sorted(groups.items()):
        site, monitoring_type, method, room, grade, point_id, unit = key
        samples = sorted(group["records"], key=lambda r: (r["current"]["sample_date"], r["id"]))
        def limit_values(field):
            values = []
            for record in samples:
                value = _text(record.get("current", {}).get(field)) or "未填"
                if value not in values:
                    values.append(value)
            return values

        row = {
            "key": key, "site": site, "monitoring_type": monitoring_type,
            "method": method, "room": room, "grade": grade,
            "point_id": point_id, "unit": unit,
            "alarm_values": limit_values("alert_raw"), "action_values": limit_values("action_raw"),
            "missing_location": not room or not point_id, "months": {}, "trend_values": [],
        }
        for month in range(1, 13):
            monthly = [r for r in samples if int(r["current"]["sample_date"][5:7]) == month]
            if not monthly:
                row["months"][month] = {
                    "has_samples": False, "display": "—", "sample_count": 0,
                    "first_date": "", "first_conflict": False, "conflict_dates": [],
                    "pending": False, "numeric": None, "status": "", "status_text": "",
                }
                row["trend_values"].append(None)
                continue
            by_date = {}
            for record in monthly:
                by_date.setdefault(record["current"]["sample_date"], []).append(record)
            first_date = min(by_date)
            first_records = by_date[first_date]
            conflict_dates = [
                sample_day for sample_day, day_records in sorted(by_date.items())
                if len({_matrix_signature(record) for record in day_records}) > 1
            ]
            first_conflict = first_date in conflict_dates
            representative = sorted(first_records, key=lambda r: r["id"])[0]
            current = representative.get("current", {})
            numeric = None if first_conflict else _count(current)
            status, status_text = _limit_status(
                numeric, current.get("alert_raw"), current.get("action_raw"), first_conflict,
            )
            row["months"][month] = {
                "has_samples": True,
                "display": "需核對" if first_conflict else _matrix_display(representative),
                "sample_count": len(monthly), "first_date": first_date,
                "first_day_count": len(first_records), "first_conflict": first_conflict,
                "conflict_dates": conflict_dates,
                "pending": any(record.get("state") == "draft" for record in monthly),
                "numeric": numeric, "status": status, "status_text": status_text,
                "limit_date": first_date, "limit_source": representative.get("source_name", ""),
                "limit_source_id": representative.get("source_id", ""),
                "alert_raw": _text(current.get("alert_raw")),
                "action_raw": _text(current.get("action_raw")),
            }
            row["trend_values"].append(numeric)
        output.append(row)
    return output


def monthly_report(records: list[dict]) -> dict:
    """Summarize confirmed numeric samples without merging sampling methods.

    Personnel CRR uses Grade A process monitoring person-days with either
    settle plates or contact plates. Any nonnumeric result makes that entire
    person-day excluded. This proposed indicator is not regulatory approval.
    """
    points, months = {}, set()
    for record in records:
        if record.get("state") != "confirmed" or not _included(record):
            continue
        current = record.get("current", {})
        if _text(current.get("monitoring_type")) == "製程監測" and _isolator(current):
            continue
        if _text(current.get("monitoring_type")) == "製程監測" and _process_pending_reasons(record):
            continue
        day = _text(current.get("sample_date"))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
            continue
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        month = day[:7]
        months.add(month)
        site = _text(current.get("site"))
        monitoring_type = _text(current.get("monitoring_type"))
        method = normalize_method(current.get("method", ""))
        room = _text(current.get("room"))
        grade = _text(current.get("grade"))
        point_id = _text(current.get("point_id"))
        unit = _text(current.get("unit"))
        point_key = (site, monitoring_type, method, room, grade, point_id, unit, month)
        point = points.setdefault(point_key, {
            "site": site, "monitoring_type": monitoring_type, "method": method,
            "room": room, "grade": grade, "point_id": point_id, "unit": unit, "month": month,
            "n": 0, "cfu": 0, "positive": 0, "excluded": 0,
        })
        count = _count(current)
        if count is None:
            point["excluded"] += 1
        else:
            point["n"] += 1
            point["cfu"] += count
            point["positive"] += count > 0

    confirmed = [r for r in records if r.get("state") == "confirmed" and _included(r)]
    process = process_matrices(confirmed, sorted(months))
    people = {}
    for group in process["crr_rows"]:
        for month, values in group["months"].items():
            people[(group["site"], group["operator"], month)] = {
                "site": group["site"], "operator": group["operator"], "month": month,
                "positive_days": values["positive_days"], "total_days": values["total_days"],
                "excluded_days": values["excluded_days"], "crr": values["crr"],
            }
    return {
        "points": [points[key] for key in sorted(points)],
        "people": [people[key] for key in sorted(people)],
        "months": sorted(months),
    }


def process_matrices(records: list[dict], months: list[str], site: str = "") -> dict:
    """Build reviewable process sampling and personnel CRR matrices.

    The input may contain draft records for an explicitly labelled preview. Only
    records with an exact process classification and explicit, conflict-free
    context are aggregated. Isolator device qualification is intentionally
    pending until a source-row TRUE field is defined.
    """
    month_set = set(months)
    sampling = {}
    method_totals = {}
    period_totals = {}
    person_days = {}
    pending, isolator_pending = [], []
    isolator_groups = {}
    excluded_count = 0
    process_records = [r for r in records if r.get("state") != "void" and
                       _text(r.get("current", {}).get("monitoring_type")) == "製程監測"]

    def scoped(record):
        current = record.get("current", {})
        raw_day = _text(current.get("sample_date"))
        month = raw_day[:7] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_day) else ""
        try:
            date.fromisoformat(raw_day)
        except ValueError:
            month = ""
        return (not months or month in month_set), month

    for record in process_records:
        current = record.get("current", {})
        in_range, month = scoped(record)
        is_isolator = _isolator(current)
        method = normalize_method(current.get("method", ""))
        point_id, room = _text(current.get("point_id")), _text(current.get("room"))
        factory, operator = _text(current.get("site")), _text(current.get("operator"))
        if site and factory and factory != site:
            continue
        if not _included(record):
            if in_range and (not site or factory == site):
                excluded_count += 1
            continue
        day = _text(current.get("sample_date"))
        grade = _text(current.get("grade")).upper()
        unit = _text(current.get("unit"))
        if is_isolator:
            item = {"record": record, "month": month, "site": factory,
                    "method": method, "room": room, "point_id": point_id, "unit": unit,
                    "reason": "來源列 TRUE 資格尚無欄位定義；暫不計入設備採樣統計。"}
            if in_range:
                isolator_pending.append(item)
                key = (factory, method, room, _text(current.get("grade")), point_id, unit, month)
                group = isolator_groups.setdefault(key, {"site": factory, "method": method,
                    "room": room, "grade": _text(current.get("grade")), "point_id": point_id,
                    "unit": unit, "month": month, "pending_count": 0, "record_ids": []})
                group["pending_count"] += 1
                group["record_ids"].append(record.get("id"))
            continue

        reasons = _process_pending_reasons(record)
        if reasons:
            if in_range or not month:
                pending.append({"record": record, "reason": "、".join(dict.fromkeys(reasons)), "month": month})
            continue
        if not in_range or (site and factory != site):
            continue

        count = _count(current)
        key = (factory, method, room, grade, point_id, unit)
        row = sampling.setdefault(key, {"site": factory, "method": method, "room": room,
            "grade": grade, "point_id": point_id, "unit": unit, "months": {}})
        cell = row["months"].setdefault(month, {"sample_count": 0, "numeric_count": 0,
            "cfu_sum": 0, "non_addable": 0, "draft_count": 0, "record_ids": []})
        cell["sample_count"] += 1
        cell["record_ids"].append(record.get("id"))
        cell["draft_count"] += record.get("state") != "confirmed"
        if count is None:
            cell["non_addable"] += 1
        else:
            cell["numeric_count"] += 1
            cell["cfu_sum"] += count

        subtotal = method_totals.setdefault((factory, method, unit), {"site": factory,
            "method": method, "unit": unit, "months": {}})
        total_cell = subtotal["months"].setdefault(month, {"sample_count": 0, "numeric_count": 0,
            "cfu_sum": 0, "non_addable": 0})
        total_cell["sample_count"] += 1
        if count is None:
            total_cell["non_addable"] += 1
        else:
            total_cell["numeric_count"] += 1
            total_cell["cfu_sum"] += count
        period = period_totals.setdefault((factory, unit), {"site": factory, "unit": unit,
            "sample_count": 0, "numeric_count": 0, "cfu_sum": 0, "non_addable": 0})
        period["sample_count"] += 1
        if count is None:
            period["non_addable"] += 1
        else:
            period["numeric_count"] += 1
            period["cfu_sum"] += count

        key_day = (factory, operator, day)
        person_day = person_days.setdefault(key_day, {"site": factory, "operator": operator,
            "day": day, "month": month, "positive": False, "noncomparable": False,
            "draft": False, "record_ids": [], "methods": set()})
        person_day["record_ids"].append(record.get("id"))
        person_day["methods"].add(method)
        person_day["draft"] |= record.get("state") != "confirmed"
        if count is None:
            person_day["noncomparable"] = True
        elif count > 0:
            person_day["positive"] = True

    # A person-day with any non-comparable included sample is transparent but
    # contributes to neither A nor B, matching the accepted pending policy.
    crr_groups = {}
    day_rows = []
    for person_day in person_days.values():
        day_rows.append({**person_day, "methods": sorted(person_day["methods"]),
                         "record_ids": sorted(i for i in person_day["record_ids"] if i is not None),
                         "status": "待核對" if person_day["noncomparable"] else "可計算"})
        key = (person_day["site"], person_day["operator"])
        group = crr_groups.setdefault(key, {"site": key[0], "operator": key[1], "months": {},
            "total": {"positive_days": 0, "total_days": 0, "excluded_days": 0,
                      "draft_days": 0}})
        cell = group["months"].setdefault(person_day["month"], {
            "positive_days": 0, "total_days": 0, "excluded_days": 0, "draft_days": 0})
        cell["draft_days"] += person_day["draft"]
        group["total"]["draft_days"] += person_day["draft"]
        if person_day["noncomparable"]:
            cell["excluded_days"] += 1
            group["total"]["excluded_days"] += 1
        else:
            cell["total_days"] += 1
            group["total"]["total_days"] += 1
            cell["positive_days"] += person_day["positive"]
            group["total"]["positive_days"] += person_day["positive"]
    for group in crr_groups.values():
        for cell in [*group["months"].values(), group["total"]]:
            cell["crr"] = (100 * cell["positive_days"] / cell["total_days"]
                           if cell["total_days"] else None)

    month_totals = {}
    for month in months:
        a = sum(group["months"].get(month, {}).get("positive_days", 0) for group in crr_groups.values())
        b = sum(group["months"].get(month, {}).get("total_days", 0) for group in crr_groups.values())
        excluded = sum(group["months"].get(month, {}).get("excluded_days", 0) for group in crr_groups.values())
        month_totals[month] = {"positive_days": a, "total_days": b, "excluded_days": excluded,
                               "crr": 100 * a / b if b else None}

    return {
        "months": months,
        "sampling_rows": [sampling[key] for key in sorted(sampling)],
        "method_totals": [method_totals[key] for key in sorted(method_totals)],
        "period_totals": [period_totals[key] for key in sorted(period_totals)],
        "crr_rows": [crr_groups[key] for key in sorted(crr_groups)],
        "crr_month_totals": month_totals,
        "person_days": sorted(day_rows, key=lambda row: (row["site"], row["operator"], row["day"])),
        "pending": pending,
        "isolator_pending": isolator_pending,
        "isolator_groups": [isolator_groups[key] for key in sorted(isolator_groups)],
        "excluded_count": excluded_count,
    }


def valid_process_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False
