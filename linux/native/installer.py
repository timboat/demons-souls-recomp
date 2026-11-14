#!/usr/bin/env python3
"""Demon's Souls - one-click installer for the native Linux build.

Choose your disc image (BLUS-30443), paste its disc key if it is an encrypted (Redump) image, press Install.
The rest is automatic:
  1. the build tools: checked, and installed through your distribution's package manager after one
     password prompt (pkexec); on SteamOS a "des-build" distrobox container is made for the compile
     instead, since SteamOS itself has no compiler
  2. linux/native/build.sh with every step -- game files from your image, the EBOOT decrypted, the
     toolkit, the recompiled code, the compile -- its "==> step" lines and ninja's [n/N] drive the
     progress
  3. the applications-menu entries (where Steam's "Add a Non-Steam Game" finds them), then Play or the
     launcher (linux/native/launcher.py)
Safe to run again: every step skips what is already done, so after a failure or a Cancel, Install
continues where it stopped.

Run from a checkout (python3 linux/native/installer.py, or linux/native/install.sh, which also gets Tk
for Python if it is missing). Run on its own -- just this file -- it first clones the port (git) into the
folder it shows, branch DES_SOURCES_BRANCH (default linux-native) of DES_SOURCES_URL.
"""
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time

REDUMP_PAGE = 'http://redump.org/disc/16199/'   # Demon's Souls (USA), BLUS-30443: its "Disc Key" line
SOURCES_URL = os.environ.get('DES_SOURCES_URL', 'https://github.com/timboat/demons-souls-recomp')
SOURCES_BRANCH = os.environ.get('DES_SOURCES_BRANCH', 'linux-native')
BOX = 'des-build'
NEED_GB = 30

HERE = os.path.dirname(os.path.abspath(__file__))
IN_CHECKOUT = os.path.isfile(os.path.join(HERE, 'build.sh')) and os.path.basename(HERE) == 'native'
DEFAULT_ROOT = (os.path.dirname(os.path.dirname(HERE)) if IN_CHECKOUT
                else os.path.expanduser('~/DemonsSoulsRecomp-native'))

# Build tools by distribution family: the packages linux/native/build.sh needs, Tk for the launcher.
PACKAGES = {
    'arch': ['pacman', '-S', '--needed', '--noconfirm', 'clang', 'lld', 'cmake', 'ninja', 'sdl2', 'glslang',
             'spirv-tools', 'vulkan-headers', 'vulkan-icd-loader', 'ffmpeg', 'python', 'git', 'tk'],
    'debian': ['apt-get', 'install', '-y', 'clang', 'lld', 'cmake', 'ninja-build', 'libsdl2-dev', 'glslang-dev',
               'glslang-tools', 'spirv-tools', 'libvulkan-dev', 'libavcodec-dev', 'libavutil-dev',
               'python3-venv', 'python3-tk', 'git'],
    'fedora': ['dnf', 'install', '-y', 'clang', 'lld', 'cmake', 'ninja-build', 'SDL2-devel', 'glslang-devel',
               'spirv-tools-devel', 'vulkan-loader-devel', 'vulkan-headers', 'ffmpeg-free-devel', 'python3',
               'python3-tkinter', 'git'],
}
BOX_PACKAGES = ['clang', 'lld', 'cmake', 'ninja', 'sdl2-compat', 'glslang', 'spirv-tools', 'vulkan-headers',
                'vulkan-radeon', 'vulkan-intel', 'ffmpeg', 'python', 'git']

STEPS = [  # (build.sh step, what the checklist says)
    ('deps', 'Build tools'),
    ('venv', 'Python environment'),
    ('game', 'Game files from your disc image'),
    ('decrypt', 'Decrypt the game (EBOOT)'),
    ('toolkit', 'Recompilation toolkit'),
    ('lift', 'Recompile the game code'),
    ('build', 'Compile (the long part)'),
]
WEIGHT = {'deps': 1, 'venv': 2, 'game': 8, 'decrypt': 2, 'toolkit': 4, 'lift': 13, 'build': 70}


def os_release():
    d = {}
    try:
        for line in open('/etc/os-release'):
            if '=' in line:
                k, v = line.rstrip('\n').split('=', 1)
                d[k] = v.strip('"')
    except OSError:
        pass
    return d


