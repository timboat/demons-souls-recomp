@echo off
rem Packs your last play session (its frame-timing recording with your F8 marks, a summary, your PC's
rem specs and the end of the log) into one zip, shows it in Explorer and opens the GitHub "new issue"
rem page so you can attach it. Your Windows user name is removed from everything in the zip.
rem   REPORT.bat [perf\<date_time> folder]   (default: the newest recording)
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
if not exist ".venv\Scripts\python.exe" (
  echo Run SETUP.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\make_report.py %*
echo.
pause

:ds_unc_failed
echo This network folder could not be given a drive letter: "%~dp0"
echo Map the share to a drive letter (Explorer: This PC - Map network drive) and start from there,
echo or keep this folder on a local disk and only your disc image on the network.
if not defined DES_LAUNCHER pause
exit /b 1
