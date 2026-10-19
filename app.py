from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask, abort, flash, redirect, render_template, request, send_file,
    session, url_for,
)
from werkzeug.utils import secure_filename

from engine.analyzer import analyze_paths
from engine.database_builder import browse_table, create_database, inspect_database
from engine.insights import generate_business_insights
from engine.preflight import build_migration_preflight
from engine.quality import build_quality_summary

ROOT = Path(__file__).resolve().parent
INSTANCE = ROOT / "instance"
WORKSPACES = INSTANCE / "workspaces"
SAMPLE_DIR = ROOT / "sample_data"
ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
MAX_FILES = 8
MAX_REQUEST_BYTES = 20 * 1024 * 1024
WORKSPACE_TTL_SECONDS = int(os.environ.get("FILE2BASE_WORKSPACE_TTL_SECONDS", "21600"))
CLEANUP_INTERVAL_SECONDS = 600

INSTANCE.mkdir(exist_ok=True)
WORKSPACES.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FILE2BASE_SECRET_KEY", "local-demo-only-change-me"),
    MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
    MAX_FORM_MEMORY_SIZE=1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    PERMANENT_SESSION_LIFETIME=WORKSPACE_TTL_SECONDS,
    SESSION_REFRESH_EACH_REQUEST=False,
)
if os.environ.get("RENDER") and not os.environ.get("FILE2BASE_SECRET_KEY"):
    raise RuntimeError("Set FILE2BASE_SECRET_KEY in the hosted environment before starting File2Base.")

logger = logging.getLogger("file2base")
_last_cleanup_monotonic = 0.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _cleanup_expired_workspaces() -> None:
    """Delete old demo workspaces periodically; hosted demo data is temporary."""
    global _last_cleanup_monotonic
    current = time.monotonic()
    if current - _last_cleanup_monotonic < CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup_monotonic = current
    now = time.time()
    try:
        children = list(WORKSPACES.iterdir())
    except OSError:
        return
    for child in children:
        try:
            if child.is_dir() and now - child.stat().st_mtime > WORKSPACE_TTL_SECONDS:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            logger.exception("Could not expire workspace")


def workspace_path(workspace_id: str) -> Path:
    # UUID-hex IDs prevent path traversal and function as unguessable demo links.
    if not workspace_id or not all(c in "0123456789abcdef" for c in workspace_id) or len(workspace_id) != 32:
        abort(404)
    path = WORKSPACES / workspace_id
    if not path.exists() or not path.is_dir():
        abort(404)
    try:
        os.utime(path, None)  # Extend the time-to-live while this workspace is used.
    except OSError:
        pass
    return path


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj):
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def _record_audit_event(workspace_dir: Path, event: str, details: dict | None = None) -> list[dict]:
    """Append compact workflow metadata; never record uploaded cell values."""
    audit_path = workspace_dir / "audit.json"
    try:
        events = load_json(audit_path) if audit_path.exists() else []
        if not isinstance(events, list):
            events = []
    except (OSError, ValueError, TypeError):
        events = []
    events.append({"timestamp": _utc_now(), "event": str(event), "details": details or {}})
    save_json(audit_path, events)
    return events


def _read_audit_events(workspace_dir: Path) -> list[dict]:
    audit_path = workspace_dir / "audit.json"
    if not audit_path.exists():
        return []
    try:
        events = load_json(audit_path)
        return events if isinstance(events, list) else []
    except (OSError, ValueError, TypeError):
        return []


def _csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    session.permanent = True
    return token


@app.context_processor
def inject_template_helpers():
    return {"csrf_token": _csrf_token(), "is_hosted_demo": bool(os.environ.get("RENDER"))}


@app.before_request
def protect_posts_and_expire_workspaces():
    _cleanup_expired_workspaces()
    if request.method == "POST":
        expected = session.get("_csrf_token", "")
        supplied = request.form.get("_csrf_token", "")
        if not expected or not supplied or not hmac.compare_digest(expected, supplied):
            abort(400, description="This form has expired or could not be validated. Refresh the page and try again.")


@app.after_request
def add_safety_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'",
    )
    return response


