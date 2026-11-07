"""Build DemonsSoulsRecomp.exe (port/build_opt) with clang-cl, CMake and Ninja.

Finds the tools by itself: Visual Studio 2022 (or its Build Tools) with the C++ workload for the
Windows SDK and libraries, and clang-cl + lld-link from an LLVM install (LLVM_DIR, deps/llvm,
C:\\Program Files\\LLVM, Visual Studio's own Clang component, or PATH). CMake and Ninja come from
the Python environment SETUP.bat makes. Offers to install what is missing with winget.

The configuration is the tested one: build type "Fast" (no CMake flag preset, so the project's own
-O1 / -O2 apply) and the boot harness runner (DS_BOOT_HARNESS=ON).

The lifted SPU code uses AVX2 when this CPU has it (DS_AVX2). On an older CPU it is built without,
and port/build_opt/no_avx2.txt tells PLAY.bat not to ask for it. "set DS_AVX2=0" before BUILD.bat
builds without AVX2 on any CPU (for a copy meant for an older PC).

On Linux (docs/LINUX.md) the same exe is cross-compiled: clang-cl + lld-link from LLVM, with the
Microsoft C runtime and Windows SDK fetched on this PC by xwin (Microsoft's license is shown and
accepted by you, nothing of it is shipped with this repo) and the C runtime linked statically so
Wine/Proton needs no Visual C++ DLLs (setup/clang-cl-xwin.cmake). "set DS_XWIN=1" before BUILD.bat
takes that path on Windows too, without Visual Studio.

usage: BUILD.bat [--jobs N] [ninja targets...]
       build.py --runtime-only [--jobs N]   (cross toolchain: ps3recomp's runtime alone, no game needed)
"""
import glob, hashlib, os, re, shutil, subprocess, sys, tarfile, tempfile, threading, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netcert                                                   # noqa: E402
netcert.install()   # HTTPS on a fresh Windows: let Windows fetch missing root certificates (netcert.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, 'port', 'build_opt')
# Copies of the patches the last successful full build was made from. PLAY.bat compares them with
# patches/: a folder updated (git pull, a new ZIP) but not rebuilt -- or whose rebuild failed or was
# stopped -- would run the old exe with the new files (GitHub #4: a black screen at the title).
BUILT = os.path.join(BUILD, 'built')
PATCHES = ('ps3recomp-local.patch', 'lifted-code.patch')
MIN_CLANG = 17
EXE = '.exe' if os.name == 'nt' else ''
XWIN_DIR = os.environ.get('DS_XWIN_DIR') or os.path.join(ROOT, 'deps', 'xwin')
XWIN_VERSION = '0.10.0'
XWIN_URL = 'https://github.com/Jake-Shadle/xwin/releases/download/{v}/xwin-{v}-{t}.tar.gz'
XWIN_LICENSE = 'https://go.microsoft.com/fwlink/?LinkId=2086102'
# The portable compiler for a Windows PC without Visual Studio's C++ tools or LLVM: LLVM's own release
# (only clang-cl, lld-link, llvm-lib, llvm-rc, llvm-mt and clang's headers are unpacked, ~250 MB) with
# xwin's Microsoft CRT + SDK. Chosen once; deps/.portable_compiler remembers it (DS_XWIN=0 = Visual Studio).
LLVM_WIN_VERSION = '23.1.4'
LLVM_WIN_URL = ('https://github.com/llvm/llvm-project/releases/download/llvmorg-{v}/'
                'clang+llvm-{v}-x86_64-pc-windows-msvc.tar.zst')
LLVM_WIN_SHA256 = '1a3f2f998e230b5791cc4e2bfe11a1f7c07fe42c96ff44f227c9db0bedfaf091'
LLVM_WIN_TOOLS = ('clang-cl', 'lld-link', 'llvm-lib', 'llvm-rc', 'llvm-mt')
PORTABLE_MARK = os.path.join(ROOT, 'deps', '.portable_compiler')


def no_quickedit():
    """Windows consoles with QuickEdit on (the default) pause any program that writes to them while text is selected
    -- one stray click in the window and the setup or the build seems to hang until a key or a right-click ends the
    selection. Turn it off for this window (the console's own setting, only this window)."""
    if os.name != 'nt':
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)   # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if h and k.GetConsoleMode(h, ctypes.byref(mode)):
            # ENABLE_EXTENDED_FLAGS (0x80) must be set for the QuickEdit bit (0x40) to be changed
            k.SetConsoleMode(h, (mode.value & ~0x40) | 0x80)
    except (OSError, AttributeError, ValueError):
        pass


def say(msg=''):
    print(msg, flush=True)


def ask(prompt):
    if os.environ.get('DS_ASSUME_YES') == '1' and '[Y/n]' in prompt:   # tests: take the default
        say(prompt + '(yes: DS_ASSUME_YES)')
        return ''
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return ''


def fwd(p):
    return p.replace('\\', '/')


