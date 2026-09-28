# How IFC Audit works

This document explains what happens from the moment a model is uploaded to
the moment a fixed copy is downloaded: the overall flow, each step in detail,
and the design rules that keep the results trustworthy.

- To **install and run** it, see [INSTALL.md](INSTALL.md).
- For **developer conventions**, see [CLAUDE.md](CLAUDE.md).

---

## 1. The big picture

```text
  User ──uploads .ifc──► Web app (webapp/) ──┐
                                             ├──► Audit engine (ifcaudit/) ──► Issues
  Script / CI ─────────► audit.py (CLI) ─────┘            ▲                     │
                                                          │                     ├──► Reports: HTML, Excel, CSV, JSON
                                                          │                     ├──► SQLite: model + audit ──► Ask box (question → SQL)
                                                          │                     ├──► 3D viewer (coloured by issue)
                                                          │                     └──► Fix proposals
                                                          │                              │
                                                          └──── re-audit ◄── Fixed copy ◄┘ (approved by the user)
```

There are two front doors to one engine:

| | What it is | Used for |
|---|---|---|
| `serve.py` | FastAPI web app on `127.0.0.1:8000` | People: upload, review, fix, view in 3D, ask |
| `audit.py` | Command line | Scripts and CI gates (`--fail-on error`) |

The **engine** (`ifcaudit/`) knows nothing about the web. It takes a model and
returns a list of `Issue` objects. Everything else (reports, database, fixes,
3D colours, AI answers) is built from that list.

---

## 2. The pipeline: what happens on upload

The user configures nothing. A fixed sequence of steps runs in a background
thread, and the browser polls for progress. The sequence is declared once in
`STEP_LABELS` in `webapp/jobs.py`:

```text
  1. Receive file
        │
        ├── fixed copy? ──yes──► 1b. Apply approved fixes ──┐
        │                                                   │
        ▼ no                                                │
  2. Parse IFC  ◄───────────────────────────────────────────┘
        │
        ▼
  3. Validate schema            (L0: IFC schema + EXPRESS rules)
        │
        ▼
  4. Check IDS requirements     (L2: IfcTester)
        │
        ▼
  5. Run integrity rules        (L1: 18 rules)
        │
        ▼
  6. Build SQLite database      (model tables + audit_* tables)
        │
        ▼
  7. Generate reports           (HTML, Excel, CSV, JSON)
        │
        ▼
     Done: results page
```

### Step 1: Receive
`POST /api/upload`. The file is saved as `data/<run-id>/model.ifc` (limit
500 MB, set by `IFC_MAX_UPLOAD_MB`). If the user supplied their own `.ids`
file, it is saved next to it as `requirements.ids`, so the run keeps the exact
ruleset it was checked against. A run id is returned immediately; the rest
happens in the background.

