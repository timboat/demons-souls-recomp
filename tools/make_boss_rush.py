"""Boss rush mode: build game_bossrush/ from your own game/ (the launcher's "Game: Boss rush"; PLAY.bat runs this
when the folder is missing or older than this tool / the module).

usage: python tools/make_boss_rush.py [--check]

game_bossrush/ is a copy of game/ made of hard links (no extra disk space); the few files it changes are removed
first (a hard link is shared with game/) and written new, so game/ is never touched. What it changes:
- the 7 event-script bundles (SCRIPT/mXX.luabnd.dcx -> .sdat): tools/boss_rush/bossrush.lua appended to
  global_event.lua, with a BR_MapLoad(proxy) call at the end of g_Initialize;
- the 16 boss maps (MAP/MAPSTUDIO/*.msb): each boss's archstone warp point moved onto its fog gate, facing the
  fog, so a warp lands there (False King's: on his elevator at the bottom, which the module rides up);
- the event texts (MSG/NA_ENGLISH/menu.msgbnd): "Fight <boss>?" in empty slots; the item texts
  (MSG/NA_ENGLISH/item.msgbnd): the Nexial Binding's description and story say it keeps your souls;
- the shops (PARAM/GAMEPARAM/gameparamna.parambnd): Boldwin also sells Firebombs (a copy of the Dregling Merchant's
  ShopLineupParam row 1002 as 9009), Turpentine, every upgrade material and every weapon / shield / catalyst /
  talisman / bow / ammo (BOLDWIN_GOODS / BOLDWIN_WEAPONS: rows 9010 on, copies of his own rows with the item and
  the price changed); the Nexial Binding keeps your souls, like Evacuate (nexial_binding);
- bossrush\\timer_font.bin: the on-screen timer's letters, drawn from the game's own font (FONT/NA_ENGLISH/dsfont24,
  via tools/kbm_icons.py's glyph reader) -- made here from your game files, like the rest;
- Boldwin's talk script (SCRIPT/TALK/m01.talkesdbnd -> .sdat, t0694.esd): his shop lists rows 9000-9299 instead
  of 9000-9099 (one int literal), so the longer list fits.
--check: build into a temporary folder and verify, without touching game_bossrush/.
docs/NOTES.md (boss rush) has where each id comes from."""
import hashlib, io, os, shutil, struct, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import souls_formats as sf   # noqa: E402

GAME = os.path.join(ROOT, 'game')
USR = os.path.join('PS3_GAME', 'USRDIR')
MODULE = os.path.join(HERE, 'boss_rush', 'bossrush.lua')
STAMP = 'BOSS_RUSH_BUILT.txt'

# (map, warp point entity, fog region entity): the point each boss's WarpNextStage lands on (bossrush.lua BR_B)
POINTS = [('m02_00_00_00', 998, 2895), ('m02_01_00_00', 997, 2894), ('m02_02_00_00', 996, 2893),
          ('m02_03_00_00', 995, 2892), ('m03_01_00_00', 997, 2894), ('m03_02_00_00', 996, 2893),
          ('m03_03_00_00', 995, 2892), ('m04_00_00_00', 998, 2895), ('m04_01_00_00', 997, 2894),
          ('m04_02_00_00', 996, 2893), ('m05_00_00_00', 998, 2895), ('m05_01_00_00', 997, 2894),
          ('m05_02_00_00', 996, 2893), ('m06_00_00_00', 998, 2895), ('m06_01_00_00', 997, 2894),
          ('m06_02_00_00', 996, 2893)]
# False King's fog is at the top of an elevator (object 1620) whose platform is the floor there; his map's init
# parks it at the bottom: land on it there (its "ride up" region 2650), facing the fog side.
ON_ELEVATOR = {('m02_03_00_00', 995): (-10.87, 138.0, 1004.21, 180.0)}
BOSS_NAMES = ['Phalanx', 'the Tower Knight', 'the Penetrator', 'the False King', 'the Adjudicator', 'the Old Hero',
              'the Storm King', "the Fool's Idol", 'the Maneater', 'the Old Monk', 'the Leechmonger',
              'the Dirty Colossus', 'Maiden Astraea', 'the Armor Spider', 'the Flamelurker', 'the Dragon God']
