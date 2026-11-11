// DemonsSoulsLauncher.exe -- one window for the play options of the Demon's Souls PC port.
//
// It keeps the choices in launcher.ini next to PLAY.bat, sets the environment variables PLAY.bat
// reads (DES_FPS, DES_GAME, DES_RES_SCALE, ...) and runs PLAY.bat with them. PLAY.bat keeps the
// frame-rate recipe, the logs, the recording and the cache clean-up, so the window and PLAY.bat on
// its own always start the game the same way. DES_LAUNCHER=1 tells PLAY.bat not to wait for a key
// at the end; a crash is reported here instead, with an offer to run REPORT.bat.
//
//   DemonsSoulsLauncher.exe          the window
//   DemonsSoulsLauncher.exe --play   starts the game with the saved settings (for a desktop shortcut)
//
// Plain Win32 + GDI+ (for the game's own ICON0.PNG banner), nothing to install. Built with the game
// (project/launcher/CMakeLists.txt) and copied next to PLAY.bat.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <commctrl.h>
#include <shellapi.h>
#include <objidl.h>
#include <algorithm>
namespace Gdiplus { using std::min; using std::max; }   // gdiplus.h wants the min/max macros
#include <gdiplus.h>
#include <map>
#include <string>
#include <vector>

using std::wstring;

// ---------------------------------------------------------------------------------------------
// Paths, settings
// ---------------------------------------------------------------------------------------------
static wstring g_root;   // the folder with PLAY.bat
static wstring g_ini;

static bool exists(const wstring& p) { return GetFileAttributesW(p.c_str()) != INVALID_FILE_ATTRIBUTES; }
static wstring at(const wchar_t* rel) { return g_root + L"\\" + rel; }
static wstring widen(const std::string& s);   // UTF-8 -> UTF-16, below
static std::string g_update_notice;          // a newer release the check at start found (status line)

// Next to PLAY.bat (where the build copies it), or still in the build tree (port\build_opt\launcher).
static bool find_root() {
    wchar_t buf[MAX_PATH * 2];
    DWORD n = GetModuleFileNameW(nullptr, buf, (DWORD)(sizeof buf / sizeof *buf));
    if (!n || n >= sizeof buf / sizeof *buf) return false;
    wstring d(buf, n);
    for (int up = 0; up < 4; ++up) {
        size_t s = d.find_last_of(L'\\');
        if (s == wstring::npos) return false;
        d.resize(s);
        if (exists(d + L"\\PLAY.bat")) { g_root = d; return true; }
    }
    return false;
}

enum { FPS_AUTO, FPS_30, FPS_50, FPS_60, FPS_UNLIMITED, FPS_CUSTOM };
// Game choices: the folder each plays (Boss rush: PLAY.bat makes game_bossrush from game, so game must be there)
static const wchar_t* const GAME_DIRS[] = {L"game", L"game_remaster", L"game_mod", L"game"};
enum { GAME_BOSS_RUSH = 3, GAME_COUNT = 4 };

struct Settings {
    int fps = FPS_AUTO, custom = 72;
    int res = 1;              // DES_RES_SCALE 1-4
    bool shadow = false;      // LD_RES_SCALE_SHADOW
    int game = 0;             // GAME_DIRS
    bool fullscreen = false, movies = true, god = false, record = true, dump = false;
    bool by_letter = false, pin = true;
    bool no_rebuild = false;  // DES_NO_REBUILD: after an update, play the build there is
    bool skip_intro = false;  // DES_SKIP_INTRO: straight to PRESS START
    bool vrr = false;         // DES_VRR: a G-Sync / FreeSync screen (vsync off may tear, 60 fps vsync off)
    int br_souls = 1;         // DES_BR_SOULS: boss rush souls multiplier (BR_SOULS_CHOICES)
    wstring extra;            // NAME=value NAME=value ...
};
static Settings g_set;
static const int BR_SOULS_CHOICES[] = {1, 2, 3, 5, 10};
enum { BR_SOULS_N = (int)(sizeof BR_SOULS_CHOICES / sizeof *BR_SOULS_CHOICES) };

// Key bindings (NOTES fix 103): launcher.ini [controls] <action>=<KEY>[+<KEY>] (no line = the default, empty =
// unbound). The game gets the ones that differ from the defaults as PAD_KEYS (libs/input/cellPad.c s_kb: the same
// action names, defaults and key names); tools\kbm_icons.py draws the button icons from them before Play.
struct Action { const wchar_t* name; const wchar_t* label; const wchar_t* def; };
static const Action ACTIONS[] = {
    {L"move_forward", L"Move forward", L"W"}, {L"move_back", L"Move back", L"S"},
    {L"move_left", L"Move left", L"A"}, {L"move_right", L"Move right", L"D"},
    {L"camera_up", L"Camera up", L"I"}, {L"camera_down", L"Camera down", L"K"},
    {L"camera_left", L"Camera left", L"J"}, {L"camera_right", L"Camera right", L"L"},
    {L"attack", L"Attack (R1)", L"LMB"}, {L"strong_attack", L"Strong attack (R2)", L"SHIFT"},
    {L"block", L"Block (L1)", L"RMB"}, {L"parry", L"Parry (L2)", L"CTRL"},
    {L"roll", L"Roll / back (Circle)", L"SPACE"}, {L"interact", L"Interact (Cross)", L"E"},
    {L"two_hand", L"Two-hand (Triangle)", L"F"}, {L"use_item", L"Use item (Square)", L"R"},
    {L"lock_on", L"Lock on (R3)", L"TAB+MMB"}, {L"l3", L"L3", L"C"},
    {L"dpad_up", L"D-pad up", L"UP"}, {L"dpad_down", L"D-pad down", L"DOWN"},
    {L"dpad_left", L"D-pad left", L"LEFT"}, {L"dpad_right", L"D-pad right", L"RIGHT"},
    {L"start", L"Start (menu)", L"ENTER"}, {L"select", L"Select", L"BACK"},
};
enum { N_ACTIONS = (int)(sizeof ACTIONS / sizeof *ACTIONS) };
static wstring g_keys[N_ACTIONS][2];   // key names; "" = none

static void split_keys(const wstring& v, wstring out[2]) {
    out[0].clear(); out[1].clear();
    size_t plus = v.find(L'+');
    out[0] = v.substr(0, plus);
    if (plus != wstring::npos) out[1] = v.substr(plus + 1);
    if (out[0].empty()) { out[0] = out[1]; out[1].clear(); }
}
static wstring join_keys(const wstring k[2]) {
    if (k[0].empty()) return k[1];
    return k[1].empty() ? k[0] : k[0] + L"+" + k[1];
}
static void load_keys() {
    for (int a = 0; a < N_ACTIONS; ++a) {
        wchar_t buf[64];
        GetPrivateProfileStringW(L"controls", ACTIONS[a].name, L"\x7f", buf, 64, g_ini.c_str());
        split_keys(wcscmp(buf, L"\x7f") ? wstring(buf) : wstring(ACTIONS[a].def), g_keys[a]);
    }
}
static void save_keys() {
    for (int a = 0; a < N_ACTIONS; ++a)
        WritePrivateProfileStringW(L"controls", ACTIONS[a].name, join_keys(g_keys[a]).c_str(), g_ini.c_str());
}
static wstring pad_keys_env() {   // the actions that differ from the defaults
    wstring e;
    for (int a = 0; a < N_ACTIONS; ++a) {
        wstring v = join_keys(g_keys[a]);
        if (v != ACTIONS[a].def) e += wstring(ACTIONS[a].name) + L"=" + v + L";";
    }
    if (!e.empty()) e.pop_back();
    return e;
}

static int ini_int(const wchar_t* k, int def) { return (int)GetPrivateProfileIntW(L"launcher", k, def, g_ini.c_str()); }
static void ini_put(const wchar_t* k, const wstring& v) { WritePrivateProfileStringW(L"launcher", k, v.c_str(), g_ini.c_str()); }
static void ini_put(const wchar_t* k, int v) { ini_put(k, std::to_wstring(v)); }

static void load_settings() {
    Settings& s = g_set;
    s.fps = std::clamp(ini_int(L"fps", s.fps), 0, (int)FPS_CUSTOM);
    s.custom = ini_int(L"custom_fps", s.custom);
    s.res = std::clamp(ini_int(L"res_scale", s.res), 1, 4);
    s.shadow = ini_int(L"shadow_scale", s.shadow) != 0;
    s.game = std::clamp(ini_int(L"game", s.game), 0, GAME_COUNT - 1);
    s.fullscreen = ini_int(L"fullscreen", s.fullscreen) != 0;
    s.movies = ini_int(L"movies", s.movies) != 0;
    s.god = ini_int(L"god_mode", s.god) != 0;
    s.record = ini_int(L"record", s.record) != 0;
    s.dump = ini_int(L"dump_textures", s.dump) != 0;
    s.by_letter = ini_int(L"keys_by_letter", s.by_letter) != 0;
    s.pin = ini_int(L"pin_cores", s.pin) != 0;
    s.no_rebuild = ini_int(L"no_rebuild", s.no_rebuild) != 0;
    s.skip_intro = ini_int(L"skip_intro", s.skip_intro) != 0;
    s.vrr = ini_int(L"vrr", s.vrr) != 0;
    s.br_souls = std::clamp(ini_int(L"boss_rush_souls", s.br_souls), 1, 100);
    wchar_t buf[2048];
    GetPrivateProfileStringW(L"launcher", L"extra", L"", buf, 2048, g_ini.c_str());
    s.extra = buf;
    load_keys();
}

static void save_settings() {
    const Settings& s = g_set;
    ini_put(L"fps", s.fps);
    ini_put(L"custom_fps", s.custom);
    ini_put(L"res_scale", s.res);
    ini_put(L"shadow_scale", s.shadow);
    ini_put(L"game", s.game);
    ini_put(L"fullscreen", s.fullscreen);
    ini_put(L"movies", s.movies);
    ini_put(L"god_mode", s.god);
    ini_put(L"record", s.record);
    ini_put(L"dump_textures", s.dump);
    ini_put(L"keys_by_letter", s.by_letter);
    ini_put(L"pin_cores", s.pin);
    ini_put(L"no_rebuild", s.no_rebuild);
    ini_put(L"skip_intro", s.skip_intro);
    ini_put(L"vrr", s.vrr);
    ini_put(L"boss_rush_souls", s.br_souls);
    ini_put(L"extra", s.extra);
    save_keys();
}

static bool game_present(int g) { return exists(g_root + L"\\" + GAME_DIRS[g] + L"\\PS3_GAME\\USRDIR\\EBOOT.elf"); }
static wstring exe_path() { return at(L"port\\build_opt\\DemonsSoulsRecomp.exe"); }
static wstring pending_marker() { return at(L"update_pending.txt"); }

