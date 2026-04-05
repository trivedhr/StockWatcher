@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found.
    echo         Run setup.bat first to install all dependencies.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
echo.
echo ========================================
echo   StockPerformer  --  http://localhost:5000
echo ========================================
echo.
python server.py
pause