def run_analysis(workspace_dir: Path, items: list[dict[str, str]]):
    analysis = analyze_paths(items)
    save_json(workspace_dir / "analysis.json", analysis)
    save_json(workspace_dir / "files.json", items)
    _record_audit_event(workspace_dir, "Files analyzed", {
        "file_count": analysis.get("summary", {}).get("file_count", len(items)),
        "table_count": len(analysis.get("tables", [])),
        "row_count": analysis.get("summary", {}).get("row_count", 0),
        "relationship_candidates": len(analysis.get("relationships", [])),
    })
    return analysis


def stage_uploads(file_storages, workspace_dir: Path) -> list[dict[str, str]]:
    incoming = workspace_dir / "uploads"
    incoming.mkdir(parents=True, exist_ok=True)
    selected = [file for file in file_storages if file and file.filename]
    if not selected:
        raise ValueError("Choose at least one Excel or CSV file first.")
    if len(selected) > MAX_FILES:
        raise ValueError(f"The demo supports up to {MAX_FILES} files in one analysis.")
    items: list[dict[str, str]] = []
    for file in selected:
        safe_name = secure_filename(file.filename)
        ext = Path(safe_name).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"'{file.filename}' is not supported. Upload .csv or .xlsx files.")
        if not safe_name:
            raise ValueError("One of the uploaded files has an invalid filename.")
        file_id = uuid.uuid4().hex[:12]
        disk_path = incoming / f"{file_id}_{safe_name}"
        file.save(disk_path)
        if disk_path.stat().st_size == 0:
            disk_path.unlink(missing_ok=True)
            raise ValueError(f"'{safe_name}' is empty.")
        items.append({
            "id": file_id,
            "filename": safe_name,
            "path": str(disk_path),
            "sha256": _sha256(disk_path),
            "size_bytes": disk_path.stat().st_size,
        })
    return items


def create_workspace() -> tuple[str, Path]:
    wid = uuid.uuid4().hex
    wpath = WORKSPACES / wid
    wpath.mkdir(parents=True, exist_ok=False)
    save_json(wpath / "workspace.json", {"created_at": _utc_now(), "expires_after_seconds": WORKSPACE_TTL_SECONDS})
    _record_audit_event(wpath, "Workspace created", {"workflow": "File-to-database prototype"})
    return wid, wpath


def _source_integrity_issues(workspace_dir: Path) -> list[dict[str, str]]:
    """Confirm analyzed source files are still present and unchanged before migration."""
    issues = []
    files_manifest = workspace_dir / "files.json"
    if not files_manifest.exists():
        return [{"title": "Source manifest missing", "detail": "Re-upload the source files and rerun analysis."}]
    for item in load_json(files_manifest):
        path = Path(item.get("path", "")).resolve()
        uploads_root = (workspace_dir / "uploads").resolve()
        if uploads_root not in path.parents or not path.is_file():
            issues.append({"title": f"{item.get('filename', 'Source file')}: file unavailable", "detail": "The source file is missing from this workspace. Restart from upload before migrating."})
            continue
        expected = item.get("sha256")
        if not expected or _sha256(path) != expected:
            issues.append({"title": f"{item.get('filename', 'Source file')}: source changed", "detail": "The analyzed file no longer matches its original fingerprint. Re-upload and analyze the source again before migration."})
    return issues


def _relationship_ids_from_form() -> list[int]:
    values = []
    for value in request.form.getlist("relationship_ids"):
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue
    return values


def _table_overrides_from_form(analysis: dict) -> dict[str, str]:
    overrides = {}
    for table in analysis.get("tables", []):
        raw = request.form.get(f"table_{table['table_name']}", table["table_name"])
        overrides[table["table_name"]] = raw[:80]
    return overrides


def _primary_key_overrides_from_form(analysis: dict) -> dict[str, str]:
    overrides = {}
    for table in analysis.get("tables", []):
        submitted = request.form.get(f"primary_key_{table['table_name']}", table.get("primary_key") or "__generated__")
        allowed = {column["name"] for column in table.get("columns", [])}
        overrides[table["table_name"]] = submitted if submitted == "__generated__" or submitted in allowed else "__generated__"
    return overrides


