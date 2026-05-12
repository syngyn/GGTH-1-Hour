@echo off
setlocal enabledelayedexpansion

REM ============================================
REM GGTH Predictor v2.3 - Smart Launcher
REM Handles Python detection and setup
REM Also launches the sentiment pipeline (main.py)
REM ============================================

REM Change to script directory
cd /d "%~dp0"

REM Store script directory without trailing backslash
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

echo.
echo ================================================
echo  GGTH Predictor v2.3 - Starting Up...
echo  (unified_predictor_v9.py)
echo ================================================
echo.

REM --- Step 1: Check for Python ---
echo [1/4] Checking for Python installation...

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ================================================
    echo  ERROR: Python Not Found!
    echo ================================================
    echo.
    echo Python is required but not installed or not in PATH.
    echo.
    echo Please install Python 3.9, 3.10, or 3.11 from:
    echo https://www.python.org/downloads/
    echo.
    echo IMPORTANT: During installation, check the box that says:
    echo "Add Python to PATH"
    echo.
    echo After installing Python, run this script again.
    echo.
    pause
    exit /b 1
)

REM Check Python version
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo    Found Python version: %PYVER%

REM --- Step 2: Create Virtual Environment ---
echo [2/4] Setting up virtual environment...

if not exist ".venv" (
    echo    Creating new virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo.
        echo ERROR: Failed to create virtual environment.
        echo This usually means Python venv module is not available.
        echo.
        echo Try reinstalling Python and ensure "pip" is included.
        echo.
        pause
        exit /b 1
    )
    echo    Virtual environment created successfully!
) else (
    echo    Virtual environment already exists.
)

REM --- Step 3: Activate and Install Dependencies ---
echo [3/4] Activating virtual environment...

call ".venv\Scripts\activate.bat"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to activate virtual environment.
    echo Try deleting the .venv folder and running this script again.
    echo.
    pause
    exit /b 1
)

echo    Virtual environment activated.
echo.
echo [4/4] Installing/updating required packages...
echo    This may take a few minutes on first run...
echo.

REM Upgrade pip first
python -m pip install --upgrade pip --quiet

REM Install requirements
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Dependency installation failed.
    echo Fix the pip error above before launching GGTH.
    pause
    exit /b 1
)

echo.
echo ================================================
echo  Setup Complete!
echo ================================================
echo.

REM --- Launch Sentiment Pipeline ---
REM Write a helper bat to avoid nested-quote issues inside start command
echo Starting news sentiment pipeline (main.py)...

if exist "main.py" (
    set "HELPER=%TEMP%\ggth_sentiment_launch.bat"
    (
        echo @echo off
        echo cd /d "!SCRIPT_DIR!"
        echo call "!SCRIPT_DIR!\.venv\Scripts\activate.bat"
        echo python "!SCRIPT_DIR!\main.py"
        echo pause
    ) > "!HELPER!"

    start "GGTH Sentiment Pipeline" cmd /k "!HELPER!"
    echo    Sentiment pipeline window opened.
    echo    Close that window to stop the sentiment pipeline.
) else (
    echo    WARNING: main.py not found - sentiment pipeline not started.
)

echo.
echo ================================================
echo  Launching GUI...
echo ================================================
echo.

REM --- Launch GUI ---
python ggth_gui.py

if %errorlevel% neq 0 (
    echo.
    echo ================================================
    echo  GUI Exited with Error Code: %errorlevel%
    echo ================================================
    echo.
    echo If you see import errors, try running:
    echo    pip install -r requirements.txt
    echo.
    pause
)

endlocal
