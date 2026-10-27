@echo off
setlocal
cd /d "%~dp0"
"Azeroth Survivors Together\.coop-runtime\python.exe" -u server\public_server.py serve
pause