BOSS_TEXT_IDS = list(range(10010700, 10010710)) + list(range(10010713, 10010719))   # bossrush.lua BR_MSG
TEXTS = {i: 'Fight %s?' % n for i, n in zip(BOSS_TEXT_IDS, BOSS_NAMES)}
SCRIPT_BUNDLES = ('m01', 'm02', 'm03', 'm04', 'm05', 'm06', 'm08')
# Boldwin's shop (ShopLineupParam rows 9000-9008 in the game, 9009 Firebombs above): goods (equip type 3) and
# weapons (type 0: shields / catalysts / talismans / bows / ammo too) from row 9010 on, as (id, price).
# Weapons: every base weapon (id % 100 == 0) with an English name, minus the wandering-demon placeholders (x9000),
# "No Equipment" (100300), the unnamed sniper arrow (160300), the Torch (60800: no weapon row) and what he
# already sells. Materials: every named
# upgrade stone (goods 2000-2057) but the unused Shard of Meltstone (2054).
SHOP_FIRST_ROW = 9010
SHOP_LAST_ROW = 9299          # his talk script's new upper bound (was 9099)
MAT_PRICE = {'shard': 300, 'large': 800, 'chunk': 1500, 'pure': 10000}
BOLDWIN_GOODS = [(1015, 400)] + [(i, MAT_PRICE[k]) for i, k in [
    (2000, 'shard'), (2001, 'large'), (2002, 'chunk'), (2003, 'pure'), (2004, 'shard'), (2005, 'large'),
    (2006, 'chunk'), (2007, 'pure'), (2012, 'shard'), (2013, 'chunk'), (2014, 'pure'), (2015, 'shard'),
    (2016, 'chunk'), (2017, 'pure'), (2021, 'shard'), (2022, 'chunk'), (2023, 'pure'), (2024, 'shard'),
    (2025, 'chunk'), (2026, 'pure'), (2027, 'shard'), (2028, 'chunk'), (2029, 'pure'), (2030, 'shard'),
    (2031, 'chunk'), (2032, 'pure'), (2033, 'shard'), (2034, 'chunk'), (2035, 'pure'), (2036, 'shard'),
    (2037, 'chunk'), (2038, 'pure'), (2039, 'shard'), (2040, 'chunk'), (2041, 'pure'), (2042, 'shard'),
    (2043, 'chunk'), (2044, 'pure'), (2045, 'shard'), (2046, 'chunk'), (2047, 'pure'), (2048, 'shard'),
    (2049, 'chunk'), (2050, 'pure'), (2055, 'large'), (2056, 'large'), (2057, 'large')]]
