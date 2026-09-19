@echo off
REM Adaptive daily market-data verification.
REM Task Scheduler trigger: daily 09:35 after market open.
REM Verify the live quote and K-line provider chain.
setlocal
set PROJECT=%~dp0..
cd /d "%PROJECT%"
if not exist logs mkdir logs
echo === %date% %time% === >> logs\daily_verify.log
set PYTHON=%PROJECT%\.venv\Scripts\python.exe
if exist "%PYTHON%" (
    "%PYTHON%" scripts\verify_trading_day.py >> logs\daily_verify.log 2>&1
) else if exist "%PROJECT%\poetry.lock" (
    poetry run python scripts\verify_trading_day.py >> logs\daily_verify.log 2>&1
) else (
    python scripts\verify_trading_day.py >> logs\daily_verify.log 2>&1
)
exit /b %errorlevel%
