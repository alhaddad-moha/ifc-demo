# ifc-demo — IFC model auditor

Upload an IFC file. The system runs the whole analysis and gives you the
report. No canvas, no nodes, no configuration.

Two ways in:

- **`run_web.bat`** → the web app at <http://127.0.0.1:8000>
- **`run_demo.bat`** → the CLI, same engine, for scripts and CI

| Layer | What it checks | Status |
|---|---|---|
| **L0** Schema | Is this a valid IFC file? | ✅ EXPRESS rules via `ifcopenshell.validate` |
| **L1** Integrity | Orphans, duplicate GUIDs, units, georeferencing, geometry | ✅ 18 rules |
| **L2** Requirements | IDS — buildingSMART Information Delivery Specification | ✅ 4 example specs |
| **L3** Compliance | Custom logic (cross-element, project rules) | 🔌 seam ready |
| **L4** Geometry | Clash and clearance detection | 🔌 seam ready |

---

## Quick start (Windows)

Double-click **`run_web.bat`**. It creates a virtual environment, installs
dependencies, generates a sample model with deliberate defects plus an example
IDS, and opens the browser.

Drop `examples\sample_model.ifc` onto the page to see the whole thing work.

### Manual

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python tools\make_sample.py examples\sample_model.ifc
python tools\make_sample.py examples\clean_model.ifc --clean   REM defect-free baseline
python tools\make_ids.py examples\project_requirements.ids

python serve.py
```

---

## What happens on upload

A fixed, declared pipeline — `webapp/jobs.py`, `STEP_LABELS`:

```
receive → parse → validate schema → check IDS → run rules
        → build SQLite database → generate reports
```

It runs in a background thread and the browser polls for progress, so a large
model never has to survive a request timeout. Each step reports what it is
doing rather than showing a spinner.

### The four tabs

**Overview** — KPI row, severity distribution, IDS pass/fail per specification,
element breakdown by class.

**Issues** — every finding grouped by rule, filterable by severity, category and
free text. Each row carries the element, its storey, the finding and the
evidence behind it.

**Data** — this is the interesting one. The model is also converted into a
**SQLite database**, so you can query it directly:

```sql
SELECT d.Name, p.value AS FireRating
FROM IfcDoor d
LEFT JOIN psets p ON p.ifc_id = d.ifc_id AND p.name = 'FireRating'
```

There is a SQL console with worked examples, and an **Ask** box that turns a
plain question into SQL. See *Natural-language questions* below.

**Downloads** — HTML report, Excel workbook, issues CSV, JSON, the SQLite
database, and the original IFC.

---

## Natural-language questions

Optional. Set a key **before** starting the server:

```bat
set OPENAI_API_KEY=sk-...
python serve.py
```

`OPENROUTER_API_KEY` works too; `IFC_NLQ_MODEL` picks the model (default
`gpt-4o-mini`).

How it works, and why it is built this way:

1. The model is shown the **real database schema** and asked for one `SELECT`.
2. The SQL is checked — single statement, read-only, no `PRAGMA`/`ATTACH` — and
   run against a read-only connection.
3. The **SQL is displayed with the answer.**

So the number comes from SQLite, not from the language model, and you can check
the query that produced it. If a column is invented, the query fails loudly
rather than returning a plausible wrong figure.

**Without a key, the app says so and offers the example queries.** It never
fabricates an answer. This matters — see *What was deliberately not copied*.

---

## CLI

```
python audit.py MODEL.ifc [options]

  --ids PATH             apply an .ids information-requirements file
  --schema-check         also run full IFC schema validation
  --out DIR              output directory (default: reports)
  --include RULE...      only run these rule ids or prefixes, e.g. INT. SPA.
  --exclude RULE...      skip these rule ids or prefixes
  --fail-on LEVEL        exit 1 if issues at error|warning|info exist
  --list-rules           print every registered rule and exit
