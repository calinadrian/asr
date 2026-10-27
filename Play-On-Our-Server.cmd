@echo off
setlocal
cd /d "%~dp0"
"Azeroth Survivors Together\.coop-runtime\python.exe" server\public_server.py play
if errorlevel 1 pause