def find_vs():
    if os.environ.get('DS_TEST_NO_VS') == '1':   # tests: act as if Visual Studio were not installed
        return None, None
    pf86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
    vswhere = os.path.join(pf86, 'Microsoft Visual Studio', 'Installer', 'vswhere.exe')
    if os.path.isfile(vswhere):
        r = subprocess.run([vswhere, '-latest', '-products', '*', '-requires',
                            'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'],
                           capture_output=True, text=True)
        for line in r.stdout.splitlines():
            bat = os.path.join(line.strip(), 'VC', 'Auxiliary', 'Build', 'vcvars64.bat')
            if os.path.isfile(bat):
                return line.strip(), bat
    return None, None


BLOCKED_WINERRORS = (4551, 1260)   # application control policy (Smart App Control / WDAC), group policy


def blocked(e, what):
    """True (and says why) when Windows refused to start `what` because of an application control policy."""
    if getattr(e, 'winerror', None) not in BLOCKED_WINERRORS:
        return False
    say(f'  Windows blocked {what}: Smart App Control (or another app control policy) does not let unsigned')
    say('  programs run, and this port is built on your PC, so its tools and the game are unsigned. Turn it off')
    say('  in Windows Security -> App & browser control -> Smart App Control (Windows cannot turn it back on')
    say('  without a reinstall), then run the setup again.')
    return True


def clang_version(bindir):
    try:
        out = subprocess.run([os.path.join(bindir, 'clang-cl' + EXE), '--version'], capture_output=True,
                             text=True).stdout
    except OSError as e:
        if blocked(e, os.path.join(bindir, 'clang-cl' + EXE)):
            sys.exit(1)
        return 0, ''
    m = re.search(r'version (\d+)\.', out)
    return (int(m.group(1)) if m else 0), out.splitlines()[0] if out else ''


def find_llvm(vs_path):
    if os.environ.get('DS_TEST_NO_LLVM') == '1':   # tests: only a portable LLVM in deps/llvm counts
        return find_llvm_cross()
    cands = []
    if os.environ.get('LLVM_DIR'):
        cands += [os.environ['LLVM_DIR'], os.path.join(os.environ['LLVM_DIR'], 'bin')]
    cands += glob.glob(os.path.join(ROOT, 'deps', 'llvm', '**', 'bin'), recursive=True)
    cands.append(os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'LLVM', 'bin'))
    if vs_path:
        cands.append(os.path.join(vs_path, 'VC', 'Tools', 'Llvm', 'x64', 'bin'))
    w = shutil.which('clang-cl')
    if w:
        cands.append(os.path.dirname(w))
    best = None
    for c in cands:
        if os.path.isfile(os.path.join(c, 'clang-cl.exe')) and os.path.isfile(os.path.join(c, 'lld-link.exe')):
            v, text = clang_version(c)
            if best is None or v > best[0]:
                best = (v, c, text)
    return best


def winget(pkg, extra=()):
    if not shutil.which('winget'):
        say('  winget is not available; install it by hand (see README.md).')
        return False
    say(f'  > winget install {pkg}')
    return subprocess.run(['winget', 'install', '-e', '--id', pkg, '--accept-package-agreements',
                           '--accept-source-agreements', *extra]).returncode == 0


def offer_portable(why):
    """Windows without Visual Studio's C++ tools or LLVM: build with the portable compiler instead
    (nothing installed, no administrator rights). True = chosen, remembered in deps/.portable_compiler."""
    if os.name != 'nt':
        return False
    say(f'  {why}')
    say('  This PC can build without installing anything: a portable LLVM (clang-cl; a 280 MB download,')
    say('  250 MB unpacked) and Microsoft\'s C runtime + Windows SDK (about 1 GB, downloaded from Microsoft')
    say(f'  by the open-source xwin tool; Microsoft\'s license applies: {XWIN_LICENSE}). It all stays in deps\\.')
    if ask('  Use the portable compiler? [Y/n] ') == 'n':
        return False
    os.makedirs(os.path.dirname(PORTABLE_MARK), exist_ok=True)
    with open(PORTABLE_MARK, 'w') as f:
        f.write('Build with the portable compiler: LLVM in deps/llvm + xwin in deps/xwin (setup/build.py).\n')
    return True


def tools():
    vs_path, vcvars = find_vs()
    if not vcvars and offer_portable('Visual Studio 2022\'s C++ tools are not installed.'):
        return 'portable'
    if not vcvars:
        say('  Visual Studio 2022 with "Desktop development with C++" (or the free Build Tools) is needed')
        say('  for the Windows SDK and C++ libraries.')
        if ask('  Install the Visual Studio 2022 Build Tools now with winget (about 3 GB)? [Y/n] ') != 'n':
            winget('Microsoft.VisualStudio.2022.BuildTools',
                   ['--override', '--wait --passive --add Microsoft.VisualStudio.Workload.VCTools '
                                  '--includeRecommended'])
            vs_path, vcvars = find_vs()
        if not vcvars:
            return None
    llvm = find_llvm(vs_path)
    if not llvm or llvm[0] < MIN_CLANG:
        if llvm:
            say(f'  clang-cl in {llvm[1]} is too old ({llvm[2]}); LLVM {MIN_CLANG} or newer is needed.')
        else:
            say('  clang-cl (LLVM) is needed -- the recompiled code is built with it, not with MSVC.')
        if offer_portable('No suitable LLVM is installed.'):
            return 'portable'
        if ask('  Install LLVM now with winget? [Y/n] ') != 'n':
            winget('LLVM.LLVM')
            llvm = find_llvm(vs_path)
        if not llvm or llvm[0] < MIN_CLANG:
            return None
    scripts = os.path.dirname(sys.executable)
    cmake = shutil.which('cmake', path=scripts) or shutil.which('cmake')
    ninja = shutil.which('ninja', path=scripts) or shutil.which('ninja')
    if not cmake or not ninja:
        say('  CMake / Ninja missing: run SETUP.bat (it installs them into .venv).')
        return None
    return vcvars, llvm, cmake, ninja


