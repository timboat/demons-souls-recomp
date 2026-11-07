#!/bin/sh
# Launches Demon's Souls (BLUS-30443, ps3recomp static recompilation) on Linux / Steam Deck: the
# Windows build linux/setup.sh (or the AppImage) made, run through Proton, whose vkd3d-proton turns the
# port's Direct3D 12 renderer into Vulkan. Same settings as PLAY.bat (read that for what each one does);
# this file only adds what Linux needs. docs/LINUX.md has the details and the list of open questions.
#
# Which Proton (DS_RUNNER picks one by hand: umu, proton or wine):
#   umu   -- umu-launcher (open source, runs Proton outside Steam and downloads UMU-Proton itself on the
#            first run). Used when "umu-run" is installed, or downloaded here on the first run.
#   proton -- PROTON=/path/to/a Proton folder (from Steam's steamapps/common, or GE-Proton).
#   wine  -- WINE=wine (needs a Wine with vkd3d-proton installed in the prefix; for testing).
# The Wine prefix (the game's own fake C: drive, with nothing of yours in it) is wineprefix/ here.
#
# Options: --ms-d3dcompiler  installs Microsoft's shader compiler (d3dcompiler_47.dll, downloaded from
#                            Microsoft by winetricks) into that prefix, for when Wine's own one fails on
#                            the game's shaders (black or missing geometry, "D3DCompile" errors in the log)
# Environment: DES_FPS=30|50|60|unlimited|31-240 (a Steam Deck defaults to 30), DES_MOVIES=0, DES_NAME,
#              DES_GAME, DES_BOSS_RUSH=1, DES_RECORD=0, DES_GOD=1 -- all as in PLAY.bat.
set -u
D=$(cd "$(dirname "$0")/.." && pwd)
cd "$D"
PY=${DS_PYTHON:-python3}
UMU_VERSION=1.4.4

die() { echo "$*"; exit 1; }
# a Linux path as the Windows program sees it (Wine maps / to drive Z:)
winpath() { printf 'Z:%s' "$1" | sed 's|/|\\|g'; }

EXE="$D/port/build_opt/DemonsSoulsRecomp.exe"
[ -f "$EXE" ] || die "DemonsSoulsRecomp.exe is not built yet. Run linux/setup.sh (or the AppImage) first."

# --- which Proton ------------------------------------------------------------------------------
PFX="$D/wineprefix"
mkdir -p "$PFX" "$D/logs"
find_umu() {
  command -v umu-run 2>/dev/null && return 0
  [ -f "$D/deps/umu/umu/umu-run" ] && { echo "$D/deps/umu/umu/umu-run"; return 0; }
  return 1
}
get_umu() {
  echo "To run the Windows build this uses Proton through umu-launcher (open source, GPL-3; it downloads"
  echo "UMU-Proton, about 400 MB, on its first run). Nothing of it is part of this kit."
  printf "Download umu-launcher %s from its GitHub releases now? [Y/n] " "$UMU_VERSION"
  read -r a || a=n
  case "$a" in [nN]*) return 1;; esac
  mkdir -p "$D/deps/umu"
  url="https://github.com/Open-Wine-Components/umu-launcher/releases/download/$UMU_VERSION/umu-launcher-$UMU_VERSION-zipapp.tar"
  "$PY" - "$url" "$D/deps/umu/umu.tar" <<'EOF' || return 1
import sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=120) as r, open(sys.argv[2], 'wb') as f:
    f.write(r.read())
EOF
  tar -xf "$D/deps/umu/umu.tar" -C "$D/deps/umu" && rm -f "$D/deps/umu/umu.tar"
  [ -f "$D/deps/umu/umu/umu-run" ]
}
RUNNER=${DS_RUNNER:-}
if [ -z "$RUNNER" ]; then
  if [ -n "${PROTON:-}" ]; then RUNNER=proton
  elif find_umu >/dev/null; then RUNNER=umu
  elif get_umu; then RUNNER=umu
  else die "No Proton to run the game with: install umu-launcher, or set PROTON=/path/to/Proton (docs/LINUX.md)."
  fi
