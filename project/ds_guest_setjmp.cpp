/* Guest setjmp/longjmp for lifted code (Demon's Souls fix 101).
 *
 * The game's libc setjmp (func_01674938) stores r1, r2, r13-r31, LR, CR and f14-f31 in a jmp_buf, and longjmp
 * (func_01674A5C) loads them back and "returns" through the restored LR, so setjmp appears to return a second
 * time. Lifted code cannot do that: the lifted longjmp only overwrites the guest registers and returns to its own
 * caller, which then carries on with another function's r1/r14-r31 -- garbage pointers a few calls later.
 * Two users matter: Lua 5.0's error handling (luaD_throw -> longjmp to luaD_rawrunprotected) and the game's
 * "try" wrappers (a TLS flag at r13-28104 plus a TLS jmp_buf at r13-28648; the heap allocator longjmps there when
 * an allocation fails while the flag is set). Penetrator's fight throws a Lua error (luaD_throw, 0x00CAE768)
 * back to a protected call (setjmp at 0x00CAF1E8); without this the game crashed in luaV_execute right after.
 *
 * The fix: every guest setjmp call site arms a host jmp_buf (ds_sj_arm) and host-setjmps on it in the lifted
 * function's own frame. The lifted longjmp, after loading the guest registers, calls ds_sj_jump, which finds the
 * host jmp_buf armed for that guest buffer and host-longjmps to it: the lifted function resumes right after its
 * setjmp call with the guest registers longjmp restored, exactly like the PS3.
 *
 * Armed buffers are kept per thread as a stack in call order: arming drops every entry whose function has
 * returned (see ds_sj_arm). The PPU dispatcher's
 * per-thread depth counters are saved at arm time and put back on the jump, since the frames that would have
 * decremented them are skipped. DES_SETJMP_LOG=1 logs every jump. */
#include "ppu_recomp.h"
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#if defined(_WIN32)
#define DS_LONGJMP(env, v) longjmp(env, v)
#else
#define DS_LONGJMP(env, v) _longjmp(env, v)
#endif

extern "C" PPU_THREAD_LOCAL void (*g_trampoline_fn)(void*);
extern "C" int* ps3_ppu_dispatch_depth_slot(void);
extern "C" int* ps3_ppu_vcall_sp_slot(void);

namespace {
struct SjEntry {
    jmp_buf env;
    uintptr_t frame;    /* host frame of the lifted function that called setjmp */
    uint32_t buf;       /* guest jmp_buf (16-byte aligned, as setjmp aligns it) */
    uint32_t guest_r1;  /* guest stack pointer at setjmp */
    int depth, vcall_sp;
};
enum { SJ_MAX = 256 };
struct SjStack { SjEntry e[SJ_MAX]; int n; };
PPU_THREAD_LOCAL SjStack* t_sj;
int s_log = -1;
bool sj_log() { if (s_log < 0) { const char* v = getenv("DES_SETJMP_LOG"); s_log = (v && *v == '1') ? 1 : 0; } return s_log != 0; }
}

extern "C" void* ds_sj_arm(ppu_context* ctx, void* host_frame)
{
    SjStack* s = t_sj;
    if (!s) { s = (SjStack*)calloc(1, sizeof(SjStack)); if (!s) abort(); t_sj = s; }
    const uintptr_t f = (uintptr_t)host_frame;
    const uint32_t buf = ((uint32_t)ctx->gpr[3] + 0xF) & ~0xFu;
    /* Drop entries whose functions have returned: a deeper host frame; a deeper guest frame (both stacks grow
     * down, and a live caller's frames are above ours on both); the same host frame with another guest stack
     * pointer (an earlier call that ran at this same host depth); and this frame re-arming the same buffer. */
    const uint32_t r1 = (uint32_t)ctx->gpr[1];
    while (s->n) {
        const SjEntry& t = s->e[s->n - 1];
        if (!(t.frame < f || t.guest_r1 < r1 || (t.frame == f && (t.guest_r1 != r1 || t.buf == buf)))) break;
        s->n--;
    }
    if (s->n == SJ_MAX) {   /* never seen: drop the oldest */
        memmove(&s->e[0], &s->e[1], sizeof(SjEntry) * (SJ_MAX - 1));
        s->n--;
        static int warned; if (!warned++) fprintf(stderr, "[setjmp] more than %d armed jmp_bufs on one thread\n", SJ_MAX);
    }
    SjEntry& e = s->e[s->n++];
    e.frame = f; e.buf = buf; e.guest_r1 = r1;
    e.depth = *ps3_ppu_dispatch_depth_slot(); e.vcall_sp = *ps3_ppu_vcall_sp_slot();
    return &e.env;
}

/* Called at the end of the lifted longjmp, with the guest registers already restored from the guest buffer
 * (r3 = setjmp's second return value). Does not return when an armed host jmp_buf matches. */
extern "C" void ds_sj_jump(ppu_context* ctx, uint32_t buf, uint32_t from_lr)
{
    SjStack* s = t_sj;
    const uintptr_t here = (uintptr_t)__builtin_frame_address(0);
    for (int i = s ? s->n - 1 : -1; i >= 0; i--) {
        SjEntry& e = s->e[i];
        if (e.buf != buf || e.frame <= here) continue;
        if (sj_log()) fprintf(stderr, "[setjmp] longjmp from %08X to buf %08X (entry %d of %d) val %d\n",
                              from_lr, buf, i, s->n, (int)ctx->gpr[3]);
        s->n = i + 1;   /* entries armed by the frames being skipped are dead */
        *ps3_ppu_dispatch_depth_slot() = e.depth;
        *ps3_ppu_vcall_sp_slot() = e.vcall_sp;
        g_trampoline_fn = 0;
#if defined(_WIN64) && defined(_MSC_VER)
        /* No SEH unwind: only lifted frames and the PPU dispatcher lie between, none with cleanup to run. */
        ((_JUMP_BUFFER*)e.env)->Frame = 0;
#endif
        DS_LONGJMP(e.env, 1);
    }
    static int warned;
    if (warned < 8) { warned++; fprintf(stderr, "[setjmp] longjmp from %08X to buf %08X with no armed setjmp: falling through\n", from_lr, buf); }
}
