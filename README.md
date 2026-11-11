# Demon's Souls — native PC port (ps3recomp)

A native Windows build of **Demon's Souls** (PS3, USA, **BLUS-30443**). The game's PPU and SPU code is statically
recompiled to C/C++ with [ps3recomp](https://github.com/sp00nznet/ps3recomp) and runs as a normal x64 program
on a PS3 runtime and a Direct3D 12 renderer. It is not an emulator.

> **No game files are included.** This repo holds only tools, patches and build scripts. SETUP builds the game
> on your PC from **your own disc image**.

**Community Discord:** [discord.gg/gTvrZZ75G](https://discord.gg/gTvrZZ75G) for questions, setup help and
screenshots. Bug reports with a REPORT.bat zip are best as a GitHub issue. Thanks to MrSuS60 for having me in their Discord, and a special thanks to zackage7 who has been an immense help in testing and polishing.

## Status

- **The whole game is playable**, with sound, music and movies, on keyboard + mouse or an Xbox controller.
- **60 fps** is recommended (50 on a 100 Hz screen). 30, uncapped and any custom rate work too. Above 60 fps
  there are still known bugs, such as the sound drifting out of sync.
- **No online play yet.** Multiplayer comes once the game is optimised.
- **Performance:** mostly smooth on high-end PCs; work on lower-end PCs and the Steam Deck is ongoing. The full
  development log is [docs/NOTES.md](docs/NOTES.md).

Hit a stutter or crash? Press **F8** when it happens and run `REPORT.bat` afterwards
([details](#reporting-stutters-and-crashes)).

## What you need

- **Windows 10/11 x64** with a **Direct3D 12** GPU. AVX2 is used if your CPU has it (Haswell / Ryzen or newer).
- About **14 GB** free disk space.
- **Your disc image** of Demon's Souls USA (BLUS-30443): a `.iso`, a Redump `.zip`, or a dumped folder with
  `PS3_GAME` in it. An encrypted image also needs its **disc key**: the `.dkey` file from the dump, or the
  "Disc Key" line on [Redump's page for this disc](http://redump.org/disc/16199/).
- **Nothing else.** SETUP downloads what is missing into `deps\`, with no installer or admin rights: portable
  Python and Git, the PS3 keys for `EBOOT.BIN` (from [RPCS3](https://rpcs3.net)'s public source, kept in
  `%LOCALAPPDATA%`), and a portable LLVM compiler with Microsoft's SDK via
  [xwin](https://github.com/Jake-Shadle/xwin). All downloads are checksum-verified. An existing Python 3.10+,
  Git, or Visual Studio 2022 (*Desktop development with C++*) + LLVM 17+ is used instead.
- A plain folder path: no `[ ]` or `&`.

**Linux / Steam Deck** and **macOS (Apple silicon):** see their install guides below
([Linux](#linux--steam-deck), [macOS](#macos-apple-silicon)).

## Build it (one time)

1. Download the newest **[release](https://github.com/timboat/demons-souls-recomp/releases/latest)** ZIP (or
   `git clone`) and unpack it, e.g. to `C:\Games\DemonsSouls`.
2. Start **`DemonsSoulsLauncher.exe`**, press **PLAY**, and answer **Yes** to run `SETUP.bat`.
3. Give it your disc image: drag it into the window and press Enter. If it needs the disc key, SETUP opens
   Redump's page; copy the "Disc Key" line and paste it with **Ctrl+V**. **Enter** takes the suggested
   answer to every other question.
4. Wait for **All done**, then press **PLAY**.

| step | what SETUP does | time* |
|---|---|---|
| 1 | extracts and decrypts the game files into `game/` | 2–5 min |
| 2 | decrypts `EBOOT.BIN` → `EBOOT.elf` and checks it is the tested version | seconds |
| 3 | fetches ps3recomp at the tested commit and applies this port's runtime patch | < 1 min |
| 4 | recompiles ~94,000 PPU functions + 12 SPU programs into `port/` | 2–4 min |
| 5 | applies this port's edits to the recompiled code | seconds |
| 6 | compiles `DemonsSoulsRecomp.exe` and the launcher | 10–30 min |

\* on a fast 16-core PC. The compiler's full output goes to `logs\build_last.txt`. If something fails, fix
what it says and run SETUP.bat again: finished steps are skipped.

### Linux / Steam Deck

The Windows build runs through Proton (Steam's compatibility layer), built on your PC from your disc image.
It plays on Ubuntu 24.04 and the Steam Deck; the Deck is not smooth yet and loads are slow. You need a
Vulkan GPU driver, about **25 GB** free, and an internet connection for the first run.

1. Download `DemonsSoulsRecomp-Setup-x86_64.AppImage`: GitHub → **Actions** → *Linux AppImage* → the newest
   run → **Artifacts** (a zip with the AppImage inside). Make it executable (`chmod +x`, or right-click →
   Properties → Permissions → *Is executable*). On a Steam Deck, do this in desktop mode.
2. Run it. It asks for your disc image (a file picker, or drag the file in), then the disc key if needed,
   and runs the same six steps as SETUP.bat into `~/DemonsSoulsRecomp` (`DS_HOME=/other/folder` puts it
   elsewhere, e.g. on an SD card). It asks before each download, including Microsoft's SDK license. The
   first build takes 10–30 minutes on a desktop and 1–2 hours on a Steam Deck.
3. It offers to start the game; the first start sets up Proton (a few hundred MB). To play later, run the
   AppImage again (it updates and rebuilds what changed) or `~/DemonsSoulsRecomp/linux/play.sh`.

Settings are the same switches as on Windows, e.g. `DES_FPS=60 ./DemonsSoulsRecomp-Setup-x86_64.AppImage play`
(a Steam Deck defaults to 30 fps). **Steam Deck game mode:** add `~/DemonsSoulsRecomp/linux/play.sh` as a
non-Steam game, with *Start in* set to `~/DemonsSoulsRecomp` and no forced Proton version. **From a git
checkout** instead: install Python 3.10+, git, and clang + lld 17 or newer, then run
`sh linux/setup.sh /path/to/image.iso` and `sh linux/play.sh`. Troubleshooting: [docs/LINUX.md](docs/LINUX.md).

### macOS (Apple silicon)

A native arm64 build on Metal (by erikomis). **It is playable, but very behind on updates:** most of the
Windows and Linux features are missing. The Mac version will be worked on once Windows and Linux are finished.
You need about **14 GB** free.

1. Install Apple's command-line tools (`xcode-select --install`), then with [Homebrew](https://brew.sh):
   `brew install cmake ninja sdl2 glslang spirv-cross ffmpeg python@3.12` (FFmpeg is for the movies).
2. Get this repo (`git clone`, or the release ZIP) and, in its folder, run
   `DES_ISO="/path/to/Demon's Souls (USA).iso" mac/install.sh`. A Redump image also needs
   `DES_KEY=<32 hex digits or the .dkey file>`. It extracts the game, decrypts the EBOOT, recompiles and
   builds; after a failure or a quit, run it again and it continues where it stopped.
3. Play with `mac/play.sh`. There is no on-screen keyboard yet: `DES_NAME=<name> mac/play.sh` names your
   character. `DES_FPS=30` gives the console's 30 fps (60 is the default).

`mac/launcher/` has a desktop app that does all of this without a terminal (see its README). Controls,
settings and what is still missing: [docs/MACOS.md](docs/MACOS.md).

## Updating

Press **Check for updates** in the launcher. It downloads the newest release (no Git needed), rebuilds what
changed and reopens. Your game files, saves and settings are kept. Tick **Keep my build after updates** (or
`set DES_NO_REBUILD=1`) to play your current build and rebuild later with `BUILD.bat`.

**Copies from before v2026.11.03.7**, once: unpack the newest release ZIP over your folder, replacing files,
then press Play.

## Play

Start **`DemonsSoulsLauncher.exe`** and press **PLAY**. It holds every option (frame rate, resolution, mods,
fullscreen, movies, god mode, recording, keys by letter, CPU pinning) and saves them in `launcher.ini`.
*Extra settings* takes any `NAME=value` switch from this page or from an issue. `--play` starts the game
straight away, for a shortcut. Without the launcher, set the switches before running `PLAY.bat`.

| launcher option | switch | what it does |
|---|---|---|
| *Frame rate* | `DES_FPS=30\|50\|60\|unlimited\|31-240` | Auto = an even rate for your screen: 60 on 60 / 120 / 240 Hz, 50 on 100 Hz, 72 on 144 Hz, 55 on 165 Hz, 75 on 75 Hz. Game speed is right at any rate. A rate that divides your refresh rate is perfectly even; others turn vsync off. |
| *My screen has G-Sync / FreeSync* | `DES_VRR=1` | lets a variable-refresh monitor follow the frames (vsync-off frames may tear, so the monitor shows each when it is ready); Auto is then 60 at any refresh rate. Leave it off on other screens: the picture would tear. |
| *Resolution* | `DES_RES_SCALE=2` (up to 4) | renders above 1280x720; *Sharper shadows* = `LD_RES_SCALE_SHADOW=1` |
| *Game* | `DES_GAME=game_remaster` / `game_mod`, `DES_BOSS_RUSH=1` | the PC Remaster mod, your imported models (see below), or [boss rush mode](#boss-rush-mode) |
| *Dump textures* | `LD_TEX_DUMP=1` | saves every texture drawn, for texture packs |
| *Skip the intro* | `DES_SKIP_INTRO=1` | starts at PRESS START; story movies still play |
| *Keep my build after updates* | `DES_NO_REBUILD=1` | plays your current build instead of rebuilding |

Other switches: `DES_MOVIES=0` skips movies, `DES_CUT_BLEND=0` restores the original 30 fps cutscene camera,
`DES_FULLSCREEN=1` starts fullscreen.

### Controls

An Xbox (XInput) controller works when plugged in. A DualShock / DualSense needs Steam Input or DS4Windows.
Keyboard + mouse work alongside a controller; whichever you touch last takes over.

| key | action |
|---|---|
| WASD | move |
| mouse (or IJKL) | camera (click into the game to capture the mouse) |
| left mouse / Shift | attack (R1) / strong attack (R2) |
| right mouse / Ctrl | block (L1) / parry (L2) |
| Space | roll / dash / back (Circle) |
| E | interact / confirm (Cross) |
| F / R | two-hand (Triangle) / use item (Square) |
| Tab / middle mouse | lock on (R3) |
| arrows | d-pad (switch items) |
| Enter / Backspace | Start / Select |
| Esc or F1 | release the mouse (close the game with the X or Alt+F4) |
| Alt+Enter / F11 | borderless fullscreen |
| F9 | god mode (no death, HP/MP/stamina stay full) |

- **Menus:** the mouse is a pointer. Hover selects, left click confirms, right click goes back, the wheel
  scrolls, and side buttons or PageUp / PageDown are L1 / R1. `DES_POINT=0` turns pointing off;
  `PAD_MENU_MOUSE=0` turns the mouse off in menus.
- **Button icons** show keys or PS3 buttons depending on what you used last (`LD_TEX_KBM=0` = always PS3,
  `1` = always keyboard).
- **Mouse look** follows the game's invert options. `PAD_MOUSE_LOOK_SENS=0.0012` sets the sensitivity;
  `PAD_MOUSE_LOOK=0` restores the old stick-style mouse.
- **Keys go by position**, so AZERTY uses ZQSD. `PAD_KEYS_BY_LETTER=1` = by letter.
- **Change any key** in the launcher: **Controls**, click a slot, press the key or mouse button (right-click clears
  it). The button prompts and the title's *PRESS ENTER KEY* follow your keys.

Saves go to `gamedata/`, and logs to `logs/`; they grow ~600 MB an hour, and the previous run is kept.

### Boss rush mode

*Game: Boss rush* in the launcher (or `DES_BOSS_RUSH=1 linux/play.sh`; not on macOS yet). Make a new character:
you skip the tutorial and start in the Nexus in soul form, with 7,000 souls and every trader there. Boldwin also
sells every weapon and shield, every armour piece and ring, every upgrade material, Turpentine and Firebombs,
priced by tier: the best weapons 40,000-75,000, top armour sets 30,000-50,000, rings 5,000-50,000, and items normal
shops sell at their usual price, so a run's boss souls buy a build but not everything.
- **Pick a boss:** each world's archstone offers that world's next unbeaten boss and puts you at its fog gate.
- **After a kill:** the boss's archstone offers the next boss (*Fight the Tower Knight?*) or *Return to the Nexus?*
- **Dying:** you go back to the same boss's fog in body form.
- **The Nexial Binding** takes you back to the Nexus and keeps your souls (its description says so too).
- **The run** ends when King Allant dies; his fight and the ending are the game's own.
- **The timer** at the bottom of the screen appears once you are in the game. It starts at the first fog and pauses
  on loading screens, cutscenes and the title screen (and while the game is closed). Splits and the final time go to
  `bossrush\splits.txt` and `bossrush\results.txt`.
- **Boss rush souls** in the launcher (2x by default; `DES_BR_SOULS=2`, 3, 5 or 10): every enemy and boss gives that many times its
  souls. The timer shows *Souls x2* and so on when it is not 1x, so runs and videos say which they used.

It has its own saves in `bossrush\`, so your normal saves are never used. Play makes `game_bossrush\` from your
game files the first time, in seconds and with no extra disk space (again when you change the souls setting).

## Reporting stutters and crashes

Every run records frame timing (about 25 MB an hour, no visible cost; the last 10 sessions stay in `perf\`).

1. **Press F8** right after a stutter or slowdown. Each press marks that moment.
2. After quitting or a crash, press **Report a problem** in the launcher (or run **`REPORT.bat`**). It packs
   the session into one zip and opens GitHub's *New issue* page.
3. Pick the *Stutter / slowdown* or *Crash / bug* template, drag the zip in, and say where you were.

The zip holds a frame-pacing summary (`report.txt`), the recording (`perf.txt`), your system info
(`system.txt`) and the end of the game log (`log_tail.txt`). Your Windows user name is removed. Untick
*Record frame timing* (or `set DES_RECORD=0`) to play without recording.

## Mods (optional)

**PC Remaster mod** by fromsoftserve (Nexus Mods, Demon's Souls mod 106): download its zip, then run the line
below. It makes `game_remaster/` from hard links, so it uses no extra space and `game/` is unchanged.

```bat
.venv\Scripts\python tools\install_remaster.py "path\to\the mod.zip" --apply
```

**Texture packs:**
1. Tick *Dump textures* and play; textures land in `textures\dump\` as `<KEY>_<w>x<h>_<format>.png`.
2. Put an edited or larger file whose name starts with the same KEY in `textures\replace\`. `.dds` (DXT, BC7,
   BC4, RGBA) loads faster than PNG.

Details are in `textures\README.txt`.

**Models:**
- Export armour, weapons, characters or map pieces to glTF, edit them in Blender, and import them back.
- Import writes `game_mod\` from hard links; play it with *Game: My models*, and delete the folder to undo.
- Edit the `_l` low-detail copy too. Rules are in `models\README.txt`.

```
.venv\Scripts\python tools\flver_tool.py export game\PS3_GAME\USRDIR\PARTS\bd_f_5010.partsbnd.dcx
.venv\Scripts\python tools\flver_tool.py import models\BD_F_5010\edited.glb game\PS3_GAME\USRDIR\PARTS\bd_f_5010.partsbnd.dcx
```

Packs and models are the game's art; share them only where that is allowed.

## Repo layout

```
SETUP.bat / BUILD.bat        one-time setup / rebuild
DemonsSoulsLauncher.exe      the settings window (source in project/launcher/)
PLAY.bat / REPORT.bat        start the game / pack a bug report
setup/                       setup pipeline, toolchain finder, Linux cross toolchain
project/                     CMake project
patches/                     ps3recomp-local.patch (runtime, on ps3recomp @ 4e8f3ca) and lifted-code.patch (game code)
tools/                       disc extraction, SPU lifting, perf report, mod installer, model tool
docs/NOTES.md                development log: every fix, why, and how it was measured
linux/, mac/                 Linux / Steam Deck kit and macOS build (docs/LINUX.md, docs/MACOS.md)
```

Everything SETUP produces (`game/`, `port/`, `deps/`, `.venv/`, saves, logs) is git-ignored.
**Never commit or share those**: they are the game.

## Troubleshooting

- **"could not get the keys … using RPCS3 instead":**
  - The key download failed, so SETUP falls back to RPCS3; you can also run SETUP again later.
  - If RPCS3 then fails ("did not write EBOOT.elf"), close any open RPCS3 window and retry. Or decrypt
    `game\PS3_GAME\USRDIR\EBOOT.BIN` by hand with RPCS3's *Utilities → Decrypt PS3 Binaries*; install the
    firmware first if it asks.
  - In Windows Sandbox or a VM, RPCS3 can crash. Decrypt on another PC, copy `EBOOT.elf` into that folder,
    and rerun SETUP.
- **"EBOOT.BIN is not the tested one":** only the USA disc (BLUS-30443) is supported.
- **Build tools not found:** rerun SETUP or BUILD and allow the portable compiler download. Or install VS 2022
  Build Tools with C++ and LLVM (`winget install LLVM.LLVM`), or set `LLVM_DIR`.
- **Setup seems stuck:** one file can take a minute; see `logs\build_last.txt`. If nothing moves for many
  minutes, press Enter once.
- **Black window or crash on start:** check the end of `logs\last_run_err.txt`.
- **Uneven frames at 100+ fps in busy areas:** use 50 or 60 fps. On CPUs with two core complexes the game
  pins itself to the one with the largest L3 cache; `DES_AFFINITY=0` turns that off.
- **Something is briefly black or missing the first time you see it:** its shaders are compiling in the
  background. `LD_PSO_ASYNC=0` waits instead.
- **"needs AVX2":** the build was made on another PC. Run BUILD.bat on this one, or `set DS_AVX2=0` before
  building.
- **Online:** the official servers closed in 2018. The game starts straight in offline mode
  (`DES_AUTO_OFFLINE=0` shows the old boxes).

## Credits and license

- [ps3recomp](https://github.com/sp00nznet/ps3recomp) by Ned Heller / sp00nznet (MIT): the recompiler and runtime.
- [RPCS3](https://rpcs3.net): its public source code provides the PS3 keys, it is the decryption fallback, and
  it is the reference for PS3 behaviour.
- erikomis: the macOS build and launcher.
- The *PC Remaster* mod is by fromsoftserve.

This repo's code and patches are MIT-licensed ([LICENSE](LICENSE)). Demon's Souls is © Sony Interactive
Entertainment / FromSoftware. This project is not affiliated with or endorsed by them and contains none of
their files. Buy the game and dump your own disc.