fi
# run_win <exe> <args...>: one Windows program in the game's prefix
run_win() {
  case "$RUNNER" in
    umu)
      UMU=$(find_umu) || die "umu-run not found"
      # PROTONPATH (a Proton folder, or "GE-Proton") picks another Proton; the default is UMU-Proton
      WINEPREFIX="$PFX" GAMEID="${GAMEID:-umu-default}" "$PY" "$UMU" "$@" ;;
    proton)
      [ -x "${PROTON:-}/proton" ] || die "PROTON=$PROTON has no proton script"
      STEAM_COMPAT_DATA_PATH="$PFX" STEAM_COMPAT_CLIENT_INSTALL_PATH="${STEAM_COMPAT_CLIENT_INSTALL_PATH:-$HOME/.steam/steam}" \
        "$PROTON/proton" run "$@" ;;
    wine)
      WINEPREFIX="$PFX" "${WINE:-wine}" "$@" ;;
    *) die "DS_RUNNER=$RUNNER: use umu, proton or wine" ;;
  esac
}

# The first start downloads Proton (umu) and makes the prefix; do that here, where you can see it,
# rather than with the game's output going to the log files.
if [ "$RUNNER" = umu ] && [ ! -f "$PFX/.ds_ready" ]; then
  echo "Setting up Proton and the Wine prefix (first start only; downloads UMU-Proton)..."
  run_win "" && touch "$PFX/.ds_ready"
fi

if [ "${1:-}" = "--ms-d3dcompiler" ]; then
  echo "Installing Microsoft's d3dcompiler_47 into $PFX (winetricks downloads it from Microsoft)..."
  case "$RUNNER" in
    umu) run_win winetricks d3dcompiler_47 ;;
    *) WINEPREFIX="$PFX" winetricks d3dcompiler_47 ;;
  esac
  exit $?
fi

# --- the PLAY.bat settings ---------------------------------------------------------------------
export PS3_TITLE="Demon's Souls (ps3recomp)"
DES_GAME=${DES_GAME:-game}
[ "$DES_GAME" = game_remaster ] && PS3_TITLE="Demon's Souls (ps3recomp) - PC Remaster mod"
# DES_BOSS_RUSH=1: boss rush mode, as in PLAY.bat -- game_bossrush, made from game/ by tools/make_boss_rush.py
# (hard links), its own saves in bossrush/gamedata and the run timer's files in bossrush/.
if [ "${DES_BOSS_RUSH:-}" = 1 ]; then
  DES_GAME=game_bossrush
  PS3_TITLE="Demon's Souls (ps3recomp) - Boss rush"
  mkdir -p "$D/bossrush/gamedata"
  export DES_BOSS_RUSH=1 PS3_GAMEDATA_ROOT="$(winpath "$D/bossrush/gamedata")" DES_BOSS_RUSH_DIR="$(winpath "$D/bossrush")"
  BR_PY="$D/.venv/bin/python"
  [ -x "$BR_PY" ] || BR_PY=$PY
  "$BR_PY" "$D/tools/make_boss_rush.py" ||
    die "Boss rush: game_bossrush could not be made from your game files (the messages above say why)."
fi
[ -f "$D/$DES_GAME/PS3_GAME/USRDIR/EBOOT.elf" ] || die "No $DES_GAME/PS3_GAME/USRDIR/EBOOT.elf. Run linux/setup.sh first."
export PS3_HDD0_ROOT="$(winpath "$D/hdd0")"
export PS3_HDD1_ROOT="$(winpath "$D/hdd1")"
export RSX_LIVE_DRAW=1 GCM_NO_TITLE_RECYCLE=1 PS3_NP_STRICT_OFFLINE=1 SPU_INTERP_UNLIFTED=1 SPURS_JC_EVENTS=0
export PS3_DEV_FLASH="$(winpath "$D/no_flash")"
if [ "${DES_MOVIES:-}" = 0 ]; then export PS3_NO_SAIL=1; else unset PS3_NO_SAIL; fi
export PAD_KEYMAP=souls OSK_TEXT="${DES_NAME:-}" PAD_SCRIPT= PS3_PRIO_START=1 LD_PRESENT_PACE=0.85
if [ -f "$D/port/build_opt/no_avx2.txt" ]; then unset PS3_REQUIRE_AVX2; else export PS3_REQUIRE_AVX2=1; fi
export LD_F12_CAPTURE="$(winpath "$D/captures")"