def want_avx2():
    e = os.environ.get('DS_AVX2', '').strip()
    if e in ('0', '1'):
        return e == '1'
    if os.name != 'nt':
        try:
            with open('/proc/cpuinfo') as f:
                return any(l.startswith('flags') and ' avx2' in l for l in f)
        except OSError:
            return True
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))  # PF_AVX2_INSTRUCTIONS_AVAILABLE
    except Exception:
        return True


# --- cross toolchain: clang-cl + lld-link + xwin (Linux; Windows with DS_XWIN=1) -----------------

def use_xwin():
    e = os.environ.get('DS_XWIN', '').strip()
    return os.name != 'nt' or e == '1' or (e != '0' and os.path.isfile(PORTABLE_MARK))


def find_llvm_cross():
    """An LLVM bin folder with clang-cl, lld-link and llvm-lib (Linux packages put them in
    /usr/lib/llvm-N/bin). Returns (version, folder, version text) or None."""
    cands = []
    for e in ('DS_LLVM_DIR', 'LLVM_DIR'):
        if os.environ.get(e):
            cands += [os.environ[e], os.path.join(os.environ[e], 'bin')]
    if os.environ.get('DS_TEST_NO_LLVM') == '1':   # tests: only a portable LLVM in deps/llvm counts
        cands = []
    cands += glob.glob(os.path.join(ROOT, 'deps', 'llvm', '**', 'bin'), recursive=True)
    if os.name != 'nt':
        cands += sorted(glob.glob('/usr/lib/llvm-*/bin'), reverse=True) + ['/usr/local/bin', '/usr/bin']
    w = None if os.environ.get('DS_TEST_NO_LLVM') == '1' else shutil.which('clang-cl')
    if w:
        cands.append(os.path.dirname(os.path.realpath(w)))
        cands.append(os.path.dirname(w))
    best = None
    for c in cands:
        if all(os.path.isfile(os.path.join(c, t + EXE)) for t in ('clang-cl', 'lld-link', 'llvm-lib')):
            v, text = clang_version(c)
            if best is None or v > best[0]:
                best = (v, c, text)
    return best


def download_llvm():
    """Windows: LLVM's own release (.tar.zst, checked against its pinned sha256); only the tools the build
    uses and clang's headers are unpacked, into deps/llvm/<release folder>."""
    try:
        import zstandard
    except ImportError:
        say('  the zstandard package is missing: run SETUP.bat (it installs it into .venv).')
        return False
    url = LLVM_WIN_URL.format(v=LLVM_WIN_VERSION)
    say(f'  downloading LLVM {LLVM_WIN_VERSION} (open source, 280 MB): {url}')
    os.makedirs(os.path.join(ROOT, 'deps'), exist_ok=True)
    part = os.path.join(ROOT, 'deps', 'llvm.tar.zst.part')
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(part, 'wb') as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                h.update(b)
                f.write(b)
    except OSError as e:
        say(f'  download failed: {e}')
        return False
    if h.hexdigest() != LLVM_WIN_SHA256:
        os.remove(part)
        say('  the LLVM download does not match its checksum; not using it')
        return False
    say('  unpacking clang-cl, lld-link, llvm-lib, llvm-rc, llvm-mt and clang\'s headers ...')
    # into deps/llvm.part, renamed to deps/llvm only when complete: a stopped run leaves nothing half
    final = os.path.join(ROOT, 'deps', 'llvm')
    dest = final + '.part'
    shutil.rmtree(dest, ignore_errors=True)
    want = {f'bin/{t}.exe' for t in LLVM_WIN_TOOLS}
    n = 0
    try:
        with open(part, 'rb') as f:
            # LLVM's archives use zstd's long mode (a window of up to 2 GB)
            rd = zstandard.ZstdDecompressor(max_window_size=2 ** 31).stream_reader(f)
            with tarfile.open(fileobj=rd, mode='r|') as t:
                for m in t:
                    parts = m.name.replace('\\', '/').split('/')
                    if len(parts) < 2 or '..' in parts or m.name.startswith(('/', '\\')):
                        continue
                    rel = '/'.join(parts[1:])
                    if not (rel in want or rel.startswith('lib/clang/') or rel == 'LICENSE.TXT'):
                        continue
                    if '/finclude/' in rel:   # Fortran modules: unused, and the longest paths (MAX_PATH)
                        continue
                    out = os.path.join(dest, *parts)
                    if m.isdir():
                        os.makedirs(out, exist_ok=True)
                    elif m.isfile():
                        os.makedirs(os.path.dirname(out), exist_ok=True)
                        with t.extractfile(m) as src, open(out, 'wb') as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                        n += 1
    except (OSError, tarfile.TarError, zstandard.ZstdError) as e:
        say(f'  unpacking LLVM failed: {e}')
        if isinstance(e, FileNotFoundError) and len(ROOT) > 90:
            say(f'  The folder path is long ({len(ROOT)} characters) and Windows limits paths to 260: move the')
            say('  folder somewhere short, such as C:\\Games\\DemonsSouls, and run the setup again.')
        return False
    finally:
        if os.path.isfile(part):
            os.remove(part)
    got = {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(dest, '*', 'bin', '*.exe'))}
    if not set(LLVM_WIN_TOOLS) <= got:
        say('  the LLVM download lacks ' + ', '.join(sorted(set(LLVM_WIN_TOOLS) - got)))
        return False
    shutil.rmtree(final, ignore_errors=True)
    os.replace(dest, final)
    say(f'  LLVM {LLVM_WIN_VERSION}: {n} files in {final}')
    return True


