"""Give the extracted files their real names from the disc's UDF filesystem.

iso_extract.py walks ISO9660, whose names on PS3 discs are mangled: upper case,
one dot per name ("ds_filter.shaderbnd.dcx" -> "DS_FILTER_SHADERBND.DCX") and
cut at 31 characters. The game asks for the real names, which only the UDF
filesystem (2.50, with a metadata partition) carries. Both filesystems point at
the same data extents, so each UDF file is matched to the ISO9660 file that
starts at the same sector, and renamed.

Images made on a PS3 or with makeps3iso (ManaGunZ, webMAN, PS3 ISO Tools: GitHub #60) have no UDF at
all. Their ISO9660 names are already the real ones, only in upper case; the names then come from a Joliet
tree when there is one, else the files under PS3_GAME/USRDIR (all lower case on the disc, EBOOT.BIN aside)
are lower-cased. A UDF-less image with mangled names (one dot per name) is refused: the real names are gone.

usage: python tools/udf_rename.py <image.iso|image.zip> <game_dir> [--dry-run]
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iso_extract import open_image, read_meta   # noqa: E402

SECT = 2048
zip_path, game_dir = sys.argv[1], sys.argv[2]
dry = '--dry-run' in sys.argv

head = read_meta(open_image(zip_path))[0]             # plain region 0: both filesystems' metadata
sec = lambda n: head[n * SECT:(n + 1) * SECT]
u16 = lambda b, o: struct.unpack_from('<H', b, o)[0]
u32 = lambda b, o: struct.unpack_from('<I', b, o)[0]
u64 = lambda b, o: struct.unpack_from('<Q', b, o)[0]
tag = lambda b: u16(b, 0)

# --- ISO9660 side (same walk as iso_extract.py) --------------------------------
iso = {}
def iwalk(lba, size, path):
    d = head[lba * SECT: lba * SECT + size]; i = 0
    while i < len(d):
        L = d[i]
        if L == 0: i = (i // SECT + 1) * SECT; continue
        r = d[i:i + L]; ext = u32(r, 2); sz = u32(r, 10); nm = r[33:33 + r[32]]
        if nm not in (b'\0', b'\1'):
            n = nm.decode('latin1').split(';')[0]
            if r[25] & 2: iwalk(ext, sz, path + n + '/')
            else: iso[ext] = path + n
        i += L
root = head[16 * SECT + 156:16 * SECT + 190]
iwalk(u32(root, 2), u32(root, 10), '/')


def udf_names():
    """{first data sector: real path} from the UDF file system (2.50, metadata partition)."""
    # --- volume descriptors ------------------------------------------------------
    avdp = sec(256)
    vds_len, vds_loc = u32(avdp, 16), u32(avdp, 20)
    part_start = None; lvd = None
    for i in range(vds_len // SECT):
        d = sec(vds_loc + i)
        if tag(d) == 5: part_start = u32(d, 188)
        elif tag(d) == 6: lvd = d
        elif tag(d) == 8: break
    assert part_start is not None and lvd is not None
    fsd_lbn, fsd_pref = u32(lvd, 252), u16(lvd, 256)
    nmaps = u32(lvd, 268); maps = []; o = 440
    for _ in range(nmaps):
        t, ln = lvd[o], lvd[o + 1]
        if t == 1: maps.append(('phys', None))
        else:
            ident = lvd[o + 5:o + 28]
            assert b'Metadata' in ident, ident
            maps.append(('meta', u32(lvd, o + 40)))       # metadata file location (phys-partition lbn)
        o += ln

    def phys(lbn):                      # physical-partition lbn -> disc sector
        return part_start + lbn

    # metadata file: an (extended) file entry whose extents hold the metadata partition
    meta_extents = []
    for kind, loc in maps:
        if kind == 'meta':
            fe = sec(phys(loc))
            assert tag(fe) in (261, 266), tag(fe)
            l_ea, l_ad, base = (u32(fe, 168), u32(fe, 172), 176) if tag(fe) == 261 else (u32(fe, 208), u32(fe, 212), 216)
            p = base + l_ea
            while p < base + l_ea + l_ad:
                ln, pos = u32(fe, p) & 0x3FFFFFFF, u32(fe, p + 4); p += 8
                meta_extents.append((pos, ln // SECT))

    def resolve(lbn, pref):             # (lbn, partition ref) -> disc sector
        if maps[pref][0] == 'phys':
            return phys(lbn)
        for pos, n in meta_extents:
            if lbn < n: return phys(pos + lbn)
            lbn -= n
        raise ValueError('lbn outside metadata partition')

    def read(sector, nbytes):
        return head[sector * SECT: sector * SECT + nbytes]

    def file_entry(sector):
        fe = sec(sector)
        t = tag(fe); assert t in (261, 266), (sector, t)
        ftype = fe[16 + 11]; adtype = u16(fe, 16 + 18) & 7
        size = u64(fe, 56)
        l_ea, l_ad, base = (u32(fe, 168), u32(fe, 172), 176) if t == 261 else (u32(fe, 208), u32(fe, 212), 216)
        ads = fe[base + l_ea: base + l_ea + l_ad]
        return ftype, adtype, size, ads

    def dstring(b):
        if not b: return ''
        return b[1:].decode('latin-1') if b[0] == 8 else b[1:].decode('utf-16-be')

    udf = {}                            # first data sector -> real path
    def walk(icb_lbn, icb_pref, path):
        ftype, adtype, size, ads = file_entry(resolve(icb_lbn, icb_pref))
        if adtype == 3: data = ads[:size]
        else:
            data = b''; p = 0
            while p < len(ads) and len(data) < size:
                ln, pos = u32(ads, p) & 0x3FFFFFFF, u32(ads, p + 4)
                pref = icb_pref if adtype == 0 else u16(ads, p + 8)
                data += read(resolve(pos, pref), ln); p += 8 if adtype == 0 else 16
        p = 0
        while p + 38 <= len(data):
            if tag(data[p:]) != 257: break
            chars, l_fi = data[p + 18], data[p + 19]
            c_lbn, c_pref = u32(data, p + 24), u16(data, p + 28)
            l_iu = u16(data, p + 36)
            name = dstring(data[p + 38 + l_iu: p + 38 + l_iu + l_fi])
            rec = (38 + l_iu + l_fi + 3) & ~3
            if not chars & 8:           # not the parent entry
                if chars & 2: walk(c_lbn, c_pref, path + name + '/')
                else:
                    _, at, fsize, fads = file_entry(resolve(c_lbn, c_pref))
                    first = resolve(u32(fads, 4), c_pref if at == 0 else u16(fads, 8)) if at != 3 and fsize else None
                    udf[first] = path + name
            p += rec

    fsd = sec(resolve(fsd_lbn, fsd_pref)); assert tag(fsd) == 256
    walk(u32(fsd, 404), u16(fsd, 408), '/')
    print(f'UDF: {len(udf)} files')
    return udf


def joliet_names():
    """{first data sector: path} from a Joliet supplementary volume descriptor, or None."""
    for n in range(17, 32):
        v = sec(n)
        if v[0] == 255 or v[1:6] != b'CD001': break
        if v[0] == 2 and v[88:91] in (b'%/@', b'%/C', b'%/E'):
            names = {}
            def jwalk(lba, size, path):
                d = head[lba * SECT: lba * SECT + size]; i = 0
                while i < len(d):
                    L = d[i]
                    if L == 0: i = (i // SECT + 1) * SECT; continue
                    r = d[i:i + L]; ext = u32(r, 2); sz = u32(r, 10); nm = r[33:33 + r[32]]
                    if nm not in (b'\0', b'\1'):
                        n = nm.decode('utf-16-be', 'replace').split(';')[0]
                        if r[25] & 2: jwalk(ext, sz, path + n + '/')
                        else: names[ext] = path + n
                    i += L
            root = v[156:190]
            jwalk(u32(root, 2), u32(root, 10), '/')
            print(f'Joliet: {len(names)} files')
            return names
    return None


def lower_names():
    """No UDF and no Joliet: the ISO9660 names with the files under PS3_GAME/USRDIR lower-cased (as on the
    disc), when they are the real names (dotted names kept whole); else exit with what to do."""
    if not any(p.count('.') > 1 for p in iso.values()):
        sys.exit('This disc image has no UDF file system and its ISO9660 names are shortened, so the real file\n'
                 'names are lost. Make the image again with a tool that keeps them (a Redump-style dump with\n'
                 'its .dkey, or a PS3 folder backup: SETUP.bat accepts the dumped game folder too).')
    names = {}
    for lba, p in iso.items():
        d, b = p.rsplit('/', 1)
        names[lba] = d + '/' + (b.lower() if p.upper().startswith('/PS3_GAME/USRDIR/') and b.upper() != 'EBOOT.BIN' else b)
    print(f'no UDF or Joliet: the ISO9660 names, PS3_GAME/USRDIR files lower-cased ({len(names)} files)')
    return names


if len(sec(256)) == SECT and tag(sec(256)) == 2:
    udf = udf_names()
else:
    print('no UDF file system in this image (made on a PS3 or with makeps3iso?)')
    udf = joliet_names() or lower_names()

renamed = same = missing = 0
for lba, ipath in iso.items():
    real = udf.get(lba)
    if real is None:
        missing += 1; continue
    if real == ipath:
        same += 1; continue
    src = os.path.join(game_dir, ipath.lstrip('/'))
    dst = os.path.join(os.path.dirname(src), os.path.basename(real))
    if not os.path.exists(src):
        continue
    if os.path.basename(src) == os.path.basename(dst):
        same += 1; continue
    if dry:
        if renamed < 15: print(f'  {ipath} -> {os.path.basename(real)}')
    else:
        os.replace(src, dst)        # also fixes case-only differences
    renamed += 1
print(f'renamed {renamed}, unchanged {same}, no UDF match {missing}')
