"""Three screens: input, inspect/review database, monthly output."""
import csv
import io
import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from markupsafe import Markup

from . import store
from .importers import PARSER_VERSION, parse_file
from .folder_import import (
    FolderImportInProgress, folder_import_status, latest_folder_import, start_folder_import,
)
from .domain import normalize_method
from .reporting import FIELDS, field_accuracy, monthly_matrix, monthly_report


LABELS = dict(zip(FIELDS, (
    "採樣日期", "廠別", "監測類型", "方法", "房間", "Grade", "採樣點位", "操作者",
    "批次", "原始結果", "結果類型", "CFU 數值", "單位", "菌種", "Alert 原文", "Action 原文",
)))
DEFAULT_DATA = Path.home() / "Documents" / "Codex" / "Environmental_Monitoring_MVP-data"


def validate(values, confirmed=False):
    if values["sample_date"]:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", values["sample_date"]):
            raise ValueError("日期請填 YYYY-MM-DD。")
        date.fromisoformat(values["sample_date"])
    if values["result_type"] not in ("", "count", "tntc", "less_than", "not_applicable", "missing", "unknown"):
        raise ValueError("未知結果類型。")
    if values["cfu_count"] and not re.fullmatch(r"[0-9]+", values["cfu_count"]):
        raise ValueError("CFU 只接受非負整數；特殊結果請保留原文。")
    if values["result_type"] != "count" and values["cfu_count"]:
        raise ValueError("特殊結果不可填一般 CFU 數值。")
    if confirmed:
        for key in ("sample_date", "site", "monitoring_type", "method", "point_id", "result_type", "unit"):
            if not values[key] or values[key] in ("待分類", "方法未註明"):
                raise ValueError(f"確認前請補上 {LABELS[key]}。")
        if values["result_type"] == "count" and not values["cfu_count"]:
            raise ValueError("可計數結果須填 CFU，0 可以保留。")


def candidate_key(record):
    c = record["current"]
    # Optional operator/batch values can be absent in one of the two sources.
    # Such absence must not hide a Word/Sheet duplicate candidate.
    keys = ("sample_date", "site", "monitoring_type", "method", "room", "point_id")
    return tuple(normalize_method(c.get(k)) if k == "method" else c.get(k, "").strip() for k in keys)


def reparse_saved_source(data_dir, row):
    source_path = Path(data_dir) / "sources" / (row["sha256"] + Path(row["name"]).suffix.lower())
    if not source_path.is_file() or source_path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("來源副本不存在或超過 25 MB；未重新解析。")
    content = source_path.read_bytes()
    context = json.loads(row["context_json"] or "{}")
    if not isinstance(context, dict):
        context = {}
    if not context.get("source_prefix"):
        with store.closing(store.connection(data_dir)) as db:
            first_record = db.execute(
                "SELECT source_location FROM records WHERE source_id=? ORDER BY id LIMIT 1",
                (row["id"],),
            ).fetchone()
        if first_record:
            prefix = re.sub(r"(?:Word table \d+ row \d+|CSV row \d+|Sheet .+ row \d+)$", "",
                            first_record["source_location"])
            if prefix != first_record["source_location"]:
                context["source_prefix"] = prefix
    parsed = parse_file(row["name"], content, context)
    prefix = context.get("source_prefix", "")
    if prefix:
        for item in parsed:
            item["source_location"] = prefix + item["source_location"]
    return store.reparse_source(data_dir, row["id"], content, parsed, PARSER_VERSION)


def months_between(start, end):
    if not start or not end:
        return []
    if not re.fullmatch(r"\d{4}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}", end):
        raise ValueError("月份格式錯誤。")
    a, b = date.fromisoformat(start + "-01"), date.fromisoformat(end + "-01")
    if a > b or (b.year - a.year) * 12 + b.month - a.month > 120:
        raise ValueError("請選擇先後正確、最多 10 年的期間。")
    out = []
    while a <= b:
        out.append(a.strftime("%Y-%m"))
        a = date(a.year + (a.month == 12), a.month % 12 + 1, 1)
    return out


