"""Keyboard / mouse button icons for the game's PS3 button atlases (docs/NOTES.md fix 91).

The runtime draws a file from textures\\kbm instead of a texture while the keyboard / mouse is what was used
last, and the PS3 art again once the pad is (rsx_tex_pack.c). This makes those files from YOUR copy of the
game: the three atlases that hold the button glyphs (the text font page with the in-text icons, and two menu
sheets), each PS3 button cell redrawn as the key / mouse button it is on the keyboard layout (PAD_KEYMAP=souls).
Letters are the game's own serif font (dsfont24); key plates, mice and arrows are drawn here in the colours of
the game's own button art. Nothing from the game is in this script.

The keys are your bindings (fix 103): the launcher's Controls window keeps them in launcher.ini [controls]
(the defaults are the souls layout), and each cell shows the key its button is bound to. keys.txt in the output
folder records the bindings drawn; --if-stale only draws again when they or the art (VERSION) changed -- the
launcher runs that before Play, BUILD.bat after a build (setup/build.py kbm_icons). By hand:
    .venv\\Scripts\\python.exe tools\\kbm_icons.py [<game>\\PS3_GAME\\USRDIR] [<out folder>] [--preview] [--if-stale]
defaults game\\PS3_GAME\\USRDIR and textures\\kbm next to this repo. Needs Pillow (pip install Pillow).
--preview also writes <out>\\preview.png: each atlas's original cells above the new ones, 4x.
"""
import hashlib, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import souls_formats as sf
from PIL import Image, ImageDraw, ImageFilter

VERSION = 2                                # bump when the art changes: BUILD.bat then makes the files again
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
U = os.path.join(ROOT, 'game', 'PS3_GAME', 'USRDIR')
SS = 8                                     # supersampling for drawn shapes
CREAM = (232, 222, 196)                    # the game's button lettering (Menu00 L1 / Menu08 L)
GOLD = (236, 176, 64)                      # the game's d-pad arrows
PLATE_TOP, PLATE_BOT = (58, 58, 62), (14, 14, 16)

# ---- the key bindings (cellPad.c s_kb: the same action names and defaults; key names as pad_vk_from_name)
DEFAULT_KEYS = {'attack': ['LMB'], 'strong_attack': ['SHIFT'], 'block': ['RMB'], 'parry': ['CTRL'],
                'roll': ['SPACE'], 'interact': ['E'], 'two_hand': ['F'], 'use_item': ['R'],
                'lock_on': ['TAB', 'MMB'], 'l3': ['C'], 'dpad_up': ['UP'], 'dpad_down': ['DOWN'],
                'dpad_left': ['LEFT'], 'dpad_right': ['RIGHT'], 'start': ['ENTER'], 'select': ['BACK']}
KEY_TEXT = {'CTRL': 'Ctrl', 'RCTRL': 'Ctrl', 'ALT': 'Alt', 'RALT': 'Alt', 'TAB': 'Tab', 'CAPS': 'Caps',
            'INS': 'Ins', 'DEL': 'Del', 'HOME': 'Home', 'END': 'End', 'PGUP': 'PgUp', 'PGDN': 'PgDn',
            'MB4': 'M4', 'MB5': 'M5', 'MINUS': '-', 'EQUALS': '=', 'LBRACKET': '[', 'RBRACKET': ']',
            'BACKSLASH': '\\', 'SEMICOLON': ';', 'QUOTE': "'", 'COMMA': ',', 'PERIOD': '.', 'SLASH': '/',
            'GRAVE': '`', 'ENTER': 'Enter', 'BACK': 'Backspace', 'SPACE': 'Space', 'SHIFT': 'Shift',
            'RSHIFT': 'Shift', 'LMB': 'LMB', 'RMB': 'RMB', 'MMB': 'MMB'}
KEYS = dict(DEFAULT_KEYS)


