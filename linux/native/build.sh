#!/bin/bash
# Build the native Linux port (Vulkan, no Wine) from your own disc, step by step (docs/LINUX_NATIVE.md):
#
#   linux/native/build.sh [step ...]
#
# Steps, in order (default: all of them): deps venv game decrypt toolkit lift build
#
#   deps     checks the build tools: clang, lld, cmake, ninja, SDL2, glslang / SPIRV-Tools, the Vulkan
#            headers (FFmpeg for the movies: only a warning without it)
#   venv     .venv from Python 3.10+ with setup/requirements.txt and pycryptodome (kept once complete)
#   game     your disc image (DES_ISO; DES_KEY for a Redump image) -> game/ (mac/setup_steps.py game).
#            Skipped once game/ is extracted, so the image is needed only then
#   decrypt  EBOOT.BIN -> EBOOT.elf without RPCS3 (tools/fetch_keys.py + tools/decrypt_self.py, as on the
#            Mac), checked against setup/setup.py's EBOOT_ELF_SHA256 (DES_ANY_EBOOT=1: a warning only)
#   toolkit  deps/ps3recomp at the tested commit with patches/ps3recomp-local.patch
#   lift     the recompiled PPU and SPU code (port/recompiled, port/spu) and patches/lifted-code.patch
#   build    cmake (Ninja, clang, Vulkan) + ninja -> port/build_linux/DemonsSoulsRecomp; incremental
#
# Each step prints "==> <step>" first (the launcher's progress reads them) and "==> done" at the end.
# Everything it writes (game/, port/, deps/, .venv/) is game-derived or fetched, and .gitignore'd.
#
# Environment:
#   DES_ISO, DES_KEY  your disc image and (Redump) disc key, as for mac/rebuild.sh
#   DES_KEYS          the key file decrypt writes (default ~/.local/share/demons-souls-recomp/keys/self_keys.txt)
#   DES_BUILD         the build folder (default port/build_linux)
#   DES_LTO=1         ThinLTO across the whole program (Steam Deck, Boletaria: +3.5% on top of PGO; a longer
#                     link). Changing it reconfigures the build folder, which then rebuilds everything
#   DES_PGO=<file>    an llvm-profdata profile to optimize with (-fprofile-use); see docs/LINUX_NATIVE.md
#   DES_DISTROBOX=<name>  the distrobox container the build step compiles in. On SteamOS (no compiler on the
#                     host, and an older glibc than a current toolchain builds for) the default is "des-build"
#                     when that container exists; the game then also runs inside it (linux/native/play.sh)
#   JOBS              parallel compile jobs (ninja's -j; default: ninja's own)
#   PY                the Python 3.10+ the venv is made from (default: the newest python3.1x on PATH)
set -eo pipefail
here=$(cd "$(dirname "$0")" && pwd)
DES_ROOT=$(cd "$here/../.." && pwd)
cd "$DES_ROOT"
DES_VENV=${DES_VENV:-$DES_ROOT/.venv}
DES_BUILD=${DES_BUILD:-$DES_ROOT/port/build_linux}
DES_KEYS=${DES_KEYS:-${XDG_DATA_HOME:-$HOME/.local/share}/demons-souls-recomp/keys/self_keys.txt}
DES_USRDIR=$DES_ROOT/game/PS3_GAME/USRDIR
DES_ELF=$DES_USRDIR/EBOOT.elf
VPY=$DES_VENV/bin/python
if [ -z "${PY:-}" ]; then
  for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    command -v "$c" >/dev/null && { PY=$(command -v "$c"); break; }
  done
fi

ALL="deps venv game decrypt toolkit lift build"
steps=${*:-$ALL}
for s in $steps; do
  case " $ALL " in *" $s "*) ;; *) echo "unknown step '$s' ($ALL)" >&2; exit 2 ;; esac
done

say() { echo "==> $*"; }
fail() { echo "ERROR: $*"; exit 1; }
need_venv() { [ -x "$VPY" ] || fail "no Python environment in $DES_VENV yet: run the venv step first"; }
in_container() { [ -f /run/.containerenv ] || [ -f /.dockerenv ] || [ -n "${CONTAINER_ID:-}" ]; }