```

`--fail-on error` makes it a CI gate:

```bat
python audit.py model.ifc --ids requirements.ids --fail-on error --no-open
if errorlevel 1 echo Model rejected
```

---

## Project layout

```
ifc-demo/
├── serve.py                    start the web app
├── audit.py                    CLI entry point
├── run_web.bat / run_demo.bat  one-click launchers
│
├── ifcaudit/                   the engine — knows nothing about HTTP
│   ├── issues.py               Issue / ElementRef / AuditResult
│   ├── context.py              model wrapper + indexes
│   ├── engine.py               @rule registry and runner
│   ├── rules/
│   │   ├── integrity.py        L1 — 10 data-integrity rules
│   │   ├── project.py          L0/L1 — units, georeferencing, spatial structure
│   │   ├── schema_check.py     L0 — ifcopenshell.validate adapter
│   │   └── ids_runner.py       L2 — IfcTester/IDS adapter
│   └── report/                 console / html / json
│
├── webapp/                     the web layer
│   ├── main.py                 FastAPI routes
│   ├── jobs.py                 the pipeline + background runner
│   ├── sql_export.py           IFC → SQLite, read-only query guard
│   ├── nlq.py                  question → SQL → answer
│   ├── exports.py              Excel workbook + CSV
│   └── static/                 index.html, app.js, styles.css (no build step)
│
├── tools/                      sample model + IDS generators
├── tests/
│   ├── test_e2e.py             28 browser checks over the real app
│   └── test_nlq_stub.py        text-to-SQL plumbing, no API key needed
└── examples/
```

---

## Tests

**End-to-end, in a real browser** — no mocks, the same pipeline a user triggers:

```bat
pip install playwright
playwright install chromium

python serve.py --no-open --port 8112      REM terminal 1
python tests\test_e2e.py                   REM terminal 2
```

28 checks: upload, pipeline completion, KPI values, severity bar, IDS table,
issue grouping, both filters, SQL console, example queries, the safety guard,
honest degradation of Ask, all six downloads (the .xlsx is downloaded and size-
checked), reopening a finished run, and zero uncaught JS errors.

**Text-to-SQL, without an API key** — stands up a stub OpenAI-compatible server
and checks the whole chain including markdown-fence stripping:

```bat
python tests\test_nlq_stub.py
```

**Known-defect coverage.** `tools/make_sample.py` injects twelve deliberate
defects; the ruleset catches all twelve:

| Injected defect | Caught by |
|---|---|
| Duplicate GlobalId on two walls | `INT.DUPLICATE_GUID`, `SCHEMA.INVALID` |
| Pipe segment with no spatial container | `INT.MISSING_CONTAINER` |
| Wall with a blank Name | `INT.EMPTY_NAME` |
| Door with no geometric representation | `INT.NO_GEOMETRY` |
| Unclassified `IfcBuildingElementProxy` | `INT.PROXY_ELEMENT` |
| Two identical walls at one point | `INT.DUPLICATE_PLACEMENT` |
| Opening that voids nothing | `INT.ORPHAN_OPENING`, `SCHEMA.INVALID` |
| Storey with no Elevation | `SPA.STOREY_ELEVATION` |
| No georeferencing | `PRJ.GEOREFERENCE` |
| Doors missing FireRating | `IDS.Doors carry a fire rating` |
| Walls missing IsExternal | `IDS.Walls declare IsExternal` |
| Windows missing ThermalTransmittance | `IDS.Windows declare thermal transmittance` |

Current run on the sample: **21 errors, 35 warnings, 54 info** over 29 elements,
27 SQLite tables, about 3 seconds end to end.

---

## Design notes

### Everything becomes an `Issue`

Integrity rules, IDS failures and schema violations all produce the same object,
which is why one template renders all of them and why adding clash detection
later needs no change to any reporter.

Each carries a **stable id** — `sha1(rule_id + element GUIDs + discriminator)`.
The same defect in the same element yields the same id on every run, which is
what makes *"12 new, 30 resolved since last week"* possible.

### Adding a rule is writing one function

```python
from ifcaudit.engine import rule
from ifcaudit.issues import Category, Issue, Severity