# Prices (souls) by item id: what normal shops charge where they sell it (Brushwood capped), else by tier: best weapons
# 40,000-75,000, strong 15,000-30,000, solid 2,000-8,000. Against a run's 374,382 souls from the 16 bosses at 1x.
WEAPON_PRICE = {i: p for p, ids in {
    75000: [21500],
    60000: [20900, 21000],
    50000: [21600, 40700],
    45000: [50500],
    40000: [21700, 21800, 70300, 90200],
    30000: [20700, 21900, 60500, 130500, 150700, 151200],
    25000: [40900, 60700, 100200],
    20000: [20800, 21300, 30400, 40500, 70400, 80300, 90100, 90500, 150900],
    15000: [10500, 10600, 30200, 40600, 130400, 140200, 150400, 151100, 151400],
    10000: [50300],
    8000: [40400, 150600],
    6000: [20500, 20600, 50200, 80100],
    5000: [10400, 20300, 50400, 60400, 80200, 90400, 130300, 140100],
    4000: [20400, 30300, 60200, 70100, 80000, 150500, 151300],
    3000: [10700, 30100, 40100, 40200, 60100, 60300, 100100, 130100, 130200, 150200],
    2000: [10100, 10200, 20100, 100000, 140000],
    1500: [20200, 21100, 30000, 40300, 70000, 130000, 150000],
    1000: [40000, 90000, 150800, 151500],
    500: [21400, 60000, 60600, 150100, 160700],
    400: [160500],
    200: [151000, 160600],
    100: [170200],
    50: [160200, 160400],
    40: [170100],
    30: [160100],
    10: [170300],
    5: [160800],
}.items() for i in ids}
# Armour: a full set's price split helm 20% / body 40% / hands 20% / legs 20% near enough; top sets 30,000-50,000.
ARMOUR_PRICE = {i: p for p, ids in {
    20000: [201100],
    16000: [200800, 200900],
    15000: [200500],
    14000: [201900],
    12000: [201000, 300800, 400800],
    10000: [100800, 101100, 300500, 301100, 400500, 401100],
    8000: [100000, 100100, 100900, 300900, 301700, 400900],
    7000: [101900, 301900, 401900],
    6000: [101000, 200700, 301000, 401000],
    5000: [100500, 201200, 201400],
    4000: [200200, 200400],
    3500: [301200, 401200],
    3000: [100700, 201800, 202000, 300400, 300700, 400400, 400700],
    2500: [101400, 301400, 401400],
    2000: [100200, 100400, 200000, 200100, 300200, 400200],
    1500: [102000, 102100, 200300, 200600, 301800, 302000, 401800, 402000],
    1200: [300600, 400600],
    1000: [100600, 202100, 300000, 300100, 400000, 400100],
    800: [300300, 400300],
    500: [100300, 101800, 302100, 402100],
}.items() for i in ids}
# Rings: 5,000 (no use in a rush) to 30,000; the Ring of Avarice keeps its 50,000.
RING_PRICE = {i: p for p, ids in {
    50000: [120],
    30000: [104, 105, 106],
    25000: [109],
    20000: [102, 111, 112, 123, 124],
    15000: [100, 103],
    8000: [101, 107, 116, 121, 125, 126],
    5000: [108, 110, 113, 114, 115, 117, 118, 119],
}.items() for i in ids}
BOLDWIN_SELLS = (10000, 20000, 50000, 150300, 160000, 170000)   # his own weapon rows
BOLDWIN_WEAPONS = [(i, WEAPON_PRICE[i]) for i in [
    10000, 10100, 10200, 10400, 10500, 10600, 10700, 20000, 20100, 20200, 20300, 20400, 20500, 20600, 20700, 20800,
    20900, 21000, 21100, 21300, 21400, 21500, 21600, 21700, 21800, 21900, 30000, 30100, 30200, 30300, 30400, 40000,
    40100, 40200, 40300, 40400, 40500, 40600, 40700, 40900, 50000, 50200, 50300, 50400, 50500, 60000, 60100, 60200,
    60300, 60400, 60500, 60600, 60700, 70000, 70100, 70300, 70400, 80000, 80100, 80200, 80300, 90000, 90100,
    90200, 90400, 90500, 100000, 100100, 100200, 130000, 130100, 130200, 130300, 130400, 130500, 140000, 140100,
    140200, 150000, 150100, 150200, 150300, 150400, 150500, 150600, 150700, 150800, 150900, 151000, 151100, 151200,
    151300, 151400, 151500, 160000, 160100, 160200, 160400, 160500, 160600, 160700, 160800, 170000, 170100, 170200,
    170300] if i not in BOLDWIN_SELLS]
# Armour (equip type 1): every wearable piece -- helms 1xxxxx, armour 2xxxxx, gauntlets 3xxxxx, leggings 4xxxxx --
# minus "No Equipment", the roaming black phantoms' sets (x9xxxx) and the Old Monk's head wrappings (180000).
# Rings (type 2): every named ring (100-126; 0 is a test entry).
BOLDWIN_ARMOUR = [(i, ARMOUR_PRICE[i]) for i in [
    100000, 100100, 100200, 100300, 100400, 100500, 100600, 100700, 100800, 100900, 101000, 101100, 101400, 101800,
    101900, 102000, 102100, 200000, 200100, 200200, 200300, 200400, 200500, 200600, 200700, 200800, 200900, 201000,
    201100, 201200, 201400, 201800, 201900, 202000, 202100, 300000, 300100, 300200, 300300, 300400, 300500, 300600,
    300700, 300800, 300900, 301000, 301100, 301200, 301400, 301700, 301800, 301900, 302000, 302100, 400000, 400100,
    400200, 400300, 400400, 400500, 400600, 400700, 400800, 400900, 401000, 401100, 401200, 401400, 401800, 401900,
    402000, 402100]]
BOLDWIN_RINGS = [(i, RING_PRICE[i]) for i in list(range(100, 122)) + list(range(123, 127))]
TALK_BOLDWIN = 't0694.esd'


def soul_mult():
    """DES_BR_SOULS: the launcher's boss rush souls choice (1-100; 1 = the game's own)."""
    try:
        m = int(os.environ.get('DES_BR_SOULS', '1') or 1)
    except ValueError:
        m = 1
    return max(1, min(100, m))
G_INIT_END = b'print("g_Initialize global_event end");'


def rd(p):
    with open(p, 'rb') as f:
        return f.read()


def stamp_text():
    h = hashlib.sha256(rd(MODULE) + rd(os.path.abspath(__file__))).hexdigest()
    return 'built by tools/make_boss_rush.py from game/\n' + h + '\nsouls x%d\n' % soul_mult()


