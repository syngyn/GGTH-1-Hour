@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  GGTH Predictor v2.3 — Install Wizard Launcher
REM  Bootstraps a minimal venv (no heavy ML deps) then runs
REM  install_wizard.py to let the user pick their MT5 path.
REM ============================================================

cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   GGTH Predictor v2.3 — Install Wizard  ║
echo  ╚══════════════════════════════════════════╝
echo.

REM ── 1. Locate Python ─────────────────────────────────────────

echo [1/3] Checking for Python...

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Python not found in PATH.
    echo.
    echo  Install Python 3.9, 3.10, or 3.11 from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: Tick "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo     Found Python %PYVER%

REM Warn if Python 3.12+ (tensorflow 2.15 not supported)
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set "PY_MAJ=%%a"
    set "PY_MIN=%%b"
)
if %PY_MIN% GEQ 12 (
    echo.
    echo  WARNING: Python %PYVER% detected.
    echo  TensorFlow 2.15 ^(required by GGTH^) only supports Python 3.9–3.11.
    echo  The install wizard will still run, but training may fail later.
    echo.
)

REM ── 2. Create / reuse a lightweight venv for the wizard ──────

echo [2/3] Setting up wizard environment...

set "WIZARD_VENV=%SCRIPT_DIR%\.wizard_venv"

if not exist "%WIZARD_VENV%\Scripts\python.exe" (
    echo     Creating lightweight venv...
    python -m venv "%WIZARD_VENV%"
    if %errorlevel% neq 0 (
        echo.
        echo  ERROR: Could not create virtual environment.
        echo  Try reinstalling Python and ensure the venv module is available.
        echo.
        pause
        exit /b 1
    )

    REM The wizard only needs tkinter (built-in) — no pip installs required.
    REM Upgrade pip quietly so it doesn't print noise.
    "%WIZARD_VENV%\Scripts\python.exe" -m pip install --upgrade pip --quiet 2>nul
    echo     Wizard environment ready.
) else (
    echo     Existing wizard environment found.
)

REM ── 3. Run the install wizard ─────────────────────────────────

echo [3/3] Launching Install Wizard...
echo.

if not exist "%SCRIPT_DIR%\install_wizard.py" (
    echo  ERROR: install_wizard.py not found in:
    echo    %SCRIPT_DIR%
    echo.
    echo  Make sure install_wizard.py is in the same folder as this .bat file.
    echo.
    pause
    exit /b 1
)

"%WIZARD_VENV%\Scripts\python.exe" "%SCRIPT_DIR%\install_wizard.py"

if %errorlevel% neq 0 (
    echo.
    echo  The wizard exited with an error (code %errorlevel%).
    echo.
    echo  If you see a tkinter import error, ensure your Python
    echo  installation includes Tk/Tcl support (standard on Windows).
    echo.
    pause
    exit /b %errorlevel%
)

endlocal