def _augment_integrity_issues(preflight: dict, issues: list[dict[str, str]]) -> dict:
    if issues:
        existing_titles = {item.get("title") for item in preflight.get("blockers", [])}
        preflight["blockers"].extend(item for item in issues if item.get("title") not in existing_titles)
        preflight["blocker_count"] = len(preflight["blockers"])
        preflight["can_migrate"] = False
    return preflight


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", max_files=MAX_FILES, max_upload_mb=MAX_REQUEST_BYTES // (1024 * 1024))


@app.route("/upload", methods=["POST"])
def upload():
    wid, wpath = create_workspace()
    try:
        items = stage_uploads(request.files.getlist("files"), wpath)
        run_analysis(wpath, items)
        flash("Analysis complete. Review the proposed schema, then run the safety check before migration.", "success")
        return redirect(url_for("review", workspace_id=wid))
    except ValueError as exc:
        shutil.rmtree(wpath, ignore_errors=True)
        flash(str(exc), "error")
        return redirect(url_for("index"))
    except Exception:
        logger.exception("File upload analysis failed")
        shutil.rmtree(wpath, ignore_errors=True)
        flash("File2Base could not analyze one of those files. Check that the files are valid CSV or XLSX, then try again.", "error")
        return redirect(url_for("index"))


@app.route("/demo", methods=["POST"])
def demo():
    wid, wpath = create_workspace()
    try:
        files_in = sorted([p for p in SAMPLE_DIR.iterdir() if p.suffix.lower() in ALLOWED_EXTENSIONS])
        if not files_in:
            raise ValueError("Sample data files are missing from sample_data/.")
        incoming = wpath / "uploads"
        incoming.mkdir()
        items = []
        for path in files_in:
            file_id = uuid.uuid4().hex[:12]
            dest = incoming / f"{file_id}_{path.name}"
            shutil.copy2(path, dest)
            items.append({"id": file_id, "filename": path.name, "path": str(dest), "sha256": _sha256(dest), "size_bytes": dest.stat().st_size})
        run_analysis(wpath, items)
        flash("Sample business data analyzed. Review the schema and run the safety check before migration.", "success")
        return redirect(url_for("review", workspace_id=wid))
    except Exception:
        logger.exception("Sample workspace could not be created")
        shutil.rmtree(wpath, ignore_errors=True)
        flash("Could not load sample data. Please try again.", "error")
        return redirect(url_for("index"))


@app.route("/review/<workspace_id>", methods=["GET"])
def review(workspace_id):
    wpath = workspace_path(workspace_id)
    analysis_file = wpath / "analysis.json"
    if not analysis_file.exists():
        abort(404)
    analysis = load_json(analysis_file)
    quality = build_quality_summary(analysis)
    assistant_context = {
        "summary": analysis.get("summary", {}),
        "tables": [{
            "name": table.get("table_name", "table"),
            "filename": table.get("filename", "source file"),
            "rows": table.get("row_count", 0),
            "columns": [{
                "name": col.get("original_name", col.get("name", "column")),
                "normalized_name": col.get("name", "column"),
                "type": col.get("sql_type", "TEXT"),
                "null_pct": col.get("null_pct", 0),
                "unique_ratio": col.get("unique_ratio", 0),
                "filled_ratio": col.get("filled_ratio", 1),
            } for col in table.get("columns", [])],
            "primary_key": table.get("primary_key"),
            "duplicate_rows": table.get("duplicate_rows", 0),
        } for table in analysis.get("tables", [])],
        "relationships": [{
            "source_table": rel.get("source_table"),
            "source_column": rel.get("source_column"),
            "target_table": rel.get("target_table"),
            "target_column": rel.get("target_column"),
            "confidence_pct": rel.get("confidence_pct", 0),
            "coverage_pct": round(float(rel.get("coverage", 0) or 0) * 100),
            "reason": rel.get("reason", ""),
        } for rel in analysis.get("relationships", [])],
        "quality": quality,
    }
    return render_template("review.html", workspace_id=workspace_id, analysis=analysis,
                           quality=quality, assistant_context=assistant_context)


