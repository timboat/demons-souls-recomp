// DemonsSoulsLauncher.app -- one window for the play options of the Demon's Souls port on macOS.
// The Mac counterpart of project/launcher/launcher.cpp (DemonsSoulsLauncher.exe): the same window, the
// same launcher.ini next to the port, the same Controls window and the same four buttons.
//
// It keeps the choices in launcher.ini in the port's folder, sets the environment variables
// mac/play.sh reads (DES_FPS, DES_GAME, DES_SIZE, ...) and runs mac/play.sh with them, so the window
// and mac/play.sh on its own always start the game the same way. A crash is reported here, with an
// offer to pack a report.
//
//   DemonsSoulsLauncher.app                                         the window
//   DemonsSoulsLauncher.app/Contents/MacOS/DemonsSoulsLauncher --play
//                                                                    starts the game with the saved settings
//
// Only what the Mac build has is offered: no resolution scale, texture dump, frame-timing recording
// or rates other than 60 / 30 yet (docs/MACOS.md). launcher.ini keeps the Windows launcher's keys and
// values where both have the setting, and [controls] is the same on both.
//
// Plain AppKit, nothing to install. mac/launcher_native/build.sh builds it (mac/rebuild.sh's build
// step runs that) into DemonsSoulsLauncher.app in the port's folder.
//
// For tests: DES_LAUNCHER_INI=<file> moves launcher.ini; --snapshot <png> / --snapshot-controls <png>
// draw the window into a file and quit; --report-only makes the report zip and prints its path.
#import <Cocoa/Cocoa.h>
#include <sys/sysctl.h>

static NSString* g_root;      // the port's folder (the one holding mac/play.sh)
static NSString* g_ini_path;
static NSString* const kIssues = @"https://github.com/timboat/demons-souls-recomp/issues/new/choose";
static NSString* const kReleases = @"https://github.com/timboat/demons-souls-recomp/releases";

static NSString* at(NSString* rel) { return [g_root stringByAppendingPathComponent:rel]; }
static BOOL exists(NSString* p) { return [NSFileManager.defaultManager fileExistsAtPath:p]; }

// The bundle sits in the port's folder (where build.sh puts it); a copy elsewhere is given DES_ROOT.
static BOOL find_root(void) {
    NSMutableArray<NSString*>* starts = [NSMutableArray array];
    const char* e = getenv("DES_ROOT");
    if (e && *e) [starts addObject:@(e)];
    [starts addObject:NSBundle.mainBundle.bundlePath];
    [starts addObject:NSFileManager.defaultManager.currentDirectoryPath];
    for (NSString* s in starts) {
        NSString* d = s.stringByStandardizingPath;
        for (int up = 0; up < 5 && d.length > 1; up++) {
            if (exists([d stringByAppendingPathComponent:@"mac/play.sh"])) { g_root = d; return YES; }
            d = d.stringByDeletingLastPathComponent;
        }
    }
    return NO;
}

