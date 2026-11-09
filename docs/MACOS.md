# macOS (Apple silicon): native build on Metal

**Status: experimental.** The native arm64 build gets through the following, at 60 fps (or the console's 30):

- the opening movie, the menus and character creation;
- the Tutorial, with its 3D world, lighting, enemies and the HUD.

It has not been played beyond the start of the Tutorial yet.

Saves are written to `gamedata/dev_hdd0/home/00000001/savedata/`, as on Windows (`PS3_GAMEDATA_ROOT`
moves them). `hdd0/` stays empty.

This is not the Windows exe under Wine. The port's own renderer (`rsx_live_draw.c`, Direct3D 12) is
Windows-only, so the Mac build draws through ps3recomp's Metal RSX backend instead. Anything that
renderer fixes on Windows can look different here.

## What is missing or untested

- **Keyboard and mouse:** wired up but not yet played with. The setup reads the layout
  (`mac/input.toml`), but no key press has been checked in the game.
- **Hitches:** a few frames of 70-200 ms per minute in the Tutorial, plus longer ones while an area
  streams in.
- **The D3D12 renderer's extras:**
  - frame pacing, which is why there is no 50 fps mode and no rate above 60;
  - `DES_PERF` and F12 captures;
  - texture packs and the remaster's shaders.
- **On-screen keyboard:** there is no text box. The character name comes from `DES_NAME`.

## What you need

- Xcode or its command-line tools.
- Homebrew's `cmake`, `ninja`, `sdl2`, `glslang` and `spirv-cross`. The Metal backend compiles the game's
  shaders to MSL with them.
- `ffmpeg`, for the movies. It is loaded at run time and is not part of the build.
- Python 3.10 or newer.

## Building

From the repo folder:

```sh
python3 -m venv .venv
.venv/bin/pip install -r setup/requirements.txt pycryptodome

# 1. game files (a decrypted ISO; give --key for a Redump image), then the real file names
.venv/bin/python tools/iso_extract.py "/path/to/Demon's Souls (USA).iso" game --all
.venv/bin/python tools/udf_rename.py "/path/to/Demon's Souls (USA).iso" game
printf '%s\n' "/path/to/Demon's Souls (USA).iso" > game/.extracted

# 2. EBOOT.BIN -> EBOOT.elf without RPCS3: a SELF decrypter (decrypt_self.py) and RPCS3's public key
#    table (fetch_keys.py writes the key file). The resulting EBOOT.elf must have the SHA-256
#    EBOOT_ELF_SHA256 from setup/setup.py.
python3 fetch_keys.py
python3 decrypt_self.py game/PS3_GAME/USRDIR/EBOOT.BIN -o game/PS3_GAME/USRDIR/EBOOT.elf --keys <key file>

# 3-5. ps3recomp + this port's patch, the lift, the lifted-code patch (the setup's own steps)
.venv/bin/python -c "import sys; sys.path.insert(0,'setup'); import setup; setup.step_ps3recomp(); setup.step_lift()"

# 6. the native build (DS_AVX2=OFF: on arm64 the SPU and VMX helpers take their exact scalar paths)
cmake -S project -B port/build_mac -G Ninja -DCMAKE_BUILD_TYPE=Fast -DDS_BOOT_HARNESS=ON -DDS_AVX2=OFF \
      -DPS3RECOMP_FFMPEG_RUNTIME=ON \
      -DPS3RECOMP_DIR="$PWD/deps/ps3recomp" -DRECOMP_DIR="$PWD/port/recompiled" \
      -DSPU_DIR="$PWD/port/spu" -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
ninja -C port/build_mac
```

The two `.py` files in step 2 come from the resistance-recomp port (`tools/decrypt_self.py`,
`tools/fetch_keys.py`, same author, MIT).

`mac/install.sh` runs all of the above in one go, resumable (each step skips what is done):

```sh
DES_ISO="/path/to/Demon's Souls (USA).iso" mac/install.sh          # DES_KEY=<hex or .dkey> for Redump
mac/rebuild.sh lift build                                          # or any of: deps venv game decrypt toolkit lift build
```

The key file goes to `~/Library/Application Support/demons-souls-recomp/keys/self_keys.txt` (`DES_KEYS`
moves it). The desktop launcher in `mac/launcher/` (its README) runs these scripts for you: install
from the disc image, settings, saves, controls, the log, rebuilds.

The first build takes a while: there are 129 lifted files, about 440 MB of C++.

## Playing

```sh
mac/play.sh
```

Settings, as environment variables:

| Variable | Effect |
|---|---|
| `DES_NAME=<name>` | the character name |
| `DES_FPS=30` | the console's 30 fps; the default is 60 |
| `DES_MOVIES=0` | skip the movies; they are on whenever FFmpeg is found |
| `DES_LOG=1` | the runtime's per-event log; off by default, because it costs frames |
| `PS3_INPUT_MAP=<file>` | another key layout |
| `PS3_INPUT_MODE=controller` or `keyboard` | only that input; the default takes both |
| `DES_SIZE=<w>x<h>` | the window's size (default 1280x720) |
| `DES_LOG_DIR=<dir>` | where the two logs go (default `logs/`) |

The logs go to `logs/last_run_out.txt` and `logs/last_run_err.txt`.

## Controls

The controller works through SDL. DualSense and DualShock 4 use HIDAPI; an Xbox pad is read over IOKit,
because MFi delivers no buttons to a process without a window.

Keyboard and mouse use the Windows layout (`mac/input.toml`):

| Input | Control |
|---|---|
| WASD | move |
| mouse (click into the window to capture it) or IJKL | camera |
| left mouse | attack |
| right mouse | block |
| Shift | strong attack |
| Ctrl | parry |
| Space | roll / back |
| E | interact / confirm |
| F | two-hand |
| R | use item |
| Tab / middle mouse | lock on |
| arrows | d-pad |
| Return | Start |
| Backspace | Select |

Esc or Cmd releases the mouse.

In menus the mouse is a pointer: moving it over an item selects it, left click confirms, right click goes
back, the wheel moves the cursor, and the side buttons or PageUp / PageDown are L1 / R1. While the keyboard or
mouse is what you used last, the game's button icons show the keys and mouse buttons (`textures/kbm`, drawn
from your copy of the game by `mac/rebuild.sh build`). `LD_TEX_KBM=0` keeps the PS3 icons.