// The refresh rate of the main screen (PLAY.bat asks Windows the same thing).
static int refresh_hz() {
    DEVMODEW dm{};
    dm.dmSize = sizeof dm;
    if (EnumDisplaySettingsW(nullptr, ENUM_CURRENT_SETTINGS, &dm) && dm.dmDisplayFrequency > 1)
        return (int)dm.dmDisplayFrequency;
    return 60;
}

// "NAME=value NAME=value": the extra settings box. Names are letters, digits and _.
static bool parse_extra(const wstring& text, std::vector<std::pair<wstring, wstring>>* out, wstring* bad) {
    size_t i = 0;
    while (i < text.size()) {
        while (i < text.size() && iswspace(text[i])) ++i;
        if (i >= text.size()) break;
        size_t j = i;
        while (j < text.size() && !iswspace(text[j])) ++j;
        wstring tok = text.substr(i, j - i);
        i = j;
        size_t eq = tok.find(L'=');
        bool ok = eq != wstring::npos && eq > 0;
        for (size_t k = 0; ok && k < eq; ++k)
            ok = iswalnum(tok[k]) || tok[k] == L'_';
        if (!ok) { if (bad) *bad = tok; return false; }
        if (out) out->emplace_back(tok.substr(0, eq), tok.substr(eq + 1));
    }
    return true;
}

// The environment PLAY.bat gets: the launcher's own (left unchanged, so nothing from one run stays
// set for the next or reaches REPORT.bat / the update) with the choices on top.
struct EnvBlock {
    struct Less {   // Windows sorts and matches names case-insensitively
        bool operator()(const wstring& a, const wstring& b) const { return _wcsicmp(a.c_str(), b.c_str()) < 0; }
    };
    std::map<wstring, wstring, Less> vars;
    std::vector<wstring> hidden;   // the "=C:=C:\..." entries, kept as they are
    EnvBlock() {
        wchar_t* e = GetEnvironmentStringsW();
        for (const wchar_t* p = e; p && *p; p += wcslen(p) + 1) {
            const wchar_t* eq = wcschr(p + 1, L'=');
            if (*p == L'=' || !eq) hidden.emplace_back(p);
            else vars[wstring(p, eq)] = eq + 1;
        }
        if (e) FreeEnvironmentStringsW(e);
    }
    void set(const wchar_t* k, const wchar_t* v) { if (v) vars[k] = v; else vars.erase(k); }   // v == null: unset
    wstring block() const {
        wstring b;
        for (auto& h : hidden) { b += h; b += L'\0'; }
        for (auto& kv : vars) { b += kv.first; b += L'='; b += kv.second; b += L'\0'; }
        b += L'\0';
        return b;
    }
};

// The same variables the README's "set X=..." lines use. Every one is set
// or cleared, so a variable left over in this Windows session does not change what the window says.
static wstring game_env(const Settings& s) {
    EnvBlock eb;
    auto env = [&](const wchar_t* k, const wchar_t* v) { eb.set(k, v); };
    auto envif = [&](const wchar_t* k, bool on, const wchar_t* v) { eb.set(k, on ? v : nullptr); };
    static const wchar_t* const fps[] = {nullptr, L"30", L"50", L"60", L"unlimited"};
    wstring custom = std::to_wstring(s.custom);
    env(L"DES_FPS", s.fps == FPS_CUSTOM ? custom.c_str() : fps[s.fps]);
    wstring res = std::to_wstring(s.res);
    env(L"LD_RES_SCALE", nullptr);                 // it would win over DES_RES_SCALE
    envif(L"DES_RES_SCALE", s.res > 1, res.c_str());
    envif(L"LD_RES_SCALE_SHADOW", s.res > 1 && s.shadow, L"1");
    env(L"DES_GAME", s.game == GAME_BOSS_RUSH ? nullptr : GAME_DIRS[s.game]);
    envif(L"DES_BOSS_RUSH", s.game == GAME_BOSS_RUSH, L"1");
    wstring souls = std::to_wstring(s.br_souls);
    envif(L"DES_BR_SOULS", s.game == GAME_BOSS_RUSH && s.br_souls > 1, souls.c_str());
    envif(L"DES_FULLSCREEN", s.fullscreen, L"1");
    envif(L"DES_MOVIES", !s.movies, L"0");
    envif(L"DES_GOD", s.god, L"1");
    envif(L"DES_RECORD", !s.record, L"0");
    envif(L"LD_TEX_DUMP", s.dump, L"1");
    envif(L"PAD_KEYS_BY_LETTER", s.by_letter, L"1");
    wstring keys = pad_keys_env();
    env(L"PAD_KEYS", keys.empty() ? nullptr : keys.c_str());
    envif(L"DES_AFFINITY", !s.pin, L"0");
    envif(L"DES_NO_REBUILD", s.no_rebuild, L"1");
    envif(L"DES_SKIP_INTRO", s.skip_intro, L"1");
    envif(L"DES_VRR", s.vrr, L"1");
    std::vector<std::pair<wstring, wstring>> extra;
    parse_extra(s.extra, &extra, nullptr);
    for (auto& kv : extra)
        env(kv.first.c_str(), kv.second.c_str());
    env(L"DES_LAUNCHER", L"1");
    return eb.block();
}

// ---------------------------------------------------------------------------------------------
// Running things
// ---------------------------------------------------------------------------------------------
static wstring comspec() {
    wchar_t buf[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"ComSpec", buf, MAX_PATH);
    return (n && n < MAX_PATH) ? wstring(buf, n) : wstring(L"C:\\Windows\\System32\\cmd.exe");
}

// cmd /c on a .bat; hidden, or in a console window of its own. env: a block from game_env, or null
// for the launcher's own environment.
static HANDLE run_cmd(const wstring& what, bool console, const wstring* env = nullptr) {
    wstring cs = comspec();
    wstring cmd = L"\"" + cs + L"\" /d /c \"" + what + L"\"";
    STARTUPINFOW si{};
    si.cb = sizeof si;
    PROCESS_INFORMATION pi{};
    DWORD flags = (console ? CREATE_NEW_CONSOLE : CREATE_NO_WINDOW) | CREATE_UNICODE_ENVIRONMENT;
    if (!CreateProcessW(cs.c_str(), cmd.data(), nullptr, nullptr, FALSE, flags, env ? (void*)env->c_str() : nullptr,
                        g_root.c_str(), &si, &pi))
        return nullptr;
    CloseHandle(pi.hThread);
    return pi.hProcess;
}
static wstring q(const wstring& p) { return L"\"" + p + L"\""; }

