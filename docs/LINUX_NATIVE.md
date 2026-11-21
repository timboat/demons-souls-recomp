# Native Linux build (Vulkan, no Proton) — experimental

The game built as a Linux program and drawn by ps3recomp's Vulkan backend, instead of the Windows build
through Proton (`linux/play.sh`, [LINUX.md](LINUX.md)). It skips Wine and the D3D12 → Vulkan translation,
and the Steam Deck gets more from its CPU.

**Status:** tested on the Steam Deck only (RADV, SteamOS 3, built in an Arch distrobox). Other GPUs and
distros, NVIDIA's driver included, should work but are untested. Not there yet compared with the Windows
build: the resolution setting, the frame-timing recorder, texture dumping/replacement, models, and
custom frame rates (60, 30 and unlimited only).

## Steam Deck frame rates

Measured 2026-11-15: Steam Deck LCD ("Jupiter"), SteamOS 3.9.5, Mesa/RADV 26.2.7, on AC power,
started with `linux/native/play.sh` and its defaults (full screen 1280x800, GPU clock held at 800 MHz,
shaders compiled in the background, the shader caches warm from an earlier run). The scene is the start of
Boletarian Palace 1-1, the heaviest spot we know: 10 s walking in, then 140 s fighting the soldiers at the
gate. Frame times are the game's own presents (`HITCH_MS=1` logs every one).

| 150 s of play | Average | 1% low | 0.1% low | Median frame | 95th pct | 99th pct | Frames over 50 ms |
|---|---|---|---|---|---|---|---|
| 60 fps (default) | 47.9 fps | 14.7 fps | 7.0 fps | 20.3 ms | 26.4 ms | 31.8 ms | 40 |
| Unlimited | 47.8 fps | 15.2 fps | 8.2 fps | 20.4 ms | 27.2 ms | 31.7 ms | 40 |

- **Walking** (the 10 s before the fight): 49.5 fps average, 1% low 33.0 fps, no frame over 32 ms.
- **The cap isn't the limit here:** unlimited gives the same 48 fps, so this is what the Deck can do in this
  spot. The APU draws 15.0 W on average, the Deck's whole budget.
- **The lows** come from about 40 frames in 150 s, around one every 4 s, that take 50-230 ms during the fight (short
  hitches). Without them, 99% of frames are under 32 ms.
- **Game speed:** when frames run late the game runs slower instead of skipping ahead (0.97 of real time
  in this fight), so nothing jumps.
- **First launch** (empty shader caches, the same scene): 43.9 fps instead of 47.7 in the 5 s averages, and
  12 pauses of 200 ms or more in the fight instead of 4 (the longest 0.7 s). Each new shader is compiled once
  and kept, so this goes away after the first visit to an area.
- **Earlier builds**, in the same spot, uncapped: Proton (the Windows build) 34.5 fps, native 38.0 fps.

### Every world, at its archstone

The same settings, warped to each world's archstone in one run (the port's `DES_WARP_AT` test helper, god
mode). 50 s per stop: standing, a camera pan, a short walk, standing again. Second visit (shaders cached);
a run like this the first time gives about the same averages (within 1 fps) but 2-7 hitches of 50-360 ms per stop while the new
shaders compile.

| 50 s at the archstone | Average | 1% low | Median frame | 99th pct | Worst frame | Frames at 60 fps | APU power |
|---|---|---|---|---|---|---|---|
| The Nexus | 59.7 fps | 37.9 fps | 16.6 ms | 24.7 ms | 32 ms | 95% | 7.6 W |
| Boletarian Palace 1-1 | 56.1 fps | 34.4 fps | 17.4 ms | 27.6 ms | 32 ms | 87% | 15.0 W |
| Shrine of Storms | 59.8 fps | 38.1 fps | 16.5 ms | 24.8 ms | 29 ms | 95% | 8.4 W |
| Tower of Latria (first archstone) | 59.8 fps | 37.2 fps | 16.5 ms | 25.3 ms | 46 ms | 94% | 15.0 W |
| Tower of Latria (second archstone) | 55.1 fps | 34.5 fps | 17.8 ms | 26.9 ms | 45 ms | 83% | 13.6 W |
| Valley of Defilement | 59.7 fps | 37.0 fps | 16.5 ms | 25.2 ms | 34 ms | 94% | 9.4 W |
| Stonefang Tunnel | 59.8 fps | 37.6 fps | 16.5 ms | 25.2 ms | 31 ms | 96% | 7.0 W |

