"""Self-contained HTML report.

No CDN, no build step, no network — one file you can email, archive or open
on a site office machine with no internet. All filtering happens client-side
over a JSON blob embedded in the page.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any, Optional

from ..issues import AuditResult

# Severity uses the reserved STATUS palette, never the categorical series
# palette — severity is a state, not an identity. warning is sub-3:1 on the
# light surface by design, so every swatch is paired with its text label.
TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IFC Audit — __MODEL__</title>
<style>
  :root {
    color-scheme: light;
    --surface:      #fcfcfb;
    --plane:        #f9f9f7;
    --ink:          #0b0b0b;
    --ink-2:        #52514e;
    --muted:        #898781;
    --grid:         #e1e0d9;
    --border:       rgba(11,11,11,0.10);
    --sev-error:    #d03b3b;
    --sev-warning:  #fab219;
    --sev-info:     #898781;
    --radius: 10px;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --surface: #1a1a19;
      --plane:   #0d0d0d;
      --ink:     #ffffff;
      --ink-2:   #c3c2b7;
      --muted:   #898781;
      --grid:    #2c2c2a;
      --border:  rgba(255,255,255,0.10);
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --surface: #1a1a19;
    --plane:   #0d0d0d;
    --ink:     #ffffff;
    --ink-2:   #c3c2b7;
    --muted:   #898781;
    --grid:    #2c2c2a;
    --border:  rgba(255,255,255,0.10);
  }

  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--plane); color: var(--ink);
    font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 32px 16px 80px; }

  header h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
  header .sub { color: var(--ink-2); font-size: 13.5px; }
  .meta { display: flex; flex-wrap: wrap; gap: 8px 20px; margin-top: 14px;
          font-size: 13px; color: var(--ink-2); }
  .meta b { color: var(--ink); font-weight: 600; }

  .card { background: var(--surface); border: 1px solid var(--border);
          border-radius: var(--radius); padding: 18px 20px; margin-top: 20px; }
  .card h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .07em;
             color: var(--muted); margin: 0 0 14px; font-weight: 600; }

  /* KPI row — hero figures, no plot, so no hover layer needed */
  .kpis { display: grid; gap: 12px;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
  .kpi { background: var(--surface); border: 1px solid var(--border);
         border-radius: var(--radius); padding: 16px 18px; }
  .kpi .v { font-size: 30px; font-weight: 650; letter-spacing: -0.02em;
            line-height: 1.1; }
  .kpi .k { font-size: 12.5px; color: var(--ink-2); margin-top: 4px;
            display: flex; align-items: center; gap: 7px; }
  .dot { width: 9px; height: 9px; border-radius: 2px; flex: none; }

  /* Severity distribution — one stacked bar, 2px surface gap between fills */
  .bar { display: flex; height: 16px; border-radius: 4px; overflow: hidden;
         background: var(--grid); gap: 2px; }
  .bar > span { display: block; min-width: 2px; }
  .bar > span:first-child { border-radius: 4px 0 0 4px; }
  .bar > span:last-child  { border-radius: 0 4px 4px 0; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 12px;
            font-size: 13px; color: var(--ink-2); }
  .legend span.i { display: inline-flex; align-items: center; gap: 7px; }
  .legend b { color: var(--ink); font-variant-numeric: tabular-nums; }

  /* filters, one row above the content */
  .filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
             margin-top: 22px; }
  .filters input, .filters select {
    font: inherit; font-size: 13.5px; padding: 7px 10px; color: var(--ink);
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; }
  .filters input { flex: 1 1 240px; min-width: 180px; }
  .count { color: var(--muted); font-size: 13px; margin-left: auto; }

  .group { background: var(--surface); border: 1px solid var(--border);
           border-radius: var(--radius); margin-top: 12px; overflow: hidden; }
  .group > summary { cursor: pointer; padding: 13px 18px; display: flex;
                     align-items: center; gap: 11px; list-style: none; }
  .group > summary::-webkit-details-marker { display: none; }
  .group > summary::before { content: "▸"; color: var(--muted); font-size: 11px;
                             transition: transform .12s; }
  .group[open] > summary::before { transform: rotate(90deg); }
  .group .rid { font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
                font-size: 12px; color: var(--ink-2); }
  .group .gt { font-weight: 550; }
  .group .n { margin-left: auto; font-size: 12.5px; color: var(--muted);
              font-variant-numeric: tabular-nums; }
  .pill { font-size: 11px; font-weight: 600; letter-spacing: .04em;
          text-transform: uppercase; padding: 2px 8px; border-radius: 999px;
          display: inline-flex; align-items: center; gap: 5px;
          border: 1px solid var(--border); }

  table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
  thead th { text-align: left; font-weight: 600; font-size: 11.5px;
             text-transform: uppercase; letter-spacing: .06em; color: var(--muted);
             padding: 9px 18px; border-top: 1px solid var(--grid); }
  tbody td { padding: 9px 18px; border-top: 1px solid var(--grid);
             vertical-align: top; color: var(--ink-2); }
  tbody td.el { color: var(--ink); }
  code { font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
         font-size: 12px; color: var(--muted); }
  .desc { padding: 2px 18px 14px; color: var(--ink-2); font-size: 13.5px;
          max-width: 78ch; }

  .ids td, .ids th { padding: 8px 12px; }
  .ids tbody td { border-top: 1px solid var(--grid); }
  .ok  { color: #0ca30c; font-weight: 600; }
  .bad { color: var(--sev-error); font-weight: 600; }

  .empty { padding: 40px; text-align: center; color: var(--muted); }
  footer { margin-top: 36px; font-size: 12.5px; color: var(--muted); }
  .toggle { position: fixed; top: 14px; right: 14px; font: inherit;
            font-size: 12.5px; padding: 6px 12px; cursor: pointer;
            background: var(--surface); color: var(--ink-2);
            border: 1px solid var(--border); border-radius: 999px; }
</style>
</head>
<body>
<button class="toggle" id="themeBtn" type="button">Theme</button>
<div class="wrap">

<header>
  <h1>IFC Model Audit</h1>
  <div class="sub">__PROJECT__</div>
  <div class="meta">
    <span><b>File</b> __MODEL__</span>
    <span><b>Schema</b> __SCHEMA__</span>
    <span><b>Length unit</b> __UNIT__</span>
    <span><b>Elements</b> __ELEMENTS__</span>
    <span><b>Storeys</b> __STOREYS__</span>
    <span><b>Run</b> __TIMESTAMP__ (__DURATION__s)</span>
  </div>
</header>

<div class="kpis" style="margin-top:22px">__KPIS__</div>

<div class="card">
  <h2>Severity distribution</h2>
  <div class="bar" role="img" aria-label="__BAR_ALT__">__BAR__</div>
  <div class="legend">__LEGEND__</div>
</div>

__IDS_BLOCK__

<div class="filters">
  <input id="q" type="search" placeholder="Search rule, element, GUID or text…">
  <select id="sev">
    <option value="">All severities</option>
    <option value="error">Errors only</option>
    <option value="warning">Warnings only</option>
    <option value="info">Info only</option>
  </select>
  <select id="cat">__CAT_OPTIONS__</select>
  <span class="count" id="count"></span>
</div>

<div id="groups"></div>

<footer>
  Generated by ifcaudit __VERSION__ · rules run: __RULES__ ·
  Every figure on this page is computed by the rule engine.
</footer>
</div>

<script type="application/json" id="data">__DATA__</script>
<script>
(function () {
  var DATA = JSON.parse(document.getElementById("data").textContent);
  var SEV_COLOR = { error: "var(--sev-error)", warning: "var(--sev-warning)",
                    info: "var(--sev-info)" };
  var groupsEl = document.getElementById("groups");
  var countEl  = document.getElementById("count");

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function matches(issue, q, sev, cat) {
    if (sev && issue.severity !== sev) return false;
    if (cat && issue.category !== cat) return false;
    if (!q) return true;
    var hay = [issue.rule_id, issue.title, issue.description,
               (issue.elements || []).map(function (e) {
                 return [e.guid, e.name, e.ifc_class, e.storey].join(" ");
               }).join(" ")].join(" ").toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function render() {
    var q   = document.getElementById("q").value.trim().toLowerCase();
    var sev = document.getElementById("sev").value;
    var cat = document.getElementById("cat").value;

    var shown = DATA.issues.filter(function (i) { return matches(i, q, sev, cat); });
    countEl.textContent = shown.length + " of " + DATA.issues.length + " issues";

    if (!shown.length) {
      groupsEl.innerHTML = '<div class="group"><div class="empty">' +
        (DATA.issues.length ? "No issues match these filters."
                            : "No issues found. The model passed every check.") +
        "</div></div>";
      return;
    }

    var byRule = {};
    shown.forEach(function (i) { (byRule[i.rule_id] = byRule[i.rule_id] || []).push(i); });

    var order = Object.keys(byRule).sort(function (a, b) {
      var ra = { error: 0, warning: 1, info: 2 }[byRule[a][0].severity];
      var rb = { error: 0, warning: 1, info: 2 }[byRule[b][0].severity];
      return ra - rb || byRule[b].length - byRule[a].length || a.localeCompare(b);
    });

    groupsEl.innerHTML = order.map(function (rid) {
      var list = byRule[rid];
      var s = list[0].severity;
      var rows = list.map(function (i) {
        var els = (i.elements || []);
        var who = els.length
          ? els.map(function (e) {
              return '<div class="el">' + esc(e.ifc_class || "") +
                (e.name ? " · " + esc(e.name) : "") +
                (e.guid ? ' <code>' + esc(e.guid) + "</code>" : "") + "</div>";
            }).join("")
          : '<span style="color:var(--muted)">model-wide</span>';
        // Keys already shown in the group header would just repeat on every row.
        var HIDE = { key: 1, traceback: 1, specification: 1, requirement: 1,
                     reason: 1 };
        var ev = Object.keys(i.evidence || {})
          .filter(function (k) { return !HIDE[k] && i.evidence[k] !== null; })
          .map(function (k) { return esc(k) + ": " + esc(JSON.stringify(i.evidence[k])); })
          .join("<br>");
        var finding = (i.evidence && i.evidence.reason) || i.title;
        return "<tr><td>" + who + "</td><td>" + esc(i.elements[0] &&
               i.elements[0].storey || "—") + "</td><td>" + esc(finding) +
               "</td><td><code>" + (ev || "—") + "</code></td></tr>";
      }).join("");

      return '<details class="group" ' + (s === "error" ? "open" : "") + ">" +
        "<summary>" +
          '<span class="pill" style="color:' + SEV_COLOR[s] + '">' +
            '<span class="dot" style="background:' + SEV_COLOR[s] + '"></span>' +
            esc(s) + "</span>" +
          '<span class="gt">' + esc(list[0].title.split(" — ")[0]) + "</span>" +
          '<span class="rid">' + esc(rid) + "</span>" +
          '<span class="n">' + list.length + "</span>" +
        "</summary>" +
        '<div class="desc">' + esc(list[0].description) + "</div>" +
        "<table><thead><tr><th>Element</th><th>Storey</th><th>Finding</th>" +
        "<th>Evidence</th></tr></thead><tbody>" + rows + "</tbody></table>" +
        "</details>";
    }).join("");
  }

  ["q", "sev", "cat"].forEach(function (id) {
    var el = document.getElementById(id);
    el.addEventListener("input", render);
    el.addEventListener("change", render);
  });

  document.getElementById("themeBtn").addEventListener("click", function () {
    var root = document.documentElement;
    var dark = getComputedStyle(root).getPropertyValue("--surface").trim() === "#1a1a19";
    root.setAttribute("data-theme", dark ? "light" : "dark");
  });

  render();
})();
</script>
</body>
</html>
"""


