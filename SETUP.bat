@echo off
rem Demon's Souls (BLUS-30443) PC port -- one-click setup.
rem Drag your disc image (.iso, Redump .zip, or dumped disc folder) onto this file, or double-click
rem it and it will ask. It extracts the game, recompiles it and builds DemonsSoulsRecomp.exe.
rem Safe to run again: finished steps are skipped.
setlocal EnableExtensions
cd /d "%~dp0"
set "KIT=%CD%"
rem CMake treats [ ] in a path as a wildcard (its globs then find nothing) and cmd breaks on & in one:
rem stop here with a clear message instead of failing later.
set "DS_P=%CD%"
if not "%DS_P:[=%"=="%DS_P%" goto :bad_path
if not "%DS_P:]=%"=="%DS_P%" goto :bad_path
if not "%DS_P:&=%"=="%DS_P%" goto :bad_path
title Demon's Souls PC port - setup

rem Python 3.10+ and Git: the installed ones, else portable copies downloaded into deps\ (nothing is
rem installed). DS_TEST_NO_PYTHON=1 / DS_TEST_NO_GIT=1 (tests) act as if none were installed.
if not exist "deps" mkdir "deps"
set "PY="
if defined DS_TEST_NO_PYTHON goto :portable_python
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
)
:portable_python
if not defined PY if not exist "deps\python\tools\python.exe" call "%KIT%\setup\get_python.bat"
if not defined PY if exist "deps\python\tools\python.exe" set "PY=deps\python\tools\python.exe"
if not defined PY goto :need_python
if defined DS_TEST_NO_GIT goto :portable_git
where git >nul 2>nul && goto :have_git
:portable_git
if not exist "deps\mingit\cmd\git.exe" call :get_git
if not exist "deps\mingit\cmd\git.exe" goto :need_git
set "PATH=%CD%\deps\mingit\cmd;%PATH%"
:have_git

rem The Python that made .venv may have been removed or upgraded since ("No Python at ..."): make it again.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "" >nul 2>nul || (
    echo The Python that made .venv is no longer installed: making it again ...
    rmdir /s /q ".venv"
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment in .venv ...
  %PY% -m venv .venv || goto :failed
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r setup\requirements.txt || goto :failed
".venv\Scripts\python.exe" setup\setup.py %*
if errorlevel 1 goto :failed
echo.
pause
exit /b 0

:get_git
echo Git is not installed: downloading a portable one (Git for Windows' MinGit, 40 MB) into deps\mingit.
echo Nothing is installed.
pushd "%SystemRoot%"
set "DS_FETCH=%KIT%\setup\fetch.ps1"
set "DS_DEST=%KIT%\deps\mingit"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create([IO.File]::ReadAllText($env:DS_FETCH))) -Url 'https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.4/MinGit-2.56.0.4-64-bit.zip' -Sha256 e3bf78351fe777fba47ddee5950082f8a98bb0f02604fdc7ba3ee2cb68ffa877 -Dest $env:DS_DEST -Name 'MinGit 2.56.0.4'; exit $LASTEXITCODE"
popd
exit /b 0

:need_python
echo Python 3.10 or newer is needed and the portable one could not be downloaded
echo (https://www.python.org/downloads/ - tick "Add python.exe to PATH").
call :offer Python.Python.3.12
goto :reopen

:need_git
echo Git is needed and the portable one could not be downloaded (https://git-scm.com/download/win).
call :offer Git.Git
goto :reopen

:offer
where winget >nul 2>nul || exit /b 1
set "ANS="
set /p "ANS=Install it now with winget? [Y/n] "
if /i "%ANS%"=="n" exit /b 1
winget install -e --id %1 --accept-package-agreements --accept-source-agreements
exit /b %errorlevel%

:reopen
echo.
echo When it is installed, close this window and run SETUP.bat again.
pause
exit /b 1

:failed
echo.
echo Setup stopped. Fix the problem above and run SETUP.bat again - finished steps are skipped.
pause
exit /b 1

:bad_path
echo This folder's path has a [ ] or ^& in it, which the build tools cannot handle:
echo   "%CD%"
echo Move or rename the folder (for example C:\Games\DemonsSouls) and run this again.
pause
exit /b 1
