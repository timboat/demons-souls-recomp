#!/bin/bash
# Launches Demon's Souls (BLUS-30443, ps3recomp static recompilation) natively on Linux: the x86-64 build in
# port/build_linux (linux/native/build.sh), drawn by ps3recomp's Vulkan backend. No Wine, no Proton, no
# D3D12. Same game settings as linux/play.sh / PLAY.bat otherwise. On SteamOS the build lives in a distrobox
# container (port/build_linux/.distrobox names it) and the game runs inside it.
#
# Input: a controller (DualSense, DualShock 4, Xbox, the Steam Deck's own) through SDL; keyboard + mouse
# (PAD_KEYMAP=souls, the Windows layout) in the game's window.
#
# Settings (environment):
#   DES_NAME=<name>      the character name the game's on-screen keyboard gets (default "Slayer")
#   DES_FPS=60|30|unlimited   the frame rate (default 60: the port's 60 fps patch with 120 Hz vblanks and the
#                        guest clock at 200 %; 30 = the console's own rate; unlimited = as fast as it runs,
#                        still held to the screen's refresh by vsync)
#   DES_FULLSCREEN=0|1   borderless full screen (default: 1 on a Steam Deck, 0 elsewhere; F11 toggles it)
#   DES_MOVIES=0|1       the movies, decoded by the system's FFmpeg (libavcodec) at run time: on when the build
#                        found FFmpeg's headers; 0 skips them
#   DES_GAME=game_remaster   run the PC Remaster mod's copy instead of game/
#   DES_BOSS_RUSH=1      boss rush mode (as in PLAY.bat); DES_BR_SOULS=2|3|5|10 multiplies the souls
#   DES_GOD=1            no damage (testing)
#   DES_LOG=1            the runtime's per-event log lines (PS3_VERBOSE=1); off by default, they cost frames
#   DES_GPU_CLOCK=<MHz>|auto   Steam Deck only: pin the GPU clock for the session (default 800; see
#                        linux/play.sh, the same helper and the same reason)
#   DES_EXE=<path>       run another build of DemonsSoulsRecomp (A/B tests)
#   DES_LOG_DIR=<dir>    where last_run_out.txt / last_run_err.txt go (default logs/)
set -u
D=$(cd "$(dirname "$0")/../.." && pwd)
cd "$D"
die() { echo "error: $*" >&2; exit 1; }

BUILD=$D/port/build_linux
BIN=${DES_EXE:-$BUILD/DemonsSoulsRecomp}
[ -x "$BIN" ] || die "the native Linux build is not there yet ($BIN). Build it first: linux/native/build.sh"

DECK=
case "$(cat /sys/class/dmi/id/board_vendor 2>/dev/null)/$(cat /sys/class/dmi/id/product_name 2>/dev/null)" in
  Valve/Jupiter|Valve/Galileo) DECK=1 ;;
esac

DES_GAME=${DES_GAME:-game}
if [ "${DES_BOSS_RUSH:-}" = 1 ]; then
  DES_GAME=game_bossrush
  export DES_BOSS_RUSH=1 DES_BOSS_RUSH_DIR="${DES_BOSS_RUSH_DIR:-$D/bossrush}"
  export PS3_GAMEDATA_ROOT="$DES_BOSS_RUSH_DIR/gamedata"
  mkdir -p "$PS3_GAMEDATA_ROOT"
  [ -x "$D/.venv/bin/python" ] || die "Boss rush needs the setup's Python (.venv): run linux/native/build.sh venv."
  "$D/.venv/bin/python" "$D/tools/make_boss_rush.py" ||
    die "Boss rush: game_bossrush could not be made from your game files (the messages above say why)."
fi
EBOOT="$D/$DES_GAME/PS3_GAME/USRDIR/EBOOT.elf"
[ -f "$EBOOT" ] || die "no $DES_GAME/PS3_GAME/USRDIR/EBOOT.elf. Run linux/native/build.sh first."

export PS3_TITLE="Demon's Souls (ps3recomp)"
[ "$DES_GAME" = game_remaster ] && PS3_TITLE="Demon's Souls (ps3recomp) - PC Remaster mod"
[ "${DES_BOSS_RUSH:-}" = 1 ] && PS3_TITLE="Demon's Souls (ps3recomp) - Boss rush"
LOGS=${DES_LOG_DIR:-$D/logs}
export PS3_HDD0_ROOT="${PS3_HDD0_ROOT:-$D/hdd0}" PS3_HDD1_ROOT="${PS3_HDD1_ROOT:-$D/hdd1}" PS3_DEV_FLASH="${PS3_DEV_FLASH:-$D/no_flash}"
# The game copies files it read from the disc into its HDD1 cache and trusts them on the next run; that cache
# goes before every run, as in PLAY.bat (a killed run leaves truncated files there).
rm -rf "${PS3_HDD1_ROOT:?}/cache"
mkdir -p "$PS3_HDD0_ROOT" "$PS3_HDD1_ROOT" "$PS3_DEV_FLASH" "$LOGS"
export GCM_NO_TITLE_RECYCLE=1 PS3_NP_STRICT_OFFLINE=1 SPU_INTERP_UNLIFTED=1 SPURS_JC_EVENTS=0
export PAD_KEYMAP=souls OSK_TEXT="${DES_NAME:-Slayer}" PAD_SCRIPT="${PAD_SCRIPT:-}" PS3_PRIO_START=1
export PS3_INPUT_MAP="${PS3_INPUT_MAP:-$D/linux/native/input.toml}"
# The Vulkan renderer: the game's own shaders translated (guest programs), drawn in batches, in a window.
export PS3RECOMP_VK_GUEST_PROGRAMS=1 PS3RECOMP_VK_WINDOW=1 VK_DRAW_BATCH=1
# The SPU command dispatcher takes the rest of a fetched queue line without re-reserving it (NOTES fix 150) and
# waits for work instead of spinning (fix 145).
export DES_DISPQ_BATCH="${DES_DISPQ_BATCH:-1}" SPU_DISPQ_WAIT="${SPU_DISPQ_WAIT:-1}"
if [ -n "$DECK" ]; then
  # 4 cores share 15 W with the GPU: idle SPUs back off and then sleep (linux/play.sh has the measurements).
  export SPU_IDLE_PAUSE="${SPU_IDLE_PAUSE:-128}" SPU_IDLE_SLEEP_US="${SPU_IDLE_SLEEP_US:-50}"
