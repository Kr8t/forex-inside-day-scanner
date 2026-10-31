@echo off
rem Forex Scanner launcher for Windows.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo Install Python 3.10+ from https://python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

python forex_scanner.py scan --set all
set RC=%errorlevel%
if not %RC%==0 echo [WARN] Scanner exited with code %RC% - check the messages above.
pause
exit /b %RC%