# A Steam Deck (LCD "Jupiter", OLED "Galileo"): 4 Zen 2 cores hold 30 fps, not 60.
DECK=
case "$(cat /sys/class/dmi/id/board_vendor 2>/dev/null)/$(cat /sys/class/dmi/id/product_name 2>/dev/null)" in
  Valve/Jupiter|Valve/Galileo) DECK=1 ;;
esac
# Refresh rate of the active display (xrandr marks it with *); 60 when it cannot tell (gamescope).
REFRESH=$(xrandr --current 2>/dev/null | sed -n 's/.* \([0-9][0-9]*\)\.[0-9]*\*.*/\1/p' | head -n 1)
REFRESH=${REFRESH:-60}
# Auto, as PLAY.bat: 30 on a Steam Deck; 60 with DES_VRR=1 (G-Sync / FreeSync) or when the refresh (or the next
# whole Hz) is a multiple of 60; 50 on ~100 Hz; else the highest rate 45-75 the refresh is a whole multiple of
# (144 -> 72, 165 -> 55, 75 -> 75), every frame then shown the same number of refreshes; 60 when there is none.
auto_fps() {
  [ -n "$DECK" ] && { echo 30; return; }
  [ "${DES_VRR:-}" = 1 ] && { echo 60; return; }
  if [ $((REFRESH % 60)) -eq 0 ] || [ $(((REFRESH + 1) % 60)) -eq 0 ]; then echo 60; return; fi
  if [ "$REFRESH" -ge 95 ] && [ "$REFRESH" -le 105 ]; then echo 50; return; fi
  for R in "$REFRESH" $((REFRESH + 1)); do
    best=0
    for K in 1 2 3 4 5; do
      N=$((R / K))
      if [ $((R % K)) -eq 0 ] && [ "$N" -ge 45 ] && [ "$N" -le 75 ] && [ "$N" -gt "$best" ]; then best=$N; fi
    done
    [ "$best" -gt 0 ] && { echo "$best"; return; }
  done
  echo 60
}
if [ -z "${DES_FPS:-}" ]; then DES_FPS=$(auto_fps); fi
FPS_NOTE=
case "$DES_FPS" in
  30) ;;
  60) export DES_60FPS=1 PS3_VBLANK_HZ=120 PS3_CLOCK_SCALE=200 ;;
  50) export DES_60FPS=1 PS3_VBLANK_HZ=100 PS3_CLOCK_SCALE=167 LD_PRESENT_INTERVAL=2 LD_PRESENT_PACE=0 ;;
  unlimited) export DES_60FPS=1 PS3_VBLANK_HZ=480 PS3_CLOCK_SCALE=200 DES_MAX_FPS=240 LD_PRESENT_INTERVAL=0 LD_PRESENT_PACE=0 ;;
  *)
    case "$DES_FPS" in *[!0-9]*|'') N=0 ;; *) N=$DES_FPS ;; esac
    if [ "$N" -lt 31 ] || [ "$N" -gt 240 ]; then
      die "DES_FPS=$DES_FPS is not a frame rate this port can run: use 30, 50, 60, unlimited, or 31-240."
    fi
    S=$(( (N * 100 + 15) / 30 )); [ "$S" -gt 200 ] && S=200
    export DES_60FPS=1 PS3_VBLANK_HZ=$((N * 2)) PS3_CLOCK_SCALE=$S LD_PRESENT_PACE=0 LD_PRESENT_INTERVAL=0
    [ "$N" -gt 60 ] && export DES_MAX_FPS=$N
    FPS_NOTE=" (vsync off: $REFRESH Hz is not a multiple of $N)"
    for R in "$REFRESH" $((REFRESH + 1)); do
      if [ $((R % N)) -eq 0 ]; then
        export LD_PRESENT_INTERVAL=$((R / N))
        FPS_NOTE=" (vsync on: every frame shown $((R / N)) of your monitor's $REFRESH Hz refreshes)"
      fi
    done ;;
