#!/usr/bin/env python3
"""Demon's Souls launcher for the native Linux build (linux/native/build.sh, linux/native/play.sh).

One window for the play options, as DemonsSoulsLauncher.exe is on Windows and the launcher app on the Mac:
it keeps the choices in ~/.config/demons-souls-recomp/linux-launcher.json, sets the environment variables
linux/native/play.sh reads (DES_FPS, DES_GAME, DES_FULLSCREEN, ...) and runs it, so the window and play.sh
on its own always start the game the same way. It also installs and rebuilds the game from your disc image
(linux/native/build.sh, its "==> step" lines drive the progress line), updates the checkout (git pull, then
the build), and adds itself to the applications menu (where Steam's "Add a Non-Steam Game" finds it).

    python3 linux/native/launcher.py          the window
    python3 linux/native/launcher.py --play   starts the game with the saved settings (for a shortcut)

Python 3.8+ with Tk (tkinter), nothing else: SteamOS has it; Debian / Ubuntu: sudo apt install python3-tk;
Fedora: sudo dnf install python3-tkinter; Arch: sudo pacman -S tk.
"""
import json
import os
import shlex
import signal
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PLAY = os.path.join(HERE, 'play.sh')
BUILD = os.path.join(HERE, 'build.sh')
EXE = os.path.join(ROOT, 'port', 'build_linux', 'DemonsSoulsRecomp')
ELF = os.path.join(ROOT, 'game', 'PS3_GAME', 'USRDIR', 'EBOOT.elf')
CONF_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'demons-souls-recomp')
CONF = os.path.join(CONF_DIR, 'linux-launcher.json')
LOGS = os.path.join(ROOT, 'logs')
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
    'skip_intro': False,
    'god': False,
    'gpu_clock': '800',        # Steam Deck: MHz or auto
    'iso': '',
    'key': '',
    'lto': False,
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


def play_env(c):
    """The environment play.sh gets for these settings (the launcher's own process environment plus these)."""
    e = dict(os.environ)
    e['DES_FPS'] = c['fps']
    e['DES_NAME'] = c['name'] or 'Slayer'
    e['DES_FULLSCREEN'] = '1' if c['fullscreen'] else '0'
    e['DES_MOVIES'] = '1' if c['movies'] else '0'
    for k in ('DES_GAME', 'DES_BOSS_RUSH', 'DES_BR_SOULS', 'DES_SKIP_INTRO', 'DES_GOD'):
        e.pop(k, None)
    if c['game'] == 'bossrush':
        e['DES_BOSS_RUSH'] = '1'
        if c['br_souls'] != '1':
            e['DES_BR_SOULS'] = c['br_souls']
    elif c['game'] != 'game':
        e['DES_GAME'] = c['game']
    if c['skip_intro']:
        e['DES_SKIP_INTRO'] = '1'
    if c['god']:
        e['DES_GOD'] = '1'
    if DECK:
        e['DES_GPU_CLOCK'] = c['gpu_clock'] or '800'
    return e


def play_now(c):
    """--play: start the game with the saved settings, no window."""
    if not os.access(EXE, os.X_OK):
        print('The native build is not there yet: open the launcher and choose Install.')
        return 1
    return subprocess.call(['bash', PLAY], cwd=ROOT, env=play_env(c))


