#!/usr/bin/env python3
"""Steam library entry for Demon's Souls: artwork from your own disc, and a non-Steam shortcut.

    python3 linux/native/steam.py art      only make the artwork (port/steam_art/)
    python3 linux/native/steam.py add      add or update the shortcut, with the artwork (Steam must be closed)

The artwork is cut from the game's own PS3_GAME/PIC1.PNG (the XMB background) in game/, so it comes from
your copy of the game and is not in this repository: a portrait capsule (600x900), the wide capsule
(920x430), the hero banner (1920x620), the logo on a transparent background, and a square icon.

add writes Steam's shortcuts.vdf for every Steam user on this computer: a "Demon's Souls" shortcut that runs
linux/native/launcher.py --play (the game with the launcher's saved settings), made once and updated after
(found by its linux/native path). A shortcut for the Proton build (linux/play.sh) gets the same artwork.
Steam rewrites shortcuts.vdf when it exits, so it has to be closed while this runs: --restart-steam closes
it and starts it again (the installer and the launcher ask first).

Needs Pillow; without it, this runs itself again in the port's Python environment (.venv), installing
Pillow there first.
"""
import os
import shlex
import struct
import subprocess
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PIC1 = os.path.join(ROOT, 'game', 'PS3_GAME', 'PIC1.PNG')
ART = os.path.join(ROOT, 'port', 'steam_art')
NAME = "Demon's Souls"
LAUNCHER = os.path.join(HERE, 'launcher.py')

# Where things are in PIC1 (1920x1080): the "Demon's Souls" logo, and the dragon's open mouth.
LOGO_BOX = (790, 740, 1350, 975)
MOUTH = (1060, 430)