esac
# DES_VRR=1 (G-Sync / FreeSync screen): vsync-off presents may tear, so a variable-refresh monitor shows every
# frame when it is ready; 60 fps then runs vsync off too. Not for other screens: without VRR it tears.
if [ "${DES_VRR:-}" = 1 ]; then
  export LD_ALLOW_TEARING=1
  [ "$DES_FPS" = 60 ] && export LD_PRESENT_INTERVAL=0
  FPS_NOTE="$FPS_NOTE (G-Sync / FreeSync)"
fi
echo "Running at $DES_FPS fps$FPS_NOTE."

# Frame-timing recording, as in PLAY.bat: F8 in the game marks a stutter; perf/<date_time>/perf.txt.
if [ "${DES_RECORD:-}" != 0 ]; then
  PD="$D/perf/$(date +%Y-%m-%d_%H-%M-%S)"
  mkdir -p "$PD"
  ls -1d "$D"/perf/*/ 2>/dev/null | sort -r | tail -n +11 | while read -r old; do rm -rf "$old"; done
  export DES_PERF=1 LD_PRESENT_LOG="$(winpath "$PD/perf.txt")" LD_PRESENT_LOG_FROM=0 LD_PRESENT_LOG_SECS=0
  export DES_PERF_STACKS="${DES_PERF_STACKS:-1}" DES_PERF_STACK_THREADS="${DES_PERF_STACK_THREADS:-HighGraphics}"
  echo "Recording frame timing: press F8 in the game right after any stutter you see."
fi

# A killed run can leave truncated files in the HDD1 cache that the next run trusts.
rm -rf "$D/hdd1/cache"
for f in out err; do
  [ -f "$D/logs/last_run_$f.txt" ] && mv -f "$D/logs/last_run_$f.txt" "$D/logs/last_run_${f}_prev.txt"
done
echo "Starting Demon's Souls through $RUNNER (the logos and loading take about a minute)..."
EBOOT="$D/$DES_GAME/PS3_GAME/USRDIR/EBOOT.elf"
OUT="$D/logs/last_run_out.txt" ERR="$D/logs/last_run_err.txt"
# Under Proton the game gets a console window of its own, and its log (hundreds of thousands of lines
# a session) goes there instead of to the files: unreadable, and slow to draw. So a batch file starts
# it and redirects its output on the Windows side, as PLAY.bat does; Proton's own output goes to
# logs/last_run_proton.txt. DS_RUN_DIRECT=1 starts the exe directly instead (log in that window).
# Batch files read paths in the OEM code page, so a non-ASCII folder also starts it directly.
batq() { printf '"%s"' "$(winpath "$1" | sed 's/%/%%/g')"; }   # in a .bat, "..." is literal except %
if [ "${DS_RUN_DIRECT:-}" != 1 ] && ! printf '%s' "$D" | LC_ALL=C grep -q '[^ -~]'; then
  BAT="$D/logs/run_game.bat"
  printf '@%s %s > %s 2> %s\r\n@exit /b %%ERRORLEVEL%%\r\n' \
    "$(batq "$EXE")" "$(batq "$EBOOT")" "$(batq "$OUT")" "$(batq "$ERR")" > "$BAT"
  CMD=cmd
  [ -f "$PFX/drive_c/windows/system32/cmd.exe" ] && CMD="$PFX/drive_c/windows/system32/cmd.exe"
  [ -f "$PFX/pfx/drive_c/windows/system32/cmd.exe" ] && CMD="$PFX/pfx/drive_c/windows/system32/cmd.exe"
  echo "Game log: logs/last_run_err.txt (an empty console window opens with the game; leave it open)."
  run_win "$CMD" /c "$(winpath "$BAT")" > "$D/logs/last_run_proton.txt" 2>&1
else
  run_win "$EXE" "$(winpath "$EBOOT")" > "$OUT" 2> "$ERR"
fi
CODE=$?
if [ "$CODE" != 0 ]; then
  echo
  echo "Demon's Souls exited with code $CODE. The logs are in logs/last_run_*.txt."
  echo "Please report what happened on GitHub (docs/LINUX.md says what helps)."
fi
exit "$CODE"
