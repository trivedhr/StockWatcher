@echo off
echo ========================================
echo   StockPerformer - S^&P 500 Dashboard
echo ========================================
echo.
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Starting server...
echo Open http://localhost:5000 in your browser
echo.
python server.py
pause