### Step 1b: Apply fixes (fixed copies only)
Only for runs created from the **Fix** tab. See [section 5](#5-fixing-issues).

### Step 2: Parse
IfcOpenShell opens the file and an `AuditContext` is built around it. The
context computes, once, the indexes every rule needs: all physical elements,
storeys, spaces, element-to-storey lookup, GUID-to-entity lookup, and the
project **unit scale** (metres per project unit). Rules query these indexes
and never re-scan the file.

### Step 3: Validate schema (L0)
`ifcopenshell.validate` checks the file against the IFC schema: attribute
types, required attributes, and the formal EXPRESS rules (e.g. "a face's edges
must form a closed loop"). Each violation becomes an **error** issue
(`SCHEMA.INVALID`). At most 200 are listed; the rest are counted.

### Step 4: Check information requirements (L2)
The model is checked against an **IDS** (buildingSMART Information Delivery
Specification) file using IfcTester. The example IDS
(`examples/project_requirements.ids`) requires that:

- doors carry `Pset_DoorCommon.FireRating`,
- walls declare `Pset_WallCommon.IsExternal`,
- slabs have a Name,
- windows declare `Pset_WindowCommon.ThermalTransmittance`.

Each failing element becomes an **error** issue (`IDS.<specification>`). A
specification that matched no elements at all becomes an **info** issue:
usually that means the filter doesn't fit how the model was exported.

IDS runs *before* the rules because the rule runner receives these issues as
`extra_issues` and merges them into one result.

### Step 5: Run integrity rules (L1)
18 rules, each a small Python function registered with `@rule`:

| Rule | Severity | Finds |
|---|---|---|
| `INT.DUPLICATE_GUID` | error | Two entities share a GlobalId |
| `INT.MISSING_CONTAINER` | error | Element not placed on any storey |
| `INT.EMPTY_NAME` | warning | Blank element Name |
| `INT.NO_GEOMETRY` | warning | Element has no 3D representation |
| `INT.NO_MATERIAL` | warning | No material assigned |
| `INT.NO_TYPE` | info | Not linked to a type object |
| `INT.PROXY_ELEMENT` | warning | Exported as a generic `IfcBuildingElementProxy` |
| `INT.DUPLICATE_PLACEMENT` | warning | Same class + name at identical coordinates |
| `INT.ORPHAN_OPENING` | warning | Opening that cuts nothing |
| `INT.MISSING_COMMON_PSET` | info | Missing the standard `Pset_<Class>Common` |
| `PRJ.SCHEMA_VERSION` | info/warning | Old IFC2X3 schema |
| `PRJ.NO_PROJECT` | error | Zero or several `IfcProject` |
| `PRJ.UNITS` | error/warning | No units, or non-metric units |
| `PRJ.GEOREFERENCE` | warning | No map conversion and no site latitude/longitude |
| `SPA.NO_STOREYS` | error | Building with no storeys |
| `SPA.STOREY_ELEVATION` | warning | Storey without an Elevation |
| `SPA.DUPLICATE_STOREY_ELEVATION` | warning | Two storeys at the same level |
| `SPA.NO_SPACES` | info | Model defines no rooms/spaces |

A rule that crashes doesn't stop the audit. It is reported as one warning
(`ENGINE.RULE_FAILED`) and the other rules continue.

### Step 6: Build the database
The model is converted to **SQLite** with the official `ifcpatch` *Ifc2Sql*
recipe: one table per IFC class present (`IfcWall`, `IfcDoor`…), plus `psets`
(every property value), `id_map` (every entity's class) and `metadata`.

The audit result is written into the same file as four more tables:

| Table | Contents |
|---|---|
| `audit_file` | One row: file name, project, schema, unit, element/storey/space counts, issue counts by severity |
| `audit_issues` | One row per issue: rule, severity, title, storey, element count |
| `audit_issue_elements` | Which elements each issue points at |
| `audit_ids` | Pass/fail per IDS specification |

This database powers the **SQL console** and the **Ask** box, and can be
downloaded.

### Step 7: Reports
Written to the run folder and offered under **Downloads**:

| File | Format | For |
|---|---|---|
| `report.html` | Self-contained web page | Sharing; opens offline |
| `report.xlsx` | Excel: summary, issues, IDS, elements | People who live in Excel |
| `issues.csv` | One row per issue/element | Other tools |
| `report.json` | Machine-readable | CI, scripts, run-to-run comparison |
| `model.db` | SQLite | Your own queries |

---

## 3. The Issue: one format for everything

Every finding (schema violation, IDS failure, integrity rule) becomes the same
object:

```
Issue
  id           stable 12-character hash (see below)
  rule_id      e.g. INT.NO_MATERIAL, IDS.Doors carry a fire rating
  severity     error | warning | info
  category     schema | integrity | ids | compliance | clash
  title, description
  elements     [ {guid, ifc_class, name, storey} ]
  evidence     the data behind the finding, e.g. {expected, found}
```

**The id is stable:** `sha1(rule_id + element GUIDs + discriminator)`. The same
defect in the same element gets the same id on every run and on every
machine. That makes it possible to compare runs precisely ("9 resolved, 0
new"). A random id would make every run look entirely new.

Because there is one format, one report template renders all issue types, and
future checks (e.g. clash detection) need no change to any report.

---

## 4. Reviewing results

### Issues tab
Issues grouped by rule, most serious first. Filters: severity, category, free
text (matches rule, element name, GUID, storey, description).

### 3D tab

```text
  Browser                               Server                     jsDelivr (CDN)
     │                                     │                             │
     │── three.js + web-ifc (first time) ─────────────────────────────►  │
     │── GET /api/jobs/{id}/elements ────►│                             │
     │◄── [{id, guid, class, name, storey}]│                             │
     │── GET /api/jobs/{id}/download/ifc ►│                             │
     │◄── model.ifc ───────────────────────│                             │
     │
     ├─ web-ifc turns the IFC into triangles, three.js draws them
     └─ each mesh: expressID = STEP id → element → GUID → its issues → colour
```

- **web-ifc** (WebAssembly) turns the IFC into triangles inside the browser;
  **three.js** draws them. Both are loaded from jsDelivr, which is why the tab
  needs internet.
- web-ifc identifies each mesh by its **expressID**, which equals the IFC
  STEP id (`#123`). The server's `/elements` list maps STEP id → GUID, class,
  name and storey, and the audit's issues are matched by GUID. So colours and
  click-to-inspect use exactly the same data as the report.
- Colour = the most serious issue on that element. Elements without geometry
  can't be drawn; "view in 3D" says so.

---

## 5. Fixing issues

```text
  User              Browser                                  Server
   │                   │                                        │
   │── open Fix tab ──►│── GET /api/jobs/{id}/fixes ──────────►│
   │                   │◄── proposals (kind, fields, suggestion)│
   │── tick, fill, ───►│                                        │
   │   Apply           │── POST /fixes/apply {issue_id,values} ►│
   │                   │                                        ├─ check values against its own proposals
   │                   │◄── new run id ─────────────────────────│
   │                   │                                        ├─ copy source → original.ifc (untouched)
   │                   │                                        ├─ apply fixes → model.ifc
   │                   │                                        ├─ write changes.json
   │                   │                                        ├─ full re-audit of the copy
   │                   │                                        └─ diff against the source run
   │                   │── poll, then GET result ─────────────►│
   │◄── results + ─────│◄── new results ────────────────────────│
   │    "resolved / new" banner                                 │
```

### 5.1 Proposals
For every issue, a **fixer** (registered with `@fixer("RULE.ID")` in
`ifcaudit/fixes/builtin.py`) proposes one of three kinds:

| Kind | Meaning | Examples |
|---|---|---|
| **Auto** | Only one sensible fix; the user just approves | Duplicate GUID → new GUID for the copy · stacked duplicate → delete the copy · opening that cuts nothing → delete it |
| **Needs a value** | The user supplies (or confirms) a value | Fire rating, IsExternal, U-value, material, name, storey, storey elevation, site latitude/longitude, class for a proxy |
| **Manual** | Can't be repaired inside the IFC | No geometry, missing types, schema violations: fix in the authoring tool; advice text says how |

Input fields are typed from the IFC property templates: a boolean becomes a
True/False list, a measure becomes a number (with its unit), an enumeration
becomes a dropdown.

**Suggestions.** A fixer may pre-fill a value only when it can derive it from
the model, and it must show how:

| Fix | Suggestion derived from |
|---|---|
| Element with no storey | Its height (z) versus the storey elevations |
| Storey with no elevation | The spacing of the other storeys |
| Proxy element | Keywords in its Revit family/type name (e.g. *Muntin* → `IfcMember`, *Trim* / *Corniche* → `IfcCovering`) |

Fire ratings, materials, thermal values and coordinates are **never
suggested**: they are design and safety decisions.

### 5.2 Applying
1. The browser sends only **issue ids and typed values**. The operations
   themselves come from the proposals the server generated, so a request can't
   ask for an edit no fixer proposed. Values are re-validated on the server.
2. A new run is created. The source model is copied byte-for-byte to
   `original.ifc`. **The uploaded file and its run folder are never written
   to.**
3. Operations are applied to the copy through the IfcOpenShell API, in a safe
   order: property/attribute edits first, then GUID changes, then deletions
   last. Elements are addressed by STEP id, which is unambiguous even when
   GUIDs are duplicated.
4. Each fix is recorded in `changes.json` as *applied*, *failed* or
   *skipped*, with its values. One failing fix never stops the others.
5. The copy is saved as `model.ifc` and goes through the **full pipeline**
   again (schema, IDS, rules, database, reports).

### 5.3 Verifying
The new result is compared with the original run on the stable issue ids:

| Count | Meaning |
|---|---|
| **Resolved** | In the original, gone from the fixed copy |
| **New** | Not in the original, split by severity (e.g. a reclassified element now expects a different property set) |
| **Carried** | Same defect, but its element got a new GUID, so its id changed |
| **Remaining** | Everything still present |

If an applied fix did **not** make its issue disappear, the banner says so.
The re-audit is the proof, not the fix code's own opinion.

### 5.4 The run folder of a fixed copy
```
data/<new-run-id>/
  original.ifc      the model it was fixed from (byte copy, untouched)
  model.ifc         the fixed model
  changes.json      every fix: values, status, message; GUID changes; deletions
  report.* / issues.csv / model.db   the re-audit
```

A fixed copy can itself be fixed again; each round is a new run linked to its
parent.

---

## 6. Asking questions

```text
  Question
     │
     ▼
  Prompt = real database schema + notes + worked examples
     │
     ▼
  Language model ──► { "sql": "SELECT …", "answer": "There are {errors} errors…" }
     │
     ▼
  Guard: one statement, SELECT/WITH only, no PRAGMA/ATTACH/writes?
     │                         │
     no                        yes
     ▼                         ▼
  Refused, shown          Run on SQLite (read-only connection)
  as an error                  │
                               ▼
                          Rows ──► fill {placeholders} from the rows
                               │   (template dropped if it has its own digits)
                               ▼
                          Answer sentence + table + the SQL used
```

1. The model is given the **real database schema** (including the `audit_*`
   tables), notes on how the tables fit together, and worked examples.
2. It returns one SQL query and a one-sentence **template** such as
   *"There are {errors} errors and {warnings} warnings."*
3. The SQL is checked: a single statement, starting with SELECT/WITH, and no
   PRAGMA, ATTACH, INSERT, UPDATE, DELETE or DDL. It runs over a
   **read-only** connection.
4. The template's `{placeholders}` are filled from the result rows. If the
   template contains any digit of its own, or names a column the query didn't
   return, it is dropped and only the table is shown.
5. The SQL is always displayed under the answer.

**Result: the AI chooses the wording, but every number comes from the
database.** Without a key the box says so and points to the SQL console. It
never guesses.

---

## 7. Where things are stored

```
ifc-audit/
  data/<run-id>/        one folder per run (kept on disk)
    model.ifc           the audited model
    requirements.ids    uploaded IDS, if any
    model.db            SQLite database
    report.html/.json/.xlsx, issues.csv
    elements.json       cache for the 3D viewer
    original.ifc, changes.json   (fixed copies only)
  reports/              CLI output
  examples/             sample models and the example IDS
```

The list of runs on the home page is held in memory and clears when the
server stops. The folders under `data/` remain until you delete them.

---

## 8. Web API

Everything the browser does goes through these endpoints (all on
`http://127.0.0.1:8000`):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Rules, limits, whether the Ask box is enabled |
| POST | `/api/upload` | Upload a model (+ options, optional IDS); starts a run |
| GET | `/api/jobs` | List runs |
| GET | `/api/jobs/{id}` | Progress of a run |
| GET | `/api/jobs/{id}/result` | Full result of a finished run |
| DELETE | `/api/jobs/{id}` | Delete a run and its folder |
| GET | `/api/jobs/{id}/download/{kind}` | `html`, `xlsx`, `csv`, `json`, `db`, `ifc`, `original`, `changes` |
| GET | `/api/jobs/{id}/report` | The HTML report inline |
| GET | `/api/jobs/{id}/elements` | STEP id → GUID/class/name/storey (3D viewer) |
| GET | `/api/jobs/{id}/fixes` | Fix proposals |
| POST | `/api/jobs/{id}/fixes/apply` | Apply approved fixes to a new copy |
| GET | `/api/jobs/{id}/schema` | Database tables and row counts |
| POST | `/api/jobs/{id}/sql` | Run a read-only SQL query |
| POST | `/api/jobs/{id}/sql.csv` | Same, as a CSV download |
| POST | `/api/jobs/{id}/ask` | Question → SQL → answer |

---

## 9. Design rules that keep results trustworthy

1. **Everything is an Issue** with a **stable id**, so runs can be compared
   exactly.
2. **Units are never assumed.** Dimensions are converted with the model's own
   unit scale.
3. **The AI never produces a number.** It writes SQL and wording; SQLite
   produces the figures, and the SQL is shown.
4. **SQL is read-only**, checked before it runs and executed on a read-only
   connection.
5. **The uploaded file is never modified.** Fixes go to a copy, with the
   original and a change log alongside.
6. **Values are never invented.** Suggestions must be derivable from the model
   and explained; safety and design values always come from a person.
7. **Fixes are verified by re-auditing**, not assumed to have worked.
8. **One broken check never kills an audit.** It becomes an issue.

---

## 10. Limits

- **Local, single-user.** No login; the server listens only on your own
  machine. A shared or hosted service would need authentication, a job queue
  and file storage.
- **3D needs internet** (the engine is loaded from jsDelivr).
- **Fixes don't flow back to Revit.** Re-exporting from the authoring tool
  overwrites them; make the same change at the source. BCF export (to send
  issues back to Revit/Navisworks) isn't built yet.
- **Not built yet:** clash detection, BCF export, comparing two separate
  uploads of the same model, combining several discipline models.