def pip_tool(name):
    """cmake / ninja from their pip packages (the module knows where its binary is, which still holds
    when the Python environment was moved, as inside the Linux AppImage), else from PATH."""
    try:
        if name == 'cmake':
            import cmake
            p = os.path.join(cmake.CMAKE_BIN_DIR, 'cmake' + EXE)
        else:
            import ninja
            p = os.path.join(ninja.BIN_DIR, 'ninja' + EXE)
        if os.path.isfile(p):
            return p
    except (ImportError, AttributeError):
        pass
    return shutil.which(name, path=os.path.dirname(sys.executable)) or shutil.which(name)


def find_xwin():
    cands = [os.environ.get('XWIN'), shutil.which('xwin'), os.path.join(ROOT, 'deps', 'xwin-bin', 'xwin' + EXE)]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def download_xwin():
    """The xwin release for this OS from its GitHub page, checked against the release's sha256."""
    target = 'x86_64-pc-windows-msvc' if os.name == 'nt' else 'x86_64-unknown-linux-musl'
    url = XWIN_URL.format(v=XWIN_VERSION, t=target)
    say(f'  downloading xwin {XWIN_VERSION} (open source, ~3 MB): {url}')
    try:
        data = urllib.request.urlopen(url, timeout=120).read()
        want = urllib.request.urlopen(url + '.sha256', timeout=60).read().decode().split()[0].lower()
    except OSError as e:
        say(f'  download failed: {e}')
        return None
    if hashlib.sha256(data).hexdigest() != want:
        say('  xwin download does not match its sha256; not using it')
        return None
    out = os.path.join(ROOT, 'deps', 'xwin-bin')
    os.makedirs(out, exist_ok=True)
    fd, tgz = tempfile.mkstemp(suffix='.tar.gz')
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
    try:
        with tarfile.open(tgz) as t:
            m = next(m for m in t.getmembers() if m.isfile() and os.path.basename(m.name) == 'xwin' + EXE)
            with t.extractfile(m) as src, open(os.path.join(out, 'xwin' + EXE), 'wb') as dst:
                shutil.copyfileobj(src, dst)
    finally:
        os.remove(tgz)
    exe = os.path.join(out, 'xwin' + EXE)
    os.chmod(exe, 0o755)
    return exe


def xwin_paths(sdk):
    """Include and library folders of an "xwin splat --use-winsysroot-style --preserve-ms-arch-notation"
    folder (the Visual Studio layout: VC/Tools/MSVC/<ver>, Windows Kits/10/{Include,Lib}/<ver>), and the
    MSVC version clang-cl should imitate (CRT 14.44 -> 19.44)."""
    def newest(pattern):
        found = sorted(glob.glob(os.path.join(sdk, *pattern)),
                       key=lambda p: [int(x) for x in re.findall(r'\d+', os.path.basename(p))])
        return found[-1] if found else os.path.join(sdk, *pattern).replace('*', '?')
    vc = newest(('VC', 'Tools', 'MSVC', '*'))
    inc_kit = newest(('Windows Kits', '10', 'Include', '*'))
    lib_kit = newest(('Windows Kits', '10', 'Lib', '*'))
    inc = [os.path.join(vc, 'include')] + [os.path.join(inc_kit, d) for d in ('ucrt', 'um', 'shared', 'winrt')]
    lib = [os.path.join(vc, 'lib', 'x64')] + [os.path.join(lib_kit, d, 'x64') for d in ('um', 'ucrt')]
    m = re.match(r'14\.(\d+)', os.path.basename(vc))
    return inc, lib, f'19.{m.group(1)}' if m else '19.40'


