# Linux and Steam Deck

> **Works on Linux and the Steam Deck.** On the Deck it plays but is not perfect yet: loads are slow and it is
> not fully smooth. The kit has also set up and played the game on Ubuntu
> 24.04 (Intel i7-4770K, NVIDIA GTX 980, Proton): about 57-58 fps on average in 60 fps mode, but choppy,
> with frequent one-frame hitches on that 4-core CPU. Linux performance work is under way. If you try
> it, especially on a Steam Deck or another AMD / Intel GPU, please report what happens, good or bad: see
> [For testers](#for-testers).

There is no ready-made Linux download of the game, and there cannot be one: it would contain code
recompiled from the game. Instead there is a **setup + play kit** for Linux. Like `SETUP.bat` on
Windows, it takes **your own disc image** and builds the port on your PC.

The port itself stays a Windows program (its renderer is Direct3D 12). On Linux it is built with the
same compiler as on Windows and runs through **Proton** (the same layer Steam uses for Windows games),
whose vkd3d-proton turns Direct3D 12 into Vulkan. A true native Linux build would need the renderer
rewritten for Vulkan; that is not planned for now.

## What you need

- A Linux PC (x86-64) with a Vulkan GPU driver, or a Steam Deck (in desktop mode for the setup).
- Your Demon's Souls disc image (USA, **BLUS-30443**): `.iso`, Redump `.zip`, or a dumped disc folder,
  plus its disc key if it is encrypted (as Redump images are).
- About **25 GB free** (8 GB game files, 1-2 GB tools and SDK, the rest build files) and time: the first
  build takes 10-30 minutes on a desktop (6 minutes on a 16-core one), probably **1-2 hours on a
  Steam Deck**.
- An internet connection for the first run: it downloads the PS3 decryption keys for the game's EBOOT
  (one small file from RPCS3's public source; RPCS3's AppImage only if that fails),
  ps3recomp, Microsoft's C runtime and Windows SDK (through xwin; you are asked to accept Microsoft's
  license), and Proton (through umu-launcher). None of these are part of the kit.

## Set up and play

1. Download `DemonsSoulsRecomp-Setup-x86_64.AppImage` (GitHub → Actions → "Linux AppImage" → the
   newest run → Artifacts; it is a zip with the AppImage inside), and make it executable
   (right-click → Properties → Permissions → "Is executable", or `chmod +x`).
2. Run it. A terminal window opens and asks for your disc image (a file picker, or drag the file into
   the window), then for the disc key if needed. Everything goes into `~/DemonsSoulsRecomp`
   (set `DS_HOME=/other/folder` to put it elsewhere, e.g. on an SD card).
