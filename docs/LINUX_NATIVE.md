# Native Linux build (Vulkan, no Proton) — experimental

The game built as a Linux program and drawn by ps3recomp's Vulkan backend, instead of the Windows build
through Proton (`linux/play.sh`, [LINUX.md](LINUX.md)). It skips Wine and the D3D12 → Vulkan translation,
and the Steam Deck gets more from its CPU.

**Status:** tested on the Steam Deck only (RADV, SteamOS 3, built in an Arch distrobox). Other GPUs and
distros, NVIDIA's driver included, should work but are untested. Not there yet compared with the Windows
build: the resolution setting, the frame-timing recorder, texture dumping/replacement, models, and
custom frame rates (60, 30 and unlimited only).

## Steam Deck numbers (uncapped, Boletarian Palace 1-1, the heaviest spot)

| | fps |
|---|---|
| Proton (Windows build), GPU clock pinned at 800 MHz | 34.5 |
| Native | 35.8 |
| Native, PGO | 37.0 |
| Native, PGO + ThinLTO | 38.0 |

The other areas (Shrine of Storms, Valley of Defilement, Stonefang Tunnel, the Nexus) reach the 60 fps cap
natively; the Tower of Latria is around 46. On the Deck the game holds the GPU clock at 800 MHz while it
runs (`DES_GPU_CLOCK`, below): with the automatic clock, the CPU takes the shared 15 W and the GPU sits
at 200 MHz.

## Build

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
see NOTES), `JOBS=<n>` (parallel compile jobs; lower it if the build runs out of memory),
`DES_AVX2=0` (a CPU without AVX2).

### SteamOS: the build container

SteamOS has no compiler, so the compile runs in a distrobox container named `des-build`; `build.sh` finds
it and uses it, and `play.sh` then runs the game there too (its FFmpeg and SDL match the build's). Make it
once, in desktop mode:

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
it) keeps your settings, runs the build from your disc image with a progress bar, updates the checkout
(git pull + rebuild), and **More → Add to the applications menu** adds two entries: the launcher and
"... - play" (straight into the game with the saved settings, `launcher.py --play`). For Steam's game mode,
add one of them with *Games → Add a Non-Steam Game to My Library*.

`linux/native/play.sh` settings (environment): `DES_FPS=60|30|unlimited` (default 60),
`DES_FULLSCREEN=0|1` (default 1 on a Deck), `DES_MOVIES=0|1`, `DES_NAME`, `DES_GAME=game_remaster`,
`DES_BOSS_RUSH=1` and `DES_BR_SOULS`, `DES_SKIP_INTRO=1`, `DES_GOD=1`, `DES_LOG=1`, and on a Steam Deck
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
