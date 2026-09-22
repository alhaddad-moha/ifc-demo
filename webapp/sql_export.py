"""IFC → SQLite.

The single most valuable idea borrowed from IFCflow, but moved to where it
belongs: the server. IFCflow runs this in the browser under Pyodide/WASM,
which caps out around 2-4 GB and pushes the whole file through the client.
Here it is plain CPython calling the same official ifcpatch Ifc2Sql recipe —
fewer moving parts, no memory ceiling beyond the machine's.

Once a model is a relational database, two things become easy that are hard
otherwise: ad-hoc querying, and letting a language model answer questions by
writing SQL instead of generating ifcopenshell code nobody can audit.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Optional

# A query is allowed only if it is a single read. Everything else is refused
# before it reaches sqlite, and the connection is opened read-only as well.
_FORBIDDEN = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|"
    r"VACUUM|REINDEX|TRIGGER|LOAD_EXTENSION)\b",
    re.IGNORECASE,
)

MAX_ROWS = 500


def build(ifc_path: str, db_path: str, include_geometry: bool = False) -> dict[str, Any]:
    """Convert an IFC file into a queryable SQLite database."""
    import ifcopenshell
    import ifcpatch

    if os.path.exists(db_path):
        os.remove(db_path)

    model = ifcopenshell.open(ifc_path)
    ifcpatch.execute({
        "input": ifc_path,
        "file": model,
        "recipe": "Ifc2Sql",
        "arguments": [
            "SQLite",        # sql_type
            "localhost",     # host   (unused for SQLite)
            "root",          # username
            "pass",          # password
            db_path,         # database — the output path
            False,           # full_schema: only emit classes the model uses
            False,           # is_strict
            False,           # should_expand
            True,            # should_get_inverses
            True,            # should_get_psets
            include_geometry,
            not include_geometry,  # should_skip_geometry_data
        ],
    })

    return {"path": db_path, "size": os.path.getsize(db_path), **describe(db_path)}


def describe(db_path: str) -> dict[str, Any]:
    """Table names and row counts — this is what the UI shows and what the
    language model is given as schema context."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [r[0] for r in cur.fetchall()]
        counts: dict[str, int] = {}
        for table in tables:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                counts[table] = cur.fetchone()[0]
            except sqlite3.Error:
                counts[table] = -1
        return {"tables": tables, "row_counts": counts}
    finally:
        con.close()


def schema_text(db_path: str, max_tables: int = 60) -> str:
    """A compact CREATE-TABLE dump, used as grounding context for text-to-SQL.

    The model is shown the real schema, so it cannot invent column names —
    and anything it does invent fails loudly at execution instead of
    silently returning a plausible wrong number.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL "
            "ORDER BY name LIMIT ?", (max_tables,)
        )
        return "\n".join(r[0] for r in cur.fetchall() if r[0])
    finally:
        con.close()


def is_safe(sql: str) -> tuple[bool, Optional[str]]:
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return False, "Empty query."
    if ";" in stripped:
        return False, "Only a single statement is allowed."
    if not re.match(r"^\s*(SELECT|WITH)\b", stripped, re.IGNORECASE):
        return False, "Only SELECT queries are allowed."
    found = _FORBIDDEN.search(stripped)
    if found:
        return False, f"'{found.group(0).upper()}' is not allowed."
    return True, None


def query(db_path: str, sql: str, limit: int = MAX_ROWS) -> dict[str, Any]:
    """Run one read-only SELECT and return columns + rows."""
    ok, reason = is_safe(sql)
    if not ok:
        return {"error": reason, "sql": sql}

    stripped = sql.strip().rstrip(";").strip()
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(stripped)
        rows = cur.fetchmany(limit)
        columns = [d[0] for d in cur.description] if cur.description else []
        truncated = len(rows) == limit and cur.fetchone() is not None
        return {
            "sql": stripped,
            "columns": columns,
            "rows": [[r[c] for c in columns] for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
    except sqlite3.Error as exc:
        return {"error": str(exc), "sql": stripped}
    finally:
        con.close()


# Worked examples. They double as the UI's starter queries and as few-shot
# grounding for the text-to-SQL prompt.
EXAMPLE_QUERIES: list[dict[str, str]] = [
    {"label": "Count elements by class",
     "sql": "SELECT ifc_class, COUNT(*) AS n FROM id_map\n"
            "GROUP BY ifc_class ORDER BY n DESC"},
    {"label": "Doors and their fire rating",
     "sql": "SELECT d.Name, p.value AS FireRating\n"
            "FROM IfcDoor d\n"
            "LEFT JOIN psets p ON p.ifc_id = d.ifc_id AND p.name = 'FireRating'\n"
            "ORDER BY d.Name"},
    {"label": "Walls missing IsExternal",
     "sql": "SELECT w.GlobalId, w.Name FROM IfcWall w\n"
            "WHERE NOT EXISTS (\n"
            "  SELECT 1 FROM psets p\n"
            "  WHERE p.ifc_id = w.ifc_id AND p.name = 'IsExternal')"},
    {"label": "Storeys by elevation",
     "sql": "SELECT GlobalId, Name, Elevation FROM IfcBuildingStorey\n"
            "ORDER BY Elevation"},
    {"label": "Every property in use",
     "sql": "SELECT pset_name, name, COUNT(*) AS n FROM psets\n"
            "GROUP BY pset_name, name ORDER BY n DESC"},
]

# The schema is small and regular, so a handful of notes is enough to keep a
# language model on the rails. Passed with the CREATE TABLE dump.
SCHEMA_NOTES = """\
Notes on this database:
- One table per IFC class actually present, named exactly as the class
  (IfcWall, IfcDoor, IfcBuildingStorey, ...). Columns mirror the IFC
  attributes, plus `ifc_id` (the STEP id) and `inverses`.
- `id_map(ifc_id, ifc_class)` maps every entity id to its class. Use it for
  counts across all classes.
- `psets(ifc_id, pset_name, name, value)` holds every property set value, one
  row per property. `value` is stored as TEXT — booleans are '0' / '1'.
- Join elements to properties on `psets.ifc_id = <Table>.ifc_id`.
- `metadata(preprocessor, schema, mvd)` describes the source file.
"""