3. It works through the same six steps as `SETUP.bat`: extract the game files, decrypt the EBOOT (keys from
   RPCS3's source), fetch ps3recomp and apply this repo's patches, recompile the game code, apply the port's
   edits, build `DemonsSoulsRecomp.exe`. On the way it asks before each download.
4. Then it offers to start the game. The first start sets up Proton (a few hundred MB download).
5. To play later, run the AppImage again (it checks for updates to the patches and only rebuilds what
   changed), or `~/DemonsSoulsRecomp/linux/play.sh`.

Settings are the same environment variables as on Windows: `DES_FPS=30|50|60|unlimited|31-240`
(a Steam Deck defaults to 30), `DES_MOVIES=0` (skip movies), `DES_NAME=<name>`, `DES_RECORD=0`,
`DES_GAME=game_remaster` (PC Remaster mod) or `DES_GAME=game_mod` (imported models), `LD_TEX_DUMP=1`
(dump textures for texture packs).
For example: `DES_FPS=60 ./DemonsSoulsRecomp-Setup-x86_64.AppImage play`.

Controllers: Steam Input / Proton present controllers as an Xbox pad, which the port uses. Keyboard and
mouse work as on Windows (see `PLAY.bat` for the keys).

### From a git checkout instead of the AppImage

You need Python 3.10+, git, and clang + lld 17 or newer (Debian/Ubuntu: `sudo apt install python3-venv
git clang lld llvm`). Then `sh linux/setup.sh /path/to/image.iso` and `sh linux/play.sh`.

### Steam Deck game mode

After the setup, add `~/DemonsSoulsRecomp/linux/play.sh` to Steam as a non-Steam game (Steam → Games →
Add a Non-Steam Game → Browse; set "Start in" to `~/DemonsSoulsRecomp`). Do not force a Proton version
on that shortcut: `play.sh` starts Proton itself.

## If something goes wrong

- **Logs:** `~/DemonsSoulsRecomp/logs/last_run_out.txt` and `last_run_err.txt` (the game),
  `last_run_proton.txt` (Proton's own messages), and the terminal output of the setup. The game's log
  is written there through `logs/run_game.bat`; the console window that opens with the game stays
  empty. `DS_RUN_DIRECT=1` starts the game without that batch file, with its log in the console window.
- **Stuck on a blank window** for more than a few minutes: most likely the opening movies (see
  Movies below). Close it and start with `DES_MOVIES=0`.
- **Shaders fail** (black screen, missing geometry, `D3DCompile` errors in the log): Wine's built-in
  shader compiler may not handle the game's shaders. Install Microsoft's (winetricks downloads it from
  Microsoft): `./DemonsSoulsRecomp-Setup-x86_64.AppImage play --ms-d3dcompiler`, then start again.
- **Movies:** they need a Media Foundation MPEG-2 decoder, which Proton may not have. If the game hangs
  or crashes at the logos, start with `DES_MOVIES=0`.
- **Other Proton:** `PROTONPATH=GE-Proton` (newest GE-Proton) or `PROTONPATH=/path/to/proton-folder`;
  or `DS_RUNNER=proton PROTON=/path/to/proton-folder`. More output from Proton: `PROTON_LOG=1`.
- **Setup steps** are skipped once done; after fixing a problem, just run the AppImage again.

## For testers

The most useful report says, for each step, whether it worked:

1. Distro / Steam Deck model, CPU, GPU, Mesa or NVIDIA driver version.
2. Setup: did the six steps finish? If not, the last 30 lines of the terminal.
3. First start: did Proton install? Do you see the title screen? With or without the logos/movies?
4. In game: frame rate (the window title shows it), stutters, missing or wrong graphics, sound.
5. If it crashed: the last 100 lines of `logs/last_run_err.txt`, and the AppImage's `selftest` output.

Open a GitHub issue with that. Known unknowns, roughly in the order they may bite:

| Area | Risk | Workaround |
|---|---|---|
| Shaders (D3DCompile, shader model 5.0) | Wine's own compiler may reject or mis-compile them | `play --ms-d3dcompiler` |
| Renderer features under vkd3d-proton (texture heaps, occlusion queries) | medium | report the log |
| Movies (Media Foundation MPEG-2) | likely missing in Proton | `DES_MOVIES=0` |
| Speed on a Steam Deck | 60 fps out of reach on 4 Zen 2 cores | 30 fps default |
| Timers, thread pinning, priorities under Wine | medium | report frame timing (F8 marks, `perf/`) |

## What is tested

- On Windows: the whole Linux build path except the operating system itself: Microsoft's CRT and SDK
  fetched by xwin (no Visual Studio), the game code lifted from the EBOOT, and `DemonsSoulsRecomp.exe`
  built with clang-cl + lld-link and a static C runtime (`setup/build.py` with `DS_XWIN=1`). That exe
  imports no Visual C++ runtime DLLs, only Windows system ones that Proton provides.
- On GitHub Actions (Ubuntu, `.github/workflows/linux-appimage.yml`): the AppImage is built and its
  self-test run on Ubuntu and in bare Debian and Arch Linux containers (no Python, git or compiler
  installed); started by hand with "cross_build_test", it also cross-compiles ps3recomp's whole
  runtime library, renderer included, on Linux.
- `linux/play.sh` sets the same variables as `PLAY.bat` for every frame-rate mode (checked with a stand-in
  for Wine).
- On a real Linux PC: Ubuntu 24.04, Intel i7-4770K + NVIDIA GTX 980 under Proton. Setup and the game
  run; the tutorial plays at about 57-58 fps on average in 60 fps mode, with frequent one-frame hitches
  (CPU-bound). Its first setup found the line-ending bug fixed in 6c7dca3.
- Steam Deck (AMD GPU, Mesa): set up and plays, but loads take minutes and it is not fully smooth yet.
- Not confirmed yet: Intel GPUs and AMD desktop GPUs.

## How it works (for developers)

- `linux/appimage/build-appimage.sh` makes the AppImage: python-appimage's Python with cryptography,
  CMake and Ninja; LLVM's release clang-cl/lld-link/llvm-lib/llvm-rc; xwin; a fallback git; this repo's
  `setup/`, `tools/`, `patches/`, `project/`, `linux/`, `docs/`. It refuses to package anything that
  looks like game data. `.github/workflows/linux-appimage.yml` builds and tests it.
- Licenses: everything in the AppImage is under permissive licenses except the fallback git and the
  libraries it needs (GPL-2.0 / LGPL), copied from Ubuntu. Their Ubuntu source packages are published
  with every build as `DemonsSoulsRecomp-Setup-sources.tar` (the workflow's second artifact);
  `usr/share/licenses/SOURCES.txt` inside the AppImage lists them. Python's GPL/LGPL modules (readline,
  gdbm, crypt, nis), which the kit never uses, are removed. Whoever re-hosts the AppImage has to offer
  that sources file alongside it.
- `linux/appimage/AppRun` copies the kit's scripts into the data folder and runs `setup/setup.py` there,
  then `linux/play.sh`. `selftest` checks the bundled tools (`linux/selftest.py`).
- `setup/build.py` cross-compiles when not on Windows (or with `DS_XWIN=1` on Windows): toolchain file
  `setup/clang-cl-xwin.cmake`, the SDK from `xwin splat --use-winsysroot-style` in `deps/xwin`, found
  through the `INCLUDE` / `LIB` environment variables, the C runtime linked statically (`/MT`) so Wine
  needs no Visual C++ DLLs, and no manifest step. `setup/build.py --runtime-only` builds just
  ps3recomp's runtime library (no disc needed).
- `linux/play.sh` sets the same variables as `PLAY.bat` (paths as `Z:\...` for the Windows program) and
  runs the exe through umu-launcher (`umu-run`), a Proton folder, or Wine.