def _kpi(value: Any, label: str, color: Optional[str] = None) -> str:
    dot = f'<span class="dot" style="background:{color}"></span>' if color else ""
    return (f'<div class="kpi"><div class="v">{value}</div>'
            f'<div class="k">{dot}{html.escape(label)}</div></div>')


def _ids_block(summary: Optional[dict[str, Any]]) -> str:
    if not summary:
        return ""
    rows = []
    for s in summary["specifications"]:
        state = ('<span class="ok">PASS</span>' if s["status"]
                 else '<span class="bad">FAIL</span>')
        rows.append(
            f"<tr><td>{state}</td><td>{html.escape(s['name'])}</td>"
            f"<td>{s['applicable']}</td><td>{s['passed']}</td>"
            f"<td>{s['failed']}</td></tr>"
        )
    return (
        '<div class="card"><h2>IDS — ' + html.escape(str(summary["title"])) + "</h2>"
        '<table class="ids"><thead><tr><th>Result</th><th>Specification</th>'
        "<th>Applicable</th><th>Passed</th><th>Failed</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def write(result: AuditResult, path: str,
          ids_summary: Optional[dict[str, Any]] = None) -> str:
    counts = result.counts()
    total = sum(counts.values())
    colors = {"error": "var(--sev-error)", "warning": "var(--sev-warning)",
              "info": "var(--sev-info)"}

    kpis = "".join([
        _kpi(total, "Total issues"),
        _kpi(counts["error"], "Errors", colors["error"]),
        _kpi(counts["warning"], "Warnings", colors["warning"]),
        _kpi(counts["info"], "Info", colors["info"]),
        _kpi(result.stats.get("elements", 0), "Elements checked"),
    ])

    if total:
        bar = "".join(
            f'<span title="{k}: {counts[k]}" style="flex:{counts[k]};'
            f'background:{colors[k]}"></span>'
            for k in ("error", "warning", "info") if counts[k]
        )
    else:
        bar = '<span style="flex:1;background:#0ca30c"></span>'

    legend = "".join(
        f'<span class="i"><span class="dot" style="background:{colors[k]}"></span>'
        f"{k.capitalize()} <b>{counts[k]}</b></span>"
        for k in ("error", "warning", "info")
    )
    bar_alt = ", ".join(f"{counts[k]} {k}" for k in ("error", "warning", "info"))

    cats = sorted(result.by_category().keys())
    cat_options = '<option value="">All categories</option>' + "".join(
        f'<option value="{c}">{c.capitalize()}</option>' for c in cats
    )

    payload = json.dumps(result.to_dict(), ensure_ascii=False, default=str)

    from .. import __version__

    replacements = {
        "__MODEL__": html.escape(result.model_path.split("/")[-1].split("\\")[-1]),
        "__PROJECT__": html.escape(result.project_name or "(unnamed project)"),
        "__SCHEMA__": html.escape(result.schema),
        "__UNIT__": html.escape(str(result.units.get("length") or "unknown")),
        "__ELEMENTS__": str(result.stats.get("elements", 0)),
        "__STOREYS__": str(result.stats.get("storeys", 0)),
        "__TIMESTAMP__": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "__DURATION__": f"{result.duration_s:.2f}",
        "__KPIS__": kpis,
        "__BAR__": bar,
        "__BAR_ALT__": html.escape(bar_alt),
        "__LEGEND__": legend,
        "__IDS_BLOCK__": _ids_block(ids_summary),
        "__CAT_OPTIONS__": cat_options,
        "__RULES__": str(len(result.rules_run)),
        "__VERSION__": __version__,
        "__DATA__": payload,
    }

    out = TEMPLATE
    for key, value in replacements.items():
        out = out.replace(key, value)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    return path
