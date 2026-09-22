# Project context for Claude

Read this before changing anything. It carries the decisions behind the code
so they don't get re-litigated or accidentally undone.

## What this is

An IFC/BIM model auditor. A user uploads an IFC file; a fixed pipeline runs the
whole analysis and produces a report. There is deliberately **no visual
workflow canvas** — the user configures nothing.

Two front doors, one engine:

- `serve.py` → FastAPI web app on http://127.0.0.1:8000
- `audit.py` → CLI, same engine, for scripts and CI

## Running it

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python tools\make_sample.py examples\sample_model.ifc
python tools\make_ids.py examples\project_requirements.ids

python serve.py
```

`run_web.bat` and `run_demo.bat` do all of the above in one double-click.

## Architecture

```
ifcaudit/        the engine — knows nothing about HTTP. Never import webapp from here.
  issues.py      Issue / ElementRef / AuditResult — the schema everything speaks
  context.py     AuditContext: model wrapper + indexes, built once, shared by all rules
  engine.py      @rule registry and runner
  rules/         integrity.py (L1), project.py (L0/L1), schema_check.py (L0), ids_runner.py (L2)
  report/        console / html / json

webapp/          the web layer
  main.py        FastAPI routes
  jobs.py        the pipeline + background thread runner
  sql_export.py  IFC → SQLite, read-only query guard
  nlq.py         question → SQL → answer
  exports.py     Excel workbook + CSV
  static/        index.html, app.js, styles.css — no build step, no framework
```

### Check layers

| Layer | What | Where |
|---|---|---|
| L0 | Schema validity | `rules/schema_check.py`, `rules/project.py` |
| L1 | Data integrity | `rules/integrity.py` — 18 rules total with project.py |
| L2 | Information requirements (IDS) | `rules/ids_runner.py` via IfcTester |
| L3 | Custom compliance logic | not built — use the `@rule` decorator |
| L4 | Geometry / clash | not built — see below |

## Decisions that must not be undone

**Everything becomes an `Issue`.** Integrity rules, IDS failures and schema
violations all produce the same object. That is why one template renders all of
them, and why adding clash detection later needs no change to any reporter.
Do not add a parallel result type.

**`Issue.id` is a stable hash**, `sha1(rule_id + element GUIDs + discriminator)`.
The same defect in the same element yields the same id on every run. This is
what makes run-to-run diffing ("12 new, 30 resolved") possible. Never replace
it with a uuid or a counter.

**Units are never assumed.** Use `ctx.unit_scale` (metres per project unit, from
`ifcopenshell.util.unit.calculate_unit_scale`) for every dimensional
comparison. Do not hardcode mm or m anywhere.

**`needs_geometry` on `@rule` gates the expensive tessellation pass.** Nothing
sets it yet, so a large model audits in seconds. Keep that gate.

**The AI never produces a number.** `nlq.py` sends the real schema, gets one
`SELECT` back, guards it, runs it against SQLite, and shows the SQL next to the
answer. With no API key the endpoint says so and offers example queries — it
does not fall back to anything clever. This is a deliberate reaction to
IFCflow's `server-python-executor.ts`, which regex-matches Python and
reimplements it in TypeScript, so unrecognised input gets a plausible wrong
answer. Never add a "best effort" path here.

**SQL is read-only.** Single statement, must start with SELECT/WITH, no
PRAGMA/ATTACH/DDL/DML, executed over a `mode=ro` connection. See
`sql_export.is_safe`.

**A rule that crashes becomes an issue, not an exception.** `engine.run`
catches per-rule so one bad rule never kills an audit.

## Adding a rule

One decorated generator. No central list to update beyond the import.

```python
from ifcaudit.engine import rule
from ifcaudit.issues import Category, Issue, Severity

@rule(id="PRJ.CEILING_HEIGHT", title="Minimum ceiling height",
      category=Category.COMPLIANCE, severity=Severity.ERROR)
def ceiling_height(ctx):
    for space in ctx.spaces:
        height = ...                       # ctx.unit_scale → metres
        if height < 2.4:
            yield Issue(
                rule_id="PRJ.CEILING_HEIGHT",
                severity=Severity.ERROR,
                category=Category.COMPLIANCE,
                title="Ceiling height below minimum",
                elements=[ctx.ref(space)],
                evidence={"key": space.GlobalId, "expected": 2.4, "actual": height},
            )