// ---------------------------------------------------------------------------------------------
// launcher.ini: [section] key=value lines. Keys this launcher does not know (the Windows launcher's)
// are kept as they are.
// ---------------------------------------------------------------------------------------------
@interface Ini : NSObject
@property NSMutableArray<NSString*>* order;                                       // section names
@property NSMutableDictionary<NSString*, NSMutableArray<NSString*>*>* keys;       // section -> key order
@property NSMutableDictionary<NSString*, NSMutableDictionary<NSString*, NSString*>*>* vals;
@end
@implementation Ini
- (instancetype)init {
    if ((self = [super init])) { _order = [NSMutableArray array]; _keys = [NSMutableDictionary dictionary]; _vals = [NSMutableDictionary dictionary]; }
    return self;
}
+ (Ini*)load:(NSString*)path {
    Ini* ini = [Ini new];
    NSData* d = [NSData dataWithContentsOfFile:path];
    if (!d.length) return ini;
    const unsigned char* b = d.bytes;
    BOOL utf16 = d.length >= 2 && ((b[0] == 0xFF && b[1] == 0xFE) || (b[0] == 0xFE && b[1] == 0xFF));   // the Windows file
    NSString* text = [[NSString alloc] initWithData:d encoding:utf16 ? NSUTF16StringEncoding : NSUTF8StringEncoding];
    if (!text) text = [[NSString alloc] initWithData:d encoding:NSISOLatin1StringEncoding];
    NSString* sec = nil;
    for (NSString* raw in [text componentsSeparatedByCharactersInSet:NSCharacterSet.newlineCharacterSet]) {
        NSString* l = [raw stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
        if (!l.length || [l hasPrefix:@";"] || [l hasPrefix:@"#"]) continue;
        if ([l hasPrefix:@"["] && [l hasSuffix:@"]"]) { sec = [l substringWithRange:NSMakeRange(1, l.length - 2)]; continue; }
        NSRange eq = [l rangeOfString:@"="];
        if (!sec || eq.location == NSNotFound || eq.location == 0) continue;
        NSString* k = [[l substringToIndex:eq.location] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
        NSString* v = [[l substringFromIndex:eq.location + 1] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
        [ini set:sec key:k value:v];
    }
    return ini;
}
- (NSString*)get:(NSString*)sec key:(NSString*)k { return _vals[sec][k]; }
- (void)set:(NSString*)sec key:(NSString*)k value:(NSString*)v {
    if (!_vals[sec]) { [_order addObject:sec]; _keys[sec] = [NSMutableArray array]; _vals[sec] = [NSMutableDictionary dictionary]; }
    if (!_vals[sec][k]) [_keys[sec] addObject:k];
    _vals[sec][k] = v;
}
- (BOOL)save:(NSString*)path {
    NSMutableString* s = [NSMutableString string];
    for (NSString* sec in _order) {
        [s appendFormat:@"[%@]\n", sec];
        for (NSString* k in _keys[sec]) [s appendFormat:@"%@=%@\n", k, _vals[sec][k]];
    }
    return [s writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
}
@end

// ---------------------------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------------------------
// fps keeps the Windows launcher's numbers (0 Auto, 1 30, 2 50, 3 60, 4 Unlimited, 5 Custom); the Mac
// build has 60 and 30, so everything but 1 is 60 here and is left as it was in the file unless changed.
enum { FPS_30 = 1, FPS_60 = 3 };
static NSString* const GAME_DIRS[3] = {@"game", @"game_remaster", @"game_mod"};
static NSString* const SIZES[] = {@"1280x720", @"1600x900", @"1920x1080", @"2560x1440", @"fit"};
enum { N_SIZES = 5 };
static NSString* const INPUT_MODES[] = {@"both", @"controller", @"keyboard"};

typedef struct {
    int fps, size, game, input;
    BOOL movies, god, skip_intro, log;
} Settings;
static Settings g_set;
static NSString* g_name = @"";    // DES_NAME
static NSString* g_extra = @"";   // NAME=value NAME=value ...
static Ini* g_ini;

// Key bindings: launcher.ini [controls] <action>=<KEY>[+<KEY>], the Windows launcher's action and key
// names (no line = the default, empty = unbound), so tools/kbm_icons.py draws the same button icons
// from them. The game gets them as a PS3_INPUT_MAP file written before Play (write_input_map).
typedef struct { const char* name; const char* label; const char* def; const char* ps3; } Action;
static const Action ACTIONS[] = {
    {"move_forward", "Move forward", "W", "ls_up"}, {"move_back", "Move back", "S", "ls_down"},
    {"move_left", "Move left", "A", "ls_left"}, {"move_right", "Move right", "D", "ls_right"},
    {"camera_up", "Camera up", "I", "rs_up"}, {"camera_down", "Camera down", "K", "rs_down"},
    {"camera_left", "Camera left", "J", "rs_left"}, {"camera_right", "Camera right", "L", "rs_right"},
    {"attack", "Attack (R1)", "LMB", "r1"}, {"strong_attack", "Strong attack (R2)", "SHIFT", "r2"},
    {"block", "Block (L1)", "RMB", "l1"}, {"parry", "Parry (L2)", "CTRL", "l2"},
    {"roll", "Roll / back (Circle)", "SPACE", "circle"}, {"interact", "Interact (Cross)", "E", "cross"},
    {"two_hand", "Two-hand (Triangle)", "F", "triangle"}, {"use_item", "Use item (Square)", "R", "square"},
    {"lock_on", "Lock on (R3)", "TAB+MMB", "r3"}, {"l3", "L3", "C", "l3"},
    {"dpad_up", "D-pad up", "UP", "up"}, {"dpad_down", "D-pad down", "DOWN", "down"},
    {"dpad_left", "D-pad left", "LEFT", "left"}, {"dpad_right", "D-pad right", "RIGHT", "right"},
    {"start", "Start (menu)", "ENTER", "start"}, {"select", "Select", "BACK", "select"},
};
enum { N_ACTIONS = (int)(sizeof ACTIONS / sizeof *ACTIONS) };
static NSString* g_keys[N_ACTIONS][2];   // key names; @"" = none
static BOOL g_keys_custom;               // launcher.ini has a [controls] section

// name = the Windows launcher's key name, code = the Mac key code (-1: a mouse button), toml = its name
// in libs/input/pad_input_map.h, label = what a slot shows.
typedef struct { const char* name; int code; const char* toml; const char* label; } KeyDef;
static const KeyDef KEYDEFS[] = {
    {"A", 0x00, "A", 0}, {"S", 0x01, "S", 0}, {"D", 0x02, "D", 0}, {"F", 0x03, "F", 0}, {"H", 0x04, "H", 0},
    {"G", 0x05, "G", 0}, {"Z", 0x06, "Z", 0}, {"X", 0x07, "X", 0}, {"C", 0x08, "C", 0}, {"V", 0x09, "V", 0},
    {"B", 0x0B, "B", 0}, {"Q", 0x0C, "Q", 0}, {"W", 0x0D, "W", 0}, {"E", 0x0E, "E", 0}, {"R", 0x0F, "R", 0},
    {"Y", 0x10, "Y", 0}, {"T", 0x11, "T", 0}, {"1", 0x12, "1", 0}, {"2", 0x13, "2", 0}, {"3", 0x14, "3", 0},
    {"4", 0x15, "4", 0}, {"6", 0x16, "6", 0}, {"5", 0x17, "5", 0}, {"9", 0x19, "9", 0}, {"7", 0x1A, "7", 0},
    {"8", 0x1C, "8", 0}, {"0", 0x1D, "0", 0}, {"O", 0x1F, "O", 0}, {"U", 0x20, "U", 0}, {"I", 0x22, "I", 0},
    {"P", 0x23, "P", 0}, {"L", 0x25, "L", 0}, {"J", 0x26, "J", 0}, {"K", 0x28, "K", 0}, {"N", 0x2D, "N", 0},
    {"M", 0x2E, "M", 0},
    {"SHIFT", 0x38, "Shift", "Shift"}, {"RSHIFT", 0x3C, "RightShift", "Right Shift"},
    {"CTRL", 0x3B, "Control", "Control"}, {"RCTRL", 0x3E, "RightControl", "Right Control"},
    {"ALT", 0x3A, "Option", "Option"}, {"RALT", 0x3D, "RightOption", "Right Option"},
    {"SPACE", 0x31, "Space", "Space"}, {"TAB", 0x30, "Tab", "Tab"}, {"ENTER", 0x24, "Return, KeypadEnter", "Return"},
    {"ENTER", 0x4C, "Return, KeypadEnter", "Return"}, {"BACK", 0x33, "Backspace", "Delete"},
    {"UP", 0x7E, "Up", "Up"}, {"DOWN", 0x7D, "Down", "Down"}, {"LEFT", 0x7B, "Left", "Left"}, {"RIGHT", 0x7C, "Right", "Right"},
    {"DEL", 0x75, "ForwardDelete", "Fwd Delete"}, {"HOME", 0x73, "Home", "Home"}, {"END", 0x77, "End", "End"},
    {"PGUP", 0x74, "PageUp", "Page Up"}, {"PGDN", 0x79, "PageDown", "Page Down"},
    {"F2", 0x78, "F2", 0}, {"F3", 0x63, "F3", 0}, {"F4", 0x76, "F4", 0}, {"F5", 0x60, "F5", 0},
    {"F6", 0x61, "F6", 0}, {"F7", 0x62, "F7", 0}, {"F10", 0x6D, "F10", 0},
    {"NUM0", 0x52, "Keypad0", "Num 0"}, {"NUM1", 0x53, "Keypad1", "Num 1"}, {"NUM2", 0x54, "Keypad2", "Num 2"},
    {"NUM3", 0x55, "Keypad3", "Num 3"}, {"NUM4", 0x56, "Keypad4", "Num 4"}, {"NUM5", 0x57, "Keypad5", "Num 5"},
    {"NUM6", 0x58, "Keypad6", "Num 6"}, {"NUM7", 0x59, "Keypad7", "Num 7"}, {"NUM8", 0x5B, "Keypad8", "Num 8"},
    {"NUM9", 0x5C, "Keypad9", "Num 9"},
    {"MINUS", 0x1B, "Minus", "-"}, {"EQUALS", 0x18, "Equal", "="}, {"LBRACKET", 0x21, "LeftBracket", "["},
    {"RBRACKET", 0x1E, "RightBracket", "]"}, {"BACKSLASH", 0x2A, "Backslash", "\\"}, {"SEMICOLON", 0x29, "Semicolon", ";"},
    {"QUOTE", 0x27, "Quote", "'"}, {"COMMA", 0x2B, "Comma", ","}, {"PERIOD", 0x2F, "Period", "."},
    {"SLASH", 0x2C, "Slash", "/"}, {"GRAVE", 0x32, "Grave", "`"},
    {"LMB", -1, "Left", "Left mouse"}, {"RMB", -1, "Right", "Right mouse"}, {"MMB", -1, "Middle", "Middle mouse"},
    {"MB4", -1, "Button4", "Mouse 4"}, {"MB5", -1, "Button5", "Mouse 5"},
};
enum { N_KEYDEFS = (int)(sizeof KEYDEFS / sizeof *KEYDEFS) };

static const KeyDef* keydef_named(NSString* name) {
    for (int i = 0; i < N_KEYDEFS; i++)
        if ([name isEqualToString:@(KEYDEFS[i].name)]) return &KEYDEFS[i];
    return NULL;
}
static NSString* key_name_of_code(int code) {   // nil = not a key the game takes
    for (int i = 0; i < N_KEYDEFS; i++)
        if (KEYDEFS[i].code == code) return @(KEYDEFS[i].name);
    return nil;
}
static NSString* key_label(NSString* name) {
    if (!name.length) return @"-";
    const KeyDef* k = keydef_named(name);
    return (k && k->label) ? @(k->label) : name;
}
static void split_keys(NSString* v, NSString* __strong out[2]) {
    out[0] = out[1] = @"";
    NSArray<NSString*>* parts = [v.uppercaseString componentsSeparatedByString:@"+"];
    int n = 0;
    for (NSString* p in parts) {
        NSString* t = [p stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
        if (t.length && n < 2 && keydef_named(t)) out[n++] = t;
    }
}
static NSString* join_keys(NSString* __strong k[2]) {
    if (!k[0].length) return k[1];
    return k[1].length ? [NSString stringWithFormat:@"%@+%@", k[0], k[1]] : k[0];
}
static void default_keys(void) {
    for (int a = 0; a < N_ACTIONS; a++) split_keys(@(ACTIONS[a].def), g_keys[a]);
}

static int ini_int(NSString* k, int def) {
    NSString* v = [g_ini get:@"launcher" key:k];
    return v.length ? v.intValue : def;
}
static void ini_put(NSString* k, NSString* v) { [g_ini set:@"launcher" key:k value:v]; }
static void ini_put_int(NSString* k, int v) { ini_put(k, [NSString stringWithFormat:@"%d", v]); }

static void load_settings(void) {
    g_ini = [Ini load:g_ini_path];
    Settings* s = &g_set;
    s->fps = ini_int(@"fps", FPS_60) == FPS_30 ? FPS_30 : FPS_60;
    s->game = MAX(0, MIN(2, ini_int(@"game", 0)));
    s->movies = ini_int(@"movies", 1) != 0;
    s->god = ini_int(@"god_mode", 0) != 0;
    s->skip_intro = ini_int(@"skip_intro", 0) != 0;
    s->log = ini_int(@"mac_log", 0) != 0;
    s->input = MAX(0, MIN(2, ini_int(@"mac_input", 0)));
    s->size = 0;
    NSString* size = [g_ini get:@"launcher" key:@"mac_window"];
    for (int i = 0; i < N_SIZES; i++)
        if ([size isEqualToString:SIZES[i]]) s->size = i;
    g_name = [g_ini get:@"launcher" key:@"mac_name"] ?: @"";
    g_extra = [g_ini get:@"launcher" key:@"extra"] ?: @"";
    g_keys_custom = g_ini.vals[@"controls"] != nil;
    for (int a = 0; a < N_ACTIONS; a++) {
        NSString* v = [g_ini get:@"controls" key:@(ACTIONS[a].name)];
        split_keys(v ?: @(ACTIONS[a].def), g_keys[a]);
    }
}

static BOOL save_settings(void) {
    const Settings* s = &g_set;
    // 60 keeps a Windows choice the Mac shows as 60 (Auto, 50, Unlimited, Custom) as it was
    int was = ini_int(@"fps", FPS_60);
    if (s->fps == FPS_30 || was == FPS_30 || ![g_ini get:@"launcher" key:@"fps"]) ini_put_int(@"fps", s->fps);
    ini_put_int(@"game", s->game);
    ini_put_int(@"movies", s->movies);
    ini_put_int(@"god_mode", s->god);
    ini_put_int(@"skip_intro", s->skip_intro);
    ini_put_int(@"mac_log", s->log);
    ini_put_int(@"mac_input", s->input);
    ini_put(@"mac_window", SIZES[s->size]);
    ini_put(@"mac_name", g_name);
    ini_put(@"extra", g_extra);
    if (g_keys_custom)
        for (int a = 0; a < N_ACTIONS; a++)
            [g_ini set:@"controls" key:@(ACTIONS[a].name) value:join_keys(g_keys[a])];
    return [g_ini save:g_ini_path];
}

static BOOL game_present(int g) {
    return exists([[g_root stringByAppendingPathComponent:GAME_DIRS[g]] stringByAppendingPathComponent:@"PS3_GAME/USRDIR/EBOOT.elf"]);
}
static NSString* exe_path(void) { return at(@"port/build_mac/DemonsSoulsRecomp"); }
static BOOL built(void) { return exists(exe_path()) && exists(at(@"port/build_mac/DemonsSoulsRecomp_window")); }
static BOOL have_ffmpeg(void) {
    if (getenv("PS3RECOMP_FFMPEG_AVCODEC")) return YES;
    for (NSString* p in @[@"/opt/homebrew/lib", @"/usr/local/lib"])
        for (NSString* f in [NSFileManager.defaultManager contentsOfDirectoryAtPath:p error:nil] ?: @[])
            if ([f hasPrefix:@"libavcodec."] && [f hasSuffix:@".dylib"]) return YES;
    return NO;
}

// "NAME=value NAME=value": the extra settings box. Names are letters, digits and _.
static BOOL parse_extra(NSString* text, NSMutableArray<NSArray<NSString*>*>* out, NSString** bad) {
    NSCharacterSet* ok = [NSCharacterSet characterSetWithCharactersInString:@"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"];
    for (NSString* tok in [text componentsSeparatedByCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet]) {
        if (!tok.length) continue;
        NSRange eq = [tok rangeOfString:@"="];
        BOOL good = eq.location != NSNotFound && eq.location > 0 &&
                    [[tok substringToIndex:eq.location] stringByTrimmingCharactersInSet:ok].length == 0;
        if (!good) { if (bad) *bad = tok; return NO; }
        [out addObject:@[[tok substringToIndex:eq.location], [tok substringFromIndex:eq.location + 1]]];
    }
    return YES;
}

// The largest 16:9 window that fits the main screen under its title bar.
static NSString* fit_size(void) {
    NSRect v = NSScreen.mainScreen.visibleFrame;
    int w = (int)MIN(v.size.width, floor((v.size.height - 32) * 16.0 / 9.0));
    w -= w % 16;
    if (w < 640) w = 640;
    return [NSString stringWithFormat:@"%dx%d", w, w * 9 / 16];
}

// The bindings as a PS3_INPUT_MAP file (libs/input/pad_input_map.h). The [mouse] section (camera,
// sensitivity, invert) is taken from mac/input.toml as it is, so edits there still count.
static NSString* write_input_map(void) {
    NSMutableString* kb = [NSMutableString stringWithString:@"[keyboard]\n"], *mb = [NSMutableString stringWithString:@"\n[mouse_buttons]\n"];
    for (int a = 0; a < N_ACTIONS; a++) {
        NSMutableArray<NSString*>* keys = [NSMutableArray array], *buttons = [NSMutableArray array];
        for (int k = 0; k < 2; k++) {
            const KeyDef* d = keydef_named(g_keys[a][k]);
            if (d) [(d->code < 0 ? buttons : keys) addObject:@(d->toml)];
        }
        if (!strcmp(ACTIONS[a].ps3, "up")) [buttons addObject:@"WheelUp"];       // the wheel moves through
        if (!strcmp(ACTIONS[a].ps3, "down")) [buttons addObject:@"WheelDown"];   // the item slots, as mac/input.toml
        [kb appendFormat:@"%-8s = \"%@\"\n", ACTIONS[a].ps3, [keys componentsJoinedByString:@", "]];
        [mb appendFormat:@"%-8s = \"%@\"\n", ACTIONS[a].ps3, [buttons componentsJoinedByString:@", "]];
    }
    NSString* mouse = @"\n[mouse]\ncamera      = true\nsensitivity = 1.0\ninvert_x    = false\ninvert_y    = false\ndeadzone    = 30\ncapture     = true\n";
    NSString* base = [NSString stringWithContentsOfFile:at(@"mac/input.toml") encoding:NSUTF8StringEncoding error:nil];
    NSRange m = base ? [base rangeOfString:@"\n[mouse]"] : NSMakeRange(NSNotFound, 0);
    if (m.location != NSNotFound) {
        NSString* rest = [base substringFromIndex:m.location + 1];
        NSRange next = [rest rangeOfString:@"\n[" options:0 range:NSMakeRange(1, rest.length - 1)];
        mouse = [@"\n" stringByAppendingString:next.location == NSNotFound ? rest : [rest substringToIndex:next.location + 1]];
    }
    NSString* text = [NSString stringWithFormat:@"# Written by DemonsSoulsLauncher.app from launcher.ini [controls] before every Play. Change the keys in the\n"
                                                @"# launcher's Controls window; the mouse settings below come from mac/input.toml.\n\n%@%@%@", kb, mb, mouse];
    NSString* path = at(@"cache/launcher_input.toml");
    [NSFileManager.defaultManager createDirectoryAtPath:at(@"cache") withIntermediateDirectories:YES attributes:nil error:nil];
    return [text writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil] ? path : nil;
}

// The environment mac/play.sh gets: the launcher's own with the choices on top. Every one is set or
// cleared, so a variable left over in this session does not change what the window says.
static NSDictionary<NSString*, NSString*>* game_env(const Settings* s) {
    NSMutableDictionary<NSString*, NSString*>* e = [NSProcessInfo.processInfo.environment mutableCopy];
    e[@"DES_FPS"] = s->fps == FPS_30 ? @"30" : @"60";
    e[@"DES_SIZE"] = [SIZES[s->size] isEqualToString:@"fit"] ? fit_size() : SIZES[s->size];
    e[@"DES_GAME"] = GAME_DIRS[s->game];
    if (s->movies) [e removeObjectForKey:@"DES_MOVIES"]; else e[@"DES_MOVIES"] = @"0";   // on = when FFmpeg is found
    if (s->god) e[@"DES_GOD"] = @"1"; else [e removeObjectForKey:@"DES_GOD"];
    if (s->skip_intro) e[@"DES_SKIP_INTRO"] = @"1"; else [e removeObjectForKey:@"DES_SKIP_INTRO"];
    if (s->log) e[@"DES_LOG"] = @"1"; else [e removeObjectForKey:@"DES_LOG"];
    e[@"PS3_INPUT_MODE"] = INPUT_MODES[s->input];
    NSString* name = [g_name stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
    if (name.length) e[@"DES_NAME"] = name; else [e removeObjectForKey:@"DES_NAME"];
    NSString* map = write_input_map();
    if (map) e[@"PS3_INPUT_MAP"] = map; else [e removeObjectForKey:@"PS3_INPUT_MAP"];
    NSMutableArray<NSArray<NSString*>*>* extra = [NSMutableArray array];
    parse_extra(g_extra, extra, NULL);
    for (NSArray<NSString*>* kv in extra) e[kv[0]] = kv[1];
    e[@"DES_LAUNCHER"] = @"1";
    return e;
}

// ---------------------------------------------------------------------------------------------
// Running things
// ---------------------------------------------------------------------------------------------
// A program run to its end; its output (stdout + stderr) in *out. NO = no start, a timeout or a non-zero exit.
static BOOL run_tool(NSString* exe, NSArray<NSString*>* args, NSDictionary* extra_env, NSTimeInterval timeout, NSString** out) {
    NSTask* t = [NSTask new];
    t.executableURL = [NSURL fileURLWithPath:exe];
    t.arguments = args;
    t.currentDirectoryURL = [NSURL fileURLWithPath:g_root];
    if (extra_env) {
        NSMutableDictionary* e = [NSProcessInfo.processInfo.environment mutableCopy];
        [e addEntriesFromDictionary:extra_env];
        t.environment = e;
    }
    NSPipe* pipe = [NSPipe pipe];
    t.standardOutput = pipe;
    t.standardError = pipe;
    t.standardInput = NSFileHandle.fileHandleWithNullDevice;
    if (![t launchAndReturnError:nil]) return NO;
    NSMutableData* data = [NSMutableData data];
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        [data appendData:[pipe.fileHandleForReading readDataToEndOfFile]];
        dispatch_semaphore_signal(done);
    });
    BOOL timed_out = dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, (int64_t)(timeout * NSEC_PER_SEC))) != 0;
    if (timed_out) { [t terminate]; dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 3 * NSEC_PER_SEC)); }
    [t waitUntilExit];
    if (out) *out = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] ?: @"";
    return !timed_out && t.terminationStatus == 0;
}