static void open_folder(const wstring& p, bool create) {
    if (create) CreateDirectoryW(p.c_str(), nullptr);
    if (!exists(p)) {
        MessageBoxW(GetActiveWindow(), (L"There is nothing here yet:\n" + p).c_str(), L"Demon's Souls", MB_ICONINFORMATION);
        return;
    }
    ShellExecuteW(nullptr, L"open", p.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
}

static bool have_venv() { return exists(at(L".venv\\Scripts\\python.exe")); }

static void run_report(HWND w) {
    if (!have_venv()) {
        MessageBoxW(w, L"REPORT.bat needs the Python environment SETUP.bat makes. Run SETUP.bat first.",
                    L"Report a problem", MB_ICONWARNING);
        return;
    }
    if (HANDLE h = run_cmd(q(at(L"REPORT.bat")), true)) CloseHandle(h);
}

static void show_crash(HWND w, DWORD code) {
    wchar_t msg[768];
    swprintf(msg, 768,
             L"Demon's Souls stopped with an error (exit code %ld).\n\n"
             L"The log of this run is in logs\\last_run_err.txt.\n\n"
             L"Make a report now? It packs the log and the frame-timing recording into a zip for a "
             L"GitHub issue (REPORT.bat).", (long)code);
    if (MessageBoxW(w, msg, L"Demon's Souls", MB_ICONWARNING | MB_YESNO) == IDYES)
        run_report(w);
}

// Checks before a start; false = a message was shown.
static bool can_play(HWND w, const Settings& s) {
    if (!exists(exe_path())) {
        if (MessageBoxW(w, L"DemonsSoulsRecomp.exe is not built yet (port\\build_opt).\n\n"
                           L"SETUP.bat builds it from your disc image. Run SETUP.bat now?",
                        L"Demon's Souls", MB_ICONWARNING | MB_YESNO) == IDYES)
            if (HANDLE h = run_cmd(q(at(L"SETUP.bat")), true)) CloseHandle(h);
        return false;
    }
    if (!game_present(s.game)) {
        static const wchar_t* const how[] = {
            L"The game files are not in the game folder. Run SETUP.bat.",
            L"The PC Remaster mod is not installed (game_remaster). See \"Optional: PC Remaster mod\" in README.md.",
            L"No models imported yet (game_mod). See models\\README.txt.",
            L"The game files are not in the game folder. Run SETUP.bat."};
        MessageBoxW(w, how[s.game], L"Demon's Souls", MB_ICONWARNING);
        return false;
    }
    if (s.fps == FPS_CUSTOM && (s.custom < 31 || s.custom > 240)) {
        MessageBoxW(w, L"A custom frame rate is a whole number from 31 to 240.", L"Demon's Souls", MB_ICONWARNING);
        return false;
    }
    wstring bad;
    if (!parse_extra(s.extra, nullptr, &bad)) {
        MessageBoxW(w, (L"Extra settings are NAME=value pairs separated by spaces; this one is not:\n\n" + bad).c_str(),
                    L"Demon's Souls", MB_ICONWARNING);
        return false;
    }
    return true;
}

static HANDLE start_game(const Settings& s) {
    // The keyboard / mouse button icons follow the bindings (fix 103): kbm_icons.py --if-stale draws them again when
    // they or its art changed (a few seconds), else returns at once. No Python environment: the icons stay as they are.
    wstring py = at(L".venv\\Scripts\\python.exe"), tool = at(L"tools\\kbm_icons.py");
    if (exists(py) && exists(tool) && exists(at(L"game\\PS3_GAME\\USRDIR"))) {
        if (HANDLE h = run_cmd(q(py) + L" " + q(tool) + L" --if-stale", false)) {
            WaitForSingleObject(h, 60000);
            CloseHandle(h);
        }
    }
    wstring env = game_env(s);
    return run_cmd(q(at(L"PLAY.bat")), false, &env);
}

// ---------------------------------------------------------------------------------------------
// The window
// ---------------------------------------------------------------------------------------------
enum {
    ID_PLAY = IDOK, ID_FPS = 100, ID_CUSTOM, ID_FPS_HINT, ID_RES, ID_SHADOW, ID_GAME0, ID_GAME1, ID_GAME2, ID_GAME3,
    ID_FULLSCREEN, ID_MOVIES, ID_GOD, ID_RECORD, ID_DUMP, ID_LETTER, ID_PIN, ID_NOREBUILD, ID_SKIPINTRO, ID_VRR, ID_EXTRA,
    ID_UPDATE, ID_REPORT, ID_CONTROLS, ID_FOLDERS, ID_STATUS, ID_BRSOULS,
    ID_F_SAVES = 200, ID_F_LOGS, ID_F_PERF, ID_F_REPLACE, ID_F_DUMP, ID_F_CAPTURES, ID_F_MODELS, ID_F_ROOT,
};
static const UINT WM_GAME_DONE = WM_APP + 1, WM_UPDATE_CHECKED = WM_APP + 2;

static HWND g_wnd, g_tip;
static HFONT g_font, g_font_big, g_font_title;
static Gdiplus::Bitmap* g_banner;
static int g_dpi = 96, g_hz = 60;
static HANDLE g_game;
static bool g_loading;

static int S(int v) { return MulDiv(v, g_dpi, 96); }
static HWND item(int id) { return GetDlgItem(g_wnd, id); }
static bool checked(int id) { return SendMessageW(item(id), BM_GETCHECK, 0, 0) == BST_CHECKED; }
static void check(int id, bool on) { SendMessageW(item(id), BM_SETCHECK, on ? BST_CHECKED : BST_UNCHECKED, 0); }

static HWND add(const wchar_t* cls, const wchar_t* text, DWORD style, int id, int x, int y, int w, int h, const wchar_t* tip = nullptr) {
    HWND c = CreateWindowExW(0, cls, text, WS_CHILD | WS_VISIBLE | style, S(x), S(y), S(w), S(h), g_wnd,
                             (HMENU)(INT_PTR)id, GetModuleHandleW(nullptr), nullptr);
    SendMessageW(c, WM_SETFONT, (WPARAM)g_font, FALSE);
    if (tip && g_tip) {
        TOOLINFOW ti{};
        ti.cbSize = sizeof ti;
        ti.uFlags = TTF_IDISHWND | TTF_SUBCLASS;
        ti.hwnd = g_wnd;
        ti.uId = (UINT_PTR)c;
        ti.lpszText = (LPWSTR)tip;
        SendMessageW(g_tip, TTM_ADDTOOLW, 0, (LPARAM)&ti);
    }
    return c;
}
static HWND label(const wchar_t* text, int x, int y, int w, int h = 20, int id = -1) {
    return add(L"STATIC", text, SS_LEFT, id, x, y, w, h);
}

static int banner_h() { return g_banner ? 132 : 44; }

// Auto's frame rate on a screen of R Hz without G-Sync / FreeSync, as PLAY.bat's :auto_fps: 60 when R (or R + 1:
// 59.94 is reported as 59) is a multiple of 60; 50 on ~100 Hz; else the highest rate 45-75 that R (or else R + 1)
// is a whole multiple of (144 -> 72, 165 -> 55, 75 -> 75); 60 when there is none.
static int auto_fps(int R) {
    if (R % 60 == 0 || (R + 1) % 60 == 0) return 60;
    if (R >= 95 && R <= 105) return 50;
    for (int r : {R, R + 1}) {
        int best = 0;
        for (int k = 1; k <= 5; k++)
            if (r % k == 0 && r / k >= 45 && r / k <= 75 && r / k > best) best = r / k;
        if (best) return best;
    }
    return 60;
}
// How many refreshes each frame of N fps stays up on R Hz (0 = not a whole number), as PLAY.bat.
static int refreshes_per_frame(int R, int N) {
    return N <= 0 ? 0 : R % N == 0 ? R / N : (R + 1) % N == 0 ? (R + 1) / N : 0;
}

// The line under the frame rate: what the choice does on this screen.
static void update_fps_hint() {
    int sel = (int)SendMessageW(item(ID_FPS), CB_GETCURSEL, 0, 0);
    EnableWindow(item(ID_CUSTOM), sel == FPS_CUSTOM);
    const int R = g_hz;
    const bool hz100 = R >= 95 && R <= 105;
    const bool vrr = checked(ID_VRR);
    wchar_t t[256];
    switch (sel) {
    case FPS_AUTO: {
        if (vrr) { swprintf(t, 256, L"60 fps, vsync off: your G-Sync / FreeSync screen shows every frame when it is ready."); break; }
        const int N = auto_fps(R), K = refreshes_per_frame(R, N);
        if (K) swprintf(t, 256, L"%d fps on your %d Hz screen: every frame shown exactly %d refresh%s, perfectly even.", N, R,
                        K, K == 1 ? L"" : L"es");
        else swprintf(t, 256, L"60 fps. No even rate fits your %d Hz screen; with G-Sync / FreeSync tick the box below.", R);
        break;
    }
    case FPS_30: swprintf(t, 256, L"The game's original frame rate."); break;
    case FPS_50: swprintf(t, 256, L"Made for 100 Hz screens: every frame shown exactly 2 refreshes."); break;
    case FPS_60:
        if (vrr) swprintf(t, 256, L"Vsync off: smooth on your G-Sync / FreeSync screen.");
        else if (refreshes_per_frame(R, 60)) swprintf(t, 256, L"Smooth on 60, 120 and 240 Hz screens like yours (%d Hz).", R);
        else swprintf(t, 256, L"Uneven on your %d Hz screen (Auto picks %d there).", R, auto_fps(R));
        break;
    case FPS_UNLIMITED:
        swprintf(t, 256, vrr ? L"Up to 240 fps, no vsync; your G-Sync / FreeSync screen follows the frame rate."
                             : L"Up to 240 fps, no vsync. Game speed stays right; frames are not evenly paced.");
        break;
    default: {
        wchar_t b[16];
        GetWindowTextW(item(ID_CUSTOM), b, 16);
        int N = _wtoi(b);
        if (N < 31 || N > 240) { swprintf(t, 256, L"Type a whole number from 31 to 240."); break; }
        // as PLAY.bat: vsync when the refresh (or the next whole Hz up: 99.98 is reported as 99) is a multiple of N
        int K = (R % N == 0) ? R / N : ((R + 1) % N == 0 ? (R + 1) / N : 0);
        if (K >= 1) swprintf(t, 256, L"Vsync on: every frame shown %d of your screen's %d Hz refreshes, perfectly even.", K, R);
        else if (vrr) swprintf(t, 256, L"Vsync off: smooth on your G-Sync / FreeSync screen.");
        else swprintf(t, 256, L"Vsync off (%d Hz is not a multiple of %d): frames are not evenly paced.", R, N);
    }
    }
    SetWindowTextW(item(ID_FPS_HINT), t);
}

static void update_status() {
    wstring s;
    if (!exists(exe_path())) s = L"Not built yet: run SETUP.bat first.";
    else {
        bool no_avx2_build = exists(at(L"port\\build_opt\\no_avx2.txt"));
        bool cpu_avx2 = IsProcessorFeaturePresent(40 /* PF_AVX2_INSTRUCTIONS_AVAILABLE */) != 0;
        s = std::to_wstring(g_hz) + L" Hz screen  \u00b7  ";
        if (!no_avx2_build && !cpu_avx2) s += L"this build needs AVX2, which your CPU lacks: run BUILD.bat on this PC";
        else {
            s += no_avx2_build ? L"built without AVX2" : L"AVX2 build";
            s += game_present(0) ? L"  \u00b7  ready to play" : L"  \u00b7  game files missing: run SETUP.bat";
        }
    }
    {   // which release this folder has (VERSION: the release ZIP and update.py write it)
        HANDLE f = CreateFileW(at(L"VERSION").c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        if (f != INVALID_HANDLE_VALUE) {
            char v[64] = {};
            DWORD n = 0;
            ReadFile(f, v, sizeof v - 1, &n, nullptr);
            CloseHandle(f);
            std::string t(v, n);
            while (!t.empty() && (t.back() == '\n' || t.back() == '\r' || t.back() == ' ')) t.pop_back();
            if (!t.empty() && t.size() < 40) s += L"  \u00b7  " + widen(t);
        }
    }
    if (!g_update_notice.empty() && exists(exe_path()))
        s = L"New version " + widen(g_update_notice) + L" is available: press Check for updates.";
    if (exists(pending_marker()) && !g_game) s = L"The last update did not finish building: press Check for updates.";
    if (g_game) s = L"Playing. The logos and the first load take about a minute.";
    SetWindowTextW(item(ID_STATUS), s.c_str());
}

static void read_controls() {
    Settings& s = g_set;
    s.fps = (int)SendMessageW(item(ID_FPS), CB_GETCURSEL, 0, 0);
    wchar_t b[2048];
    GetWindowTextW(item(ID_CUSTOM), b, 16);
    if (s.fps == FPS_CUSTOM || _wtoi(b) > 0) s.custom = _wtoi(b);   // empty while Custom: can_play says so
    s.res = (int)SendMessageW(item(ID_RES), CB_GETCURSEL, 0, 0) + 1;
    s.shadow = checked(ID_SHADOW);
    for (int g = 0; g < GAME_COUNT; ++g)
        if (checked(ID_GAME0 + g)) s.game = g;
    s.fullscreen = checked(ID_FULLSCREEN);
    s.movies = checked(ID_MOVIES);
    s.god = checked(ID_GOD);
    s.record = checked(ID_RECORD);
    s.dump = checked(ID_DUMP);
    s.by_letter = checked(ID_LETTER);
    s.pin = checked(ID_PIN);
    s.no_rebuild = checked(ID_NOREBUILD);
    s.skip_intro = checked(ID_SKIPINTRO);
    s.vrr = checked(ID_VRR);
    {
        int i = (int)SendMessageW(item(ID_BRSOULS), CB_GETCURSEL, 0, 0);
        if (i >= 0 && i < BR_SOULS_N) s.br_souls = BR_SOULS_CHOICES[i];
    }
    GetWindowTextW(item(ID_EXTRA), b, 2048);
    s.extra = b;
}

static void write_controls() {
    const Settings& s = g_set;
    g_loading = true;
    SendMessageW(item(ID_FPS), CB_SETCURSEL, s.fps, 0);
    SetWindowTextW(item(ID_CUSTOM), std::to_wstring(s.custom).c_str());
    SendMessageW(item(ID_RES), CB_SETCURSEL, s.res - 1, 0);
    check(ID_SHADOW, s.shadow);
    EnableWindow(item(ID_SHADOW), s.res > 1);
    int game = game_present(s.game) ? s.game : 0;
    for (int g = 0; g < GAME_COUNT; ++g) {
        check(ID_GAME0 + g, g == game);
        if (g) EnableWindow(item(ID_GAME0 + g), game_present(g));
    }
    check(ID_FULLSCREEN, s.fullscreen);
    check(ID_MOVIES, s.movies);
    check(ID_GOD, s.god);
    check(ID_RECORD, s.record);
    check(ID_DUMP, s.dump);
    check(ID_LETTER, s.by_letter);
    check(ID_PIN, s.pin);
    check(ID_NOREBUILD, s.no_rebuild);
    check(ID_SKIPINTRO, s.skip_intro);
    check(ID_VRR, s.vrr);
    {
        int sel = 0;
        for (int i = 0; i < BR_SOULS_N; ++i) if (BR_SOULS_CHOICES[i] <= s.br_souls) sel = i;
        SendMessageW(item(ID_BRSOULS), CB_SETCURSEL, sel, 0);
        EnableWindow(item(ID_BRSOULS), game == GAME_BOSS_RUSH);
    }
    SetWindowTextW(item(ID_EXTRA), s.extra.c_str());
    g_loading = false;
    update_fps_hint();
}

static DWORD WINAPI wait_game(void* h) {
    WaitForSingleObject((HANDLE)h, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess((HANDLE)h, &code);
    PostMessageW(g_wnd, WM_GAME_DONE, code, 0);
    return 0;
}

static void on_play() {
    if (g_game) return;
    read_controls();
    save_settings();
    if (!can_play(g_wnd, g_set)) return;
    g_game = start_game(g_set);
    if (!g_game) {
        MessageBoxW(g_wnd, L"Could not start PLAY.bat.", L"Demon's Souls", MB_ICONERROR);
        return;
    }
    EnableWindow(item(ID_PLAY), FALSE);
    EnableWindow(item(ID_UPDATE), FALSE);
    SetWindowTextW(item(ID_PLAY), L"Playing...");
    update_status();
    if (HANDLE t = CreateThread(nullptr, 0, wait_game, g_game, 0, nullptr)) CloseHandle(t);
    ShowWindow(g_wnd, SW_MINIMIZE);
}

// The update script deletes this after a good BUILD.bat; while it is there (and the game exe is not
// newer), "Check for updates" offers to build again instead of saying everything is up to date.

static bool build_pending() {
    WIN32_FILE_ATTRIBUTE_DATA m, e;
    if (!GetFileAttributesExW(pending_marker().c_str(), GetFileExInfoStandard, &m)) return false;
    if (GetFileAttributesExW(exe_path().c_str(), GetFileExInfoStandard, &e) &&
        CompareFileTime(&e.ftLastWriteTime, &m.ftLastWriteTime) > 0) {   // built by hand since
        DeleteFileW(pending_marker().c_str());
        return false;
    }
    return true;
}

struct ReadPipe { HANDLE rd; std::string* out; };
static DWORD WINAPI read_pipe(void* p) {
    ReadPipe* r = (ReadPipe*)p;
    char buf[4096];
    DWORD n;
    while (ReadFile(r->rd, buf, sizeof buf, &n, nullptr) && n) r->out->append(buf, n);
    return 0;
}

// git <args> in the port folder, hidden; its output (stdout + stderr) in *out. False = no start,
// a timeout or a non-zero exit. git and its helpers (git-remote-https) run in a job, so a timeout
// ends all of them and the pipe they share closes. Runs on the update-check thread.
static bool git_run(const wstring& git, const wstring& args, std::string* out, DWORD timeout_ms) {
    out->clear();
    SECURITY_ATTRIBUTES sa{sizeof sa, nullptr, TRUE};
    HANDLE rd = nullptr, wr = nullptr;
    if (!CreatePipe(&rd, &wr, &sa, 0)) return false;
    SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);
    HANDLE job = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION lim{};
    lim.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (job) SetInformationJobObject(job, JobObjectExtendedLimitInformation, &lim, sizeof lim);
    // No prompt nobody could answer (terminal or Git Credential Manager window); give up on a
    // connection that stalls under 1 KB/s for 20 s.
    EnvBlock eb;
    eb.set(L"GIT_TERMINAL_PROMPT", L"0");
    eb.set(L"GCM_INTERACTIVE", L"never");
    eb.set(L"GIT_HTTP_LOW_SPEED_LIMIT", L"1000");
    eb.set(L"GIT_HTTP_LOW_SPEED_TIME", L"20");
    wstring env = eb.block();
    wstring cmd = L"\"" + git + L"\" " + args;
    STARTUPINFOW si{};
    si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdOutput = si.hStdError = wr;
    PROCESS_INFORMATION pi{};
    BOOL ok = CreateProcessW(git.c_str(), cmd.data(), nullptr, nullptr, TRUE,
                             CREATE_NO_WINDOW | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT, (void*)env.c_str(),
                             g_root.c_str(), &si, &pi);
    CloseHandle(wr);
    if (!ok) {
        CloseHandle(rd);
        if (job) CloseHandle(job);
        return false;
    }
    if (job) AssignProcessToJobObject(job, pi.hProcess);
    ResumeThread(pi.hThread);
    ReadPipe rp{rd, out};
    HANDLE reader = CreateThread(nullptr, 0, read_pipe, &rp, 0, nullptr);
    DWORD code = 1;
    if (WaitForSingleObject(pi.hProcess, timeout_ms) == WAIT_OBJECT_0) GetExitCodeProcess(pi.hProcess, &code);
    else code = 1;
    if (job) TerminateJobObject(job, 1);   // the timed-out git, or helpers still holding the pipe
    else TerminateProcess(pi.hProcess, 1);
    if (reader) {
        WaitForSingleObject(reader, 5000);
        CancelSynchronousIo(reader);
        WaitForSingleObject(reader, 1000);
        CloseHandle(reader);
    }
    CloseHandle(rd);
    if (job) CloseHandle(job);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return code == 0;
}

static wstring widen(const std::string& s) {
    int n = MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), nullptr, 0);
    wstring w(n, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), w.data(), n);
    return w;
}