"Frames at 60 fps": frames shown within 20.8 ms (a 60 fps frame plus a quarter). No frame took 50 ms or more at
any stop. Five of the seven hold 60; Boletaria and Latria's second archstone, the two heaviest views on the tour,
run at 55-56 standing and walking; Boletaria drops to around 48 in a fight (above).

**Why the GPU clock is held:** with the automatic clock, the CPU takes the shared 15 W and the GPU sits at
200 MHz (`DES_GPU_CLOCK`, below).

## Install (one click)

```sh
git clone https://github.com/timboat/demons-souls-recomp
demons-souls-recomp/linux/native/install.sh
```

The installer window asks for your disc image (an .iso, a Redump .zip, or a dumped disc folder) and its
disc key; **Install** does the rest. The disc key is only for an
encrypted (Redump) image: copy the "Disc Key" line from
[Redump's page for this disc](http://redump.org/disc/16199/) (the window has a button for it). The
installer's steps:

- **The build tools:** missing ones are installed through your distribution's package manager after one
  password prompt (Arch, Debian / Ubuntu, Fedora families). On SteamOS it makes the `des-build`
  container instead (below).
- **The build:** every step of `linux/native/build.sh`, with a checklist and a progress bar.
- **The menu entries:** they go in your applications menu, with an icon cut from your disc's artwork. The
  window then offers Play, the launcher, and **Add to Steam**.

Run it again after a failure or a Cancel: it continues where it stopped. `install.sh` first gets Tk for
Python if it is missing.

## Build (by hand)

You need clang + lld (17 or newer; tested with 23), cmake, ninja, SDL2, glslang, SPIRV-Tools, the Vulkan
headers, Python 3.10+ and git, and FFmpeg's development files for the movies. `linux/native/build.sh deps`
checks them and prints the install line for Arch, Debian / Ubuntu and Fedora.

```sh
linux/native/build.sh                         # every step (below); safe to run again
DES_ISO=/path/to/BLUS30443.iso linux/native/build.sh    # the first time: your disc image
DES_ISO=/path/to/image.iso DES_KEY=<32 hex digits or .dkey> linux/native/build.sh   # a Redump image
```

The steps are `deps venv game decrypt toolkit lift build` (`linux/native/build.sh build` runs only the
compile). The game files come from your own disc image, the EBOOT is decrypted without RPCS3 (the keys are
downloaded once from RPCS3's source), and the build lands in `port/build_linux/DemonsSoulsRecomp`. A
checkout that already went through `linux/setup.sh` (the Proton build) has the game files and the lifted
code; only `build` is new then. The first build takes about an hour on a Steam Deck, less on a desktop.

Options: `DES_LTO=1` (ThinLTO across the whole program: about 3.5% faster on the Deck, a longer link),
`DES_PGO=<profile.profdata>` (profile-guided optimization with an llvm-profdata profile; +10% on the Deck,
see NOTES; `port/pgo/des.profdata` is used when it exists, `DES_PGO=0` turns that off), `JOBS=<n>`
(parallel compile jobs; lower it if the build runs out of memory), `DES_AVX2=0` (a CPU without AVX2).
On a CPU with all of x86-64-v3 (AVX2, BMI1/2, FMA, F16C, LZCNT, MOVBE: every AVX2 CPU in practice) the
build targets it, about 3.7% faster on the Deck; float results are unchanged (`-ffp-contract=off`).
`DES_MARCH=0` builds for plain x86-64 + AVX2 instead.

### SteamOS: the build container

SteamOS has no compiler, so the compile runs in a distrobox container named `des-build`; `build.sh` finds
it and uses it, and `play.sh` then runs the game there too (its FFmpeg and SDL match the build's). The
installer makes it; by hand, once, in desktop mode:

```sh
distrobox create -n des-build -i archlinux:latest
distrobox enter des-build -- sudo pacman -Syu --noconfirm clang lld cmake ninja sdl2-compat glslang \
    spirv-tools vulkan-headers vulkan-radeon ffmpeg python git
```

On a PC with NVIDIA's driver, a container needs `distrobox create --nvidia ...`; building on the host is
simpler there.

## Play

```sh
python3 linux/native/launcher.py     # the launcher window
linux/native/play.sh                 # or straight into the game, with the settings below
```

The launcher (Python + Tk: Debian / Ubuntu `python3-tk`, Fedora `python3-tkinter`, Arch `tk`; SteamOS has
it) keeps your settings, rebuilds (for example with ThinLTO), updates the checkout (git pull + rebuild), and **More → Add to the applications menu** adds two entries: the launcher and
"... - play" (straight into the game with the saved settings, `launcher.py --play`). For Steam's game mode,
add one of them with *Games → Add a Non-Steam Game to My Library*.

**Steam:** *Add to Steam* (in the installer, or the launcher's More menu; or `linux/native/steam.py add
--restart-steam`) adds a "Demon's Souls" shortcut that opens the launcher with Play selected
(`launcher.py --steam`); the launcher closes when the game ends, so quitting the game is back in the Steam
library. A controller works the launcher, for game mode: up / down (D-pad or left stick) moves between the
items, left / right changes the selected one, A presses it, B backs out of a menu or a question, Start plays;
A on the character name opens Steam's on-screen keyboard. The arrow keys and Enter do the same. It comes with library artwork cut from your own disc's background picture (`PS3_GAME/PIC1.PNG`):
a portrait and a wide capsule, the hero banner, the logo and an icon, kept in `port/steam_art/`. A shortcut
for the Proton build (`linux/play.sh`) gets the same artwork. Steam rewrites its shortcut list when it exits,
so it closes for a moment and opens again. The first change keeps a copy of the old list
(`shortcuts.vdf.before-demons-souls`).

`linux/native/play.sh` settings (environment): `DES_FPS=60|30|unlimited` (default 60),
`DES_FULLSCREEN=0|1` (default 1 on a Deck), `DES_MOVIES=0|1`, `DES_NAME`, `DES_GAME=game_remaster`,
`DES_BOSS_RUSH=1` and `DES_BR_SOULS`, `DES_SKIP_INTRO=1`, `DES_GOD=1`, `DES_EASY=1` (attacks that hit you take half
as much HP), `DES_LOG=1`,
`DES_ASYNC_SHADERS=0|1` (default 1: a shader never seen before is translated in the background and its object
shows a frame or so late instead of the game stalling; the launcher's "Compile new shaders in the background"), and on a Steam Deck
`DES_GPU_CLOCK=<MHz>|auto` (default 800; restored to automatic when the game exits). The saves are in
`gamedata/`, the same folder the Proton build uses. Logs: `logs/last_run_err.txt`.

**Controls:** a controller through SDL (DualSense, DualShock 4, Xbox, the Deck's own). Keyboard and mouse
use the Windows layout (`linux/native/input.toml`, editable): click in the window to give the mouse to the
camera; Esc releases it and opens the game's menu. **F11** or **Alt+Enter** switches between full screen
and a window (the window can be resized).

## Troubleshooting

- **Black or no window, and the game is slow:** look for `window disabled, continuing headless` in
  `logs/last_run_err.txt`; the line before it says why the Vulkan window could not be made.
  `SDL_VIDEODRIVER=x11 linux/native/play.sh` tries X11 instead of Wayland.
- **No movies:** `[ffmpeg] ... not found` in the log means the FFmpeg the game runs with is not the one
  it was built against (on SteamOS: run it through `play.sh`, which uses the build container).
- **Which GPU:** `PS3RECOMP_VK_DEVICE=<n>` picks another one (the log lists them).
