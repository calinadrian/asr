@echo off
setlocal
cd /d "%~dp0"
rem tools\python is a local Python 3.12 with cryptography; it is not part of the repository.
set "PY=tools\python\python.exe"
if not exist "%PY%" (echo Missing %PY%. Copy a Python 3.12 with the cryptography package there. & exit /b 1)
if /i "%~1"=="stage" if not "%~3"=="" ("%PY%" launcher\release.py --version "%~2" --sequence "%~3" --stage-only & exit /b)
if /i "%~1"=="test" ("%PY%" launcher\test_launcher.py & exit /b)
if /i "%~1"=="publish" if not "%~3"=="" ("%PY%" launcher\release.py --version "%~2" --sequence "%~3" --promote & exit /b)
if /i "%~1"=="upload" if not "%~3"=="" ("%PY%" launcher\release.py --version "%~2" --sequence "%~3" --upload & exit /b)
if /i "%~1"=="publish-game" if not "%~3"=="" ("%PY%" launcher\game_release.py --exe "%~2" --version "%~3" --notes "%~4" & exit /b)
if /i "%~1"=="publish-data" if not "%~2"=="" ("%PY%" launcher\game_release.py --data "%~2" & exit /b)
if /i "%~1"=="server"("%PY%" -u server\public_server.py serve & pause & exit /b)
if /i "%~1"=="play" ("%PY%" server\public_server.py play & exit /b)
echo Usage (in PowerShell, type .\asr instead of asr):
echo   asr server                    run the co-op and update server
echo   asr play                      open the game on this PC with co-op on our server
echo   asr publish-game EXE VERSION ["NOTES"]  send a game executable to every player
echo   asr publish-data DATA-FOLDER  send the game's data files (*.MPQ) to every player
echo   launcher\set_game_icon.ps1 -Exe EXE        put the ASR icon on a game executable before publishing it
echo.
echo Launcher releases normally publish themselves: change launcher\version.json and push.
echo   asr stage VERSION SEQUENCE    build and sign a launcher locally, e.g. asr stage 0.1.9 10
echo   asr test                      test the staged launcher
echo   asr publish VERSION SEQUENCE  publish the staged launcher from this PC instead
echo   asr upload VERSION SEQUENCE   retry only the GitHub upload of a published release
exit /b 1