static NSString* venv_python(void) { return at(@".venv/bin/python"); }

static NSTask* start_game(const Settings* s) {
    // The keyboard / mouse button icons follow the bindings: kbm_icons.py --if-stale draws them again when they or
    // its art changed (a few seconds), else returns at once. No Python environment: the icons stay as they are.
    if (exists(venv_python()) && exists(at(@"tools/kbm_icons.py")) && exists(at(@"game/PS3_GAME/USRDIR")))
        run_tool(venv_python(), @[at(@"tools/kbm_icons.py"), at(@"game/PS3_GAME/USRDIR"), at(@"textures/kbm"), @"--if-stale"], nil, 60, NULL);
    NSTask* t = [NSTask new];
    t.executableURL = [NSURL fileURLWithPath:@"/bin/sh"];
    t.arguments = @[at(@"mac/play.sh")];
    t.currentDirectoryURL = [NSURL fileURLWithPath:g_root];
    t.environment = game_env(s);
    t.standardInput = NSFileHandle.fileHandleWithNullDevice;
    t.standardOutput = NSFileHandle.fileHandleWithNullDevice;
    t.standardError = NSFileHandle.fileHandleWithNullDevice;
    return [t launchAndReturnError:nil] ? t : nil;
}

static NSString* sysctl_string(const char* name) {
    char buf[256] = {0};
    size_t n = sizeof buf - 1;
    return sysctlbyname(name, buf, &n, NULL, 0) == 0 ? @(buf) : @"?";
}
static NSString* log_dir(void) {
    const char* e = getenv("DES_LOG_DIR");
    return (e && *e) ? @(e) : at(@"logs");
}

