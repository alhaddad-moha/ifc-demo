@echo off
REM ---------------------------------------------------------------
REM  ifc-demo : one-click setup + demo run (Windows)
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
    echo Generating the sample model with deliberate defects...
    python tools\make_sample.py examples\sample_model.ifc
)

if not exist "examples\project_requirements.ids" (
    echo Generating the example IDS ruleset...
    python tools\make_ids.py examples\project_requirements.ids
)

echo.
echo ===============================================================
echo  Running the audit
echo ===============================================================
python audit.py examples\sample_model.ifc ^
    --ids examples\project_requirements.ids ^
    --schema-check

echo.
echo Done. The HTML report should have opened in your browser.
goto :end

:nopython
echo.
echo ERROR: Python was not found on PATH. Install Python 3.10+ and retry.
goto :end

:pipfail
echo.
echo ERROR: Dependency installation failed. See the messages above.

:end
pause
endlocal