def valid_sample_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def chart(months, values, title):
    """Small native SVG: real zero is plotted; absent month breaks the line."""
    if not months:
        return Markup("<p>尚無月份資料。</p>")
    top = max([v for v in values if v is not None] or [1]) or 1
    xs = [55 + i * 620 / max(len(months) - 1, 1) for i in range(len(months))]
    bits = [f'<svg viewBox="0 0 740 245" role="img" aria-label="{escape(title)}">',
            '<path d="M55 20 V195 H700" fill="none" stroke="#94a3b8"/>',
            f'<text x="8" y="24">{top:g}</text><text x="24" y="198">0</text>']
    previous = None
    for x, month, value in zip(xs, months, values):
        if value is None:
            previous = None
        else:
            y = 195 - 170 * value / top
            if previous:
                bits.append(f'<path d="M{previous[0]} {previous[1]} L{x} {y}" stroke="#167a8c" stroke-width="3"/>')
            bits.extend((f'<circle cx="{x}" cy="{y}" r="4" fill="#167a8c"/>',
                         f'<text x="{x}" y="{max(14,y-9)}" text-anchor="middle">{value:g}</text>'))
            previous = (x, y)
        bits.append(f'<text x="{x}" y="223" text-anchor="middle">{month}</text>')
    return Markup("".join(bits) + "</svg>")


def point_sparkline(values, title):
    numeric = [value for value in values if value is not None]
    if not numeric:
        return Markup(f'<span aria-label="{escape(title)}">—</span>')
    top = max(numeric) or 1
    xs = [3 + i * 142 / 11 for i in range(12)]
    bits = [f'<svg viewBox="0 0 148 32" role="img" aria-label="{escape(title)}">']
    previous = None
    for x, value in zip(xs, values):
        if value is None:
            previous = None
            continue
        y = 27 - 22 * value / top
        if previous:
            bits.append(f'<path d="M{previous[0]:.1f} {previous[1]:.1f} L{x:.1f} {y:.1f}" fill="none" stroke="#167a8c" stroke-width="2"/>')
        bits.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="#167a8c"/>')
        previous = (x, y)
    return Markup("".join(bits) + "</svg>")