def read_bindings(ini=None):
    """launcher.ini [controls]: action = KEY or KEY+KEY ('' = unbound); a missing action keeps its default."""
    import configparser
    keys = {a: list(v) for a, v in DEFAULT_KEYS.items()}
    ini = ini or os.path.join(ROOT, 'launcher.ini')
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(ini, encoding='utf-16') if open(ini, 'rb').read(2) in (b'\xff\xfe', b'\xfe\xff') else cp.read(ini)
    except (OSError, configparser.Error, UnicodeError):
        return keys
    if cp.has_section('controls'):
        for a in keys:
            if cp.has_option('controls', a):
                keys[a] = [k.strip().upper() for k in cp.get('controls', a).split('+') if k.strip()][:2]
    return keys


def signature(keys):
    return ';'.join('%s=%s' % (a, '+'.join(keys[a])) for a in sorted(keys))


def first(action):
    k = KEYS.get(action) or []
    return k[0] if k else None


def text_of(k):
    return KEY_TEXT.get(k) or (('Num' + k[3:]) if k.startswith('NUM') else k)


def icon(action, style='font', wide=False, menu_frac=0.62):
    """The icon maker for the key an action is bound to. style 'font': the text font page; 'menu': a Menu00 / 08
    plate cell (mice big on a black plate); 'emboss': the Menu00 L2 / R2 engraved text."""
    k = first(action)
    if k is None:   # unbound: an empty plate
        return lambda w, h: down(plate(w, h), w, h)
    if style == 'emboss':
        return emboss(text_of(k) if k not in ('LMB', 'RMB', 'MMB') else {'LMB': 'LMB', 'RMB': 'RMB', 'MMB': 'MMB'}[k])
    mouse = {'LMB': 'left', 'RMB': 'right', 'MMB': 'middle'}.get(k)
    if mouse:
        if style == 'menu':
            return menu_plate_icon(lambda w, h: mouse_icon(w, h, mouse, big=True))
        return lambda w, h: mouse_icon(w, h, mouse)
    if k in ('UP', 'DOWN', 'LEFT', 'RIGHT'):
        return lambda w, h: arrow_key(w, h, [k.lower()])
    if not wide and k in ('SPACE', 'SHIFT', 'RSHIFT', 'ENTER', 'BACK'):
        kind = {'SPACE': 'space', 'SHIFT': 'shift', 'RSHIFT': 'shift', 'ENTER': 'enter', 'BACK': 'back'}[k]
        return lambda w, h: symbol_key(w, h, kind)
    t = text_of(k)
    frac = 0.52 if wide else 0.62 if len(t) == 1 else 0.46
    if style == 'menu':
        return lambda w, h: key_icon(w, h, t, menu_frac if len(t) == 1 else 0.46)
    return kc(t, frac)