// "Check for updates" asks GitHub (git fetch) on a thread of its own, so a slow network never
// freezes the window; WM_UPDATE_CHECKED brings the answer back.
// A copy without git (a release ZIP, GitHub's Download ZIP; or git is not installed) asks GitHub's
// releases instead: setup\update.py --check with the setup's own Python.
struct UpdateCheck {
    wstring git;
    bool fetched = false, counted = false;
    int behind = 0;
    std::string out, log;
    bool zip = false;                        // the releases path (update.py)
    bool quiet = false;                      // the check at start: only the status line, no message box
    wstring py;                              // .venv\Scripts\python.exe
    std::string latest, current, notes;
};
static bool g_checking;

static wstring venv_python() { return at(L".venv\\Scripts\\python.exe"); }

static DWORD WINAPI check_thread(void* p) {
    UpdateCheck* c = (UpdateCheck*)p;
    if (c->zip) {
        c->fetched = git_run(c->py, L"\"" + at(L"setup\\update.py") + L"\" --check", &c->out, 60000);
        size_t i = 0;
        while (i < c->out.size()) {
            size_t e = c->out.find('\n', i);
            std::string l = c->out.substr(i, (e == std::string::npos ? c->out.size() : e) - i);
            if (!l.empty() && l.back() == '\r') l.pop_back();
            if (l.rfind("latest=", 0) == 0) c->latest = l.substr(7);
            else if (l.rfind("current=", 0) == 0) c->current = l.substr(8);
            else if (l.rfind("note=", 0) == 0) c->notes += l.substr(5) + "\n";
            if (e == std::string::npos) break;
            i = e + 1;
        }
        c->counted = c->fetched && !c->latest.empty();
        if (!PostMessageW(g_wnd, WM_UPDATE_CHECKED, 0, (LPARAM)c)) delete c;
        return 0;
    }
    std::string count;
    c->fetched = git_run(c->git, L"fetch --quiet", &c->out, 90000);
    c->counted = c->fetched && git_run(c->git, L"rev-list --count HEAD..@{u}", &count, 15000);
    c->behind = c->counted ? atoi(count.c_str()) : 0;
    if (c->behind > 0) git_run(c->git, L"log --no-merges --format=\"- %s\" -n 12 HEAD..@{u}", &c->log, 15000);
    if (!PostMessageW(g_wnd, WM_UPDATE_CHECKED, 0, (LPARAM)c)) delete c;
    return 0;
}

