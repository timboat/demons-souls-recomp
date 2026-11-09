#!/bin/zsh
# Build the native macOS port from your own disc, step by step (docs/MACOS.md has the same commands):
#
#   mac/rebuild.sh [step ...]
#
# Steps, in order (default: all of them): deps venv game decrypt toolkit lift build
#
#   deps     checks the build tools: Xcode's command-line tools, and Homebrew's cmake, ninja, sdl2,
#            glslang and spirv-cross (ffmpeg for the movies: only a warning without it)
#   venv     .venv from Python 3.10+ with setup/requirements.txt and pycryptodome (kept once complete)
#   game     your disc image (DES_ISO; DES_KEY for a Redump image) -> game/: tools/iso_extract.py
#            --all, tools/udf_rename.py, game/.extracted. Skipped once game/ is extracted, so the
#            image is needed only then
#   decrypt  game/PS3_GAME/USRDIR/EBOOT.BIN -> EBOOT.elf without RPCS3: tools/fetch_keys.py writes the
#            key file once (RPCS3's public key table, downloaded and checked by its SHA-256) and
#            tools/decrypt_self.py decrypts. Skipped while EBOOT.elf is there; either way the ELF is
#            checked against setup/setup.py's EBOOT_ELF_SHA256 (DES_ANY_EBOOT=1: a warning only)
#   toolkit  setup.step_ps3recomp(): deps/ps3recomp at the tested commit with patches/ps3recomp-local.patch
#   lift     setup.step_lift(): the recompiled PPU and SPU code (port/recompiled, port/spu) and
#            patches/lifted-code.patch. Both skip what is current, as SETUP.bat does
#   build    cmake (Ninja, -DPS3RECOMP_FFMPEG_RUNTIME=ON) + ninja -> port/build_mac/DemonsSoulsRecomp and
#            DemonsSoulsRecomp_window (the window mac/play.sh runs); incremental
#
# Each step prints "==> <step>" first (the launcher's progress bar reads them) and "==> done" at the end.
# Everything it writes (game/, port/, deps/, .venv/) is game-derived or fetched, and .gitignore'd.
# Environment: mac/env.sh (DES_ISO, DES_KEY, DES_KEYS, JOBS, PY).
set -e
setopt pipefail
here=${0:A:h}
source "$here/env.sh"
cd "$DES_ROOT"
ALL=(deps venv game decrypt toolkit lift build)
if (( $# )); then steps=("$@"); else steps=($ALL); fi
for s in $steps; do
    (( ${ALL[(Ie)$s]} )) || { print -u2 -r -- "unknown step '$s' ($ALL)"; exit 2; }
done

say() { print -r -- "==> $*"; }
fail() { print -r -- "ERROR: $*"; exit 1; }
need_venv() { [ -x "$VPY" ] || fail "no Python environment in $DES_VENV yet: run the venv step first"; }

for s in $steps; do
    case $s in
    deps)
        say "deps (the build tools)"
        xcode-select -p >/dev/null 2>&1 || fail "Apple's command-line tools are missing: run xcode-select --install"
        missing=()
        for t in cmake ninja glslangValidator spirv-cross; do
            command -v $t >/dev/null || missing+=($t)
        done
        [ -e "$DES_BREW/lib/libSDL2.dylib" ] || [ -n "$(brew --prefix sdl2 2>/dev/null)" ] || missing+=(sdl2)
        [ -n "$PY" ] || missing+=(python@3.12)
        if (( ${#missing} )); then
            missing=(${missing/glslangValidator/glslang})
            fail "missing: ${missing[*]}. Install them with: brew install ${missing[*]}"
        fi
        ls "$DES_BREW"/lib/libavcodec.[0-9]*.dylib >/dev/null 2>&1 ||
            print -r -- "  no FFmpeg (brew install ffmpeg): the game runs, but its movies are skipped"
        print -r -- "  cmake $(cmake --version | head -n 1 | cut -d' ' -f3), ninja $(ninja --version), $($PY --version 2>&1)" ;;
    venv)
        say "venv (the Python environment)"
        req=$(cat setup/requirements.txt | shasum -a 256 | cut -c1-16)
        if [ "$(cat "$DES_VENV/.des-ready" 2>/dev/null)" != "$req" ] ||
           ! "$VPY" -c 'import sys, Crypto, cryptography; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
            if ! "$VPY" -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
                [ -n "$PY" ] || fail "no Python 3.10 or newer (brew install python@3.12)"
                rm -rf "$DES_VENV"
                "$PY" -m venv "$DES_VENV" || fail "could not make the Python environment in $DES_VENV"
            fi
            "$VPY" -m pip install --quiet --disable-pip-version-check -r setup/requirements.txt pycryptodome ||
                fail "could not install the Python packages (pip). Check the internet connection and run this again."
            print -r -- "$req" >"$DES_VENV/.des-ready"
        fi
        print -r -- "  $("$VPY" --version 2>&1) in $DES_VENV" ;;
    game)
        say "game (the game files from your disc image)"
        need_venv
        "$VPY" -u "$here/setup_steps.py" game "${DES_ISO:-}" --key "${DES_KEY:-}" ;;
    decrypt)
        say "decrypt (EBOOT.BIN -> EBOOT.elf)"
        need_venv
        if [ ! -f "$DES_ELF" ]; then
            [ -f "$DES_USRDIR/EBOOT.BIN" ] || fail "no game/PS3_GAME/USRDIR/EBOOT.BIN: run the game step first"
            keys=$("$VPY" "$DES_ROOT/tools/fetch_keys.py" --out "$DES_KEYS") ||
                fail "could not get the decryption keys (they are downloaded once from RPCS3's source on GitHub). Check the internet connection and run this again."
            rm -f "$DES_ELF.partial"
            "$VPY" "$DES_ROOT/tools/decrypt_self.py" "$DES_USRDIR/EBOOT.BIN" -o "$DES_ELF.partial" --keys "$keys" ||
                { rm -f "$DES_ELF.partial"; fail "could not decrypt game/PS3_GAME/USRDIR/EBOOT.BIN (is it Demon's Souls, BLUS-30443?)"; }
            mv "$DES_ELF.partial" "$DES_ELF"
        fi
        "$VPY" "$here/setup_steps.py" check-elf ${DES_ANY_EBOOT:+--any} ;;
    toolkit)
        say "toolkit (ps3recomp at the tested commit, with this port's patch)"
        need_venv
        command -v git >/dev/null || fail "git is missing (Apple's command-line tools have it)"
        "$VPY" -u "$here/setup_steps.py" toolkit ;;
    lift)
        say "lift (the game's PPU and SPU code to C/C++)"
        need_venv
        "$VPY" -u "$here/setup_steps.py" lift ;;
    build)
        say "build (cmake + ninja: port/build_mac)"
        need_venv
        [ -f "$DES_ROOT/port/.lifted" ] || fail "nothing lifted yet (port/recompiled): run the lift step first"
        mkdir -p "$DES_ROOT/hdd0" "$DES_ROOT/hdd1" "$DES_ROOT/no_flash" "$DES_ROOT/logs"
        # DS_AVX2=OFF: on arm64 the SPU and VMX helpers take their exact scalar paths
        cmake -S "$DES_ROOT/project" -B "$DES_BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Fast -DDS_BOOT_HARNESS=ON -DDS_AVX2=OFF \
              -DPS3RECOMP_FFMPEG_RUNTIME=ON \
              -DPS3RECOMP_DIR="$DES_ROOT/deps/ps3recomp" -DRECOMP_DIR="$DES_ROOT/port/recompiled" \
              -DSPU_DIR="$DES_ROOT/port/spu" -DPython3_EXECUTABLE="$VPY" ||
            fail "cmake could not configure the build (see the lines above)"
        jobs=(); [ -n "$JOBS" ] && [ "$JOBS" != 0 ] && jobs=(-j "$JOBS")
        ninja -C "$DES_BUILD" "${jobs[@]}" || fail "the build failed (see the lines above)"
        [ -x "$DES_EXE" ] && [ -x "$DES_WIN" ] || fail "the build ended without $DES_EXE and $DES_WIN"
        # The keyboard / mouse button icons, from this copy of the game (NOTES fixes 91, 134). Never stops
        # the build: without them the game shows the PS3 buttons.
        "$VPY" "$DES_ROOT/tools/kbm_icons.py" "$DES_USRDIR" "$DES_ROOT/textures/kbm" --if-stale ||
            print -r -- "  keyboard / mouse button icons not made; the game shows the PS3 buttons"
        print -r -- "  built: $DES_EXE"
        # The launcher window (DemonsSoulsLauncher.app next to mac/). Never stops the build: mac/play.sh
        # plays without it.
        zsh "$here/launcher_native/build.sh" ||
            print -r -- "  DemonsSoulsLauncher.app not built; mac/play.sh starts the game" ;;
    esac
done
say "done"
