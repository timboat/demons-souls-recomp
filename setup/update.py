"""Updates a copy of this kit that was not made with git clone (a release ZIP, or GitHub's "Download ZIP"):
asks GitHub for the newest release, downloads its ZIP (checked against the sha256 GitHub publishes for it) and
copies its files over this folder. The launcher's "Check for updates" runs it (--check, then --install) and then
BUILD.bat, which rebuilds what changed. A git clone updates with git pull instead.

  update.py --check            prints latest=<tag>, current=<tag or unknown>, note=<line>... ; exit 1 on error
  update.py --install          downloads the newest release and copies it over this folder
  update.py --install --zip F --tag T   the same from a ZIP on disk (tests)

Only the kit's own files are written: game\\, port\\, deps\\, .venv\\, saves, logs and settings are not in the ZIP
and are never touched. VERSION (written last) says which release this folder now has.
"""
import hashlib, json, os, re, sys, time, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netcert                                                   # noqa: E402
netcert.install()   # HTTPS on a fresh Windows: let Windows fetch missing root certificates (netcert.py)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = 'timboat/demons-souls-recomp'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
VERSION = os.path.join(ROOT, 'VERSION')
# never written, even if a ZIP had them: what SETUP makes on this PC and what the player keeps
KEEP = {'game', 'game_remaster', 'game_mod', 'game_bossrush', 'bossrush', 'port', 'deps', '.venv', '.git', 'hdd0',
        'hdd1', 'gamedata', 'logs', 'perf', 'captures', 'launcher.ini', 'update_pending.txt'}


def say(msg=''):
    print(msg, flush=True)


# The launcher reads --check through a pipe as UTF-8; a piped Python writes the ANSI code page by default, where a
# character of the release notes such as an arrow would not even encode.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass


def latest():
    req = urllib.request.Request(API, headers={'Accept': 'application/vnd.github+json',
                                               'User-Agent': 'DemonsSoulsRecomp-updater'})
    with urllib.request.urlopen(req, timeout=30) as r:
        rel = json.load(r)
    a = next(a for a in rel['assets'] if a['name'].startswith('DemonsSoulsRecomp-') and a['name'].endswith('.zip'))
    return rel['tag_name'], a, rel.get('body') or ''


def current():
    try:
        with open(VERSION, encoding='utf-8') as f:
            return f.read().strip() or 'unknown'
    except OSError:
        return 'unknown'


def notes(body, n=6):
    """The release notes' "New in this release" list (else their start), as plain short lines."""
    lines = body.replace('\r', '').split('\n')
    try:
        i = next(k for k, l in enumerate(lines) if l.lower().startswith('## new'))
        lines = lines[i + 1:]
    except StopIteration:
        pass
    out = []
    for l in lines:
        if l.startswith('## '):
            break
        l = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', l).replace('**', '').replace('`', '').strip()   # [text](url) -> text
        if l.startswith('- '):
            out.append(l)
        elif l and out:
            out[-1] += ' ' + l
        if len(out) >= n:
            break
    return [o if len(o) <= 200 else o[:197] + '...' for o in out]


def check():
    try:
        tag, a, body = latest()
    except (OSError, ValueError, KeyError, StopIteration) as e:
        say(f'error=could not ask GitHub ({e})')
        return 1
    say(f'latest={tag}')
    say(f'current={current()}')
    say(f'size={a.get("size", 0)}')
    for l in notes(body):
        say(f'note={l}')
    return 0


def download(a, dest):
    want = (a.get('digest') or '').lower()
    want = want[7:] if want.startswith('sha256:') else ''
    h = hashlib.sha256()
    say(f'  downloading {a["name"]} ({max(1, a.get("size", 0) >> 10)} KB) from GitHub')
    req = urllib.request.Request(a['browser_download_url'], headers={'User-Agent': 'DemonsSoulsRecomp-updater'})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, 'wb') as f:
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            h.update(b)
            f.write(b)
    if want and h.hexdigest() != want:
        os.remove(dest)
        raise ValueError('the download does not match the checksum GitHub publishes for it')


def put(path, data):
    """Write a file through a temporary name; the launcher's own exe may still be running for a moment after it
    started this update: wait for it, and as a last resort rename the running exe aside (Windows allows that)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.new'
    with open(tmp, 'wb') as f:
        f.write(data)
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.25)
    old = path + '.old'
    try:
        if os.path.exists(old):
            os.remove(old)
    except OSError:
        pass
    os.replace(path, old)
    os.replace(tmp, path)


def install(zip_path=None, tag=None):
    os.makedirs(os.path.join(ROOT, 'deps'), exist_ok=True)
    own = zip_path is None
    if own:
        tag, a, _ = latest()
        zip_path = os.path.join(ROOT, 'deps', 'update.zip')
        download(a, zip_path)
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for i in z.infolist():
            parts = i.filename.replace('\\', '/').split('/')
            # only the release's own folder (DemonsSoulsRecomp-<tag>/...), plain relative names, nothing KEEP
            # names in any letter case (Windows does not tell them apart)
            if (i.is_dir() or len(parts) < 2 or not parts[0].startswith('DemonsSoulsRecomp-') or not parts[-1] or
                    any(p in ('', '.', '..') or ':' in p for p in parts[1:]) or parts[1].lower() in KEEP):
                continue
            put(os.path.join(ROOT, *parts[1:]), z.read(i))
            n += 1
    if own:
        os.remove(zip_path)
    with open(VERSION, 'w', encoding='utf-8') as f:
        f.write(tag + '\n')
    say(f'  {tag}: {n} files updated (your game files, build, saves and settings were not touched)')
    return 0


if __name__ == '__main__':
    if '--install' in sys.argv:   # its own console window: a click must not pause it
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import build
            build.no_quickedit()
        except Exception:
            pass
    a = sys.argv[1:]
    if '--check' in a:
        sys.exit(check())
    if '--install' in a:
        z = a[a.index('--zip') + 1] if '--zip' in a else None
        t = a[a.index('--tag') + 1] if '--tag' in a else None
        try:
            sys.exit(install(z, t))
        except (OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile) as e:
            say(f'  the update failed: {e}')
            sys.exit(1)
    say(__doc__)
    sys.exit(2)
