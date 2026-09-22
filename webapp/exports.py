"""Spreadsheet and CSV exports.

IFCflow's export node is one of its genuinely useful ideas: the people who
receive an audit live in Excel, not in a web dashboard. Three sheets —
summary, issues, IDS — is what makes a report actionable in a coordination
meeting.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F2933")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
SEVERITY_FILL = {
    "error": PatternFill("solid", fgColor="FADBD8"),
    "warning": PatternFill("solid", fgColor="FDEBD0"),
    "info": PatternFill("solid", fgColor="EAEDED"),
}


def _write_header(sheet, headers: list[str]) -> None:
    sheet.append(headers)
    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"


def _autosize(sheet, widths: list[int]) -> None:
    for i, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(i)].width = width


def workbook(result: dict[str, Any], ids_summary: Optional[dict[str, Any]],
             path: str) -> str:
    wb = Workbook()

    # --- Summary ---------------------------------------------------------
    summary = wb.active
    summary.title = "Summary"
    counts = result.get("counts", {})
    stats = result.get("stats", {})
    rows = [
        ("Model", result.get("model_path", "")),
        ("Project", result.get("project_name") or ""),
        ("IFC schema", result.get("schema", "")),
        ("Length unit", str(result.get("units", {}).get("length", ""))),
        ("Elements", stats.get("elements", 0)),
        ("Storeys", stats.get("storeys", 0)),
        ("Spaces", stats.get("spaces", 0)),
        ("Rules run", len(result.get("rules_run", []))),
        ("", ""),
        ("Errors", counts.get("error", 0)),
        ("Warnings", counts.get("warning", 0)),
        ("Info", counts.get("info", 0)),
        ("Total issues", sum(counts.values()) if counts else 0),
    ]
    _write_header(summary, ["Metric", "Value"])
    for label, value in rows:
        summary.append([label, value])
    bold = Font(bold=True)
    for cell in summary["A"]:
        if cell.row > 1:
            cell.font = bold
    _autosize(summary, [26, 70])

    # --- Issues ----------------------------------------------------------
    issues = wb.create_sheet("Issues")
    _write_header(issues, ["Severity", "Category", "Rule", "Title", "Element",
                           "IFC class", "GlobalId", "Storey", "Description"])
    for issue in result.get("issues", []):
        elements = issue.get("elements") or [{}]
        for element in elements:
            issues.append([
                issue.get("severity", ""),
                issue.get("category", ""),
                issue.get("rule_id", ""),
                issue.get("title", ""),
                element.get("name") or "",
                element.get("ifc_class") or "",
                element.get("guid") or "",
                element.get("storey") or "",
                issue.get("description", ""),
            ])
            fill = SEVERITY_FILL.get(issue.get("severity", ""))
            if fill:
                issues.cell(row=issues.max_row, column=1).fill = fill
    issues.auto_filter.ref = f"A1:I{max(issues.max_row, 1)}"
    _autosize(issues, [11, 12, 30, 44, 24, 20, 24, 16, 80])

    # --- IDS -------------------------------------------------------------
    if ids_summary:
        sheet = wb.create_sheet("IDS")
        _write_header(sheet, ["Result", "Specification", "Applicable",
                              "Passed", "Failed"])
        for spec in ids_summary.get("specifications", []):
            sheet.append([
                "PASS" if spec.get("status") else "FAIL",
                spec.get("name", ""),
                spec.get("applicable", 0),
                spec.get("passed", 0),
                spec.get("failed", 0),
            ])
            if not spec.get("status"):
                sheet.cell(row=sheet.max_row, column=1).fill = SEVERITY_FILL["error"]
        _autosize(sheet, [10, 52, 12, 10, 10])

    # --- Element breakdown ----------------------------------------------
    breakdown = wb.create_sheet("Elements")
    _write_header(breakdown, ["IFC class", "Count"])
    for ifc_class, count in (stats.get("by_class") or {}).items():
        breakdown.append([ifc_class, count])
    _autosize(breakdown, [34, 10])

    wb.save(path)
    return path


def issues_csv(result: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["severity", "category", "rule_id", "title", "element_name",
                     "ifc_class", "global_id", "storey", "description"])
    for issue in result.get("issues", []):
        for element in (issue.get("elements") or [{}]):
            writer.writerow([
                issue.get("severity", ""), issue.get("category", ""),
                issue.get("rule_id", ""), issue.get("title", ""),
                element.get("name") or "", element.get("ifc_class") or "",
                element.get("guid") or "", element.get("storey") or "",
                issue.get("description", ""),
            ])
    return buffer.getvalue()


def rows_csv(columns: list[str], rows: list[list[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()