def is_current(dst):
    p = os.path.join(dst, STAMP)
    return os.path.isfile(p) and rd(p).decode() == stamp_text() and os.path.isfile(FONT_OUT)


# The timer's glyphs (project/ds_boss_rush.cpp draws the clock with them): the game's own font at FONT_PX a cell.
# 'BRF1', u32 count, u32 cell height, then per glyph: u32 code, i32 pre, i32 advance, u32 w, u32 h, w*h
# (luminance, alpha) byte pairs (the font's glyphs are white with a darker outline; the luminance keeps it).
FONT_OUT = os.path.join(ROOT, 'bossrush', 'timer_font.bin')
FONT_PX = 64
FONT_CHARS = "0123456789:.+-'()/ ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def timer_font(usrdir, out=FONT_OUT):
    import kbm_icons as k
    from PIL import Image
    k.U = usrdir
    k.load_font()
    cell = max(k.glyph(c)[0].height for c in '0AMg')
    sc = FONT_PX / float(cell)
    recs = []
    for ch in FONT_CHARS:
        if ord(ch) not in k.FONT_DATA['cmap']:
            if ch == ' ':
                adv = k.glyph('n')[2]
                recs.append(struct.pack('<IiiII', 32, 0, int(round(adv * sc)), 0, 0))
            continue
        im, pre, adv = k.glyph(ch)
        w, h = max(1, int(round(im.width * sc))), max(1, int(round(im.height * sc)))
        im = im.convert('RGBA').resize((w, h), Image.LANCZOS)
        lum = im.convert('L').tobytes()
        alp = im.getchannel('A').tobytes()
        recs.append(struct.pack('<IiiII', ord(ch), int(round(pre * sc)), int(round(adv * sc)), w, h) +
                    bytes(b for pair in zip(lum, alp) for b in pair))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'wb') as f:
        f.write(b'BRF1' + struct.pack('<II', len(recs), int(round(cell * sc))) + b''.join(recs))
    return len(recs)


# --- the files -------------------------------------------------------------------------------------------

def bnd_entry(bnd, suffix=None, eid=None):
    hits = [e for e in bnd.entries if (eid is not None and e['id'] == eid) or
            (suffix and e['name'] and e['name'].lower().replace('/', '\\').endswith(suffix.lower()))]
    assert len(hits) == 1, (suffix, eid, len(hits))
    return hits[0]


def script_bundle(src):
    """mXX.luabnd.dcx -> the .sdat the game opens (a plain DCX there is fine, as the game_dbg trees use)."""
    raw, info = sf.dcx_decompress(src)
    bnd = sf.Bnd3(raw)
    e = bnd_entry(bnd, '\\global_event.lua')
    ge = e['data']
    nl = b'\r\n' if b'\r\n' in ge else b'\n'
    assert ge.count(G_INIT_END) == 1, 'global_event.lua: the end of g_Initialize not found once'
    mod = rd(MODULE).replace(b'\r\n', b'\n').replace(b'\n', nl)
    e['data'] = ge.replace(G_INIT_END, b'BR_MapLoad(proxy);' + nl + G_INIT_END) + nl + mod
    out = sf.dcx_compress(bnd.write(), info)
    back = sf.Bnd3(sf.dcx_decompress(out)[0])
    assert bnd_entry(back, '\\global_event.lua')['data'] == e['data']
    return out


def msb_lists(b):
    o, out = 0, {}
    while True:
        _, no, cnt = struct.unpack_from('>III', b, o)
        name = b[no:b.index(b'\0', no)].decode('ascii', 'replace')
        offs = [struct.unpack_from('>I', b, o + 12 + 4 * i)[0] for i in range(cnt)]
        out[name] = offs[:-1]
        if offs[-1] == 0:
            return out
        o = offs[-1]


def msb_points(b, wants):
    """Move warp points (player parts, type 4) onto fog regions. Part: +0x04 type, +0x14 position, +0x20 rotation
    (degrees), +0x58 -> base data whose first word is the entity id. Region: +0x10 position, +0x1C rotation,
    +0x34 -> the entity id."""
    b = bytearray(b)
    L = msb_lists(b)
    parts = {}
    for r in L['PARTS_PARAM_ST']:
        if struct.unpack_from('>i', b, r + 4)[0] == 4:
            parts[struct.unpack_from('>i', b, r + struct.unpack_from('>I', b, r + 0x58)[0])[0]] = r
    regions = {}
    for r in L['POINT_PARAM_ST']:
        eo = struct.unpack_from('>I', b, r + 0x34)[0]
        if eo:
            regions[struct.unpack_from('>i', b, r + eo)[0]] = r
    for key, pt, fog in wants:
        p, f = parts[pt], regions[fog]
        x, y, z = struct.unpack_from('>3f', b, f + 0x10)
        ry = struct.unpack_from('>3f', b, f + 0x1C)[1]
        y += 0.5   # just above the floor
        if key in ON_ELEVATOR:
            x, y, z, ry = ON_ELEVATOR[key]
        struct.pack_into('>3f', b, p + 0x14, x, y, z)
        struct.pack_into('>3f', b, p + 0x20, 0.0, ry, 0.0)
    return bytes(b)