def xwin_sdk():
    """The Microsoft CRT + Windows SDK in deps/xwin, fetched once by xwin (about 1 GB to download,
    700 MB on disk). xwin itself asks you to accept Microsoft's license."""
    mark = os.path.join(XWIN_DIR, '.ds_done')
    if os.path.isfile(mark):
        return XWIN_DIR
    if os.environ.get('DS_XWIN_DIR'):   # your own "xwin splat" output: used as it is
        inc, lib, _ = xwin_paths(XWIN_DIR)
        missing = [p for p in inc + lib if not os.path.isdir(p)]
        if missing:
            say('  DS_XWIN_DIR is not an xwin splat --use-winsysroot-style folder (no ' + ', '.join(missing) + ')')
            return None
        return XWIN_DIR
    say('  The exe is built against Microsoft\'s C runtime and Windows SDK. They are not part of this')
    say('  repo: xwin (an open-source tool) downloads them from Microsoft to this PC, once. Microsoft')
    say(f'  allows that under its license ({XWIN_LICENSE}); xwin asks you to accept it.')
    xwin = find_xwin() or download_xwin()
    if not xwin:
        say('  xwin is needed: get it from https://github.com/Jake-Shadle/xwin/releases and put it in')
        say(f'  {os.path.join(ROOT, "deps", "xwin-bin")} (or set XWIN=/path/to/xwin).')
        return None
    cache = os.path.join(ROOT, 'deps', 'xwin-cache')
    # the Visual Studio folder layout on every OS; xwin's symlinks fix the case of header names that
    # Microsoft's own headers spell differently (Linux), and need rights Windows does not give by default
    cmd = [xwin, '--cache-dir', cache, '--arch', 'x86_64', '--variant', 'desktop', '--http-retry', '3',
           'splat', '--output', XWIN_DIR, '--use-winsysroot-style', '--preserve-ms-arch-notation']
    if os.name == 'nt':
        cmd.append('--disable-symlinks')
    if os.name == 'nt':
        # xwin.exe needs the Visual C++ runtime (VCRUNTIME140.dll); setup.py installs it for RPCS3 in step 2, but a
        # setup whose EBOOT.elf was already there skips that (Windows Sandbox test: "VCRUNTIME140.dll was not found")
        import setup as _setup   # setup.py imports this module too; by now both are loaded
        if not _setup.vc_runtime_ok('xwin (it downloads the C runtime + Windows SDK)'):
            return None
    shutil.rmtree(XWIN_DIR, ignore_errors=True)
    say('  > xwin splat (downloading the Microsoft CRT + SDK, a few minutes)')
    try:
        rc = subprocess.run(cmd).returncode
    except OSError as e:
        if not blocked(e, xwin):
            say(f'  could not run {xwin}: {e}')
        return None
    if rc:
        say('  xwin failed (see above); run the setup again to retry.')
        return None
    shutil.rmtree(cache, ignore_errors=True)   # the downloaded packages, no longer needed
    inc, lib, _ = xwin_paths(XWIN_DIR)
    missing = [p for p in inc + lib if not os.path.isdir(p)]
    if missing:
        say('  xwin output is missing ' + ', '.join(missing))
        return None
    with open(mark, 'w') as f:
        f.write(f'xwin {XWIN_VERSION}\n')
    return XWIN_DIR


def default_jobs():
    """One compile per core, but no more than ~1 per 2.5 GB of free memory: the biggest lifted files need
    about that much (a Steam Deck has 16 GB for 8 threads; Windows Sandbox gets every host thread but its own
    RAM). Windows: 1 per 2 GB of installed RAM; Linux: 1 per 2.5 GB of MemAvailable."""
    n = os.cpu_count() or 4
    if os.name == 'nt':
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                            ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                            ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                            ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                            ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(st)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                # by installed RAM (2 GB per compile): the page file grows as needed and most files need far
                # less than the biggest, so free memory right now would be too strict (a 64 GB PC: 32 jobs)
                n = max(1, min(n, int(st.ullTotalPhys / (2 * 1024 ** 3))))
        except (OSError, AttributeError, ValueError):
            pass
    else:
        try:
            with open('/proc/meminfo') as f:
                kb = next(int(l.split()[1]) for l in f if l.startswith('MemAvailable:'))
            n = max(1, min(n, int(kb / (2.5 * 1024 * 1024))))
        except (OSError, StopIteration, ValueError):
            pass
    return n


