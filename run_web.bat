@echo off
REM ---------------------------------------------------------------
REM  ifc-demo : start the web app (Windows)
REM ---------------------------------------------------------------
setlocal

cd /d "%~dp0"

if not exist ".venv\" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :nopython
    call .venv\Scripts\activate.bat
    echo Installing dependencies ^(this takes a minute the first time^)...
    python -m pip install --upgrade pip --quiet
    python -m pip install -r requirements.txt
    if errorlevel 1 goto :pipfail
) else (
    call .venv\Scripts\activate.bat
)

if not exist "examples\sample_model.ifc" (
    echo Generating the sample model...
    python tools\make_sample.py examples\sample_model.ifc
)
if not exist "examples\project_requirements.ids" (
    echo Generating the example IDS ruleset...
    python tools\make_ids.py examples\project_requirements.ids
)

REM  Optional: enable natural-language questions by setting a key here.
REM  set OPENAI_API_KEY=sk-...

echo.
echo ===============================================================
echo  Starting the web app  -  http://127.0.0.1:8000
echo  Press Ctrl+C to stop.
echo ===============================================================
echo.
python serve.py
goto :end

:nopython
echo.
echo ERROR: Python was not found on PATH. Install Python 3.10+ and retry.
pause
goto :end

:pipfail
echo.
echo ERROR: Dependency installation failed. See the messages above.
pause

:end
endlocal
