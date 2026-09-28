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

`run_web.bat` / `run_web.sh` and `run_demo.bat` do all of the above in one
double-click. The launchers load `ai_settings.bat` / `ai_settings.sh` if present
(git-ignored; templates are the `.example` files). User docs: `INSTALL.md`,
`HOW_IT_WORKS.md`. Keep them in step with behaviour changes.

## Architecture

```
ifcaudit/        the engine — knows nothing about HTTP. Never import webapp from here.
  issues.py      Issue / ElementRef / AuditResult — the schema everything speaks
  context.py     AuditContext: model wrapper + indexes, built once, shared by all rules
  engine.py      @rule registry and runner
  rules/         integrity.py (L1), project.py (L0/L1), schema_check.py (L0), ids_runner.py (L2)
  report/        console / html / json
  fixes/         @fixer proposals + apply (builtin.py holds the fixers)
  diff.py        run-to-run diff on the stable ids

webapp/          the web layer
  main.py        FastAPI routes
  jobs.py        the pipeline + background thread runner
  sql_export.py  IFC → SQLite, read-only query guard
  nlq.py         question → SQL → answer
  exports.py     Excel workbook + CSV
  static/        index.html, app.js, styles.css, viewer.js — no build step, no framework
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

**Answer wording is a template, numbers are not.** The model returns
`{"sql", "answer"}`; `answer` uses `{column}` placeholders that
`nlq.fill_answer` fills from the result rows. A template with any digit of its
own, or naming a column the query didn't return, is dropped. The audit is
written into the same SQLite file (`audit_file`, `audit_issues`,
`audit_issue_elements`, `audit_ids`) so questions about issues get the same
guarantee.

**SQL is read-only.** Single statement, must start with SELECT/WITH, no
PRAGMA/ATTACH/DDL/DML, executed over a `mode=ro` connection. See
`sql_export.is_safe`.

**A rule that crashes becomes an issue, not an exception.** `engine.run`
catches per-rule so one bad rule never kills an audit.

**Fixes never touch the uploaded file.** Approving fixes creates a *new* job:
`original.ifc` (byte copy of the source), `model.ifc` (fixed), `changes.json`
(every fix, its values, its outcome). The parent job's directory is never
written to. The copy is then re-audited and diffed against the parent.

**The client never sends operations.** A `Fix` carries its `ops` as data,
generated server-side from the model; the apply endpoint takes only issue ids
and values, re-validates them (`fixes.coerce`) and uses the server's own
proposals. Ops address elements by STEP id, not GUID, because GUIDs can be
duplicated and the copy is byte-identical so STEP ids stay valid.

**Fixers never invent values.** A fixer may *suggest* something derived
deterministically from the model (storey from an element's z, the next storey
elevation from the spacing, a proxy's IFC class from keywords in its Revit
family/type name via `CLASS_HINTS`) and must say how in `inferred`. "Select all
suggestions" in the UI ticks exactly those; the user still presses Apply. Fire ratings,
materials, coordinates and the like always come from the user. Issues that
can't be repaired in the IFC (no geometry, missing types, schema violations) are
`MANUAL` with advice text, never a guess.

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

If the defect can be repaired inside the IFC, add a fixer in
`ifcaudit/fixes/builtin.py` with `@fixer("YOUR.RULE_ID")` returning a `Fix`
(`AUTO` / `INPUT`). Otherwise add a line to `ADVICE` in `fixes/__init__.py`.

## The pipeline

`STEP_LABELS` in `webapp/jobs.py` **is** the workflow graph, already authored:

```
receive → [apply fixes] → parse → validate schema → check IDS → run rules
        → build SQLite → generate reports
```

`apply fixes` only appears on a fixed copy (`Job.steps` filters it out otherwise).

IDS runs before rules because `ifcaudit.run` takes `extra_issues`, which must be
collected first. If you reorder execution, reorder `STEP_LABELS` to match or the
progress UI jumps backwards.

## Testing — run these before calling a change done

```bat
REM terminal 1
python serve.py --no-open --port 8112

REM terminal 2
python tests\test_e2e.py           REM 36 browser checks, real Chromium, no mocks
python tests\test_nlq_stub.py      REM text-to-SQL chain, no API key needed
```

`tests/test_e2e.py` needs `pip install playwright && playwright install chromium`.

**Known-defect coverage.** `tools/make_sample.py` injects twelve deliberate
defects and the ruleset catches all twelve — the table is in README.md. If you
add a rule, add a matching defect to the sample generator.

Expected result on the sample: **21 errors, 35 warnings, 54 info** over 29
elements, 31 SQLite tables, ~3s end to end. If those numbers move, understand
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

1. **3D viewer**: built (`static/viewer.js`, the 3D tab). web-ifc + three.js
   from jsDelivr via the import map in `index.html`, so it needs internet.
   Elements join to the audit by STEP id = web-ifc expressID
   (`/api/jobs/<id>/elements`). Next: side-by-side original vs fixed copy.
2. **Clash detection (L4)** — `ifcopenshell.geom.tree`, `clash_intersection_many` /
   `clash_clearance_many`. Two things first: check georeferencing
   (`PRJ.GEOREFERENCE` already does — misaligned models give either zero clashes
   or a million, silently), and group results (one pipe through forty studs is
   one issue, not forty).
3. **BCF export** — without it, issues can't round-trip into Revit / Navisworks /
   BIMcollab.
4. **Run-to-run diffing** — `ifcaudit/diff.py` exists and the fix flow uses it
   (parent vs fixed copy). Still missing: diffing two independent uploads of
   the same model, and a CLI flag (`audit.py --baseline previous.json`).
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
| `OPENAI_BASE_URL` | OpenAI | any OpenAI-compatible endpoint (Claude: `https://api.anthropic.com/v1`) |
| `ANTHROPIC_WORKSPACE_ID` | unset | sent as `anthropic-workspace-id`; needed for Anthropic keys not scoped to a workspace |
| `IFC_MAX_UPLOAD_MB` | 500 | upload cap |
| `IFC_DATA_DIR` | `./data` | where job data goes |