```

Drop it in `ifcaudit/rules/`, import it in `rules/__init__.py`. The `evidence`
dict should always carry a `key` — it feeds the stable id.

## The pipeline

`STEP_LABELS` in `webapp/jobs.py` **is** the workflow graph, already authored:

```
receive → parse → validate schema → check IDS → run rules
        → build SQLite → generate reports
```

IDS runs before rules because `ifcaudit.run` takes `extra_issues`, which must be
collected first. If you reorder execution, reorder `STEP_LABELS` to match or the
progress UI jumps backwards.

## Testing — run these before calling a change done

```bat
REM terminal 1
python serve.py --no-open --port 8112

REM terminal 2
python tests\test_e2e.py           REM 28 browser checks, real Chromium, no mocks
python tests\test_nlq_stub.py      REM text-to-SQL chain, no API key needed
```

`tests/test_e2e.py` needs `pip install playwright && playwright install chromium`.

**Known-defect coverage.** `tools/make_sample.py` injects twelve deliberate
defects and the ruleset catches all twelve — the table is in README.md. If you
add a rule, add a matching defect to the sample generator.

Expected result on the sample: **21 errors, 35 warnings, 54 info** over 29
elements, 27 SQLite tables, ~3s end to end. If those numbers move, understand
why before committing.

**False-positive baseline.** `python tools\make_sample.py examples\clean_model.ifc --clean`
builds the same tower with no defects (36 elements, typed, materialised,
georeferenced, spaces, full common psets). It must audit at **0 / 0 / 0** with
the IDS and `--schema-check`. If a new rule fires on it, the rule is wrong or
the clean model needs the data the rule expects. Pick one deliberately.

## Licence note — important

`D:\Companies\Others\RND\ai-ifc` holds **IFCflow** (`louistrue/ifc-flow`), which
is **AGPL-3.0**. Its network-use clause obliges anyone hosting a derived work to
publish their complete source.

Ideas were taken from it; **no code was copied**. This project is a clean-room
implementation against IfcOpenShell directly. Do not paste code from that folder
into this one.

What was taken as ideas: IFC→SQLite (moved from browser Pyodide to server-side
CPython calling the same official `ifcpatch` `Ifc2Sql` recipe), SQL as the
substrate for AI questions, multi-format export, and the typed pipeline —
inverted so it is authored once rather than dragged per use.

## Not built yet, in rough priority order

1. **3D viewer** — "click an issue → see the element highlighted". `Issue.location`
   and the stable ids are already in place. Build on `web-ifc` + `three.js`
   directly, not on IFCflow's wrapper.
2. **Clash detection (L4)** — `ifcopenshell.geom.tree`, `clash_intersection_many` /
   `clash_clearance_many`. Two things first: check georeferencing
   (`PRJ.GEOREFERENCE` already does — misaligned models give either zero clashes
   or a million, silently), and group results (one pipe through forty studs is
   one issue, not forty).
3. **BCF export** — without it, issues can't round-trip into Revit / Navisworks /
   BIMcollab.
4. **Run-to-run diffing** — ~40 lines on the stable ids: load the previous JSON,
   compare id sets, report new / resolved / persisting.
5. **Multi-file federation** — `AuditContext` wraps one model today.
   `ElementRef.source_file` is already in the schema for when it wraps several.

## Production gaps (fine for a local tool, not for a service)

Jobs live in memory, files on local disk under `data/<job-id>/`. No
authentication; the server binds to `127.0.0.1`. A multi-user deployment needs a
real queue, object storage and auth.

## Environment variables

| Var | Default | Effect |
|---|---|---|
| `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | unset | enables the Ask box |
| `IFC_NLQ_MODEL` | `gpt-4o-mini` | model for text-to-SQL |
| `OPENAI_BASE_URL` | OpenAI | any OpenAI-compatible endpoint |
| `IFC_MAX_UPLOAD_MB` | 500 | upload cap |
| `IFC_DATA_DIR` | `./data` | where job data goes |
