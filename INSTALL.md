# Install and run IFC Audit

A step-by-step guide for getting IFC Audit running on your own computer and
auditing your first model. No programming needed.

- **Time:** about 10 minutes, most of it the first-time download.
- **Works on:** Windows 10/11, macOS, Linux.
- **Runs locally:** your models never leave your computer. The app runs a
  small web server that only your own machine can reach.

---

## Part 1: Install (once)

### Step 1: Install Python

You need **Python 3.10, 3.11, 3.12 or 3.13**.

**Windows**
1. Go to <https://www.python.org/downloads/windows/> and download the
   latest **Python 3.13** installer.
2. Run it. On the first screen, **tick "Add python.exe to PATH"**, then click
   **Install Now**.
3. Check it: open **PowerShell** and type:
   ```powershell
   python --version
   ```
   You should see `Python 3.13.x`.

**macOS**: install from <https://www.python.org/downloads/macos/>, or with
Homebrew: `brew install python@3.13`. Check with `python3 --version`.

**Linux**: use your package manager, e.g. `sudo apt install python3 python3-venv`.

> If Windows opens the Microsoft Store when you type `python`, the PATH box
> wasn't ticked. Re-run the installer, choose **Modify**, and enable
> "Add Python to environment variables".

### Step 2: Get the IFC Audit folder

Either:

- **From a zip** someone sent you: unzip it somewhere simple, e.g.
  `C:\Tools\ifc-audit`. Avoid putting it inside OneDrive or a path with
  unusual characters.
- **From git**, if you were given a repository link:
  ```bash
  git clone <repository-url> ifc-audit
  ```

The folder should contain `run_web.bat`, `run_web.sh`, `serve.py` and
`requirements.txt`.

### Step 3: First start (installs everything)

**Windows**: double-click **`run_web.bat`**.

**macOS / Linux**: open a terminal in the folder and run:
```bash
chmod +x run_web.sh
./run_web.sh
```

The first start takes a few minutes. It:
1. creates a private Python environment in `.venv` (nothing is installed
   system-wide),
2. downloads the libraries (IfcOpenShell, FastAPI…),
3. generates example models and an example requirements file,
4. starts the server and opens your browser at **<http://127.0.0.1:8000>**.

Keep the black console window open while you use the app. Closing it stops
the app.

Later starts take a few seconds.

---

## Part 2: Use it, step by step

### Step 4: Upload a model

1. In the browser at <http://127.0.0.1:8000>, drag an `.ifc` file onto the
   drop area, or click it to choose a file.
   To try it first, use **`examples\sample_model.ifc`**. It contains twelve
   deliberate defects.
2. The options under the drop area are all on by default. Leave them:
   - **Validate schema:** checks the file against the IFC standard.
   - **Build queryable database:** needed for the Data tab and the Ask box.
   - **Apply IDS requirements:** checks the example rules (doors need a fire
     rating, walls need IsExternal…). Click **Use my own IDS** to check
     against your own `.ids` file instead.
3. Watch the progress steps. A small model takes seconds; a 100 MB model can
   take a few minutes.

### Step 5: Read the results

The results page has six tabs.

| Tab | What you do there |
|---|---|
| **Overview** | Totals: errors, warnings, info, IDS pass/fail, element counts by class. |
| **Issues** | Every problem, grouped by rule. Filter by severity or search by name/GUID. **view in 3D** jumps to the element. |
| **Fix** | Review proposed fixes, fill in values, apply them to a copy of the file. |
| **3D** | The model coloured by issue severity. Click an element to see its issues. |
| **Data** | Ask questions in plain English, or write SQL yourself. |
| **Downloads** | HTML report, Excel workbook, CSV, JSON, SQLite database, IFC. |

Severity:
- **Error**: the model is wrong or unusable for downstream work.
- **Warning**: probably wrong; needs a person's decision.
- **Info**: good practice, not a defect.

### Step 6: Look at problems in 3D

1. Open the **3D** tab. The first time takes a few seconds, because it
   downloads the 3D engine (**needs internet**).
2. Red = error, amber = warning, grey = info only, neutral = no issues.
3. **Drag** to orbit, **right-drag** to pan, **scroll** to zoom.
4. **Click an element** to see its class, name, storey, GlobalId and issues.
5. Toolbar:
   - **Fit** re-centres the view.
   - **X-ray** fades everything that has no issues.
   - **Only elements with issues** hides the rest.
   - **Isolate selected** shows just the clicked element.
   - **Section** slices the building horizontally.

### Step 7: Fix issues (optional)

The file you uploaded is **never changed**. Fixes go into a new copy.