def main_window():
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
        'skip_intro': tk.BooleanVar(value=conf['skip_intro']),
        'god': tk.BooleanVar(value=conf['god']),
        'gpu_clock': tk.StringVar(value=conf['gpu_clock']),
        'lto': tk.BooleanVar(value=conf['lto']),
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
    ttk.Label(opts, text='Boss rush souls').grid(row=row, column=0, sticky='w', pady=2)
    ttk.Combobox(opts, textvariable=v['br_souls'], values=('1', '2', '3', '5', '10'), width=5,
                 state='readonly').grid(row=row, column=1, sticky='w')
    row += 1
    ttk.Label(opts, text='Character name').grid(row=row, column=0, sticky='w', pady=2)
    ttk.Entry(opts, textvariable=v['name'], width=24).grid(row=row, column=1, sticky='w')
    row += 1
    for key, txt in (('fullscreen', 'Start in fullscreen (F11 or Alt+Enter switches in the game)'),
                     ('movies', 'Play movies'),
                     ('skip_intro', 'Skip the intro (straight to PRESS START)'),
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

    # --- install / build ---------------------------------------------------------------------------------
    inst = ttk.LabelFrame(body, text='Install and update', padding=10)
    inst.pack(fill='x', pady=(10, 0))
    iso = tk.StringVar(value=conf['iso'])
    key = tk.StringVar(value=conf['key'])
    ttk.Label(inst, text='Disc image').grid(row=0, column=0, sticky='w')
    ttk.Entry(inst, textvariable=iso, width=40).grid(row=0, column=1, sticky='we', padx=4)

    def pick_iso():
        p = filedialog.askopenfilename(title='Your Demon\'s Souls disc image (BLUS-30443)',
                                       filetypes=[('Disc images', '*.iso *.zip'), ('All files', '*')])
        if p:
            iso.set(p)
    ttk.Button(inst, text='Browse...', command=pick_iso).grid(row=0, column=2)

    def pick_dir():
        p = filedialog.askdirectory(title='A dumped disc folder (it holds PS3_GAME)')
        if p:
            iso.set(p)
    ttk.Button(inst, text='Folder...', command=pick_dir).grid(row=0, column=3, padx=(4, 0))
    ttk.Label(inst, text='Disc key').grid(row=1, column=0, sticky='w')
    ttk.Entry(inst, textvariable=key, width=40).grid(row=1, column=1, sticky='we', padx=4)
    ttk.Label(inst, text='only for an encrypted (Redump) image; a .dkey next to it is found on its own',
              foreground='#666').grid(row=2, column=1, columnspan=3, sticky='w', padx=4)
    ttk.Checkbutton(inst, text='Whole-program optimization (ThinLTO: a few % faster, a longer build)',
                    variable=v['lto']).grid(row=3, column=0, columnspan=4, sticky='w', pady=(4, 0))
    inst.columnconfigure(1, weight=1)
    for var, k in ((iso, 'iso'), (key, 'key')):
        var.trace_add('write', lambda *_a, var=var, k=k: (conf.__setitem__(k, var.get()), save_conf(conf)))

    prog = tk.StringVar(value='')
    bar = ttk.Progressbar(inst, maximum=len(STEPS) + 1, mode='determinate')
    bar.grid(row=4, column=0, columnspan=4, sticky='we', pady=(8, 0))
    ttk.Label(inst, textvariable=prog).grid(row=5, column=0, columnspan=4, sticky='w')

    logbox = tk.Text(body, height=5, wrap='none', font=('TkFixedFont', 9))
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
    b_build = ttk.Button(btns, text='Install / Rebuild')
    b_build.pack(side='left', padx=6)
    b_update = ttk.Button(btns, text='Update')
    b_update.pack(side='left')
    b_stop = ttk.Button(btns, text='Stop')
    b_stop.pack(side='left', padx=6)
    more = ttk.Menubutton(btns, text='More')
    more.pack(side='right')
    menu = tk.Menu(more, tearoff=0)
    more['menu'] = menu

    def busy():
        return state['proc'] is not None and state['proc'].poll() is None

    def refresh():
        built = os.access(EXE, os.X_OK) and os.path.isfile(ELF)
        running = busy()
        b_play.configure(state='disabled' if running or not built else 'normal')
        b_build.configure(state='disabled' if running else 'normal')
        b_update.configure(state='disabled' if running or not os.path.isdir(os.path.join(ROOT, '.git')) else 'normal')
        b_stop.configure(state='normal' if running else 'disabled')
        if not running:
            if built:
                status.set('Ready to play.')
            elif os.path.isfile(ELF):
                status.set('The game files are there; Install / Rebuild compiles the game.')
            else:
                status.set('Not installed yet: choose your disc image, then Install / Rebuild.')

    def run(kind, argv, env, on_line=None, on_done=None):
        os.makedirs(LOGS, exist_ok=True)
        log('\n$ ' + ' '.join(shlex.quote(a) for a in argv) + '\n')
        p = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1, start_new_session=True)
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

    def do_play():
        remember()
        if busy():
            return
        status.set('Playing. The logos and the first load take about a minute.')

        def done(code):
            if code not in (0, -signal.SIGTERM, 130, 143):
                if messagebox.askyesno('Demon\'s Souls',
                                       'Demon\'s Souls stopped with an error (exit code %d).\n\n'
                                       'Open the logs folder?' % code):
                    open_path(LOGS)
        run('play', ['bash', PLAY], play_env(current()), on_done=done)

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
        env = dict(os.environ)
        if iso.get().strip():
            env['DES_ISO'] = iso.get().strip()
        if key.get().strip():
            env['DES_KEY'] = key.get().strip()
        env['DES_LTO'] = '1' if v['lto'].get() else '0'
        if not os.path.isdir(os.path.join(ROOT, 'game', 'PS3_GAME')) and not iso.get().strip():
            messagebox.showinfo('Demon\'s Souls', 'Choose your disc image (or a dumped disc folder) first.')
            return
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
        icon = icon_path if os.path.isfile(icon_path) else 'applications-games'
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
                            'into the game) to your applications menu. In Steam: Games > Add a Non-Steam Game to '
                            'My Library, and pick one of them.')

    menu.add_command(label='Saves folder', command=lambda: open_path(os.path.join(ROOT, 'gamedata')))
    menu.add_command(label='Logs folder', command=lambda: open_path(LOGS))
    menu.add_command(label='Keyboard and mouse keys (input.toml)',
                     command=lambda: open_path(os.path.join(HERE, 'input.toml')))
    menu.add_separator()
    menu.add_command(label='Add to the applications menu (and Steam)', command=add_menu_entry)

    b_play.configure(command=do_play)
    b_build.configure(command=do_build)
    b_update.configure(command=do_update)
    b_stop.configure(command=do_stop)

    def on_close():
        if busy() and state['kind'] == 'build':
            if not messagebox.askyesno('Demon\'s Souls', 'A build is running. Stop it and quit?'):
                return
            do_stop()
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', on_close)
    refresh()
    # Fit the screen (a Steam Deck is 800 px tall): the log is what gives way.
    root.update_idletasks()
    h = min(root.winfo_reqheight(), root.winfo_screenheight() - 60)
    root.geometry('%dx%d' % (max(root.winfo_reqwidth(), 560), h))
    root.mainloop()
    return 0


def main():
    if '--play' in sys.argv[1:]:
        return play_now(load_conf())
    return main_window()


if __name__ == '__main__':
    sys.exit(main())
