/* Demon's Souls boss rush mode: the run timer, per-boss splits, results file and starting souls.
 *
 * Only with DES_BOSS_RUSH=1 (the launcher's "Game: Boss rush"; PLAY.bat sets it with game_bossrush/, made by
 * tools/make_boss_rush.py). The boss rush module in the game scripts (tools/boss_rush/bossrush.lua) sends its
 * events through print(): the game's print hook (func_00C02C78, patches/lifted-code.patch) hands every
 * "BRX ..." line here, and the per-step hook (func_0001B8D0) calls br_step() / br_take_souls():
 *   BRX reset          a new run: timer cleared
 *   BRX start          the first boss fog: the timer starts (ignored while it runs)
 *   BRX boss <name>    through a boss's fog: the split being run
 *   BRX split <name>   that boss died: its split is recorded
 *   BRX end            King Allant died: the timer stops, results written
 *   BRX souls <n>      a new character's starting souls (the step hook adds them to the player)
 * The timer is real time and never pauses (deaths and loads count), except while the game is closed:
 * its state goes to <DES_BOSS_RUSH_DIR>\state.txt every few seconds and is picked up again on the next
 * start. Splits: splits.txt there (rewritten on every split), results: results.txt. DES_BOSS_RUSH_DIR unset:
 * <PS3_HDD0_ROOT>\..\bossrush.
 * The clock is drawn at the bottom centre in the game's own font (<dir>\\timer_font.bin, which
 * tools/make_boss_rush.py makes from the game files): the text is composed here into a picture with a soft shadow
 * and handed to the renderer's image overlay (ps3_overlay_image). Without the font file: the text overlay
 * (ps3_overlay_set, a built-in 5x7 font). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>
#include <atomic>
#include <algorithm>
#include <math.h>
#ifdef _WIN32
#include <direct.h>
#else
#include <sys/stat.h>
#endif

extern "C" unsigned long long ps3_qpc_us(void);
extern "C" void ps3_overlay_set(int line, const char* text);
extern "C" void ps3_overlay_image(const void* rgba, int w, int h, float cx, float bottom, float height);

namespace {
struct Split { std::string name; unsigned long long total_us, seg_us; };
/* A spin lock, not std::mutex: the newer STL's std::mutex fails fast (0xC0000409) against an older
 * msvcp140.dll, and the game and its step hook only touch this a few times a second anyway. */
std::atomic_flag g_mu = ATOMIC_FLAG_INIT;
struct Lock {
    Lock() { while (g_mu.test_and_set(std::memory_order_acquire)) { } }
    ~Lock() { g_mu.clear(std::memory_order_release); }
};
int g_on = -1;
bool g_running = false, g_done = false;
unsigned long long g_base_us = 0;      /* elapsed before this session */
unsigned long long g_t0 = 0;           /* qpc at (re)start in this session */
unsigned long long g_seg_start = 0;    /* run time when the current boss's fog was passed */
std::string g_boss;
std::vector<Split> g_splits;
unsigned long long g_last_save = 0;
std::string g_dir;

// DES_BR_SOULS: the boss rush souls multiplier (the launcher's choice; make_boss_rush.py builds it in)
int souls_mult()
{
    static int m = -1;
    if (m < 0) { const char* e = getenv("DES_BR_SOULS"); m = e ? atoi(e) : 1; if (m < 1) m = 1; if (m > 100) m = 100; }
    return m;
}

bool on()
{
    if (g_on < 0) { const char* e = getenv("DES_BOSS_RUSH"); g_on = e && *e && *e != '0'; }
    return g_on == 1;
}

const std::string& dir()
{
    if (g_dir.empty()) {
        const char* own = getenv("DES_BOSS_RUSH_DIR");
        if (own && *own) {
            g_dir = own;
            while (!g_dir.empty() && (g_dir.back() == '\\' || g_dir.back() == '/')) g_dir.pop_back();
#ifdef _WIN32
            (void)_mkdir(g_dir.c_str());
#else
            (void)mkdir(g_dir.c_str(), 0755);
#endif
            return g_dir;
        }
        const char* h = getenv("PS3_HDD0_ROOT");
        std::string d = h && *h ? std::string(h) : std::string(".");
        while (!d.empty() && (d.back() == '\\' || d.back() == '/')) d.pop_back();
        const size_t cut = d.find_last_of("\\/");
        d = (cut == std::string::npos ? std::string(".") : d.substr(0, cut)) + "\\bossrush";
#ifdef _WIN32
        (void)_mkdir(d.c_str());
#else
        (void)mkdir(d.c_str(), 0755);
#endif
        g_dir = d;
    }
    return g_dir;
}

