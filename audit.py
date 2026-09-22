#!/usr/bin/env python
"""ifc-demo — audit an IFC model and produce a report.

    python audit.py examples/sample_model.ifc
    python audit.py model.ifc --ids requirements.ids --out reports/
    python audit.py model.ifc --schema-check --fail-on error

Exit code is 1 when issues at or above --fail-on are found, so this drops
straight into a CI pipeline or a pre-upload gate.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

import ifcaudit
from ifcaudit.report import console_report, html_report, json_report
from ifcaudit.rules.ids_runner import ids_summary, run_ids
from ifcaudit.rules.schema_check import run_schema_check


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="audit.py",
        description="Audit an IFC model for data-integrity and information "
                    "requirement issues.",
    )
    p.add_argument("model", help="path to the .ifc file")
    p.add_argument("--ids", help="path to an .ids file of information requirements")
    p.add_argument("--out", default="reports",
                   help="output directory (default: reports)")
    p.add_argument("--include", nargs="*", metavar="RULE",
                   help="only run these rule ids or prefixes, e.g. INT. SPA.")
    p.add_argument("--exclude", nargs="*", metavar="RULE",
                   help="skip these rule ids or prefixes")
    p.add_argument("--schema-check", action="store_true",
                   help="also run full IFC schema validation (slower)")
    p.add_argument("--fail-on", choices=["error", "warning", "info", "never"],
                   default="never",
                   help="exit with code 1 if issues at this level or worse exist")
    p.add_argument("--list-rules", action="store_true",
                   help="print the registered rules and exit")
    p.add_argument("--no-open", action="store_true",
                   help="do not open the HTML report in a browser")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def list_rules() -> None:
    print(f"{len(ifcaudit.REGISTRY)} registered rules:\n")
    for rule in sorted(ifcaudit.REGISTRY.values(), key=lambda r: r.id):
        print(f"  {rule.id:<32} {rule.severity.value:<8} "
              f"{rule.category.value:<11} {rule.title}")
    print("\nPlus: IDS.<specification>  (when --ids is given)")
    print("      SCHEMA.INVALID        (when --schema-check is given)")


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.list_rules:
        list_rules()
        return 0

    print(f"Loading {args.model} …")
    ctx = ifcaudit.load(args.model)
    print(f"  {ctx.schema}, {len(ctx.elements)} elements, "
          f"{len(ctx.storeys)} storeys")

    extra = []
    if args.schema_check:
        print("Running schema validation …")
        extra.extend(run_schema_check(ctx))

    summary = None
    if args.ids:
        print(f"Applying IDS {args.ids} …")
        extra.extend(run_ids(ctx, args.ids))
        summary = ids_summary(args.ids, ctx)

    print("Running rules …")
    result = ifcaudit.run(ctx, include=args.include, exclude=args.exclude,
                          extra_issues=extra, verbose=args.verbose)

    console_report.write(result, ids_summary=summary)

    os.makedirs(args.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.model))[0]
    json_path = os.path.join(args.out, f"{stem}_audit.json")
    html_path = os.path.join(args.out, f"{stem}_audit.html")
    json_report.write(result, json_path, ids_summary=summary)
    html_report.write(result, html_path, ids_summary=summary)

    print(f"\n  JSON report : {os.path.abspath(json_path)}")
    print(f"  HTML report : {os.path.abspath(html_path)}")

    if not args.no_open:
        try:
            webbrowser.open("file://" + os.path.abspath(html_path))
        except Exception:
            pass

    if args.fail_on != "never":
        threshold = {"error": 0, "warning": 1, "info": 2}[args.fail_on]
        if any(i.severity.rank <= threshold for i in result.issues):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
