#!/usr/bin/env python3
"""Demon's Souls launcher for the native Linux build (linux/native/build.sh, linux/native/play.sh).

One window for the play options, as DemonsSoulsLauncher.exe is on Windows and the launcher app on the Mac:
it keeps the choices in ~/.config/demons-souls-recomp/linux-launcher.json, sets the environment variables
linux/native/play.sh reads (DES_FPS, DES_GAME, DES_FULLSCREEN, ...) and runs it, so the window and play.sh
on its own always start the game the same way. It also rebuilds the game (linux/native/build.sh, its
"==> step" lines drive the progress bar), updates the checkout (git pull, then the build), and adds itself to
the applications menu (where Steam's "Add a Non-Steam Game" finds it). The first install, from your disc
image, is the installer's job (linux/native/install.sh); before it, Play opens the installer.

    python3 linux/native/launcher.py           the window
    python3 linux/native/launcher.py --steam   the window, for Steam's shortcut: Play has the focus, and the
                                               window closes when the game ends (back to the Steam library)
    python3 linux/native/launcher.py --play    starts the game with the saved settings, no window

A controller works the window (Steam's game mode has no mouse): up / down (D-pad or left stick) moves between
the items, left / right changes the one selected, A presses it, B backs out of a menu or a question, Start
plays. It is read from /dev/input/js* (Steam's virtual pad, or any pad the kernel knows), not at all while
the game runs. The arrow keys and Enter do the same from a keyboard -- and from the Deck's controls in
desktop mode, which type them.

Python 3.8+ with Tk (tkinter), nothing else: SteamOS has it; Debian / Ubuntu: sudo apt install python3-tk;
Fedora: sudo dnf install python3-tkinter; Arch: sudo pacman -S tk.
"""
import errno
import glob
import json
import os
import shlex
import signal
import struct
import subprocess
import sys
import threading
import time
try:
    import fcntl
except ImportError:     # not Linux: no controller, the window still works
    fcntl = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PLAY = os.path.join(HERE, 'play.sh')
BUILD = os.path.join(HERE, 'build.sh')
EXE = os.path.join(ROOT, 'port', 'build_linux', 'DemonsSoulsRecomp')
ELF = os.path.join(ROOT, 'game', 'PS3_GAME', 'USRDIR', 'EBOOT.elf')
CONF_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'demons-souls-recomp')
CONF = os.path.join(CONF_DIR, 'linux-launcher.json')
LOGS = os.path.join(ROOT, 'logs')
TRANSLATIONS = os.path.join(ROOT, 'translations', 'translations.py')
BUILD_LOG = os.path.join(LOGS, 'native_build.txt')


def is_deck():
    try:
        v = open('/sys/class/dmi/id/board_vendor').read().strip()
        p = open('/sys/class/dmi/id/product_name').read().strip()
        return v == 'Valve' and p in ('Jupiter', 'Galileo')
    except OSError:
        return False


DECK = is_deck()
DEFAULTS = {
    'fps': '60',               # 60 | 30 | unlimited
    'game': 'game',            # game | game_remaster | bossrush
    'br_souls': '1',
    'name': 'Slayer',
    'fullscreen': DECK,
    'movies': True,
    'async_shaders': True,     # new shaders built in the background: brief pop-in instead of a stutter
    'skip_intro': False,
    'omniroll': False,         # DES_OMNIROLL: locked-on rolls follow the stick (the OmniRoll mod, NOTES fix 165)
    'god': False,
    'gpu_clock': '800',        # Steam Deck: MHz or auto
    'lto': False,
    'language': 'en',          # an id from translations/translations.py list (en, fr, ar, ...)
}
STEPS = ['deps', 'venv', 'game', 'decrypt', 'toolkit', 'lift', 'build']


def load_conf():
    c = dict(DEFAULTS)
    try:
        with open(CONF) as f:
            c.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return c


def save_conf(c):
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = CONF + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(c, f, indent=2)
    os.replace(tmp, CONF)


def lang_game(c):
    """The game folder the language applies to: the one play.sh plays (boss rush is made from game/)."""
    return os.path.join(ROOT, 'game_remaster' if c['game'] == 'game_remaster' else 'game')


def lang_python():
    """The repo's venv Python runs translations.py (the installers need its packages); this one if there is none."""
    py = os.path.join(ROOT, '.venv', 'bin', 'python')
    return py if os.access(py, os.X_OK) else (sys.executable or 'python3')