def fmg_strings(f):
    ng, ns, soff = struct.unpack_from('>III', f, 0xC)
    out = {}
    for g in range(ng):
        fi, a, z = struct.unpack_from('>iii', f, 0x1C + 12 * g)
        for k in range(z - a + 1):
            o = struct.unpack_from('>I', f, soff + 4 * (fi + k))[0]
            if o:
                e = o
                while f[e:e + 2] != b'\0\0':
                    e += 2
                out[a + k] = f[o:e].decode('utf-16-be')
            else:
                out[a + k] = None
    return out


def fmg_set(f, texts):
    """Fill empty slots of a (big-endian) FMG: string offset table at +0x14, groups {first index, first id,
    last id} at +0x1C, file size at +4; the new strings go at the end."""
    f = bytearray(f)
    ng, ns, soff = struct.unpack_from('>III', f, 0xC)
    for tid, text in texts.items():
        idx = None
        for g in range(ng):
            fi, a, z = struct.unpack_from('>iii', f, 0x1C + 12 * g)
            if a <= tid <= z:
                idx = fi + tid - a
        assert idx is not None and struct.unpack_from('>I', f, soff + 4 * idx)[0] == 0, ('text slot not empty', tid)
        while len(f) % 4:
            f += b'\0'
        struct.pack_into('>I', f, soff + 4 * idx, len(f))
        f += text.encode('utf-16-be') + b'\0\0'
    while len(f) % 4:
        f += b'\0'
    struct.pack_into('>I', f, 4, len(f))
    return bytes(f)


def fmg_replace(f, texts):
    """Point existing (big-endian) FMG strings at new text, appended at the end; the old text stays, unused."""
    f = bytearray(f)
    ng, ns, soff = struct.unpack_from('>III', f, 0xC)
    for tid, text in texts.items():
        idx = None
        for g in range(ng):
            fi, a, z = struct.unpack_from('>iii', f, 0x1C + 12 * g)
            if a <= tid <= z:
                idx = fi + tid - a
        assert idx is not None and struct.unpack_from('>I', f, soff + 4 * idx)[0] != 0, ('no text to replace', tid)
        while len(f) % 4:
            f += b'\0'
        struct.pack_into('>I', f, soff + 4 * idx, len(f))
        f += text.encode('utf-16-be') + b'\0\0'
    while len(f) % 4:
        f += b'\0'
    struct.pack_into('>I', f, 4, len(f))
    return bytes(f)


# The Nexial Binding's item texts (MSG/NA_ENGLISH/item.msgbnd): it keeps your souls in boss rush (nexial_binding).
# The game's own texts are checked by their SHA-256 only -- nothing of the disc goes into this repository. FMG 20
# (the one-line description) is replaced; FMG 24 (the story) keeps its first paragraph, read from your game files
# at build time, and gets our second paragraph in place of the game's.
NEXIAL_OLD_SHA = {20: 'e81f4cdaa1cee779828803fa108648c8107d48e5d00c4a243c3b75f1e4e562b5',
                  24: '796e3d4dc554e02d8241674cdcdfa2252eafdbc52aaf464a732b8f192c05c225'}
NEXIAL_LINE = 'Return to the Nexus, keeping all Souls'
NEXIAL_STORY_END = 'In a boss rush it takes you back to the Nexus\nwith every Soul you carry.'


def nexial_texts(old):
    """{fmg id: new text} from the game's own {fmg id: text}."""
    return {20: NEXIAL_LINE, 24: old[24].split('\n\n')[0] + '\n\n' + NEXIAL_STORY_END}


