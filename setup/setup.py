"""One-shot setup: your Demon's Souls disc image -> a native Windows build.

Run through SETUP.bat (which makes the Python environment). Every step is skipped when its
output is already there, so after a failure just fix the cause and run SETUP.bat again. After an
update of this repo, steps 3 and 5 re-apply the patches that changed (setup/patch_sync.py).

  1. extract the game files from the disc image          -> game/
  2. decrypt EBOOT.BIN (SELF -> ELF), with the PS3 keys   -> game/PS3_GAME/USRDIR/EBOOT.elf
     from RPCS3's public source (RPCS3 itself if that fails)
  3. fetch ps3recomp at the tested commit + our patches   -> deps/ps3recomp
  4. recompile the game's PPU and SPU code to C/C++       -> port/recompiled, port/spu
  5. apply this port's edits to the recompiled code       (patches/lifted-code.patch; Europe: lifted-code-eu.patch)
  6. build DemonsSoulsRecomp.exe                          -> port/build_opt (setup/build.py)

usage: SETUP.bat [image.iso | image.zip | dumped disc folder] [--key HEX | --key file.dkey]
                 [--rpcs3 path\\to\\rpcs3.exe] [--jobs N]

On Linux the same steps run from linux/setup.sh or the AppImage (docs/LINUX.md); step 2's fallback
is RPCS3's Linux AppImage and step 6 cross-compiles the Windows exe (setup/build.py).
"""
import glob, hashlib, json, os, shutil, subprocess, sys, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'setup'))
import build                                                    # noqa: E402
import patch_sync                                               # noqa: E402
import region                                                   # noqa: E402

# Every Python tool this runs (the lifter, patch tools) reads and writes UTF-8, whatever the Windows code page:
# with cp932 (Japanese) or similar the lift died writing an em dash (UnicodeEncodeError).
os.environ.setdefault('PYTHONUTF8', '1')

GAME = os.path.join(ROOT, 'game')
USRDIR = os.path.join(GAME, 'PS3_GAME', 'USRDIR')
PORT = os.path.join(ROOT, 'port')
PS3RECOMP = os.path.join(ROOT, 'deps', 'ps3recomp')
CONFIG = os.path.join(ROOT, 'setup', 'local_config.json')       # remembered paths (git-ignored)

PS3RECOMP_URL = 'https://github.com/sp00nznet/ps3recomp.git'
PS3RECOMP_COMMIT = '4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514'   # v0.18.0, what the patches are made against
# What to tell you to run: the Linux launchers (linux/setup.sh, the AppImage) set these
SETUP_NAME = os.environ.get('DS_SETUP_NAME') or 'SETUP.bat'
PLAY_HINT = os.environ.get('DS_PLAY_HINT') or 'Double-click DemonsSoulsLauncher.exe to play.'
RPCS3_LINUX_RELEASES = 'https://api.github.com/repos/RPCS3/rpcs3-binaries-linux/releases/latest'
RPCS3_WIN_RELEASES = 'https://api.github.com/repos/RPCS3/rpcs3-binaries-win/releases/latest'
# 7-Zip's own standalone 7zr.exe: unpacks RPCS3's .7z where Windows' tar.exe cannot (Windows 10 and Windows
# 11 before 23H2 ship a tar without LZMA; RPCS3's archive also uses BCJ2, which no pip package reads)
SEVENZR_URL = 'https://github.com/ip7z/7zip/releases/download/26.05/7zr.exe'
SEVENZR_SHA256 = '9bf582b894dfa665f852d7e9112b02290a1c303c2d95a21fcdc41ffcb03143b7'
VCRT_MIN = (14, 40)   # RPCS3's Windows builds are made with Visual C++ 14.5x; its runtime must not be older
VCREDIST_URL = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'   # Microsoft's own link to the newest x64 runtime

# The release (USA BLUS-30443 or Europe BLES-00932, setup/region.py) decides the EBOOT hashes, the lift settings,
# the SPURS job offsets, Redump's page for the disc (its "Disc Key" line is the key an encrypted Redump image
# needs; opened for the player when there is no .dkey, the key itself is never part of this kit) and which
# patch carries the port's edits to the recompiled code. Read from the game's PARAM.SFO; the US one until
# there is a game folder.
REGION = R = EBOOT_BIN_SHA256 = EBOOT_ELF_SHA256 = SPURS_JOBS = LIFT_ARGS = REDUMP_PAGE = LIFTED_PATCH = None


def set_region(key):
    global REGION, R, EBOOT_BIN_SHA256, EBOOT_ELF_SHA256, SPURS_JOBS, LIFT_ARGS, REDUMP_PAGE, LIFTED_PATCH
    REGION, R = key, region.REGIONS[key]
    EBOOT_BIN_SHA256, EBOOT_ELF_SHA256 = R['eboot_bin_sha256'], R['eboot_elf_sha256']
    SPURS_JOBS, LIFT_ARGS, REDUMP_PAGE = R['spurs_jobs'], R['lift_args'], R['redump_page']
    LIFTED_PATCH = R['lifted_patch']
    patch_sync.LIFTED_PATCH = os.path.join(ROOT, 'patches', LIFTED_PATCH)


