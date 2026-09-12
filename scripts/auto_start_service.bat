@echo off
REM QuantAI user-login watchdog launcher.
REM The PowerShell process remains alive and restarts the Adaptive API whenever
REM Python exits. The Startup-folder VBS launches this batch without a window.
set WORKSPACE=%~dp0..\..
set WATCHDOG=%WORKSPACE%\scripts\start_adaptive_learning_backend.ps1

if not exist "%WATCHDOG%" (
    echo [%date% %time%] watchdog script not found: %WATCHDOG%
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WATCHDOG%"