def item_msg(raw_plain):
    """Item texts: the Nexial Binding's (goods 1033) description (FMG 20) and story (FMG 24) say it keeps souls."""
    bnd = sf.Bnd3(raw_plain)
    old = {fid: fmg_strings(bnd_entry(bnd, eid=fid)['data']) for fid in NEXIAL_OLD_SHA}
    for fid, sha in NEXIAL_OLD_SHA.items():
        assert old[fid].get(1033) and hashlib.sha256(old[fid][1033].encode('utf-8')).hexdigest() == sha, \
            ('not the tested item texts (NA English)', fid)
    for fid, text in nexial_texts({k: v[1033] for k, v in old.items()}).items():
        e = bnd_entry(bnd, eid=fid)
        e['data'] = fmg_replace(e['data'], {1033: text})
        new = fmg_strings(e['data'])
        assert new[1033] == text and all(new[k] == v for k, v in old[fid].items() if k != 1033)
    return bnd.write()


def menu_msg(raw_plain):
    bnd = sf.Bnd3(raw_plain)
    e = bnd_entry(bnd, eid=30)                     # event texts
    old = fmg_strings(e['data'])
    assert old.get(10010710) == 'Return to the Nexus?', 'not the tested event texts (NA English)'
    e['data'] = fmg_set(e['data'], TEXTS)
    new = fmg_strings(e['data'])
    assert all(new[k] == v for k, v in TEXTS.items()) and all(new[k] == v for k, v in old.items() if k not in TEXTS)
    return bnd.write()


def param_add_row(b, new_id, from_id, size=32):
    """A DeS PARAM (big-endian): u32 at 0, u16 data start at 0x4, u16 row count at 0xA, rows (id, data offset,
    name offset) from 0x30 sorted by id, padding, the row data, the names. One row added (a copy of from_id)."""
    n = struct.unpack_from('>H', b, 0xA)[0]
    rows = [struct.unpack_from('>III', b, 0x30 + 12 * i) for i in range(n)]
    ids = [r[0] for r in rows]
    assert new_id not in ids and from_id in ids
    table_end = 0x30 + 12 * n
    data_start = struct.unpack_from('>H', b, 0x4)[0]
    assert data_start >= table_end
    data_end = min(r[2] for r in rows)
    assert all(r[1] + size <= data_end for r in rows)
    src = [r for r in rows if r[0] == from_id][0]
    new_name = b[src[2]:b.index(b'\0', src[2]) + 1]

    def mv(o):
        return o + 12 + (size if o >= data_end else 0)

    head = bytearray(b[:0x30])
    struct.pack_into('>I', head, 0, mv(struct.unpack_from('>I', b, 0)[0]))
    struct.pack_into('>H', head, 0x4, data_start + 12)
    struct.pack_into('>H', head, 0xA, n + 1)
    table = sorted([(r[0], mv(r[1]), mv(r[2])) for r in rows] + [(new_id, data_end + 12, len(b) + 12 + size)])
    out = bytes(head) + b''.join(struct.pack('>III', *t) for t in table) + \
        b[table_end:data_end] + b[src[1]:src[1] + size] + b[data_end:] + new_name
    return out


def shops(raw_plain):
    bnd = sf.Bnd3(raw_plain)
    e = bnd_entry(bnd, '\\shoplineupparam.param')
    old = e['data']
    new = param_add_row(old, 9009, 1002)
    row = lambda b, rid: [struct.unpack_from('>III', b, 0x30 + 12 * i) for i in range(struct.unpack_from('>H', b, 0xA)[0])
                          if struct.unpack_from('>I', b, 0x30 + 12 * i)[0] == rid][0]
    r = row(new, 9009)
    assert new[r[1] + 1] == 3 and struct.unpack_from('>i', new, r[1] + 4)[0] == 1013, 'row 9009 is not Firebombs'
    have = {k: set(param_ids(bnd_entry(bnd, '\\' + k + '.param')['data']))
            for k in ('equipparamgoods', 'equipparamweapon', 'equipparamprotector', 'equipparamaccessory')}
    rid = SHOP_FIRST_ROW
    table_of = {0: 'equipparamweapon', 1: 'equipparamprotector', 2: 'equipparamaccessory', 3: 'equipparamgoods'}
    for kind, template, items in ((3, 9000, BOLDWIN_GOODS), (0, 9003, BOLDWIN_WEAPONS), (1, 9003, BOLDWIN_ARMOUR),
                                  (2, 9003, BOLDWIN_RINGS)):
        for item, price in items:
            assert item in have[table_of[kind]], ('no such item', kind, item)
            new = param_add_row(new, rid, template)
            d = row(new, rid)[1]
            assert new[d + 1] == 0 or new[d + 1] == kind   # a weapon row as the armour / ring template
            new = new[:d + 1] + bytes([kind]) + new[d + 2:d + 4] + struct.pack('>ii', item, price) + new[d + 12:]
            rid += 1
    assert rid - 1 <= SHOP_LAST_ROW
    e['data'] = new
    nexial_binding(bnd)
    souls(bnd, soul_mult())
    return bnd.write()