// Packs the last run (the two logs' first and last lines, this Mac, the port's version, the settings)
// into logs/report_<date>.zip. The user's name and home folder are taken out of everything.
static NSString* make_report(NSString** why) {
    NSString* err = [log_dir() stringByAppendingPathComponent:@"last_run_err.txt"];
    if (!exists(err)) { if (why) *why = @"There is no log yet: play once first (logs/last_run_err.txt)."; return nil; }
    NSDateFormatter* f = [NSDateFormatter new];
    f.dateFormat = @"yyyyMMdd_HHmmss";
    NSString* stamp = [f stringFromDate:NSDate.date];
    NSString* dir = [NSTemporaryDirectory() stringByAppendingPathComponent:[@"des_report_" stringByAppendingString:stamp]];
    [NSFileManager.defaultManager createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
    NSString* (^scrub)(NSString*) = ^NSString*(NSString* s) {
        s = [s stringByReplacingOccurrencesOfString:NSHomeDirectory() withString:@"~"];
        return [s stringByReplacingOccurrencesOfString:NSUserName() withString:@"<user>"];
    };
    void (^put)(NSString*, NSString*) = ^(NSString* name, NSString* text) {
        [scrub(text) writeToFile:[dir stringByAppendingPathComponent:name] atomically:YES encoding:NSUTF8StringEncoding error:nil];
    };
    for (NSString* which in @[@"err", @"out"]) {
        NSData* d = [NSData dataWithContentsOfFile:[log_dir() stringByAppendingPathComponent:[NSString stringWithFormat:@"last_run_%@.txt", which]]];
        if (!d) continue;
        NSString* text = [[NSString alloc] initWithData:d encoding:NSUTF8StringEncoding] ?: [[NSString alloc] initWithData:d encoding:NSISOLatin1StringEncoding];
        NSArray<NSString*>* lines = [text componentsSeparatedByString:@"\n"];
        NSUInteger n = lines.count, keep = 400;
        put([NSString stringWithFormat:@"%@_head.txt", which], [[lines subarrayWithRange:NSMakeRange(0, MIN(n, keep))] componentsJoinedByString:@"\n"]);
        if (n > keep)
            put([NSString stringWithFormat:@"%@_tail.txt", which], [[lines subarrayWithRange:NSMakeRange(MAX(keep, n - keep), n - MAX(keep, n - keep))] componentsJoinedByString:@"\n"]);
    }
    NSMutableString* sys = [NSMutableString string];
    uint64_t mem = 0;
    size_t ml = sizeof mem;
    sysctlbyname("hw.memsize", &mem, &ml, NULL, 0);
    NSScreen* sc = NSScreen.mainScreen;
    [sys appendFormat:@"macOS %@\n", NSProcessInfo.processInfo.operatingSystemVersionString];
    [sys appendFormat:@"Mac: %@, %@, %llu GB\n", sysctl_string("hw.model"), sysctl_string("machdep.cpu.brand_string"), mem >> 30];
    [sys appendFormat:@"Screen: %.0fx%.0f points, scale %.0f, up to %ld Hz\n", sc.frame.size.width, sc.frame.size.height, sc.backingScaleFactor, (long)sc.maximumFramesPerSecond];
    NSString* v = [NSString stringWithContentsOfFile:at(@"VERSION") encoding:NSUTF8StringEncoding error:nil];
    [sys appendFormat:@"Port version: %@\n", [v stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] ?: @"?"];
    NSString* commit = nil;
    if (exists(at(@".git")) && run_tool(@"/usr/bin/git", @[@"rev-parse", @"--short", @"HEAD"], nil, 10, &commit))
        [sys appendFormat:@"Commit: %@", commit];
    NSString* ini = [NSString stringWithContentsOfFile:g_ini_path encoding:NSUTF8StringEncoding error:nil];
    if (ini) [sys appendFormat:@"\nlauncher.ini:\n%@", ini];
    put(@"system.txt", sys);
    [NSFileManager.defaultManager createDirectoryAtPath:log_dir() withIntermediateDirectories:YES attributes:nil error:nil];
    NSString* zip = [log_dir() stringByAppendingPathComponent:[NSString stringWithFormat:@"report_%@.zip", stamp]];
    NSArray<NSString*>* names = [NSFileManager.defaultManager contentsOfDirectoryAtPath:dir error:nil] ?: @[];
    NSMutableArray<NSString*>* args = [@[@"-j", @"-q", zip] mutableCopy];
    for (NSString* n in names) [args addObject:[dir stringByAppendingPathComponent:n]];
    BOOL ok = run_tool(@"/usr/bin/zip", args, nil, 60, NULL);
    [NSFileManager.defaultManager removeItemAtPath:dir error:nil];
    if (!ok) { if (why) *why = @"Could not make the zip."; return nil; }
    return zip;
}

// ---------------------------------------------------------------------------------------------
// The window
// ---------------------------------------------------------------------------------------------
@interface Flipped : NSView
@end
@implementation Flipped
- (BOOL)isFlipped { return YES; }
- (void)drawRect:(NSRect)r { [NSColor.windowBackgroundColor setFill]; NSRectFill(r); }   // so --snapshot has the window's colour
@end

@interface Banner : NSView
@property NSImage* image;
@end
@implementation Banner
- (BOOL)isFlipped { return YES; }
- (void)drawRect:(NSRect)r {
    [NSColor.blackColor setFill];
    NSRectFill(self.bounds);
    if (!_image) return;
    NSSize s = _image.size;
    CGFloat h = self.bounds.size.height, w = h * s.width / s.height;
    [_image drawInRect:NSMakeRect((self.bounds.size.width - w) / 2, 0, w, h) fromRect:NSZeroRect operation:NSCompositingOperationSourceOver
              fraction:1 respectFlipped:YES hints:@{NSImageHintInterpolation: @(NSImageInterpolationHigh)}];
}
@end

enum { K_SLOT = 1000 };   // a Controls slot button's tag: K_SLOT + action * 2 + 0/1

@interface App : NSObject <NSApplicationDelegate, NSWindowDelegate, NSTextFieldDelegate>
@property NSWindow* window;
@property NSPopUpButton* fps, *size, *input;
@property NSTextField* fpsHint, *status, *name, *extra, *keysStatus;
@property NSMutableArray<NSButton*>* games;
@property NSButton* movies, *god, *skipIntro, *log, *play, *update, *folders;
@property NSTask* game;
@property BOOL checking;
@property NSString* updateNotice;
@property NSPanel* keysPanel;
@property int listen;          // slot waiting for a key, -1 = none
@property id keyMonitor;
@property BOOL keysChanged;
@end

@implementation App

- (NSTextField*)label:(NSString*)text x:(CGFloat)x y:(CGFloat)y w:(CGFloat)w h:(CGFloat)h in:(NSView*)v {
    NSTextField* t = [NSTextField wrappingLabelWithString:text];
    t.frame = NSMakeRect(x, y, w, h);
    t.font = [NSFont systemFontOfSize:NSFont.systemFontSize];
    [v addSubview:t];
    return t;
}
- (NSButton*)check:(NSString*)text x:(CGFloat)x y:(CGFloat)y w:(CGFloat)w tip:(NSString*)tip in:(NSView*)v {
    NSButton* b = [NSButton checkboxWithTitle:text target:self action:@selector(changed:)];
    b.frame = NSMakeRect(x, y, w, 22);
    b.toolTip = tip;
    [v addSubview:b];
    return b;
}
- (NSButton*)button:(NSString*)text x:(CGFloat)x y:(CGFloat)y w:(CGFloat)w h:(CGFloat)h action:(SEL)a tip:(NSString*)tip in:(NSView*)v {
    NSButton* b = [NSButton buttonWithTitle:text target:self action:a];
    b.frame = NSMakeRect(x, y, w, h);
    b.toolTip = tip;
    [v addSubview:b];
    return b;
}
- (NSPopUpButton*)popup:(NSArray<NSString*>*)items x:(CGFloat)x y:(CGFloat)y w:(CGFloat)w tip:(NSString*)tip in:(NSView*)v {
    NSPopUpButton* p = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(x, y, w, 26) pullsDown:NO];
    [p addItemsWithTitles:items];
    p.target = self;
    p.action = @selector(changed:);
    p.toolTip = tip;
    [v addSubview:p];
    return p;
}