# --- artwork -------------------------------------------------------------------------------------------
def make_art(out=ART):
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
    if not os.path.isfile(PIC1):
        raise SystemExit('no %s: the game files are not there yet (install first)' % PIC1)
    os.makedirs(out, exist_ok=True)
    src = Image.open(PIC1).convert('RGB')
    W, H = src.size

    def fit(box, size):
        return src.crop(box).resize(size, Image.LANCZOS)

    def save(im, name):
        p = os.path.join(out, name)
        im.save(p + '.tmp.png')
        os.replace(p + '.tmp.png', p)

    # The logo alone: bright letters keyed out of the fog behind them, with a soft dark edge so it reads
    # over any picture (Steam lays it over the hero banner).
    region = src.crop(LOGO_BOX)
    lum = ImageOps.grayscale(region)
    # The letters reach white; the fog behind the right half tops out near 210. So: the letters are what is
    # brighter than the fog, plus a 2-pixel band around them for their soft edges.
    core = lum.point(lambda v: 255 if v > 218 else 0).filter(ImageFilter.MedianFilter(3))
    near = core.filter(ImageFilter.MaxFilter(5))
    ramp = lum.point(lambda v: 0 if v < 165 else 255 if v > 232 else int((v - 165) * 255 / 67))
    # the letters' dark grunge specks are part of the logo: fill the inside of the letters (a closing)
    inside = core.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    alpha = ImageChops.lighter(ImageChops.multiply(ramp, near), inside)
    bbox = alpha.point(lambda v: 255 if v > 60 else 0).getbbox() or (0, 0) + region.size
    pad = 14
    bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(region.width, bbox[2] + pad),
            min(region.height, bbox[3] + pad))
    letters = Image.new('RGBA', region.size)
    letters.paste(region, (0, 0))
    letters.putalpha(alpha)
    shadow = Image.new('RGBA', region.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(4)).point(
        lambda v: int(v * 0.85)))
    logo = Image.alpha_composite(shadow, letters).crop(bbox)
    scale = 1280 / logo.width
    save(logo.resize((1280, int(logo.height * scale)), Image.LANCZOS), 'logo.png')

    # Portrait capsule: the dragon and the logo, centred on the mouth.
    cw = H * 600 // 900
    x0 = min(max(0, MOUTH[0] - cw // 2), W - cw)
    save(fit((x0, 0, x0 + cw, H), (600, 900)), 'capsule.png')
    # Wide capsule: nearly the whole picture, logo included.
    wh = W * 430 // 920
    y0 = min(120, H - wh)
    save(fit((0, y0, W, y0 + wh), (920, 430)), 'wide.png')
    # Hero banner: the dragon without the logo (Steam draws logo.png over it).
    hh = W * 620 // 1920
    save(fit((0, 40, W, 40 + hh), (1920, 620)), 'hero.png')
    # Icon: the open mouth, square, a little more contrast for small sizes, rounded corners.
    s = 640
    icon = fit((MOUTH[0] - s // 2, MOUTH[1] - s // 2 - 40, MOUTH[0] + s // 2, MOUTH[1] + s // 2 - 40), (256, 256))
    icon = ImageOps.autocontrast(icon, cutoff=1).convert('RGBA')
    mask = Image.new('L', (256 * 4, 256 * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 256 * 4 - 1, 256 * 4 - 1), radius=44 * 4, fill=255)
    icon.putalpha(mask.resize((256, 256), Image.LANCZOS))
    save(icon, 'icon.png')
    return out


# --- shortcuts.vdf (Steam's binary key-value format) --------------------------------------------------
def vdf_parse(d, i=0):
    out = []
    while True:
        t = d[i]
        i += 1
        if t == 8:
            return out, i
        j = d.index(b'\0', i)
        k = d[i:j].decode('utf-8', 'surrogateescape')
        i = j + 1
        if t == 0:
            v, i = vdf_parse(d, i)
        elif t == 1:
            j = d.index(b'\0', i)
            v = d[i:j].decode('utf-8', 'surrogateescape')
            i = j + 1
        elif t == 2:
            v = struct.unpack('<i', d[i:i + 4])[0]
            i += 4
        else:
            raise ValueError('shortcuts.vdf: unknown field type %d at %d' % (t, i - 1))
        out.append([t, k, v])


def vdf_dump(items):
    b = bytearray()
    for t, k, v in items:
        b.append(t)
        b += k.encode('utf-8', 'surrogateescape') + b'\0'
        if t == 0:
            b += vdf_dump(v)
        elif t == 1:
            b += v.encode('utf-8', 'surrogateescape') + b'\0'
        else:
            b += struct.pack('<i', v)
    b.append(8)
    return bytes(b)


def field(entry, key, default=None):
    for t, k, v in entry:
        if k.lower() == key.lower():
            return v
    return default


def set_field(entry, key, t, value):
    for f in entry:
        if f[1].lower() == key.lower():
            f[0], f[2] = t, value
            return
    entry.append([t, key, value])


def new_entry(exe, start, name, opts):
    # Steam's own id for a non-Steam shortcut: crc32 of exe + name with the top bit set.
    appid = (zlib.crc32((exe + name).encode('utf-8')) & 0xffffffff) | 0x80000000
    return [[2, 'appid', struct.unpack('<i', struct.pack('<I', appid))[0]], [1, 'AppName', name], [1, 'Exe', exe],
            [1, 'StartDir', start], [1, 'icon', ''], [1, 'ShortcutPath', ''], [1, 'LaunchOptions', opts],
            [2, 'IsHidden', 0], [2, 'AllowDesktopConfig', 1], [2, 'AllowOverlay', 1], [2, 'OpenVR', 0],
            [2, 'Devkit', 0], [1, 'DevkitGameID', ''], [2, 'DevkitOverrideAppID', 0], [2, 'LastPlayTime', 0],
            [1, 'FlatpakAppID', ''], [1, 'sortas', ''], [0, 'tags', []]]


def steam_users():
    seen, out = set(), []
    for base in ('~/.steam/steam', '~/.local/share/Steam', '~/.var/app/com.valvesoftware.Steam/data/Steam'):
        ud = os.path.join(os.path.expanduser(base), 'userdata')
        if not os.path.isdir(ud) or os.path.realpath(ud) in seen:
            continue
        seen.add(os.path.realpath(ud))
        for u in sorted(os.listdir(ud)):
            if u.isdigit() and u != '0' and os.path.isdir(os.path.join(ud, u, 'config')):
                out.append(os.path.join(ud, u, 'config'))
    return out


def steam_running():
    return subprocess.run(['pgrep', '-x', 'steam'], stdout=subprocess.DEVNULL).returncode == 0


def add_to_steam(log=print):
    art = make_art()
    users = steam_users()
    if not users:
        raise SystemExit('no Steam user found (log in to Steam once first)')
    exe = '"%s"' % LAUNCHER
    start = '"%s"' % ROOT
    for cfg in users:
        path = os.path.join(cfg, 'shortcuts.vdf')
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                data = f.read()
            top, _ = vdf_parse(data)
            if not top or top[0][1].lower() != 'shortcuts':
                raise SystemExit('%s: not a shortcuts file' % path)
        else:
            top = [[0, 'shortcuts', []]]
        entries = top[0][2]
        native = [e for t, k, e in entries if t == 0 and '/linux/native/' in field(e, 'Exe', '') +
                  field(e, 'LaunchOptions', '')]
        proton = [e for t, k, e in entries if t == 0 and 'linux/play.sh' in field(e, 'Exe', '') +
                  field(e, 'LaunchOptions', '') and 'demons-souls' in (field(e, 'Exe', '') +
                                                                         field(e, 'LaunchOptions', '')).lower()]
        if native:
            e = native[0]
            set_field(e, 'Exe', 1, exe)
            set_field(e, 'StartDir', 1, start)
            set_field(e, 'LaunchOptions', 1, '--play')
            what = 'updated'
        else:
            e = new_entry(exe, start, NAME, '--play')
            entries.append([0, str(len(entries)), e])
            what = 'added'
        grid = os.path.join(cfg, 'grid')
        os.makedirs(grid, exist_ok=True)
        for ent in [e] + proton:
            gid = field(ent, 'appid') & 0xffffffff
            for src, dst in (('capsule.png', '%dp.png'), ('wide.png', '%d.png'), ('hero.png', '%d_hero.png'),
                             ('logo.png', '%d_logo.png'), ('icon.png', '%d_icon.png')):
                with open(os.path.join(art, src), 'rb') as fi, open(os.path.join(grid, dst % gid), 'wb') as fo:
                    fo.write(fi.read())
            set_field(ent, 'icon', 1, os.path.join(grid, '%d_icon.png' % gid))
        # the logo's place over the hero banner: bottom left, as most games have it
        for ent in [e] + proton:
            gid = field(ent, 'appid') & 0xffffffff
            with open(os.path.join(grid, '%d.json' % gid), 'w') as f:
                f.write('{"nVersion":1,"logoPosition":{"pinnedPosition":"BottomLeft",'
                        '"nWidthPct":36,"nHeightPct":60}}')
        if os.path.isfile(path):
            bak = path + '.before-demons-souls'
            if not os.path.exists(bak):
                with open(bak, 'wb') as f:
                    f.write(data)
        with open(path + '.tmp', 'wb') as f:
            f.write(vdf_dump(top))
        os.replace(path + '.tmp', path)
        log('%s the "%s" shortcut (with artwork%s) for Steam user %s' % (
            what, field(e, 'AppName'), ', and on the Proton one' if proton else '',
            os.path.basename(os.path.dirname(cfg))))


def restart_steam_around(fn):
    """Close Steam, run fn, start Steam again (if it was running and this is not game mode)."""
    was = steam_running()
    if was:
        subprocess.call(['steam', '-shutdown'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(120):
            if not steam_running():
                break
            time.sleep(0.5)
        else:
            raise SystemExit('Steam did not close; close it and run this again')
        time.sleep(1)
    try:
        fn()
    finally:
        if was and os.environ.get('XDG_CURRENT_DESKTOP', '').lower() != 'gamescope':
            subprocess.Popen(['steam'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def ensure_pillow():
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        pass
    venv = os.path.join(ROOT, '.venv')
    vpy = os.path.join(venv, 'bin', 'python')
    # (the venv's python is a symlink to the system one: compare the environment, not the executable)
    if os.path.realpath(sys.prefix) == os.path.realpath(venv):
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
                               'Pillow'])
        return
    if not os.access(vpy, os.X_OK):
        raise SystemExit('Pillow (python3-pil) is needed, or the port\'s .venv (linux/native/build.sh venv)')
    if os.environ.get('DES_STEAM_NESTED'):
        raise SystemExit('Pillow is missing in %s' % venv)
    os.execve(vpy, [vpy, os.path.abspath(__file__)] + sys.argv[1:], dict(os.environ, DES_STEAM_NESTED='1'))


def main():
    args = sys.argv[1:]
    ensure_pillow()
    if args[:1] == ['art']:
        print('artwork in', make_art())
    elif args[:1] == ['add']:
        if '--restart-steam' in args:
            restart_steam_around(add_to_steam)
        elif steam_running():
            raise SystemExit('Steam is running and rewrites its shortcuts when it exits: close it first, or '
                             'run this with --restart-steam')
        else:
            add_to_steam()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