def lang_list(game):
    """translations.py list for this game folder: (its JSON, None), or (None, why) when it cannot run."""
    try:
        r = subprocess.run([lang_python(), TRANSLATIONS, 'list', '--game', game], cwd=ROOT,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return None, 'Language list unavailable (%s): English only.' % e
    out = r.stdout.decode('utf-8', 'replace').strip().splitlines()
    try:
        if r.returncode != 0:
            raise ValueError
        data = json.loads(out[-1])
        data['choices'][0]
        return data, None
    except (ValueError, IndexError, KeyError, TypeError):
        why = (r.stderr.decode('utf-8', 'replace').strip().splitlines() or ['exit code %d' % r.returncode])[-1]
        return None, 'Language list unavailable (%s): English only.' % why


ENGLISH = {'id': 'en', 'label': 'English', 'kind': 'original', 'env': {}, 'available': True, 'note': ''}


def lang_choice(data, lang):
    """The choice to play with: the saved one when this game folder has it, otherwise English (an Arabic setting
    on the European disc plays in English, and the setting stays for the disc it is for)."""
    for ch in (data or {}).get('choices', []):
        if ch['id'] == lang and ch.get('available'):
            return ch
    return ENGLISH


def lang_needs_apply(data, ch):
    """True when translations.py apply has to run before playing: the choice is a translation not installed yet,
    or a translation is installed and the choice is something else."""
    if not data:
        return False
    inst = data.get('installed')
    return (ch['kind'] == 'translation' and inst != ch['id']) or (inst is not None and inst != ch['id'])


def lang_apply_argv(ch, game):
    return [lang_python(), TRANSLATIONS, 'apply', ch['id'], '--game', game]


def play_env(c, lang_env=None):
    """The environment play.sh gets for these settings (the launcher's own process environment plus these)."""
    e = dict(os.environ)
    # The language's variables (PS3_LANG=fr for the European disc's French; NOTES fix 162). One the player set in
    # the environment themselves keeps priority, as typed extra settings do in the other launchers.
    for k, val in (lang_env or {}).items():
        e.setdefault(k, val)
    e['DES_FPS'] = c['fps']
    e['DES_NAME'] = c['name'] or 'Slayer'
    e['DES_FULLSCREEN'] = '1' if c['fullscreen'] else '0'
    e['DES_MOVIES'] = '1' if c['movies'] else '0'
    e['DES_ASYNC_SHADERS'] = '1' if c['async_shaders'] else '0'
    for k in ('DES_GAME', 'DES_BOSS_RUSH', 'DES_BR_SOULS', 'DES_SKIP_INTRO', 'DES_GOD', 'DES_OMNIROLL'):
        e.pop(k, None)
    if c['game'] == 'bossrush':
        e['DES_BOSS_RUSH'] = '1'
        if c['br_souls'] != '1':
            e['DES_BR_SOULS'] = c['br_souls']
    elif c['game'] != 'game':
        e['DES_GAME'] = c['game']
    if c['skip_intro']:
        e['DES_SKIP_INTRO'] = '1'
    if c['omniroll']:
        e['DES_OMNIROLL'] = '1'
    if c['god']:
        e['DES_GOD'] = '1'
    if DECK:
        e['DES_GPU_CLOCK'] = c['gpu_clock'] or '800'
    return e


def play_now(c):
    """--play: start the game with the saved settings, no window."""
    if not os.access(EXE, os.X_OK):
        print('The native build is not there yet: run linux/native/install.sh first.')
        return 1
    # The language first (NOTES fix 162): install or remove a translation when the setting asks for it, and play
    # only when that worked. When translations.py cannot run, the game plays in English.
    game = lang_game(c)
    data, why = lang_list(game)
    if why:
        print(why, flush=True)
    ch = lang_choice(data, c['language'])
    if lang_needs_apply(data, ch):
        p = subprocess.Popen(lang_apply_argv(ch, game), cwd=ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
        for line in p.stdout:
            print(line.rstrip(), flush=True)
        if p.wait() != 0:
            print('The language could not be set (the line above says why); the game was not started.')
            return 1
    return subprocess.call(['bash', PLAY], cwd=ROOT, env=play_env(c, ch['env']))


class Gamepads:
    """The kernel's joystick devices (/dev/input/js*), read without blocking: poll() returns the actions
    since the last call -- 'up' 'down' 'left' 'right' (D-pad or left stick, repeating while held), 'a', 'b',
    'start'. Buttons and axes go by the kernel's own maps (JSIOCGBTNMAP / JSIOCGAXMAP), so A is the south
    face button and Start is Start on any pad the kernel knows; a device without a south button (a wheel,
    a flight stick, a keyboard receiver's "Multi Axis") is not a pad. When Steam's virtual pad is there
    (Valve's vendor id), it is the only one read: Steam mirrors the physical pads into it, and reading both
    would count every press twice. New pads are picked up every 2 s."""
    EV_BUTTON, EV_AXIS, EV_INIT = 0x01, 0x02, 0x80
    JSIOCGAXES, JSIOCGBUTTONS = 0x80016A11, 0x80016A12
    JSIOCGAXMAP, JSIOCGBTNMAP = 0x80406A32, 0x84006A34          # u8[ABS_CNT], u16[KEY_MAX - BTN_MISC + 1]
    BTN_SOUTH, BTN_EAST, BTN_START = 0x130, 0x131, 0x13B
    BTN_DPAD = {0x220: 'up', 0x221: 'down', 0x222: 'left', 0x223: 'right'}
    ABS_X, ABS_Y, ABS_HAT0X, ABS_HAT0Y = 0x00, 0x01, 0x10, 0x11
    REPEAT_FIRST, REPEAT_NEXT = 0.40, 0.12
    STICK, HAT = 20000, 16000

    def __init__(self):
        self.pads = {}          # path -> {'fd', 'buttons': {number: code}, 'axes': {number: code}, 'val', 'dpad', 'steam'}
        self.rescan_at = 0.0
        self.held = None        # the direction being held, and when it repeats next
        self.repeat_at = 0.0

    def _open(self, path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return None
        try:
            b = bytearray(1)
            fcntl.ioctl(fd, self.JSIOCGBUTTONS, b)
            nb = b[0]
            fcntl.ioctl(fd, self.JSIOCGAXES, b)
            na = b[0]
            bm = bytearray(1024)
            fcntl.ioctl(fd, self.JSIOCGBTNMAP, bm)
            am = bytearray(64)
            fcntl.ioctl(fd, self.JSIOCGAXMAP, am)
        except OSError:
            os.close(fd)
            return None
        buttons = dict(enumerate(struct.unpack('<512H', bm)[:nb]))
        if self.BTN_SOUTH not in buttons.values():
            os.close(fd)
            return None
        try:
            vendor = open('/sys/class/input/%s/device/id/vendor' % os.path.basename(path)).read().strip()
        except OSError:
            vendor = ''
        return {'fd': fd, 'buttons': buttons, 'axes': dict(enumerate(am[:na])), 'val': {}, 'dpad': set(),
                'steam': vendor == '28de'}

    def _rescan(self):
        for path in sorted(glob.glob('/dev/input/js*')):
            if path not in self.pads:
                p = self._open(path)
                if p:
                    self.pads[path] = p
        if any(p['steam'] for p in self.pads.values()):
            for path in [k for k, p in self.pads.items() if not p['steam']]:
                os.close(self.pads.pop(path)['fd'])

    def close(self):
        for p in self.pads.values():
            os.close(p['fd'])
        self.pads.clear()

    def _direction(self):
        for p in self.pads.values():
            if p['dpad']:
                return next(iter(p['dpad']))
            v = p['val']
            for x, y, t in ((v.get(self.ABS_HAT0X, 0), v.get(self.ABS_HAT0Y, 0), self.HAT),
                            (v.get(self.ABS_X, 0), v.get(self.ABS_Y, 0), self.STICK)):
                if abs(y) >= t and abs(y) >= abs(x):
                    return 'up' if y < 0 else 'down'
                if abs(x) >= t:
                    return 'left' if x < 0 else 'right'
        return None

    def poll(self):
        if fcntl is None:
            return []
        now = time.monotonic()
        if now >= self.rescan_at:
            self._rescan()
            self.rescan_at = now + 2.0
        out = []
        for path, p in list(self.pads.items()):
            while True:
                try:
                    data = os.read(p['fd'], 8 * 64)
                except OSError as e:
                    if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):   # unplugged
                        os.close(p['fd'])
                        del self.pads[path]
                    break
                if not data:
                    break
                for off in range(0, len(data) - 7, 8):
                    _, value, kind, number = struct.unpack_from('<IhBB', data, off)
                    if kind & self.EV_AXIS:
                        code = p['axes'].get(number)
                        if code is not None:
                            p['val'][code] = value      # an init event: where the axis rests
                    elif kind & self.EV_BUTTON:
                        code = p['buttons'].get(number)
                        if code in self.BTN_DPAD:
                            (p['dpad'].add if value else p['dpad'].discard)(self.BTN_DPAD[code])
                        elif value == 1 and not kind & self.EV_INIT:
                            if code == self.BTN_SOUTH:
                                out.append('a')
                            elif code == self.BTN_EAST:
                                out.append('b')
                            elif code == self.BTN_START:
                                out.append('start')
        d = self._direction()
        if d != self.held:
            self.held = d
            if d:
                out.append(d)
                self.repeat_at = now + self.REPEAT_FIRST
        elif d and now >= self.repeat_at:
            out.append(d)
            self.repeat_at = now + self.REPEAT_NEXT
        return out

    def reset(self):
        """Forget what is held (after the game ran: the presses made in it are not the window's)."""
        self.held = None
        for p in self.pads.values():
            p['val'].clear()
            p['dpad'].clear()


def main_window(steam=False):
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print('The launcher needs Tk for Python (tkinter). Debian / Ubuntu: sudo apt install python3-tk; '
              'Fedora: sudo dnf install python3-tkinter; Arch: sudo pacman -S tk.\n'
              'Without it, linux/native/play.sh starts the game and linux/native/build.sh builds it.')
        return 1

    conf = load_conf()
    root = tk.Tk()
    root.title("Demon's Souls - native Linux launcher")
    root.minsize(560, 0)
    style = ttk.Style(root)
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    style.configure('Horizontal.TProgressbar', background='#3584e4')   # clam's own fill is light grey
    # The item a controller (or Tab) is on, plain to see from arm's length: clam's dotted focus ring is not.
    focus_bg = '#bcd4f6'
    for st, opt in (('TButton', 'background'), ('TMenubutton', 'background'), ('TCheckbutton', 'background'),
                    ('TRadiobutton', 'background'), ('TCombobox', 'fieldbackground'), ('TEntry', 'fieldbackground')):
        # 'user1': the item the controller is on, which may not have the keyboard focus (below)
        style.map(st, **{opt: [('focus', focus_bg), ('user1', focus_bg)] + [tuple(x) for x in (style.map(st, opt) or [])]})
    # clam draws a focused read-only combobox's value white (on its dark blue): dark on the light blue here
    style.map('TCombobox', foreground=[('focus', 'black'), ('user1', 'black')] +
              [tuple(x) for x in (style.map('TCombobox', 'foreground') or [])])

    state = {'proc': None, 'kind': None}

    # --- banner: the game's own ICON0.PNG, when the game files are there ------------------------------
    top = ttk.Frame(root, padding=(12, 12, 12, 0))
    top.pack(fill='x')
    icon_path = os.path.join(ROOT, 'game', 'PS3_GAME', 'ICON0.PNG')
    banner = None
    if os.path.isfile(icon_path):
        try:
            banner = tk.PhotoImage(file=icon_path)
            root.iconphoto(True, banner)
            if root.winfo_screenheight() < 1000:   # a Steam Deck: room for the log and the progress
                banner = banner.subsample(2)
            ttk.Label(top, image=banner).pack(side='left')
        except tk.TclError:
            banner = None
    title = ttk.Frame(top, padding=(12 if banner else 0, 0, 0, 0))
    title.pack(side='left', fill='x', expand=True)
    ttk.Label(title, text="Demon's Souls", font=('TkDefaultFont', 16, 'bold')).pack(anchor='w')
    ttk.Label(title, text='Native Linux build (Vulkan)' + (' - Steam Deck' if DECK else '')).pack(anchor='w')
    status = tk.StringVar()
    ttk.Label(title, textvariable=status, foreground='#555').pack(anchor='w', pady=(4, 0))

    # --- settings ----------------------------------------------------------------------------------------
    body = ttk.Frame(root, padding=12)
    body.pack(fill='both', expand=True)
    opts = ttk.LabelFrame(body, text='Settings', padding=10)
    opts.pack(fill='x')
    v = {
        'fps': tk.StringVar(value=conf['fps']),
        'game': tk.StringVar(value=conf['game']),
        'br_souls': tk.StringVar(value=conf['br_souls']),
        'name': tk.StringVar(value=conf['name']),
        'fullscreen': tk.BooleanVar(value=conf['fullscreen']),
        'movies': tk.BooleanVar(value=conf['movies']),
        'async_shaders': tk.BooleanVar(value=conf['async_shaders']),
        'skip_intro': tk.BooleanVar(value=conf['skip_intro']),
        'omniroll': tk.BooleanVar(value=conf['omniroll']),
        'god': tk.BooleanVar(value=conf['god']),
        'gpu_clock': tk.StringVar(value=conf['gpu_clock']),
        'lto': tk.BooleanVar(value=conf['lto']),
        'language': tk.StringVar(value=conf['language']),
    }
    row = 0
    ttk.Label(opts, text='Frame rate').grid(row=row, column=0, sticky='w', pady=2)
    fr = ttk.Frame(opts)
    fr.grid(row=row, column=1, sticky='w')
    for val, txt in (('60', '60 fps'), ('30', '30 fps (the console\'s)'), ('unlimited', 'Unlimited')):
        ttk.Radiobutton(fr, text=txt, value=val, variable=v['fps']).pack(side='left', padx=(0, 10))
    row += 1
    ttk.Label(opts, text='Game').grid(row=row, column=0, sticky='w', pady=2)
    gr = ttk.Frame(opts)
    gr.grid(row=row, column=1, sticky='w')
    for val, txt in (('game', 'Normal'), ('game_remaster', 'PC Remaster'), ('bossrush', 'Boss rush')):
        ttk.Radiobutton(gr, text=txt, value=val, variable=v['game']).pack(side='left', padx=(0, 10))
    row += 1
    # Language (NOTES fix 162): the choices translations.py lists for the game folder Play uses. The setting keeps
    # the id; the box shows the labels. Choices this disc does not have are left out and named on the right.
    ttk.Label(opts, text='Language').grid(row=row, column=0, sticky='w', pady=2)
    lr = ttk.Frame(opts)
    lr.grid(row=row, column=1, sticky='w')
    lang_label = tk.StringVar()
    lang_box = ttk.Combobox(lr, textvariable=lang_label, width=22, state='readonly')
    lang_box.pack(side='left')
    lang_hint = ttk.Label(lr, foreground='#555')
    lang_hint.pack(side='left', padx=(8, 0))
    lang = {'game': None, 'data': None, 'why': None}

    def lang_show():
        data = lang['data']
        shown = [ch for ch in (data or {'choices': [ENGLISH]})['choices'] if ch.get('available')]
        lang_box.configure(values=[ch['label'] for ch in shown])
        ch = lang_choice(data, v['language'].get())
        lang_label.set(ch['label'])
        hint = [ch['note']] if ch['note'] else []
        hint += ['%s: %s' % (x['label'], x['note']) for x in (data or {}).get('choices', []) if not x.get('available')]
        lang_hint.configure(text='; '.join(hint))

    def lang_picked(_e=None):
        data = lang['data']
        for ch in (data or {'choices': [ENGLISH]})['choices']:
            if ch['label'] == lang_label.get() and ch.get('available'):
                v['language'].set(ch['id'])
        lang_show()
    lang_box.bind('<<ComboboxSelected>>', lang_picked)

    def lang_load(*_):
        """Lists the choices for the game folder Play uses, off the Tk thread (it runs a Python)."""
        game = lang_game({'game': v['game'].get()})

        def work():
            data, why = lang_list(game)
            root.after(0, got, data, why)

        def got(data, why):
            if game != lang_game({'game': v['game'].get()}):
                return      # the Game choice changed meanwhile: its own listing follows
            changed = why != lang['why']
            lang.update(game=game, data=data, why=why)
            lang_show()
            if changed and not busy():
                refresh()   # only for the reason in the status line: a failed apply's message stays there
        threading.Thread(target=work, daemon=True).start()
    v['game'].trace_add('write', lang_load)
    row += 1
    ttk.Label(opts, text='Boss rush souls').grid(row=row, column=0, sticky='w', pady=2)
    ttk.Combobox(opts, textvariable=v['br_souls'], values=('1', '2', '3', '5', '10'), width=5,
                 state='readonly').grid(row=row, column=1, sticky='w')
    row += 1
    ttk.Label(opts, text='Character name').grid(row=row, column=0, sticky='w', pady=2)
    ttk.Entry(opts, textvariable=v['name'], width=24).grid(row=row, column=1, sticky='w')
    row += 1
    for key, txt in (('fullscreen', 'Start in fullscreen (F11 or Alt+Enter switches in the game)'),
                     ('movies', 'Play movies'),
                     ('async_shaders', 'Compile new shaders in the background (brief pop-in instead of a stutter)'),
                     ('skip_intro', 'Skip the intro (straight to PRESS START)'),
                     ('omniroll', 'Locked-on rolls follow the stick (the OmniRoll mod by hamzafallahi)'),
                     ('god', 'God mode at start')):
        ttk.Checkbutton(opts, text=txt, variable=v[key]).grid(row=row, column=0, columnspan=2, sticky='w')
        row += 1
    if DECK:
        ttk.Label(opts, text='GPU clock (MHz)').grid(row=row, column=0, sticky='w', pady=2)
        ttk.Combobox(opts, textvariable=v['gpu_clock'], values=('800', '1100', '1600', 'auto'), width=6,
                     state='readonly').grid(row=row, column=1, sticky='w')
        row += 1
    opts.columnconfigure(1, weight=1)

    def current():
        c = dict(conf)
        for k, var in v.items():
            c[k] = var.get()
        return c

    def remember(*_):
        conf.update(current())
        save_conf(conf)
    for var in v.values():
        var.trace_add('write', remember)

    # --- rebuild / update (the first install is linux/native/installer.py) ----------------------------------
    inst = ttk.LabelFrame(body, text='Rebuild and update', padding=10)
    inst.pack(fill='x', pady=(10, 0))
    ttk.Checkbutton(inst, text='Whole-program optimization (ThinLTO: a few % faster, a longer build)',
                    variable=v['lto']).grid(row=3, column=0, columnspan=4, sticky='w')
    inst.columnconfigure(1, weight=1)

    prog = tk.StringVar(value='')
    bar = ttk.Progressbar(inst, maximum=len(STEPS) + 1, mode='determinate')
    bar.grid(row=4, column=0, columnspan=4, sticky='we', pady=(8, 0))
    ttk.Label(inst, textvariable=prog).grid(row=5, column=0, columnspan=4, sticky='w')

    logbox = tk.Text(body, height=5, wrap='none', font=('TkFixedFont', 9), takefocus=0)
    logbox.pack(fill='both', expand=True, pady=(10, 0))
    logbox.configure(state='disabled')

    def log(text):
        logbox.configure(state='normal')
        logbox.insert('end', text)
        logbox.see('end')
        if int(logbox.index('end-1c').split('.')[0]) > 4000:
            logbox.delete('1.0', '1000.0')
        logbox.configure(state='disabled')

    # --- buttons -----------------------------------------------------------------------------------------
    btns = ttk.Frame(root, padding=(12, 0, 12, 12))
    btns.pack(side='bottom', fill='x', before=body)
    b_play = ttk.Button(btns, text='Play')
    b_play.pack(side='left')
    b_build = ttk.Button(btns, text='Rebuild')
    b_build.pack(side='left', padx=6)
    b_update = ttk.Button(btns, text='Update')
    b_update.pack(side='left')
    b_stop = ttk.Button(btns, text='Stop')
    b_stop.pack(side='left', padx=6)
    b_quit = ttk.Button(btns, text='Quit')
    b_quit.pack(side='right')
    more = ttk.Menubutton(btns, text='More')
    more.pack(side='right', padx=6)
    menu = tk.Menu(more, tearoff=0)
    more['menu'] = menu

    def busy():
        return state['proc'] is not None and state['proc'].poll() is None

    def refresh():
        built = os.access(EXE, os.X_OK) and os.path.isfile(ELF)
        running = busy()
        b_play.configure(state='disabled' if running else 'normal', text='Play' if built else 'Install...')
        b_build.configure(state='disabled' if running or not os.path.isfile(ELF) else 'normal')
        b_update.configure(state='disabled' if running or not os.path.isdir(os.path.join(ROOT, '.git')) else 'normal')
        b_stop.configure(state='normal' if running else 'disabled')
        if not running:
            if built:
                status.set('Ready to play.')
            elif os.path.isfile(ELF):
                status.set('The game files are there, the compile is not: Rebuild finishes it.')
            else:
                status.set('Not installed yet: Install... opens the installer.')
            if lang['why']:
                status.set(status.get() + ' ' + lang['why'])

    def run(kind, argv, env, on_line=None, on_done=None):
        os.makedirs(LOGS, exist_ok=True)
        log('\n$ ' + ' '.join(shlex.quote(a) for a in argv) + '\n')
        p = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding='utf-8', errors='replace',   # language labels are not ASCII
                             bufsize=1, start_new_session=True)
        state['proc'], state['kind'] = p, kind
        refresh()

        def reader():
            sink = open(BUILD_LOG, 'a') if kind == 'build' else None
            for line in p.stdout:
                if sink:
                    sink.write(line)
                    sink.flush()
                root.after(0, log, line)
                if on_line:
                    root.after(0, on_line, line)
            code = p.wait()
            if sink:
                sink.close()
            root.after(0, finished, code)

        def finished(code):
            state['proc'] = None
            refresh()
            if on_done:
                on_done(code)
        threading.Thread(target=reader, daemon=True).start()

    def open_installer():
        subprocess.Popen([sys.executable or 'python3', os.path.join(HERE, 'installer.py')], cwd=ROOT,
                         start_new_session=True)
        root.destroy()

    def do_play():
        remember()
        if busy():
            return
        if not os.access(EXE, os.X_OK):
            return open_installer()
        c = current()
        game = lang_game(c)
        if lang['game'] != game:    # not listed yet for this folder (rare: the listing runs at start)
            data, why = lang_list(game)
            lang.update(game=game, data=data, why=why)
            lang_show()
        ch = lang_choice(lang['data'], c['language'])
        if lang_needs_apply(lang['data'], ch):
            # Install (or remove) the translation first, in the log, and play only when it worked (NOTES fix 162).
            status.set('Setting the language to %s...' % ch['label'])
            last = {'line': ''}

            def lang_line(line):
                if line.strip():
                    last['line'] = line.strip()
                    status.set(last['line'])

            def lang_done(code):
                lang_load()     # what is installed now
                if code == 0:
                    start(c, ch)
                else:
                    if not last['line']:
                        last['line'] = 'stopped (exit code %d)' % code   # Stop, or no reason printed
                    status.set('The language could not be set: ' + last['line'])
                    messagebox.showerror('Demon\'s Souls', 'The language could not be set, so the game was not '
                                         'started:\n\n%s\n\n(The log below has the details.)' % last['line'])
            run('lang', lang_apply_argv(ch, game), dict(os.environ), on_line=lang_line, on_done=lang_done)
            return
        start(c, ch)

    def start(c, ch):
        status.set('Playing. The logos and the first load take about a minute.')

        def done(code):
            pads.reset()
            if code not in (0, -signal.SIGTERM, 130, 143):
                if messagebox.askyesno('Demon\'s Souls',
                                       'Demon\'s Souls stopped with an error (exit code %d).\n\n'
                                       'Open the logs folder?' % code):
                    open_path(LOGS)
            elif steam:
                root.destroy()      # from Steam: the game ended, so does the "game" Steam started
        run('play', ['bash', PLAY], play_env(c, ch['env']), on_done=done)

    def build_line(line):
        if line.startswith('==> '):
            step = line[4:].split(' ', 1)[0].strip()
            if step in STEPS:
                bar['value'] = STEPS.index(step) + 1
                prog.set(line[4:].strip())
            elif step == 'done':
                bar['value'] = len(STEPS) + 1
                prog.set('Done.')
        elif line.startswith('ERROR: '):
            prog.set(line.strip())

    def do_build(steps=None, after=None):
        remember()
        if busy():
            return
        if not os.path.isfile(ELF):
            return open_installer()
        env = dict(os.environ)
        env['DES_LTO'] = '1' if v['lto'].get() else '0'
        bar['value'] = 0
        prog.set('Starting...')
        status.set('Building. The first build takes a long while (an hour or more on a Steam Deck).')
        with open(BUILD_LOG, 'w'):
            pass

        def done(code):
            if code == 0:
                prog.set('Done.')
                if after:
                    after()
            else:
                messagebox.showerror('Demon\'s Souls', 'The build stopped (exit code %d). The last lines of the log '
                                     'say why; the whole log is %s.' % (code, BUILD_LOG))
        run('build', ['bash', BUILD] + (steps or []), env, on_line=build_line, on_done=done)

    def do_update():
        if busy():
            return
        if messagebox.askyesno('Demon\'s Souls', 'Update: git pull this checkout, then rebuild what changed?'):
            prog.set('Updating the checkout...')
            run('build', ['git', 'pull', '--ff-only'], dict(os.environ),
                on_done=lambda code: do_build(['toolkit', 'lift', 'build']) if code == 0 else
                messagebox.showerror('Demon\'s Souls', 'git pull failed (see the log above).'))

    def do_stop():
        p = state['proc']
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
            if state['kind'] == 'play':
                # the game itself may run inside a distrobox container, outside this process group
                subprocess.call(['pkill', '-TERM', '-f', '^' + EXE + ' '])

    def open_path(p):
        os.makedirs(p, exist_ok=True)
        subprocess.Popen(['xdg-open', p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def add_menu_entry():
        apps = os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'applications')
        os.makedirs(apps, exist_ok=True)
        art_icon = os.path.join(ROOT, 'port', 'steam_art', 'icon.png')
        icon = art_icon if os.path.isfile(art_icon) else icon_path if os.path.isfile(icon_path) else 'applications-games'
        py = sys.executable or 'python3'
        entries = {
            'demons-souls-native.desktop': ("Demon's Souls (native)", '%s %s' % (shlex.quote(py), shlex.quote(__file__))),
            'demons-souls-native-play.desktop': ("Demon's Souls (native) - play", '%s %s --play' % (
                shlex.quote(py), shlex.quote(__file__))),
        }
        for fname, (name, cmd) in entries.items():
            with open(os.path.join(apps, fname), 'w') as f:
                f.write('[Desktop Entry]\nType=Application\nName=%s\nExec=%s\nIcon=%s\nTerminal=false\n'
                        'Categories=Game;\nPath=%s\n' % (name, cmd, icon, ROOT))
        messagebox.showinfo('Demon\'s Souls', 'Added "Demon\'s Souls (native)" (this window) and "... - play" (straight '
                            'into the game) to your applications menu.')

    def add_to_steam():
        if busy():
            return
        if subprocess.run(['pgrep', '-x', 'steam'], stdout=subprocess.DEVNULL).returncode == 0 and \
                not messagebox.askyesno('Demon\'s Souls', 'Steam has to close for a moment to add the game (it '
                                        'rewrites its list of games when it exits), then it opens again. Go on?'):
            return
        status.set('Adding Demon\'s Souls to Steam, with its artwork...')

        def done(code):
            if code == 0:
                status.set('In your Steam library as "Demon\'s Souls", with artwork from your disc.')
            else:
                messagebox.showerror('Demon\'s Souls', 'Adding it to Steam failed (exit code %d; the log below '
                                     'says why).' % code)
        run('steam', [sys.executable or 'python3', os.path.join(HERE, 'steam.py'), 'add', '--restart-steam'],
            dict(os.environ), on_done=done)

    menu.add_command(label='Saves folder', command=lambda: open_path(os.path.join(ROOT, 'gamedata')))
    menu.add_command(label='Logs folder', command=lambda: open_path(LOGS))
    menu.add_command(label='Keyboard and mouse keys (input.toml)',
                     command=lambda: open_path(os.path.join(HERE, 'input.toml')))
    menu.add_separator()
    menu.add_command(label='Add to Steam (with artwork from your disc)', command=add_to_steam)
    menu.add_command(label='Add to the applications menu', command=add_menu_entry)

    b_play.configure(command=do_play)
    b_build.configure(command=do_build)
    b_update.configure(command=do_update)
    b_stop.configure(command=do_stop)

    def on_close():
        if busy() and state['kind'] in ('build', 'lang'):
            what = 'A build is running' if state['kind'] == 'build' else 'The language is being installed'
            if not messagebox.askyesno('Demon\'s Souls', what + '. Stop it and quit?'):
                return
            do_stop()
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', on_close)
    b_quit.configure(command=on_close)

    # --- controller and arrow keys ---------------------------------------------------------------------
    pads = Gamepads()
    menu_open = {'on': False}

    def steam_running():
        return subprocess.run(['pgrep', '-x', 'steam'], stdout=subprocess.DEVNULL).returncode == 0

    T = root.tk.call     # by Tcl path: a question's buttons (tk_messageBox) have no Python widget

    def enabled(path):
        try:
            if T('winfo', 'class', path).startswith('T'):
                return not root.tk.getboolean(T(path, 'instate', 'disabled'))
            return str(T(path, 'cget', '-state')) != 'disabled'
        except tk.TclError:
            return True

    def move_focus(path, forward):
        n = str(T('tk_focusNext' if forward else 'tk_focusPrev', path))
        if n:
            T('focus', n)

    def change(path, step):
        """Left / right: the next or previous choice of the item selected."""
        cls = str(T('winfo', 'class', path))
        if cls in ('TRadiobutton', 'Radiobutton'):
            sibs = [str(c) for c in T('winfo', 'children', T('winfo', 'parent', path))
                    if str(T('winfo', 'class', c)) == cls and enabled(c)]
            if path in sibs and len(sibs) > 1:
                n = sibs[(sibs.index(path) + step) % len(sibs)]
                T('focus', n)
                T(n, 'invoke')
        elif cls == 'TCombobox':
            vals = [str(x) for x in root.tk.splitlist(T(path, 'cget', '-values'))]
            if vals:
                cur = str(T(path, 'get'))
                i = vals.index(cur) if cur in vals else -step
                T(path, 'set', vals[(i + step) % len(vals)])
                T('event', 'generate', path, '<<ComboboxSelected>>')
        else:
            move_focus(path, step > 0)      # buttons in a row, and the yes / no of a question

    def open_more():
        more.update_idletasks()
        # as a ttk menubutton posts it: with Tk's grab, so Escape and a click elsewhere close it too
        T('tk_popup', str(menu), more.winfo_rootx(), more.winfo_rooty() + more.winfo_height())
        menu.activate(0)
        menu_open['on'] = True
    menu.bind('<Unmap>', lambda _e: menu_open.update(on=False))   # closed by the mouse, or by Escape

    def menu_action(act):
        last = menu.index('end')
        cur = menu.index('active')
        if act in ('up', 'down'):
            step = 1 if act == 'down' else -1
            i = cur if cur is not None else (-1 if step > 0 else last + 1)
            for _ in range(last + 1):
                i = (i + step) % (last + 1)
                if menu.type(i) != 'separator':
                    break
            menu.activate(i)
        elif act in ('a', 'b', 'start'):
            T('tk::MenuUnpost', str(menu))      # releases tk_popup's grab and gives the focus back
            menu_open['on'] = False
            if act == 'a' and cur is not None:  # nothing highlighted (the mouse left it): nothing to run
                menu.invoke(cur)

    # Started by Steam, the window often does not get the keyboard focus (the desktop keeps it with Steam's
    # window), and in desktop mode Steam turns the Deck's controls from mouse into the game's pad while the
    # launcher runs. So from Steam the pad works the item Tk remembers as focused in the window (or in the
    # question on top: it holds a grab), keyboard focus or not, and 'user1' shows which one it is.
    padlog = None
    if steam or os.environ.get('DES_LAUNCHER_DEBUG') == '1':
        try:
            os.makedirs(LOGS, exist_ok=True)
            padlog = open(os.path.join(LOGS, 'launcher.txt'), 'w')
        except OSError:
            padlog = None

    def note(msg):
        if padlog:
            padlog.write('%.3f %s\n' % (time.monotonic(), msg))
            padlog.flush()
    note('env: ' + ' '.join('%s=%s' % (k, os.environ.get(k, '-')) for k in
                            ('SteamGameId', 'SteamAppId', 'SteamOverlayGameId', 'SDL_VIDEODRIVER',
                             'SDL_GAMECONTROLLER_IGNORE_DEVICES', 'XDG_SESSION_TYPE', 'SDL_AUDIODRIVER',
                             'PULSE_SERVER', 'PULSE_LATENCY_MSEC', 'PIPEWIRE_LATENCY', 'LD_PRELOAD')))
    cursor = {'path': ''}

    def mark(path):
        """The 'user1' highlight on path, off the item it was on."""
        old = cursor['path']
        if old and old != path:
            try:
                if T('winfo', 'exists', old) and str(T('winfo', 'class', old)).startswith('T'):
                    T(old, 'state', '!user1')
            except tk.TclError:
                pass
        cursor['path'] = path
        try:
            if path and str(T('winfo', 'class', path)).startswith('T'):
                T(path, 'state', 'user1')
        except tk.TclError:
            pass
    root.bind_all('<FocusIn>', lambda e: mark(str(e.widget)), add='+')

    def target():
        """The item an action is for: the keyboard focus, or (from Steam) the one Tk keeps for the window."""
        path = str(T('focus'))
        if path or not steam:
            return path     # nothing focused outside Steam: another program has the keyboard, and the pad
        grab = str(T('grab', 'current'))
        return str(T('focus', '-lastfor', grab if grab and grab != '.' else '.'))

    def nav(act, src='pad'):
        """One controller (or arrow key) action on the item that has the focus."""
        if menu_open['on']:
            note('%s %s in the More menu' % (src, act))
            return menu_action(act)
        path = target()
        note('%s %s on %s' % (src, act, path or '(no focus: ignored)'))
        if not path or path == '.':
            if not steam:
                return
            path = str(b_play)
            T('focus', path)
        cls = str(T('winfo', 'class', path))
        dialog = str(T('winfo', 'toplevel', path)) != '.'
        if act == 'start':
            if not dialog:
                do_play()
        elif act in ('up', 'down'):
            move_focus(path, act == 'down')
        elif act in ('left', 'right'):
            change(path, 1 if act == 'right' else -1)
        elif act == 'b':
            if dialog:
                T('event', 'generate', path, '<Escape>')
        elif act == 'a':
            if path == str(more):
                open_more()
            elif cls in ('TButton', 'Button', 'TCheckbutton', 'Checkbutton', 'TRadiobutton', 'Radiobutton'):
                if enabled(path):
                    T(path, 'invoke')
            elif cls == 'TCombobox':
                change(path, 1)
            elif cls in ('TEntry', 'Entry') and steam_running():
                # the character name: Steam's on-screen keyboard types into the window that has the focus
                subprocess.Popen(['xdg-open', 'steam://open/keyboard'], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        mark(target())      # where the action left the focus (a question it opened has been answered by now)

    def safe_nav(a):
        try:
            nav(a)
        except tk.TclError:
            pass    # a widget went away between the press and the action

    seen = {'pads': None}

    def pad_tick():
        # The next poll is queued first and each action runs as its own event: an action that opens a question
        # (tk_messageBox waits in a nested event loop) must not stop the polling the question is answered with.
        root.after(16, pad_tick)
        acts = pads.poll()
        if sorted(pads.pads) != seen['pads']:
            seen['pads'] = sorted(pads.pads)
            note('pads: %s' % (', '.join('%s%s' % (k, ' (Steam)' if v['steam'] else '') for k, v in
                                          sorted(pads.pads.items())) or 'none'))
        # Read all the while, act only when the game is not running: what is pressed in the game is the game's.
        if acts and not (busy() and state['kind'] == 'play'):
            for a in acts:
                root.after_idle(safe_nav, a)

    def key(act):
        def handler(_e):
            nav(act, 'key')
            return 'break'
        return handler
    # Up / Down move between items everywhere (a read-only combobox would open its list on Down); Left / Right
    # change the choice where there is one, and stay the cursor keys in the name field; Return presses.
    for cls in ('TButton', 'TCheckbutton', 'TRadiobutton', 'TCombobox', 'TMenubutton', 'TEntry', 'Button'):
        root.bind_class(cls, '<Up>', key('up'))
        root.bind_class(cls, '<Down>', key('down'))
    for cls in ('TButton', 'TCheckbutton', 'TRadiobutton', 'TCombobox', 'TMenubutton', 'Button'):
        root.bind_class(cls, '<Left>', key('left'))
        root.bind_class(cls, '<Right>', key('right'))
        root.bind_class(cls, '<Return>', key('a'))
        root.bind_class(cls, '<KP_Enter>', key('a'))

    refresh()
    lang_show()
    lang_load()
    # Fit the screen (a Steam Deck is 800 px tall): the log is what gives way.
    root.update_idletasks()
    h = min(root.winfo_reqheight(), root.winfo_screenheight() - 60)
    root.geometry('%dx%d' % (max(root.winfo_reqwidth(), 560), h))
    b_play.focus_set()
    mark(str(b_play))
    if steam:
        root.after(200, b_play.focus_force)    # the window's X focus, and Play keeps Tk's
    root.after(100, pad_tick)
    try:
        root.mainloop()
    finally:
        pads.close()
    return 0


def main():
    if '--play' in sys.argv[1:]:
        return play_now(load_conf())
    return main_window(steam='--steam' in sys.argv[1:])


if __name__ == '__main__':
    sys.exit(main())
