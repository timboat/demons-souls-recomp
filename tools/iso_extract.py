"""Extract files from a PS3 disc image of Demon's Souls (BLUS-30443).

The image can be a plain .iso or a .zip holding one (a Redump set, read straight out of the zip
without unpacking it). Redump images keep the disc's encryption: the sectors outside the plain
regions listed in sector 0 are AES-128-CBC encrypted with the disc key (IV = sector number, big
endian). Give that key with --key <32 hex digits> (or a .dkey file); a decrypted image needs none.

usage: python tools/iso_extract.py <image.iso|image.zip> <out_dir> [--key HEX] (--all | /PATH ...)
"""
import os, struct, sys, zipfile

SECT = 2048
HEAD = 17632            # plain region 0 of this disc: both filesystems' metadata


def open_image(path):
    """A sequential binary stream of the disc image (.iso, or the .iso inside a .zip)."""
    if zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        isos = [i for i in z.infolist() if i.filename.lower().endswith('.iso')]
        if not isos:
            sys.exit(f'{path}: no .iso inside the zip')
        return z.open(max(isos, key=lambda i: i.file_size))
    return open(path, 'rb')


def parse_key(text):
    """32 hex digits, a raw 16-byte .dkey file, or a text file holding the hex key."""
    if text and os.path.isfile(text):
        b = open(text, 'rb').read()
        if len(b) == 16:
            return b
        text = b.decode('latin-1')
    h = ''.join(c for c in (text or '') if c in '0123456789abcdefABCDEF')
    if len(h) != 32:
        raise ValueError('a disc key is 32 hex digits')
    return bytes.fromhex(h)


def regions(s0):
    n = struct.unpack('>I', s0[0:4])[0]
    return [struct.unpack('>II', s0[8 + i * 8:16 + i * 8]) for i in range(n)]


def dec_sector(key, buf, lba):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    iv = b'\0' * 12 + struct.pack('>I', lba)
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return d.update(buf) + d.finalize()


def iso9660_files(meta):
    files = {}
    def walk(lba, size, path):
        d = meta[lba * SECT: lba * SECT + size]; i = 0
        while i < len(d):
            L = d[i]
            if L == 0: i = (i // SECT + 1) * SECT; continue
            r = d[i:i + L]; ext, sz = struct.unpack('<I', r[2:6])[0], struct.unpack('<I', r[10:14])[0]
            name = r[33:33 + r[32]]
            if name not in (b'\0', b'\1'):
                n = name.decode('latin1').split(';')[0]
                if r[25] & 2: walk(ext, sz, path + n + '/')
                else: files[path + n] = (ext, sz)
            i += L
    root = meta[16 * SECT + 156:16 * SECT + 190]
    walk(struct.unpack('<I', root[2:6])[0], struct.unpack('<I', root[10:14])[0], '/')
    return files


def probe(path):
    """(needs_key, check) -- check(key) is True when that key decrypts EBOOT.BIN to a SELF."""
    f = open_image(path)
    meta = f.read(HEAD * SECT)
    files = iso9660_files(meta)
    if '/PS3_GAME/USRDIR/EBOOT.BIN' not in files:
        sys.exit(f'{path}: no PS3_GAME/USRDIR/EBOOT.BIN -- not a PS3 game disc image?')
    lba = files['/PS3_GAME/USRDIR/EBOOT.BIN'][0]
    if lba < HEAD:   # an image rebuilt from a folder dump: the file is in the part already read
        first = meta[lba * SECT:(lba + 1) * SECT]
    else:
        pos = HEAD
        while pos < lba:
            step = min(lba - pos, 8192); f.read(step * SECT); pos += step
        first = f.read(SECT)
    if first[:4] == b'SCE\0':
        return False, lambda key: True
    return True, lambda key: dec_sector(key, first, lba)[:4] == b'SCE\0'


def extract(path, out_dir, wanted, key=None):
    f = open_image(path)
    meta = f.read(HEAD * SECT)
    plain = regions(meta)
    is_plain = lambda l: key is None or any(a <= l <= b for a, b in plain)
    files = iso9660_files(meta)
    if wanted == ['--all']:   # everything but the system update
        wanted = [k for k in files if not k.startswith('/PS3_UPDATE/')]
    targets = sorted(((files[w][0], files[w][1], w) for w in wanted), key=lambda t: t[0])
    done = 0
    pos = HEAD
    for lba, size, name in targets:
        out = os.path.join(out_dir, name.lstrip('/')); os.makedirs(os.path.dirname(out), exist_ok=True)
        nsec = (size + SECT - 1) // SECT
        with open(out, 'wb') as o:
            left = size
            for k in range(nsec):
                l = lba + k
                if l < HEAD:   # a file that starts in the metadata part (an image rebuilt from a folder dump)
                    s = meta[l * SECT:(l + 1) * SECT]
                else:
                    # the stream is sequential (a zip member can't seek): skip forward
                    while pos < l:
                        step = min(l - pos, 8192); f.read(step * SECT); pos += step
                    s = f.read(SECT); pos += 1
                if not is_plain(l): s = dec_sector(key, s, l)
                o.write(s[:min(SECT, left)]); left -= SECT
        done += 1
        if len(targets) < 20 or done % 500 == 0 or done == len(targets):
            print(f'  [{done}/{len(targets)}] {name}', flush=True)


if __name__ == '__main__':
    args = sys.argv[1:]
    key = None
    if '--key' in args:
        i = args.index('--key'); key = parse_key(args[i + 1]); del args[i:i + 2]
    extract(args[0], args[1], args[2:], key)