- (void)buildWindow {
    const CGFloat L = 16, X = 112, W = 428;   // left edge, control column, full width (the Windows launcher's)
    NSImage* icon = [[NSImage alloc] initWithContentsOfFile:at(@"game/PS3_GAME/ICON0.PNG")];   // the game's own banner
    const CGFloat bh = icon ? 132 : 44;
    Flipped* v = [[Flipped alloc] initWithFrame:NSMakeRect(0, 0, W + 2 * L, 100)];
    if (icon) {
        Banner* b = [[Banner alloc] initWithFrame:NSMakeRect(L, 12, W, bh)];
        b.image = icon;
        [v addSubview:b];
    } else {
        NSTextField* t = [self label:@"Demon's Souls" x:L y:12 w:W h:bh in:v];
        t.font = [NSFont systemFontOfSize:26 weight:NSFontWeightSemibold];
    }
    CGFloat y = 12 + bh + 12;

    [self label:@"Frame rate" x:L y:y + 4 w:92 h:20 in:v];
    _fps = [self popup:@[@"60 fps", @"30 fps (the original game)"] x:X y:y w:240
                   tip:@"How many frames a second the game runs at. The game runs at real speed at both." in:v];
    y += 30;
    _fpsHint = [self label:@"" x:X y:y w:W - (X - L) h:34 in:v];
    _fpsHint.textColor = NSColor.secondaryLabelColor;
    y += 40;

    [self label:@"Window" x:L y:y + 4 w:92 h:20 in:v];
    _size = [self popup:@[@"1280 x 720 (the original)", @"1600 x 900", @"1920 x 1080", @"2560 x 1440", @"As big as fits my screen"] x:X y:y w:240
                    tip:@"The size of the game's window. The game is drawn at its own 1280x720 and scaled to the window, always at 16:9. "
                        @"A higher internal resolution is not in the Mac build yet." in:v];
    y += 38;

    [self label:@"Game" x:L y:y + 3 w:92 h:20 in:v];
    _games = [NSMutableArray array];
    NSArray* gt = @[@"Normal", @"PC Remaster mod", @"My models"];
    NSArray* gtip = @[@"Your game as on the disc.",
                      @"The \"Demon's Souls PC Remaster\" mod by fromsoftserve (game_remaster). Install it with tools/install_remaster.py, see README.md.",
                      @"The copy with your imported models (game_mod, made by tools/flver_tool.py import)."];
    const CGFloat gx[] = {X, X + 82, X + 222}, gw[] = {80, 138, 110};
    for (int g = 0; g < 3; g++) {
        NSButton* b = [NSButton radioButtonWithTitle:gt[g] target:self action:@selector(gameChosen:)];
        b.frame = NSMakeRect(gx[g], y, gw[g], 22);
        b.tag = g;
        b.toolTip = gtip[g];
        [v addSubview:b];
        [_games addObject:b];
    }
    y += 34;

    const CGFloat C2 = L + W / 2;
    _movies = [self check:@"Play movies" x:L y:y w:200
                      tip:@"The title logo, intro, story and ending movies. Untick to skip them. They need FFmpeg (brew install ffmpeg); without it they are skipped." in:v];
    _god = [self check:@"God mode at start" x:C2 y:y w:200 tip:@"You cannot die and HP, MP and stamina stay full." in:v];
    y += 26;
    _skipIntro = [self check:@"Skip the intro (straight to PRESS START)" x:L y:y w:320
                         tip:@"Confirms the autosave notice, fast-forwards the logos and skips the opening movie, so the game starts at the "
                             @"title screen in a few seconds. The story movies later on still play." in:v];
    y += 26;
    _log = [self check:@"Detailed log (slower)" x:L y:y w:320
                   tip:@"Writes the runtime's per-event lines to logs/last_run_err.txt (DES_LOG=1). Only when asked in an issue: it costs frames and grows fast." in:v];
    y += 34;

    [self label:@"Input" x:L y:y + 4 w:92 h:20 in:v];
    _input = [self popup:@[@"Controller, keyboard and mouse", @"Controller only", @"Keyboard and mouse only"] x:X y:y w:240
                     tip:@"What the game listens to. A DualSense, DualShock 4 or Xbox controller works when connected; the button prompts follow what you last used." in:v];
    y += 36;

    [self label:@"Name" x:L y:y + 3 w:92 h:20 in:v];
    _name = [[NSTextField alloc] initWithFrame:NSMakeRect(X, y, 160, 22)];
    _name.placeholderString = @"Slayer";
    _name.delegate = self;
    _name.toolTip = @"The Mac build has no text box for the game's on-screen keyboard yet: the name you make a new character with comes from here. "
                    @"Letters, digits and spaces, up to 16.";
    [v addSubview:_name];
    y += 34;

    [self label:@"Extra settings" x:L y:y + 3 w:92 h:20 in:v];
    _extra = [[NSTextField alloc] initWithFrame:NSMakeRect(X, y, W - (X - L), 22)];
    _extra.delegate = self;
    _extra.toolTip = @"For testing, or when asked in an issue: NAME=value pairs separated by spaces, e.g. RSX_ENGINE_VCACHE=0. "
                     @"They are set last, so they win over the choices above.";
    [v addSubview:_extra];
    y += 36;

    _play = [self button:@"PLAY" x:L y:y w:W h:46 action:@selector(onPlay:) tip:nil in:v];
    _play.bezelStyle = NSBezelStyleRegularSquare;
    _play.font = [NSFont systemFontOfSize:18 weight:NSFontWeightSemibold];
    _play.keyEquivalent = @"\r";
    y += 56;
    const CGFloat bw = (W - 3 * 8) / 4;
    _update = [self button:@"Check for updates" x:L - 4 y:y w:bw + 8 h:30 action:@selector(onUpdate:)
                       tip:@"Asks GitHub whether there is a newer version, shows what changed and, if you want, installs and rebuilds it in Terminal (mac/rebuild.sh)." in:v];
    [self button:@"Report a problem" x:L + (bw + 8) - 4 y:y w:bw + 8 h:30 action:@selector(onReport:)
             tip:@"Packs the log of your last run and this Mac's specs into a zip and opens a GitHub issue to attach it to." in:v];
    [self button:@"Controls" x:L + 2 * (bw + 8) - 4 y:y w:bw + 8 h:30 action:@selector(onControls:)
             tip:@"Change the keyboard and mouse keys. The game's button prompts follow them." in:v];
    _folders = [self button:@"Folders ▾" x:L + 3 * (bw + 8) - 4 y:y w:bw + 8 h:30 action:@selector(onFolders:)
                        tip:@"Saves, logs and the port's folder." in:v];
    for (NSView* b in v.subviews)
        if ([b isKindOfClass:NSButton.class] && b.frame.size.height == 30) ((NSButton*)b).font = [NSFont systemFontOfSize:11];
    y += 38;
    _status = [self label:@"" x:L y:y w:W h:20 in:v];
    _status.textColor = NSColor.secondaryLabelColor;
    _status.font = [NSFont systemFontOfSize:11];
    _status.maximumNumberOfLines = 1;
    _status.lineBreakMode = NSLineBreakByTruncatingTail;
    y += 20 + 12;

    v.frame = NSMakeRect(0, 0, W + 2 * L, y);
    _window = [[NSWindow alloc] initWithContentRect:v.frame
                                          styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
                                            backing:NSBackingStoreBuffered defer:NO];
    _window.title = @"Demon's Souls - Mac port launcher";
    _window.contentView = v;
    _window.delegate = self;
    [_window center];
}

