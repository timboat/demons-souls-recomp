@echo off
rem Rebuilds DemonsSoulsRecomp.exe after you change code (incremental; SETUP.bat must have run once).
rem   BUILD.bat [--jobs N] [ninja targets...]
setlocal
rem In a network folder (\\server\share\..., GitHub #45) cmd cannot cd: pushd gives the share a drive
rem letter while this window is open, and this file runs again from there.
if not "%~d0"=="\\" goto :ds_local
pushd "%~dp0" || goto :ds_unc_failed
call "%CD%\%~nx0" %*
set "DS_RC=%errorlevel%"
popd
exit /b %DS_RC%
:ds_local
cd /d "%~dp0"
rem CMake treats [ ] in a path as a wildcard (its globs then find nothing) and cmd breaks on & in one:
rem stop here with a clear message instead of failing later.
set "DS_P=%CD%"
if not "%DS_P:[=%"=="%DS_P%" goto :bad_path
if not "%DS_P:]=%"=="%DS_P%" goto :bad_path
if not "%DS_P:&=%"=="%DS_P%" goto :bad_path
if not exist ".venv\Scripts\python.exe" (
  echo Run SETUP.bat first.
  pause
  exit /b 1
)
rem Git from SETUP.bat's portable copy when it fetched one (updates re-apply patches with git apply).
if exist "deps\mingit\cmd\git.exe" set "PATH=%CD%\deps\mingit\cmd;%PATH%"
rem The Python that made .venv may have been removed or upgraded since ("No Python at ..."): then make
rem .venv again with the Python installed now.
".venv\Scripts\python.exe" -c "" >nul 2>nul || call :remake_venv || exit /b 1
".venv\Scripts\python.exe" setup\build.py %*
exit /b %errorlevel%

:remake_venv
echo The Python that SETUP.bat used is no longer installed: making the Python environment again ...
set "PY="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
)
rem Neither (Python was uninstalled after SETUP): the same portable one SETUP.bat downloads.
if not defined PY if not exist "deps\python\tools\python.exe" call "%CD%\setup\get_python.bat"
if not defined PY if exist "deps\python\tools\python.exe" set "PY=deps\python\tools\python.exe"
if not defined PY goto :no_python
rmdir /s /q ".venv"
%PY% -m venv .venv || goto :venv_failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r setup\requirements.txt || goto :venv_failed
exit /b 0
:no_python
echo Python 3.10 or newer is needed and the portable one could not be downloaded
echo (https://www.python.org/downloads/ - tick "Add python.exe to PATH"), then run this again.
pause
exit /b 1
:venv_failed
echo Making the Python environment failed: run SETUP.bat.
pause
exit /b 1

:bad_path
echo This folder's path has a [ ] or ^& in it, which the build tools cannot handle:
echo   "%CD%"
echo Move or rename the folder (for example C:\Games\DemonsSouls) and run this again.
pause
exit /b 1

:ds_unc_failed
echo This network folder could not be given a drive letter: "%~dp0"
echo Map the share to a drive letter (Explorer: This PC - Map network drive) and start from there,
echo or keep this folder on a local disk and only your disc image on the network.
if not defined DES_LAUNCHER pause
exit /b 1