@rule(id="PRJ.CEILING_HEIGHT", title="Minimum ceiling height",
      category=Category.COMPLIANCE, severity=Severity.ERROR)
def ceiling_height(ctx):
    for space in ctx.spaces:
        height = ...                       # ctx.unit_scale converts to metres
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

Drop the module in `ifcaudit/rules/`, import it in `rules/__init__.py`, done.
A rule that crashes is reported as an issue and never kills the audit.

### The pipeline is a saved workflow

`STEP_LABELS` in `webapp/jobs.py` *is* the graph, already authored. If you ever
want a visual editor, it becomes an internal tool for producing more entries in
that list — not something the end user has to learn.

---

## What was taken from IFCflow, and what wasn't

The `ai-ifc` folder holds **IFCflow** (`louistrue/ifc-flow`), AGPL-3.0. Ideas
were taken; no code was copied.

**Taken — as ideas, reimplemented:**

- **IFC → SQLite.** Their best idea by a distance. Moved from browser Pyodide to
  server-side CPython calling the same official `ifcpatch` `Ifc2Sql` recipe:
  fewer moving parts, and no ~2–4 GB WASM memory ceiling.
- **SQL as the substrate for AI questions.** Far safer than having a model emit
  ifcopenshell code nobody can audit.
- **Multi-format export.** The people who receive an audit live in Excel.
- **A pipeline of typed steps**, inverted — authored once, not dragged per use.

**Deliberately not copied:**

- **`server-python-executor.ts`.** 829 lines that import `spawn` on line 6 and
  never call it. It regex-matches Python source and reimplements it in
  TypeScript, so an unrecognised question gets a plausible wrong answer. The
  `nlq.py` design here is the direct response: real SQL, shown to the user,
  executed by a real database — and an honest "not configured" when no key is
  set.
- **Their clash detection.** Advertised in the README; `analysis-utils.ts`
  returns `{error: "Not implemented"}`.
- **The canvas UI**, which is the thing you explicitly did not want.

**Licence.** IFCflow is AGPL-3.0, whose network-use clause obliges anyone
hosting a derived work to publish their complete source. That is why this is a
clean-room implementation against IfcOpenShell directly.

---

## What's still missing, and why

**Clash detection (L4).** The seam is `needs_geometry=True` on `@rule`, which
gates the expensive tessellation pass — nothing sets it yet, so a large model
still audits in seconds. Two things to get right first: **check georeferencing**
(`PRJ.GEOREFERENCE` already does — misaligned models give either zero clashes or
a million, silently), and **group results** (one pipe through forty studs is one
issue, not forty).

**3D viewer.** "Click an issue → see the element highlighted" is the next big
usability jump. `Issue.location` and the stable ids are already in place. Build
it on `web-ifc` + `three.js` directly.

**BCF export.** Without it, issues can't round-trip into Revit / Navisworks /
BIMcollab.

**Run-to-run diffing.** The stable ids make this ~40 lines: load the previous
JSON, compare id sets, report new / resolved / persisting.

**Production concerns.** Jobs live in memory and files on local disk, which is
right for a single-machine tool and wrong for a multi-user service — that needs
a real queue, object storage and authentication.

---

## Notes

- Units are never assumed. `ctx.unit_scale` gives metres per project unit via
  `ifcopenshell.util.unit.calculate_unit_scale`. Use it for every dimensional
  comparison.
- Uploads are capped by `IFC_MAX_UPLOAD_MB` (default 500). Job data goes to
  `data/<job-id>/`; set `IFC_DATA_DIR` to move it.
- The SQL console accepts a single read-only `SELECT`/`WITH` and nothing else,
  over a read-only connection.
- The server binds to `127.0.0.1` by default. It has **no authentication** — put
  it behind something before exposing it with `--host 0.0.0.0`.
- The standalone HTML report loads no external resources at all.