- (void)writeControls {
    const Settings* s = &g_set;
    [_fps selectItemAtIndex:s->fps == FPS_30 ? 1 : 0];
    [_size selectItemAtIndex:s->size];
    int game = game_present(s->game) ? s->game : 0;
    for (int g = 0; g < 3; g++) {
        _games[g].state = g == game ? NSControlStateValueOn : NSControlStateValueOff;
        if (g) _games[g].enabled = game_present(g);
    }
    _movies.state = s->movies;
    _god.state = s->god;
    _skipIntro.state = s->skip_intro;
    _log.state = s->log;
    [_input selectItemAtIndex:s->input];
    _name.stringValue = g_name;
    _extra.stringValue = g_extra;
    [self updateHint];
}
- (void)readControls {
    Settings* s = &g_set;
    s->fps = _fps.indexOfSelectedItem == 1 ? FPS_30 : FPS_60;
    s->size = (int)_size.indexOfSelectedItem;
    for (int g = 0; g < 3; g++)
        if (_games[g].state == NSControlStateValueOn) s->game = g;
    s->movies = _movies.state == NSControlStateValueOn;
    s->god = _god.state == NSControlStateValueOn;
    s->skip_intro = _skipIntro.state == NSControlStateValueOn;
    s->log = _log.state == NSControlStateValueOn;
    s->input = (int)_input.indexOfSelectedItem;
    g_name = [_name.stringValue copy];
    g_extra = [_extra.stringValue copy];
}
- (void)changed:(id)sender { [self updateHint]; [self readControls]; save_settings(); }
- (void)gameChosen:(NSButton*)sender {
    for (NSButton* b in _games) b.state = b == sender ? NSControlStateValueOn : NSControlStateValueOff;
    [self changed:sender];
}
- (void)controlTextDidEndEditing:(NSNotification*)n { [self readControls]; save_settings(); }

// The line under the frame rate: what the choice does on this screen.
- (void)updateHint {
    long hz = NSScreen.mainScreen.maximumFramesPerSecond;
    if (_fps.indexOfSelectedItem == 1) _fpsHint.stringValue = @"The game's original frame rate.";
    else if (hz % 60 == 0)
        _fpsHint.stringValue = [NSString stringWithFormat:@"Twice the original, at real game speed. Your screen goes up to %ld Hz, a multiple of 60.", hz];
    else
        _fpsHint.stringValue = [NSString stringWithFormat:@"Twice the original, at real game speed. May look uneven on your %ld Hz screen.", hz];
}

- (void)updateStatus {
    NSString* s;
    if (!built()) s = @"Not built yet: see docs/MACOS.md (mac/install.sh).";
    else {
        s = [NSString stringWithFormat:@"%@  ·  %@", sysctl_string("machdep.cpu.brand_string"),
             game_present(0) ? @"ready to play" : @"game files missing: see docs/MACOS.md"];
        NSString* v = [[NSString stringWithContentsOfFile:at(@"VERSION") encoding:NSUTF8StringEncoding error:nil]
                       stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        if (v.length && v.length < 40) s = [s stringByAppendingFormat:@"  ·  %@", v];
        if (g_set.movies && !have_ffmpeg()) s = [s stringByAppendingString:@"  ·  no FFmpeg: movies are skipped"];
    }
    if (_updateNotice.length && built()) s = [NSString stringWithFormat:@"%@ newer change(s) on GitHub: press Check for updates.", _updateNotice];
    if (_game) s = @"Playing. The logos and the first load take about a minute.";
    _status.stringValue = s;
}

- (void)message:(NSString*)text info:(NSString*)info {
    NSAlert* a = [NSAlert new];
    a.messageText = text;
    a.informativeText = info ?: @"";
    [a runModal];
}

// Checks before a start; NO = a message was shown.
- (BOOL)canPlay {
    if (!built()) {
        NSAlert* a = [NSAlert new];
        a.messageText = @"The game is not built yet (port/build_mac).";
        a.informativeText = @"mac/install.sh builds it from your disc image. docs/MACOS.md has the steps.";
        [a addButtonWithTitle:@"Open the guide"];
        [a addButtonWithTitle:@"Cancel"];
        if ([a runModal] == NSAlertFirstButtonReturn) [NSWorkspace.sharedWorkspace openURL:[NSURL fileURLWithPath:at(@"docs/MACOS.md")]];
        return NO;
    }
    if (!game_present(g_set.game)) {
        NSArray* how = @[@"The game files are not in the game folder. See docs/MACOS.md (mac/install.sh).",
                         @"The PC Remaster mod is not installed (game_remaster). See \"Optional: PC Remaster mod\" in README.md.",
                         @"No models imported yet (game_mod). See models/README.txt."];
        [self message:how[g_set.game] info:nil];
        return NO;
    }
    NSString* bad = nil;
    if (!parse_extra(g_extra, [NSMutableArray array], &bad)) {
        [self message:@"Extra settings are NAME=value pairs separated by spaces; this one is not:" info:bad];
        return NO;
    }
    return YES;
}

- (void)onPlay:(id)sender {
    if (_game) return;
    [_window makeFirstResponder:nil];
    [self readControls];
    if (!save_settings()) { [self message:@"Could not write launcher.ini." info:g_ini_path]; return; }
    if (![self canPlay]) return;
    _game = start_game(&g_set);
    if (!_game) { [self message:@"Could not start mac/play.sh." info:nil]; return; }
    _play.enabled = NO;
    _update.enabled = NO;
    _play.title = @"Playing...";
    [self updateStatus];
    __weak App* me = self;
    _game.terminationHandler = ^(NSTask* t) {
        int code = t.terminationReason == NSTaskTerminationReasonExit ? t.terminationStatus : 128 + t.terminationStatus;
        dispatch_async(dispatch_get_main_queue(), ^{ [me gameDone:code]; });
    };
    [_window miniaturize:nil];
}
- (void)gameDone:(int)code {
    _game = nil;
    _play.enabled = YES;
    _update.enabled = YES;
    _play.title = @"PLAY";
    [self updateStatus];
    [_window deminiaturize:nil];
    [NSApp activateIgnoringOtherApps:YES];
    if (code == 0) return;
    NSAlert* a = [NSAlert new];
    a.alertStyle = NSAlertStyleWarning;
    a.messageText = [NSString stringWithFormat:@"Demon's Souls stopped with an error (exit code %d).", code];
    a.informativeText = @"The log of this run is in logs/last_run_err.txt.\n\nMake a report now? It packs the log and this Mac's specs into a zip for a GitHub issue.";
    [a addButtonWithTitle:@"Make a report"];
    [a addButtonWithTitle:@"Not now"];
    if ([a runModal] == NSAlertFirstButtonReturn) [self onReport:nil];
}

- (void)onReport:(id)sender {
    NSString* why = nil;
    NSString* zip = make_report(&why);
    if (!zip) { [self message:@"Report a problem" info:why]; return; }
    [NSWorkspace.sharedWorkspace activateFileViewerSelectingURLs:@[[NSURL fileURLWithPath:zip]]];
    NSAlert* a = [NSAlert new];
    a.messageText = @"The report is ready.";
    a.informativeText = [NSString stringWithFormat:@"%@ is shown in Finder. Open a new GitHub issue and drag it in?", zip.lastPathComponent];
    [a addButtonWithTitle:@"Open GitHub"];
    [a addButtonWithTitle:@"Not now"];
    if ([a runModal] == NSAlertFirstButtonReturn) [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:kIssues]];
}

- (void)openFolder:(NSMenuItem*)item {
    NSString* p = item.representedObject;
    if (!exists(p)) { [self message:@"There is nothing here yet:" info:p]; return; }
    [NSWorkspace.sharedWorkspace openURL:[NSURL fileURLWithPath:p]];
}
- (void)onFolders:(NSButton*)sender {
    NSMenu* m = [NSMenu new];
    const char* gd = getenv("PS3_GAMEDATA_ROOT");
    NSString* saves = [(gd && *gd) ? @(gd) : at(@"gamedata") stringByAppendingPathComponent:@"dev_hdd0/home/00000001/savedata"];
    NSArray* items = @[@[@"Saves", saves], @[@"Logs of the last run", log_dir()], @[@"-", @""],
                       @[@"Keyboard and mouse button icons (textures/kbm)", at(@"textures/kbm")], @[@"-", @""], @[@"The port's folder", g_root]];
    for (NSArray* it in items) {
        if ([it[0] isEqualToString:@"-"]) { [m addItem:NSMenuItem.separatorItem]; continue; }
        NSMenuItem* mi = [m addItemWithTitle:it[0] action:@selector(openFolder:) keyEquivalent:@""];
        mi.target = self;
        mi.representedObject = it[1];
    }
    [m popUpMenuPositioningItem:nil atLocation:NSMakePoint(0, sender.bounds.size.height + 4) inView:sender];
}