// The build replaces DemonsSoulsLauncher.exe, which cannot happen while it runs: a small script in
// %TEMP% does the work (git pull when pull, then BUILD.bat) and starts the launcher again at the end.
static void start_update(const wstring& git, bool pull, bool zip = false) {
    read_controls();
    save_settings();
    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    wstring bat = wstring(tmp) + L"DemonsSoulsLauncher_update.bat";
    wstring self = at(L"DemonsSoulsLauncher.exe");
    if (!exists(self)) {
        wchar_t me[MAX_PATH * 2];
        GetModuleFileNameW(nullptr, me, MAX_PATH * 2);
        self = me;
    }
    // A path as the script writes it: UTF-8 (the script switches cmd to code page 65001 first, so a folder
    // name outside the OEM code page survives) with % doubled (cmd expands %...% even inside quotes).
    auto oem = [](const wstring& w) {
        int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), nullptr, 0, nullptr, nullptr);
        std::string o(n, '\0');
        WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), o.data(), n, nullptr, nullptr);
        std::string e;
        for (char ch : o) { e += ch; if (ch == '%') e += '%'; }
        return e;
    };
    std::string s = "@echo off\r\nchcp 65001 >nul\r\ntitle Demon's Souls - update\r\n";
    s += "cd /d \"" + oem(g_root) + "\" || goto :failed\r\n";
    if (pull)
        s += "echo Getting the newest version (git pull)...\r\n\"" + oem(git) + "\" pull --ff-only || goto :failed\r\necho.\r\n";
    if (zip)   // the launcher has closed by now; update.py waits a moment if its exe is still in use
        s += "echo Getting the newest version from GitHub...\r\n\"" + oem(venv_python()) + "\" \"" +
             oem(at(L"setup\\update.py")) + "\" --install || goto :failed\r\necho.\r\n";
    // .\ : with NoDefaultCurrentDirectoryInExePath set, cmd does not look in the current folder for a bare name;
    // and no full path, because call expands % a second time (a folder named "100%" would break it)
    s += "call \".\\BUILD.bat\" || goto :failed\r\n"
         "del \"" + oem(pending_marker()) + "\" 2>nul\r\n"
         "echo.\r\necho Up to date. Opening the launcher again...\r\n"
         "start \"\" \"" + oem(self) + "\"\r\ntimeout /t 4 >nul\r\nexit /b 0\r\n"
         ":failed\r\necho.\r\necho The update stopped: see the messages above. Once it is fixed, press \"Check for\r\n"
         "echo updates\" in the launcher again to finish it (or run BUILD.bat).\r\n"
         "start \"\" \"" + oem(self) + "\"\r\npause\r\nexit /b 1\r\n";
    HANDLE f = CreateFileW(bat.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    DWORD wrote = 0;
    bool ok = f != INVALID_HANDLE_VALUE && WriteFile(f, s.data(), (DWORD)s.size(), &wrote, nullptr) && wrote == s.size();
    if (f != INVALID_HANDLE_VALUE) CloseHandle(f);
    if (ok) {   // the marker: written now, removed by the script after a good build
        HANDLE m = CreateFileW(pending_marker().c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        static const char text[] = "An update was started from the launcher and has not finished building yet.\r\n";
        if (m != INVALID_HANDLE_VALUE) { WriteFile(m, text, sizeof text - 1, &wrote, nullptr); CloseHandle(m); }
    }
    HANDLE h = ok ? run_cmd(q(bat), true) : nullptr;
    if (!h) {
        MessageBoxW(g_wnd, L"Could not start the update. Run git pull and BUILD.bat by hand.", L"Check for updates", MB_ICONERROR);
        return;
    }
    CloseHandle(h);
    DestroyWindow(g_wnd);
}

static void on_update_checked(UpdateCheck* c) {
    if (c->quiet) {   // the check at start: a newer release only shows in the status line
        if (c->counted && c->latest != c->current) {
            g_update_notice = c->latest;
            update_status();
        }
        return;
    }
    g_checking = false;
    EnableWindow(item(ID_UPDATE), !g_game);
    update_status();
    if (g_game) return;   // the player started the game meanwhile; the answer can wait for the next press
    if (c->zip) {
        if (!c->counted) {
            // update.py prints error=... when GitHub did not answer; no such line = its Python did not run
            bool py_ran = c->out.find("error=") != std::string::npos;
            wstring msg = py_ran ? L"Could not check for updates (no internet, or GitHub did not answer).\n\n"
                                 : L"Could not check for updates: the setup's Python environment does not start "
                                   L"(Python was removed or upgraded?). Press PLAY: it repairs it, then try again.\n\n";
            msg += widen(c->out.substr(0, 600));
            MessageBoxW(g_wnd, msg.c_str(), L"Check for updates", MB_ICONWARNING);
            return;
        }
        if (c->latest == c->current) {
            MessageBoxW(g_wnd, (L"You have the newest version (" + widen(c->latest) + L").").c_str(),
                        L"Check for updates", MB_ICONINFORMATION);
            return;
        }
        wstring msg = L"Version " + widen(c->latest) + L" is available" +
                      (c->current == "unknown" ? wstring(L".") : L" (you have " + widen(c->current) + L").") +
                      (c->notes.empty() ? wstring() : L"\n\nWhat's new:\n" + widen(c->notes)) +
                      L"\nInstall it now? It downloads it from GitHub (under 1 MB), puts it in this folder "
                      L"(your game files, saves and settings stay) and rebuilds the game in a console window: "
                      L"a few minutes. The launcher closes and opens again when it is done.";
        if (MessageBoxW(g_wnd, msg.c_str(), L"Check for updates", MB_ICONQUESTION | MB_YESNO) == IDYES)
            start_update(L"", false, true);
        return;
    }
    if (!c->fetched || !c->counted) {
        wstring msg = L"Could not check for updates";
        msg += c->fetched ? L" (this copy follows no GitHub branch)." : L" (no internet, or GitHub did not answer).";
        msg += L"\n\n" + widen(c->out.substr(0, 600));
        MessageBoxW(g_wnd, msg.c_str(), L"Check for updates", MB_ICONWARNING);
        return;
    }
    if (c->behind <= 0) {
        MessageBoxW(g_wnd, L"You have the newest version.", L"Check for updates", MB_ICONINFORMATION);
        return;
    }
    wstring msg = std::to_wstring(c->behind) + (c->behind == 1 ? L" update is" : L" updates are") + L" available:\n\n" +
                  widen(c->log) + L"\nInstall now? It downloads them (git pull) and rebuilds the game with BUILD.bat in a "
                  L"console window: a few minutes, longer after big changes. The launcher closes and opens again "
                  L"when it is done.";
    if (MessageBoxW(g_wnd, msg.c_str(), L"Check for updates", MB_ICONQUESTION | MB_YESNO) == IDYES)
        start_update(c->git, true);
}

static void on_update() {
    if (g_checking) return;
    if (g_game) {   // the build would fail on the running game's exe
        MessageBoxW(g_wnd, L"Close the game first: the update rebuilds it.", L"Check for updates", MB_ICONINFORMATION);
        return;
    }
    wchar_t gitbuf[MAX_PATH];
    bool have_git = SearchPathW(nullptr, L"git.exe", nullptr, MAX_PATH, gitbuf, nullptr) > 0;
    wstring git = have_git ? gitbuf : L"";
    bool from_git = exists(at(L".git"));
    bool zip_copy = !from_git && exists(venv_python()) && exists(at(L"setup\\update.py"));
    if (build_pending()) {
        // a copy without git may have stopped while downloading or copying: then fetch it again too
        const wchar_t* msg = zip_copy
            ? L"The last update did not finish.\n\nFinish it now (download it again and rebuild with BUILD.bat)?"
            : L"The last update was downloaded but did not finish building.\n\nBuild it now (BUILD.bat)?";
        if (MessageBoxW(g_wnd, msg, L"Check for updates", MB_ICONQUESTION | MB_YESNO) == IDYES)
            start_update(git, false, zip_copy);
        return;
    }
    g_update_notice.clear();
    if (zip_copy) {
        // not a git clone: ask GitHub's releases (update.py), on a thread like the git check. (A clone
        // without git.exe on PATH -- GitHub Desktop's -- keeps the old message: copying release files over a
        // checkout would leave it modified and block its next pull.)
        UpdateCheck* c = new UpdateCheck;
        c->zip = true;
        c->py = venv_python();
        HANDLE t = CreateThread(nullptr, 0, check_thread, c, 0, nullptr);
        if (!t) { delete c; return; }
        CloseHandle(t);
        g_checking = true;
        EnableWindow(item(ID_UPDATE), FALSE);
        SetWindowTextW(item(ID_STATUS), L"Checking for updates...");
        return;
    }
    if (!from_git || !have_git) {
        const wchar_t* msg = !from_git
            ? L"This copy was not made with git clone, so it cannot download updates by itself.\n\n"
              L"Download the new ZIP from GitHub and unpack it over this folder (keep game, port and deps), "
              L"then press this button again or run BUILD.bat.\n\nRebuild now with the files that are here?"
            : L"Git is not installed, so updates cannot be downloaded. Rebuild with the files that are here?";
        if (MessageBoxW(g_wnd, msg, L"Check for updates", MB_ICONINFORMATION | MB_YESNO) == IDYES)
            start_update(git, false);
        return;
    }
    UpdateCheck* c = new UpdateCheck;
    c->git = git;
    HANDLE t = CreateThread(nullptr, 0, check_thread, c, 0, nullptr);
    if (!t) { delete c; return; }
    CloseHandle(t);
    g_checking = true;
    EnableWindow(item(ID_UPDATE), FALSE);
    SetWindowTextW(item(ID_STATUS), L"Checking for updates...");
}

// ---- the Controls window (fix 103) -----------------------------------------------------------------------
struct KeyDef { const wchar_t* name; int vk; const wchar_t* label; };
static const KeyDef KEYDEFS[] = {
    {L"LMB", VK_LBUTTON, L"Left mouse"}, {L"RMB", VK_RBUTTON, L"Right mouse"}, {L"MMB", VK_MBUTTON, L"Middle mouse"},
    {L"MB4", VK_XBUTTON1, L"Mouse 4"}, {L"MB5", VK_XBUTTON2, L"Mouse 5"}, {L"SPACE", VK_SPACE, L"Space"},
    {L"SHIFT", VK_LSHIFT, L"Shift"}, {L"RSHIFT", VK_RSHIFT, L"Right Shift"}, {L"CTRL", VK_LCONTROL, L"Ctrl"},
    {L"RCTRL", VK_RCONTROL, L"Right Ctrl"}, {L"ALT", VK_LMENU, L"Alt"}, {L"RALT", VK_RMENU, L"Right Alt"},
    {L"TAB", VK_TAB, L"Tab"}, {L"ENTER", VK_RETURN, L"Enter"}, {L"BACK", VK_BACK, L"Backspace"},
    {L"CAPS", VK_CAPITAL, L"Caps Lock"}, {L"UP", VK_UP, L"Up"}, {L"DOWN", VK_DOWN, L"Down"}, {L"LEFT", VK_LEFT, L"Left"},
    {L"RIGHT", VK_RIGHT, L"Right"}, {L"INS", VK_INSERT, L"Insert"}, {L"DEL", VK_DELETE, L"Delete"},
    {L"HOME", VK_HOME, L"Home"}, {L"END", VK_END, L"End"}, {L"PGUP", VK_PRIOR, L"Page Up"},
    {L"PGDN", VK_NEXT, L"Page Down"}, {L"F2", VK_F2, L"F2"}, {L"F3", VK_F3, L"F3"}, {L"F4", VK_F4, L"F4"},
    {L"F5", VK_F5, L"F5"}, {L"F6", VK_F6, L"F6"}, {L"F7", VK_F7, L"F7"}, {L"F10", VK_F10, L"F10"},
    {L"NUM0", VK_NUMPAD0, L"Num 0"}, {L"NUM1", VK_NUMPAD1, L"Num 1"}, {L"NUM2", VK_NUMPAD2, L"Num 2"},
    {L"NUM3", VK_NUMPAD3, L"Num 3"}, {L"NUM4", VK_NUMPAD4, L"Num 4"}, {L"NUM5", VK_NUMPAD5, L"Num 5"},
    {L"NUM6", VK_NUMPAD6, L"Num 6"}, {L"NUM7", VK_NUMPAD7, L"Num 7"}, {L"NUM8", VK_NUMPAD8, L"Num 8"},
    {L"NUM9", VK_NUMPAD9, L"Num 9"}, {L"MINUS", VK_OEM_MINUS, nullptr}, {L"EQUALS", VK_OEM_PLUS, nullptr},
    {L"LBRACKET", VK_OEM_4, nullptr}, {L"RBRACKET", VK_OEM_6, nullptr}, {L"BACKSLASH", VK_OEM_5, nullptr},
    {L"SEMICOLON", VK_OEM_1, nullptr}, {L"QUOTE", VK_OEM_7, nullptr}, {L"COMMA", VK_OEM_COMMA, nullptr},
    {L"PERIOD", VK_OEM_PERIOD, nullptr}, {L"SLASH", VK_OEM_2, nullptr}, {L"GRAVE", VK_OEM_3, nullptr},
};
// A..Z: the US QWERTY scan code of each letter. Letters are stored by position, as the game reads them (fix 69):
// the key pressed here is turned into the US letter in that place, and shown as this keyboard's letter there.
static const unsigned char US_SC[26] = {0x1E, 0x30, 0x2E, 0x20, 0x12, 0x21, 0x22, 0x23, 0x17, 0x24, 0x25, 0x26, 0x32,
                                         0x31, 0x18, 0x19, 0x10, 0x13, 0x1F, 0x14, 0x16, 0x2F, 0x11, 0x2D, 0x15, 0x2C};
static HKL key_layout() { return GetKeyboardLayout(0); }
static wstring key_name_of_vk(int vk) {   // "" = not a key the game takes
    if (vk >= '0' && vk <= '9') return wstring(1, (wchar_t)vk);
    if (vk >= 'A' && vk <= 'Z') {
        if (g_set.by_letter) return wstring(1, (wchar_t)vk);
        UINT sc = MapVirtualKeyExW((UINT)vk, MAPVK_VK_TO_VSC, key_layout());
        for (int i = 0; i < 26; ++i)
            if (US_SC[i] == sc) return wstring(1, (wchar_t)(L'A' + i));
        return wstring(1, (wchar_t)vk);
    }
    for (auto& k : KEYDEFS)
        if (k.vk == vk) return k.name;
    return L"";
}
static wstring key_label(const wstring& name) {   // what a button shows
    if (name.empty()) return L"-";
    if (name.size() == 1 && name[0] >= L'A' && name[0] <= L'Z' && !g_set.by_letter) {
        UINT vk = MapVirtualKeyExW(US_SC[name[0] - L'A'], MAPVK_VSC_TO_VK, key_layout());
        if (vk >= 'A' && vk <= 'Z') return wstring(1, (wchar_t)vk);
    }
    if (name.size() == 1) return name;
    for (auto& k : KEYDEFS)
        if (name == k.name) {
            if (k.label) return k.label;
            wchar_t c = (wchar_t)(MapVirtualKeyExW((UINT)k.vk, MAPVK_VK_TO_CHAR, key_layout()) & 0x7FFF);
            return c > L' ' ? wstring(1, c) : wstring(k.name);
        }
    return name;
}

enum { ID_K_FIRST = 300, ID_K_RESET = 400, ID_K_DONE, ID_K_STATUS, ID_K_HELP };
static HWND g_kw;                 // the Controls window
static int g_listen = -1;         // slot (action * 2 + 0/1) waiting for a key
static bool g_listen_armed;       // everything was released since the click that started it
static bool g_keys_changed;
static ULONGLONG g_key_set_at;    // a key was just set: the click / right-click that set it is not a command too

static void keys_refresh() {
    for (int a = 0; a < N_ACTIONS; ++a)
        for (int k = 0; k < 2; ++k) {
            int slot = a * 2 + k;
            SetWindowTextW(GetDlgItem(g_kw, ID_K_FIRST + slot), slot == g_listen ? L"press a key..." : key_label(g_keys[a][k]).c_str());
        }
}
static void keys_status(const wstring& t) { SetWindowTextW(GetDlgItem(g_kw, ID_K_STATUS), t.c_str()); }

static bool key_down(int vk) { return (GetAsyncKeyState(vk) & 0x8000) != 0; }
static void keys_poll() {   // the timer while a slot listens: the first key or mouse button pressed
    if (g_listen < 0 || GetForegroundWindow() != g_kw) return;
    std::vector<int> vks = {VK_ESCAPE, VK_F1, VK_F8, VK_F9, VK_F11, VK_F12, VK_LWIN, VK_RWIN};
    for (int c = '0'; c <= '9'; ++c) vks.push_back(c);
    for (int c = 'A'; c <= 'Z'; ++c) vks.push_back(c);
    for (auto& k : KEYDEFS) vks.push_back(k.vk);
    int hit = 0;
    for (int vk : vks)
        if (key_down(vk)) { hit = vk; break; }
    if (!g_listen_armed) { if (!hit) g_listen_armed = true; return; }   // the click (or a key) that started it
    if (!hit) return;
    const int slot = g_listen, a = slot / 2, k = slot % 2;
    g_listen = -1;
    KillTimer(g_kw, 1);
    g_key_set_at = GetTickCount64();
    if (hit == VK_ESCAPE) { keys_status(L"Cancelled."); keys_refresh(); return; }
    if (hit == VK_F1 || hit == VK_F8 || hit == VK_F9 || hit == VK_F11 || hit == VK_F12 || hit == VK_LWIN || hit == VK_RWIN) {
        keys_status(L"That key is taken (F1 frees the mouse, F8 marks a stutter, F9 god mode, F11 fullscreen, "
                    L"F12 a capture). Pick another one.");
        keys_refresh();
        return;
    }
    wstring name = key_name_of_vk(hit);
    if (name.empty()) { keys_refresh(); return; }
    wstring moved;
    for (int b = 0; b < N_ACTIONS; ++b)
        for (int j = 0; j < 2; ++j)
            if ((b != a || j != k) && g_keys[b][j] == name) {
                g_keys[b][j].clear();
                if (j == 0) { g_keys[b][0] = g_keys[b][1]; g_keys[b][1].clear(); }
                moved = ACTIONS[b].label;
            }
    g_keys[a][k] = name;
    if (k == 1 && g_keys[a][0].empty()) { g_keys[a][0] = name; g_keys[a][1].clear(); }
    g_keys_changed = true;
    keys_status(moved.empty() ? key_label(name) + L" is now " + ACTIONS[a].label + L"."
                              : key_label(name) + L" is now " + ACTIONS[a].label + L" (taken off " + moved + L").");
    keys_refresh();
}

static LRESULT CALLBACK keys_proc(HWND w, UINT m, WPARAM wp, LPARAM lp) {
    switch (m) {
    case WM_COMMAND: {
        int id = LOWORD(wp);
        if (GetTickCount64() - g_key_set_at < 500) return 0;   // the mouse button / Space that was just bound
        if (id >= ID_K_FIRST && id < ID_K_FIRST + 2 * N_ACTIONS) {
            g_listen = id - ID_K_FIRST;
            SetFocus(w);   // keys go to the window, not to a button (Space would click it again)
            g_listen_armed = false;
            keys_status(L"Press the key or mouse button for " + wstring(ACTIONS[g_listen / 2].label) + L" (Esc cancels).");
            keys_refresh();
            SetTimer(w, 1, 15, nullptr);
        } else if (id == ID_K_RESET) {
            for (int a = 0; a < N_ACTIONS; ++a) split_keys(ACTIONS[a].def, g_keys[a]);
            g_listen = -1;
            g_keys_changed = true;
            keys_status(L"Back to the default keys.");
            keys_refresh();
        } else if (id == ID_K_DONE) DestroyWindow(w);
        return 0;
    }
    case WM_CONTEXTMENU: {   // right-click a slot: clear it
        int id = GetDlgCtrlID((HWND)wp);
        if (GetTickCount64() - g_key_set_at < 500) return 0;   // the right button was just bound
        if (g_listen < 0 && id >= ID_K_FIRST && id < ID_K_FIRST + 2 * N_ACTIONS) {
            int a = (id - ID_K_FIRST) / 2, k = (id - ID_K_FIRST) % 2;
            g_keys[a][k].clear();
            if (k == 0) { g_keys[a][0] = g_keys[a][1]; g_keys[a][1].clear(); }
            g_keys_changed = true;
            keys_status(wstring(ACTIONS[a].label) + (g_keys[a][0].empty() ? L" has no key now." : L": one key less."));
            keys_refresh();
        }
        return 0;
    }
    case WM_TIMER: keys_poll(); return 0;
    case WM_CTLCOLORSTATIC: {
        HDC dc = (HDC)wp;
        SetBkMode(dc, TRANSPARENT);
        int id = GetDlgCtrlID((HWND)lp);
        SetTextColor(dc, GetSysColor(id == ID_K_HELP || id == ID_K_STATUS ? COLOR_GRAYTEXT : COLOR_WINDOWTEXT));
        return (LRESULT)GetSysColorBrush(COLOR_WINDOW);
    }
    case WM_CLOSE: DestroyWindow(w); return 0;
    case WM_DESTROY:
        KillTimer(w, 1);
        g_listen = -1;
        if (g_keys_changed) save_keys();
        g_kw = nullptr;
        EnableWindow(g_wnd, TRUE);
        SetForegroundWindow(g_wnd);
        return 0;
    }
    return DefWindowProcW(w, m, wp, lp);
}

static void on_controls() {
    if (g_kw) { SetForegroundWindow(g_kw); return; }
    read_controls();   // "Keys by letter" decides how letters are stored and shown
    static bool reg = false;
    if (!reg) {
        WNDCLASSEXW wc{sizeof wc};
        wc.lpfnWndProc = keys_proc;
        wc.hInstance = GetModuleHandleW(nullptr);
        wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        wc.hbrBackground = GetSysColorBrush(COLOR_WINDOW);
        wc.lpszClassName = L"DemonsSoulsControls";
        RegisterClassExW(&wc);
        reg = true;
    }
    const int ROWS = (N_ACTIONS + 1) / 2, CW = 320, TOP = 100, RH = 27;
    const int cw = 2 * CW + 16, ch = TOP + ROWS * RH + 90;
    const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU;
    RECT r{0, 0, S(cw), S(ch)};
    AdjustWindowRect(&r, style, FALSE);
    RECT pr;
    GetWindowRect(g_wnd, &pr);
    g_kw = CreateWindowExW(0, L"DemonsSoulsControls", L"Controls - keyboard and mouse", style,
                           pr.left + 20, pr.top + 20, r.right - r.left, r.bottom - r.top, g_wnd, nullptr,
                           GetModuleHandleW(nullptr), nullptr);
    if (!g_kw) return;
    g_keys_changed = false;
    auto make = [&](const wchar_t* cls, const wchar_t* text, DWORD st, int id, int x, int y, int w, int h) {
        HWND c = CreateWindowExW(0, cls, text, WS_CHILD | WS_VISIBLE | st, S(x), S(y), S(w), S(h), g_kw,
                                 (HMENU)(INT_PTR)id, GetModuleHandleW(nullptr), nullptr);
        SendMessageW(c, WM_SETFONT, (WPARAM)g_font, FALSE);
        return c;
    };
    make(L"STATIC", L"Click a slot, then press the key or mouse button for it. Right-click a slot to clear it. "
         L"Two keys per action; a key goes to one action only. Fixed keys: F1 frees the mouse, F8 marks a stutter, "
         L"F9 god mode, F11 / Alt+Enter fullscreen. In menus the left / right mouse buttons always confirm / go back. "
         L"An Xbox controller always works too (DualShock / DualSense: Steam Input or DS4Windows).",
         SS_LEFT, ID_K_HELP, 12, 8, cw - 24, TOP - 14);
    for (int a = 0; a < N_ACTIONS; ++a) {
        int col = a / ROWS, row = a % ROWS;
        int x = 12 + col * (CW + 8), y = TOP + row * RH;
        make(L"STATIC", ACTIONS[a].label, SS_LEFT, -1, x, y + 4, 120, 20);
        for (int k = 0; k < 2; ++k)
            make(WC_BUTTONW, L"", BS_PUSHBUTTON, ID_K_FIRST + a * 2 + k, x + 124 + k * 92, y, 88, 24);
    }
    int y = TOP + ROWS * RH + 8;
    make(L"STATIC", L"", SS_LEFT, ID_K_STATUS, 12, y, cw - 24, 36);
    y += 42;
    make(WC_BUTTONW, L"Reset to defaults", BS_PUSHBUTTON, ID_K_RESET, 12, y, 140, 28);
    make(WC_BUTTONW, L"Done", BS_DEFPUSHBUTTON, ID_K_DONE, cw - 12 - 100, y, 100, 28);
    keys_refresh();
    keys_status(L"The button prompts in the game follow these keys.");
    EnableWindow(g_wnd, FALSE);
    ShowWindow(g_kw, SW_SHOW);
}

static void on_folders() {
    HMENU m = CreatePopupMenu();
    AppendMenuW(m, MF_STRING, ID_F_SAVES, L"Saves");
    AppendMenuW(m, MF_STRING, ID_F_LOGS, L"Logs of the last run");
    AppendMenuW(m, MF_STRING, ID_F_PERF, L"Frame-timing recordings");
    AppendMenuW(m, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(m, MF_STRING, ID_F_REPLACE, L"Texture replacements (textures\\replace)");
    AppendMenuW(m, MF_STRING, ID_F_DUMP, L"Dumped textures (textures\\dump)");
    AppendMenuW(m, MF_STRING, ID_F_MODELS, L"Models");
    AppendMenuW(m, MF_STRING, ID_F_CAPTURES, L"F12 captures");
    AppendMenuW(m, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(m, MF_STRING, ID_F_ROOT, L"The port's folder");
    RECT r;
    GetWindowRect(item(ID_FOLDERS), &r);
    int id = TrackPopupMenu(m, TPM_RETURNCMD | TPM_LEFTALIGN | TPM_BOTTOMALIGN, r.left, r.top, 0, g_wnd, nullptr);
    DestroyMenu(m);
    switch (id) {
    case ID_F_SAVES: {
        wstring p = at(L"gamedata\\dev_hdd0\\home\\00000001\\savedata");
        open_folder(exists(p) ? p : at(L"gamedata"), false);
        break;
    }
    case ID_F_LOGS: open_folder(at(L"logs"), false); break;
    case ID_F_PERF: open_folder(at(L"perf"), false); break;
    case ID_F_REPLACE: CreateDirectoryW(at(L"textures").c_str(), nullptr); open_folder(at(L"textures\\replace"), true); break;
    case ID_F_DUMP: open_folder(at(L"textures\\dump"), false); break;
    case ID_F_MODELS: open_folder(at(L"models"), true); break;
    case ID_F_CAPTURES: open_folder(at(L"captures"), false); break;
    case ID_F_ROOT: open_folder(g_root, false); break;
    }
}

static void create_controls() {
    g_tip = CreateWindowExW(WS_EX_TOPMOST, TOOLTIPS_CLASSW, nullptr, WS_POPUP | TTS_ALWAYSTIP | TTS_NOPREFIX,
                            CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT, CW_USEDEFAULT, g_wnd, nullptr,
                            GetModuleHandleW(nullptr), nullptr);
    SendMessageW(g_tip, TTM_SETMAXTIPWIDTH, 0, S(360));
    SendMessageW(g_tip, TTM_SETDELAYTIME, TTDT_AUTOPOP, 30000);

    const int L = 16, X = 112, W = 428;   // left edge, control column, full width
    int y = 12 + banner_h() + 10;

    label(L"Frame rate", L, y + 3, 92);
    HWND c = add(WC_COMBOBOXW, nullptr, CBS_DROPDOWNLIST | WS_TABSTOP | WS_VSCROLL, ID_FPS, X, y, 240, 200,
                 L"How many frames a second the game runs at. The game runs at real speed at every choice.");
    for (const wchar_t* t : {L"Auto (an even rate for your screen)", L"30 fps (the original game)", L"50 fps (100 Hz screens)",
                             L"60 fps", L"Unlimited (up to 240, no vsync)", L"Custom..."})
        SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)t);
    add(WC_EDITW, nullptr, WS_BORDER | WS_TABSTOP | ES_NUMBER | ES_CENTER, ID_CUSTOM, X + 248, y + 1, 52, 22,
        L"Any whole number from 31 to 240, e.g. 72 or 144 on a 144 Hz screen. Smoothest when your screen's "
        L"refresh rate is a multiple of it.");
    label(L"fps", X + 306, y + 3, 30);
    y += 28;
    label(L"", X, y, W - (X - L), 34, ID_FPS_HINT);
    y += 40;

    label(L"Resolution", L, y + 3, 92);
    c = add(WC_COMBOBOXW, nullptr, CBS_DROPDOWNLIST | WS_TABSTOP | WS_VSCROLL, ID_RES, X, y, 240, 200,
            L"Renders the game at a multiple of its own 1280x720: much sharper, at no cost on the CPU side. "
            L"A mid-range GPU handles 2x easily. The picture always fills the window at 16:9.");
    for (const wchar_t* t : {L"1x  1280x720 (the original)", L"2x  2560x1440", L"3x  3840x2160 (4K)", L"4x  5120x2880"})
        SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)t);
    y += 28;
    add(WC_BUTTONW, L"Sharper shadows too", BS_AUTOCHECKBOX | WS_TABSTOP, ID_SHADOW, X, y, 240, 22,
        L"Also renders the 2048x2048 shadow map at the higher resolution (more GPU work).");
    y += 32;

    label(L"Game", L, y + 3, 92);
    add(WC_BUTTONW, L"Normal", BS_AUTORADIOBUTTON | WS_TABSTOP | WS_GROUP, ID_GAME0, X, y, 64, 22, L"Your game as on the disc.");
    add(WC_BUTTONW, L"PC Remaster", BS_AUTORADIOBUTTON, ID_GAME1, X + 66, y, 96, 22,
        L"The \"Demon's Souls PC Remaster\" mod by fromsoftserve (game_remaster). Install it with "
        L"tools\\install_remaster.py, see README.md.");
    add(WC_BUTTONW, L"My models", BS_AUTORADIOBUTTON, ID_GAME2, X + 164, y, 86, 22,
        L"The copy with your imported models (game_mod, made by tools\\flver_tool.py import).");
    add(WC_BUTTONW, L"Boss rush", BS_AUTORADIOBUTTON, ID_GAME3, X + 252, y, 80, 22,
        L"Boss rush mode: a new character starts in the Nexus with 7,000 souls; each archstone takes you to its "
        L"world's next boss, a timer runs from the first boss fog to King Allant. Its own saves (bossrush\\).");
    y += 30;
    label(L"Boss rush souls", L, y + 3, 92);
    c = add(WC_COMBOBOXW, nullptr, CBS_DROPDOWNLIST | WS_TABSTOP | WS_VSCROLL, ID_BRSOULS, X, y, 140, 200,
            L"Boss rush only: every enemy and boss gives this many times its souls (picking up your bloodstain gives back "
            L"what you lost). The timer shows it when it is not 1x, for videos and runs.");
    for (const wchar_t* t : {L"1x (the game's own)", L"2x", L"3x", L"5x", L"10x"})
        SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)t);
    y += 34;

    const int C2 = L + W / 2;
    add(WC_BUTTONW, L"Start in fullscreen", BS_AUTOCHECKBOX | WS_TABSTOP | WS_GROUP, ID_FULLSCREEN, L, y, 200, 22,
        L"Borderless fullscreen. Alt+Enter or F11 switches in the game.");
    add(WC_BUTTONW, L"Play movies", BS_AUTOCHECKBOX | WS_TABSTOP, ID_MOVIES, C2, y, 200, 22,
        L"The title logo, intro, story and ending movies. Untick to skip them.");
    y += 26;
    add(WC_BUTTONW, L"God mode at start (F9)", BS_AUTOCHECKBOX | WS_TABSTOP, ID_GOD, L, y, 200, 22,
        L"You cannot die and HP, MP and stamina stay full. F9 turns it on and off in the game.");
    add(WC_BUTTONW, L"Record frame timing (F8)", BS_AUTOCHECKBOX | WS_TABSTOP, ID_RECORD, C2, y, 200, 22,
        L"Records frame timing while you play (about 25 MB an hour, no visible cost). Press F8 right after a "
        L"stutter; \"Report a problem\" packs it up for a GitHub issue.");
    y += 26;
    add(WC_BUTTONW, L"Dump textures", BS_AUTOCHECKBOX | WS_TABSTOP, ID_DUMP, L, y, 200, 22,
        L"Saves every texture the game draws to textures\\dump, for texture packs. Replacements in "
        L"textures\\replace always load. May stutter a little in new areas.");
    add(WC_BUTTONW, L"Keys by letter", BS_AUTOCHECKBOX | WS_TABSTOP, ID_LETTER, C2, y, 200, 22,
        L"Keys go by position (ZQSD on AZERTY moves like WASD). Tick this to go by the letter printed on the key.");
    y += 26;
    add(WC_BUTTONW, L"Pin to the fastest CPU cores", BS_AUTOCHECKBOX | WS_TABSTOP, ID_PIN, L, y, 220, 22,
        L"On CPUs with two core groups (e.g. Ryzen X3D) the game runs on the group with the biggest cache. "
        L"Untick if your system manages that itself.");
    add(WC_BUTTONW, L"Keep my build after updates", BS_AUTOCHECKBOX | WS_TABSTOP, ID_NOREBUILD, C2, y, 220, 22,
        L"After an update, Play normally rebuilds the game first (only what changed). Tick this to play the build "
        L"you already have instead; the update's fixes then wait until you run BUILD.bat. An old build with new "
        L"files can misbehave (e.g. a black screen with movies on).");
    y += 26;
    add(WC_BUTTONW, L"Skip the intro (straight to PRESS START)", BS_AUTOCHECKBOX | WS_TABSTOP, ID_SKIPINTRO, L, y, 320, 22,
        L"Confirms the autosave notice, fast-forwards the logos and skips the opening movie, so the game starts at "
        L"the title screen in a few seconds. The story movies later on still play.");
    y += 26;
    add(WC_BUTTONW, L"My screen has G-Sync / FreeSync", BS_AUTOCHECKBOX | WS_TABSTOP, ID_VRR, L, y, 320, 22,
        L"Tick this if your monitor has G-Sync, FreeSync or another variable refresh rate (and it is on). The game "
        L"then lets the monitor follow its frames: 60 fps is smooth at any refresh rate. Without such a monitor "
        L"leave it off: the picture would tear.");
    y += 34;

    label(L"Extra settings", L, y + 3, 92);
    add(WC_EDITW, nullptr, WS_BORDER | WS_TABSTOP | ES_AUTOHSCROLL, ID_EXTRA, X, y, W - (X - L), 22,
        L"For testing, or when asked in an issue: NAME=value pairs separated by spaces, e.g. LD_PSO_ASYNC=0 "
        L"LD_SWAP_RESIZE=0. They are set last, so they win over the choices above.");
    y += 36;

    c = add(WC_BUTTONW, L"PLAY", BS_DEFPUSHBUTTON | WS_TABSTOP | WS_GROUP, ID_PLAY, L, y, W, 46);
    SendMessageW(c, WM_SETFONT, (WPARAM)g_font_big, FALSE);
    y += 54;
    const int bw = (W - 3 * 8) / 4;
    add(WC_BUTTONW, L"Check for updates", BS_PUSHBUTTON | WS_TABSTOP, ID_UPDATE, L, y, bw, 28,
        L"Asks GitHub whether there is a newer version, shows what changed and installs it if you want, then rebuilds "
        L"(BUILD.bat). No git needed: a copy from a release ZIP gets the newest release.");
    add(WC_BUTTONW, L"Report a problem", BS_PUSHBUTTON | WS_TABSTOP, ID_REPORT, L + (bw + 8), y, bw, 28,
        L"Packs your last session (recording, F8 marks, log, PC specs) into a zip and opens a GitHub issue (REPORT.bat).");
    add(WC_BUTTONW, L"Controls", BS_PUSHBUTTON | WS_TABSTOP, ID_CONTROLS, L + 2 * (bw + 8), y, bw, 28,
        L"Change the keyboard and mouse keys. The game's button prompts follow them.");
    add(WC_BUTTONW, L"Folders \u25b4", BS_PUSHBUTTON | WS_TABSTOP, ID_FOLDERS, L + 3 * (bw + 8), y, bw, 28,
        L"Saves, logs, recordings, texture and model folders.");
    y += 36;
    label(L"", L, y, W, 20, ID_STATUS);
}

