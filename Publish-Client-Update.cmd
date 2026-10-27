@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" goto usage
if "%~2"=="" goto usage
"Azeroth Survivors Together\.coop-runtime\python.exe" launcher\release.py --version "%~1" --sequence "%~2" --promote
exit /b %errorlevel%
:usage
echo Usage: Publish-Client-Update.cmd VERSION SEQUENCE
echo Example: Publish-Client-Update.cmd 0.1.2 3
exit /b 1