@app.route("/preflight/<workspace_id>", methods=["POST"])
def start_preflight(workspace_id):
    wpath = workspace_path(workspace_id)
    analysis_file = wpath / "analysis.json"
    if not analysis_file.exists():
        abort(404)
    analysis = load_json(analysis_file)
    relation_ids = _relationship_ids_from_form()
    table_overrides = _table_overrides_from_form(analysis)
    primary_key_overrides = _primary_key_overrides_from_form(analysis)
    try:
        preflight = build_migration_preflight(analysis, relation_ids, table_overrides, primary_key_overrides)
    except Exception:
        logger.exception("Migration preflight failed")
        flash("The safety check could not complete. Recheck the files and try analysis again.", "error")
        return redirect(url_for("review", workspace_id=workspace_id))
    preflight = _augment_integrity_issues(preflight, _source_integrity_issues(wpath))
    preflight["created_at"] = _utc_now()
    save_json(wpath / "preflight.json", preflight)
    _record_audit_event(wpath, "Migration preview generated", {
        "can_migrate": bool(preflight.get("can_migrate")),
        "table_count": preflight.get("table_count", 0),
        "row_count": preflight.get("row_count", 0),
        "relationship_count": preflight.get("relationship_count", 0),
        "warning_count": preflight.get("warning_count", 0),
        "blocker_count": preflight.get("blocker_count", 0),
    })
    return redirect(url_for("preflight", workspace_id=workspace_id))


@app.route("/preflight/<workspace_id>", methods=["GET"])
def preflight(workspace_id):
    wpath = workspace_path(workspace_id)
    path = wpath / "preflight.json"
    if not path.exists():
        return redirect(url_for("review", workspace_id=workspace_id))
    report = load_json(path)
    # Keep the review page's stored plan fresh if the source has changed since preview.
    issues = _source_integrity_issues(wpath)
    if issues:
        report = _augment_integrity_issues(report, issues)
        save_json(path, report)
    return render_template("preflight.html", workspace_id=workspace_id, preflight=report,
                           audit_events=_read_audit_events(wpath))


@app.route("/create/<workspace_id>", methods=["POST"])
def create(workspace_id):
    wpath = workspace_path(workspace_id)
    preflight_path = wpath / "preflight.json"
    analysis_path = wpath / "analysis.json"
    if not preflight_path.exists() or not analysis_path.exists():
        flash("Run the migration safety check before creating the database.", "error")
        return redirect(url_for("review", workspace_id=workspace_id))
    if request.form.get("confirm_migration") != "yes":
        flash("Please confirm that you reviewed the migration checks before continuing.", "error")
        return redirect(url_for("preflight", workspace_id=workspace_id))

    stored_plan = load_json(preflight_path)
    analysis = load_json(analysis_path)
    relation_ids = [int(value) for value in stored_plan.get("selected_relation_ids", [])]
    table_overrides = stored_plan.get("table_name_overrides", {})
    primary_key_overrides = stored_plan.get("primary_key_overrides", {})

    # Rerun all checks at commit time; the preview is not a substitute for validation.
    try:
        current_plan = build_migration_preflight(analysis, relation_ids, table_overrides, primary_key_overrides)
        current_plan = _augment_integrity_issues(current_plan, _source_integrity_issues(wpath))
        current_plan["created_at"] = _utc_now()
        save_json(preflight_path, current_plan)
        if not current_plan["can_migrate"]:
            flash("Migration stopped because the safety check found a blocking issue. Review the report below.", "error")
            return redirect(url_for("preflight", workspace_id=workspace_id))
        result = create_database(str(wpath), analysis, relation_ids, table_overrides, primary_key_overrides)
    except Exception:
        logger.exception("Database migration failed")
        _record_audit_event(wpath, "Migration attempt failed", {"reason": "Migration raised an error; source files were retained."})
        flash("Migration could not be completed. The last successful database, if any, was preserved. Review the safety notes and try again.", "error")
        return redirect(url_for("preflight", workspace_id=workspace_id))

    result["completed_at"] = _utc_now()
    _record_audit_event(wpath, "SQLite database created", {
        "table_count": result.get("table_count", 0),
        "row_count": result.get("row_count", 0),
        "relationship_count": len(result.get("relationships", [])),
        "foreign_key_violations": result.get("foreign_key_violations", 0),
    })
    audit_events = _read_audit_events(wpath)
    report = {
        "product": "File2Base prototype",
        "completed_at": result["completed_at"],
        "status": "success" if result.get("foreign_key_violations", 0) == 0 else "warning",
        "table_count": result.get("table_count", 0),
        "row_count": result.get("row_count", 0),
        "relationship_count": len(result.get("relationships", [])),
        "foreign_key_violations": result.get("foreign_key_violations", 0),
        "tables": current_plan.get("tables", []),
        "relationships": current_plan.get("relationships", []),
        "warnings": current_plan.get("warnings", []),
        "blockers": current_plan.get("blockers", []),
        "audit_trail": audit_events,
        "data_quality": build_quality_summary(analysis),
        "note": "Relationship confidence is a heuristic ranking, not a calibrated probability. Review sensitive or business-critical migrations with a qualified person.",
    }
    save_json(wpath / "migration_report.json", report)
    return redirect(url_for("database", workspace_id=workspace_id))