/* Pauses (loading screens, cutscenes, the title screen, before the first time in the game): br_mark() and the
 * step hook tick; paused time moves g_t0 forward, so it never reaches the run time. */
unsigned long long g_tick = 0;          /* qpc of the previous tick */
unsigned long long g_mark_us = 0;       /* qpc of the last br_mark */
int g_mark_kind = 0;                    /* its kind (2 cutscene, 3 title) */
bool g_loading = false;                 /* "BRX loading" until "BRX ingame": a map is loading */
int g_pause_kind = -1;                  /* the pause going on (0 none, 4 not in the game yet), for the log */
unsigned long long g_pause_from = 0, g_pause_run = 0;
bool g_visible = false;   // set by the first "BRX ingame" (1 s after a map load): hidden on the title and creation
const char* pause_name(int k)
{
    return k == 1 ? "loading screen" : k == 2 ? "cutscene" : k == 3 ? "title screen" : "not in the game yet";
}
void tick(unsigned long long now, int pause)   /* pause: 0 = counts, else the reason */
{
    if (g_tick && now > g_tick && g_running && pause) g_t0 += now - g_tick;
    g_tick = now;
    if (pause != g_pause_kind) {
        if (g_pause_kind > 0 && g_running)
            fprintf(stderr, "[bossrush] timer paused %.1f s (%s)%s", (double)(now - g_pause_from) / 1e6,
                    pause_name(g_pause_kind), "\n");
        g_pause_kind = pause;
        g_pause_from = now;
    }
}
int pause_now(unsigned long long now)
{
    if (g_mark_us && now - g_mark_us < 60000ull) return g_mark_kind;
    if (g_loading) return 1;
    return g_visible ? 0 : 4;
}

unsigned long long now_run_us()
{
    return g_running ? g_base_us + (ps3_qpc_us() - g_t0) : g_base_us;
}

std::string fmt(unsigned long long us, bool tenths = true)
{
    const unsigned long long t = us / 100000ull;   /* tenths */
    const unsigned long long h = t / 36000ull, m = (t / 600ull) % 60ull, s = (t / 10ull) % 60ull, d = t % 10ull;
    char b[32];
    if (h) snprintf(b, sizeof b, tenths ? "%llu:%02llu:%02llu.%llu" : "%llu:%02llu:%02llu", h, m, s, d);
    else snprintf(b, sizeof b, tenths ? "%llu:%02llu.%llu" : "%llu:%02llu", m, s, d);
    return b;
}

void save_state()
{
    const std::string p = dir() + "\\state.txt";
    FILE* f = fopen(p.c_str(), "w");
    if (!f) return;
    fprintf(f, "run_us %llu\nrunning %d\ndone %d\nseg_start %llu\nboss %s\n", now_run_us(), g_running ? 1 : 0,
            g_done ? 1 : 0, g_seg_start, g_boss.c_str());
    for (const Split& s : g_splits) fprintf(f, "split %llu %llu %s\n", s.total_us, s.seg_us, s.name.c_str());
    fclose(f);
}

void load_state()
{
    const std::string p = dir() + "\\state.txt";
    FILE* f = fopen(p.c_str(), "r");
    if (!f) return;
    char line[256];
    while (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\r\n")] = 0;
        unsigned long long a = 0, b = 0; int n = 0;
        if (sscanf(line, "run_us %llu", &a) == 1) g_base_us = a;
        else if (sscanf(line, "running %d", &n) == 1) g_running = n != 0;
        else if (sscanf(line, "done %d", &n) == 1) g_done = n != 0;
        else if (sscanf(line, "seg_start %llu", &a) == 1) g_seg_start = a;
        else if (!strncmp(line, "boss ", 5)) g_boss = line + 5;
        else if (sscanf(line, "split %llu %llu %n", &a, &b, &n) == 2) g_splits.push_back({ line + n, a, b });
    }
    fclose(f);
    g_t0 = g_tick = ps3_qpc_us();
    fprintf(stderr, "[bossrush] resumed: %s, %d splits%s\n", fmt(g_base_us).c_str(), (int)g_splits.size(),
            g_running ? " (running)" : "");
}

