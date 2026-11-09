#!/bin/sh
# Launches Demon's Souls (BLUS-30443, ps3recomp static recompilation) natively on macOS (Apple silicon):
# the arm64 build in port/build_mac, drawn by ps3recomp's Metal backend. No Wine, no D3D12: the port's
# Direct3D 12 renderer (rsx_live_draw.c) is Windows-only, so the Mac build draws through the toolkit's own
# Metal RSX backend. Same game settings as linux/play.sh / PLAY.bat otherwise.
#
# The game runs under the window launcher (DemonsSoulsRecomp_window): it owns the window on the main
# thread and the game renders into IOSurfaces it shares (ps3recomp tools/host_window).
#
# Input: a controller (DualSense, DualShock 4, Xbox) through SDL, and keyboard + mouse (the Windows
# layout: mac/input.toml, PS3_INPUT_MAP picks another file). A click in the window captures the mouse
# for the camera; Esc or Cmd releases it. PS3_INPUT_MODE=controller|keyboard|both (default both).
#
# Settings (environment):
#   DES_NAME=<name>   the character name the game's on-screen keyboard gets (default "Slayer")
#   DES_FPS=60|30     the frame rate (default 60, as PLAY.bat on a desktop: the port's 60 fps patch with
#                     120 Hz vblanks and the guest clock at 200 %; 30 = the console's own rate)
#   DES_MOVIES=0|1    the movies (MPEG-2) are decoded by FFmpeg, loaded at run time: on by default when
#                     its libavcodec is found (Homebrew's, or PS3RECOMP_FFMPEG_AVCODEC / _AVUTIL), off
#                     without it -- the opening movie never ends with no decoder. "brew install ffmpeg"
#   DES_GAME=game_remaster   run the PC Remaster mod's copy instead of game/
#   DES_LOG=1         the runtime's per-event log lines (PS3_VERBOSE=1). Off by default: thousands of
#                     lines a second from every guest thread through one stderr lock change the game's
#                     timing (frame drops, hitches) and grew the log by ~50 MB in five minutes
#   DES_SIZE=<w>x<h>  the window's size (default 1280x720; the picture keeps its 16:9 inside it)
#   DES_LOG_DIR=<dir> where last_run_out.txt / last_run_err.txt go (default logs/; the launcher's
#                     debug mode points it at the session's folder)
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
cd "$D"
die() { echo "error: $*" >&2; exit 1; }

BIN="$D/port/build_mac/DemonsSoulsRecomp"
WIN="$D/port/build_mac/DemonsSoulsRecomp_window"
[ -x "$BIN" ] && [ -x "$WIN" ] || die "the macOS build is not there yet (port/build_mac). Build it first (docs/MACOS.md)."

DES_GAME=${DES_GAME:-game}
EBOOT="$D/$DES_GAME/PS3_GAME/USRDIR/EBOOT.elf"
[ -f "$EBOOT" ] || die "no $DES_GAME/PS3_GAME/USRDIR/EBOOT.elf. Run the setup steps first (docs/MACOS.md)."

export PS3_TITLE="Demon's Souls (ps3recomp)"
[ "$DES_GAME" = game_remaster ] && PS3_TITLE="Demon's Souls (ps3recomp) - PC Remaster mod"
LOGS=${DES_LOG_DIR:-$D/logs}
# (a test run moves these, and PS3_GAMEDATA_ROOT for the saves, into its own folder)
export PS3_HDD0_ROOT="${PS3_HDD0_ROOT:-$D/hdd0}" PS3_HDD1_ROOT="${PS3_HDD1_ROOT:-$D/hdd1}" PS3_DEV_FLASH="${PS3_DEV_FLASH:-$D/no_flash}"
mkdir -p "$PS3_HDD0_ROOT" "$PS3_HDD1_ROOT" "$PS3_DEV_FLASH" "$LOGS"
export GCM_NO_TITLE_RECYCLE=1 PS3_NP_STRICT_OFFLINE=1 SPU_INTERP_UNLIFTED=1 SPURS_JC_EVENTS=0
export PS3_INPUT_MAP="${PS3_INPUT_MAP:-$D/mac/input.toml}"
# Translated shaders (HLSL -> SPIR-V -> MSL) kept on disk, as deadpool-recomp's run.sh does: a new
# material hitches the game the first time it is ever seen, not once per run. macOS keeps the compiled
# Metal side in its own shader cache.
export PS3RECOMP_MSL_CACHE="${PS3RECOMP_MSL_CACHE:-$D/cache/msl}"
mkdir -p "$PS3RECOMP_MSL_CACHE"
export PAD_KEYMAP=souls OSK_TEXT="${DES_NAME:-Slayer}" PAD_SCRIPT="${PAD_SCRIPT:-}" PS3_PRIO_START=1
if [ -z "${PS3RECOMP_FFMPEG_AVCODEC:-}" ]; then
  for P in /opt/homebrew/lib /usr/local/lib; do
    C=$(ls "$P"/libavcodec.[0-9]*.dylib 2>/dev/null | grep -E 'libavcodec\.[0-9]+\.dylib$' | head -n 1)
    U=$(ls "$P"/libavutil.[0-9]*.dylib 2>/dev/null | grep -E 'libavutil\.[0-9]+\.dylib$' | head -n 1)
    if [ -n "$C" ] && [ -n "$U" ]; then
      export PS3RECOMP_FFMPEG_AVCODEC="$C" PS3RECOMP_FFMPEG_AVUTIL="$U"; break
    fi
  done
fi
if [ -z "${DES_MOVIES:-}" ]; then
  if [ -n "${PS3RECOMP_FFMPEG_AVCODEC:-}" ]; then DES_MOVIES=1; else DES_MOVIES=0
    echo "No FFmpeg found (brew install ffmpeg): the movies are skipped."; fi
fi
if [ "$DES_MOVIES" = 1 ]; then unset PS3_NO_SAIL; else export PS3_NO_SAIL=1; fi
case "${DES_FPS:-60}" in
  60) export DES_60FPS=1 PS3_VBLANK_HZ=120 PS3_CLOCK_SCALE=200 ;;
  30) unset DES_60FPS PS3_VBLANK_HZ PS3_CLOCK_SCALE ;;
  *)  die "DES_FPS=$DES_FPS: the macOS build runs at 60 or 30 fps (50 and above 60 need the D3D12 present pacing)." ;;
esac
if [ "${DES_LOG:-0}" = 1 ]; then export PS3_VERBOSE=1; else export PS3_VERBOSE="${PS3_VERBOSE:-0}"; fi

for f in out err; do
  [ -f "$LOGS/last_run_$f.txt" ] && mv -f "$LOGS/last_run_$f.txt" "$LOGS/last_run_${f}_prev.txt"
done
SIZE=${DES_SIZE:-1280x720}
case "$SIZE" in
  [0-9]*x[0-9]*) ;;
  *) die "DES_SIZE=$SIZE: give the window size as <width>x<height>, e.g. 1920x1080." ;;
esac
echo "Demon's Souls: game log in $LOGS/last_run_err.txt"
set +e
"$WIN" --title "$PS3_TITLE" --size "$SIZE" -- "$BIN" "$EBOOT" \
  > "$LOGS/last_run_out.txt" 2> "$LOGS/last_run_err.txt"
CODE=$?
[ $CODE -eq 0 ] || echo "Demon's Souls exited with code $CODE. The logs are in $LOGS/last_run_*.txt."
exit $CODE