# The container the compile runs in, if any: none inside one already, DES_DISTROBOX if given, else des-build
# on a host without clang (SteamOS) when distrobox has it.
BOX=
if ! in_container; then
  if [ -n "${DES_DISTROBOX:-}" ]; then BOX=$DES_DISTROBOX
  elif ! command -v clang >/dev/null && command -v distrobox >/dev/null &&
       distrobox list 2>/dev/null | awk -F'|' '{gsub(/ /,"",$2); print $2}' | grep -qx des-build; then BOX=des-build
  fi
fi

for s in $steps; do
  case $s in
  deps)
    say "deps (the build tools)"
    if [ -n "$BOX" ]; then
      echo "  the compile runs in the distrobox container '$BOX'; checking the tools there"
      distrobox enter "$BOX" -- env DES_DISTROBOX= bash "$here/build.sh" deps | grep --line-buffered -v '^==> ' || exit 1
    else
      missing=
      for t in clang clang++ ld.lld cmake ninja glslangValidator; do command -v "$t" >/dev/null || missing="$missing $t"; done
      for h in vulkan/vulkan.h SDL2/SDL.h glslang/Public/ShaderLang.h spirv-tools/libspirv.h; do
        found=
        for inc in /usr/include /usr/local/include; do [ -f "$inc/$h" ] && found=1; done
        [ -n "$found" ] || missing="$missing <$h>"
      done
      [ -n "$PY" ] || missing="$missing python3"
      if [ -n "$missing" ]; then
        fail "missing:$missing. Arch: sudo pacman -S clang lld cmake ninja sdl2 glslang spirv-tools vulkan-headers ffmpeg python git
  Debian / Ubuntu: sudo apt install clang lld cmake ninja-build libsdl2-dev glslang-dev glslang-tools spirv-tools libvulkan-dev libavcodec-dev python3-venv git
  Fedora: sudo dnf install clang lld cmake ninja-build SDL2-devel glslang-devel spirv-tools-devel vulkan-loader-devel ffmpeg-free-devel python3 git
  On SteamOS: make the build container once (docs/LINUX_NATIVE.md) and run this again."
      fi
      ls /usr/include/libavcodec/avcodec.h /usr/include/*/libavcodec/avcodec.h >/dev/null 2>&1 ||
        echo "  no FFmpeg headers (libavcodec): the game runs, but its movies are skipped"
      echo "  $(clang --version | head -n 1), cmake $(cmake --version | head -n 1 | cut -d' ' -f3), ninja $(ninja --version), $($PY --version 2>&1)"
    fi ;;
  venv)
    say "venv (the Python environment)"
    [ -n "$PY" ] || fail "no Python 3.10 or newer (python3)"
    req=$(sha256sum setup/requirements.txt | cut -c1-16)
    if [ "$(cat "$DES_VENV/.des-ready" 2>/dev/null)" != "$req" ] ||
       ! "$VPY" -c 'import sys, Crypto, cryptography; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
      if ! "$VPY" -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
        rm -rf "$DES_VENV"
        "$PY" -m venv "$DES_VENV" || fail "could not make the Python environment in $DES_VENV (Debian / Ubuntu: sudo apt install python3-venv)"
      fi
      "$VPY" -m pip install --quiet --disable-pip-version-check -r setup/requirements.txt pycryptodome ||
        fail "could not install the Python packages (pip). Check the internet connection and run this again."
      echo "$req" >"$DES_VENV/.des-ready"
    fi
    echo "  $("$VPY" --version 2>&1) in $DES_VENV" ;;
  game)
    say "game (the game files from your disc image)"
    need_venv
    "$VPY" -u "$DES_ROOT/mac/setup_steps.py" game "${DES_ISO:-}" --key "${DES_KEY:-}" ;;
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
    "$VPY" "$DES_ROOT/mac/setup_steps.py" check-elf ${DES_ANY_EBOOT:+--any} ;;
  toolkit)
    say "toolkit (ps3recomp at the tested commit, with this port's patch)"
    need_venv
    command -v git >/dev/null || fail "git is missing"
    "$VPY" -u "$DES_ROOT/mac/setup_steps.py" toolkit ;;
  lift)
    say "lift (the game's PPU and SPU code to C/C++)"
    need_venv
    "$VPY" -u "$DES_ROOT/mac/setup_steps.py" lift ;;
  build)
    say "build (cmake + ninja: ${DES_BUILD#$DES_ROOT/})"
    [ -f "$DES_ROOT/port/.lifted" ] || fail "nothing lifted yet (port/recompiled): run the lift step first"
    mkdir -p "$DES_ROOT/hdd0" "$DES_ROOT/hdd1" "$DES_ROOT/no_flash" "$DES_ROOT/logs"
    if [ -n "$BOX" ]; then
      echo "  compiling in the distrobox container '$BOX'"
      distrobox enter "$BOX" -- env DES_DISTROBOX= DES_BUILD="$DES_BUILD" DES_LTO="${DES_LTO:-}" DES_PGO="${DES_PGO:-}" \
        JOBS="${JOBS:-}" DES_NESTED=1 bash "$here/build.sh" build | grep --line-buffered -v '^==> ' || exit 1
      echo "$BOX" >"$DES_BUILD/.distrobox"
    else
      command -v clang >/dev/null || fail "clang is missing: run the deps step for what to install"
      flags=
      lflags="-fuse-ld=lld"
      if [ "${DES_LTO:-0}" = 1 ]; then
        flags="-flto=thin"
        lflags="$lflags -flto=thin -Wl,--thinlto-cache-dir=$DES_BUILD/ltocache"
      fi
      if [ -n "${DES_PGO:-}" ]; then
        [ -f "$DES_PGO" ] || fail "DES_PGO=$DES_PGO: no such profile"
        flags="$flags -fprofile-use=$DES_PGO -Wno-profile-instr-unprofiled -Wno-profile-instr-out-of-date -Wno-backend-plugin"
      fi
      # DS_AVX2: the SPU and VMX helpers' AVX2 / FMA paths, on CPUs that have them (every x86-64 since ~2013;
      # the Steam Deck's too). DES_AVX2=0 builds for an older CPU.
      avx=ON; [ "${DES_AVX2:-1}" = 0 ] && avx=OFF
      grep -q '^flags' /proc/cpuinfo && ! grep -qw avx2 /proc/cpuinfo && avx=OFF
      cmake -S "$DES_ROOT/project" -B "$DES_BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Fast \
            -DCMAKE_C_COMPILER="$(command -v clang)" -DCMAKE_CXX_COMPILER="$(command -v clang++)" \
            -DCMAKE_C_FLAGS="$flags" -DCMAKE_CXX_FLAGS="$flags" -DCMAKE_EXE_LINKER_FLAGS="$lflags" \
            -DDS_AVX2=$avx -DDS_BOOT_HARNESS=ON -DPS3RECOMP_BUILD_TESTS=OFF \
            -DPS3RECOMP_FFMPEG_RUNTIME=ON -DPS3RECOMP_RSX_VULKAN=ON \
            -DPS3RECOMP_DIR="$DES_ROOT/deps/ps3recomp" -DRECOMP_DIR="$DES_ROOT/port/recompiled" \
            -DSPU_DIR="$DES_ROOT/port/spu" ||
        fail "cmake could not configure the build (see the lines above)"
      jobs=; [ -n "${JOBS:-}" ] && [ "$JOBS" != 0 ] && jobs="-j $JOBS"
      # shellcheck disable=SC2086
      ninja -C "$DES_BUILD" $jobs DemonsSoulsRecomp || fail "the build failed (see the lines above)"
      [ -x "$DES_BUILD/DemonsSoulsRecomp" ] || fail "the build ended without $DES_BUILD/DemonsSoulsRecomp"
      in_container || rm -f "$DES_BUILD/.distrobox"
      echo "  built: $DES_BUILD/DemonsSoulsRecomp"
    fi
    # The keyboard / mouse button icons, from this copy of the game (NOTES fixes 91, 134). Never stops the
    # build: without them the game shows the PS3 buttons.
    if [ -z "${DES_NESTED:-}" ] && [ -x "$VPY" ]; then
      "$VPY" "$DES_ROOT/tools/kbm_icons.py" "$DES_USRDIR" "$DES_ROOT/textures/kbm" --if-stale ||
        echo "  keyboard / mouse button icons not made; the game shows the PS3 buttons"
    fi ;;
  esac
done
say "done"
