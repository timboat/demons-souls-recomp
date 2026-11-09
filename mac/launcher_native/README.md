# DemonsSoulsLauncher.app

The launcher window for the macOS build: the counterpart of `project/launcher/` (DemonsSoulsLauncher.exe).
One file of plain AppKit (`launcher.m`), nothing to install.

```sh
mac/launcher_native/build.sh        # -> DemonsSoulsLauncher.app in the port's folder
```

`mac/rebuild.sh build` runs that after the game is built.

- Settings are kept in `launcher.ini` in the port's folder, in the Windows launcher's format. Keys only
  the Windows launcher has are left as they are; the Mac-only ones start with `mac_`.
- PLAY sets the variables `mac/play.sh` reads and runs it. A non-zero exit offers a report.
- Controls: `[controls]` in `launcher.ini`, the same action and key names as on Windows, so
  `tools/kbm_icons.py` draws the same button icons. Before each Play they are written as a
  `PS3_INPUT_MAP` file (`cache/launcher_input.toml`); its `[mouse]` section is copied from `mac/input.toml`.
- Check for updates: `git fetch`, then, if you agree and the folder has no changes of its own,
  `git pull --ff-only` and `mac/rebuild.sh toolkit lift build` in Terminal.
- Report a problem: the first and last 400 lines of both logs and this Mac's specs in
  `logs/report_<date>.zip`, with your user name and home folder taken out.

For tests: `DES_LAUNCHER_INI=<file>` moves `launcher.ini`; `--snapshot <png>` and
`--snapshot-controls <png>` draw a window into a file and quit; `--report-only` makes the zip and prints
its path; `--play` starts the game with the saved settings and no window.

`mac/launcher/` is a separate, larger Tauri launcher (install from the disc image, saves, rebuilds).
