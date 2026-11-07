@echo off
rem SETUP.bat / BUILD.bat: no Python 3.10 or newer is installed, so download python.org's own portable
rem build (the NuGet package, checked against its SHA-256) into deps\python. Nothing is installed.
rem Afterwards deps\python\tools\python.exe exists, or the download failed (the caller says what to do).
setlocal
set "KIT=%~dp0.."
for %%K in ("%KIT%") do set "KIT=%%~fK"
if exist "%KIT%\deps\python\tools\python.exe" exit /b 0
if not exist "%KIT%\deps" mkdir "%KIT%\deps"
echo No Python 3.10 or newer is installed: downloading a portable one (python.org's own build, 15 MB) into
echo deps\python. Nothing is installed.
pushd "%SystemRoot%"
set "DS_FETCH=%KIT%\setup\fetch.ps1"
set "DS_DEST=%KIT%\deps\python"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create([IO.File]::ReadAllText($env:DS_FETCH))) -Url 'https://api.nuget.org/v3-flatcontainer/python/3.13.17/python.3.13.17.nupkg' -Sha256 dce409744b088f94c6e37ba41f8100c384c27e029e843237364c602d30d475e5 -Dest $env:DS_DEST -Name 'Python 3.13.17'; exit $LASTEXITCODE"
popd
exit /b 0