// "Check for updates" asks GitHub (git fetch) off the main thread, so a slow network never freezes the
// window. quiet = the check at start: only the status line.
- (void)checkUpdates:(BOOL)quiet {
    if (_checking) return;
    if (!exists(at(@".git"))) {
        if (quiet) return;
        NSAlert* a = [NSAlert new];
        a.messageText = @"This copy was not made with git, so it cannot update itself.";
        a.informativeText = @"The newest version is on the GitHub releases page.";
        [a addButtonWithTitle:@"Open GitHub"];
        [a addButtonWithTitle:@"Cancel"];
        if ([a runModal] == NSAlertFirstButtonReturn) [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:kReleases]];
        return;
    }
    _checking = YES;
    if (!quiet) { _update.enabled = NO; _status.stringValue = @"Asking GitHub..."; }
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        // no prompt nobody could answer; give up on a connection that stalls under 1 KB/s for 20 s
        NSDictionary* env = @{@"GIT_TERMINAL_PROMPT": @"0", @"GIT_HTTP_LOW_SPEED_LIMIT": @"1000", @"GIT_HTTP_LOW_SPEED_TIME": @"20"};
        NSString* out = nil, *count = nil, *log = nil, *dirty = nil, *ahead = nil;
        BOOL fetched = run_tool(@"/usr/bin/git", @[@"fetch", @"--quiet", @"origin", @"main"], env, 90, &out);
        BOOL counted = fetched && run_tool(@"/usr/bin/git", @[@"rev-list", @"--count", @"HEAD..origin/main"], nil, 20, &count);
        if (counted && count.intValue > 0) {
            run_tool(@"/usr/bin/git", @[@"log", @"--format=- %s", @"-n", @"12", @"HEAD..origin/main"], nil, 20, &log);
            run_tool(@"/usr/bin/git", @[@"status", @"--porcelain", @"--untracked-files=no"], nil, 20, &dirty);
            run_tool(@"/usr/bin/git", @[@"rev-list", @"--count", @"origin/main..HEAD"], nil, 20, &ahead);
        }
        dispatch_async(dispatch_get_main_queue(), ^{
            self.checking = NO;
            self.update.enabled = self.game == nil;
            int behind = counted ? count.intValue : 0;
            self.updateNotice = behind > 0 ? [NSString stringWithFormat:@"%d", behind] : nil;
            [self updateStatus];
            if (quiet) return;
            if (!fetched) { [self message:@"Could not reach GitHub." info:[out stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet]]; return; }
            if (behind <= 0) { [self message:@"You have the newest version." info:nil]; return; }
            BOOL own = [dirty stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet].length || ahead.intValue > 0;
            NSAlert* a = [NSAlert new];
            a.messageText = [NSString stringWithFormat:@"%d newer change%s on GitHub", behind, behind == 1 ? "" : "s"];
            a.informativeText = [NSString stringWithFormat:@"%@%@%@", log ?: @"", behind > 12 ? @"...\n" : @"",
                                 own ? @"\nThis folder has changes of its own (edited files or commits GitHub does not have), so the launcher will not update it: "
                                       @"use git yourself."
                                     : @"\nUpdate now? Terminal opens, gets them (git pull) and rebuilds what changed (mac/rebuild.sh)."];
            if (!own) [a addButtonWithTitle:@"Update and rebuild"];
            [a addButtonWithTitle:own ? @"OK" : @"Not now"];
            if (!own && [a runModal] == NSAlertFirstButtonReturn) [self runUpdate];
            else if (own) [a runModal];
        });
    });
}
- (void)onUpdate:(id)sender { [self checkUpdates:NO]; }
- (void)runUpdate {
    NSString* script = [NSString stringWithFormat:@"#!/bin/zsh\ncd %@ || exit 1\n"
                        @"git pull --ff-only origin main && mac/rebuild.sh toolkit lift build && echo && echo 'Updated. You can close this window and press PLAY.'\n",
                        [NSString stringWithFormat:@"'%@'", [g_root stringByReplacingOccurrencesOfString:@"'" withString:@"'\\''"]]];
    NSString* path = at(@"cache/launcher_update.command");
    [NSFileManager.defaultManager createDirectoryAtPath:at(@"cache") withIntermediateDirectories:YES attributes:nil error:nil];
    if (![script writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil]) { [self message:@"Could not write the update script." info:path]; return; }
    [NSFileManager.defaultManager setAttributes:@{NSFilePosixPermissions: @0755} ofItemAtPath:path error:nil];
    [NSWorkspace.sharedWorkspace openURL:[NSURL fileURLWithPath:path]];
    _updateNotice = nil;
    [self updateStatus];
}

// ----- the Controls window -----
- (NSButton*)slotButton:(int)slot { return [_keysPanel.contentView viewWithTag:K_SLOT + slot]; }
- (void)keysRefresh {
    for (int a = 0; a < N_ACTIONS; a++)
        for (int k = 0; k < 2; k++) {
            int slot = a * 2 + k;
            [self slotButton:slot].title = slot == _listen ? @"press a key..." : key_label(g_keys[a][k]);
        }
}
- (void)keysSay:(NSString*)t { _keysStatus.stringValue = t; }
- (void)keysChangedNow {
    _keysChanged = YES;
    g_keys_custom = YES;
    save_settings();
}
- (void)bind:(NSString*)name {
    int a = _listen / 2, k = _listen % 2;
    _listen = -1;
    NSMutableArray<NSString*>* moved = [NSMutableArray array];
    for (int b = 0; b < N_ACTIONS; b++)
        for (int j = 0; j < 2; j++)
            if ([g_keys[b][j] isEqualToString:name] && !(b == a && j == k)) {
                g_keys[b][j] = @"";
                if (b != a) [moved addObject:@(ACTIONS[b].label)];
            }
    g_keys[a][k] = name;
    if (!g_keys[a][0].length) { g_keys[a][0] = g_keys[a][1]; g_keys[a][1] = @""; }
    [self keysChangedNow];
    [self keysRefresh];
    [self keysSay:moved.count ? [NSString stringWithFormat:@"%@ is now %s (taken off %@).", key_label(name), ACTIONS[a].label, [moved componentsJoinedByString:@", "]]
                              : [NSString stringWithFormat:@"%@ is now %s.", key_label(name), ACTIONS[a].label]];
}
- (void)slotClicked:(NSButton*)b {
    _listen = (int)b.tag - K_SLOT;
    [self keysRefresh];
    [self keysSay:[NSString stringWithFormat:@"Press the key or mouse button for %s (Esc cancels).", ACTIONS[_listen / 2].label]];
}
- (void)keysReset:(id)sender {
    _listen = -1;
    default_keys();
    [self keysChangedNow];
    [self keysRefresh];
    [self keysSay:@"Back to the default keys."];
}
- (void)keysDone:(id)sender { [_keysPanel close]; }

// Keys and mouse buttons while the Controls window is up: nil = the event was used here.
- (NSEvent*)keysEvent:(NSEvent*)e {
    if (e.window != _keysPanel) return e;
    BOOL mouse = e.type == NSEventTypeLeftMouseDown || e.type == NSEventTypeRightMouseDown || e.type == NSEventTypeOtherMouseDown;
    if (_listen < 0) {
        if (e.type == NSEventTypeRightMouseDown) {   // right-click a slot: clear it
            NSView* hit = [_keysPanel.contentView hitTest:[_keysPanel.contentView.superview convertPoint:e.locationInWindow fromView:nil]];
            if ([hit isKindOfClass:NSButton.class] && hit.tag >= K_SLOT) {
                int slot = (int)hit.tag - K_SLOT, a = slot / 2;
                g_keys[a][slot % 2] = @"";
                if (!g_keys[a][0].length) { g_keys[a][0] = g_keys[a][1]; g_keys[a][1] = @""; }
                [self keysChangedNow];
                [self keysRefresh];
                [self keysSay:[NSString stringWithFormat:@"%s%@", ACTIONS[a].label, g_keys[a][0].length ? @": one key less." : @" has no key now."]];
                return nil;
            }
        }
        return e;
    }
    NSString* name = nil;
    if (mouse) {
        static NSString* const btn[] = {@"LMB", @"RMB", @"MMB", @"MB4", @"MB5"};
        if (e.buttonNumber >= 0 && e.buttonNumber < 5) name = btn[e.buttonNumber];
    } else if (e.type == NSEventTypeKeyDown) {
        if (e.keyCode == 0x35) { _listen = -1; [self keysRefresh]; [self keysSay:@"Cancelled."]; return nil; }
        name = key_name_of_code(e.keyCode);
    } else if (e.type == NSEventTypeFlagsChanged) {
        NSEventModifierFlags f = e.modifierFlags & (NSEventModifierFlagShift | NSEventModifierFlagControl | NSEventModifierFlagOption);
        if (!f) return nil;                          // a modifier going up
        name = key_name_of_code(e.keyCode);
        if (!name) return e;                         // Command, Caps Lock, fn
    }
    if (!name) { [self keysSay:@"That key cannot be used (Command frees the mouse in the game). Pick another one."]; return nil; }
    [self bind:name];
    return nil;
}