def souls(bnd, m):
    """The souls an enemy gives (NpcParam +0x3C: a slave soldier 2, a knight 51, a crystal lizard 105) and a boss
    (GameAreaParam, one row per boss: +0 and +4, e.g. Penetrator 35850) times m."""
    if m == 1:
        return
    for name, offs in (('npcparam', (0x3C,)), ('gameareaparam', (0x0, 0x4))):
        e = bnd_entry(bnd, '\\' + name + '.param')
        b = bytearray(e['data'])
        for i in range(struct.unpack_from('>H', b, 0xA)[0]):
            d = struct.unpack_from('>I', b, 0x30 + 12 * i + 4)[0]
            for o in offs:
                v = struct.unpack_from('>i', b, d + o)[0]
                if v > 0:
                    struct.pack_into('>i', b, d + o, min(v * m, 99999999))
        e['data'] = bytes(b)


def param_ids(b):
    return [struct.unpack_from('>I', b, 0x30 + 12 * i)[0] for i in range(struct.unpack_from('>H', b, 0xA)[0])]


def param_row_off(b, rid):
    for i in range(struct.unpack_from('>H', b, 0xA)[0]):
        k, d, _ = struct.unpack_from('>III', b, 0x30 + 12 * i)
        if k == rid:
            return d
    raise KeyError(rid)


def nexial_binding(bnd):
    """The Nexial Binding (goods 1033) returns you to the Nexus keeping your souls, like the miracle Evacuate:
    its effect (behavior 3110 -> SpEffectParam 3110) and Evacuate's (behavior 2008 -> SpEffectParam 1513) are the
    same row but for the word at +0x2C (1 = the souls are lost); and its yes/no box asks "Return to the Nexus?"
    (event text 10010710, Evacuate's) instead of "Forfeit all Souls and return?" (10010712; goods +0x3C)."""
    e = bnd_entry(bnd, '\\speffectparam.param')
    b = e['data']
    bind, evac = param_row_off(b, 3110), param_row_off(b, 1513)
    size = 384
    diff = [o for o in range(0, size, 4) if b[bind + o:bind + o + 4] != b[evac + o:evac + o + 4]]
    assert diff == [0x2C] and struct.unpack_from('>I', b, bind + 0x2C)[0] == 1, 'not the tested SpEffect rows'
    e['data'] = b[:bind + 0x2C] + b'\0\0\0\0' + b[bind + 0x30:]
    g = bnd_entry(bnd, '\\equipparamgoods.param')
    d = param_row_off(g['data'], 1033)
    assert struct.unpack_from('>I', g['data'], d + 0x14)[0] == 3110, 'goods 1033 is not the Nexial Binding'
    assert struct.unpack_from('>i', g['data'], d + 0x3C)[0] == 10010712, 'not the tested goods row'
    g['data'] = g['data'][:d + 0x3C] + struct.pack('>i', 10010710) + g['data'][d + 0x40:]


def talk_shop_range(src):
    """m01.talkesdbnd.dcx -> the .sdat the game opens: in Boldwin's t0694.esd the shop's last row 9099 (an int
    literal: 0x82 + little-endian int32, there once) becomes SHOP_LAST_ROW."""
    raw, info = sf.dcx_decompress(src)
    bnd = sf.Bnd3(raw)
    e = bnd_entry(bnd, '\\' + TALK_BOLDWIN)
    lit = lambda v: b'\x82' + struct.pack('<i', v)
    assert e['data'].count(lit(9099)) == 1 and e['data'].count(lit(9000)) == 1, 'not the tested t0694.esd'
    e['data'] = e['data'].replace(lit(9099), lit(SHOP_LAST_ROW))
    out = sf.dcx_compress(bnd.write(), info)
    assert bnd_entry(sf.Bnd3(sf.dcx_decompress(out)[0]), '\\' + TALK_BOLDWIN)['data'] == e['data']
    return out


# --- the folder ------------------------------------------------------------------------------------------

def link_tree(src, dst):
    for d, _, fs in os.walk(src):
        t = os.path.join(dst, os.path.relpath(d, src))
        os.makedirs(t, exist_ok=True)
        for f in fs:
            tp = os.path.join(t, f)
            if os.path.exists(tp):
                continue
            try:
                os.link(os.path.join(d, f), tp)
            except OSError:
                shutil.copy2(os.path.join(d, f), tp)