@app.route("/database/<workspace_id>", methods=["GET"])
def database(workspace_id):
    wpath = workspace_path(workspace_id)
    db_path = wpath / "generated.sqlite"
    result_path = wpath / "database_result.json"
    if not db_path.exists() or not result_path.exists():
        return redirect(url_for("review", workspace_id=workspace_id))
    info = inspect_database(str(db_path))
    result = load_json(result_path)
    audit_events = _read_audit_events(wpath)
    migration_report_path = wpath / "migration_report.json"
    migration_report = load_json(migration_report_path) if migration_report_path.exists() else {}
    quality = migration_report.get("data_quality", {})
    try:
        insights = generate_business_insights(str(db_path))
    except Exception:
        logger.exception("Could not generate business insights")
        insights = None
    return render_template("database.html", workspace_id=workspace_id, info=info, result=result,
                           audit_events=audit_events, quality=quality, insights=insights)


@app.route("/database/<workspace_id>/table/<table_name>", methods=["GET"])
def table_view(workspace_id, table_name):
    wpath = workspace_path(workspace_id)
    db_path = wpath / "generated.sqlite"
    if not db_path.exists():
        abort(404)
    try:
        data = browse_table(str(db_path), table_name)
    except ValueError:
        abort(404)
    info = inspect_database(str(db_path))
    return render_template("table.html", workspace_id=workspace_id, data=data, info=info)


@app.route("/download/<workspace_id>", methods=["GET"])
def download_db(workspace_id):
    wpath = workspace_path(workspace_id)
    db_path = wpath / "generated.sqlite"
    if not db_path.exists():
        abort(404)
    return send_file(db_path, as_attachment=True, download_name="file2base_generated.sqlite", mimetype="application/x-sqlite3")


@app.route("/report/<workspace_id>", methods=["GET"])
def download_report(workspace_id):
    wpath = workspace_path(workspace_id)
    report_path = wpath / "migration_report.json"
    if not report_path.exists():
        abort(404)
    return send_file(report_path, as_attachment=True, download_name="file2base_migration_report.json", mimetype="application/json")


@app.route("/audit/<workspace_id>", methods=["GET"])
def download_audit(workspace_id):
    wpath = workspace_path(workspace_id)
    events = _read_audit_events(wpath)
    return app.response_class(
        json.dumps({"workspace_id": workspace_id, "events": events}, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="file2base_audit_trail.json"'},
    )


@app.route("/delete/<workspace_id>", methods=["POST"])
def delete_workspace(workspace_id):
    wpath = workspace_path(workspace_id)
    shutil.rmtree(wpath, ignore_errors=True)
    flash("Workspace and generated files deleted from this running demo instance.", "success")
    return redirect(url_for("index"))


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "product": "File2Base demo", "version": "2.0"}


@app.errorhandler(400)
def bad_request(error):
    message = getattr(error, "description", "The request could not be validated.")
    return render_template("error.html", code=400, title="Please refresh and try again", message=message), 400


@app.errorhandler(413)
def too_large(_error):
    return render_template(
        "error.html", code=413, title="Files are too large",
        message=f"The public demo accepts up to {MAX_REQUEST_BYTES // (1024 * 1024)} MB per upload request. Try fewer or smaller files.",
    ), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
