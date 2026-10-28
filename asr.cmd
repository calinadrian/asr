@echo off
setlocal
cd /d "%~dp0"
rem tools\python is a local Python 3.12 with cryptography; it is not part of the repository.
set "PY=tools\python\python.exe"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%PY%" (echo Missing %PY%. Copy a Python 3.12 with the cryptography package there. & exit /b 1)
if /i "%~1"=="server" goto server
if /i "%~1"=="play" goto play
if /i "%~1"=="setup" goto setup
if /i "%~1"=="publish-game" if not "%~3"=="" goto publish_game
if /i "%~1"=="publish-zone-photos" goto publish_zone_photos
if /i "%~1"=="publish-lighting" if not "%~2"=="" goto publish_lighting
if /i "%~1"=="publish-durotar" if not "%~3"=="" goto publish_durotar
if /i "%~1"=="publish-addons" goto publish_addons
if /i "%~1"=="publish-data" if not "%~2"=="" goto publish_data
if /i "%~1"=="stage" if not "%~3"=="" goto stage
if /i "%~1"=="test" goto test
if /i "%~1"=="publish" if not "%~3"=="" goto publish
if /i "%~1"=="upload" if not "%~3"=="" goto upload
echo Usage (in PowerShell, type .\asr instead of asr):
echo   asr server                    run the co-op server
echo   asr play                      open the game on this PC with co-op on our server
echo   asr setup                     build downloads\ASR-Setup.exe, the installer players download
echo   asr publish-game EXE VERSION ["NOTES"]  send a game executable to every player
echo   asr publish-zone-photos       update zone photos without republishing other data
echo   asr publish-lighting DATA-FOLDER  update the brighter zone lighting without republishing other data
echo   asr publish-durotar VANILLA-DATA DATA-FOLDER  add Durotar's assets without republishing other data
echo   asr publish-addons            put ASR's addons (launcher\addon) on the release as zips
echo   asr publish-data DATA-FOLDER  send the game's data files (*.MPQ) to every player
echo   launcher\set_game_icon.ps1 -Exe EXE        put the ASR icon on a game executable before publishing it
echo.
echo Old launchers (ASR.exe 0.1.8 and earlier):
echo   asr stage VERSION SEQUENCE    build and sign a launcher locally
echo   asr test                      test the staged launcher
echo   asr publish VERSION SEQUENCE  publish the staged launcher
echo   asr upload VERSION SEQUENCE   retry only the GitHub upload of a published launcher
exit /b 1

:server
"%PY%" -u server\public_server.py serve
pause
exit /b
:play
"%PY%" server\public_server.py play
exit /b
:setup
"%CSC%" /nologo /target:winexe /optimize+ /out:downloads\ASR-Setup.exe /win32icon:launcher\asr.ico /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll launcher\Setup.cs launcher\Relay.cs launcher\AddonStore.cs launcher\AddonManager.cs launcher\GameUi.cs || exit /b 1
echo Built downloads\ASR-Setup.exe
exit /b
:publish_game
"%PY%" launcher\game_release.py --exe "%~2" --version "%~3" --notes "%~4"
exit /b
:publish_zone_photos
"%PY%" launcher\game_release.py --zone-photos
exit /b
:publish_lighting
"%PY%" launcher\game_release.py --lighting --data "%~2"
exit /b
:publish_durotar
"%PY%" launcher\game_release.py --durotar "%~2" --data "%~3"
exit /b
:publish_addons
"%PY%" launcher\game_release.py --addons
exit /b
:publish_data
"%PY%" launcher\game_release.py --data "%~2"
exit /b
:stage
"%PY%" launcher\release.py --version "%~2" --sequence "%~3" --stage-only
exit /b
:test
"%PY%" launcher\test_launcher.py
exit /b
:publish
"%PY%" launcher\release.py --version "%~2" --sequence "%~3" --promote
exit /b
:upload
"%PY%" launcher\release.py --version "%~2" --sequence "%~3" --upload
exit /b