void write_splits(const char* file, bool final)
{
    const std::string p = dir() + "\\" + file;
    FILE* f = fopen(p.c_str(), "w");
    if (!f) return;
    fprintf(f, "Demon's Souls boss rush%s\n", final ? " - results" : " - splits so far");
    fprintf(f, "Souls x%d%s\n\n", souls_mult(), souls_mult() == 1 ? " (the game's own)" : "");
    int i = 1;
    for (const Split& s : g_splits)
        fprintf(f, "%2d  %-22s %10s  (+%s)\n", i++, s.name.c_str(), fmt(s.total_us).c_str(), fmt(s.seg_us).c_str());
    fprintf(f, "\n%s  %s\n", final ? "Final time" : "Time so far", fmt(now_run_us()).c_str());
    fclose(f);
}

// ---- the clock in the game's font -------------------------------------------------------------------------
struct Glyph { int pre = 0, adv = 0, w = 0, h = 0; std::vector<unsigned char> la; };   // (luminance, alpha) pairs
struct Font { int cell = 0; Glyph g[128]; };
Font g_font;
int g_font_state = 0;   // 0 not tried, 1 loaded, -1 none (the text overlay then)

bool font_load()
{
    if (g_font_state) return g_font_state > 0;
    g_font_state = -1;
    FILE* f = fopen((dir() + "\\timer_font.bin").c_str(), "rb");
    if (!f) return false;
    unsigned hdr[3] = {0, 0, 0};
    bool ok = fread(hdr, 4, 3, f) == 3 && hdr[0] == 0x31465242u /* BRF1 */ && hdr[1] < 256 && hdr[2] > 0 && hdr[2] < 512;
    for (unsigned i = 0; ok && i < hdr[1]; i++) {
        int r[5];
        if (fread(r, 4, 5, f) != 5 || r[3] < 0 || r[4] < 0 || r[3] > 1024 || r[4] > 1024) { ok = false; break; }
        Glyph gl;
        gl.pre = r[1]; gl.adv = r[2]; gl.w = r[3]; gl.h = r[4];
        gl.la.resize((size_t)gl.w * gl.h * 2);
        if (!gl.la.empty() && fread(gl.la.data(), 1, gl.la.size(), f) != gl.la.size()) { ok = false; break; }
        if (r[0] > 0 && r[0] < 128) g_font.g[r[0]] = std::move(gl);
    }
    fclose(f);
    if (!ok) return false;
    g_font.cell = (int)hdr[2];
    g_font_state = 1;
    fprintf(stderr, "[bossrush] timer font: %u letters, %d px\n", hdr[1], g_font.cell);
    return true;
}

struct Part { std::string text; float scale; float r, g, b; };
struct Canvas {
    int w, h;
    std::vector<float> col, a, sh;   // premultiplied colour (3 a pixel), text alpha, shadow alpha
    Canvas(int W, int H) : w(W), h(H), col((size_t)W * H * 3, 0.0f), a((size_t)W * H, 0.0f), sh((size_t)W * H, 0.0f) {}
};

float text_width(const Part& p)
{
    float x = 0;
    for (unsigned char c : p.text) if (c < 128) x += g_font.g[c].adv * p.scale;
    return x;
}