def csv_response(name, headers, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(headers)
    for row in rows:
        safe = []
        for value in row:
            text = "" if value is None else str(value)
            # Excel must not execute an imported note/name as a formula.
            safe.append("'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text)
        writer.writerow(safe)
    return Response("\ufeff" + out.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def create_app(data_dir=None):
    app = Flask(__name__)
    data_dir = Path(data_dir or os.environ.get("EM_MVP_DATA_DIR", DEFAULT_DATA))
    store.initialize(data_dir)
    secret = data_dir / "session.key"
    if not secret.exists():
        secret.write_text(secrets.token_hex(32), encoding="ascii")
    app.config.update(SECRET_KEY=secret.read_text(encoding="ascii"), MAX_CONTENT_LENGTH=25 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict", DATA_DIR=data_dir)
    app.jinja_env.globals.update(labels=LABELS, fields=FIELDS, version=PARSER_VERSION)

    @app.before_request
    def protect():
        if request.host.split(":")[0] not in ("127.0.0.1", "localhost"):
            abort(400, "此試用版僅供本機操作。")
        session.setdefault("csrf", secrets.token_hex(24))
        if request.method == "POST":
            supplied = request.form.get("csrf", "")
            if not secrets.compare_digest(supplied, session["csrf"]):
                abort(400, "請重新開啟頁面後再儲存。")
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                abort(400, "來源不符。")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/")
    def index():
        all_rows = store.records(data_dir)
        sources = store.sources(data_dir)
        return render_template("input.html", count=len(all_rows), data_dir=data_dir,
                               imports=store.import_history(data_dir),
                               sources=sources,
                               stale_source_count=sum(source["latest_parser_version"] != PARSER_VERSION
                                                      for source in sources),
                               folder_job=latest_folder_import(data_dir))

    @app.get("/health")
    def health():
        return {"app": "em-mvp", "version": "0.4.0", "parser_version": PARSER_VERSION}

    @app.post("/import")
    def import_files():
        site = request.form.get("site_context", "")
        if site not in ("", "一廠", "三廠"):
            abort(400, "未知廠別脈絡。")
        context = {"site": site} if site else {}
        for file in request.files.getlist("files"):
            if not file.filename:
                continue
            data = file.read()
            try:
                parsed = parse_file(file.filename, data, context)
                if not parsed:
                    raise ValueError("沒有可讀取的明細；未入庫。")
                for row in parsed:
                    row["values"] = {f: str(row["values"].get(f, "")) for f in FIELDS}
                count = store.add_import(data_dir, file.filename, data, parsed, PARSER_VERSION, context)
                detail = f"新增 {count} 筆待核對。" if count else "相同內容已匯入，沒有新增或覆蓋。"
                store.log_import(data_dir,file.filename,data,"imported" if count else "duplicate",detail)
                flash(f"{Path(file.filename).name}：{detail}")
            except (ValueError, OSError, KeyError, sqlite3.IntegrityError) as error:
                store.log_import(data_dir,file.filename,data,"error",str(error))
                flash(f"{Path(file.filename).name}：{error}")
        return redirect(url_for("database"))

    @app.post("/folder-import")
    def import_folder():
        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        site_context = request.form.get("site_context", "")
        if site_context not in ("", "一廠", "三廠"):
            if wants_json:
                return jsonify(error="未知廠別脈絡。"), 400
            flash("未知廠別脈絡。")
            return redirect(url_for("index"))
        try:
            job = start_folder_import(
                data_dir, request.form.get("folder_path", ""),
                request.form.get("include_sheets") == "on",
                {"site": site_context} if site_context else {},
            )
        except FolderImportInProgress as error:
            if wants_json:
                return jsonify(error=str(error), job_id=error.job_id), 409
            flash(str(error))
            return redirect(url_for("index"))
        except ValueError as error:
            if wants_json:
                return jsonify(error=str(error)), 400
            flash(str(error))
            return redirect(url_for("index"))
        if wants_json:
            return jsonify(job_id=job["id"]), 202
        flash("資料夾匯入已啟動；此頁會顯示掃描與處理進度。")
        return redirect(url_for("index"))

    @app.get("/folder-import/status/<job_id>")
    def folder_import_progress(job_id):
        job = folder_import_status(job_id, data_dir)
        return jsonify(job) if job else (jsonify(error="找不到此匯入工作。"), 404)

    @app.post("/manual")
    def manual():
        record_id = store.add_manual(data_dir, {f: "" for f in FIELDS})
        return redirect(url_for("edit", record_id=record_id))

    @app.get("/records")
    def database():
        all_rows = store.records(data_dir)
        view = request.args.get("view", "matrix")
        state = request.args.get("state", "")
        if state not in ("", "draft", "confirmed", "void"):
            abort(400, "未知核對狀態。")

        def state_matches(record):
            return record["state"] == state if state else record["state"] != "void"

        if view == "month":
            year = request.args.get("year", type=int)
            month = request.args.get("month", type=int)
            if not year or not month or not 1 <= month <= 12:
                abort(400, "月份參數錯誤。")
            target = f"{year:04d}-{month:02d}"
            target_key = (
                request.args.get("site", ""), request.args.get("monitoring_type", ""),
                normalize_method(request.args.get("method", "")), request.args.get("room", ""),
                request.args.get("grade", ""), request.args.get("point_id", ""), request.args.get("unit", ""),
            )
            rows = []
            for record in all_rows:
                current = record["current"]
                record_key = (
                    current.get("site", ""), current.get("monitoring_type", ""),
                    normalize_method(current.get("method", "")), current.get("room", ""),
                    current.get("grade", ""), current.get("point_id", ""), current.get("unit", ""),
                )
                if state_matches(record) and current.get("sample_date", "").startswith(target) and record_key == target_key:
                    rows.append(record)
            rows.sort(key=lambda record: (record["current"].get("sample_date", ""), record["id"]))
            label = " / ".join(value or "未填" for value in target_key)
            return render_template("database.html", view=view, rows=rows, state=state,
                                   year=year, month=month, point_label=label)

        if view == "detail":
            rows = [record for record in all_rows if state_matches(record)]
            page = max(1, request.args.get("page", 1, type=int))
            return render_template("database.html", view=view, rows=rows[(page-1)*100:page*100],
                                   total=len(rows), page=page, state=state)
        if view != "matrix":
            abort(400, "未知資料庫檢視模式。")

        dated_years = []
        for record in all_rows:
            if record["state"] == "void":
                continue
            sample_date = record["current"].get("sample_date", "")
            if valid_sample_date(sample_date):
                dated_years.append(date.fromisoformat(sample_date).year)
        years = sorted(set(dated_years), reverse=True)
        year = request.args.get("year", type=int) or (years[0] if years else date.today().year)
        base_rows = [record for record in all_rows if state_matches(record)]
        sites = sorted({record["current"].get("site", "") for record in base_rows} - {""})
        monitoring_types = sorted({record["current"].get("monitoring_type", "") for record in base_rows} - {""})
        methods = sorted({normalize_method(record["current"].get("method", "")) for record in base_rows} - {""})
        filtered = []
        for record in base_rows:
            current = record["current"]
            if (not request.args.get("site") or current.get("site", "") == request.args.get("site")) and \
               (not request.args.get("monitoring_type") or current.get("monitoring_type", "") == request.args.get("monitoring_type")) and \
               (not request.args.get("method") or normalize_method(current.get("method", "")) == normalize_method(request.args.get("method"))):
                filtered.append(record)
        in_year = [record for record in filtered if record["current"].get("sample_date", "").startswith(f"{year:04d}-")]
        matrix = monthly_matrix(in_year, year)
        for row in matrix:
            point = row["room"] + " / " + row["point_id"]
            row["sparkline"] = point_sparkline(row["trend_values"], f"{point} {year}年逐月趨勢；僅顯示最早日可計數結果")
        undated_count = sum(
            not valid_sample_date(record["current"].get("sample_date", ""))
            for record in filtered
        )
        return render_template(
            "database.html", view=view, matrix=matrix, state=state, year=year, years=years,
            site=request.args.get("site", ""), monitoring_type=request.args.get("monitoring_type", ""),
            method=normalize_method(request.args.get("method", "")), sites=sites,
            monitoring_types=monitoring_types, methods=methods, total=len(in_year),
            undated_count=undated_count,
        )

    @app.route("/record/<int:record_id>", methods=["GET", "POST"])
    def edit(record_id):
        record = store.get(data_dir, record_id)
        if not record:
            abort(404)
        candidates = [r for r in store.records(data_dir) if r["id"] != record_id and
                      r["state"] != "void" and candidate_key(r) == candidate_key(record)]
        if request.method == "POST":
            try:
                values = {f: request.form.get(f, "").strip() for f in FIELDS}
                values["method"] = normalize_method(values["method"])
                verified = {f: request.form.get("review_"+f) for f in FIELDS
                            if request.form.get("review_"+f) in ("checked", "not_applicable")}
                state = request.form.get("state", "draft")
                if state not in ("draft", "confirmed", "void"):
                    raise ValueError("未知狀態。")
                validate(values, state == "confirmed")
                if state == "confirmed" and record["warnings"] and not request.form.get("warnings_reviewed"):
                    raise ValueError("請核對提醒內容，確認對照組、重複菌種列及特殊結果的處理後再納入。")
                submitted_key = candidate_key({"current": values})
                submitted_candidates = [r for r in store.records(data_dir) if r["id"] != record_id and
                    r["state"] != "void" and candidate_key(r) == submitted_key]
                if state == "confirmed" and submitted_candidates and not request.form.get("distinct_sample"):
                    raise ValueError("有同日期／點位的候選紀錄，請核對是否同一採樣，再勾選確認。")
                store.update(data_dir, record_id, int(request.form["record_version"]), values,
                             verified, state, request.form.get("reason", ""))
                flash("已儲存；原始辨認值保留，月報使用目前已確認值。")
                return redirect(url_for("edit", record_id=record_id))
            except store.StaleRecord as error:
                abort(409, str(error))
            except (ValueError, KeyError) as error:
                if "values" in locals():
                    record["current"] = values
                    record["verified"] = verified
                    if state in ("draft", "confirmed", "void"):
                        record["state"] = state
                flash(str(error))
        return render_template("record.html", record=record, candidates=candidates,
                               history=store.history(data_dir, record_id))

    @app.get("/source/<int:source_id>")
    def source(source_id):
        with store.closing(store.connection(data_dir)) as db:
            row = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            abort(404)
        path = data_dir / "sources" / (row["sha256"] + Path(row["name"]).suffix.lower())
        return send_file(path, as_attachment=True, download_name=row["name"])

    @app.post("/reparse/<int:source_id>")
    def reparse(source_id):
        with store.closing(store.connection(data_dir)) as db:
            row = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            abort(404)
        try:
            result = reparse_saved_source(data_dir, row)
            if result["noop"]:
                flash(f"{row['name']}：來源目前已是解析版本 {PARSER_VERSION}，沒有變更。")
            else:
                flash(f"{row['name']}：重新解析完成；新增 {result['added']}、補值紀錄 {result['updated']}、差異待核對 {result['conflicts']}、保留作廢 {result['voided']}。備份：{result['backup']}。")
        except (ValueError, OSError, sqlite3.Error) as error:
            store.log_import(data_dir, row["name"], None, "reparse_error", str(error))
            flash(f"{row['name']}：重新解析未完成：{error}")
        return redirect(url_for("index"))

    @app.post("/reparse-batch")
    def reparse_batch():
        results = []
        counts = {"success": 0, "skipped": 0, "conflict": 0, "failed": 0}
        for source in store.sources(data_dir):
            if source["latest_parser_version"] == PARSER_VERSION:
                continue
            try:
                result = reparse_saved_source(data_dir, source)
                if result["noop"]:
                    outcome = "skipped"
                    detail = f"來源已是 parser {PARSER_VERSION}；沒有修改。"
                    store.log_import(data_dir, source["name"], None, "reparse_skipped", detail)
                elif result["conflicts"]:
                    outcome = "conflict"
                    detail = (f"已重新解析；新增 {result['added']}、補值紀錄 {result['updated']}、"
                              f"待核對差異 {result['conflicts']}、保留作廢 {result['voided']}；"
                              f"備份 {result['backup']}。")
                else:
                    outcome = "success"
                    detail = (f"新增 {result['added']}、補值紀錄 {result['updated']}、"
                              f"保留作廢 {result['voided']}；備份 {result['backup']}。")
                counts[outcome] += 1
                results.append({"name": source["name"], "outcome": outcome, "detail": detail,
                                "backup": result.get("backup", "")})
            except (ValueError, OSError, sqlite3.Error) as error:
                detail = str(error)
                store.log_import(data_dir, source["name"], None, "reparse_failed", detail)
                counts["failed"] += 1
                results.append({"name": source["name"], "outcome": "failed", "detail": detail,
                                "backup": ""})
        return render_template("reparse_results.html", results=results, counts=counts,
                               parser_version=PARSER_VERSION)

    @app.get("/records.csv")
    def records_csv():
        rows = store.records(data_dir)
        return csv_response("em_records.csv", ("record_id", "state", *FIELDS, "source", "location", "sha256",
                            "original_parser_version", "source_initial_parser_version", "latest_parser_version"),
            [(r["id"], r["state"], *(r["current"].get(f, "") for f in FIELDS),
              r["source_name"], r["source_location"], r["sha256"], r["original_parser_version"],
              r["source_initial_parser_version"],
              r["latest_parser_version"]) for r in rows])

    @app.get("/accuracy.csv")
    def accuracy_csv():
        items = field_accuracy([r for r in store.records(data_dir) if r["state"] != "void"])
        keys = ("field", "total", "checked", "correct", "incorrect", "pending", "not_applicable", "manual_excluded", "accuracy")
        return csv_response("field_accuracy.csv", keys, [[r[k] for k in keys] for r in items])

    @app.get("/report.html")
    @app.get("/reports")
    def reports():
        rows = [r for r in store.records(data_dir) if r["state"] != "void"]
        site = request.args.get("site", "")
        sites = sorted({r["current"].get("site", "") for r in rows} - {""})
        if site:
            rows = [r for r in rows if r["current"].get("site") == site]
        available = monthly_report(rows)["months"]
        start = request.args.get("start", available[0] if available else "")
        end = request.args.get("end", available[-1] if available else "")
        try:
            months = months_between(start, end)
        except ValueError as error:
            abort(400, str(error))
        filtered = [r for r in rows if r["current"].get("sample_date", "")[:7] in months]
        report = monthly_report(filtered)
        point_groups, person_groups = {}, {}
        for p in report["points"]:
            key = " / ".join(p[k] or "未填" for k in ("site", "monitoring_type", "method", "room", "grade", "point_id", "unit"))
            point_groups.setdefault(key, {})[p["month"]] = p
        for p in report["people"]:
            key = p["site"] + " / " + p["operator"]
            person_groups.setdefault(key, {})[p["month"]] = p
        selected = request.args.get("point", next(iter(point_groups), ""))
        chosen = point_groups.get(selected, {})
        point_chart = chart(months, [chosen[m]["cfu"] if m in chosen and chosen[m]["n"] else None for m in months], "所選點位每月 CFU 加總")
        crr = []
        for month in months:
            items = [p for p in report["people"] if p["month"] == month]
            n = sum(p["total_days"] for p in items)
            crr.append(100 * sum(p["positive_days"] for p in items) / n if n else None)
        context = dict(months=months, report=report, point_groups=point_groups, person_groups=person_groups,
                       point_chart=point_chart, crr_chart=chart(months, crr, "每月人日 CRR 百分比"),
                       accuracy=field_accuracy(rows), site=site, sites=sites, start=start, end=end,
                       void_count=sum(r["state"] == "void" for r in store.records(data_dir)),
                       selected=selected, timestamp=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M 台北"),
                       snapshot=request.path == "/report.html")
        html = render_template("reports.html", **context)
        if context["snapshot"]:
            return Response(html, headers={"Content-Disposition": 'attachment; filename="em_monthly_report.html"'})
        return html

    return app


def main():
    import argparse
    from waitress import serve
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app = create_app()
    print(f"EM MVP: http://127.0.0.1:{args.port} | data: {app.config['DATA_DIR']}", flush=True)
    serve(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
