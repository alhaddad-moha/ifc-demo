/* IFC Audit — front end. No framework, no build step. */

(function () {
  "use strict";

  var SEV = { error: "var(--sev-error)", warning: "var(--sev-warning)",
              info: "var(--sev-info)" };
  var state = { job: null, data: null, poll: null, ids: null, config: null };

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

    $("downloads").innerHTML = [
      ["html", "HTML report", "Self-contained, offline, filterable"],
      ["xlsx", "Excel workbook", "Summary, issues, IDS and element sheets"],
      ["csv", "Issues CSV", "One row per issue / element"],
      ["json", "JSON", "Machine-readable — for CI or another tool"],
      ["db", "SQLite database", "The whole model, queryable"],
      ["ifc", "Original IFC", "The file as uploaded"]
    ].map(function (d) {
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
    ["paneOverview", "paneIssues", "paneData", "paneFiles"].forEach(function (p) {
      $(p).hidden = p !== pane;
    });
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
            (e.guid ? " <code>" + esc(e.guid) + "</code>" : "") + "</div>";
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
  ["q", "sev", "cat"].forEach(function (id) {
    $(id).addEventListener("input", renderIssues);
    $(id).addEventListener("change", renderIssues);
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
      // The SQL is always shown — the number comes from the database, not
      // from the model, and the user can check the query that produced it.
      $("askNote").innerHTML =
        '<div class="note" style="margin-top:12px">Ran this query:<br>' +
        "<code>" + esc(res.sql) + "</code></div><div id='askRows'></div>";
      renderRows("askRows", res);
    }).catch(function (e) {
      $("askNote").innerHTML = '<div class="note err" style="margin-top:12px">' +
        esc(e.message) + "</div>";
    });
  }
  $("askBtn").addEventListener("click", ask);
  $("question").addEventListener("keydown", function (e) {
    if (e.key === "Enter") ask();
  });
})();