// One glyph at (x, y) scaled, bilinear from the font's pixels: into the text layer, and (offset) the shadow layer.
void draw_glyph(Canvas& cv, const Glyph& gl, float x, float y, const Part& p, float shoff)
{
    const int dw = (int)(gl.w * p.scale + 1), dh = (int)(gl.h * p.scale + 1);
    for (int dy = 0; dy < dh; dy++)
        for (int dx = 0; dx < dw; dx++) {
            const float sx = (dx + 0.5f) / p.scale - 0.5f, sy = (dy + 0.5f) / p.scale - 0.5f;
            const int x0 = (int)floorf(sx), y0 = (int)floorf(sy);
            const float fx = sx - x0, fy = sy - y0;
            float L = 0, A = 0;
            for (int k = 0; k < 4; k++) {
                const int xi = x0 + (k & 1), yi = y0 + (k >> 1);
                if (xi < 0 || yi < 0 || xi >= gl.w || yi >= gl.h) continue;
                const float wgt = ((k & 1) ? fx : 1 - fx) * ((k >> 1) ? fy : 1 - fy);
                const unsigned char* q = &gl.la[((size_t)yi * gl.w + xi) * 2];
                L += wgt * q[0] * q[1]; A += wgt * q[1];
            }
            if (A <= 0.5f) continue;
            const float lum = L / A / 255.0f, al = A / 255.0f;
            const int px = (int)(x + gl.pre * p.scale) + dx, py = (int)y + dy;
            if (px >= 0 && py >= 0 && px < cv.w && py < cv.h) {
                const size_t i = (size_t)py * cv.w + px;
                const float keep = 1.0f - al;
                cv.col[i * 3 + 0] = cv.col[i * 3 + 0] * keep + p.r * lum * al;
                cv.col[i * 3 + 1] = cv.col[i * 3 + 1] * keep + p.g * lum * al;
                cv.col[i * 3 + 2] = cv.col[i * 3 + 2] * keep + p.b * lum * al;
                cv.a[i] = cv.a[i] * keep + al;
            }
            const int qx = px + (int)shoff, qy = py + (int)shoff;
            if (qx >= 0 && qy >= 0 && qx < cv.w && qy < cv.h) {
                float& s2 = cv.sh[(size_t)qy * cv.w + qx];
                if (al > s2) s2 = al;
            }
        }
}

void blur(std::vector<float>& v, int w, int h, int r)
{
    std::vector<float> t(v.size());
    for (int pass = 0; pass < 2; pass++) {
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++) {
                float sum = 0; int n = 0;
                for (int k = -r; k <= r; k++) { const int xx = x + k; if (xx >= 0 && xx < w) { sum += v[(size_t)y * w + xx]; n++; } }
                t[(size_t)y * w + x] = sum / n;
            }
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++) {
                float sum = 0; int n = 0;
                for (int k = -r; k <= r; k++) { const int yy = y + k; if (yy >= 0 && yy < h) { sum += t[(size_t)yy * w + x]; n++; } }
                v[(size_t)y * w + x] = sum / n;
            }
    }
}

// The clock: line 0 the run time (large), line 1 the parts side by side (small); bottom centre of the screen.
void show_image(const std::vector<Part>& l0, const std::vector<Part>& l1)
{
    const float cell = (float)g_font.cell, gap1 = cell * 0.18f;
    auto line_w = [&](const std::vector<Part>& l) {
        float x = 0;
        for (size_t i = 0; i < l.size(); i++) x += text_width(l[i]) + (i ? cell * l[i].scale * 0.6f : 0.0f);
        return x;
    };
    const float h0 = l0.empty() ? 0 : cell * l0[0].scale, h1 = l1.empty() ? 0 : cell * l1[0].scale;
    const int pad = (int)(cell * 0.25f);
    const int W = (int)std::max(line_w(l0), line_w(l1)) + 2 * pad + 2;
    const int H = (int)(h0 + (h1 > 0 ? gap1 + h1 : 0)) + 2 * pad + 2;
    if (W <= 2 * pad + 2 || W > 2048 || H > 512) { ps3_overlay_image(nullptr, 0, 0, 0, 0, 0); return; }
    Canvas cv(W, H);
    const float shoff = cell * 0.05f;
    auto draw_line = [&](const std::vector<Part>& l, float y) {
        float x = (W - line_w(l)) * 0.5f;
        for (size_t i = 0; i < l.size(); i++) {
            if (i) x += cell * l[i].scale * 0.6f;
            for (unsigned char c : l[i].text) {
                if (c >= 128) continue;
                const Glyph& gl = g_font.g[c];
                if (gl.w) draw_glyph(cv, gl, x, y, l[i], shoff);
                x += gl.adv * l[i].scale;
            }
        }
    };
    draw_line(l0, (float)pad);
    draw_line(l1, pad + h0 + gap1);
    blur(cv.sh, W, H, std::max(1, (int)(cell * 0.05f)));
    std::vector<unsigned char> px((size_t)W * H * 4);
    for (size_t i = 0; i < (size_t)W * H; i++) {   // text over its shadow (black at 85%), premultiplied
        const float sa = std::min(1.0f, cv.sh[i] * 1.6f) * 0.85f, ta = cv.a[i];
        const float out_a = ta + sa * (1.0f - ta);
        for (int c = 0; c < 3; c++) px[i * 4 + c] = (unsigned char)std::min(255.0f, cv.col[i * 3 + c] * 255.0f + 0.5f);
        px[i * 4 + 3] = (unsigned char)std::min(255.0f, out_a * 255.0f + 0.5f);
    }
    // on screen: a cell of the font is about 37 px of a 720 px tall picture, whatever the window size
    ps3_overlay_image(px.data(), W, H, 0.5f, 0.975f, H * (37.0f / cell) / 720.0f);
}

