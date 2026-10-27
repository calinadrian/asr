@echo off
setlocal
cd /d "%~dp0"
rem The co-op runtime's Python runs every ASR tool.
set "PY=Azeroth Survivors Together\.coop-runtime\python.exe"
if /i "%~1"=="stage" if not "%~3"=="" ("%PY%" launcher\release.py --version "%~2" --sequence "%~3" --stage-only & exit /b)
if /i "%~1"=="test" ("%PY%" launcher\test_launcher.py & exit /b)
if /i "%~1"=="publish" if not "%~3"=="" ("%PY%" launcher\release.py --version "%~2" --sequence "%~3" --promote & exit /b)
if /i "%~1"=="upload" if not "%~3"=="" ("%PY%" launcher\release.py --version "%~2" --sequence "%~3" --upload & exit /b)
if /i "%~1"=="server" ("%PY%" -u server\public_server.py serve & pause & exit /b)
if /i "%~1"=="play" ("%PY%" server\public_server.py play & exit /b)
echo Usage:
echo   asr stage VERSION SEQUENCE    build and sign a launcher candidate, e.g. asr stage 0.1.7 8
echo   asr test                      test the staged candidate
echo   asr publish VERSION SEQUENCE  publish the tested candidate to our server and GitHub
echo   asr upload VERSION SEQUENCE   retry only the GitHub upload of a published release
echo   asr server                    run the co-op and update server
echo   asr play                      open the game on this PC with co-op on our server
exit /b 1