def build_xwin(jobs=None, targets=(), runtime_only=False):
    """runtime_only: just ps3recomp's runtime library (deps/ps3recomp on its own, port/build_runtime),
    no game code -- a quick check of the toolchain that needs no disc (the Linux CI job runs it)."""
    llvm = find_llvm_cross()
    if (not llvm or llvm[0] < MIN_CLANG) and os.name == 'nt' and download_llvm():
        llvm = find_llvm_cross()
    if not llvm or llvm[0] < MIN_CLANG:
        if os.name == 'nt':
            say(f'  clang-cl + lld-link (LLVM {MIN_CLANG} or newer) are needed. Run SETUP.bat again to retry the')
            say('  portable compiler download (check the internet connection), or install Visual Studio 2022 with')
            say('  "Desktop development with C++" + LLVM (winget install LLVM.LLVM), or set DS_LLVM_DIR.')
            return 1
        say(f'  clang-cl + lld-link (LLVM {MIN_CLANG} or newer) are needed. The Linux AppImage brings them;')
        say('  from a git checkout install your distribution\'s clang and lld packages (Debian/Ubuntu:')
        say('  clang lld llvm, Fedora: clang lld llvm, Arch: clang lld llvm) or set DS_LLVM_DIR.')
        return 1
    ver, bindir, ver_text = llvm
    cmake, ninja = pip_tool('cmake'), pip_tool('ninja')
    if not cmake or not ninja:
        say('  CMake / Ninja missing: pip install cmake ninja (the setup normally does).')
        return 1
    sdk = xwin_sdk()
    if not sdk:
        return 1
    say(f'  compiler: {ver_text} ({bindir}), Microsoft CRT/SDK from xwin ({sdk})')
    inc, lib, msc = xwin_paths(sdk)
    env = dict(os.environ, INCLUDE=';'.join(inc), LIB=';'.join(lib))
    env.pop('EXTERNAL_INCLUDE', None)
    jobs = int(jobs or default_jobs())
    toolchain = fwd(os.path.join(ROOT, 'setup', 'clang-cl-xwin.cmake'))
    bdir = os.path.join(ROOT, 'port', 'build_runtime') if runtime_only else BUILD
    cache = os.path.join(bdir, 'CMakeCache.txt')
    if os.path.isfile(cache) and toolchain not in open(cache, errors='replace').read():
        if os.path.isfile(PORTABLE_MARK) and not runtime_only:
            # built with Visual Studio before, and the portable compiler chosen now: configure afresh
            say(f'  {bdir} was built with Visual Studio before: building it again with the portable compiler')
            for f in ('CMakeCache.txt', 'build.ninja'):
                if os.path.isfile(os.path.join(bdir, f)):
                    os.remove(os.path.join(bdir, f))
            shutil.rmtree(os.path.join(bdir, 'CMakeFiles'), ignore_errors=True)
        else:
            say(f'  {bdir} was configured with another toolchain (Visual Studio?). Delete that folder')
            say('  (or set DS_XWIN=0) and build again.')
            return 1
    avx2 = want_avx2()
    flag = '-DDS_AVX2=' + ('ON' if avx2 else 'OFF')
    if not avx2 and not runtime_only:
        say('  CPU without AVX2 (or DS_AVX2=0): building the SPU code without it')
    ps3recomp = fwd(os.path.join(ROOT, 'deps', 'ps3recomp'))
    if not os.path.isfile(os.path.join(bdir, 'build.ninja')):
        cfg = [cmake, '-S', ps3recomp if runtime_only else fwd(os.path.join(ROOT, 'project')),
               '-B', fwd(bdir), '-G', 'Ninja',
               f'-DCMAKE_MAKE_PROGRAM={fwd(ninja)}', f'-DCMAKE_TOOLCHAIN_FILE={toolchain}',
               f'-DDS_LLVM_BIN={fwd(bindir)}', f'-DDS_MSVC_COMPAT={msc}',
               # static C runtime: Wine/Proton then needs none of the Visual C++ DLLs
               '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded',
               '-DCMAKE_BUILD_TYPE=Fast', f'-DPython3_EXECUTABLE={fwd(sys.executable)}']
        if not runtime_only:
            cfg += ['-DDS_BOOT_HARNESS=ON', f'-DPS3RECOMP_DIR={ps3recomp}',
                    f'-DRECOMP_DIR={fwd(os.path.join(ROOT, "port", "recompiled"))}',
                    f'-DSPU_DIR={fwd(os.path.join(ROOT, "port", "spu"))}', flag]
    elif runtime_only:
        cfg = None
    else:   # existing build: a quick CMake re-run; the SPU code rebuilds only when the choice changed
        cfg = [cmake, flag, fwd(bdir)]
    if cfg and run_quiet(cfg, env=env, what='configuring'):
        return 5
    if runtime_only:
        targets = targets or ['ps3recomp_runtime']
    rc = run_quiet([ninja, '-C', bdir, '-j', str(jobs), *targets], env=env)
    if runtime_only:
        say('\n  runtime library built' if rc == 0 else '\n  runtime library build FAILED')
        return rc
    return finish(rc, avx2)


def fix_future_times():
    """Files dated in the future (a ZIP made in another time zone: ZIP times have no zone, so GitHub's
    UTC-made archives unpack hours ahead west of UTC) make CMake re-run itself until ninja gives up
    ("manifest 'build.ninja' still dirty after 100 tries"). Date them now. Only this repo's own files;
    game/, port/, deps/ and the rest are made on this PC."""
    now = time.time()
    skip = {'game', 'game_remaster', 'game_mod', 'port', 'deps', '.venv', '.git', 'logs', 'perf', 'hdd0', 'hdd1',
            'gamedata', 'captures', 'dev_flash', 'no_flash'}
    n = 0
    for d, dirs, files in os.walk(ROOT):
        if d == ROOT:
            dirs[:] = [x for x in dirs if x not in skip]
        for f in files:
            p = os.path.join(d, f)
            try:
                if os.stat(p).st_mtime > now + 120:
                    os.utime(p, (now, now))
                    n += 1
            except OSError:
                pass
    if n:
        say(f'  {n} file(s) from the download were dated in the future (another time zone): dated now')
    return n