void show()
{
    if (!g_visible) return;   // nothing drawn yet: the overlay starts empty
    std::string t0 = fmt(now_run_us());
    if (g_done) t0 = "Final " + t0;
    static const float CREAM[3] = {232 / 255.f, 222 / 255.f, 196 / 255.f}, GOLD[3] = {214 / 255.f, 178 / 255.f, 102 / 255.f},
                       DIM[3] = {170 / 255.f, 160 / 255.f, 140 / 255.f};
    std::vector<Part> l0 = {{t0, 1.0f, CREAM[0], CREAM[1], CREAM[2]}}, l1;
    if (!g_splits.empty()) {
        const Split& s = g_splits.back();
        l1 = {{s.name, 0.45f, GOLD[0], GOLD[1], GOLD[2]}, {fmt(s.total_us), 0.45f, CREAM[0], CREAM[1], CREAM[2]},
              {"+" + fmt(s.seg_us), 0.45f, DIM[0], DIM[1], DIM[2]}};
    } else if (!g_boss.empty())
        l1 = {{g_boss, 0.45f, GOLD[0], GOLD[1], GOLD[2]}};
    if (souls_mult() > 1)   // shown for videos and runs: not the game's own souls
        l1.insert(l1.begin(), {"Souls x" + std::to_string(souls_mult()), 0.45f, GOLD[0], GOLD[1], GOLD[2]});
    if (font_load()) {
        static std::string last;
        std::string key = t0;
        for (const Part& p : l1) key += "|" + p.text;
        if (key == last) return;
        last = key;
        ps3_overlay_set(0, "");
        ps3_overlay_set(1, "");
        show_image(l0, l1);
        return;
    }
    ps3_overlay_set(0, (g_done ? "FINAL " + fmt(now_run_us()) : fmt(now_run_us())).c_str());
    if (!g_splits.empty()) {
        const Split& s = g_splits.back();
        const std::string line1 = s.name + "  " + fmt(s.total_us) + "  (+" + fmt(s.seg_us) + ")";
        ps3_overlay_set(1, line1.c_str());
    } else ps3_overlay_set(1, g_boss.empty() ? "" : g_boss.c_str());
    ps3_overlay_set(2, souls_mult() > 1 ? ("SOULS X" + std::to_string(souls_mult())).c_str() : "");
}

int g_souls_pending = 0;
bool g_loaded = false;
void ensure_loaded()
{
    if (!g_loaded) { g_loaded = true; load_state(); }
}
}  // namespace