- (void)buildKeysPanel {
    const CGFloat CW = 316, RH = 28, TOP = 64;
    const int ROWS = (N_ACTIONS + 1) / 2;
    const CGFloat cw = 12 + 2 * CW + 8 + 12;
    Flipped* v = [[Flipped alloc] initWithFrame:NSMakeRect(0, 0, cw, TOP + ROWS * RH + 8 + 42 + 40)];
    NSTextField* help = [self label:@"Click a slot, then press the key or mouse button for it. Right-click a slot to clear it. Two keys per action; a key goes to "
                                    @"one action only. Fixed: Esc and Command free the mouse; the wheel moves through the item slots. In menus the left / right mouse "
                                    @"buttons always confirm / go back. A DualSense, DualShock 4 or Xbox controller always works too."
                                  x:12 y:8 w:cw - 24 h:TOP - 14 in:v];
    help.font = [NSFont systemFontOfSize:11];
    for (int a = 0; a < N_ACTIONS; a++) {
        int col = a / ROWS, row = a % ROWS;
        CGFloat x = 12 + col * (CW + 8), y = TOP + row * RH;
        [self label:@(ACTIONS[a].label) x:x y:y + 4 w:128 h:20 in:v];
        for (int k = 0; k < 2; k++) {
            NSButton* b = [self button:@"" x:x + 126 + k * 94 y:y - 2 w:96 h:28 action:@selector(slotClicked:) tip:nil in:v];
            b.tag = K_SLOT + a * 2 + k;
            b.font = [NSFont systemFontOfSize:11];
        }
    }
    CGFloat y = TOP + ROWS * RH + 8;
    _keysStatus = [self label:@"" x:12 y:y w:cw - 24 h:36 in:v];
    _keysStatus.textColor = NSColor.secondaryLabelColor;
    y += 42;
    [self button:@"Reset to defaults" x:8 y:y w:150 h:30 action:@selector(keysReset:) tip:nil in:v];
    NSButton* done = [self button:@"Done" x:cw - 8 - 100 y:y w:100 h:30 action:@selector(keysDone:) tip:nil in:v];
    done.keyEquivalent = @"\r";
    _keysPanel = [[NSPanel alloc] initWithContentRect:v.frame styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                                              backing:NSBackingStoreBuffered defer:NO];
    _keysPanel.title = @"Controls - keyboard and mouse";
    _keysPanel.contentView = v;
    _keysPanel.releasedWhenClosed = NO;
    _keysPanel.delegate = self;
    _listen = -1;
    _keysChanged = NO;
    [self keysRefresh];
    [self keysSay:@"The button prompts in the game follow these keys."];
}
- (void)onControls:(id)sender {
    if (_keysPanel.visible) { [_keysPanel makeKeyAndOrderFront:nil]; return; }
    [self buildKeysPanel];
    NSRect f = _window.frame;
    [_keysPanel setFrameTopLeftPoint:NSMakePoint(f.origin.x + 20, NSMaxY(f) - 20)];
    __weak App* me = self;
    _keyMonitor = [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown | NSEventMaskFlagsChanged | NSEventMaskLeftMouseDown |
                                                                NSEventMaskRightMouseDown | NSEventMaskOtherMouseDown
                                                        handler:^NSEvent*(NSEvent* e) { return [me keysEvent:e]; }];
    [_keysPanel makeKeyAndOrderFront:nil];
}
- (void)windowWillClose:(NSNotification*)n {
    if (n.object == _keysPanel) {
        if (_keyMonitor) { [NSEvent removeMonitor:_keyMonitor]; _keyMonitor = nil; }
        _listen = -1;
    } else if (n.object == _window) {
        [self readControls];
        save_settings();
    }
}

// ----- the application -----
- (void)buildMenu {
    NSMenu* bar = [NSMenu new], *app = [NSMenu new], *edit = [NSMenu new];
    [bar addItemWithTitle:@"" action:nil keyEquivalent:@""].submenu = app;
    [app addItemWithTitle:@"Hide Demon's Souls Launcher" action:@selector(hide:) keyEquivalent:@"h"];
    [app addItemWithTitle:@"Quit Demon's Souls Launcher" action:@selector(terminate:) keyEquivalent:@"q"];
    NSMenuItem* e = [bar addItemWithTitle:@"Edit" action:nil keyEquivalent:@""];
    edit.title = @"Edit";
    e.submenu = edit;
    [edit addItemWithTitle:@"Cut" action:@selector(cut:) keyEquivalent:@"x"];
    [edit addItemWithTitle:@"Copy" action:@selector(copy:) keyEquivalent:@"c"];
    [edit addItemWithTitle:@"Paste" action:@selector(paste:) keyEquivalent:@"v"];
    [edit addItemWithTitle:@"Select All" action:@selector(selectAll:) keyEquivalent:@"a"];
    NSApp.mainMenu = bar;
}
- (void)snapshot:(NSView*)v to:(NSString*)path {
    [v layoutSubtreeIfNeeded];
    NSBitmapImageRep* rep = [v bitmapImageRepForCachingDisplayInRect:v.bounds];
    [v cacheDisplayInRect:v.bounds toBitmapImageRep:rep];
    [[rep representationUsingType:NSBitmapImageFileTypePNG properties:@{}] writeToFile:path atomically:YES];
}
- (void)applicationDidFinishLaunching:(NSNotification*)n {
    [self buildMenu];
    [self buildWindow];
    [self writeControls];
    [self updateStatus];
    NSArray<NSString*>* args = NSProcessInfo.processInfo.arguments;
    NSUInteger si = [args indexOfObject:@"--snapshot"], sk = [args indexOfObject:@"--snapshot-controls"];
    if (si != NSNotFound && si + 1 < args.count) { [self snapshot:_window.contentView to:args[si + 1]]; exit(0); }
    if (sk != NSNotFound && sk + 1 < args.count) { [self buildKeysPanel]; [self snapshot:_keysPanel.contentView to:args[sk + 1]]; exit(0); }
    [_window makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    if (built()) [self checkUpdates:YES];
}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication*)a { return _game == nil; }
- (BOOL)applicationSupportsSecureRestorableState:(NSApplication*)a { return YES; }
@end

int main(int argc, const char** argv) {
    @autoreleasepool {
        BOOL play = NO, report = NO;
        for (int i = 1; i < argc; i++) {
            if (!strcmp(argv[i], "--play")) play = YES;
            if (!strcmp(argv[i], "--report-only")) report = YES;
        }
        if (!find_root()) {
            if (play || report) { fprintf(stderr, "DemonsSoulsLauncher: mac/play.sh not found next to the app (set DES_ROOT)\n"); return 2; }
            [NSApplication sharedApplication];
            NSAlert* a = [NSAlert new];
            a.messageText = @"The port's folder was not found.";
            a.informativeText = @"Keep DemonsSoulsLauncher.app in the folder that holds mac/play.sh (mac/rebuild.sh build puts it there).";
            [a runModal];
            return 2;
        }
        const char* ini = getenv("DES_LAUNCHER_INI");
        g_ini_path = (ini && *ini) ? @(ini) : at(@"launcher.ini");
        default_keys();
        load_settings();
        if (report) {
            NSString* why = nil, *zip = make_report(&why);
            if (!zip) { fprintf(stderr, "%s\n", why.UTF8String); return 1; }
            printf("%s\n", zip.UTF8String);
            return 0;
        }
        if (play) {   // for a Dock shortcut or a script: the saved settings, no window
            NSString* bad = nil;
            if (!built() || !game_present(g_set.game) || !parse_extra(g_extra, [NSMutableArray array], &bad)) {
                fprintf(stderr, "DemonsSoulsLauncher: not ready to play (open the launcher for the reason)\n");
                return 1;
            }
            NSTask* t = start_game(&g_set);
            if (!t) return 1;
            [t waitUntilExit];
            return t.terminationStatus;
        }
        NSApplication* app = [NSApplication sharedApplication];
        app.activationPolicy = NSApplicationActivationPolicyRegular;
        App* d = [App new];
        app.delegate = d;
        [app run];
    }
    return 0;
}