def dpad_icon(dirs):
    """The d-pad cells: the arrow cluster while the d-pad is on the arrow keys, else key plates in that layout."""
    ks = [first('dpad_' + d) for d in dirs]
    if ks == [d.upper() for d in dirs]:
        return lambda w, h: arrow_key(w, h, dirs)
    def f(w, h):
        W, H = w * SS, h * SS
        im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        k = w // 2
        pos = {'up': (W / 4, 0), 'down': (W / 4, H / 2), 'left': (0, H / 2), 'right': (W / 2, H / 2)}
        if len(dirs) == 4:   # three plates side by side below one: labels must not overlap
            k = w // 3
            pos = {'up': (W / 3, 0), 'left': (0, H / 2), 'down': (W / 3, H / 2), 'right': (2 * W / 3, H / 2)}
        if set(dirs) == {'left', 'right'}:
            pos = {'left': (0, H / 4), 'right': (W / 2, H / 4)}
        if set(dirs) == {'up', 'down'}:
            pos = {'up': (W / 4, 0), 'down': (W / 4, H / 2)}
        for d, key in zip(dirs, ks):
            p = plate(k, min(k, h // 2) if len(dirs) == 4 else k)
            if key:
                place_label(p, text_img(text_of(key)[:3]), 0.62)
            im.alpha_composite(p, (int(pos[d][0]), int(pos[d][1])))
        return down(im, w, h)
    return f


def tex(tpf, name):
    t = [x for x in sf.Tpf(open(os.path.join(U, tpf), 'rb').read()).textures if x['name'] == name][0]
    w, h, px = sf.decode_texture(t)
    return Image.frombytes('RGBA', (w, h), bytes(px))


# ---- the game's font: glyph table from dsfont24.ccm (big-endian: group / glyph counts at 0x10, their offsets
# at 0x14; a group = first code, last code, first glyph; a glyph = u1 v1 u2 v2 floats, then pre, width, advance,
# page shorts), pages from dsfont24.tpf
FONT_DATA = {}


def load_font():
    fdir = os.path.join(U, 'FONT', 'NA_ENGLISH')
    ccm = open(os.path.join(fdir, 'dsfont24.ccm'), 'rb').read()
    ngr, ngl = struct.unpack_from('>HH', ccm, 0x10)
    go, glo = struct.unpack_from('>II', ccm, 0x14)
    cmap = {}
    for i in range(ngr):
        a, b, first = struct.unpack_from('>III', ccm, go + 12 * i)
        for c in range(a, b + 1):
            cmap[c] = first + c - a
    pages = {i: Image.frombytes('RGBA', (x['w'], x['h']), bytes(sf.decode_texture(x)[2]))
             for i, x in enumerate(sf.Tpf(open(os.path.join(fdir, 'dsfont24.tpf'), 'rb').read()).textures)}
    FONT_DATA.update(ccm=ccm, glo=glo, cmap=cmap, pages=pages)


def glyph(ch):
    ccm, glo, cmap, pages = FONT_DATA['ccm'], FONT_DATA['glo'], FONT_DATA['cmap'], FONT_DATA['pages']
    u1, v1, u2, v2, pre, width, adv, ti = struct.unpack_from('>4f4h', ccm, glo + 24 * cmap[ord(ch)])
    p = pages[ti]
    box = (round(u1 * p.width), round(v1 * p.height), round(u2 * p.width), round(v2 * p.height))
    return p.crop(box), pre, adv


def text_img(s, track=0):
    """The string in the game font: white RGBA on transparent, at the font's own 24 px."""
    parts = [glyph(c) for c in s]
    w = sum(a for _, _, a in parts) + track * (len(s) - 1) + 4
    h = max(g.height for g, _, _ in parts)
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    x = 2
    for g, pre, adv in parts:
        im.alpha_composite(g, (max(0, x + pre), 0))
        x += adv + track
    a = im.getchannel('A')
    bb = a.getbbox()
    return im.crop(bb) if bb else im


def tint(im, col):
    """The font pages are white glyphs with alpha: keep the alpha, colour by luminance (the outline darker)."""
    a = im.getchannel('A')
    l = im.convert('L')
    r = Image.eval(l, lambda v: v * col[0] // 255)
    g = Image.eval(l, lambda v: v * col[1] // 255)
    b = Image.eval(l, lambda v: v * col[2] // 255)
    return Image.merge('RGBA', (r, g, b, a))


def plate(w, h, round_=True, rim=True):
    """A dark key plate like the game's L1/R1 glyphs: vertical gradient, grey rim, rounded corners. (SS-scaled)"""
    W, H = w * SS, h * SS
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    grad = Image.new('RGBA', (W, H))
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        t = y / max(1, H - 1)
        gd.line((0, y, W, y), fill=tuple(int(PLATE_TOP[i] * (1 - t) + PLATE_BOT[i] * t) for i in range(3)) + (255,))
    m = Image.new('L', (W, H), 0)
    r = int(min(W, H) * (0.22 if round_ else 0.06))
    ImageDraw.Draw(m).rounded_rectangle((SS, SS, W - SS - 1, H - SS - 1), r, fill=255)
    im.paste(grad, (0, 0), m)
    d = ImageDraw.Draw(im)
    if rim:
        d.rounded_rectangle((SS, SS, W - SS - 1, H - SS - 1), r, outline=(120, 120, 126, 255), width=max(1, SS // 2))
        d.rounded_rectangle((0, 0, W - 1, H - 1), r + SS, outline=(0, 0, 0, 200), width=SS)
    return im


def down(im, w, h):
    return im.resize((w, h), Image.LANCZOS)


def place_label(base_ss, lab, frac=0.62, dy=0.0):
    """Centre a game-font label (24 px native) on an SS-scaled plate, height = frac of the plate."""
    W, H = base_ss.size
    lab = tint(lab, CREAM)
    s = min(H * frac / lab.height, W * 0.78 / lab.width)
    L = lab.resize((max(1, int(lab.width * s)), max(1, int(lab.height * s))), Image.LANCZOS)
    shadow = Image.new('RGBA', L.size, (0, 0, 0, 0))
    shadow.putalpha(L.getchannel('A'))
    x, y = (W - L.width) // 2, int((H - L.height) / 2 + dy * H)
    base_ss.alpha_composite(shadow, (x + SS // 2, y + SS // 2))
    base_ss.alpha_composite(L, (x, y))
    return base_ss


def key_icon(w, h, s, frac=0.62):
    return down(place_label(plate(w, h), text_img(s), frac), w, h)


def arrow(d, cx, cy, size, direction, col=GOLD):
    s = size
    pts = {'up': [(cx, cy - s), (cx - s, cy + s * 0.6), (cx + s, cy + s * 0.6)],
           'down': [(cx, cy + s), (cx - s, cy - s * 0.6), (cx + s, cy - s * 0.6)],
           'left': [(cx - s, cy), (cx + s * 0.6, cy - s), (cx + s * 0.6, cy + s)],
           'right': [(cx + s, cy), (cx - s * 0.6, cy - s), (cx - s * 0.6, cy + s)]}[direction]
    d.polygon(pts, fill=col + (255,), outline=(60, 40, 10, 255))


def arrow_key(w, h, dirs):
    """Arrow keys: one plate per direction listed, laid out like the arrow cluster (gold arrows)."""
    W, H = w * SS, h * SS
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    if len(dirs) == 1:
        p = plate(w, h); d = ImageDraw.Draw(p); arrow(d, W / 2, H / 2, W * 0.24, dirs[0]); return down(p, w, h)
    k = w // 2
    pos = {'up': (W / 4, 0), 'down': (W / 4, H / 2), 'left': (0, H / 2), 'right': (W / 2, H / 2)}
    if set(dirs) == {'left', 'right'}:
        pos = {'left': (0, H / 4), 'right': (W / 2, H / 4)}
    if set(dirs) == {'up', 'down'}:
        pos = {'up': (W / 4, 0), 'down': (W / 4, H / 2)}
    for dr in dirs:
        p = plate(k, k)
        arrow(ImageDraw.Draw(p), p.width / 2, p.height / 2, p.width * 0.26, dr)
        im.alpha_composite(p, (int(pos[dr][0]), int(pos[dr][1])))
    return down(im, w, h)


def mouse_icon(w, h, button=None, moving=False, plate_bg=False, big=False):
    """A mouse in the game's cream line style; button = 'left'|'right'|'middle' lit in gold; moving = arrows."""
    W, H = w * SS, h * SS
    im = plate(w, h, round_=False) if plate_bg else Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    mw, mh = W * (0.48 if moving else 0.70 if big else 0.56), H * (0.72 if moving else 0.96 if big else 0.80)
    x0, y0 = (W - mw) / 2, (H - mh) / 2
    body = (x0, y0, x0 + mw, y0 + mh)
    r = int(mw * 0.48)
    d.rounded_rectangle(body, r, fill=(20, 20, 22, 255), outline=CREAM + (255,), width=max(2, int(SS * (1.6 if big else 1))))
    split = y0 + mh * (0.46 if big else 0.42)
    if button in ('left', 'right'):   # the lit half of the top
        m = Image.new('L', (W, H), 0)
        md = ImageDraw.Draw(m)
        md.rounded_rectangle(body, r, fill=255)
        md.rectangle((0, split, W, H), fill=0)
        if button == 'left': md.rectangle((x0 + mw / 2, 0, W, H), fill=0)
        else: md.rectangle((0, 0, x0 + mw / 2, H), fill=0)
        m = m.filter(ImageFilter.MinFilter(max(3, (int(SS * (1.6 if big else 1)) + 1) | 1)))
        im.paste(Image.new('RGBA', (W, H), GOLD + (255,)), (0, 0), m)
    d.line((x0 + SS, split, x0 + mw - SS, split), fill=CREAM + (255,), width=max(2, SS // 2 + 1))
    d.line((x0 + mw / 2, y0 + SS, x0 + mw / 2, split), fill=CREAM + (255,), width=max(2, SS // 2 + 1))
    if button == 'middle':
        d.rounded_rectangle((x0 + mw / 2 - SS * 1.4, y0 + mh * 0.12, x0 + mw / 2 + SS * 1.4, y0 + mh * 0.34), SS,
                            fill=GOLD + (255,))
    if moving:
        a = W * 0.10
        arrow(d, W * 0.10, H / 2, a, 'left', CREAM); arrow(d, W * 0.90, H / 2, a, 'right', CREAM)
        arrow(d, W / 2, H * 0.06, a, 'up', CREAM); arrow(d, W / 2, H * 0.94, a, 'down', CREAM)
    return down(im, w, h)


def wasd_icon(w, h):
    """Movement: a small 4-key cluster without letters (keys go by position, AZERTY = ZQSD)."""
    W, H = w * SS, h * SS
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    k = int(W * 0.42)
    for (x, y) in ((W / 2 - k / 2, H * 0.06), (W / 2 - k * 1.5 + 0, H * 0.52), (W / 2 - k / 2, H * 0.52),
                   (W / 2 + k / 2, H * 0.52)):
        p = plate(k // SS, k // SS)
        ImageDraw.Draw(p).rounded_rectangle((SS, SS, p.width - SS - 1, p.height - SS - 1), int(p.width * 0.22),
                                            outline=CREAM + (255,), width=max(2, SS // 2 + 1))
        im.alpha_composite(p, (int(x), int(y)))
    return down(im, w, h)


def symbol_key(w, h, kind):
    p = plate(w, h)
    d = ImageDraw.Draw(p)
    W, H = p.size
    c = CREAM + (255,)
    lw = max(2, int(W * 0.07))
    if kind == 'space':   # the space bar sign
        y = H * 0.62
        d.line((W * 0.22, H * 0.42, W * 0.22, y, W * 0.78, y, W * 0.78, H * 0.42), fill=c, width=lw, joint='curve')
    elif kind == 'shift':   # outlined up arrow
        d.polygon([(W / 2, H * 0.18), (W * 0.20, H * 0.52), (W * 0.36, H * 0.52), (W * 0.36, H * 0.80),
                   (W * 0.64, H * 0.80), (W * 0.64, H * 0.52), (W * 0.80, H * 0.52)], outline=c, width=lw)
    elif kind == 'enter':
        d.line((W * 0.74, H * 0.24, W * 0.74, H * 0.60, W * 0.30, H * 0.60), fill=c, width=lw, joint='curve')
        d.polygon([(W * 0.20, H * 0.60), (W * 0.36, H * 0.46), (W * 0.36, H * 0.74)], fill=c)
    elif kind == 'back':
        d.line((W * 0.78, H / 2, W * 0.32, H / 2), fill=c, width=lw)
        d.polygon([(W * 0.20, H / 2), (W * 0.38, H * 0.34), (W * 0.38, H * 0.66)], fill=c)
    return down(p, w, h)


# ---- the cells (font page 26 px; wide SELECT 112 x 26, START 96 x 26)
def kc(s, frac=0.62):
    return lambda w, h: key_icon(w, h, s, frac)


def menu_plate_icon(inner):
    """Menu00 32 px: black plate like its L1/R1 cells, content inside."""
    def f(w, h):
        base = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(base).rectangle((1, 2, w - 2, h - 3), fill=(16, 16, 18, 255))
        ic = inner(w - 2, h - 4)
        base.alpha_composite(ic, (1, 2))
        return base
    return f


def emboss(s):
    """Menu00 L2/R2 'emboss' cells: engraved game-font text in the cell's own muted blue-grey."""
    def f(w, h):
        lab = text_img(s)
        sc = min(h * 0.52 / lab.height, w * 0.92 / lab.width)
        L = lab.resize((max(1, int(lab.width * sc)), max(1, int(lab.height * sc))), Image.LANCZOS)
        im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        x, y = (w - L.width) // 2, (h - L.height) // 2
        im.alpha_composite(tint(L, (40, 52, 70)), (x + 1, y + 1))
        im.alpha_composite(tint(L, (150, 165, 185)), (x, y))
        return im
    return f


def cells():
    """(box, icon maker) per atlas, for the current KEYS."""
    font = [  # (box, icon maker)            PS3 button -> its key
        ((0, 0, 26, 26), icon('two_hand')),                 # triangle
        ((26, 0, 52, 26), icon('use_item')),                # square
        ((52, 0, 78, 26), icon('roll')),                    # circle
        ((78, 0, 104, 26), icon('interact')),               # cross
        ((104, 0, 130, 26), dpad_icon(['up', 'left', 'down', 'right'])),   # d-pad
        ((156, 0, 182, 26), icon('attack')),                # R1
        ((182, 0, 208, 26), icon('strong_attack')),         # R2
        ((208, 0, 234, 26), icon('block')),                 # L1
        ((234, 0, 260, 26), icon('parry')),                 # L2
        ((260, 0, 286, 26), icon('lock_on')),               # R3
        ((286, 0, 312, 26), icon('l3')),                    # L3
        ((338, 0, 364, 26), dpad_icon(['left', 'right'])),
        ((364, 0, 390, 26), dpad_icon(['up', 'down'])),
        ((416, 0, 442, 26), lambda w, h: mouse_icon(w, h, None, moving=True)),   # right stick -> mouse
        ((442, 0, 468, 26), lambda w, h: wasd_icon(w, h)),                       # left stick -> move keys
        ((468, 0, 494, 26), icon('dpad_up')),
        ((0, 26, 26, 52), icon('dpad_down')),
        ((26, 26, 52, 52), icon('dpad_right')),
        ((52, 26, 78, 52), icon('dpad_left')),
        ((0, 52, 112, 78), icon('select', wide=True)),      # wide SELECT
        ((112, 52, 208, 78), icon('start', wide=True)),     # wide START
        ((130, 0, 156, 26), icon('select')),                # small SELECT
        ((390, 0, 416, 26), icon('start')),                 # small START
    ]
    menu00 = [((160, 0, 192, 32), icon('use_item', 'menu')),
              ((192, 0, 224, 32), icon('two_hand', 'menu')),
              ((160, 32, 192, 64), icon('roll', 'menu')),
              ((192, 32, 224, 64), icon('interact', 'menu')),
              ((256, 0, 288, 32), icon('block', 'menu')),                                 # L1
              ((256, 32, 288, 64), icon('attack', 'menu')),                               # R1
              ((288, 0, 320, 32), icon('parry', 'emboss')), ((320, 0, 352, 32), icon('parry', 'emboss')),   # L2
              ((288, 32, 320, 64), icon('strong_attack', 'emboss')),
              ((320, 32, 352, 64), icon('strong_attack', 'emboss'))]                     # R2
    menu08 = [((79, 404, 98, 423), icon('block', 'menu')),       # FE_key_L (L1)
              ((102, 404, 121, 423), icon('attack', 'menu')),    # FE_key_R (R1)
              ((79, 426, 98, 445), icon('use_item', 'menu', menu_frac=0.7))]    # FE_key_Square
    return {'DSFont24_1000': font, 'Menu00': menu00, 'Menu08': menu08}


# (file, texture, the runtime's texture-pack KEY of it as the game draws it, first 16 hex digits of the sha1 of
# the decoded original = the BLUS-30443 English disc's, cells). Another disc's atlas has another KEY: skipped.
JOBS = [(r'FONT\NA_ENGLISH\dsfont24.tpf', 'DSFont24_1000', 'CE4F0427E62376F5', '41ac2ad63b6a6e53'),
        (r'MENU\menu.tpf', 'Menu00', '073A392EE5388F44', '9209bebf1b636346'),
        (r'MENU\menu.tpf', 'Menu08', '0740A345421ED259', '0eec764f7e387a26')]


def up_to_date(out, keys=None):
    """The icons in out are from this VERSION and these bindings."""
    keys = keys or read_bindings()
    try:
        with open(os.path.join(out, 'version.txt')) as f:
            v = f.read().strip()
        with open(os.path.join(out, 'keys.txt')) as f:
            k = f.read().strip()
    except OSError:
        return False
    return v == str(VERSION) and k == signature(keys)


def make(usrdir, out, preview=False, keys=None):
    """-> how many atlases were written to out (<KEY>_kbm_<name>.png each), plus out\\version.txt and keys.txt
    (the bindings drawn; keys: action -> [key, key], default read_bindings())."""
    global U
    U = usrdir
    KEYS.clear()
    KEYS.update(keys or read_bindings())
    load_font()
    table = cells()
    os.makedirs(out, exist_ok=True)
    prev, n = [], 0
    for tpf, name, key, sha in JOBS:
        cl = table[name]
        orig = tex(tpf.replace('\\', os.sep), name)
        if hashlib.sha1(orig.tobytes()).hexdigest()[:16] != sha:
            print(f'  {name}: not the BLUS-30443 English one, left as it is')
            continue
        im = orig.copy()
        for (x0, y0, x1, y1), mk in cl:
            w, h = x1 - x0, y1 - y0
            im.paste(Image.new('RGBA', (w, h), (0, 0, 0, 0)), (x0, y0))
            im.alpha_composite(mk(w, h), (x0, y0))
        im.save(os.path.join(out, '%s_kbm_%s.png' % (key, name)))
        n += 1
        if preview:
            xs = [c[0] for c in cl]
            bx = (min(b[0] for b in xs), min(b[1] for b in xs), max(b[2] for b in xs), max(b[3] for b in xs))
            prev.append((orig.crop(bx), im.crop(bx)))
    with open(os.path.join(out, 'version.txt'), 'w') as f:
        f.write(f'{VERSION}\n')
    with open(os.path.join(out, 'keys.txt'), 'w') as f:
        f.write(signature(KEYS) + '\n')
    if prev:
        Z, rows = 4, []
        for a, b in prev:
            for im in (a, b):
                bg = Image.new('RGBA', im.size, (34, 34, 38, 255)); bg.alpha_composite(im)
                rows.append(bg.resize((im.width * Z, im.height * Z), Image.NEAREST))
        sheet = Image.new('RGBA', (max(r.width for r in rows), sum(r.height + 8 for r in rows)), (10, 10, 12, 255))
        y = 0
        for r in rows:
            sheet.alpha_composite(r, (0, y)); y += r.height + 8
        sheet.save(os.path.join(out, 'preview.png'))
    return n


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    usr = a[0] if a else U
    out = a[1] if len(a) > 1 else os.path.join(ROOT, 'textures', 'kbm')
    if '--if-stale' in sys.argv and up_to_date(out):
        sys.exit(0)
    n = make(usr, out, '--preview' in sys.argv)
    print(f'  {n} keyboard / mouse button atlases in {out}')
    sys.exit(0 if n else 1)
