# ifc-demo — IFC model auditor

Upload an IFC file. The system runs the whole analysis and gives you the
report. No canvas, no nodes, no configuration.

> **New here?** [INSTALL.md](INSTALL.md) is a step-by-step guide to installing
> and using it: no programming needed. [HOW_IT_WORKS.md](HOW_IT_WORKS.md)
> explains the whole flow and each step in detail.

Two ways in:

- **`run_web.bat`** (Windows) / **`run_web.sh`** (macOS, Linux) → the web app at <http://127.0.0.1:8000>
- **`run_demo.bat`** → the CLI, same engine, for scripts and CI

What you get: schema, integrity and IDS checks; a **Fix** tab that repairs
issues on a copy of the file and re-audits it; a **3D** view coloured by
issue severity; and an **Ask** box that answers questions with SQL.

| Layer | What it checks | Status |
|---|---|---|
| **L0** Schema | Is this a valid IFC file? | ✅ EXPRESS rules via `ifcopenshell.validate` |
| **L1** Integrity | Orphans, duplicate GUIDs, units, georeferencing, geometry | ✅ 18 rules |
| **L2** Requirements | IDS — buildingSMART Information Delivery Specification | ✅ 4 example specs |
| **L3** Compliance | Custom logic (cross-element, project rules) | 🔌 seam ready |
| **L4** Geometry | Clash and clearance detection | 🔌 seam ready |

---

## Quick start

Needs **Python 3.10–3.13** ([python.org](https://www.python.org/downloads/);
on Windows tick *Add python.exe to PATH*).

```bash
git clone https://github.com/<owner>/<repo>.git ifc-audit
cd ifc-audit
```

No git? Use **Code → Download ZIP** on this page and unzip it.

Then double-click **`run_web.bat`** (macOS/Linux: `./run_web.sh`). It creates a
virtual environment, installs dependencies, generates a sample model with
deliberate defects, a defect-free one and an example IDS, and opens the
browser. Full walkthrough: [INSTALL.md](INSTALL.md).

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
receive → [apply fixes] → parse → validate schema → check IDS → run rules
        → build SQLite database → generate reports
```

(`apply fixes` only runs for a fixed copy. Details: [HOW_IT_WORKS.md](HOW_IT_WORKS.md).)

It runs in a background thread and the browser polls for progress, so a large
model never has to survive a request timeout. Each step reports what it is
doing rather than showing a spinner.

### The six tabs

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

**Fix** — a proposed fix for every issue: *Auto* (unambiguous, just approve),
*Needs a value* (you supply or confirm it; some are pre-filled with a
suggestion and its reason), or *Manual* (advice for the authoring tool).
Approved fixes are applied to a **copy**, which is re-audited and compared
with the original: resolved, new, remaining. The uploaded file is never
modified.

**3D** — the model rendered with three.js + web-ifc, coloured by the most
serious issue on each element. Click an element to see its issues; *view in
3D* on any issue flies to it. X-ray, isolate and a section slider. Needs
internet the first time (the 3D engine loads from jsDelivr).

**Downloads** — HTML report, Excel workbook, issues CSV, JSON, the SQLite
database, and the IFC. A fixed copy also offers the untouched original and a
change log.

---

## Natural-language questions

Optional. Copy `ai_settings.example.bat` to `ai_settings.bat` (macOS/Linux:
the `.sh` pair), fill in one provider, and start the app; the launcher loads
it. Claude, OpenAI and OpenRouter all work. The file is git-ignored.
Step-by-step: [INSTALL.md, Part 3](INSTALL.md#part-3-turn-on-the-ask-box-optional).

The audit itself is also in the database (`audit_*` tables), so questions like
*"what are the most serious issues?"* work too. The model writes the answer
sentence as a template with `{placeholders}` that are filled from the query
result, so it never writes a number itself.

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
├── run_web.bat / run_web.sh    one-click launchers (web app)
├── run_demo.bat                one-click CLI demo
├── ai_settings.example.*       template for the optional AI key
├── INSTALL.md                  install + step-by-step usage
├── HOW_IT_WORKS.md             the flow and each step in detail
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
│   ├── report/                 console / html / json
│   ├── fixes/                  fix proposals (@fixer) and the apply engine
│   └── diff.py                 run-to-run diff on the stable issue ids
│
├── webapp/                     the web layer
│   ├── main.py                 FastAPI routes
│   ├── jobs.py                 the pipeline + background runner
│   ├── sql_export.py           IFC → SQLite, read-only query guard
│   ├── nlq.py                  question → SQL → answer
│   ├── exports.py              Excel workbook + CSV
│   └── static/                 index.html, app.js, styles.css, viewer.js (no build step)
│
├── tools/                      sample model + IDS generators
├── tests/
│   ├── test_e2e.py             36 browser checks over the real app
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

36 checks: upload, pipeline completion, KPI values, severity bar, IDS table,
issue grouping, both filters, SQL console, example queries, the safety guard,
honest degradation of Ask, all six downloads (the .xlsx is downloaded and size-
checked), reopening a finished run, the 3D model loading and "view in 3D",
applying auto fixes to a copy with a verified re-audit, and zero uncaught JS
errors.

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
31 SQLite tables, about 3 seconds end to end.

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

**BCF export.** Without it, issues can't round-trip into Revit / Navisworks /
BIMcollab.

**Run-to-run diffing between separate uploads.** `ifcaudit/diff.py` already
compares a fixed copy with its source; comparing two independent uploads of
the same model (and a CLI `--baseline` flag) is the remaining step.

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