extern "C" void br_lua_line(const char* line)
{
    if (!on() || !line) return;
    Lock lk;
    ensure_loaded();
    if (!strcmp(line, "loading")) {
        const unsigned long long t = ps3_qpc_us();
        tick(t, pause_now(t));
        g_loading = true;
        tick(t, pause_now(t));
        return;
    }
    if (!strcmp(line, "ingame")) {
        /* 1 s of play after the load: a loading (or not-in-the-game-yet) pause ends, and that second counts */
        const unsigned long long t = ps3_qpc_us();
        tick(t, pause_now(t));
        if ((g_pause_kind == 1 || g_pause_kind == 4) && g_running) {
            const unsigned long long back = t - g_pause_from < 1000000ull ? t - g_pause_from : 1000000ull;
            g_t0 -= back;
            g_pause_from += back;   /* the logged pause ends where play began */
        }
        g_loading = false;
        if (!g_visible) fprintf(stderr, "[bossrush] in game: timer shown\n");
        g_visible = true;
        show();
        return;   // nothing changed to save
    } else if (!strcmp(line, "reset")) {
        g_running = g_done = false; g_base_us = g_seg_start = 0; g_boss.clear(); g_splits.clear();
        fprintf(stderr, "[bossrush] reset\n");
    } else if (!strcmp(line, "start")) {
        if (!g_running && !g_done) {
            g_running = true; g_base_us = 0; g_t0 = g_tick = ps3_qpc_us(); g_seg_start = 0; g_splits.clear();
            fprintf(stderr, "[bossrush] timer started\n");
        }
    } else if (!strncmp(line, "boss ", 5)) {
        if (g_boss != line + 5) { g_boss = line + 5; g_seg_start = now_run_us(); }
        fprintf(stderr, "[bossrush] fighting %s at %s\n", g_boss.c_str(), fmt(now_run_us()).c_str());
    } else if (!strncmp(line, "split ", 6)) {
        if (g_running) {
            const unsigned long long t = now_run_us();
            const unsigned long long prev = g_splits.empty() ? 0 : g_splits.back().total_us;
            const unsigned long long from = prev;   /* a split's segment: since the previous split */
            g_splits.push_back({ line + 6, t, t - from });
            g_boss.clear();
            write_splits("splits.txt", false);
            fprintf(stderr, "[bossrush] split %s %s (+%s)\n", line + 6, fmt(t).c_str(), fmt(t - from).c_str());
        }
    } else if (!strncmp(line, "souls ", 6)) {
        g_souls_pending += atoi(line + 6);   /* the step hook adds them (br_take_souls) */
        fprintf(stderr, "[bossrush] %d souls queued\n", atoi(line + 6));
    } else if (!strcmp(line, "end")) {
        if (g_running) {
            g_base_us = now_run_us(); g_running = false; g_done = true;
            write_splits("results.txt", true);
            fprintf(stderr, "[bossrush] FINAL %s\n", fmt(g_base_us).c_str());
        }
    }
    save_state();
    g_last_save = ps3_qpc_us();
    show();
}

/* Every game step: refresh the clock; save the state every 5 s while running. */
extern "C" void br_step(void)
{
    if (!on()) return;
    Lock lk;
    ensure_loaded();
    const unsigned long long t = ps3_qpc_us();
    tick(t, pause_now(t));
    static unsigned long long last_show;
    if (t - last_show >= 50000ull) { last_show = t; show(); }
    if (g_running && t - g_last_save >= 5000000ull) { g_last_save = t; save_state(); }
}

/* Souls a "BRX souls <n>" event asked for; the step hook adds them to the player once there is one and
 * calls br_souls_done(). */
extern "C" int br_take_souls(void)
{
    if (!on()) return 0;
    Lock lk;
    return g_souls_pending;
}

extern "C" void br_souls_done(int n)
{
    Lock lk;
    g_souls_pending -= n;
}

/* Every frame of a loading screen (1), a cutscene (2) or the title screen (3), from the lifted code: the run
 * timer leaves that time out. */
extern "C" void br_mark(int kind)
{
    if (!on()) return;
    Lock lk;
    const unsigned long long t = ps3_qpc_us();
    g_mark_us = t;
    g_mark_kind = kind;
    tick(t, kind);
}

/* DES_BOSS_RUSH is on: the lifted character start (ppu_recomp_018.cpp, func_00185158) sends a new character
 * straight to the Nexus in soul form, without the "journey to the Nexus?" prompt or the tutorial. */
extern "C" int br_on(void)
{
    return on() ? 1 : 0;
}
