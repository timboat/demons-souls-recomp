#!/bin/zsh
# Builds DemonsSoulsLauncher.app (launcher.m, plain AppKit) into the port's folder, next to mac/ --
# the Mac counterpart of DemonsSoulsLauncher.exe next to PLAY.bat. mac/rebuild.sh's build step runs
# this; on its own:  mac/launcher_native/build.sh [<folder the .app goes into>]
# Needs only Apple's command-line tools. The app is ad-hoc signed and holds nothing from the game: the
# banner is read from your own game/PS3_GAME/ICON0.PNG when the window opens.
set -e
here=${0:A:h}
root=${here:h:h}
dest=${1:-$root}
app="$dest/DemonsSoulsLauncher.app"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/app/Contents/MacOS" "$tmp/app/Contents/Resources"
xcrun clang -fobjc-arc -O2 -Wall -Wno-deprecated-declarations -arch arm64 -mmacosx-version-min=12.0 \
    -framework Cocoa "$here/launcher.m" -o "$tmp/app/Contents/MacOS/DemonsSoulsLauncher"
# the flame mac/launcher/scripts/make_icon.py draws (not game art)
icon="$root/mac/launcher/src-tauri/icons/icon.icns"
[ -f "$icon" ] && cp "$icon" "$tmp/app/Contents/Resources/icon.icns"
version=$(tr -d ' \n\r' < "$root/VERSION" 2>/dev/null || true)
version=${${version#v}:-0}
cat > "$tmp/app/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Demon's Souls Launcher</string>
    <key>CFBundleDisplayName</key><string>Demon's Souls Launcher</string>
    <key>CFBundleIdentifier</key><string>io.github.timboat.demons-souls-launcher</string>
    <key>CFBundleExecutable</key><string>DemonsSoulsLauncher</string>
    <key>CFBundleIconFile</key><string>icon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$version</string>
    <key>CFBundleVersion</key><string>$version</string>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSPrincipalClass</key><string>NSApplication</string>
</dict>
</plist>
EOF
codesign --force --sign - "$tmp/app" >/dev/null 2>&1 || print -r -- "  (not signed: codesign failed; the app still runs from this folder)"
rm -rf "$app"
mkdir -p "$dest"
mv "$tmp/app" "$app"
print -r -- "  built: $app"
