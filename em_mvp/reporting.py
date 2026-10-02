"""Deterministic review accuracy and monthly summaries; no inferred limits."""

from datetime import date
import re
import unicodedata

from .domain import FIELDS, normalize_method


def _text(value):
    return "" if value is None else str(value).strip()


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
    points, days, months = {}, {}, set()
    for record in records:
        if record.get("state") != "confirmed":
            continue
        current = record.get("current", {})
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

        operator = _text(current.get("operator"))
        if (
            grade.upper() not in ("A", "GRADE A", "A級")
            or monitoring_type != "製程監測"
            or method not in ("落菌法", "培養皿接觸法")
            or operator.upper() in ("", "N/A", "NA", "N.A.", "NONE", "NULL", "-", "—", "不適用", "無")
        ):
            continue
        person_day = days.setdefault((site, day, operator), {
            "excluded": False, "positive": False,
        })
        if count is None:
            person_day["excluded"] = True
        elif count > 0:
            person_day["positive"] = True

    people = {}
    for (site, day, operator), person_day in days.items():
        key = (site, operator, day[:7])
        person = people.setdefault(key, {
            "site": site, "operator": operator, "month": day[:7],
            "positive_days": 0, "total_days": 0, "excluded_days": 0,
        })
        if person_day["excluded"]:
            person["excluded_days"] += 1
        else:
            person["total_days"] += 1
            person["positive_days"] += person_day["positive"]
    for person in people.values():
        person["crr"] = (
            100 * person["positive_days"] / person["total_days"]
            if person["total_days"] else None
        )
    return {
        "points": [points[key] for key in sorted(points)],
        "people": [people[key] for key in sorted(people)],
        "months": sorted(months),
    }