def put(dst, rel, data):
    """Replace one file of the copy: remove it first (a hard link shared with game/), then write."""
    before = rd(os.path.join(GAME, rel)) if os.path.isfile(os.path.join(GAME, rel)) else None
    p = os.path.join(dst, rel)
    if os.path.exists(p):
        os.remove(p)
    with open(p, 'wb') as f:
        f.write(data)
    if before is not None:
        assert rd(os.path.join(GAME, rel)) == before, 'game/ changed: ' + rel


def build(dst):
    if not os.path.isdir(os.path.join(GAME, USR)):
        sys.exit('no game/ yet -- run SETUP.bat first')
    if os.path.isfile(os.path.join(dst, STAMP)):
        os.remove(os.path.join(dst, STAMP))
    print('  game_bossrush: hard links to game/ ...')
    link_tree(GAME, dst)
    sd = os.path.join(USR, 'SCRIPT')
    for m in SCRIPT_BUNDLES:
        put(dst, os.path.join(sd, m + '.luabnd.dcx.sdat'), script_bundle(rd(os.path.join(GAME, sd, m + '.luabnd.dcx'))))
    print('  event scripts: the boss rush module in %d bundles' % len(SCRIPT_BUNDLES))
    by_map = {}
    for m, pt, fog in POINTS:
        by_map.setdefault(m, []).append(((m, pt), pt, fog))
    for m, wants in by_map.items():
        rel = os.path.join(USR, 'MAP', 'MAPSTUDIO', m + '.msb')
        put(dst, rel, msb_points(rd(os.path.join(GAME, rel)), wants))
    print('  maps: %d boss warp points on their fog gates' % len(POINTS))
    mrel = os.path.join(USR, 'MSG', 'NA_ENGLISH', 'menu.msgbnd')
    plain, info = sf.dcx_decompress(rd(os.path.join(GAME, mrel + '.dcx')))
    new = menu_msg(plain)
    put(dst, mrel + '.dcx', sf.dcx_compress(new, info))
    if os.path.isfile(os.path.join(GAME, mrel)):
        put(dst, mrel, new)
    print('  texts: %d added' % len(TEXTS))
    irel = os.path.join(USR, 'MSG', 'NA_ENGLISH', 'item.msgbnd')
    plain, info = sf.dcx_decompress(rd(os.path.join(GAME, irel + '.dcx')))
    new = item_msg(plain)
    put(dst, irel + '.dcx', sf.dcx_compress(new, info))
    if os.path.isfile(os.path.join(GAME, irel)):
        put(dst, irel, new)
    print("  item texts: the Nexial Binding's description says it keeps your souls")
    prel = os.path.join(USR, 'PARAM', 'GAMEPARAM', 'gameparamna.parambnd')
    plain, info = sf.dcx_decompress(rd(os.path.join(GAME, prel + '.dcx')))
    new = shops(plain)
    put(dst, prel + '.dcx', sf.dcx_compress(new, info))
    if os.path.isfile(os.path.join(GAME, prel)):
        put(dst, prel, new)
    print('  shops: Boldwin sells Firebombs, Turpentine, %d upgrade materials, %d more weapons, %d armour pieces and '
          '%d rings' % (len(BOLDWIN_GOODS) - 1, len(BOLDWIN_WEAPONS), len(BOLDWIN_ARMOUR), len(BOLDWIN_RINGS)))
    print('  souls: x%d' % soul_mult())
    print('  items: the Nexial Binding keeps your souls')
    trel = os.path.join(USR, 'SCRIPT', 'TALK', 'm01.talkesdbnd.dcx')
    put(dst, trel + '.sdat', talk_shop_range(rd(os.path.join(GAME, trel))))
    print("  talk: Boldwin's shop lists rows 9000-%d" % SHOP_LAST_ROW)
    n = timer_font(os.path.join(GAME, USR))
    print('  timer: %d letters from the game\'s font' % n)
    with open(os.path.join(dst, STAMP), 'w', newline='\n') as f:
        f.write(stamp_text())


if __name__ == '__main__':
    if '--check' in sys.argv:
        tmp = tempfile.mkdtemp(prefix='bossrush_check_', dir=ROOT)
        try:
            build(tmp)
            print('check ok (built in a temporary folder, removed)')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        dst = os.path.join(ROOT, 'game_bossrush')
        if is_current(dst):
            print('  game_bossrush is up to date')
        else:
            build(dst)
            print('  game_bossrush ready')