static int client_h() { return 12 + banner_h() + 10 + 28 + 40 + 28 + 32 + 30 + 34 + 26 * 5 + 34 + 36 + 54 + 36 + 20 + 12; }

static LRESULT CALLBACK wndproc(HWND w, UINT m, WPARAM wp, LPARAM lp) {
    switch (m) {
    case WM_CREATE:
        g_wnd = w;
        create_controls();
        write_controls();
        update_status();
        // Players rarely press Check for updates: a copy without git asks GitHub's releases once at start, in
        // the background, and a newer one shows in the status line (no message box; offline = nothing).
        if (!exists(at(L".git")) && exists(venv_python()) && exists(at(L"setup\\update.py"))) {
            UpdateCheck* c = new UpdateCheck;
            c->zip = c->quiet = true;
            c->py = venv_python();
            HANDLE t = CreateThread(nullptr, 0, check_thread, c, 0, nullptr);
            if (t) CloseHandle(t);
            else delete c;
        }
        return 0;
    case WM_COMMAND: {
        int id = LOWORD(wp), code = HIWORD(wp);
        if (id == ID_PLAY) on_play();
        else if (id == ID_UPDATE) on_update();
        else if (id == ID_REPORT) run_report(w);
        else if (id == ID_CONTROLS) on_controls();
        else if (id == ID_FOLDERS) on_folders();
        else if (id == ID_FPS && code == CBN_SELCHANGE) {
            update_fps_hint();
            if (SendMessageW(item(ID_FPS), CB_GETCURSEL, 0, 0) == FPS_CUSTOM) {
                SetFocus(item(ID_CUSTOM));
                SendMessageW(item(ID_CUSTOM), EM_SETSEL, 0, -1);
            }
        } else if (id == ID_CUSTOM && code == EN_CHANGE && !g_loading) update_fps_hint();
        else if (id == ID_VRR && code == BN_CLICKED) update_fps_hint();
        else if (id >= ID_GAME0 && id <= ID_GAME3 && code == BN_CLICKED)
            EnableWindow(item(ID_BRSOULS), checked(ID_GAME3));
        else if (id == ID_RES && code == CBN_SELCHANGE)
            EnableWindow(item(ID_SHADOW), SendMessageW(item(ID_RES), CB_GETCURSEL, 0, 0) > 0);
        return 0;
    }
    case WM_GAME_DONE: {
        CloseHandle(g_game);
        g_game = nullptr;
        EnableWindow(item(ID_PLAY), TRUE);
        EnableWindow(item(ID_UPDATE), !g_checking);
        SetWindowTextW(item(ID_PLAY), L"PLAY");
        update_status();
        ShowWindow(w, SW_RESTORE);
        SetForegroundWindow(w);
        if (wp != 0) show_crash(w, (DWORD)wp);
        return 0;
    }
    case WM_UPDATE_CHECKED: {
        UpdateCheck* c = (UpdateCheck*)lp;
        on_update_checked(c);
        delete c;
        return 0;
    }
    case WM_CTLCOLORSTATIC: {
        HDC dc = (HDC)wp;
        int id = GetDlgCtrlID((HWND)lp);
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, GetSysColor(id == ID_FPS_HINT || id == ID_STATUS ? COLOR_GRAYTEXT : COLOR_WINDOWTEXT));
        return (LRESULT)GetSysColorBrush(COLOR_WINDOW);
    }
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(w, &ps);
        RECT rc;
        GetClientRect(w, &rc);
        if (g_banner) {
            Gdiplus::Graphics gfx(dc);
            gfx.SetInterpolationMode(Gdiplus::InterpolationModeHighQualityBicubic);
            int bw = S(240), bh = S(132);
            gfx.DrawImage(g_banner, (rc.right - bw) / 2, S(12), bw, bh);
        } else {
            RECT t{0, S(12), rc.right, S(12 + 44)};
            HGDIOBJ old = SelectObject(dc, g_font_title);
            SetBkMode(dc, TRANSPARENT);
            DrawTextW(dc, L"Demon's Souls", -1, &t, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
            SelectObject(dc, old);
        }
        EndPaint(w, &ps);
        return 0;
    }
    case WM_CLOSE:
        read_controls();
        save_settings();
        DestroyWindow(w);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(w, m, wp, lp);
}

