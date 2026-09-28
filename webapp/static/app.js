/* IFC Audit — front end. No framework, no build step. */

(function () {
  "use strict";

  var SEV = { error: "var(--sev-error)", warning: "var(--sev-warning)",
              info: "var(--sev-info)" };
  var state = { job: null, data: null, poll: null, ids: null, config: null,
                fixes: null, payload: null };

  var $ = function (id) { return document.getElementById(id); };
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function bytes(n) {
    if (!n) return "0 B";
    var u = ["B", "KB", "MB", "GB"], i = Math.floor(Math.log(n) / Math.log(1024));
    return (n / Math.pow(1024, i)).toFixed(i ? 1 : 0) + " " + u[i];
  }
  function show(view) {
    ["viewUpload", "viewProgress", "viewResult"].forEach(function (v) {
      $(v).hidden = v !== view;
    });
    $("homeBtn").hidden = view === "viewUpload";
  }
  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      if (!r.ok) return r.json().catch(function () { return {}; })
        .then(function (b) { throw new Error(b.detail || r.statusText); });
      return r.json();
    });
  }

  /* ---------------- theme ---------------- */
  $("themeBtn").addEventListener("click", function () {
    var root = document.documentElement;
    var dark = getComputedStyle(root).getPropertyValue("--surface").trim() === "#1a1a19";
    root.setAttribute("data-theme", dark ? "light" : "dark");
    try { localStorage.setItem("ifcaudit-theme", dark ? "light" : "dark"); } catch (e) {}
    if (v3d.viewer) v3d.viewer.refreshTheme();
  });
  try {
    var saved = localStorage.getItem("ifcaudit-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
  } catch (e) {}

  $("homeBtn").addEventListener("click", function () {
    if (state.poll) clearInterval(state.poll);
    show("viewUpload"); loadRecent();
  });

  /* ---------------- config ---------------- */
  api("/api/config").then(function (cfg) {
    state.config = cfg;
    $("limitTxt").textContent = ".ifc up to " + cfg.max_upload_mb + " MB";
    if (cfg.default_ids) $("idsName").textContent = cfg.default_ids;
    var chip = $("nlqChip");
    chip.hidden = false;
    chip.textContent = cfg.rules.length + " rules" +
      (cfg.nlq_available ? " · AI queries on" : "");
    renderExamples(cfg.examples || []);
  }).catch(function () {});

  /* ---------------- upload ---------------- */
  var drop = $("drop"), fileInput = $("fileInput");
  drop.addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () {
    if (fileInput.files[0]) upload(fileInput.files[0]);
  });
  ["dragenter", "dragover"].forEach(function (e) {
    drop.addEventListener(e, function (ev) {
      ev.preventDefault(); drop.classList.add("over");
    });
  });
  ["dragleave", "drop"].forEach(function (e) {
    drop.addEventListener(e, function (ev) {
      ev.preventDefault(); drop.classList.remove("over");
    });
  });
  drop.addEventListener("drop", function (ev) {
    var f = ev.dataTransfer.files[0];
    if (f) upload(f);
  });

  $("idsBtn").addEventListener("click", function (e) {
    e.stopPropagation(); $("idsInput").click();
  });
  $("idsInput").addEventListener("change", function () {
    var f = $("idsInput").files[0];
    if (f) { state.ids = f; $("idsName").textContent = f.name; }
  });

  function upload(file) {
    var fd = new FormData();
    fd.append("file", file);
    fd.append("schema_check", $("optSchema").checked ? "true" : "false");
    fd.append("build_db", $("optDb").checked ? "true" : "false");
    fd.append("use_ids", $("optIds").checked ? "true" : "false");
    if (state.ids) fd.append("ids_file", state.ids);

    $("progTitle").textContent = "Analysing " + file.name;
    $("progSub").textContent = bytes(file.size) +
      " — this runs in the background, the page updates as it goes.";
    $("logBox").textContent = "";
    show("viewProgress");

    api("/api/upload", { method: "POST", body: fd })
      .then(function (job) { state.job = job.id; track(job); })
      .catch(function (err) {
        $("progTitle").textContent = "Upload failed";
        $("progSub").textContent = err.message;
      });
  }

  /* ---------------- progress ---------------- */
  function renderSteps(job) {
    $("steps").innerHTML = job.steps.map(function (s, i) {
      var cls = i < job.step_index ? "done"
              : i === job.step_index ? (job.status === "failed" ? "" : "active") : "";
      var icon = i < job.step_index ? "✓"
               : i === job.step_index && job.status === "running"
                 ? '<span class="spin">◐</span>' : String(i + 1);
      return '<div class="step ' + cls + '"><span class="ic">' + icon +
             "</span>" + esc(s.label) + "</div>";
    }).join("");
    $("logBox").textContent = (job.log || []).join("\n");
    $("logBox").scrollTop = $("logBox").scrollHeight;
  }

  function track(job) {
    renderSteps(job);
    if (state.poll) clearInterval(state.poll);
    state.poll = setInterval(function () {
      api("/api/jobs/" + job.id).then(function (j) {
        renderSteps(j);
        if (j.status === "done") {
          clearInterval(state.poll);
          api("/api/jobs/" + j.id + "/result").then(showResult);
        } else if (j.status === "failed") {
          clearInterval(state.poll);
          $("progTitle").textContent = "Analysis failed";
          $("progSub").textContent = j.error || "Unknown error";
        }
      }).catch(function () { clearInterval(state.poll); });
    }, 700);
  }

  /* ---------------- recent ---------------- */
  function loadRecent() {
    api("/api/jobs").then(function (d) {
      var jobs = d.jobs || [];
      $("recent").hidden = jobs.length === 0;
      $("recentList").innerHTML = jobs.map(function (j) {
        var tone = j.status === "done" ? "var(--good)"
                 : j.status === "failed" ? "var(--sev-error)" : "var(--muted)";
        return '<div class="job-row" data-id="' + j.id + '">' +
          '<span class="dot" style="background:' + tone + '"></span>' +
          '<span class="nm">' + esc(j.filename) + "</span>" +
          (j.parent_id ? '<span class="chip">fixed copy</span>' : "") +
          '<span class="meta">' + bytes(j.size) + "</span>" +
          '<span class="spacer"></span>' +
          '<span class="meta">' + esc(j.status) + " · " + j.elapsed + "s</span>" +
          "</div>";
      }).join("");
      Array.prototype.forEach.call(document.querySelectorAll(".job-row"),
        function (row) {
          row.addEventListener("click", function () {
            var id = row.getAttribute("data-id");
            api("/api/jobs/" + id).then(function (j) {
              if (j.status === "done") {
                api("/api/jobs/" + id + "/result").then(showResult);
              } else { state.job = id; show("viewProgress"); track(j); }
            });
          });
        });
    }).catch(function () {});
  }
  loadRecent();
  show("viewUpload");

  /* ---------------- results ---------------- */
  function showResult(payload) {
    state.job = payload.id;
    state.data = payload.result;
    state.payload = payload;
    state.fixes = null;
    renderBanner(payload);
    var r = payload.result, counts = r.counts, stats = r.stats;

    $("resTitle").textContent = r.project_name || payload.filename;
    $("resMeta").innerHTML = [
      ["File", payload.filename], ["Schema", r.schema],
      ["Length unit", (r.units && r.units.length) || "unknown"],
      ["Elements", stats.elements], ["Storeys", stats.storeys],
      ["Rules", r.rules_run.length], ["Time", r.duration_s + "s"]
    ].map(function (p) {
      return "<span><b>" + esc(p[0]) + "</b> " + esc(p[1]) + "</span>";
    }).join("");

    var total = counts.error + counts.warning + counts.info;
    $("kpis").innerHTML = [
      [total, "Total issues", null],
      [counts.error, "Errors", SEV.error],
      [counts.warning, "Warnings", SEV.warning],
      [counts.info, "Info", SEV.info],
      [stats.elements, "Elements checked", null]
    ].map(function (k) {
      return '<div class="kpi"><div class="v">' + k[0] + '</div><div class="k">' +
        (k[2] ? '<span class="dot" style="background:' + k[2] + '"></span>' : "") +
        esc(k[1]) + "</div></div>";
    }).join("");

    $("sevBar").innerHTML = total
      ? ["error", "warning", "info"].filter(function (k) { return counts[k]; })
          .map(function (k) {
            return '<span title="' + k + ": " + counts[k] + '" style="flex:' +
              counts[k] + ";background:" + SEV[k] + '"></span>';
          }).join("")
      : '<span style="flex:1;background:var(--good)"></span>';
    $("sevLegend").innerHTML = ["error", "warning", "info"].map(function (k) {
      return '<span class="i"><span class="dot" style="background:' + SEV[k] +
        '"></span>' + k[0].toUpperCase() + k.slice(1) + " <b>" + counts[k] +
        "</b></span>";
    }).join("");

    if (payload.ids) {
      $("idsPanel").hidden = false;
      $("idsTitle").textContent = payload.ids.title;
      $("idsRows").innerHTML = payload.ids.specifications.map(function (s) {
        return "<tr><td class='" + (s.status ? "ok" : "bad") + "'>" +
          (s.status ? "PASS" : "FAIL") + "</td><td>" + esc(s.name) + "</td><td>" +
          s.applicable + "</td><td>" + s.passed + "</td><td>" + s.failed +
          "</td></tr>";
      }).join("");
    } else { $("idsPanel").hidden = true; }

    $("classRows").innerHTML = Object.keys(stats.by_class || {}).map(function (c) {
      return "<tr><td>" + esc(c) + "</td><td>" + stats.by_class[c] + "</td></tr>";
    }).join("");

    var cats = {};
    r.issues.forEach(function (i) { cats[i.category] = 1; });
    $("cat").innerHTML = '<option value="">All categories</option>' +
      Object.keys(cats).sort().map(function (c) {
        return '<option value="' + c + '">' + c[0].toUpperCase() + c.slice(1) +
          "</option>";
      }).join("");
    renderIssues();

    var files = [
      ["html", "HTML report", "Self-contained, offline, filterable"],
      ["xlsx", "Excel workbook", "Summary, issues, IDS and element sheets"],
      ["csv", "Issues CSV", "One row per issue / element"],
      ["json", "JSON", "Machine-readable — for CI or another tool"],
      ["db", "SQLite database", "The whole model, queryable"]
    ];
    if (payload.parent_id) {
      files.push(["ifc", "Fixed IFC", payload.filename + " — with the approved fixes"],
                 ["original", "Original IFC",
                  (payload.parent_filename || "") + " — untouched"],
                 ["changes", "Change log", "Every fix, its values and its outcome"]);
    } else {
      files.push(["ifc", "Original IFC", "The file as uploaded"]);
    }
    $("downloads").innerHTML = files.map(function (d) {
      return '<a href="/api/jobs/' + payload.id + "/download/" + d[0] +
        '"><div class="t">' + d[1] + '</div><div class="d">' + d[2] +
        "</div></a>";
    }).join("");

    if (payload.db) {
      $("tableRows").innerHTML = payload.db.tables.map(function (t) {
        return "<tr><td>" + esc(t) + "</td><td>" +
          payload.db.row_counts[t] + "</td></tr>";
      }).join("");
    } else {
      $("tableRows").innerHTML =
        '<tr><td colspan="2" class="empty">No database was built for this run.</td></tr>';
    }

    show("viewResult");
    selectTab("paneOverview");
  }

  /* ---------------- tabs ---------------- */
  function selectTab(pane) {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) {
      t.classList.toggle("on", t.getAttribute("data-pane") === pane);
    });
    ["paneOverview", "paneIssues", "paneFix", "pane3d", "paneData", "paneFiles"]
      .forEach(function (p) { $(p).hidden = p !== pane; });
    if (pane === "paneFix") loadFixes();
    if (pane === "pane3d") open3d();
  }
  Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) {
    t.addEventListener("click", function () {
      selectTab(t.getAttribute("data-pane"));
    });
  });

  /* ---------------- issue explorer ---------------- */
  function renderIssues() {
    if (!state.data) return;
    var q = $("q").value.trim().toLowerCase();
    var sev = $("sev").value, cat = $("cat").value;

    var shown = state.data.issues.filter(function (i) {
      if (sev && i.severity !== sev) return false;
      if (cat && i.category !== cat) return false;
      if (!q) return true;
      var hay = [i.rule_id, i.title, i.description,
        (i.elements || []).map(function (e) {
          return [e.guid, e.name, e.ifc_class, e.storey].join(" ");
        }).join(" ")].join(" ").toLowerCase();
      return hay.indexOf(q) !== -1;
    });

    $("issueCount").textContent = shown.length + " of " +
      state.data.issues.length + " issues";

    if (!shown.length) {
      $("groups").innerHTML = '<div class="group"><div class="empty">' +
        (state.data.issues.length ? "No issues match these filters."
                                  : "No issues found.") + "</div></div>";
      return;
    }

    var byRule = {};
    shown.forEach(function (i) {
      (byRule[i.rule_id] = byRule[i.rule_id] || []).push(i);
    });
    var rank = { error: 0, warning: 1, info: 2 };
    var order = Object.keys(byRule).sort(function (a, b) {
      return rank[byRule[a][0].severity] - rank[byRule[b][0].severity] ||
             byRule[b].length - byRule[a].length || a.localeCompare(b);
    });

    $("groups").innerHTML = order.map(function (rid) {
      var list = byRule[rid], s = list[0].severity;
      var rows = list.map(function (i) {
        var els = i.elements || [];
        var who = els.length ? els.map(function (e) {
          return "<div>" + esc(e.ifc_class || "") +
            (e.name ? " · " + esc(e.name) : "") +
            (e.guid ? " <code>" + esc(e.guid) + "</code>" +
              ' <button class="linkbtn" data-guid="' + esc(e.guid) +
              '" type="button">view in 3D</button>' : "") + "</div>";
        }).join("") : '<span style="color:var(--muted)">model-wide</span>';
        var hide = { key: 1, traceback: 1, specification: 1, requirement: 1, reason: 1 };
        var ev = Object.keys(i.evidence || {}).filter(function (k) {
          return !hide[k] && i.evidence[k] !== null;
        }).map(function (k) {
          return esc(k) + ": " + esc(JSON.stringify(i.evidence[k]));
        }).join("<br>");
        var finding = (i.evidence && i.evidence.reason) || i.title;
        return "<tr><td>" + who + "</td><td>" +
          esc((els[0] && els[0].storey) || "—") + "</td><td>" + esc(finding) +
          "</td><td><code>" + (ev || "—") + "</code></td></tr>";
      }).join("");

      return '<details class="group"' + (s === "error" ? " open" : "") +
        "><summary>" +
        '<span class="pill" style="color:' + SEV[s] + '">' +
        '<span class="dot" style="background:' + SEV[s] + '"></span>' + s +
        "</span>" +
        '<span class="gt">' + esc(list[0].title.split(" — ")[0]) + "</span>" +
        '<span class="rid">' + esc(rid) + "</span>" +
        '<span class="n">' + list.length + "</span></summary>" +
        '<div class="desc">' + esc(list[0].description) + "</div>" +
        "<table><thead><tr><th>Element</th><th>Storey</th><th>Finding</th>" +
        "<th>Evidence</th></tr></thead><tbody>" + rows + "</tbody></table>" +
        "</details>";
    }).join("");
  }
  $("groups").addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-guid]");
    if (btn) showIn3d(btn.getAttribute("data-guid"));
  });

  /* ---------------- 3D viewer ---------------- */
  var v3d = { job: null, viewer: null, loading: null, pending: null };

  function v3dMsg(text, isErr) {
    var m = $("v3dMsg");
    m.hidden = !text;
    m.textContent = text || "";
    m.classList.toggle("err", !!isErr);
  }

  function open3d() {
    if (!state.job) return Promise.resolve(null);
    if (v3d.job === state.job && (v3d.viewer || v3d.loading)) {
      return v3d.loading || Promise.resolve(v3d.viewer);
    }
    if (v3d.viewer) { v3d.viewer.dispose(); v3d.viewer = null; }
    var job = state.job, issues = state.data.issues;
    v3d.job = job;
    renderInfo(null);
    v3dMsg("Loading the 3D viewer…");
    v3d.loading = import("/static/viewer.js").then(function (mod) {
      if (v3d.job !== job) return null;
      var viewer = new mod.Viewer($("v3dCanvas"), { onSelect: renderInfo });
      return api("/api/jobs/" + job + "/elements").then(function (d) {
        return viewer.load("/api/jobs/" + job + "/download/ifc", d.elements,
                           issues, function (t) { v3dMsg(t); });
      }).then(function (stats) {
        if (v3d.job !== job) { viewer.dispose(); return null; }
        v3d.viewer = viewer;
        renderLegend(stats);
        if (v3d.pending) { showIn3d(v3d.pending); v3d.pending = null; }
        return viewer;
      });
    }).catch(function (e) {
      v3dMsg("The 3D view could not load: " + e.message +
        ". It needs internet access to load three.js and web-ifc.", true);
      v3d.job = null;
      return null;
    }).then(function (viewer) { v3d.loading = null; return viewer; });
    return v3d.loading;
  }

  function showIn3d(guid) {
    v3d.pending = guid;
    selectTab("pane3d");   // opens the viewer if needed
    if (v3d.viewer && v3d.job === state.job) {
      v3d.pending = null;
      if (!v3d.viewer.selectGuid(guid)) {
        $("v3dInfo").innerHTML = '<div class="note">This element has no 3D ' +
          "geometry, so it can't be shown. That is often the issue itself.</div>";
      }
    }
  }

  function renderLegend(stats) {
    $("v3dLegend").innerHTML = [["error", "Error"], ["warning", "Warning"],
      ["info", "Info only"]].map(function (k) {
        return '<span class="i"><span class="dot" style="background:' + SEV[k[0]] +
          '"></span>' + k[1] + "</span>";
      }).join("") + '<span class="i"><span class="dot" style="background:var(--v3d-clean)">' +
      "</span>No issues</span>" +
      '<div class="count" style="margin:6px 0 0;width:100%">' + stats.flagged +
      " of " + stats.elements + " elements have issues</div>";
  }

  function renderInfo(rec) {
    $("v3dIsoSel").disabled = !rec;
    if (!rec) {
      $("v3dInfo").innerHTML = '<p class="hint">Click an element to see its ' +
        "issues. Drag to orbit, right-drag to pan, scroll to zoom.</p>";
      return;
    }
    var name = rec.name && String(rec.name).trim();
    var rows = [["Class", rec.cls], ["Name", name || "(blank)"],
                ["Storey", rec.storey || "—"], ["GlobalId", rec.guid || "—"]];
    var issues = rec.issues.slice().sort(function (a, b) {
      return ({ error: 0, warning: 1, info: 2 })[a.severity] -
             ({ error: 0, warning: 1, info: 2 })[b.severity];
    });
    $("v3dInfo").innerHTML =
      "<h3>" + esc(name || rec.cls) + "</h3><table class='kv'>" +
      rows.map(function (r) {
        return "<tr><th>" + r[0] + "</th><td>" + esc(r[1]) + "</td></tr>";
      }).join("") + "</table>" +
      "<h4>" + (issues.length ? issues.length + " issue(s)" : "No issues") + "</h4>" +
      issues.map(function (i) {
        return '<div class="v3d-issue"><span class="pill" style="color:' +
          SEV[i.severity] + '"><span class="dot" style="background:' +
          SEV[i.severity] + '"></span>' + esc(i.severity) + "</span> " +
          esc(i.title) + '<div class="rid">' + esc(i.rule_id) + "</div></div>";
      }).join("");
  }

  $("v3dFit").addEventListener("click", function () {
    if (v3d.viewer) v3d.viewer.fit();
  });
  $("v3dColour").addEventListener("change", function () {
    if (v3d.viewer) v3d.viewer.setColourByIssues($("v3dColour").checked);
  });
  $("v3dXray").addEventListener("change", function () {
    if (v3d.viewer) v3d.viewer.setXray($("v3dXray").checked);
  });
  $("v3dIsoFlagged").addEventListener("click", function () {
    if (v3d.viewer) v3d.viewer.isolateFlagged();
  });
  $("v3dIsoSel").addEventListener("click", function () {
    if (v3d.viewer) v3d.viewer.isolateSelection();
  });
  $("v3dShowAll").addEventListener("click", function () {
    if (v3d.viewer) v3d.viewer.showAll();
  });
  $("v3dSection").addEventListener("input", function () {
    if (v3d.viewer) v3d.viewer.setSection(+$("v3dSection").value / 100);
  });

  ["q", "sev", "cat"].forEach(function (id) {
    $(id).addEventListener("input", renderIssues);
    $(id).addEventListener("change", renderIssues);
  });

  /* ---------------- fixed-copy banner ---------------- */
  function openRun(id) {
    api("/api/jobs/" + id + "/result").then(showResult).catch(function (e) {
      alert("That run is no longer available: " + e.message);
    });
  }

  // New issues are only alarming if they are errors or warnings.
  function newSpan(d) {
    var by = d.new_by_severity || {}, n = d.new || 0;
    var serious = (by.error || 0) + (by.warning || 0);
    var parts = ["error", "warning", "info"].filter(function (s) {
      return by[s];
    }).map(function (s) { return by[s] + " " + s; });
    return "<span" + (serious ? ' class="bad"' : "") + "><b>" + n + "</b> new" +
      (parts.length ? " (" + parts.join(", ") + ")" : "") + "</span>";
  }

  function renderBanner(payload) {
    var b = $("fixBanner");
    if (!payload.parent_id || !payload.changes) { b.hidden = true; return; }
    var c = payload.changes.counts, d = payload.diff || {};
    var bad = (payload.changes.changes || []).filter(function (x) {
      return x.status !== "applied";
    });
    var unresolved = d.unresolved_fixes || [];
    b.innerHTML =
      "<div><b>Fixed copy</b> of " + esc(payload.parent_filename) +
      '. The original is unchanged. <a href="#" id="openParent">Open the original run</a></div>' +
      '<div class="nums">' +
      "<span><b>" + c.applied + "</b> fixes applied</span>" +
      (c.failed ? '<span class="bad"><b>' + c.failed + "</b> failed</span>" : "") +
      (c.skipped ? "<span><b>" + c.skipped + "</b> skipped</span>" : "") +
      '<span class="ok"><b>' + (d.resolved || 0) + "</b> issues resolved</span>" +
      newSpan(d) +
      "<span><b>" + (d.after || 0) + "</b> remaining</span>" +
      (d.carried ? "<span title='Same defects on elements that got a new GlobalId'><b>" +
        d.carried + "</b> carried to a new GUID</span>" : "") +
      "</div>" +
      (bad.length ? "<details><summary>" + bad.length +
        " fix(es) not applied</summary><ul>" + bad.map(function (x) {
          return "<li>" + esc(x.element) + " — " + esc(x.summary) + ": <i>" +
            esc(x.status) + "</i> " + esc(x.message) + "</li>";
        }).join("") + "</ul></details>" : "") +
      (unresolved.length ? '<div class="bad">' + unresolved.length +
        " applied fix(es) did not clear their issue — see the Issues tab.</div>" : "");
    b.hidden = false;
    $("openParent").addEventListener("click", function (e) {
      e.preventDefault(); openRun(payload.parent_id);
    });
  }

  /* ---------------- fixes ---------------- */
  var KIND = { auto: "Auto", input: "Needs a value", manual: "Manual" };

  function loadFixes() {
    if (!state.job || (state.fixes && state.fixes.job === state.job)) return;
    var job = state.job;
    state.fixes = { job: job, list: null };
    $("fixSummary").innerHTML = "";
    $("fixBar").hidden = true;
    $("fixGroups").innerHTML = '<div class="note" style="margin-top:14px">' +
      "Working out fixes…</div>";
    api("/api/jobs/" + job + "/fixes").then(function (d) {
      if (state.job !== job) return;
      state.fixes.list = d.fixes;
      renderFixes();
    }).catch(function (e) {
      state.fixes = null;
      $("fixGroups").innerHTML = '<div class="note err" style="margin-top:14px">' +
        esc(e.message) + "</div>";
    });
  }

  function control(fix, f) {
    var attrs = ' data-issue="' + esc(fix.issue_id) + '" data-field="' +
      esc(f.name) + '"';
    var dv = f.default === null || f.default === undefined ? "" : String(f.default);
    if (f.type === "select" || f.type === "bool") {
      var opts = f.type === "bool"
        ? [{ value: "true", label: "True" }, { value: "false", label: "False" }]
        : f.options;
      return "<select" + attrs + ">" +
        '<option value="">— choose —</option>' +
        opts.map(function (o) {
          var v = String(o.value);
          return '<option value="' + esc(v) + '"' +
            (v.toLowerCase() === dv.toLowerCase() ? " selected" : "") + ">" +
            esc(o.label) + "</option>";
        }).join("") + "</select>";
    }
    var list = f.suggestions && f.suggestions.length
      ? ' list="dl-' + esc(f.name) + '"' : "";
    return '<input type="' + (f.type === "number" ? "number" : "text") + '"' +
      attrs + list + (f.type === "number" ? ' step="any"' : "") +
      (f.min !== null && f.min !== undefined ? ' min="' + f.min + '"' : "") +
      (f.max !== null && f.max !== undefined ? ' max="' + f.max + '"' : "") +
      ' value="' + esc(dv) + '" placeholder="' + esc(f.label) + '">';
  }

  function fieldsHtml(fix) {
    return fix.fields.map(function (f) {
      return '<label class="fld"><span>' + esc(f.label) + "</span>" +
        control(fix, f) + (f.unit ? '<span class="unit">' + esc(f.unit) +
        "</span>" : "") + "</label>";
    }).join("");
  }

  function renderFixes() {
    var list = state.fixes.list || [];
    var counts = { auto: 0, input: 0, manual: 0 };
    list.forEach(function (f) { counts[f.kind]++; });
    $("fixSummary").innerHTML = ["auto", "input", "manual"].map(function (k) {
      return '<span class="kind k-' + k + '">' + KIND[k] + " <b>" + counts[k] +
        "</b></span>";
    }).join("");

    if (!list.length) {
      $("fixGroups").innerHTML = '<div class="group"><div class="empty">' +
        "No issues, nothing to fix.</div></div>";
      $("fixBar").hidden = true;
      return;
    }

    // Datalists for free-text suggestions (materials), one per field name.
    var lists = {};
    list.forEach(function (fix) {
      fix.fields.forEach(function (f) {
        if (f.suggestions && f.suggestions.length) lists[f.name] = f.suggestions;
      });
    });
    var dl = Object.keys(lists).map(function (n) {
      return '<datalist id="dl-' + esc(n) + '">' + lists[n].map(function (v) {
        return '<option value="' + esc(v) + '">';
      }).join("") + "</datalist>";
    }).join("");

    var groups = {}, order = [];
    list.forEach(function (f) {
      if (!groups[f.rule_id]) { groups[f.rule_id] = []; order.push(f.rule_id); }
      groups[f.rule_id].push(f);
    });
    var kindRank = { auto: 0, input: 1, manual: 2 };
    var sevRank = { error: 0, warning: 1, info: 2 };
    order.sort(function (a, b) {
      var x = groups[a][0], y = groups[b][0];
      return kindRank[x.kind] - kindRank[y.kind] ||
        sevRank[x.severity] - sevRank[y.severity] || a.localeCompare(b);
    });

    $("fixGroups").innerHTML = dl + order.map(function (rid) {
      var g = groups[rid], first = g[0], s = first.severity;
      var actionable = first.kind !== "manual";
      var head = "<summary>" +
        (actionable ? '<input type="checkbox" class="gsel" data-rule="' +
          esc(rid) + '" title="Select all in this group">' : "") +
        '<span class="pill" style="color:' + SEV[s] + '"><span class="dot" ' +
        'style="background:' + SEV[s] + '"></span>' + esc(s) + "</span>" +
        '<span class="gt">' + esc(first.title.split(" — ")[0]) + "</span>" +
        '<span class="rid">' + esc(rid) + "</span>" +
        '<span class="kind k-' + first.kind + '">' + KIND[first.kind] + "</span>" +
        '<span class="n">' + g.length + "</span></summary>";

      if (!actionable) {
        return '<details class="group manual">' + head +
          '<div class="desc">' + esc(first.summary) + "</div>" +
          '<div class="desc els">' + g.map(function (f) {
            return esc(f.element);
          }).join(" · ") + "</div></details>";
      }

      // One "fill all" row per group when the fixes take the same fields.
      var fill = "";
      if (first.fields.length && g.length > 1) {
        fill = '<div class="fillall">' +
          "<span>Same value for all " + g.length + ":</span>" +
          first.fields.map(function (f) {
            var copy = JSON.parse(JSON.stringify(f));
            copy.default = null;
            return '<label class="fld">' + control({ issue_id: "__all__" }, copy) +
              (f.unit ? '<span class="unit">' + esc(f.unit) + "</span>" : "") +
              "</label>";
          }).join("") +
          '<button class="btn sm" type="button" data-fill="' + esc(rid) +
          '">Fill &amp; select all</button></div>';
      }

      var rows = g.map(function (f) {
        // "Suggested" = the fixer derived every value itself and said how.
        var suggested = f.inferred && f.fields.length && f.fields.every(function (x) {
          return x.default !== null && x.default !== undefined && x.default !== "";
        });
        return '<div class="fixrow">' +
          '<input type="checkbox" class="fsel" data-issue="' + esc(f.issue_id) +
          '" data-rule="' + esc(rid) + '" data-kind="' + f.kind + '"' +
          (suggested ? ' data-suggested="1"' : "") + ">" +
          '<div class="body"><div class="what"><b>' + esc(f.element) + "</b> — " +
          esc(f.summary) +
          (f.destructive ? ' <span class="kind k-del">deletes</span>' : "") +
          "</div>" +
          (f.detail ? '<div class="sub">' + esc(f.detail) + "</div>" : "") +
          (f.inferred ? '<div class="sub inf"><b>Suggested:</b> ' +
            esc(f.inferred) + "</div>" : "") +
          (f.fields.length ? '<div class="flds">' + fieldsHtml(f) + "</div>" : "") +
          "</div></div>";
      }).join("");

      return '<details class="group"' + (first.kind === "auto" ? " open" : "") +
        ">" + head + '<div class="desc">' + esc(first.title) + "</div>" + fill +
        rows + "</details>";
    }).join("");

    wireFixes();
    $("fixBar").hidden = false;
    var nSug = fixEls('.fsel[data-suggested="1"]').length;
    $("fixAllSuggested").hidden = !nSug;
    $("fixAllSuggested").textContent = "Select all suggestions (" + nSug + ")";
    updateFixCount();
  }

  function fixEls(sel) {
    return Array.prototype.slice.call($("fixGroups").querySelectorAll(sel));
  }

  function wireFixes() {
    fixEls(".gsel").forEach(function (g) {
      g.addEventListener("click", function (e) { e.stopPropagation(); });
      g.addEventListener("change", function () {
        fixEls('.fsel[data-rule="' + g.getAttribute("data-rule") + '"]')
          .forEach(function (b) { b.checked = g.checked; });
        updateFixCount();
      });
    });
    fixEls(".fsel").forEach(function (b) {
      b.addEventListener("change", updateFixCount);
    });
    // Editing a value selects its fix.
    fixEls(".fixrow [data-field]").forEach(function (inp) {
      inp.addEventListener("input", function () {
        var box = $("fixGroups").querySelector(
          '.fsel[data-issue="' + inp.getAttribute("data-issue") + '"]');
        if (box && inp.value !== "") { box.checked = true; updateFixCount(); }
      });
    });
    fixEls("[data-fill]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var rid = btn.getAttribute("data-fill");
        var src = btn.parentNode.querySelectorAll("[data-field]");
        fixEls('.fsel[data-rule="' + rid + '"]').forEach(function (box) {
          var id = box.getAttribute("data-issue");
          Array.prototype.forEach.call(src, function (s) {
            var t = $("fixGroups").querySelector('.fixrow [data-issue="' + id +
              '"][data-field="' + s.getAttribute("data-field") + '"]');
            if (t) t.value = s.value;
          });
          box.checked = true;
        });
        updateFixCount();
      });
    });
  }

  function updateFixCount() {
    var n = fixEls(".fsel:checked").length;
    $("fixCount").textContent = n + " fix" + (n === 1 ? "" : "es") + " selected";
    $("fixApply").disabled = n === 0;
    $("fixApply").textContent = n ? "Apply " + n + " to a copy" : "Apply to a copy";
    $("fixErr").textContent = "";
  }

  $("fixAllAuto").addEventListener("click", function () {
    fixEls('.fsel[data-kind="auto"]').forEach(function (b) { b.checked = true; });
    updateFixCount();
  });

  $("fixAllSuggested").addEventListener("click", function () {
    var boxes = fixEls('.fsel[data-suggested="1"]');
    boxes.forEach(function (b) { b.checked = true; });
    // Open the groups so the suggested values can be reviewed before applying.
    boxes.forEach(function (b) { b.closest("details").open = true; });
    updateFixCount();
  });

  $("fixApply").addEventListener("click", function () {
    var checked = fixEls(".fsel:checked");
    var chosen = checked.map(function (box) {
      var id = box.getAttribute("data-issue"), values = {};
      fixEls('.fixrow [data-issue="' + id + '"][data-field]').forEach(function (i) {
        values[i.getAttribute("data-field")] = i.value;
      });
      return { issue_id: id, values: values };
    });
    if (!chosen.length) return;
    var deletes = checked.filter(function (box) {
      return box.closest(".fixrow").querySelector(".k-del");
    }).length;
    if (deletes && !confirm(deletes + " of the selected fixes delete elements " +
        "from the copy. The original file is kept. Continue?")) return;

    var source = state.payload;
    $("fixApply").disabled = true;
    api("/api/jobs/" + state.job + "/fixes/apply", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fixes: chosen })
    }).then(function (job) {
      $("progTitle").textContent = "Applying " + chosen.length + " fixes";
      $("progSub").textContent = "Working on a copy of " + source.filename +
        " — the original is kept. The copy is re-audited when done.";
      $("logBox").textContent = "";
      state.job = job.id;
      show("viewProgress");
      track(job);
    }).catch(function (e) {
      $("fixErr").textContent = e.message;
      $("fixApply").disabled = false;
    });
  });

  /* ---------------- SQL + ask ---------------- */
  function renderExamples(list) {
    $("examples").innerHTML = list.map(function (q, i) {
      return "<button data-i='" + i + "'>" + esc(q.label) + "</button>";
    }).join("");
    Array.prototype.forEach.call($("examples").children, function (b) {
      b.addEventListener("click", function () {
        $("sqlBox").value = list[+b.getAttribute("data-i")].sql;
        runSql();
      });
    });
  }

  function renderRows(target, res) {
    if (res.error) {
      $(target).innerHTML = '<div class="note err" style="margin-top:14px">' +
        esc(res.error) + "</div>";
      return;
    }
    if (!res.columns || !res.columns.length) {
      $(target).innerHTML = '<div class="note" style="margin-top:14px">' +
        "Query returned no columns.</div>";
      return;
    }
    $(target).innerHTML = '<div class="scroll"><table><thead><tr>' +
      res.columns.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("") +
      "</tr></thead><tbody>" +
      res.rows.map(function (row) {
        return "<tr>" + row.map(function (v) {
          return "<td>" + esc(v === null ? "NULL" : v) + "</td>";
        }).join("") + "</tr>";
      }).join("") + "</tbody></table></div>";
  }

  function runSql() {
    if (!state.job) return;
    var sql = $("sqlBox").value;
    $("sqlCount").textContent = "running…";
    api("/api/jobs/" + state.job + "/sql", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql: sql })
    }).then(function (res) {
      $("sqlCount").textContent = res.error ? "" :
        res.row_count + " row(s)" + (res.truncated ? " (truncated)" : "");
      renderRows("sqlOut", res);
    }).catch(function (e) {
      $("sqlCount").textContent = "";
      $("sqlOut").innerHTML = '<div class="note err" style="margin-top:14px">' +
        esc(e.message) + "</div>";
    });
  }
  $("runSql").addEventListener("click", runSql);
  $("sqlBox").addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runSql();
  });

  $("dlCsv").addEventListener("click", function () {
    if (!state.job) return;
    fetch("/api/jobs/" + state.job + "/sql.csv", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql: $("sqlBox").value })
    }).then(function (r) { return r.text(); }).then(function (text) {
      var blob = new Blob([text], { type: "text/csv" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "query_result.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    });
  });

  function ask() {
    if (!state.job) return;
    var question = $("question").value.trim();
    if (!question) return;
    $("askNote").innerHTML = '<div class="note" style="margin-top:12px">Thinking…</div>';
    api("/api/jobs/" + state.job + "/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question })
    }).then(function (res) {
      if (res.available === false) {
        $("askNote").innerHTML = '<div class="note" style="margin-top:12px"><b>' +
          esc(res.error) + "</b><br>" + esc(res.hint) + "</div>";
        return;
      }
      if (res.error) {
        $("askNote").innerHTML = '<div class="note err" style="margin-top:12px">' +
          esc(res.error) + "</div>";
        return;
      }
      renderAnswer(res);
    }).catch(function (e) {
      $("askNote").innerHTML = '<div class="note err" style="margin-top:12px">' +
        esc(e.message) + "</div>";
    });
  }
  function label(col) {
    var s = String(col).replace(/_/g, " ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }
  function cell(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "number") {
      return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return String(v);
  }

  // The SQL is always shown — every number comes from the database, not
  // from the language model, and the user can check the query behind it.
  function renderAnswer(res) {
    var html = '<div class="answer">';
    if (res.answer) html += '<p class="sentence">' + esc(res.answer) + "</p>";
    var cols = res.columns || [], rows = res.rows || [];

    if (!rows.length) {
      if (!res.answer) html += '<p class="sentence">No matching results.</p>';
    } else if (rows.length === 1 && cols.length <= 4 &&
               rows[0].every(function (v) { return typeof v === "number"; })) {
      // A handful of figures: show them as stat tiles.
      html += '<div class="kpis">' + cols.map(function (c, i) {
        return '<div class="kpi"><div class="v">' + esc(cell(rows[0][i])) +
          '</div><div class="k">' + esc(label(c)) + "</div></div>";
      }).join("") + "</div>";
    } else {
      html += '<div class="scroll"><table><thead><tr>' +
        cols.map(function (c) { return "<th>" + esc(label(c)) + "</th>"; }).join("") +
        "</tr></thead><tbody>" + rows.map(function (r) {
          return "<tr>" + r.map(function (v) {
            return "<td" + (typeof v === "number" ? ' class="num"' : "") + ">" +
              esc(cell(v)) + "</td>";
          }).join("") + "</tr>";
        }).join("") + "</tbody></table></div>" +
        '<div class="count" style="margin:6px 0 0">' + rows.length + " row(s)" +
        (res.truncated ? " (truncated)" : "") + "</div>";
    }
    html += '<details class="how"><summary>SQL behind this answer</summary><code>' +
      esc(res.sql) + "</code></details></div>";
    $("askNote").innerHTML = html;
  }

  var ASK_EXAMPLES = [
    "What does this file contain?",
    "How many issues are there by severity?",
    "What are the most serious issues?",
    "Which storeys have the most issues?",
    "Which doors have no fire rating?",
    "How many elements are on each storey?"
  ];
  $("askExamples").innerHTML = ASK_EXAMPLES.map(function (q, i) {
    return "<button data-i='" + i + "'>" + esc(q) + "</button>";
  }).join("");
  Array.prototype.forEach.call($("askExamples").children, function (b) {
    b.addEventListener("click", function () {
      $("question").value = ASK_EXAMPLES[+b.getAttribute("data-i")];
      ask();
    });
  });

  $("askBtn").addEventListener("click", ask);
  $("question").addEventListener("keydown", function (e) {
    if (e.key === "Enter") ask();
  });
})();
