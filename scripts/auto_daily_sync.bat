@echo off
REM Adaptive daily market-data sync.
REM Task Scheduler trigger: daily 16:00 after market close.
REM Sync recent daily bars for the outcome-backfill learning loop.
setlocal
set PROJECT=%~dp0..
cd /d "%PROJECT%"
if not exist logs mkdir logs
echo === %date% %time% === >> logs\daily_sync.log
set PYTHON=%PROJECT%\.venv\Scripts\python.exe
if exist "%PYTHON%" (
    "%PYTHON%" scripts\daily_sync.py >> logs\daily_sync.log 2>&1
) else if exist "%PROJECT%\poetry.lock" (
    poetry run python scripts\daily_sync.py >> logs\daily_sync.log 2>&1
) else (
    python scripts\daily_sync.py >> logs\daily_sync.log 2>&1
)
exit /b %errorlevel%
