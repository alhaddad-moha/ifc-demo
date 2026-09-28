#!/usr/bin/env bash
# ---------------------------------------------------------------
#  ifc-demo : start the web app (macOS / Linux)
#  First run creates .venv and installs dependencies.
# ---------------------------------------------------------------
set -e
cd "$(dirname "$0")"

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "ERROR: Python was not found. Install Python 3.10+ and retry."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  "$PY" -m venv .venv
  . .venv/bin/activate
  echo "Installing dependencies (this takes a minute the first time)..."
  python -m pip install --upgrade pip --quiet
  python -m pip install -r requirements.txt
else
  . .venv/bin/activate
fi

[ -f examples/sample_model.ifc ] || python tools/make_sample.py examples/sample_model.ifc
[ -f examples/clean_model.ifc ] || python tools/make_sample.py examples/clean_model.ifc --clean
[ -f examples/project_requirements.ids ] || python tools/make_ids.py examples/project_requirements.ids

# Optional AI settings (copy ai_settings.example.sh to ai_settings.sh).
[ -f ai_settings.sh ] && . ./ai_settings.sh

echo
echo "==============================================================="
echo " Starting the web app  -  http://127.0.0.1:8000"
echo " Press Ctrl+C to stop."
echo "==============================================================="
python serve.py