set_region(region.current(ROOT)[0])


def say(msg=''):
    print(msg, flush=True)


def step(n, msg):
    say(f'\n=== [{n}/6] {msg}')


def fail(msg):
    say('\nERROR: ' + msg)
    sys.exit(1)


def ask(prompt):
    if os.environ.get('DS_ASSUME_YES') == '1' and '[Y/n]' in prompt:   # tests: take the default
        say(prompt + '(yes: DS_ASSUME_YES)')
        return ''
    try:
        t = input(prompt).strip().strip('"')
    except EOFError:
        fail(f'no answer (input closed) -- run {SETUP_NAME} in a console window')
    if os.name != 'nt':   # what Linux terminals paste for a dropped file: 'quoted', file://, a\ b
        t = t.strip("'")
        if t.startswith('file://'):
            t = urllib.parse.unquote(t[7:])
        if not os.path.exists(t) and '\\' in t and os.path.exists(t.replace('\\', '')):
            t = t.replace('\\', '')
    return t


def pick_file(title, filters):
    """A file dialog on a Linux desktop (zenity or kdialog, whichever is there; a Steam Deck in desktop
    mode has kdialog). None when there is none or it was cancelled -- then the path is typed."""
    if os.name == 'nt' or not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return None
    pats = ' '.join(f'*.{e} *.{e.upper()}' for e in filters)
    for cmd in (['zenity', '--file-selection', f'--title={title}', f'--file-filter={title} | {pats}',
                 '--file-filter=All files | *'],
                ['kdialog', '--title', title, '--getopenfilename', os.path.expanduser('~'), f'{title} ({pats})']):
        if shutil.which(cmd[0]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            except (OSError, subprocess.TimeoutExpired):
                continue
            p = r.stdout.strip()
            return p if r.returncode == 0 and os.path.isfile(p) else None
    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_config():
    try:
        return json.load(open(CONFIG))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    json.dump(cfg, open(CONFIG, 'w'), indent=2)


def run(cmd, cwd=None, log=None):
    say('  > ' + ' '.join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
    build.cpu_ramp()   # the lift's workers start on a few cores, all of them a few seconds later
    if log:
        with open(log, 'w') as f:
            r = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            fail(f'{os.path.basename(cmd[1] if cmd[0] == sys.executable else cmd[0])} failed -- see {log}')
    elif subprocess.run(cmd, cwd=cwd).returncode:
        fail('command failed: ' + ' '.join(cmd))


def find_eboot_elf():
    for n in ('EBOOT.elf', 'EBOOT.ELF'):
        p = os.path.join(USRDIR, n)
        if os.path.isfile(p):
            return p
    return None


# --- 1. game files -----------------------------------------------------------------------------

def get_image(args, cfg):
    src = args.get('image') or cfg.get('image')
    if not src or not os.path.exists(src):
        say('  Pick your Demon\'s Souls disc image (USA BLUS-30443 or Europe BLES-00932; .iso or Redump .zip)...')
        src = pick_file("Demon's Souls disc image", ('iso', 'zip')) or src
    while not src or not os.path.exists(src):
        if src:
            say(f'  not found: {src}')
        say('  Drag your Demon\'s Souls (USA BLUS-30443 or Europe BLES-00932) disc image -- .iso, a Redump .zip,')
        say('  or a dumped disc folder that has PS3_GAME in it -- into this window and press Enter:')
        src = ask('  > ')
    return os.path.abspath(src)


def copy_folder_dump(src):
    if os.path.isdir(os.path.join(src, 'PS3_GAME')):
        base = src
    else:
        fail(f'{src} has no PS3_GAME folder')
    say(f'  copying the game files from {base} (hard links where possible)')
    n = 0
    for d, _, fs in os.walk(base):
        rel = os.path.relpath(d, base)
        if rel.split(os.sep)[0] == 'PS3_UPDATE':
            continue
        os.makedirs(os.path.join(GAME, rel), exist_ok=True)
        for f in fs:
            s, t = os.path.join(d, f), os.path.join(GAME, rel, f)
            if os.path.exists(t):
                continue
            try:
                os.link(s, t)
            except OSError:
                shutil.copy2(s, t)
            n += 1
    say(f'  {n} files')


def disc_key(args, image, needs_key, check):
    if not needs_key:
        say('  image is already decrypted, no disc key needed')
        return None
    import iso_extract
    cands = []
    if args.get('key'):
        cands.append(args['key'])
    stem = os.path.splitext(image)[0]
    for ext in ('.dkey', '.key', '.txt'):
        if os.path.isfile(stem + ext):
            cands.append(stem + ext)
    d = os.path.dirname(image)
    cands += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith('.dkey')]
    for c in cands:
        try:
            k = iso_extract.parse_key(c)
        except (ValueError, OSError):
            continue
        if check(k):
            say(f'  disc key OK ({os.path.basename(c) if os.path.isfile(c) else "from --key"})')
            return k
    say('  This image is encrypted (as Redump images are) and needs its disc key: the 32 hex digits')
    say('  that came with your dump (a .dkey file next to the .iso), or the "Disc Key" on the Redump')
    say(f'  page for your disc: {REDUMP_PAGE} (Demon\'s Souls {R["name"]}, {R["serial"]}, version 01.00).')
    if os.environ.get('DS_NO_BROWSER') != '1':
        try:
            import webbrowser
            if webbrowser.open(REDUMP_PAGE):
                say('  That page is now open in your browser: copy the long code on its "Disc Key" line and')
                say('  paste it here with Ctrl+V.')
        except Exception:
            pass
    while True:
        t = ask('  Disc key (or drag the .dkey file here): ')
        try:
            k = iso_extract.parse_key(t)
        except (ValueError, OSError) as e:
            say(f'  {e}'); continue
        if check(k):
            return k
        say('  That key does not decrypt this disc. Check it and try again.')


def use_release(title_id):
    key = region.from_title_id(title_id)
    if key:
        set_region(key)
        say(f'  Demon\'s Souls {R["name"]} ({R["serial"]})')
    else:
        set_region(region.DEFAULT)
        say(f'  WARNING: this disc is {title_id or "not recognised"}; this port supports Demon\'s Souls USA'
            ' (BLUS-30443) and Europe (BLES-00932). Going on as for the USA disc.')


def step_game(args, cfg):
    step(1, 'game files')
    if os.path.isfile(os.path.join(USRDIR, 'EBOOT.BIN')) and os.path.isfile(os.path.join(GAME, '.extracted')):
        say('  already extracted'); return
    image = get_image(args, cfg)
    cfg['image'] = image; save_config(cfg)
    if os.path.isdir(image):
        sfo = os.path.join(image, 'PS3_GAME', 'PARAM.SFO')
        use_release(region.sfo_title_id(open(sfo, 'rb').read()) if os.path.isfile(sfo) else None)
        copy_folder_dump(image)
    else:
        import iso_extract
        use_release(iso_extract.title_id(image))
        needs_key, check = iso_extract.probe(image)
        key = disc_key(args, image, needs_key, check)
        say('  extracting all game files (about 8 GB, a few minutes)...')
        iso_extract.extract(image, GAME, ['--all'], key)
        say('  restoring the real file names from the disc\'s UDF file system...')
        run([sys.executable, os.path.join(ROOT, 'tools', 'udf_rename.py'), image, GAME])
    if not os.path.isfile(os.path.join(USRDIR, 'EBOOT.BIN')):
        fail('no PS3_GAME/USRDIR/EBOOT.BIN after extraction')
    open(os.path.join(GAME, '.extracted'), 'w').write(image + '\n')


# --- 2. EBOOT.BIN -> EBOOT.elf -----------------------------------------------------------------

def find_rpcs3(args, cfg):
    """rpcs3.exe on Windows; on Linux the rpcs3 command or RPCS3's AppImage (in deps/rpcs3,
    ~/Applications or ~/Downloads, where people keep AppImages)."""
    cands = [args.get('rpcs3'), os.environ.get('RPCS3'), cfg.get('rpcs3')]
    if os.name == 'nt':
        cands.append(os.path.join(ROOT, 'deps', 'rpcs3', 'rpcs3.exe'))
    else:
        for d in (os.path.join(ROOT, 'deps', 'rpcs3'), '~/Applications', '~/Downloads'):
            cands += sorted(glob.glob(os.path.join(os.path.expanduser(d), '[Rr][Pp][Cc][Ss]3*.AppImage')),
                            reverse=True)
    cands.append(shutil.which('rpcs3'))
    for c in cands:
        if c and os.path.isdir(c):
            inner = [os.path.join(c, 'rpcs3.exe' if os.name == 'nt' else 'rpcs3')]
            inner += sorted(glob.glob(os.path.join(c, '*.AppImage')), reverse=True)
            c = next((i for i in inner if os.path.isfile(i)), None)
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def download_rpcs3_windows():
    """Windows: the newest RPCS3 build from RPCS3's own GitHub releases (checked against the sha256 they
    publish), unpacked into deps/rpcs3 by Windows' own tar.exe (it reads .7z)."""
    try:
        rel = json.load(urllib.request.urlopen(RPCS3_WIN_RELEASES, timeout=60))
        a = next(a for a in rel['assets'] if a['name'].endswith('_win64_msvc.7z'))
        want = urllib.request.urlopen(a['browser_download_url'] + '.sha256', timeout=60).read().decode().split()[0].lower()
    except (OSError, ValueError, KeyError, StopIteration, IndexError) as e:
        say(f'  could not look up the RPCS3 download ({e})')
        return None
    d = os.path.join(ROOT, 'deps', 'rpcs3')
    os.makedirs(d, exist_ok=True)
    arc = os.path.join(ROOT, 'deps', a['name'])
    say(f'  downloading {a["name"]} ({a["size"] >> 20} MB) from {a["browser_download_url"]}')
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(a['browser_download_url'], timeout=120) as r, open(arc, 'wb') as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                h.update(b)
                f.write(b)
    except OSError as e:
        say(f'  download failed: {e}')
        return None
    try:
        if h.hexdigest() != want:
            say('  the RPCS3 download does not match its checksum; not using it')
            return None
        tar = os.path.join(sysdir(), 'tar.exe')
        if os.environ.get('DS_TEST_NO_TAR') == '1':   # tests: as on Windows 10, whose tar cannot read RPCS3's .7z
            tar = ''
        if not (tar and os.path.isfile(tar) and subprocess.run([tar, '-xf', arc, '-C', d], stderr=subprocess.DEVNULL).returncode == 0):
            say('  Windows\' own tar cannot unpack it here (no LZMA before Windows 11 23H2): using 7-Zip\'s 7zr.exe')
            z = os.path.join(ROOT, 'deps', '7zr.exe')
            try:
                data = urllib.request.urlopen(SEVENZR_URL, timeout=120).read()
            except OSError as e:
                say(f'  downloading 7zr.exe failed: {e}')
                return None
            if hashlib.sha256(data).hexdigest() != SEVENZR_SHA256:
                say('  7zr.exe does not match its checksum; not using it')
                return None
            with open(z, 'wb') as f:
                f.write(data)
            if subprocess.run([z, 'x', arc, '-o' + d, '-y'], stdout=subprocess.DEVNULL).returncode:
                say(f'  could not unpack {a["name"]}')
                return None
    finally:
        os.remove(arc)
    exe = os.path.join(d, 'rpcs3.exe')
    return exe if os.path.isfile(exe) else None


def sysdir():
    """The 64-bit System32 (a 32-bit Python sees SysWOW64 there; Sysnative is the real one)."""
    w = os.environ.get('SystemRoot', r'C:\Windows')
    n = os.path.join(w, 'Sysnative')
    return n if os.path.isdir(n) else os.path.join(w, 'System32')


def file_version(p):
    """(major, minor) of a Windows file's version resource, or None."""
    try:
        import ctypes
        from ctypes import wintypes
        v = ctypes.windll.version
        size = v.GetFileVersionInfoSizeW(p, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not v.GetFileVersionInfoW(p, 0, size, buf):
            return None
        ptr, n = ctypes.c_void_p(), wintypes.UINT()
        if not v.VerQueryValueW(buf, '\\', ctypes.byref(ptr), ctypes.byref(n)):
            return None
        ffi = ctypes.cast(ptr, ctypes.POINTER(wintypes.DWORD * 4)).contents   # VS_FIXEDFILEINFO
        return ffi[2] >> 16, ffi[2] & 0xFFFF
    except (OSError, AttributeError, ValueError):
        return None


def vc_versions():
    names = ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
    return [file_version(os.path.join(sysdir(), n)) if os.path.isfile(os.path.join(sysdir(), n)) else None for n in names]


def vc_current():
    if os.environ.get('DS_TEST_NO_VCRT') == '1':   # tests: act as if the runtime were missing
        return False
    return all(v is not None and v >= VCRT_MIN for v in vc_versions())


def ps(cmd, **env):
    """A PowerShell one-liner with its paths passed through the environment (no quoting, no wildcards)."""
    return subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', cmd],
                          env=dict(os.environ, **env)).returncode


def install_vcredist(run=True):
    """Without winget: Microsoft's own installer from Microsoft's own link, used only if Authenticode says it is
    validly signed by Microsoft; run elevated (Windows asks once). run=False: download and check only (tests)."""
    exe = os.path.join(ROOT, 'deps', 'vc_redist.x64.exe')
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    say(f'  downloading Microsoft\'s Visual C++ runtime installer from {VCREDIST_URL}')
    try:
        with urllib.request.urlopen(VCREDIST_URL, timeout=120) as r, open(exe, 'wb') as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except OSError as e:
        say(f'  download failed: {e}')
        return False
    try:
        if ps("$s = Get-AuthenticodeSignature -LiteralPath $env:DS_FILE; "
              "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -like '*O=Microsoft Corporation*') "
              "{ exit 0 } else { Write-Host ('  not signed by Microsoft: ' + $s.Status); exit 1 }", DS_FILE=exe):
            say('  the download is not a Microsoft-signed installer; not running it')
            return False
        if not run:
            return True
        say('  installing it (Windows asks you to allow Microsoft\'s installer to make changes) ...')
        # a "No" at the Windows prompt makes Start-Process throw: report it as 1223 (ERROR_CANCELLED), not as 0
        rc = ps("try { $p = Start-Process -FilePath $env:DS_FILE -ArgumentList '/install','/passive','/norestart' "
                "-Verb RunAs -Wait -PassThru -ErrorAction Stop; exit $p.ExitCode } catch { exit 1223 }", DS_FILE=exe)
        if rc == 1223:
            say('  the Windows prompt was answered with No, so the runtime was not installed')
            return False
        if rc not in (0, 3010, 1638):   # 3010: done, restart later; 1638: a newer one is already there
            say(f'  the installer stopped (code {rc})')
            return False
        if rc == 3010:
            say('  installed; Windows wants a restart before it is used')
        return True
    finally:
        try:
            os.remove(exe)
        except OSError:
            pass


def vc_runtime_ok(who='RPCS3'):
    """RPCS3's Windows build (and xwin.exe, build.py) needs a recent Microsoft Visual C++ runtime (MSVCP140.dll and friends), which
    most PCs have from games and other programs. Install Microsoft's when it is missing or too old: with winget
    when there is one, else Microsoft's installer straight from Microsoft (Windows Sandbox has no winget)."""
    if vc_current():
        return True
    have = vc_versions()[0]
    say(f'  {who} needs the Microsoft Visual C++ runtime ' +
        (f'{VCRT_MIN[0]}.{VCRT_MIN[1]} or newer (this PC has {have[0]}.{have[1]}).' if have else 'which is not installed on this PC.'))
    if ask('  Install it now (Microsoft\'s own installer, about 25 MB)? [Y/n] ').lower() != 'n':
        if shutil.which('winget') and os.environ.get('DS_TEST_NO_WINGET') != '1' and subprocess.run(
                ['winget', 'install', '-e', '--id', 'Microsoft.VCRedist.2015+.x64',
                 '--accept-package-agreements', '--accept-source-agreements']).returncode == 0 and vc_current():
            return True
        if install_vcredist():
            if vc_current():
                say('  Visual C++ runtime installed')
                return True
            say('  Restart Windows, then press Play (or run the setup) again: finished steps are skipped.')
            return False
    say(f'  Install it from {VCREDIST_URL} and run the setup again.')
    return False


def download_rpcs3():
    """Linux: the newest RPCS3 AppImage from RPCS3's own GitHub releases -> deps/rpcs3."""
    try:
        rel = json.load(urllib.request.urlopen(RPCS3_LINUX_RELEASES, timeout=60))
        a = next(a for a in rel['assets'] if a['name'].endswith('_linux64.AppImage'))
    except (OSError, ValueError, KeyError, StopIteration) as e:
        say(f'  could not look up the RPCS3 download ({e})')
        return None
    out = os.path.join(ROOT, 'deps', 'rpcs3', a['name'])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    say(f'  downloading {a["name"]} ({a["size"] >> 20} MB) from {a["browser_download_url"]}')
    try:
        with urllib.request.urlopen(a['browser_download_url'], timeout=120) as r, open(out + '.part', 'wb') as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except OSError as e:
        say(f'  download failed: {e}')
        return None
    os.replace(out + '.part', out)
    os.chmod(out, 0o755)
    return out


def decrypt_without_rpcs3(eboot, tested_bin):
    """EBOOT.BIN -> EBOOT.elf in Python (docs/NOTES.md fix 97): tools/fetch_keys.py downloads the PS3's application
    keys from RPCS3's public source (one file at a pinned commit, checked against its SHA-256) into a private file
    outside this folder, and tools/decrypt_self.py decrypts with them -- byte-identical to rpcs3 --decrypt. No
    emulator download, no Vulkan driver, no administrator problems. False: use RPCS3 as before."""
    fetch = os.path.join(ROOT, 'tools', 'fetch_keys.py')
    dec = os.path.join(ROOT, 'tools', 'decrypt_self.py')
    if not (os.path.isfile(fetch) and os.path.isfile(dec)):
        return False
    say('  The game\'s EBOOT.BIN is a signed+encrypted PS3 executable (SELF). It is decrypted with the PS3\'s')
    say('  application keys, which RPCS3 (the PS3 emulator, open source) publishes in its source code.')
    if ask('  Download that key file from RPCS3\'s GitHub now (one small file, checked against its SHA-256;'
           ' the keys go to a private file outside this folder)? [Y/n] ').lower() == 'n':
        return False
    try:
        r = subprocess.run([sys.executable, fetch], capture_output=True, text=True, timeout=180,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        say(f'  could not get the keys ({e}); using RPCS3 instead')
        return False
    keys = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ''
    if not keys or not os.path.isfile(keys):
        say('  could not get the keys (' + (r.stderr.strip().splitlines() or ['no output'])[-1] + '); using RPCS3 instead')
        return False
    out = os.path.join(USRDIR, 'EBOOT.elf')
    try:
        r = subprocess.run([sys.executable, dec, eboot, '-o', out, '--keys', keys], capture_output=True, text=True,
                           timeout=300, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        r = None
        say(f'  the decrypt did not run ({e})')
    if not r or r.returncode or not os.path.isfile(out):
        if r is not None:
            say('  the decrypt failed (' + ((r.stderr or r.stdout).strip().splitlines() or ['no output'])[-1] + ')')
        if os.path.isfile(out):
            os.remove(out)
        say('  using RPCS3 instead')
        return False
    if tested_bin and sha256(out) != EBOOT_ELF_SHA256:   # the tested EBOOT.BIN must give the tested EBOOT.elf
        os.remove(out)
        say('  the decrypted EBOOT.elf is not the expected one; using RPCS3 instead')
        return False
    say('  decrypted without RPCS3')
    return True


def step_decrypt(args, cfg):
    step(2, 'decrypt EBOOT.BIN')
    eboot = os.path.join(USRDIR, 'EBOOT.BIN')
    h = sha256(eboot)
    if h != EBOOT_BIN_SHA256:
        say(f'  WARNING: EBOOT.BIN is not the tested one (sha256 {h}).')
        say(f'  This port is made for Demon\'s Souls {R["name"]} {R["serial"]} version 1.00 as on the disc'
            ' (or the other supported release);')
        say('  the patches will most likely not apply to another region or an updated EBOOT.')
        if ask('  Continue anyway? [y/N] ').lower() != 'y':
            sys.exit(1)
    elf = find_eboot_elf()
    if not elf and not args.get('rpcs3') and decrypt_without_rpcs3(eboot, h == EBOOT_BIN_SHA256):
        elf = find_eboot_elf()
    if not elf:
        rpcs3 = find_rpcs3(args, cfg)
        if not rpcs3 and os.name == 'nt':
            say('  The game\'s EBOOT.BIN is a signed+encrypted PS3 executable (SELF); RPCS3 (the PS3')
            say('  emulator, open source) decrypts it, once. It is not part of this kit.')
            if ask('  Download RPCS3 from its GitHub releases now (~40 MB, into deps\\rpcs3)? [Y/n] ').lower() != 'n':
                rpcs3 = download_rpcs3_windows()
        if rpcs3 and os.name == 'nt' and not vc_runtime_ok():
            sys.exit(1)
        if not rpcs3 and os.name != 'nt':
            say('  The game\'s EBOOT.BIN is a signed+encrypted PS3 executable (SELF); RPCS3 (the PS3')
            say('  emulator, open source) decrypts it. It is not part of this kit.')
            if ask('  Download RPCS3\'s Linux AppImage from its GitHub releases now (~80 MB)? [Y/n] ').lower() != 'n':
                rpcs3 = download_rpcs3()
        name = 'rpcs3.exe' if os.name == 'nt' else 'RPCS3 AppImage'
        while not rpcs3:
            say('  The game\'s EBOOT.BIN is a signed+encrypted PS3 executable (SELF); RPCS3 decrypts it.')
            say(f'  Get RPCS3 from https://rpcs3.net/download (unzip it anywhere), then drag the {name}')
            say('  here and press Enter. (Or decrypt it yourself: RPCS3 -> Utilities -> Decrypt PS3')
            say(f'  Binaries -> {eboot}, then just press Enter.)')
            t = ask(f'  {name}: ')
            if not t and find_eboot_elf():
                break
            rpcs3 = find_rpcs3({'rpcs3': t}, {})
        if rpcs3:
            cfg['rpcs3'] = rpcs3; save_config(cfg)
            say('  running rpcs3 --decrypt (a window may flash up)')
            # Decrypting needs no graphics, but RPCS3 still loads the Vulkan driver at start, and a broken one
            # crashes it before it writes anything (Windows Sandbox's virtual GPU: an access violation inside
            # vk_icdNegotiateLoaderICDInterfaceVersion). These standard Vulkan loader settings hide every driver --
            # except in a process running as administrator, where the loader ignores them (Windows Sandbox runs
            # everything as administrator). A vulkan-1.dll stub next to rpcs3.exe is no way out: RPCS3 refuses to
            # start with one there ("module vulkan-1.dll was incorrectly installed").
            nodrv = os.path.join(ROOT, 'no-vulkan-driver.json')   # never exists
            env = dict(os.environ, VK_ICD_FILENAMES=nodrv, VK_DRIVER_FILES=nodrv, VK_LOADER_DRIVERS_DISABLE='*')
            if rpcs3.endswith('.AppImage'):
                env['APPIMAGE_EXTRACT_AND_RUN'] = '1'   # runs without FUSE (a Steam Deck or a container may lack it)
            for attempt in range(3):
                if attempt:
                    say(f'  no EBOOT.elf yet: trying again ({attempt + 1} of 3)')
                try:
                    r = subprocess.run([rpcs3, '--decrypt', eboot], timeout=300, env=env,
                                       stdin=subprocess.DEVNULL)   # a failed decrypt asks for a key on stdin
                    if r.returncode and not find_eboot_elf():
                        say(f'  RPCS3 stopped with exit code {r.returncode:#x}'
                            f' (its log: {os.path.join(os.path.dirname(rpcs3), "log", "RPCS3.log")})')
                except subprocess.TimeoutExpired:
                    say('  RPCS3 took over 5 minutes and was stopped')
                except OSError as e:
                    say(f'  could not run {rpcs3}: {e}')
                    break
                if find_eboot_elf():
                    break
        elf = find_eboot_elf()
        while not elf:
            say(f'  RPCS3 did not write EBOOT.elf (is another RPCS3 window open? close it and run {SETUP_NAME}')
            say('  again), or decrypt by hand: RPCS3 -> Utilities -> Decrypt PS3 Binaries ->')
            say(f'  {eboot}  -- it writes EBOOT.elf next to it.')
            if ask('  Press Enter when EBOOT.elf is there (or type q to quit): ').lower() == 'q':
                sys.exit(1)
            elf = find_eboot_elf()
    h = sha256(elf)
    if h != EBOOT_ELF_SHA256:
        say(f'  WARNING: EBOOT.elf differs from the tested one (sha256 {h}).')
        if ask('  Continue anyway? [y/N] ').lower() != 'y':
            sys.exit(1)
    else:
        say('  EBOOT.elf OK (matches the tested build)')


# --- 3. ps3recomp -------------------------------------------------------------------------------

def git(*a, cwd=None, check=True):
    r = subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True)
    if r.returncode and os.name == 'nt' and a and a[0] in ('clone', 'fetch') and _tls_trouble(r.stderr):
        # Git's own certificate file is missing or unreadable ("error adding trust anchors from file ...
        # ca-bundle.crt", GitHub #49): ask Windows' certificate store instead (schannel), which every Windows has.
        say('  git could not check GitHub\'s certificate with its own file: trying Windows\' certificate store')
        r = subprocess.run(['git', '-c', 'http.sslBackend=schannel', *a], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        fail(f'git {" ".join(a)} failed:\n{r.stdout}{r.stderr}')
    return r


def _tls_trouble(err):
    e = (err or '').lower()
    return any(s in e for s in ('trust anchors', 'ca-bundle', 'certificate file', 'ssl certificate',
                                'certificate problem', 'ssl_ctx', 'cafile', 'unable to get local issuer'))


def step_ps3recomp():
    step(3, 'ps3recomp (static recompiler + PS3 runtime) at the tested commit, with this port\'s patch')
    mark = os.path.join(PS3RECOMP, '.ds_patched')
    if os.path.isfile(mark):
        state = patch_sync.sync_runtime(PS3RECOMP_COMMIT)   # an update since: re-apply the patch
        if state == 'current':
            say('  already set up')
        if state in ('current', 'updated'):
            return
        say('  setting it up again')
    if not os.path.isdir(os.path.join(PS3RECOMP, '.git')):
        os.makedirs(os.path.dirname(PS3RECOMP), exist_ok=True)
        say(f'  cloning {PS3RECOMP_URL}')
        git('clone', '-q', PS3RECOMP_URL, PS3RECOMP)
    if git('cat-file', '-e', PS3RECOMP_COMMIT + '^{commit}', cwd=PS3RECOMP, check=False).returncode:
        git('fetch', '-q', 'origin', cwd=PS3RECOMP)
    git('-c', 'advice.detachedHead=false', 'checkout', '-q', '-f', PS3RECOMP_COMMIT, cwd=PS3RECOMP)
    git('reset', '-q', '--hard', cwd=PS3RECOMP)
    git('clean', '-q', '-fd', cwd=PS3RECOMP)
    git(*patch_sync.GIT_EOL, 'apply', '--whitespace=nowarn', os.path.join(ROOT, 'patches', 'ps3recomp-local.patch'),
        cwd=PS3RECOMP)   # GIT_EOL: the commit's mixed CRLF / LF files (patch_sync.py)
    with open(os.path.join(ROOT, 'patches', 'ps3recomp-local.patch'), 'rb') as f:
        patch_sync.save_runtime_state(PS3RECOMP_COMMIT, f.read())
    say('  patched')


# --- 4 + 5. recompile ---------------------------------------------------------------------------

def lift_inputs():
    """What the recompiled code is made from besides the EBOOT; if this changes, an update needs a
    full recompile, not just the lifted-code patch again (setup/patch_sync.py). For the US release the string is
    the same as before region support, so an existing US setup is not recompiled."""
    with open(os.path.join(ROOT, 'tools', 'lift_spurs_jobs.py'), 'rb') as f:
        tool = hashlib.sha256(f.read().replace(b'\r\n', b'\n')).hexdigest()[:16]
    return f'{PS3RECOMP_COMMIT} {" ".join(LIFT_ARGS)} {SPURS_JOBS} {tool}'


def step_lift():
    step(4, 'recompile the game code (PPU + SPU) -- a few minutes')
    mark = os.path.join(PORT, '.lifted')
    if os.path.isfile(mark):
        state = patch_sync.sync_lifted(lift_inputs())   # an update since: re-apply lifted-code.patch
        if state == 'current':
            say('  already done')
        if state in ('current', 'updated'):
            return
        os.remove(mark)   # 'relift': recompile from scratch below
    for d in ('out', 'recompiled', 'spu', 'spu_miss'):
        shutil.rmtree(os.path.join(PORT, d), ignore_errors=True)
    os.makedirs(os.path.join(PORT, 'game'), exist_ok=True)
    elf = os.path.join(PORT, 'game', 'EBOOT.ELF')
    shutil.copyfile(find_eboot_elf(), elf)
    T = os.path.join(PS3RECOMP, 'tools')
    py = sys.executable
    logs = os.path.join(PORT, 'logs'); os.makedirs(logs, exist_ok=True)
    run([py, os.path.join(T, 'ppu_loader.py'), 'game/EBOOT.ELF', '-o', 'out/'], PORT,
        os.path.join(logs, 'ppu_loader.log'))
    say('  lifting 94,000 PPU functions (about a minute or two)...')
    run([py, os.path.join(T, 'ppu_lifter.py'), 'game/EBOOT.ELF', '--functions', 'out/EBOOT.functions.json',
         '--hle-stubs', 'out/EBOOT.imports.json', *LIFT_ARGS, '--output', 'recompiled/',
         '--jobs', str(build.default_jobs())], PORT,
        os.path.join(logs, 'ppu_lifter.log'))
    run([py, os.path.join(T, 'extract_spu_images.py'), 'game/EBOOT.ELF', '--output', 'spu/images'], PORT,
        os.path.join(logs, 'spu_extract.log'))
    run([py, os.path.join(T, 'build_spu_workloads.py'), '--images', 'spu/images', '--lifted', 'spu',
         '--out', 'spu/spu_workloads.c', '--constructor'], PORT, os.path.join(logs, 'spu_lift.log'))
    raw = open(elf, 'rb').read()
    os.makedirs(os.path.join(PORT, 'spu_miss'), exist_ok=True)
    for off, size, fp in SPURS_JOBS:
        open(os.path.join(PORT, 'spu_miss', f'spujob_{fp}_{size}.bin'), 'wb').write(raw[off:off + size])
    run([py, os.path.join(ROOT, 'tools', 'lift_spurs_jobs.py'), PS3RECOMP, 'spu_miss', 'spu'], PORT,
        os.path.join(logs, 'spu_jobs.log'))

    step(5, 'apply this port\'s edits to the recompiled code')
    n = 0
    for sub in ('recompiled', 'spu'):
        for d, _, fs in os.walk(os.path.join(PORT, sub)):
            for f in fs:
                if f.endswith(('.c', '.cpp', '.h')):
                    p = os.path.join(d, f); b = open(p, 'rb').read()
                    if b'\r\n' in b:
                        open(p, 'wb').write(b.replace(b'\r\n', b'\n')); n += 1
    patch = os.path.join(ROOT, 'patches', LIFTED_PATCH)
    # port/ sits inside this repo's checkout: keep git from finding that repo, or it would take the
    # patch's paths as relative to the checkout's top instead of port/
    r = subprocess.run(['git', 'apply', '--whitespace=nowarn', '-p1', patch], cwd=PORT, capture_output=True,
                       text=True, env=dict(os.environ, GIT_CEILING_DIRECTORIES=ROOT))
    if r.returncode:
        fail(f'patches/{LIFTED_PATCH} did not apply:\n{r.stdout}{r.stderr}')
    with open(patch, 'rb') as f:
        patch_sync.save_lifted_state(f.read(), lift_inputs())
    say('  done')


def long_path_warning():
    """Windows limits paths to 260 characters unless LongPathsEnabled is set (it is not on a new PC); the
    build's deepest paths are ~130 characters inside the folder, so a long folder path breaks it midway."""
    if os.name != 'nt' or len(ROOT) <= 100:
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\FileSystem') as k:
            if winreg.QueryValueEx(k, 'LongPathsEnabled')[0] == 1:
                return
    except OSError:
        pass
    say(f'  NOTE: this folder\'s path is long ({len(ROOT)} characters): {ROOT}')
    say('  Windows limits paths to 260 characters and the build goes ~130 deep, so it may fail partway.')
    say('  Moving the folder somewhere short (for example C:\\Games\\DemonsSouls) avoids that.')
    if ask('  Continue here anyway? [y/N] ').lower() != 'y':
        sys.exit(1)


def main():
    build.no_quickedit()   # a click in the window must not pause the setup
    long_path_warning()
    args, a = {}, sys.argv[1:]
    while a:
        x = a.pop(0)
        if x in ('--key', '--rpcs3', '--jobs') and a:
            args[x[2:]] = a.pop(0)
        elif x in ('-h', '--help'):
            say(__doc__); return
        else:
            args['image'] = x
    if shutil.which('git') is None:
        fail(f'git is not installed ({SETUP_NAME} normally checks this)')
    cfg = load_config()
    say("Demon's Souls (USA BLUS-30443 / Europe BLES-00932) -- ps3recomp PC port setup")
    step_game(args, cfg)
    step_decrypt(args, cfg)
    step_ps3recomp()
    step_lift()
    step(6, 'build DemonsSoulsRecomp.exe (the first build takes a while: 10-30 minutes)')
    for d in ('hdd0', 'hdd1', 'no_flash', 'logs'):
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)
    if build.build(jobs=args.get('jobs')):
        fail('the build failed -- see the messages above')
    say('\nAll done. ' + PLAY_HINT)


if __name__ == '__main__':
    main()