## Mac-specific fixes so far (in `patches/`)

- **The guest runs off the main thread** (`boot_main.cpp`, as in ps3recomp's `templates/project/main.cpp`).
  The Metal backend reaches AppKit with `dispatch_sync` onto the main queue from the frame clock. With the
  guest on the main thread, that queue was never serviced: the FIFO never drained, and the window stayed
  black at 0 fps.
- **Small float render targets go back to guest memory every frame** (`rsx_draw_engine.c`,
  `eng_float_targets_to_guest`). The game's auto-exposure is a GPU result its PPU reads from local memory
  (NOTES fixes 20/21). The Metal engine never stored R32F targets, so the exposure stayed 0 and the 3D
  world drew black. `RSX_ENGINE_FLOAT_WRITEBACK=<max texels>` (default 4096, 0 = off).
- **Movies through FFmpeg:**
  - `vdec_mf.c`'s non-Windows half implements the same interface over the toolkit's `vdec_ffmpeg.c`
    (MPEG-2).
  - `sail_engine.c`, and `cellSail.c`'s lock and future wait, now build on every host through
    `win32_compat.h`.
- **Keyboard and mouse under the window launcher**, from resistance-recomp:
  - The launcher (`host_window.m`) writes its NSEvents into an input block in the shared control page
    (`rsx_host_surface.h`).
  - The backend maps that page for `cellPad` (`host_attach_input`).
  - `cellPad` reads it through the input map. That part is ps3recomp-up-r8 commit 4773f0ae, merged with this
    port's `cellPad.c`.
  - The SDL MFi hint is the fix for Xbox pads.
- **Per-SPU-task log lines are verbose only** (`spu_workload.c`, `cellSpurs.c`), and `mac/play.sh` runs with
  `PS3_VERBOSE=0`.
  - Before, thousands of lines a second went through one stderr lock, a `fflush` came with every SPU task,
    and the log grew by about 50 MB in five minutes.
  - On a 60 s walk in the Tutorial at 30 fps: 7 s under 25 fps and 4 s under 15 before, against 5 and 2 after
    (including the first seconds after loading).
- **Non-Windows stand-ins** for what the lifted code calls in the D3D12 perf engine (`rsx_live_draw.c`)
  and for the menu pointer, which is Win32 only (`cellPad.c`). `Sleep` and `GetCurrentThreadId` in the
  lifted-code patch also get POSIX forms.
- **SPU compile flags for clang/gcc** (`project/CMakeLists.txt`): `-fno-stack-protector` instead of `/GS-`,
  and x86 flags on x86 only.
- **Fixes so the kit's tests link and pass on arm64:**
  - the `CreateWaitableTimerExW` shim;
  - `YieldProcessor` instead of `_mm_pause`;
  - missing includes and fixture stubs;
  - `gcm_reports` now runs with the old FIFO layout it was written for.