def run_quiet(cmd, env=None, what='compiling'):
    """Run a build command showing one progress line ("compiling 47/322 (15%) - 3:12", from ninja's [n/N] lines)
    instead of the compiler's warnings, which are harmless but scare people. A failed step (ninja's FAILED:, or an
    error line) is shown in full. Everything goes to logs/build_last.txt. DS_BUILD_VERBOSE=1: the old full output."""
    if os.environ.get('DS_BUILD_VERBOSE') == '1':
        return subprocess.run(cmd, env=env).returncode
    os.makedirs(os.path.join(ROOT, 'logs'), exist_ok=True)
    logp = os.path.join(ROOT, 'logs', 'build_last.txt')
    t0 = time.time()
    state = {'line': f'  {what} ...', 'shown': False}
    lock = threading.Lock()

    def show(final=False):
        el = int(time.time() - t0)
        text = f"{state['line']}  -  {el // 60}:{el % 60:02d}"
        sys.stdout.write('\r' + text.ljust(78) + ('\n' if final else ''))
        sys.stdout.flush()
        state['shown'] = not final

    def above(text):   # a line of its own, then the progress line again under it
        with lock:
            if state['shown']:
                sys.stdout.write('\r' + ' ' * 79 + '\r')
            sys.stdout.write(text.rstrip('\n') + '\n')
            show()

    done = threading.Event()

    def tick():   # the elapsed time keeps moving while one big file compiles for minutes
        while not done.wait(1.0):
            with lock:
                show()

    try:
        p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        if not blocked(e, cmd[0]):
            say(f'  could not run {cmd[0]}: {e}')
        return 1
    th = threading.Thread(target=tick, daemon=True)
    th.start()
    errors = 0
    loud = False   # inside a failed step's output (from FAILED: to the next [n/N] line)
    tail = []
    with open(logp, 'w', encoding='utf-8', errors='replace') as log:
        for b in p.stdout:
            line = b.decode('utf-8', 'replace').rstrip('\r\n')
            log.write(line + '\n')
            tail = (tail + [line])[-40:]
            m = re.match(r'\[(\d+)/(\d+)\]', line)
            if m:
                loud = False
                n, total = int(m.group(1)), int(m.group(2))
                with lock:
                    state['line'] = f'  {what} {n}/{total} ({100 * n // max(total, 1)}%)'
                    show()
                continue
            if line.startswith('FAILED:') or line.startswith('ninja: error') or line.startswith('CMake Error'):
                loud = True
            if loud or re.search(r'(?:^|[\s:)])(?:fatal )?error(?: [A-Z]+\d+)?:', line):
                errors += 1
                above('  ' + line)
    rc = p.wait()
    done.set()
    th.join()
    with lock:
        show(final=True)
    if rc and not errors:   # failed without an error line we recognised: show the end of the output
        for l in tail[-25:]:
            say('  ' + l)
    if rc:
        say(f'  the full build output is in {logp}')
    return rc


def build(jobs=None, targets=()):
    fix_future_times()
    if use_xwin():
        return build_xwin(jobs, targets)
    t = tools()
    if t == 'portable':
        return build_xwin(jobs, targets)
    if not t:
        say('  Missing build tools -- see README.md, "What you need".')
        return 1
    vcvars, (ver, llvm, ver_text), cmake, ninja = t
    say(f'  compiler: {ver_text} ({llvm})')
    jobs = int(jobs or default_jobs())
    L = fwd(llvm)
    lines = ['@echo off', f'call "{vcvars}" >nul || exit /b 4',
             f'set "PATH={os.path.dirname(cmake)};{os.path.dirname(ninja)};{llvm};%PATH%"']
    if not os.path.isfile(os.path.join(BUILD, 'build.ninja')):
        cfg = [f'"{cmake}"', '-S', f'"{fwd(os.path.join(ROOT, "project"))}"', '-B', f'"{fwd(BUILD)}"',
               '-G', 'Ninja', f'-DCMAKE_MAKE_PROGRAM="{fwd(ninja)}"',
               '-DCMAKE_BUILD_TYPE=Fast', '-DDS_BOOT_HARNESS=ON',
               f'-DPS3RECOMP_DIR="{fwd(os.path.join(ROOT, "deps", "ps3recomp"))}"',
               f'-DRECOMP_DIR="{fwd(os.path.join(ROOT, "port", "recompiled"))}"',
               f'-DSPU_DIR="{fwd(os.path.join(ROOT, "port", "spu"))}"',
               f'-DPython3_EXECUTABLE="{fwd(sys.executable)}"',
               f'-DCMAKE_C_COMPILER="{L}/clang-cl.exe"', f'-DCMAKE_CXX_COMPILER="{L}/clang-cl.exe"',
               f'-DCMAKE_LINKER="{L}/lld-link.exe"']
        if os.path.isfile(os.path.join(llvm, 'llvm-rc.exe')):
            cfg.append(f'-DCMAKE_RC_COMPILER="{L}/llvm-rc.exe"')
        if os.path.isfile(os.path.join(llvm, 'llvm-lib.exe')):
            cfg.append(f'-DCMAKE_AR="{L}/llvm-lib.exe"')
        lines.append(' '.join(cfg) + ' || exit /b 5')
    else:
        cfg = None
    avx2 = want_avx2()
    flag = '-DDS_AVX2=' + ('ON' if avx2 else 'OFF')
    if cfg:
        lines[-1] = lines[-1].replace(' || exit /b 5', f' {flag} || exit /b 5')
    else:   # existing build: a quick CMake re-run; the SPU code rebuilds only when the choice changed
        lines.append(f'"{cmake}" {flag} "{fwd(BUILD)}" >nul || exit /b 5')
    if not avx2:
        say('  CPU without AVX2 (or DS_AVX2=0): building the SPU code without it')
    lines.append(f'"{ninja}" -C "{BUILD}" -j {jobs} {" ".join(targets)}')
    lines.append('exit /b %errorlevel%')
    fd, bat = tempfile.mkstemp(suffix='.bat', prefix='ds_build_')
    with os.fdopen(fd, 'w') as f:
        f.write('\r\n'.join(lines) + '\r\n')
    try:
        rc = run_quiet(['cmd', '/d', '/c', bat])
    finally:
        os.remove(bat)
    return finish(rc, avx2, full=not targets)


