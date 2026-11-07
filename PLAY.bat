@echo off
rem Launches the native PC build of Demon's Souls (BLUS-30443, ps3recomp static recompilation).
rem Run SETUP.bat once first. Game files: game\   Saves: gamedata\dev_hdd0\home\00000001\savedata
rem
rem Controls: an Xbox (XInput) controller is used when one is plugged in (A = Cross, B = Circle, X = Square,
rem Y = Triangle, LB/RB = L1/R1, LT/RT = L2/R2, Back = Select). A DualShock/DualSense needs Steam Input or
rem DS4Windows to show up as an Xbox pad. Without a controller, keyboard + mouse:
rem   WASD move   mouse camera (IJKL also)   LMB attack (R1)   Shift strong attack (R2)
rem   RMB block (L1)   Ctrl parry (L2)   Space roll/dash/back (Circle)   E interact/confirm (Cross)
rem   F two-hand (Triangle)   R use item (Square)   Tab or middle mouse lock on (R3)   C (L3)
rem   arrows d-pad (switch items)   Enter Start   Backspace Select   F1 capture/release the mouse
rem Keys only count while the game window is in front. At Create Profile a text box opens for the
rem character name: type it, Enter = OK, Esc = Cancel (the game ignores keys while it is open).
rem "set DES_NAME=<name>" before launching skips the box and uses that name.
rem God mode (fix 44): F9 in the game window turns it on / off (the window title says [GOD MODE - F9]):
rem you cannot die and HP, MP and stamina stay full. "set DES_GOD=1" before launching starts with it on.
rem
rem Every run is logged to logs\last_run_out.txt / last_run_err.txt (previous run kept as *_prev.txt).
rem They grow by roughly 600 MB an hour. Attach the end of last_run_err.txt when you report a crash.
rem Runs at up to 60 fps by default (docs\NOTES.md fix 28), 50 on a 100 Hz monitor (fix 42);
rem set DES_FPS=30 for the original 30, or any whole number 31-240 (the launcher's Custom... asks).
rem Frame timing is recorded on every run: press F8 in the game right after a stutter, then run
rem REPORT.bat to pack it up for a GitHub issue (see README.md).
rem Where the PC cannot hold 60 (Boletarian Palace: ~58 since fix 36) the game step stretches to match,
rem so the game still runs at real speed instead of in slow motion (fix 33; DES_ADAPTIVE_STEP=0 = fixed 1/60).
rem Sound and music work (fix 29). Known gaps: intro movies are skipped.
rem Uses the build SETUP.bat / BUILD.bat make (port\build_opt).
rem DemonsSoulsLauncher.exe runs this file with the choices from its window as these variables;
rem DES_LAUNCHER=1 (set by it) skips the pauses: the launcher reports errors itself.
setlocal
set "D=%~dp0"
if "%D:~-1%"=="\" set "D=%D:~0,-1%"
set "PS3_TITLE=Demon's Souls (ps3recomp)"
rem DES_GAME=<folder next to this file> picks the game files (default "game"); the PC Remaster mod copy
rem is "game_remaster" (the launcher's Game: PC Remaster mod, NOTES fix 45), your imported models
rem "game_mod" (Game: My models). Saves are shared.
if "%DES_GAME%"=="" set "DES_GAME=game"
if /i "%DES_GAME%"=="game_remaster" set "PS3_TITLE=Demon's Souls (ps3recomp) - PC Remaster mod"
set "PS3_HDD0_ROOT=%D%\hdd0"
set "PS3_HDD1_ROOT=%D%\hdd1"
set "RSX_LIVE_DRAW=1"
set "GCM_NO_TITLE_RECYCLE=1"
set "PS3_NP_STRICT_OFFLINE=1"
set "SPU_INTERP_UNLIFTED=1"
set "PS3_DEV_FLASH=%D%\no_flash"
set "SPURS_JC_EVENTS=0"
rem Movies play (title logo, intro, story, endings -- NOTES fix 71). "set DES_MOVIES=0" before
rem launching skips them, as before.
if "%DES_MOVIES%"=="0" (set "PS3_NO_SAIL=1") else (set "PS3_NO_SAIL=")
set "PAD_KEYMAP=souls"
set "OSK_TEXT=%DES_NAME%"
set "PAD_SCRIPT="
rem Sound: threads start in PS3 priority order. Without it the audio notify queue (created by a
rem higher-priority thread) is read before it exists and the game stays silent (NOTES fix 29).
set "PS3_PRIO_START=1"
rem Even frame pacing (fix 37): when the game falls behind it renders two frames back to back;
rem this spaces their presents out instead of showing them a millisecond apart (judder).
set "LD_PRESENT_PACE=0.85"
rem The SPU code is built for AVX2 when the building CPU has it (fix 36); then a CPU without it
rem stops with a message box instead of crashing. BUILD.bat leaves no_avx2.txt for a build without.
set "PS3_REQUIRE_AVX2="
if not exist "%D%\port\build_opt\no_avx2.txt" set "PS3_REQUIRE_AVX2=1"
rem F12 while the game window is in front records that frame for debugging (every draw as an
rem image + the draw log) into captures\f<frame>. About 1 GB and a few seconds per press.
set "LD_F12_CAPTURE=%D%\captures"
rem 60 fps mode (default): the game steps a fixed 1/30 s per frame and its frame loop takes two
rem vblanks, so 60 fps = a 1/60 s step (DES_60FPS) + 120 Hz vblanks + guest clock at 200% (so the
rem game's own frame skip still keeps the speed right when a frame runs long) -- the same recipe
rem as RPCS3's 60 FPS patch. "set DES_FPS=30" before launching gives the original 30 fps.
rem 50 fps mode (NOTES fix 42): on a ~100 Hz monitor 60 fps cannot be even (frames stay up 1, 2 or 3
rem refreshes -- judder when the camera turns), so there the default is 50 fps with every frame shown for
rem exactly 2 refreshes: 100 Hz vblanks, guest clock 167%, present on every 2nd refresh. The adaptive step
rem keeps game speed right. "set DES_FPS=60" (or 30 / 50) before launching picks the mode by hand
rem ("set DES_FPS=unlimited" = uncapped, a number 31-240 = custom). The launcher's frame rate choice
rem just sets DES_FPS and calls this file.
set "DES_REFRESH="
for /f %%R in ('powershell -NoProfile -Command "(Get-CimInstance Win32_VideoController | Where-Object CurrentRefreshRate | Select-Object -First 1).CurrentRefreshRate"') do set "DES_REFRESH=%%R"
if "%DES_REFRESH%"=="" set "DES_REFRESH=60"
rem Auto (DES_FPS unset): an even rate for this screen (:auto_fps below): 60 on 60 / 120 / 240 Hz, 50 on
rem 100 Hz, 72 on 144 Hz, 55 on 165 Hz, 75 on 75 Hz; with DES_VRR=1 (G-Sync / FreeSync) always 60.
if "%DES_FPS%"=="" call :auto_fps
if "%DES_FPS%"=="60" (
  set "DES_60FPS=1"
  set "PS3_VBLANK_HZ=120"
  set "PS3_CLOCK_SCALE=200"
)
if "%DES_FPS%"=="50" (
  set "DES_60FPS=1"
  set "PS3_VBLANK_HZ=100"
  set "PS3_CLOCK_SCALE=167"
  set "LD_PRESENT_INTERVAL=2"
  set "LD_PRESENT_PACE=0"
)
rem Uncapped (fix 43): 480 Hz vblanks (game loop up to 240 fps), shortest step 1/240 s so the adaptive
rem step keeps real speed, no vsync. Boletarian Palace ~68 fps; frames are not evenly paced.
if "%DES_FPS%"=="unlimited" (
  set "DES_60FPS=1"
  set "PS3_VBLANK_HZ=480"
  set "PS3_CLOCK_SCALE=200"
  set "DES_MAX_FPS=240"
  set "LD_PRESENT_INTERVAL=0"
  set "LD_PRESENT_PACE=0"
)
set "FPS_NOTE="
set "DES_CUSTOM=1"
for %%F in (30 50 60 unlimited) do if /i "%DES_FPS%"=="%%F" set "DES_CUSTOM="
if defined DES_CUSTOM call :custom_fps || exit /b 1
rem DES_VRR=1 (the launcher's "G-Sync / FreeSync screen" box): vsync-off presents may tear (LD_ALLOW_TEARING),
rem which is what lets a variable-refresh monitor show every frame the moment it is ready, at any refresh
rem rate; 60 fps then runs vsync off too. Not for other screens: without VRR it tears.
if "%DES_VRR%"=="1" (
  set "LD_ALLOW_TEARING=1"
  if "%DES_FPS%"=="60" set "LD_PRESENT_INTERVAL=0"
  set "FPS_NOTE=%FPS_NOTE% (G-Sync / FreeSync)"
)
echo Running at %DES_FPS% fps%FPS_NOTE%.
rem Frame-timing recording (NOTES fix 46), on for every run (~25 MB an hour, no visible cost): press
rem F8 in the game window right after you see a stutter -- the window title counts the marks. Saved to
rem perf\<date_time>\perf.txt; REPORT.bat packs the newest one (+ a short summary, your PC's specs and
rem the end of the log) into a zip to attach to a GitHub issue. Only the newest 10 recordings are
rem kept. "set DES_RECORD=0" before launching turns recording off.
set "PD="
if "%DES_RECORD%"=="0" goto :no_record
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set "TS=%%T"
set "PD=%D%\perf\%TS%"
if not exist "%PD%" mkdir "%PD%"
for /f "skip=10 delims=" %%P in ('dir /b /ad /o-n "%D%\perf" 2^>nul') do rmdir /s /q "%D%\perf\%%P"
set "DES_PERF=1"
set "LD_PRESENT_LOG=%PD%\perf.txt"
set "LD_PRESENT_LOG_FROM=0"
set "LD_PRESENT_LOG_SECS=0"
rem When a game step runs 28 ms or more, a few stack samples of the main thread and HighGraphics go in the
rem recording too, so a freeze says what the game was doing (docs/NOTES.md fix 59). Costs nothing otherwise.
if not defined DES_PERF_STACKS set "DES_PERF_STACKS=1"
if not defined DES_PERF_STACK_THREADS set "DES_PERF_STACK_THREADS=HighGraphics"
echo Recording frame timing: press F8 in the game right after any stutter you see.
:no_record
set "EXE=%D%\port\build_opt\DemonsSoulsRecomp.exe"
if not exist "%EXE%" (
  echo DemonsSoulsRecomp.exe is not built yet. Run SETUP.bat first.
  if not defined DES_LAUNCHER pause
  exit /b 1
)
rem After an update (git pull, or a new ZIP unpacked over this folder) the game has to be rebuilt:
rem BUILD.bat re-applies the patches that changed and recompiles. Until then this would run the OLD
rem exe with the NEW settings -- e.g. movies on with an exe that cannot play them stays on a black
rem screen (GitHub #4). A successful full build leaves a copy of the patches it was made from in
rem port\build_opt\built (setup/build.py); when the folder's patches differ from those (or a build from
rem before 2026-11-03 left none, or a rebuild failed or was stopped) the game was not rebuilt: build it
rem now, then play. Only then -- an up-to-date folder starts straight away.
rem (gotos, not ( ) blocks: a ")" in the folder's path would end a block.)
rem DES_NO_REBUILD=1 ("Keep my build after updates" in the launcher) plays the build there is instead, and a
rem rebuild that does not finish asks whether to play it anyway.
call :stale
if not defined STALE goto play
if "%DES_NO_REBUILD%"=="1" goto stale_keep
if defined DES_LAUNCHER goto stale_launcher
echo.
echo This folder was updated: rebuilding the game first with BUILD.bat (a few minutes; only what
echo changed is recompiled). The old build may not work with the new files.
echo.
call "%D%\BUILD.bat"
if errorlevel 1 goto build_failed
goto play
:stale_launcher
rem The launcher runs this file without a window: rebuild in a window of its own and wait for it (the
rem launcher keeps Play greyed out meanwhile), then start the game if the build is now current. The
rem window closes by itself when the build works; when it fails it asks whether to play the build there is
rem anyway (setup\rebuild_window.bat leaves logs\play_old_build.flag for a yes).
if exist "%D%\logs\play_old_build.flag" del "%D%\logs\play_old_build.flag"
start "Demon's Souls - rebuilding after the update" /wait /d "%D%" cmd /c call "%D%\setup\rebuild_window.bat"
call :stale
if not defined STALE goto play
if not exist "%D%\logs\play_old_build.flag" exit /b 1
del "%D%\logs\play_old_build.flag"
goto play
:stale_keep
echo.
echo This folder was updated, but DES_NO_REBUILD=1 ("Keep my build after updates" in the launcher): playing
echo the build you already have. Its fixes are from before the update; run BUILD.bat to get the new ones.
echo.
goto play
:build_failed
echo.
echo BUILD.bat did not finish. If it asks for SETUP.bat, run SETUP.bat: it keeps your game files.
echo The build you already have is still there, but it was made before this update.
choice /c YN /m "Play the build you already have anyway"
if errorlevel 2 exit /b 1
goto play
:play
rem A game from an earlier Play can still be running (stuck on a black screen, or its window gone): a second one
rem cannot start next to it (its recording and save files are taken), so nothing seemed to happen. Ask whether to
rem close it -- in a message box when the launcher runs this without a window.
tasklist /FI "IMAGENAME eq DemonsSoulsRecomp.exe" /NH 2>nul | findstr /i /c:"DemonsSoulsRecomp.exe" >nul || goto not_running
if defined DES_LAUNCHER goto running_box
echo.
echo Demon's Souls is still running from an earlier start (maybe stuck on a black screen), and a second
echo copy cannot start next to it.
choice /c YN /m "Close the running one and start again"
if errorlevel 2 exit /b 1
goto close_running
:running_box
powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $m = 'Demon''s Souls is still running from an earlier start (maybe stuck on a black screen), and a second copy cannot start next to it.' + [char]10 + [char]10 + 'Close the running one and start again?'; exit [int]([System.Windows.Forms.MessageBox]::Show($m, 'Demon''s Souls', 'YesNo', 'Warning') -eq 'Yes')"
if not errorlevel 1 exit /b 1
:close_running
taskkill /F /IM DemonsSoulsRecomp.exe >nul 2>&1
rem wait until it is gone (up to ~10 s) before its cache and logs are touched
for /l %%i in (1,1,10) do (
  tasklist /FI "IMAGENAME eq DemonsSoulsRecomp.exe" /NH 2>nul | findstr /i /c:"DemonsSoulsRecomp.exe" >nul || goto not_running
  ping -n 2 127.0.0.1 >nul
)
:not_running
rem (again: a rebuild may have switched between the AVX2 and the plain build)
set "PS3_REQUIRE_AVX2="
if not exist "%D%\port\build_opt\no_avx2.txt" set "PS3_REQUIRE_AVX2=1"
rem A killed run can leave truncated files in the HDD1 cache that the next run trusts.
if exist "%D%\hdd1\cache" rmdir /s /q "%D%\hdd1\cache"
if not exist "%D%\logs" mkdir "%D%\logs"
if exist "%D%\logs\last_run_out.txt" move /y "%D%\logs\last_run_out.txt" "%D%\logs\last_run_out_prev.txt" >nul
if exist "%D%\logs\last_run_err.txt" move /y "%D%\logs\last_run_err.txt" "%D%\logs\last_run_err_prev.txt" >nul
echo Starting Demon's Souls (the logos and loading take about a minute)...
cd /d "%D%"
"%EXE%" "%D%\%DES_GAME%\PS3_GAME\USRDIR\EBOOT.elf" > "%D%\logs\last_run_out.txt" 2> "%D%\logs\last_run_err.txt"
set "CODE=%errorlevel%"
if not "%CODE%"=="0" (
  echo.
  echo Demon's Souls exited with code %CODE%. The logs are in logs\last_run_*.txt.
  echo To report the crash, run REPORT.bat and attach the zip it makes to a GitHub issue.
  if not defined DES_LAUNCHER pause
)
exit /b %CODE%

rem Custom frame rate N (31-240): 2 vblanks per game frame, guest clock N/30 (at most 200%, as the
rem 60 fps and uncapped modes), shortest adaptive step 1/N above 60. When the monitor's refresh is a
rem whole multiple of N every frame stays up the same number of refreshes (vsync, even pacing);
rem otherwise vsync is off, which is smooth on a G-Sync / FreeSync screen and may tear on others.
rem STALE=1 when patches\ differs from what the last successful build used (see :play above).
:stale
set "STALE="
for %%P in (ps3recomp-local.patch lifted-code.patch) do (
  if not exist "%D%\port\build_opt\built\%%P" set "STALE=1"
  fc /b "%D%\patches\%%P" "%D%\port\build_opt\built\%%P" >nul 2>&1 || set "STALE=1"
)
exit /b 0

:auto_fps
set "DES_FPS=60"
if "%DES_VRR%"=="1" exit /b 0
set /a "R1=DES_REFRESH+1, M0=DES_REFRESH %% 60, M1=R1 %% 60"
if %M0% EQU 0 exit /b 0
if %M1% EQU 0 exit /b 0
if %DES_REFRESH% GEQ 95 if %DES_REFRESH% LEQ 105 (set "DES_FPS=50" & exit /b 0)
set "AUTO_BEST=0"
for %%K in (1 2 3 4 5) do call :auto_try %%K %DES_REFRESH%
if %AUTO_BEST% EQU 0 for %%K in (1 2 3 4 5) do call :auto_try %%K %R1%
if %AUTO_BEST% GTR 0 set "DES_FPS=%AUTO_BEST%"
exit /b 0
rem :auto_try <k> <refresh>: refresh / k when it divides evenly into 45-75 fps and beats the best so far.
:auto_try
set /a "AT_M=%2 %% %1, AT_N=%2 / %1"
if not %AT_M%==0 exit /b 0
if %AT_N% LSS 45 exit /b 0
if %AT_N% GTR 75 exit /b 0
if %AT_N% GTR %AUTO_BEST% set "AUTO_BEST=%AT_N%"
exit /b 0

:custom_fps
set "N="
set /a "N=%DES_FPS%" 2>nul
if not "%N%"=="%DES_FPS%" goto :bad_fps
if %N% LSS 31 goto :bad_fps
if %N% GTR 240 goto :bad_fps
set "DES_60FPS=1"
set /a "PS3_VBLANK_HZ=N*2"
set /a "PS3_CLOCK_SCALE=(N*100+15)/30"
if %PS3_CLOCK_SCALE% GTR 200 set "PS3_CLOCK_SCALE=200"
if %N% GTR 60 set "DES_MAX_FPS=%N%"
set "LD_PRESENT_PACE=0"
set "LD_PRESENT_INTERVAL=0"
set "FPS_NOTE= (vsync off: %DES_REFRESH% Hz is not a multiple of %N%)"
rem Windows reports fractional refresh rates rounded down (99.98 Hz -> 99), so try one higher too.
set /a "K=DES_REFRESH/N, RMD=DES_REFRESH %% N, K2=(DES_REFRESH+1)/N, RMD2=(DES_REFRESH+1) %% N"
if %K2% GEQ 1 if %RMD2% EQU 0 set "LD_PRESENT_INTERVAL=%K2%"
if %K% GEQ 1 if %RMD% EQU 0 set "LD_PRESENT_INTERVAL=%K%"
if not "%LD_PRESENT_INTERVAL%"=="0" set "K=%LD_PRESENT_INTERVAL%"
if not "%LD_PRESENT_INTERVAL%"=="0" set "FPS_NOTE= (vsync on: every frame shown %K% of your monitor's %DES_REFRESH% Hz refreshes)"
exit /b 0
:bad_fps
echo DES_FPS=%DES_FPS% is not a frame rate this port can run: use 30, 50, 60, unlimited, or a whole
echo number from 31 to 240.
if not defined DES_LAUNCHER pause
exit /b 1