def distro_family():
    r = os_release()
    ids = (r.get('ID', '') + ' ' + r.get('ID_LIKE', '')).split()
    if 'steamos' in ids:
        return 'steamos'
    for fam, keys in (('arch', ('arch', 'manjaro', 'endeavouros', 'cachyos')),
                      ('debian', ('debian', 'ubuntu', 'linuxmint', 'pop')),
                      ('fedora', ('fedora', 'rhel', 'nobara', 'bazzite'))):
        if any(k in ids for k in keys):
            return fam
    return None


def is_deck():
    try:
        return (open('/sys/class/dmi/id/board_vendor').read().strip() == 'Valve' and
                open('/sys/class/dmi/id/product_name').read().strip() in ('Jupiter', 'Galileo'))
    except OSError:
        return False


def box_exists():
    if not shutil.which('distrobox'):
        return False
    try:
        out = subprocess.run(['distrobox', 'list'], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(len(c) > 1 and c[1].strip() == BOX for c in (l.split('|') for l in out.splitlines()))


def key_ok(k):
    k = k.strip()
    return not k or re.fullmatch(r'[0-9A-Fa-f]{32}', k) is not None or os.path.isfile(os.path.expanduser(k))


def main():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print('The installer needs Tk for Python (tkinter). Run linux/native/install.sh, which installs it, or: '
              'Debian / Ubuntu: sudo apt install python3-tk; Fedora: sudo dnf install python3-tkinter; '
              'Arch: sudo pacman -S tk.')
        return 1

    root = tk.Tk()
    root.title("Demon's Souls - install (native Linux)")
    style = ttk.Style(root)
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    style.configure('Big.TButton', font=('TkDefaultFont', 12, 'bold'), padding=(18, 8))
    style.configure('Link.TLabel', foreground='#1a5fb4')
    style.configure('Horizontal.TProgressbar', background='#3584e4')   # clam's own fill is light grey: full looks empty
    family = distro_family()
    st = {'proc': None, 'cancelled': False, 'step': None, 'started': 0.0, 'done_steps': set()}

    outer = ttk.Frame(root, padding=14)
    outer.pack(fill='both', expand=True)
    ttk.Label(outer, text="Install Demon's Souls", font=('TkDefaultFont', 16, 'bold')).pack(anchor='w')
    ttk.Label(outer, wraplength=600, justify='left',
              text='The native Linux build of the PC port, made on this computer from your own copy of the game '
                   '(Demon\'s Souls, USA, BLUS-30443). Nothing of the game is downloaded.').pack(anchor='w', pady=(2, 10))

    form = ttk.Frame(outer)
    form.pack(fill='x')
    iso = tk.StringVar(value=os.environ.get('DES_ISO', ''))
    key = tk.StringVar(value=os.environ.get('DES_KEY', ''))
    dest = tk.StringVar(value=DEFAULT_ROOT)

    ttk.Label(form, text='1. Your disc image', font=('TkDefaultFont', 10, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
    e_iso = ttk.Entry(form, textvariable=iso, width=56)
    e_iso.grid(row=1, column=0, sticky='we', pady=2)

    def pick_iso():
        p = filedialog.askopenfilename(title='Your Demon\'s Souls disc image (.iso, or a Redump .zip)',
                                       filetypes=[('Disc images', '*.iso *.ISO *.zip *.ZIP'), ('All files', '*')])
        if p:
            iso.set(p)

    def pick_folder():
        p = filedialog.askdirectory(title='A dumped disc folder (the one holding PS3_GAME)')
        if p:
            iso.set(p)
    b1 = ttk.Button(form, text='Choose file...', command=pick_iso)
    b1.grid(row=1, column=1, padx=(6, 0))
    b2 = ttk.Button(form, text='Folder...', command=pick_folder)
    b2.grid(row=1, column=2, padx=(6, 0))
    ttk.Label(form, foreground='#666', text='an .iso, a Redump .zip, or a dumped disc folder (holding PS3_GAME)').grid(
        row=2, column=0, columnspan=3, sticky='w')

    ttk.Label(form, text='2. Its disc key', font=('TkDefaultFont', 10, 'bold')).grid(row=3, column=0, columnspan=3, sticky='w', pady=(10, 0))
    e_key = ttk.Entry(form, textvariable=key, width=56, font=('TkFixedFont', 10))
    e_key.grid(row=4, column=0, sticky='we', pady=2)

    def open_redump():
        subprocess.Popen(['xdg-open', REDUMP_PAGE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    b3 = ttk.Button(form, text='Find it on Redump', command=open_redump)
    b3.grid(row=4, column=1, columnspan=2, sticky='we', padx=(6, 0))
    link = ttk.Label(form, style='Link.TLabel', cursor='hand2', wraplength=600, justify='left',
                     text='Copy the 32-character "Disc Key" from Redump\'s page for this disc (%s) and paste it here. '
                          'Only an encrypted (Redump) image needs it; a decrypted .iso or a disc folder does not, '
                          'and a .dkey file next to the image is found on its own.' % REDUMP_PAGE)
    link.grid(row=5, column=0, columnspan=3, sticky='w')
    link.bind('<Button-1>', lambda _e: open_redump())

    ttk.Label(form, text='3. Install into', font=('TkDefaultFont', 10, 'bold')).grid(row=6, column=0, columnspan=3, sticky='w', pady=(10, 0))
    e_dest = ttk.Entry(form, textvariable=dest, width=56)
    e_dest.grid(row=7, column=0, sticky='we', pady=2)

    def pick_dest():
        p = filedialog.askdirectory(title='Where the game is built (about %d GB)' % NEED_GB, mustexist=False)
        if p:
            dest.set(p)
    b4 = ttk.Button(form, text='Change...', command=pick_dest)
    b4.grid(row=7, column=1, columnspan=2, sticky='we', padx=(6, 0))
    if IN_CHECKOUT:   # this checkout is where the build goes
        e_dest.configure(state='disabled')
        b4.configure(state='disabled')
    space = tk.StringVar()
    ttk.Label(form, textvariable=space, foreground='#666').grid(row=8, column=0, columnspan=3, sticky='w')
    form.columnconfigure(0, weight=1)

    def update_space(*_):
        d = dest.get().strip() or DEFAULT_ROOT
        while d and not os.path.isdir(d):
            d = os.path.dirname(d)
        try:
            free = shutil.disk_usage(d or '/').free / 1e9
            space.set('%.0f GB free there; the install needs about %d GB.' % (free, NEED_GB))
        except OSError:
            space.set('')
    dest.trace_add('write', update_space)
    update_space()

    # --- progress -----------------------------------------------------------------------------------------
    prog = ttk.Frame(outer)
    prog.pack(fill='x', pady=(12, 0))
    checks = {}
    for i, (s, label) in enumerate(STEPS):
        var = tk.StringVar(value='     ' + label)
        ttk.Label(prog, textvariable=var).grid(row=i // 2, column=i % 2, sticky='w', padx=(0, 20))
        checks[s] = (var, label)
    bar = ttk.Progressbar(outer, maximum=100, mode='determinate')
    bar.pack(fill='x', pady=(8, 0))
    msg = tk.StringVar(value='')
    ttk.Label(outer, textvariable=msg, wraplength=600, justify='left').pack(anchor='w', pady=(4, 0))

    logframe = ttk.Frame(outer)
    logbox = tk.Text(logframe, height=8, wrap='none', font=('TkFixedFont', 9))
    sb = ttk.Scrollbar(logframe, command=logbox.yview)
    logbox.configure(yscrollcommand=sb.set, state='disabled')
    sb.pack(side='right', fill='y')
    logbox.pack(side='left', fill='both', expand=True)
    shown = {'log': False}

    def toggle_log():
        if shown['log']:
            logframe.pack_forget()
        else:
            logframe.pack(fill='both', expand=True, pady=(6, 0), before=btns)
        shown['log'] = not shown['log']
        b_log.configure(text='Hide details' if shown['log'] else 'Show details')

    def log(text):
        logbox.configure(state='normal')
        logbox.insert('end', text)
        if int(logbox.index('end-1c').split('.')[0]) > 5000:
            logbox.delete('1.0', '1500.0')
        logbox.see('end')
        logbox.configure(state='disabled')

    btns = ttk.Frame(outer)
    btns.pack(fill='x', pady=(10, 0))
    b_install = ttk.Button(btns, text='Install', style='Big.TButton')
    b_install.pack(side='left')
    b_cancel = ttk.Button(btns, text='Cancel', state='disabled')
    b_cancel.pack(side='left', padx=8)
    b_log = ttk.Button(btns, text='Show details', command=toggle_log)
    b_log.pack(side='right')
    after = ttk.Frame(outer)   # Play / launcher, once installed

    inputs = (e_iso, e_key, e_dest, b1, b2, b4)

    def set_busy(busy):
        for w in inputs:
            if w in (e_dest, b4) and IN_CHECKOUT:
                continue
            w.configure(state='disabled' if busy else 'normal')
        b_install.configure(state='disabled' if busy else 'normal')
        b_cancel.configure(state='normal' if busy else 'disabled')

    def mark(step, state):
        var, label = checks[step]
        var.set({'run': '  >  ', 'ok': '  ✓  ', 'fail': '  ✗  ', '': '     '}[state] + label)

    def progress(step, frac=0.0):
        done = sum(WEIGHT[s] for s, _ in STEPS if s in st['done_steps'])
        cur = WEIGHT.get(step, 0) * max(0.0, min(1.0, frac))
        bar['value'] = 100.0 * (done + cur) / sum(WEIGHT.values())

    # --- running things -----------------------------------------------------------------------------------
    def run(argv, cwd, env, on_line, on_done):
        log('\n$ ' + ' '.join(shlex.quote(a) for a in argv) + '\n')
        try:
            p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, bufsize=1, start_new_session=True)
        except OSError as e:
            log('could not start: %s\n' % e)
            root.after(0, on_done, 127)
            return
        st['proc'] = p

        def reader():
            for line in p.stdout:
                root.after(0, log, line)
                if on_line:
                    root.after(0, on_line, line)
            code = p.wait()
            root.after(0, finish, code)

        def finish(code):
            st['proc'] = None
            on_done(code)
        threading.Thread(target=reader, daemon=True).start()

    def fail(text):
        msg.set(text)
        set_busy(False)
        if st['step']:
            mark(st['step'], 'fail')
        if not shown['log']:
            toggle_log()

    def root_dir():
        return os.path.abspath(os.path.expanduser(dest.get().strip() or DEFAULT_ROOT))

    def build_env():
        e = dict(os.environ)
        e['DES_ISO'] = os.path.expanduser(iso.get().strip())
        k = key.get().strip()
        if k:
            e['DES_KEY'] = os.path.expanduser(k) if os.path.isfile(os.path.expanduser(k)) else k
        else:
            e.pop('DES_KEY', None)
        return e

    def start():
        st['cancelled'] = False
        st['error'] = ''
        st['done_steps'] = set()
        for s, _ in STEPS:
            mark(s, '')
        after.pack_forget()
        img = os.path.expanduser(iso.get().strip())
        rd = root_dir()
        have_game = os.path.isfile(os.path.join(rd, 'game', 'PS3_GAME', 'USRDIR', 'EBOOT.BIN'))
        if not have_game and not (img and os.path.exists(img)):
            messagebox.showinfo('Demon\'s Souls', 'Choose your disc image (or a dumped disc folder) first.')
            return
        if not key_ok(key.get()):
            messagebox.showinfo('Demon\'s Souls', 'The disc key is 32 characters, 0-9 and A-F (Redump\'s "Disc Key" '
                                'line), or the path of a .dkey file. Leave it empty for a decrypted image.')
            return
        if img.lower().endswith('.zip') and not key.get().strip() and not have_game:
            stem = os.path.splitext(img)[0]
            near = [f for f in os.listdir(os.path.dirname(img) or '.') if f.lower().endswith('.dkey')]
            if not os.path.isfile(stem + '.dkey') and not near:
                if not messagebox.askyesno('Demon\'s Souls', 'A Redump .zip is encrypted and needs its disc key '
                                           '(the "Find it on Redump" button). Try without one anyway?'):
                    return
        try:
            free = shutil.disk_usage(rd if os.path.isdir(rd) else os.path.dirname(rd) or '/').free / 1e9
            if free < NEED_GB and not have_game and not messagebox.askyesno(
                    'Demon\'s Souls', 'Only %.0f GB is free there and the install needs about %d GB. Go on anyway?'
                    % (free, NEED_GB)):
                return
        except OSError:
            pass
        set_busy(True)
        st['started'] = time.time()
        tick()
        get_sources()

    def tick():
        if st['proc'] is not None or b_cancel.instate(['!disabled']):
            m = int(time.time() - st['started']) // 60
            if st['step'] == 'build':
                root.title("Demon's Souls - installing (%d%%, %d min)" % (bar['value'], m))
            root.after(5000, tick)
        else:
            root.title("Demon's Souls - install (native Linux)")

    # 0. the sources: this checkout, or a clone
    def get_sources():
        rd = root_dir()
        if os.path.isfile(os.path.join(rd, 'linux', 'native', 'build.sh')):
            return tools()
        if os.path.exists(rd) and os.listdir(rd):
            return fail('%s is not empty and holds no copy of the port. Choose an empty or new folder.' % rd)
        if not shutil.which('git'):
            return need_tools('git is needed to download the port.')
        msg.set('Downloading the port (git clone, about 100 MB)...')
        os.makedirs(os.path.dirname(rd), exist_ok=True)
        run(['git', 'clone', '--branch', SOURCES_BRANCH, '--depth', '1', SOURCES_URL, rd], None, dict(os.environ),
            None, lambda code: tools() if code == 0 else
            fail('The download failed (git clone, exit code %d). Check the internet connection and press Install '
                 'again.' % code))

    # 1. the build tools
    def tools():
        st['step'] = 'deps'
        mark('deps', 'run')
        msg.set('Checking the build tools...')
        rd = root_dir()
        run(['bash', os.path.join(rd, 'linux', 'native', 'build.sh'), 'deps'], rd, build_env(), None,
            lambda code: build() if code == 0 else need_tools(None))

    def need_tools(why):
        if family == 'steamos' or (is_deck() and not shutil.which('clang')):
            if box_exists():
                return fail('The build container "%s" is missing tools (see the details). Press Install to try '
                            'again after fixing it, or remove it (distrobox rm %s) and let Install make it '
                            'anew.' % (BOX, BOX))
            if not shutil.which('distrobox'):
                return fail('SteamOS has no compiler, and distrobox (which this installer uses for one) is not here.')
            if not messagebox.askyesno('Demon\'s Souls', 'SteamOS has no compiler of its own, so the game is compiled '
                                       'in a container ("%s", Arch Linux, about 2 GB downloaded once). Make it '
                                       'now?' % BOX):
                return fail('Stopped: the build container is needed on SteamOS.')
            msg.set('Making the build container (a few minutes)...')
            cmd = ('distrobox create -Y -n %s -i docker.io/library/archlinux:latest && '
                   'distrobox enter %s -- sudo pacman -Syu --noconfirm --needed %s'
                   % (BOX, BOX, ' '.join(BOX_PACKAGES)))
            return run(['bash', '-c', cmd], None, dict(os.environ), None,
                       lambda code: tools() if code == 0 else
                       fail('The build container could not be made (exit code %d; the details say why).' % code))
        pk = PACKAGES.get(family)
        if not pk:
            return fail((why + ' ' if why else '') + 'Install the build tools your distribution names for: clang, lld, '
                        'cmake, ninja, SDL2, glslang, SPIRV-Tools, the Vulkan headers, FFmpeg (libavcodec), Python 3 '
                        'with venv and Tk, git. Then press Install again.')
        line = ' '.join(pk)
        if not shutil.which('pkexec'):
            return fail('Missing build tools. Install them in a terminal, then press Install again:\n  sudo ' + line)
        if not messagebox.askyesno('Demon\'s Souls', (why + '\n\n' if why else '') + 'Some build tools are missing. '
                                   'Install them now? Your password is asked for, then this runs:\n\n' + line):
            return fail('Stopped: the build tools are needed. In a terminal: sudo ' + line)
        msg.set('Installing the build tools...')
        argv = ['pkexec'] + pk
        if family == 'debian':
            argv = ['pkexec', 'sh', '-c', 'apt-get update && ' + line]
        run(argv, None, dict(os.environ, DEBIAN_FRONTEND='noninteractive'), None,
            lambda code: get_sources() if code == 0 else
            fail('Installing the build tools failed (exit code %d). In a terminal: sudo %s' % (code, line)))

    # 2. everything else: linux/native/build.sh
    def build():
        st['done_steps'].add('deps')
        mark('deps', 'ok')
        progress('venv')
        rd = root_dir()
        msg.set('Installing. The compile takes a while: about an hour on a Steam Deck, less on a desktop PC.')

        def on_line(line):
            if line.startswith('==> '):
                s = line[4:].split(' ', 1)[0].strip()
                if st['step'] and st['step'] != s and st['step'] in checks:
                    st['done_steps'].add(st['step'])
                    mark(st['step'], 'ok')
                if s in checks:
                    st['step'] = s
                    mark(s, 'run')
                    progress(s)
                return
            m = re.match(r'\[(\d+)/(\d+)\]', line)
            if m and st['step'] == 'build':
                progress('build', int(m.group(1)) / max(1, int(m.group(2))))
            elif line.startswith('ERROR: '):
                st['error'] = line[7:].strip()

        def on_done(code):
            if code == 0:
                for s, _ in STEPS:
                    st['done_steps'].add(s)
                    mark(s, 'ok')
                bar['value'] = 100
                return finished()
            if st['cancelled']:
                return fail('Cancelled. Press Install to continue where it stopped.')
            text = st.get('error', '')
            text = (text[0].upper() + text[1:]).rstrip('.') + '.' if text else ''
            fail('The install stopped%s. %sPress Install to try again; it continues where it stopped.' % (
                ' at "%s"' % checks[st['step']][1] if st['step'] in checks else '',
                (text + ' ') if text else '(The details below say why.) '))
        run(['bash', os.path.join(rd, 'linux', 'native', 'build.sh'),
             'venv', 'game', 'decrypt', 'toolkit', 'lift', 'build'], rd, build_env(), on_line, on_done)

    # 3. done: menu entries, Play / launcher
    def finished():
        set_busy(False)
        rd = root_dir()
        launcher = os.path.join(rd, 'linux', 'native', 'launcher.py')
        try:
            add_menu_entries(rd, launcher)
            extra = ' "Demon\'s Souls (native)" is in your applications menu (Steam: Games > Add a Non-Steam Game).'
        except OSError:
            extra = ''
        msg.set('Installed in %d minutes.%s' % (int(time.time() - st['started']) // 60, extra))
        for w in after.winfo_children():
            w.destroy()
        py = sys.executable or 'python3'
        ttk.Button(after, text='Play', style='Big.TButton',
                   command=lambda: (subprocess.Popen([py, launcher, '--play'], cwd=rd, start_new_session=True),
                                    root.destroy())).pack(side='left')
        ttk.Button(after, text='Open the launcher (settings)',
                   command=lambda: (subprocess.Popen([py, launcher], cwd=rd, start_new_session=True),
                                    root.destroy())).pack(side='left', padx=8)
        after.pack(fill='x', pady=(10, 0), before=btns)

    def add_menu_entries(rd, launcher):
        apps = os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'applications')
        os.makedirs(apps, exist_ok=True)
        icon = os.path.join(rd, 'game', 'PS3_GAME', 'ICON0.PNG')
        icon = icon if os.path.isfile(icon) else 'applications-games'
        py = shlex.quote(sys.executable or 'python3')
        for fname, name, extra in (('demons-souls-native.desktop', "Demon's Souls (native)", ''),
                                   ('demons-souls-native-play.desktop', "Demon's Souls (native) - play", ' --play')):
            with open(os.path.join(apps, fname), 'w') as f:
                f.write('[Desktop Entry]\nType=Application\nName=%s\nExec=%s %s%s\nIcon=%s\nTerminal=false\n'
                        'Categories=Game;\nPath=%s\n' % (name, py, shlex.quote(launcher), extra, icon, rd))

    def cancel():
        p = st['proc']
        if not p or p.poll() is not None:
            return
        st['cancelled'] = True
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except OSError:
            pass
        if st['step'] == 'build' and box_exists():   # the compile runs inside the container, outside this group
            subprocess.Popen(['distrobox', 'enter', BOX, '--', 'pkill', '-TERM', '-f', 'ninja -C ' + root_dir()],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def on_close():
        if st['proc'] is not None and st['proc'].poll() is None:
            if not messagebox.askyesno('Demon\'s Souls', 'The install is running. Stop it and quit? Install '
                                       'continues where it stopped next time.'):
                return
            cancel()
        root.destroy()

    b_install.configure(command=start)
    b_cancel.configure(command=cancel)
    root.protocol('WM_DELETE_WINDOW', on_close)
    if IN_CHECKOUT and os.access(os.path.join(DEFAULT_ROOT, 'port', 'build_linux', 'DemonsSoulsRecomp'), os.X_OK):
        msg.set('This copy is installed already. Install again checks every step and rebuilds what changed.')
    root.update_idletasks()
    root.minsize(root.winfo_reqwidth(), min(root.winfo_reqheight(), root.winfo_screenheight() - 60))
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
