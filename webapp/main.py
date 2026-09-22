"""FastAPI application: upload an IFC, get a full analysis.

Everything heavy runs in a background thread and the browser polls for
progress, so a large model does not have to survive a request timeout.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import exports, jobs, nlq, sql_export

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
PROJECT_ROOT = os.path.dirname(HERE)
DEFAULT_IDS = os.path.join(PROJECT_ROOT, "examples", "project_requirements.ids")

MAX_UPLOAD_MB = int(os.environ.get("IFC_MAX_UPLOAD_MB", "500"))

app = FastAPI(title="IFC Audit", version="0.2.0")


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


@app.get("/api/config")
def config() -> dict[str, Any]:
    import ifcaudit
    return {
        "rules": [
            {"id": r.id, "title": r.title, "severity": r.severity.value,
             "category": r.category.value}
            for r in sorted(ifcaudit.REGISTRY.values(), key=lambda r: r.id)
        ],
        "default_ids": os.path.basename(DEFAULT_IDS) if os.path.isfile(DEFAULT_IDS) else None,
        "nlq_available": nlq.available(),
        "max_upload_mb": MAX_UPLOAD_MB,
        "examples": sql_export.EXAMPLE_QUERIES,
    }


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------

@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    schema_check: bool = Form(True),
    build_db: bool = Form(True),
    use_ids: bool = Form(True),
    ids_file: Optional[UploadFile] = File(None),
) -> dict[str, Any]:
    name = file.filename or "model.ifc"
    if not name.lower().endswith((".ifc", ".ifczip")):
        raise HTTPException(400, "Only .ifc files are accepted.")

    data = await file.read()
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_MB} MB limit.")

    options: dict[str, Any] = {
        "schema_check": schema_check,
        "build_db": build_db,
    }

    job = jobs.create(name, data, options)

    # The IDS is written into the job directory so each run keeps the exact
    # ruleset it was audited against.
    if use_ids:
        if ids_file is not None and ids_file.filename:
            ids_bytes = await ids_file.read()
            target = job.path("requirements.ids")
            with open(target, "wb") as fh:
                fh.write(ids_bytes)
            options["ids_path"] = target
        elif os.path.isfile(DEFAULT_IDS):
            options["ids_path"] = DEFAULT_IDS

    return job.to_dict()


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    return {"jobs": jobs.listing()}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job.")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job.")
    if job.status != "done":
        raise HTTPException(409, f"Job is {job.status}.")
    return job.to_dict(include_result=True)


@app.delete("/api/jobs/{job_id}")
def remove_job(job_id: str) -> dict[str, bool]:
    return {"deleted": jobs.delete(job_id)}


DOWNLOADS = {
    "html": ("report.html", "text/html"),
    "json": ("report.json", "application/json"),
    "xlsx": ("report.xlsx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "csv": ("issues.csv", "text/csv"),
    "db": ("model.db", "application/vnd.sqlite3"),
    "ifc": ("model.ifc", "application/octet-stream"),
    # Only on a fixed copy: the file it was fixed from, and what changed.
    "original": ("original.ifc", "application/octet-stream"),
    "changes": ("changes.json", "application/json"),
}


@app.get("/api/jobs/{job_id}/download/{kind}")
def download(job_id: str, kind: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job.")
    if kind not in DOWNLOADS:
        raise HTTPException(404, "Unknown download.")
    name, media = DOWNLOADS[kind]
    path = job.path(name)
    if not os.path.isfile(path):
        raise HTTPException(404, f"{name} was not produced for this run.")
    stem = os.path.splitext(job.filename)[0]
    suffix = os.path.splitext(name)[1]
    download_name = {
        "ifc": job.filename,
        "original": job.parent_filename or job.filename,
        "changes": f"{stem}_changes.json",
    }.get(kind, f"{stem}_audit{suffix}")
    return FileResponse(path, media_type=media, filename=download_name)


@app.get("/api/jobs/{job_id}/report", response_class=HTMLResponse)
def inline_report(job_id: str) -> HTMLResponse:
    job = jobs.get(job_id)
    if job is None or not os.path.isfile(job.path("report.html")):
        raise HTTPException(404, "No report for this job.")
    with open(job.path("report.html"), encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


@app.get("/api/jobs/{job_id}/elements")
def job_elements(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job.")
    if job.status != "done":
        raise HTTPException(409, f"Job is {job.status}.")
    return {"elements": jobs.elements(job)}


# --------------------------------------------------------------------------
# fixes
# --------------------------------------------------------------------------

MAX_FIXES = 5000


def _require_done(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job.")
    if job.status != "done":
        raise HTTPException(409, f"Job is {job.status}.")
    return job


@app.get("/api/jobs/{job_id}/fixes")
def fix_proposals(job_id: str) -> dict[str, Any]:
    job = _require_done(job_id)
    return {"fixes": [f.to_dict() for f in jobs.proposals(job)]}


@app.post("/api/jobs/{job_id}/fixes/apply")
def apply_fixes(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply approved fixes to a copy. The client sends issue ids and values;
    the operations come from the server's own proposals, never the request."""
    from ifcaudit import fixes

    job = _require_done(job_id)
    wanted = payload.get("fixes") or []
    if not isinstance(wanted, list) or not wanted:
        raise HTTPException(400, "Select at least one fix.")
    if len(wanted) > MAX_FIXES:
        raise HTTPException(400, f"At most {MAX_FIXES} fixes per run.")

    by_id = {f.issue_id: f for f in jobs.proposals(job)}
    selected, values, errors = [], {}, []
    for item in wanted:
        fix = by_id.get(str((item or {}).get("issue_id", "")))
        if fix is None or fix.kind == fixes.MANUAL:
            continue
        raw = item.get("values") or {}
        try:
            fixes.coerce(fix, raw if isinstance(raw, dict) else {})
        except ValueError as exc:
            errors.append(f"{fix.element}: {exc}")
            continue
        selected.append(fix)
        values[fix.issue_id] = raw
    if errors:
        raise HTTPException(400, "; ".join(errors[:5])
                            + (f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""))
    if not selected:
        raise HTTPException(400, "None of the selected issues has an applicable fix.")

    return jobs.create_fixed(job, selected, values).to_dict()


# --------------------------------------------------------------------------
# querying
# --------------------------------------------------------------------------

def _require_db(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such job.")
    path = job.path("model.db")
    if not os.path.isfile(path):
        raise HTTPException(409, "No database was built for this model.")
    return job, path


@app.get("/api/jobs/{job_id}/schema")
def db_schema(job_id: str) -> dict[str, Any]:
    _, path = _require_db(job_id)
    return sql_export.describe(path)


@app.post("/api/jobs/{job_id}/sql")
def run_sql(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _, path = _require_db(job_id)
    sql = str(payload.get("sql", ""))
    return sql_export.query(path, sql)


@app.post("/api/jobs/{job_id}/ask")
def ask(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _, path = _require_db(job_id)
    question = str(payload.get("question", "")).strip()
    if not question:
        raise HTTPException(400, "Ask a question.")
    return nlq.ask(path, question)


@app.post("/api/jobs/{job_id}/sql.csv", response_class=PlainTextResponse)
def sql_to_csv(job_id: str, payload: dict[str, Any]) -> PlainTextResponse:
    _, path = _require_db(job_id)
    result = sql_export.query(path, str(payload.get("sql", "")), limit=50000)
    if "error" in result:
        return PlainTextResponse(result["error"], status_code=400)
    body = exports.rows_csv(result["columns"], result["rows"])
    return PlainTextResponse(body, media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="query_result.csv"'
    })


app.mount("/static", StaticFiles(directory=STATIC), name="static")