def finish(rc, avx2, full=True):
    if rc == 0 and full:   # only a whole build: "BUILD.bat <target>" may leave the exe as it was
        os.makedirs(BUILT, exist_ok=True)
        for n in PATCHES:
            shutil.copyfile(os.path.join(ROOT, 'patches', n), os.path.join(BUILT, n))
    if rc == 0:
        marker = os.path.join(BUILD, 'no_avx2.txt')
        if avx2:
            if os.path.isfile(marker):
                os.remove(marker)
        else:
            with open(marker, 'w') as f:
                f.write('Built without AVX2 (setup/build.py); PLAY.bat does not require it.\n')
        say(f'\n  built {os.path.join(BUILD, "DemonsSoulsRecomp.exe")}')
        kbm_icons()
    return rc


def kbm_icons():
    """Keyboard / mouse button icons (docs/NOTES.md fix 91): tools/kbm_icons.py draws them into textures/kbm from
    this PC's copy of the game, once, and again when the script's art changes (its VERSION). Never stops the
    build: without them the game shows the PS3 buttons as before."""
    out = os.path.join(ROOT, 'textures', 'kbm')
    usr = os.path.join(ROOT, 'game', 'PS3_GAME', 'USRDIR')
    try:
        src = open(os.path.join(ROOT, 'tools', 'kbm_icons.py'), encoding='utf-8').read()
        want = re.search(r'^VERSION = (\d+)', src, re.M).group(1)
        try:
            with open(os.path.join(out, 'version.txt')) as f:
                have = f.read().strip()
        except OSError:
            have = ''
        if have == want or not os.path.isdir(usr):
            return
        try:
            import PIL  # noqa: F401
        except ImportError:   # a setup from before fix 91 (setup/requirements.txt has it now)
            say('  installing Pillow (draws the keyboard / mouse button icons) ...')
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '-q', 'Pillow>=10'],
                           check=True, stdin=subprocess.DEVNULL)
        sys.path.insert(0, os.path.join(ROOT, 'tools'))
        import kbm_icons as k
        n = k.make(usr, out)
        say(f'  keyboard / mouse button icons: {n} of 3 made in {out}')
    except Exception as e:   # noqa: BLE001 -- an optional extra
        say(f'  keyboard / mouse button icons not made ({e}); the game shows the PS3 buttons')


def sync_patches():
    """An update of this repo since SETUP.bat: re-apply the patches that changed (setup/patch_sync.py).
    When one cannot be re-applied in place (a copy without git history, or an update that stopped
    halfway), redo that SETUP.bat step here: ps3recomp set up again (step 3), or the game code
    recompiled from the extracted EBOOT.elf (steps 4 + 5, a few minutes). Returns False only when that
    needs SETUP.bat itself (no extracted game)."""
    import patch_sync
    import setup as S
    if patch_sync.sync_runtime(S.PS3RECOMP_COMMIT) == 'redo':
        say('  setting up ps3recomp again (what SETUP.bat step 3 does) ...')
        mark = os.path.join(S.PS3RECOMP, '.ds_patched')
        if os.path.isfile(mark):
            os.remove(mark)
        S.step_ps3recomp()
    if patch_sync.sync_lifted(S.lift_inputs()) == 'relift':
        if S.find_eboot_elf() is None:
            say(f'  Run {os.environ.get("DS_SETUP_NAME") or "SETUP.bat"} to bring this setup up to date (it keeps the game files).')
            return False
        say('  recompiling the game code from your EBOOT.elf (what SETUP.bat steps 4 + 5 do) ...')
        mark = os.path.join(S.PORT, '.lifted')
        if os.path.isfile(mark):
            os.remove(mark)
        S.step_lift()
    return True


if __name__ == '__main__':
    no_quickedit()
    a = sys.argv[1:]
    jobs = None
    if '--jobs' in a:
        i = a.index('--jobs'); jobs = a[i + 1]; del a[i:i + 2]
    if '--runtime-only' in a:   # toolchain check without the game (cross toolchain only)
        a.remove('--runtime-only')
        sys.exit(build_xwin(jobs, a, runtime_only=True))
    if not sync_patches():
        sys.exit(1)
    sys.exit(build(jobs, a))
