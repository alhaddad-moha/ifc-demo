"""The pipeline: a fixed, declared sequence of steps run on upload.

This is the idea worth taking from IFCflow, inverted. There, a human drags
nodes onto a canvas and runs the graph. Here the graph is *already authored* —
PIPELINE below is the saved workflow — and the user only supplies a file.
The canvas, if you ever want one, becomes an internal tool for producing more
entries in this list, not something the end user has to learn.

Each step reports progress, so the UI can show what is happening on a large
model instead of a spinner.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

DATA_ROOT = os.environ.get("IFC_DATA_DIR", os.path.join(os.getcwd(), "data"))

STEP_LABELS = [
    ("upload", "Receiving file"),
    ("parse", "Parsing IFC"),
    ("schema", "Validating schema"),
    ("ids", "Checking information requirements"),
    ("rules", "Running integrity rules"),
    ("sqlite", "Building queryable database"),
    ("report", "Generating reports"),
]


@dataclass
class Job:
    id: str
    filename: str
    size: int
    status: str = "queued"           # queued | running | done | failed
    step: str = "upload"
    step_index: int = 0
    message: str = "Queued"
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    options: dict[str, Any] = field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    ids_summary: Optional[dict[str, Any]] = None
    db_info: Optional[dict[str, Any]] = None
    log: list[str] = field(default_factory=list)

    @property
    def dir(self) -> str:
        return os.path.join(DATA_ROOT, self.id)

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def to_dict(self, include_result: bool = False) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "filename": self.filename,
            "size": self.size,
            "status": self.status,
            "step": self.step,
            "step_index": self.step_index,
            "step_total": len(STEP_LABELS),
            "steps": [{"key": k, "label": v} for k, v in STEP_LABELS],
            "message": self.message,
            "error": self.error,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 2),
            "log": self.log[-60:],
            "has_db": bool(self.db_info),
        }
        if include_result and self.result is not None:
            payload["result"] = self.result
            payload["ids"] = self.ids_summary
            payload["db"] = self.db_info
        return payload


JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def create(filename: str, data: bytes, options: dict[str, Any]) -> Job:
    job_id = uuid.uuid4().hex[:12]
    job = Job(id=job_id, filename=filename, size=len(data), options=options)
    os.makedirs(job.dir, exist_ok=True)
    with open(job.path("model.ifc"), "wb") as fh:
        fh.write(data)
    with _LOCK:
        JOBS[job_id] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job


def get(job_id: str) -> Optional[Job]:
    return JOBS.get(job_id)


def listing() -> list[dict[str, Any]]:
    return [j.to_dict() for j in
            sorted(JOBS.values(), key=lambda j: j.started_at, reverse=True)]


def delete(job_id: str) -> bool:
    with _LOCK:
        job = JOBS.pop(job_id, None)
    if job is None:
        return False
    shutil.rmtree(job.dir, ignore_errors=True)
    return True


def _advance(job: Job, key: str, message: str) -> None:
    job.step = key
    job.step_index = next((i for i, (k, _) in enumerate(STEP_LABELS) if k == key), 0)
    job.message = message
    job.log.append(message)


def _run(job: Job) -> None:
    # Imported here so a slow import never blocks the upload response.
    import ifcaudit
    from ifcaudit.report import html_report, json_report
    from ifcaudit.rules.ids_runner import ids_summary, run_ids
    from ifcaudit.rules.schema_check import run_schema_check
    from . import exports, sql_export

    job.status = "running"
    try:
        _advance(job, "parse", "Parsing IFC file…")
        ctx = ifcaudit.load(job.path("model.ifc"))
        job.log.append(f"{ctx.schema}, {len(ctx.elements)} elements, "
                       f"{len(ctx.storeys)} storeys")

        extra = []

        if job.options.get("schema_check", True):
            _advance(job, "schema", "Validating against the IFC schema…")
            extra.extend(run_schema_check(ctx))
        else:
            job.log.append("Schema validation skipped")

        ids_path = job.options.get("ids_path")
        summary = None
        if ids_path and os.path.isfile(ids_path):
            _advance(job, "ids", "Checking information requirements…")
            extra.extend(run_ids(ctx, ids_path))
            summary = ids_summary(ids_path, ctx)
            job.ids_summary = summary

        _advance(job, "rules", "Running integrity rules…")
        result = ifcaudit.run(ctx, extra_issues=extra)
        counts = result.counts()
        job.log.append(f"{counts['error']} error(s), {counts['warning']} warning(s), "
                       f"{counts['info']} info")

        if job.options.get("build_db", True):
            _advance(job, "sqlite", "Building queryable database…")
            try:
                job.db_info = sql_export.build(job.path("model.ifc"),
                                               job.path("model.db"))
                job.log.append(f"{len(job.db_info['tables'])} tables written")
            except Exception as exc:
                # A failed SQL export must not lose the audit that already ran.
                job.log.append(f"Database export failed: {exc}")

        _advance(job, "report", "Generating reports…")
        payload = result.to_dict()
        if summary:
            payload["ids"] = summary
        json_report.write(result, job.path("report.json"), ids_summary=summary)
        html_report.write(result, job.path("report.html"), ids_summary=summary)
        exports.workbook(payload, summary, job.path("report.xlsx"))
        with open(job.path("issues.csv"), "w", encoding="utf-8") as fh:
            fh.write(exports.issues_csv(payload))

        job.result = payload
        job.status = "done"
        job.message = "Complete"
        job.step_index = len(STEP_LABELS) - 1
    except Exception as exc:
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.message = "Failed"
        job.log.append(job.error)
        job.log.append(traceback.format_exc()[-1200:])
    finally:
        job.finished_at = time.time()
