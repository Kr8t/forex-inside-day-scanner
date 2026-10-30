@echo off
cd /d "%~dp0"
python forex_scanner.py scan --set all
pause