1. Open the **Fix** tab. Each issue shows one of:
   - **Auto**: the fix is unambiguous (e.g. a duplicated GUID). Just tick it.
   - **Needs a value**: you provide the value (fire rating, material…). Some
     come with a **Suggested** value and the reason for it.
   - **Manual**: can only be fixed in the authoring tool (Revit etc.).
     The advice text tells you what to change there.
2. Select what you want:
   - **Select all auto fixes**
   - **Select all suggestions**: ticks every fix whose value the app worked
     out from the model. Review them before applying.
   - For groups, use **Same value for all N** → **Fill & select all**
     (e.g. type `EI60` once for every door missing a fire rating).
3. Click **Apply N to a copy**. Fixes that delete elements ask you to confirm.
4. The copy is re-audited automatically. A banner shows what changed:
   fixes applied, issues resolved, anything new.
5. **Downloads** now offers the **Fixed IFC**, the untouched **Original IFC**
   and a **Change log** (every fix, its value and its result).

> Fixes are for quick clean-up and handover. If the model will be exported
> again from Revit, make the same changes there too, or they will be lost on
> the next export.

### Step 8: Ask questions (optional, needs an AI key)

On the **Data** tab, type a question or click a suggested one:

- *What does this file contain?*
- *How many issues are there by severity?*
- *What are the most serious issues?*
- *Which doors have no fire rating?*

The answer comes with the SQL query that produced it. The numbers always come
from the database, never from the AI.

The **SQL console** below works without any key.

To turn the Ask box on, see **Part 3**.

### Step 9: Stop, restart, come back later

- **Stop:** press **Ctrl+C** in the console window, or close it.
- **Start again:** double-click `run_web.bat` (or `./run_web.sh`).
- The run list on the home page is kept in memory, so it **clears when the
  app stops**. The files stay on disk under `data\<run-id>\`; re-upload the
  model to see a run again.

---

## Part 3: Turn on the Ask box (optional)

The Ask box needs an API key from an AI provider. This is **separate from a
ChatGPT or Claude subscription**: API usage is prepaid credit bought on the
provider's developer console. Each question costs a fraction of a cent.

1. Get a key:
   - **Claude:** <https://console.anthropic.com> → Billing (add credit) →
     API Keys → Create key.
   - **OpenAI:** <https://platform.openai.com> → Billing → API keys.
   - **OpenRouter:** <https://openrouter.ai/keys>.
2. In the IFC Audit folder, copy **`ai_settings.example.bat`** to
   **`ai_settings.bat`** (macOS/Linux: `ai_settings.example.sh` →
   `ai_settings.sh`).
3. Open the copy in Notepad. Remove `REM ` (or `# `) from the lines of **one**
   option, paste your key, and save.
4. Restart the app. The top bar should say **"AI queries on"**.

`ai_settings.bat` is ignored by git. **Never share it or paste your key into
chats, emails or screenshots.** If a key leaks, revoke it on the provider's
site and create a new one.

---

## Part 4: Command line (optional)

The same audit without the browser. Useful for scripts and CI:

```bat
.venv\Scripts\activate
python audit.py path\to\model.ifc --ids examples\project_requirements.ids --schema-check
```

Reports go to `reports\`. Add `--fail-on error` to exit with code 1 when
errors are found. `python audit.py --help` lists every option.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| **"Python was not found"** | Install Python (Step 1) and tick **Add to PATH**. Open a *new* window afterwards. |
| **Installation fails on a Python version error** | Use Python 3.10–3.13. Delete the `.venv` folder and start again. |
| **The browser doesn't open** | Open <http://127.0.0.1:8000> yourself. |
| **"Address already in use" / port 8000 busy** | Another copy is already running; use that window, or close it. To use another port: `python serve.py --port 8001`. |
| **3D tab: "could not load"** | The 3D engine loads from the internet (jsDelivr). Check your connection or firewall. |
| **3D: an element is missing** | It has no geometry in the file. Its Issues row says so. |
| **Ask: "No language model is configured"** | No key was loaded. Check `ai_settings.bat` exists (not just the `.example`), then restart. |
| **Ask: "credit balance is too low"** | Add credit on the provider's console. A subscription doesn't include API usage. |
| **Ask: "anthropic-workspace-id header"** | Set `ANTHROPIC_WORKSPACE_ID` in `ai_settings.bat`, or create the key inside a workspace. |
| **Everything is broken after an update** | Delete the `.venv` folder and start again. It reinstalls cleanly. |

---

## Sharing it with others

To make a clean zip without your private files (`.venv`, `data`, keys), run
this in the folder (needs git):

```bash
git archive --format=zip -o ifc-audit.zip HEAD
```

Send `ifc-audit.zip`. The receiver starts from **Part 1**.

---

**How does it work inside?** See [HOW_IT_WORKS.md](HOW_IT_WORKS.md).