static HFONT make_font(int pt_scale_pct, bool bold) {
    NONCLIENTMETRICSW nm{};
    nm.cbSize = sizeof nm;
    SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof nm, &nm, 0);
    LOGFONTW lf = nm.lfMessageFont;
    lf.lfHeight = MulDiv(lf.lfHeight, pt_scale_pct, 100);
    if (bold) lf.lfWeight = FW_BOLD;
    return CreateFontIndirectW(&lf);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, LPWSTR, int show) {
    if (!find_root()) {
        MessageBoxW(nullptr, L"Put DemonsSoulsLauncher.exe in the Demon's Souls folder, next to PLAY.bat.",
                    L"Demon's Souls", MB_ICONERROR);
        return 1;
    }
    g_ini = at(L"launcher.ini");
    load_settings();

    int argc = 0;
    wchar_t** argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    bool play_now = false;
    for (int i = 1; i < argc; ++i)
        if (!_wcsicmp(argv[i], L"--play")) play_now = true;
    LocalFree(argv);

    // --play: no window, the saved settings; a crash still gets its message.
    if (play_now) {
        if (!can_play(nullptr, g_set)) return 1;
        HANDLE h = start_game(g_set);
        if (!h) return 1;
        WaitForSingleObject(h, INFINITE);
        DWORD code = 0;
        GetExitCodeProcess(h, &code);
        CloseHandle(h);
        if (code) show_crash(nullptr, code);
        return (int)code;
    }

    INITCOMMONCONTROLSEX icc{sizeof icc, ICC_STANDARD_CLASSES | ICC_WIN95_CLASSES};
    InitCommonControlsEx(&icc);
    ULONG_PTR gdip = 0;
    Gdiplus::GdiplusStartupInput gsi;
    Gdiplus::GdiplusStartup(&gdip, &gsi, nullptr);
    // The banner is the game's own ICON0.PNG from your copy of the game (none ships with this repo).
    wstring icon = at(L"game\\PS3_GAME\\ICON0.PNG");
    if (exists(icon)) {
        g_banner = Gdiplus::Bitmap::FromFile(icon.c_str());
        if (g_banner && g_banner->GetLastStatus() != Gdiplus::Ok) { delete g_banner; g_banner = nullptr; }
    }

    HDC sdc = GetDC(nullptr);
    g_dpi = GetDeviceCaps(sdc, LOGPIXELSY);
    ReleaseDC(nullptr, sdc);
    g_hz = refresh_hz();
    g_font = make_font(100, false);
    g_font_big = make_font(150, true);
    g_font_title = make_font(220, true);

    WNDCLASSEXW wc{sizeof wc};
    wc.lpfnWndProc = wndproc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = GetSysColorBrush(COLOR_WINDOW);
    wc.lpszClassName = L"DemonsSoulsLauncher";
    wc.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    RegisterClassExW(&wc);

    const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    RECT r{0, 0, S(16 + 428 + 16), S(client_h())};
    AdjustWindowRect(&r, style, FALSE);
    HWND w = CreateWindowExW(0, wc.lpszClassName, L"Demon's Souls - PC port launcher", style, CW_USEDEFAULT,
                             CW_USEDEFAULT, r.right - r.left, r.bottom - r.top, nullptr, nullptr, inst, nullptr);
    if (!w) return 1;
    ShowWindow(w, show);
    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        if (IsDialogMessageW(w, &msg)) continue;
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    delete g_banner;
    Gdiplus::GdiplusShutdown(gdip);
    return 0;
}