fi
[ "${DES_GOD:-}" = 1 ] && export DES_GOD=1
if [ "${DES_FULLSCREEN:-${DECK:-0}}" = 1 ]; then export PS3RECOMP_VK_FULLSCREEN=1; else unset PS3RECOMP_VK_FULLSCREEN; fi
if [ "${DES_MOVIES:-1}" = 1 ]; then unset PS3_NO_SAIL; else export PS3_NO_SAIL=1; fi
case "${DES_FPS:-60}" in
  60) export DES_60FPS=1 PS3_VBLANK_HZ=120 PS3_CLOCK_SCALE=200 ;;
  30) unset DES_60FPS PS3_VBLANK_HZ PS3_CLOCK_SCALE ;;
  unlimited) export DES_60FPS=1 PS3_VBLANK_HZ=480 PS3_CLOCK_SCALE=200 DES_MAX_FPS=240 ;;
  *) die "DES_FPS=$DES_FPS: the native build runs at 60, 30 or unlimited." ;;
esac
if [ "${DES_LOG:-0}" = 1 ]; then export PS3_VERBOSE=1; else export PS3_VERBOSE="${PS3_VERBOSE:-0}"; fi

# Steam Deck: pin the GPU clock for this session (linux/play.sh explains why), back to automatic on exit.
GPU_DEV=/sys/class/drm/card0/device GPU_PRIV=/usr/bin/steamos-polkit-helpers/steamos-priv-write
gpu_clock_restore() { "$GPU_PRIV" "$GPU_DEV/power_dpm_force_performance_level" auto >/dev/null 2>&1; }
if [ -n "$DECK" ] && [ "${DES_GPU_CLOCK:-800}" != auto ] && [ -x "$GPU_PRIV" ] &&
   [ -f "$GPU_DEV/pp_od_clk_voltage" ] && [ "$(cat "$GPU_DEV/power_dpm_force_performance_level" 2>/dev/null)" = auto ]; then
  GC=${DES_GPU_CLOCK:-800}
  case "$GC" in *[!0-9]*|'') die "DES_GPU_CLOCK=$GC: use a clock in MHz (200-1600) or auto." ;; esac
  if "$GPU_PRIV" "$GPU_DEV/power_dpm_force_performance_level" manual &&
     "$GPU_PRIV" "$GPU_DEV/pp_od_clk_voltage" "s 0 $GC" && "$GPU_PRIV" "$GPU_DEV/pp_od_clk_voltage" "s 1 $GC" &&
     "$GPU_PRIV" "$GPU_DEV/pp_od_clk_voltage" c; then
    trap gpu_clock_restore EXIT
    trap 'exit 130' INT TERM HUP
    echo "GPU clock pinned at $GC MHz for this session (DES_GPU_CLOCK=auto turns this off)."
  else
    gpu_clock_restore
  fi
fi

# Built in a distrobox container (SteamOS): run it there too, with this environment.
RUN=()
BOX=${DES_DISTROBOX-$(cat "$BUILD/.distrobox" 2>/dev/null || true)}   # DES_DISTROBOX= (empty): run on the host
if [ -n "$BOX" ] && ! [ -f /run/.containerenv ]; then
  command -v distrobox >/dev/null || die "the build was made in the distrobox container '$BOX', and distrobox is not here"
  RUN=(distrobox enter "$BOX" -- env -C "$D")
  for v in $(env | sed -n 's/^\(\(PS3\|DES_\|PAD_\|SPU_\|GCM_\|VK_\|OSK_\|SDL_\)[A-Za-z0-9_]*\)=.*/\1/p'); do
    RUN+=("$v=${!v}")
  done
fi

for f in out err; do
  [ -f "$LOGS/last_run_$f.txt" ] && mv -f "$LOGS/last_run_$f.txt" "$LOGS/last_run_${f}_prev.txt"
done
echo "Running at ${DES_FPS:-60} fps. Game log: $LOGS/last_run_err.txt"
"${RUN[@]}" "$BIN" "$EBOOT" > "$LOGS/last_run_out.txt" 2> "$LOGS/last_run_err.txt"
CODE=$?
[ $CODE -eq 0 ] || echo "Demon's Souls exited with code $CODE. The logs are in $LOGS/last_run_*.txt."
exit $CODE
