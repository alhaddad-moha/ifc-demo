"""End-to-end browser test of the whole web app.

Drives a real browser through the actual flow: drop a file, wait for the
pipeline, read the dashboard, filter issues, run SQL, check the downloads.
Nothing is mocked — the numbers asserted below come from the same pipeline
a user triggers.

    pip install playwright && playwright install chromium
    python serve.py --no-open --port 8112     # in one terminal
    python tests/test_e2e.py                  # in another

Pass BASE_URL to point it at a different host/port.
"""

from __future__ import annotations

import os
import sys
import pathlib

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8112")
ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "examples" / "sample_model.ifc"

failures: list[str] = []
checks = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


def main() -> int:
    from playwright.sync_api import sync_playwright

    if not SAMPLE.is_file():
        print(f"Sample model missing: {SAMPLE}\nRun: python tools/make_sample.py "
              f"examples/sample_model.ifc")
        return 1

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or None
        )
        page = browser.new_page(viewport={"width": 1400, "height": 1000})

        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        print("\n1. Load the page")
        page.goto(BASE, wait_until="networkidle")
        check("page title", "IFC Audit" in page.title())
        check("dropzone visible", page.is_visible("#drop"))
        check("rule count chip", "rules" in page.text_content("#nlqChip"))

        print("\n2. Upload the model")
        page.set_input_files("#fileInput", str(SAMPLE))
        page.wait_for_selector("#viewProgress:not([hidden])", timeout=10_000)
        check("progress view shown", page.is_visible("#steps"))

        print("\n3. Wait for the pipeline")
        page.wait_for_selector("#viewResult:not([hidden])", timeout=180_000)
        check("results view shown", page.is_visible("#kpis"))

        kpis = page.eval_on_selector_all(
            "#kpis .kpi",
            "els => els.map(e => [e.querySelector('.k').textContent.trim(),"
            " e.querySelector('.v').textContent.trim()])")
        values = {k: v for k, v in kpis}
        print("     KPIs:", values)
        check("errors detected", int(values.get("Errors", 0)) > 0,
              f"got {values.get('Errors')}")
        check("warnings detected", int(values.get("Warnings", 0)) > 0)
        check("elements counted", int(values.get("Elements checked", 0)) == 29,
              f"got {values.get('Elements checked')}")

        bar = page.eval_on_selector_all("#sevBar > span", "e => e.length")
        check("severity bar has segments", bar >= 2, f"got {bar}")

        ids_rows = page.eval_on_selector_all("#idsRows tr", "e => e.length")
        check("IDS table populated", ids_rows == 4, f"got {ids_rows}")
        fails = page.eval_on_selector_all(
            "#idsRows tr td.bad", "e => e.length")
        check("IDS reports failures", fails == 3, f"got {fails}")

        classes = page.eval_on_selector_all("#classRows tr", "e => e.length")
        check("element breakdown populated", classes > 5, f"got {classes}")

        print("\n4. Issues tab")
        page.click(".tab[data-pane='paneIssues']")
        page.wait_for_selector("#groups .group", timeout=10_000)
        total_text = page.text_content("#issueCount")
        print("     ", total_text)
        check("issue count rendered", "issues" in total_text)

        groups = page.eval_on_selector_all("#groups .group", "e => e.length")
        check("issues grouped by rule", groups > 5, f"got {groups}")

        total_issues = int(total_text.split(" ")[0])
        page.fill("#q", "WAL-CLONE")
        page.wait_for_timeout(300)
        filtered = page.text_content("#issueCount")
        shown = int(filtered.split(" ")[0])
        print("      filtered:", filtered)
        check("free-text filter narrows the list",
              0 < shown < total_issues, f"{shown} of {total_issues}")

        page.fill("#q", "")
        page.select_option("#sev", "error")
        page.wait_for_timeout(300)
        errs = int(page.text_content("#issueCount").split(" ")[0])
        check("severity filter works", errs == int(values["Errors"]),
              f"{errs} vs {values['Errors']}")
        page.select_option("#sev", "")

        print("\n5. Data tab — SQL console")
        page.click(".tab[data-pane='paneData']")
        page.wait_for_selector("#sqlBox", timeout=5_000)
        page.click("#runSql")
        page.wait_for_selector("#sqlOut table", timeout=15_000)
        rows = page.eval_on_selector_all("#sqlOut tbody tr", "e => e.length")
        check("SQL console returns rows", rows > 5, f"got {rows}")
        check("row count shown", "row(s)" in page.text_content("#sqlCount"))

        examples = page.eval_on_selector_all("#examples button", "e => e.length")
        check("example queries offered", examples == 5, f"got {examples}")
        page.click("#examples button:nth-child(2)")   # doors + fire rating
        page.wait_for_timeout(1200)
        cols = page.eval_on_selector_all(
            "#sqlOut thead th", "e => e.map(x => x.textContent)")
        check("example query runs", "FireRating" in cols, f"got {cols}")

        print("\n6. SQL safety guard")
        page.fill("#sqlBox", "DROP TABLE IfcWall")
        page.click("#runSql")
        page.wait_for_selector("#sqlOut .note.err", timeout=10_000)
        guard = page.text_content("#sqlOut .note.err")
        check("destructive SQL refused", "SELECT" in guard, guard)

        print("\n7. Ask (no model configured)")
        page.fill("#question", "how many doors have no fire rating?")
        page.click("#askBtn")
        # "Thinking…" is also a .note, so wait for it to be replaced rather
        # than matching the placeholder.
        page.wait_for_function(
            "() => { const n = document.getElementById('askNote');"
            " return n && n.textContent && !n.textContent.includes('Thinking'); }",
            timeout=30_000)
        note = page.text_content("#askNote")
        configured = os.environ.get("OPENAI_API_KEY") or os.environ.get(
            "OPENROUTER_API_KEY")
        if configured:
            check("answers are backed by a visible SQL query",
                  "Ran this query" in note, note[:90])
        else:
            check("degrades honestly without an API key",
                  "No language model is configured" in note, note[:90])

        print("\n8. Tables listing")
        tables = page.eval_on_selector_all("#tableRows tr", "e => e.length")
        check("SQLite tables listed", tables > 20, f"got {tables}")

        print("\n9. Downloads tab")
        page.click(".tab[data-pane='paneFiles']")
        page.wait_for_selector("#downloads a", timeout=5_000)
        links = page.eval_on_selector_all("#downloads a", "e => e.length")
        check("all six downloads offered", links == 6, f"got {links}")

        with page.expect_download(timeout=30_000) as info:
            page.click("#downloads a[href$='/xlsx']")
        download = info.value
        path = download.path()
        size = os.path.getsize(path) if path else 0
        check("xlsx downloads and is non-empty", size > 5000, f"{size} bytes")

        print("\n10. Return home and see the run listed")
        page.click("#homeBtn")
        page.wait_for_selector("#recentList .job-row", timeout=10_000)
        recent = page.eval_on_selector_all("#recentList .job-row", "e => e.length")
        check("recent runs listed", recent >= 1, f"got {recent}")

        page.screenshot(path="/tmp/e2e_upload.png")
        page.click("#recentList .job-row")
        page.wait_for_selector("#viewResult:not([hidden])", timeout=20_000)
        check("can reopen a finished run", page.is_visible("#kpis"))
        page.screenshot(path="/tmp/e2e_results.png", full_page=False)

        real_errors = [e for e in console_errors
                       if "favicon" not in e.lower()]
        check("no uncaught JS errors", not real_errors, str(real_errors[:2]))

        browser.close()

    print("\n" + "=" * 58)
    if failures:
        print(f" {len(failures)} of {checks} checks FAILED")
        for f in failures:
            print(f"   - {f}")
        return 1
    print(f" All {checks} checks passed")
    print("=" * 58)
    return 0


if __name__ == "__main__":
    sys.exit(main())
