@echo off
setlocal EnableDelayedExpansion

echo.
echo =========================================
echo   StockPerformer -- Setup ^& Install
echo =========================================
echo.

:: ── 1. Check Python ──────────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo         Download from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo [OK]  Found %PY_VER%

:: Require Python 3.9+
python -c "import sys; exit(0 if sys.version_info >= (3,9) else 1)" 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.9 or higher is required.
    pause
    exit /b 1
)

:: ── 2. Create virtual environment ────────────────────────────────────────────
if not exist ".venv\" (
    echo [....] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK]  Virtual environment created.
) else (
    echo [OK]  Virtual environment already exists.
)

:: ── 3. Activate venv ─────────────────────────────────────────────────────────
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)
echo [OK]  Virtual environment activated.

:: ── 4. Upgrade pip ───────────────────────────────────────────────────────────
echo [....] Upgrading pip...
python -m pip install --upgrade pip --quiet
echo [OK]  pip up to date.

:: ── 5. Install dependencies ──────────────────────────────────────────────────
echo [....] Installing dependencies from requirements.txt...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check the output above.
    pause
    exit /b 1
)

:: ── 6. Verify key packages ───────────────────────────────────────────────────
echo.
echo [....] Verifying installed packages...

python -c "import flask; print('[OK]  flask', flask.__version__)"
python -c "import yfinance; print('[OK]  yfinance', yfinance.__version__)"
python -c "import pandas; print('[OK]  pandas', pandas.__version__)"
python -c "import requests; print('[OK]  requests', requests.__version__)"
python -c "import waitress; print('[OK]  waitress (WSGI server)')"
python -c "import lxml; print('[OK]  lxml')"

:: ── 7. Create start.bat if missing ───────────────────────────────────────────
if not exist "start.bat" (
    echo @echo off > start.bat
    echo cd /d "%~dp0" >> start.bat
    echo call .venv\Scripts\activate.bat >> start.bat
    echo python server.py >> start.bat
    echo pause >> start.bat
    echo [OK]  Created start.bat
)

echo.
echo =========================================
echo   Setup complete!
echo.
echo   To start the server:
echo     Double-click start.bat
echo   OR run:
echo     python server.py
echo.
echo   Then open: http://localhost:5000
echo =========================================
echo.

set /p LAUNCH="Start the server now? (y/n): "
if /i "%LAUNCH%"=="y" (
    python server.py
)

endlocal
