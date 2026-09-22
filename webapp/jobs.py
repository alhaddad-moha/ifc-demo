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
    ("fix", "Applying approved fixes"),      # only on a fixed copy, see steps()
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
    # Set on a fixed copy: the run it was fixed from, and what changed.
    parent_id: Optional[str] = None
    parent_filename: Optional[str] = None
    changes: Optional[dict[str, Any]] = None
    diff: Optional[dict[str, Any]] = None
    proposals: Optional[list] = field(default=None, repr=False)

    @property
    def steps(self) -> list[tuple[str, str]]:
        return [(k, v) for k, v in STEP_LABELS if k != "fix" or self.parent_id]

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
            "step_total": len(self.steps),
            "steps": [{"key": k, "label": v} for k, v in self.steps],
            "message": self.message,
            "error": self.error,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 2),
            "log": self.log[-60:],
            "has_db": bool(self.db_info),
            "parent_id": self.parent_id,
            "parent_filename": self.parent_filename,
        }
        if include_result and self.result is not None:
            payload["result"] = self.result
            payload["ids"] = self.ids_summary
            payload["db"] = self.db_info
            if self.changes is not None:
                payload["changes"] = self.changes
                payload["diff"] = self.diff
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


def proposals(job: Job) -> list:
    """Fix proposals for a finished run, computed once and cached."""
    if job.proposals is None:
        import ifcaudit
        from ifcaudit import fixes
        ctx = ifcaudit.load(job.path("model.ifc"))
        job.proposals = fixes.propose_all(ctx, job.result["issues"])
    return job.proposals


def elements(job: Job) -> list[dict[str, Any]]:
    """Every IfcProduct as {id, guid, cls, name, storey}, for the 3D viewer.

    `id` is the STEP id, which is also web-ifc's expressID, so the browser can
    join its meshes to this list without reading IFC attributes itself.
    Cached next to the model after the first call.
    """
    import json

    cache = job.path("elements.json")
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)

    import ifcaudit
    ctx = ifcaudit.load(job.path("model.ifc"))
    out = []
    for el in ctx.model.by_type("IfcProduct"):
        out.append({
            "id": el.id(),
            "guid": el.GlobalId,
            "cls": el.is_a(),
            "name": getattr(el, "Name", None),
            "storey": ctx.storey_name(el) if el.is_a("IfcElement") else None,
        })
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    return out


def create_fixed(parent: Job, selected: list, values: dict[str, dict]) -> Job:
    """Start a new run on a fixed copy of `parent`'s model.

    The parent's files are never written to. The new run keeps a byte copy of
    the model it started from (original.ifc) next to the fixed one (model.ifc)
    and the change log, so one directory holds before, after and the diff.
    """
    stem = os.path.splitext(parent.filename)[0]
    if not stem.endswith("_fixed"):
        stem += "_fixed"
    options = {k: v for k, v in parent.options.items()
               if k in ("schema_check", "build_db", "ids_path")}
    job = Job(id=uuid.uuid4().hex[:12], filename=stem + ".ifc", size=0,
              options=options, parent_id=parent.id,
              parent_filename=parent.filename)
    os.makedirs(job.dir, exist_ok=True)
    shutil.copyfile(parent.path("model.ifc"), job.path("original.ifc"))

    # An uploaded IDS lives in the parent's directory; take a copy so this run
    # also keeps the exact ruleset it was audited against.
    ids_path = options.get("ids_path")
    if ids_path and os.path.dirname(os.path.abspath(ids_path)) == os.path.abspath(parent.dir):
        shutil.copyfile(ids_path, job.path("requirements.ids"))
        options["ids_path"] = job.path("requirements.ids")

    job.options["fixes"] = selected
    job.options["fix_values"] = values
    job.options["parent_issues"] = parent.result["issues"]
    with _LOCK:
        JOBS[job.id] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return job


def _apply_fixes(job: Job) -> None:
    import json

    import ifcopenshell
    from ifcaudit import fixes

    model = ifcopenshell.open(job.path("original.ifc"))
    report = fixes.apply(model, job.options["fixes"], job.options["fix_values"])
    model.write(job.path("model.ifc"))
    job.size = os.path.getsize(job.path("model.ifc"))

    job.changes = {"source": job.parent_filename, "source_run": job.parent_id,
                   "output": job.filename, **report}
    with open(job.path("changes.json"), "w", encoding="utf-8") as fh:
        json.dump(job.changes, fh, indent=2, default=str)
    c = report["counts"]
    job.log.append(f"{c['applied']} fix(es) applied, {c['failed']} failed, "
                   f"{c['skipped']} skipped; original kept as original.ifc")


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
    job.step_index = next((i for i, (k, _) in enumerate(job.steps) if k == key), 0)
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
        if job.parent_id:
            _advance(job, "fix", "Applying approved fixes to a copy…")
            _apply_fixes(job)

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

        payload = result.to_dict()
        if summary:
            payload["ids"] = summary

        if job.options.get("build_db", True):
            _advance(job, "sqlite", "Building queryable database…")
            try:
                sql_export.build(job.path("model.ifc"), job.path("model.db"))
                # The audit goes in too, so questions about issues are
                # answered by SQL like everything else.
                sql_export.add_audit(job.path("model.db"), payload, summary,
                                     job.filename)
                job.db_info = {"path": job.path("model.db"),
                               "size": os.path.getsize(job.path("model.db")),
                               **sql_export.describe(job.path("model.db"))}
                job.log.append(f"{len(job.db_info['tables'])} tables written")
            except Exception as exc:
                # A failed SQL export must not lose the audit that already ran.
                job.log.append(f"Database export failed: {exc}")

        _advance(job, "report", "Generating reports…")
        json_report.write(result, job.path("report.json"), ids_summary=summary)
        html_report.write(result, job.path("report.html"), ids_summary=summary)
        exports.workbook(payload, summary, job.path("report.xlsx"))
        with open(job.path("issues.csv"), "w", encoding="utf-8") as fh:
            fh.write(exports.issues_csv(payload))

        if job.parent_id:
            from ifcaudit.diff import compare
            job.diff = compare(
                job.options["parent_issues"], payload["issues"],
                regenerated_guids=[g["new"] for g in job.changes["regenerated_guids"]],
                applied=job.changes["changes"],
            )
            job.log.append(f"{job.diff['resolved']} resolved, {job.diff['new']} new "
                           f"vs {job.parent_filename}")

        job.result = payload
        job.status = "done"
        job.message = "Complete"
        job.step_index = len(job.steps) - 1
    except Exception as exc:
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.message = "Failed"
        job.log.append(job.error)
        job.log.append(traceback.format_exc()[-1200:])
    finally:
        job.finished_at = time.time()
