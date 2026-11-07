# Demon's Souls (BLUS-30443) — ps3recomp port notes

> **Development log.** This is the running log of how the port was made, kept as written: fix by fix,
> with the reasoning and measurements. Paths are relative to the original working folder (`port/`,
> `tools/`, `game/` match this repo after SETUP.bat). "scratchpad" scripts are throwaway test
> helpers that are not part of the repo. The *Recipe* section is what `setup/setup.py` automates.


## Inputs
- `../Demon's Souls (USA).zip` — Redump ISO, CRC32 eb51fbeb (matches redump.org/disc/16199).
- Disc key: the one that comes with your dump (Redump page → Metadata → Disc Key, or a .dkey file);
  SETUP.bat asks for it. Not included here.

## Recipe
```bash
# 1. pull + disc-decrypt files straight out of the zip (AES-128-CBC, IV = sector number BE)
MSYS_NO_PATHCONV=1 python -P tools/iso_extract.py "../Demon's Souls (USA).zip" game /PS3_GAME/USRDIR/EBOOT.BIN
# 2. SELF -> ELF (official RPCS3 build in ../deps/rpcs3, no firmware needed)
../deps/rpcs3/rpcs3.exe --decrypt game/PS3_GAME/USRDIR/EBOOT.BIN      # -> EBOOT.elf
# 3. ps3recomp (../deps/ps3recomp @ 4e8f3ca, v0.18.0); run from port/
R=../../deps/ps3recomp
python $R/tools/ppu_loader.py game/EBOOT.ELF -o out/
python $R/tools/gen_imports.py game/EBOOT.ELF -o out/imports_named.json
python $R/tools/ppu_lifter.py game/EBOOT.ELF --functions out/EBOOT.functions.json \
       --hle-stubs out/EBOOT.imports.json --output recompiled/          # ~4 min, 2.4 GB
python $R/tools/extract_spu_images.py game/EBOOT.ELF --output spu/images
python $R/tools/build_spu_workloads.py --images spu/images --lifted spu --out spu/spu_workloads.c --constructor
python $R/tools/gen_hle_nids.py --all --out recompiled_hle_nids.cpp
```
Don't run ps3recomp tools with `-P`/`-I`: they import sibling modules from their own dir.

## First-lift results (2026-10-26)
- ELF: entry 0x124c0, TOC 0x19b5040. Executable range 0x10200–0x16BB5E4 (~22.7 MB).
  Section names are stripped; use the flags (0x6 = exec).
- 77,283 OPD descriptors → 104,131 lifted functions (incl. 11,136 tail-entry wrappers), 48 chunks, 28.5M lines.
  - 97,930 in exec range: **0 unhandled instructions**, 24k `.word` (inline data/jump tables).
  - 6,201 bogus "functions" in rodata/data (0x16BB5E4+, includes the embedded SPU ELFs): 4.26M `.word` +
    441k junk-insn TODOs. Dead weight — prune before building (most of the 2.4 GB).
- 12 SPU ELFs (858 KB), all lifted (91–94% coverage each):
  0 Edge zlib · 1 FromSoft SpursTaskCommandDispatcher · 2–3 FFX particle movement · 4–5 FFX cluster draw ·
  6–8 Havok physics (solver / narrowphase / collision queries) · 9 Havok anim sampling · 10 synth2 ·
  11 Sony MultiStream (loads DSP modules at runtime → same blocker as the Scott Pilgrim port).
- Imports: 389 across 25 libs; ~308 have an HLE impl. Missing 81: cellSail 25 (movie player),
  online (sys_net/sceNp/cellHttp/Avc2) ~20, cellSpurs queue funcs 5, cellAtrac 5 unnamed, cellAudioSetPortLevel,
  cellFsAioWrite, sys_prx_register_library. List: `port/out/truly_missing.txt`.
- Strings: Dantelion2 (`n:/dantelion2_autobuild/...`), `n:/DemonsSoul/Source/...` assert paths (168 files),
  Havok hk550, FaceGen, Lua. RTTI mostly Havok only.

## Build + boot (2026-10-26)
- Lift with `--code-end 0x16bb5e4 --chunks 128` (no bogus data functions: 94,017 funcs, 445 MB, 53 s).
- Project = ps3recomp template in `port/project` (name DemonsSoulsRecomp). `build.bat [target]` configures
  `port/build` with clang-cl + portable LLVM (no CMAKE_BUILD_TYPE → template's -O1) and runs ninja.
  Full build ~1 min on this machine. `-DDS_BOOT_HARNESS=ON` (currently ON in port/build) swaps in the
  toolkit's instrumented `runtime/ppu/tests/boot_main.cpp` (thread dump at 8 s/15 s, WATCHDOG_AT="a,b").
- Game data: `python -P tools/iso_extract.py <zip> game --all` (all 12,511 files, 8.0 GB, ~1 min).
- Run: see `tools/run_capture.ps1` for the env (PS3_HDD0_ROOT, RSX_LIVE_DRAW=1); don't launch it with
  -ExecutionPolicy Bypass (blocked) — run the same lines directly.

### Fixes so far
1. **ps3recomp lifter bug (deps/ps3recomp/tools/ppu_lifter.py, local edit, upstream-worthy):** `--hle-stubs`
   replaced each import stub with `ps3_hle_call` but dropped the stub's `std r2,40(r1)`. GCC-built callers
   reload r2 from that slot after the bl → TOC 0 on a fresh frame → NULL globals in static ctors.
   Now emits the store when the original stub has it (0xF8410028).
2. **SPURS job binaries:** not ELFs, so extract_spu_images misses them. Run with `SPU_DUMP_MISS=port/spu_miss`,
   then `python tools/lift_spurs_jobs.py ../deps/ps3recomp port/spu_miss port/spu` (wraps at LS 0, lifts,
   writes `spu/jobmods_register.c` keyed by raw fingerprint) and rebuild. One job so far
   (fp BD46853E5ADE5098, 2064 B, lives in the EBOOT at 0x177B600) — runs, returns 0.
- Debug aid: `scratchpad patch_drain.py` adds `ds_toc_check(ctx)` (stubs.cpp) to every chunk's
  DRAIN_TRAMPOLINE; logs the first calls returning with r2 ∉ {19B5040, 19D3BAC, 19C448C}. Re-apply after relift.
- Multi-TOC: TOC1 0x19B5040 (58k funcs), TOC2 0x19D3BAC (15k, SDK/runtime side), 0x19C448C (36);
  linker stubs `std r2,40(r1); addis/addi r2 ±0x1EB6C; b` handle switching and lift fine.

3. **GCM command buffer layout (cellGcmSys.c):** begin was ioAddress; real libgcm (and RPCS3) reserve
   4 KB: begin = ioAddress + 0x1000, put = get = 0x1000. FromSoft's SPU command dispatcher writes `put`
   as (current - begin) + 0x1000, so the walker sat 4 KB behind forever (HighGraphics label wait).
   `GCM_BEGIN_AT_IO=1` restores the old layout.
4. **Real file names (tools/udf_rename.py):** ISO9660 names on the disc are mangled ("DS_FILTER_SHADERBND.DCX",
   31-char cuts). The script reads the UDF 2.50 tree (metadata partition) from the plain head of the image
   and renames all 12,503 files. Run once after iso_extract --all. HDD1 cache lives in `hdd1/` (PS3_HDD1_ROOT);
   wipe `hdd1/cache` if it was written while files were missing.
5. **_cellSpursLFQueuePushBody (cellSpurs.c, new) + faithful _cellSpursLFQueueInitialize:** port of RPCS3's
   cellSyncLFQueue PPU2SPU push (GetPushPointer/CompletePushPointer) under the lock-line lock, waking the
   waiting task via m_hs1[] -> spu_taskset_signal_task. Feeds the Edge zlib inflate tasks (SPU image 1);
   without it every .dcx stayed compressed. `LFQ_OLD_INIT=1` = old init. `LFQ_DBG=1` logs pushes/elements.
6. **SPURS JOBLIST (cellSpurs.c jc_execute):** opcode 6 was skipped ("TODO"). FromSoft uploads shader
   microcode to VRAM via copy jobs in a CellSpursJobList, so every fragment program slot stayed zero.
   Plus a second runtime job binary (fp B1463A6F2DF960AC, 384 B, the DMA-copy job) lifted via lift_spurs_jobs.py.
7. **1D textures (rsx_live_draw.c):** decode rejected dimension 1; now decoded as height-1 2D.
- Debug switches added: LD_PSO_DBG=2/3 (hexdump / distinct FP regs), GCM_SUBCH_LOG=<n>,
  SPU_PUTWATCH=<ea>[,len], LFQ_DBG (also dumps flag+0x80/+0x100 when an EF wait blocks).
- All runtime edits: `patches/ps3recomp-local.patch` (re-apply after re-cloning ps3recomp).
- Frame dumps: LD_FRAME_DUMP=<dir> LD_FRAME_DUMP_EVERY=<n> (PPM). PrintWindow/screen grabs of the D3D12
  window come out blank -- use the dumps.

8. **Zombie SPURS tasks (spu_workload.c / spu_channels.c / cellSpurs.c):** Shutdown/JoinTaskset were no-ops,
   so tasks of destroyed Edge zlib tasksets kept running; the game reused that memory as its file read buffer
   and the zombies wrote 0x03 bytes into compressed data (one segment in ~26 inflated 3 bytes short -> its
   task skips the counter decrement -> loader waits forever). Now Shutdown marks the taskset, its tasks halt
   at their next lock-line atomic (and are released from WAIT_SIGNAL), JoinTaskset waits until they're gone,
   CreateTaskset at the same EA clears the mark. Found via SPU_ATOM_EAS per-task tracing + Edge zlib's own
   error printf (hand-patched into spu_0000.../spu_recomp.c C1A0, lost on SPU relift).
9. **GCM ring recycle:** `GCM_NO_TITLE_RECYCLE=1` (needed): the runtime's "title overran its ring" rescue
   rewound put/get under FromSoft's SPU dispatcher (it wraps its own 32 KB ring) -> label wait forever.
10. **PSN offline identity:** `PS3_NP_STRICT_OFFLINE=1` (needed): GetNpId/OnlineId/OnlineName return
    SCE_NP_ERROR_OFFLINE when signed out (as RPCS3), + sceNpManagerGetAvatarUrl implemented. With the fake
    "PS3Player" account the game sat on a black pre-title screen forever (17 file opens -> 98+).
11. **cellSpursQueuePopBody** (SPU2PPU LFQueue pop, RPCS3 port). The game's pops hit a dir=0 queue
    (q=0x181C5080, size 16 depth 250, non-blocking) -> currently returns PERM; not yet understood.
- Stale HDD1 cache: runs that hit the bugs above left truncated cache files (ds_flver 393216/752688) ->
  wipe `hdd1/cache` after fixing anything in the load path.
- **RPCS3 as oracle:** firmware 2.76 from the disc's PS3UPDAT.PUP installed in deps/rpcs3
  (`rpcs3 --installfw`). `rpcs3 --no-gui game/PS3_GAME/USRDIR/EBOOT.BIN` boots the game; its log
  (logs/rpcs3_boot1.log) has every sys_fs_open in order -- the reference boot sequence.

12. **SPURS queue layout (SUPERSEDED by 19 -- the LFQueue assumption was wrong):** `_cellSpursQueueInitialize` wrote a CellSyncLFQueue line
    (direction at +0x24, m_bs=-1, eaSignal=taskset). The particle taskset (0x18394800) reports through
    q=0x181C5080 (SPU2PPU, 16 B x 250) and the PPU polls it with cellSpursQueuePopBody -- on the old guessed
    layout the direction read 0 and nothing was popped.
13. **MultiStream / ATRAC:** MultiStream loads Sony's ATRAC decoder from /dev_flash/sys/external/flashATRAC.pic.
    The runtime's default dev_flash is the ps3recomp author's `D:/recomp/...`; `PS3_DEV_FLASH` must point at a
    real tree (deps/rpcs3/dev_flash after `--installfw`). The decoder is copied into LS 0x32890 at run time ->
    "branched into unlifted LS -- ending the job" killed the MultiStream task; `SPU_INTERP_UNLIFTED=1` runs it in
    the SPU interpreter. Even so, ATRAC-on runs stall at the BGM stream (ds_bgm_other.mowb); with no flash tree
    MultiStream just skips ATRAC (silent music) and boot gets further. run_capture.ps1 uses the latter for now.
14. **SPURS task identity race (cellSpurs.c CreateTask / spu_workload.c):** CreateTask stored the new task's
    taskset/id in the shared globals g_ydkj_real_taskset_ea/taskid and spu_workload_dispatch_async read them back.
    Havok's thread and the particle system's thread create tasks at the same time, so a particle task (image 3/4)
    could start with Havok's TaskInfo: its parameter-block DMA used Havok's argument words, the table base came out
    0, it read "\x7FELF" from EA 0 and hit HALT-ASSERT heqi pc=0x05508 (the dt3 run shows image 3 in taskset
    0x179ED800 = Havok's). Now CreateTask and the task-exit restart path name the task per thread
    (spu_workload_set_dispatch_task, thread-local) and dispatch takes it from there. 3 clean runs: no asserts,
    images 3/4 always in their own taskset 0x18394800.
15. **Synthetic job-chain events flood Havok's queues (cellSpurs.c jc_signal_done):** the runtime posts a
    made-up completion event for every job-chain job into EVERY queue attached with
    cellSpursAttachLv2EventQueue (added for Tokyo Jungle). DeS attaches one queue per Havok SPU port (q3..q11 on
    ports 0,2..9, q12 on 10/11); its command-dispatcher chain (0x1065DE00, ~70 jobs/s) filled q5..q12 to their
    capacity of 50 during loading. When a Havok physics task then reported on port 4 (q6) it got EBUSY, the step
    never completed, the Havok PPU thread (tid 11) and the main thread (tid 1, cond 13) waited forever -- the
    "run-to-run stall" at ref pos 74-101. Timing-dependent: a slow (traced) run drained in time and got to 147.
    Fix: `SPURS_JC_EVENTS=0` turns the synthetic events off (DeS's chains send none); run_capture.ps1 sets it.
    3 clean runs: all reach ref pos 148/148 and show the system-data auto-save notice (autosave_notice.png).
    Diagnostics added: the watchdog now prints `in syscall N` per guest thread; SPU_EVT_LOG=1 logs every SPU
    user-event send + result; EVT_PUSHLOG_MAX raises EVT_PUSHLOG's 200-line cap. PS3_EVQSTAT=<n> (existing)
    showing `pending=50` was the tell.
16. **Input + intro movie -> title screen:** pad input goes through the runtime's existing `PAD_SCRIPT`
    ("<sec>:<mask>,...", CROSS 0x4000, START 0x0008; latched, held ~40 polls). Cross at 30 s dismisses the
    auto-save notice; the logos follow (Atlus, SCE, Japan Studio, FromSoftware, Havok). The game then plays
    movie/ds_advertise.pam through cellSail, which ps3recomp only stubs: it reports Boot/OpenStream done but
    plays nothing, and the game never calls Start -- black screen for good (Start doesn't skip it). RPCS3's
    cellSail is unimplemented too. `PS3_NO_SAIL=1` (existing switch) fails cellSailPlayerInitialize2; the game
    retries once, gives up on the movie and goes to the title screen (title_screen.png, ~frame 1900 / 63 s).
    Start there opens NEW GAME / LOAD GAME (title_menu.png). The game's SAIL callback (func_00FD9120) forwards
    every event except Boot-completed to its movie thread via sys_event_port_send (func_00FDF768).
17. **NEW GAME -> Create Profile (cellOskDialog):** after NEW GAME the game says it cannot reach the Demon's
    Souls server (009), then "Start the game in Offline Mode" -- both just need Cross. Create Profile renders
    (character_creation.png). The name comes from the on-screen keyboard, whose stub refused LoadAsync without
    cellOskDialogInit (DeS never imports it) and sent no sysutil callbacks. Now LoadAsync self-initialises, answers
    with `OSK_TEXT` (honouring the field's limit) and posts LOADED/FINISHED (0x0502/0x0503), Unload posts UNLOADED
    (0x0504) to every sysutil slot. Down x4 + Cross on OK creates the profile; it is saved
    (gamedata/dev_hdd0/home/00000001/savedata/BLUS30443DEMONSS005 -- next NEW GAME shows a Profile List,
    profile_saved.png) and the tutorial level m08_00_00_00 starts loading (level_loading.png, "Old King Doran").
18. **Taskset running-set table full (spu_workload.c TS_TRACK):** the runtime tracked running tasks for 8
    tasksets and never released an entry. DeS creates a taskset per batch of Edge zlib work, so its particle
    taskset (0x18394800, created later) got none: ts_running() returned NULL and the exit-time scan that starts
    pending tasks never ran. The particle tasks create child tasks FROM THE SPU (SPU-side cellSpursCreateTask:
    image 3 claims an enabled bit at 0x7918/0x79EC, PUTs the TaskInfo, sets pending at 0x7C2C; image 4 likewise
    -> children elf 0x179CC00/0x17ACD00 = images 5/6). Never started, they held their ids; after ~60 frames all
    128 ids were taken and every later CreateTask failed. Now 64 entries, released on JoinTaskset and reset on
    CreateTaskset; images 3-6 run every frame and no id is ever exhausted.
    Debug added: TS_SLOT_DBG=<taskset> (each id taken / exit + enabled bitset), LFQ_POPLOG=1 (every element
    cellSpursQueuePopBody returns), SPU_ATOM_FULL=1 also prints the whole line in SPU_ATOM_EAS traces, RETURNED
    lines name taskset/task, start-task lines show the TaskInfo args.
19. **SPURS queue = libsre's layout, not an LFQueue (cellSpurs.c):** the particle system's level-load flush
    (func_014C3958) waits on queue 0x181C5080 for SPU progress reports {stream, count}: object+0 / +0x70 hold
    the two streams' item counts and the flush waits until each progress word reaches count-1. The child task
    (image 5) does push -- but only once there is work (first time: the level load), and it saw the queue as
    FULL because our _cellSpursQueueInitialize wrote a CellSyncLFQueue (my fix 12) and depth (+0x0C) read 0.
    Disassembled the firmware's libsre (dev_flash/sys/external/libsre.sprx -> rpcs3 --decrypt ->
    tools/lift_prx.py relocation -> capstone PPC; script in the tools/dis_sre.py) and ported
    _cellSpursQueueInitialize (0x082BFB09) and cellSpursQueuePopBody (0x91066667, args queue, buffer, isPeek,
    isBlocking) exactly: +0 pop / +4 push index (0..2*depth-1, ~v = in progress), +8 size, +0xC depth, +0x10
    buffer, +0x18 SPU port (-1), +0x1C direction, +0x20..0x5F waiter bytes, +0x60 taskset, +0x68 spurs, +0x70
    lv2 queue. RPCS3 has no HLE for these (it runs libsre LLE). An empty blocking pop polls instead of using
    the lv2 queue Attach would create. Under spu_lockline_lock only raw accesses + ef_line_end: vm_write32
    takes that lock itself -- the first non-empty pop deadlocked the render thread on it.
    Result: 9407 pops in a 320 s run (first {1,5}); the tutorial loads (Mephistopheles card), the opening
    narration plays as subtitles over black, and gameplay starts with the HUD (in_game_hud.png).
    Debug added: SPU_DMATRACE_BYTES / _SKIP / _MAX / _AFTER_WATCH, SPU_DMAWATCH_EA=<ea>[,<ea>] (log a GET's
    data when it changes), QUEUE_DBG=1, LFQ_POPLOG=1 now logs SPURS-queue pops too.
20. **Black 3D world = exposure 0** (stopgap REMOVED -- real fix is 21): geometry, textures, lighting and the
    shadow map all work (per-draw dumps: LD_DRAW_DUMP + RSX_DRAW_CSV(_FROM) show the silhouettes being drawn
    in black over the clear colour). Every material shader ends in `saturate(colour * T.x / T.y)` (decoded
    the raw ucode: MUL c.xxxx then DIV c.yyyy -- the decompiler is right). T is FromSoft's GLOBAL shader
    parameter 0x87: each program in shader/ds_flver.shaderbnd carries a table of (param id, ucode offset)
    pairs in front of its ucode (0x87 -> +0x3B0/+0x3D0 for the main scene shader), and the engine keeps a
    float4 table of the globals (x4, one per command context) that its SPU command dispatcher (image 2)
    patches into programs with NV308A inline transfers when a value changes. 0x87 = (exposure, 2, 0, 1); the
    exposure is auto-exposure (ExposureReaderEntity / ShaderConstant_ToneMapEntity, TONE_MAP_BANK key 0.18)
    and here it is 0 and never changes -- the reader never produces a value. Ruled out: semaphore ordering
    (GCM_SEMA_ACQUIRE=1 changes nothing), ZPASS reports (only ZCULL stats 2/3 are read), SPU reads of the
    scene target, NV0039 copies (only inline transfers are used). Most likely it waits on a GPU result that
    the live-draw renderer never writes back to guest memory (no render-target write-back exists).
    STOPGAP: LD_EXPOSURE_STOPGAP=<f> replaces x of any inline constant that is exactly (0,2,0,1);
    run_capture.ps1 sets 3.0 -> the tutorial corridor and the opening cutscene are visible
    (tutorial_visible.png, opening_cutscene.png; the cutscene looks over-bright). The stopgap is gone (fix 21).
    Tools/debug added: tools/dcx.py (DCX EDGE/DFLT decompressor), LD_FPCONST=<pso>[,_FROM] (constants,
    ucode words, copies of the program, main+local scan), LD_MEMDUMP=<dir>, GCM2D_WATCH=<ea>,<len>
    [+_EVERY] (inline writes + FIFO address), REPORT_HIST=1, 2D-engine logs now on stderr.
21. **Real auto-exposure (replaces the fix 20 stopgap):** the exposure is a GPU result read back by the CPU.
    Each frame the game reduces scene luminance through F_X32 (SURFACE_FORMAT colour 0xD) targets in local
    memory: 320x180 -> 64x64 log-lum (0x41CDF80) -> 16x16 averages (0x1377DC0, 0x1392440) -> exp2 average
    luminance (0x1392880) -> 16x16 ADAPTED EXPOSURE (0x13AB840: clamp(lum,0.08,0.2)+0.001, 0.18/that, eased
    toward from its own previous value -- the TONE_MAP_BANK row (0.1, 0.08, 0.2, 0.18) is in its constants).
    ExposureReaderEntity's read routine (0x22068, message 0x8041 via 0x22908) reads that float from
    0xC13AB840 into the tone-map constant object (+0x1A8 = x, +0x1AC = 2.0); the per-frame context builder
    (0xBD780 -> 0xB88F8) passes it to 0x6BD38, which stores (x, 2, x, 1) = global shader param 0x87 and
    marks it dirty. Three live-draw bugs broke the chain, all fixed in rsx_live_draw.c:
    a) every non-FP16 render target was RGBA8 -- F_X32 now gets R32_FLOAT, F_W32Z32Y32X32 R32G32B32A32
       (ld_surface_dxgi; the PSO key carries the RTV format as rt_fmt; LD_FP32_RT=0 = old behaviour).
    b) nothing reached guest memory -- small FP32 targets (<= LD_RT_WRITEBACK_MAX texels, default 4096) are
       copied to readback buffers before the present flush and stored big-endian at the guest pitch after
       it (one flip of latency, as on the console). LD_RT_WRITEBACK=0 = off, LD_RT_WRITEBACK_DBG=1 logs.
    c) each of these surfaces also gets an empty RGBA8 twin (same address and size, created from a
       transient surface state). Texture lookup took the first size match (the twin), and the adaptation
       pass's read of its OWN previous value bound the target's twin instead of the feedback copy -- the
       exposure stuck near 0.5 + (2.2-0.5)*0.059 = 0.6. Now: of the size matches the most recently drawn
       wins, and any twin of the current target is skipped so self-reads use surface_feedback_srv.
    Result: exposure ramps from 0 and settles at 2.22 in the dark corridor; the opening cutscene is no
    longer over-bright (auto_exposure.png). 26-29 fps. The RGBA8 twins themselves are still created
    (harmless now; the transient that creates them is not chased).
    How it was found: PPU_RWATCH on 0xC13AB840 (who reads it), PPU_WWATCH on the constant object, a
    temporary print in the lifted func_0006BD38, and decoding the adaptation program's ucode by hand.
    Tools/debug added: tools/dis_eboot.py (EBOOT disassembly with TOC/string annotations),
    LD_TEXBIND_WATCH=<offset hex> (how a texture at that offset is bound), LD_FPCONST_SURF=<offset hex>
    (the LD_FPCONST dump for draws into that surface), PPU_WVAL_MAX=<n>.
22. **Whole frame blurred + fog missing = depth read as a colour texture:** the scene buffer (0x7A0000) is
    sharp, but a full-screen pass (shader cc2a6349..., colour mask 0x01000000 = alpha only) reads the depth
    buffer 0xB50000 as an A8R8G8B8 texture, rebuilds depth as dot(tex.wxy, c) -- the RSX D24S8 word read
    as bytes: A = depth bits 23-16, R = 15-8, G = 7-0, B = stencil -- reprojects with camera matrices and
    writes a blur amount into scene alpha; the DOF/motion-blur pass (4084c3a8...: lerp(scene, 640x360 blur,
    saturate(scene.a * c0.x)) into 0x4260000) then blends by it. The live zeta exists only on the host, so
    the colour read fell through to guest VRAM, alpha came out ~0.9 everywhere and the whole image was the
    640x360 blur. The tutorial's fog volumes (soft particles) read depth the same way and were invisible.
    Fix (rsx_live_draw.c, zdepth_argb): an A8R8G8B8 texture at the address of a zeta with host depth gets
    the R32F depth snapshot repacked into those bytes by a compute pass (once per depth write; RGBA8 host
    texture R = mid, G = low, B = 0, A = high byte). LD_DEPTH_AS_COLOR=0 = old behaviour.
    Result: sharp image and visible fog (sharp_tutorial.png, blur_before_after.png); 26-27 fps.
    Found with LD_DRAW_DUMP + new LD_DRAW_DUMP_FRAMES=<n> (dump every draw of n consecutive frames): the
    post chain crosses the live-draw frame counter, so one frame never held the whole chain.
23. **Red Create Profile face = fragment source precision modifiers ignored:** the skin shader (ds_flver
    program at 0x388960; table maps its constants to globals 0x5C-0x67, 0x87, 0x8B, 0x9C) ends in a fog
    blend lerp(colour, P67.rgb, fog * P67.w) with the fog factor from the VS ((clip w - 50) * 0.02 from VS
    constant 103). For a character 1.4 units from the camera that factor is -0.97, and the menu's fog
    global 0x67 is (1,1,1,1), so the blend pushed the colour AWAY from white: G/B went to 0 and the skin
    turned dark red. On RSX the instruction reads the factor with src0_prec_mod = 4 (SRC1 bits 19-21:
    src0, 22-24 src1, 25-27 src2; 2 = clamp [-2,2], 3 = [-1,1], 4 = [0,1]) -> 0 -> no fog. Fix
    (rsx_fp_decompiler.c): emit those clamps on every non-branch source (RPCS3 ClampValue). Shader disk
    cache bumped to v3. Result: natural face and body (create_profile_fixed.png); gameplay unchanged or
    better -- the sky through the tutorial arch now shows clouds and the palace (tutorial_sky.png).
    Found with LD_PS_OUT=<fp offset hex>:<hlsl expr> (replace one program's colour output with an
    intermediate value), LD_HLSL_DUMP now also writes hlsl_fp<loc>_<off>.ps/.vs.txt, LD_FPCONST_VPC=<n>,<k>
    (VS constants), vertex attributes in the LD_FPCONST dump, LD_TEXBIND_WATCH prints guest texels.
    Reaching Create Profile needs a first-time start: move gamedata/.../savedata/BLUS30443DEMONSS005 aside
    (then it shows Brightness Setting first; PAD_SCRIPT ...,122:0x4000,140:0x4000 gets past it).
24. **Live input (keyboard + mouse, or an XInput pad):** the runtime already polled XInput (Xbox pads, port
    0..3) with a keyboard fallback on port 0 when no pad is present, but the fallback's layout (arrows,
    Z/X/A/S) had no camera stick. libs/input/cellPad.c adds PAD_KEYMAP=souls: WASD = left stick, mouse
    (recentred each poll while the window has focus; F1 toggles; PAD_MOUSE=0 never; PAD_MOUSE_SENS=<f>,
    default 6) and IJKL = right stick, LMB R1, Shift R2, RMB L1, Ctrl L2, Space Circle, E Cross,
    F Triangle, R Square, Tab/MMB R3, C L3, arrows d-pad, Enter Start, Backspace Select. Test hook
    PAD_KEY_SCRIPT="<sec>:<key>:<dur>,..." feeds the same mapping without the focus check: walking through
    the arch, camera turn, attack (stamina drops) and roll all reach the game (keyboard_test.png).
    Launcher: PLAY_DEMONS_SOULS.bat (project root) -- same env as run_capture.ps1, no PAD_SCRIPT, no
    timeout, logs to logs/last_run_*.txt; DES_NAME sets the name the OSK stub answers with.
25. **Invisible shield = S1 vertex attributes converted the D3D way:** the player's shield (a rigid
    mesh, 438 source vertices, same skinning VS as the body) stores all-zero bone indices and weights
    (attr7 UB256 = 0, attr1 S1 = 0 -- checked in the raw guest vertex bytes; no other copy exists).
    The VS normalises the weights by their sum (RCP of the sum, MUL), so with exact zeros every
    vertex collapsed to one point. The RSX converts S1 (signed normalised 16-bit) the legacy
    NV/OpenGL way, (2c+1)/65535, so a stored 0 is 1/65535: the four weights normalise to 0.25 each
    of bone 0 and the shield is rigidly attached. live-draw converted c/32767. Fix: one helper
    rsx_s1_to_float() (rsx_vertex_formats.h) used by every CPU-side S1 decode (rsx_vertex_compact.c,
    rsx_vertex_fetch.c, rsx_live_draw.c); PS3_S1_D3D=1 = old behaviour. Result: shield on the arm in
    Create Profile and gameplay (create_profile_shield.png, shield_fixed.png). Weapons/other rigid
    attachments with the same layout are fixed by the same change.
    Found by diffing each draw of the Create Profile body render (draws that change 0 pixels) and new
    debug: LD_VTXDUMP_VERTS=<n source verts>[,<c0>,<count>] (decoded attrs, raw vertex bytes, every
    other copy of vertex 0 in memory, VS constants; needs RSX_DRAW_CSV since it runs in the CSV
    writer), LD_VTXDUMP_SURF=<offset hex> (vertex counts of the draws into a surface),
    LD_FPCONST_TEX0 / LD_FPCONST_VERTS (only reached when a PSO is built -- get_pso caches).
26. **Audio (superseded -- fixed in 29), two real fixes found on the way:**
    a) cellAudioSetNotifyEventQueue got key 0: MultiStream's mixer thread (higher priority) creates
       the event queue (key 0x8000CAFE02460300) and its creator reads the key before it is written --
       the race the runtime documents in sys_ppu_thread.c. PS3_PRIO_START=1 fixes it (the key
       arrives; the mixer thread then wakes ~187x/s, once per audio block). NOT yet in the launcher.
    b) cellAudioSetPortLevel (NID 0x56DFE179, float level in f1) was unimplemented -> added
       (cellAudio.c audio_register_ctx, registered in ppu_sysprx.cpp).
    With both, MultiStream (SPURS task image 12, "Skipping DSP..." strings) runs every block and
    writes 0x2000-byte blocks to port 0 (0x58000000), but every byte is zero: its stream state
    (16 words of 0xFFFFFFFF = free slots at 0x17B96900; the 0xC40 stream tables are zero) shows that
    no stream is ever opened. The ATRAC decoder (flashATRAC.pic, real dev_flash) loads and runs once;
    the old BGM boot stall is gone (ATRAC on reaches gameplay). The game's sound engine is FromSoft
    MagicOrchestra (MOPS3SoundManager; magicorchestra2.mgs / rpcsetting.rpc / demonsmixer.momd load
    fine) on MultiStream; the break is in that PPU-side code (no symbols). synth2.elf (SPU thread
    image 11) fetches its args once and then spins (100% of a core). Next: find the MagicOrchestra
    play path (MOMainThread / MOStreamingThread are busy) and why it never calls MultiStream's
    stream open. Without dev_flash the game falls back to cellAtrac (PPU), which needs streaming
    (GetStreamDataInfo/AddStreamData, NIDs 0x06DDB53E 0x2BFFF084 0x46CFC013 0x99EFE171 0xBE07F05E
    imported but unnamed here).
    Debug added: AUDIO_MUTE=1 (silence to the device, mix/AUDIO_WAV unchanged), AUDIO_PEAK ring line
    now per port with block peak + level, SPU_DMATRACE_BYTES also shows PUT data (non-zero count).
27. **Frame rate: optimised build (steady 31 fps), 60 not reached yet -- what limits it:**
    - The port was built DEBUG: build.bat's CMake defaulted to CMAKE_BUILD_TYPE=Debug, so the lifted
      PPU code and the runtime compiled /Od /RTC1. build_opt.bat builds port\build_opt with
      CMAKE_BUILD_TYPE=Fast (a type CMake has no presets for), so the project's own -O1 applies to the
      lifted units, the runtime keeps -O2, plus /Zi for C files (PDB for profiling). Debug 26-27 fps with
      drops -> optimised 31.2 fps steady; the PPU threads go from 20-30% of a core to ~0.
      PLAY_DEMONS_SOULS.bat and run_capture.ps1 now use build_opt (fall back to build).
    - Pacing: SetFlipMode(2 = HSYNC); vblank handler func_009F7018 counts vblanks (0x1B50434) and posts
      a semaphore once count >= target (0x1B50E34); func_00A16360 sets target = count + obj[0xB]
      (obj = HighGraphics' frame object + 0x718). obj[0xB] is 1 the whole time, so the game asks for
      60 fps; DES_FRAME_INTERVAL=<n> overrides it (port patch in lifted ppu_recomp_060.cpp; logs each
      change as [des] frame interval -- keep it in patches/recompiled-port-patches.diff after a re-lift).
    - Why 31 and not 62: PS3_FTRACE timeline (tools/ftrace_report.py) shows a serial chain per frame:
      HighGraphics submits for ~3 ms, the FIFO then stays empty until ~11 ms (command generation
      upstream -- SPU dispatcher image 2, spu_0001_at_0176C200, busy 100%, a third of it in
      spu_wrch/mfc_for channel+DMA emulation), the RSX drain takes ~11-12 ms (renderer CPU: per-draw
      CPU vertex conversion ~6 ms -- rsx_vertex_decode_element/remap/fetch -- texture_content_hash
      ~1.8 ms), GPU fence wait ~3.6 ms/frame, one flush per frame. ~24 ms > 16.7 ms, so each frame
      lands on the second vblank. With PS3_VBLANK_MS=8 (125 Hz) it runs at ~39 fps, i.e. the host-
      bound rate is ~40 fps (and game speed would scale with the vblank rate -- not for play).
    - Tried, no effect on the cap: LD_PRESENT_INTERVAL=0 (Present without vsync wait),
      GCM_HSYNC_IMMEDIATE (now default: HSYNC flips complete when the drain reaches them -- correct
      for mode 2/3, kept), GCM_PUMP_THREAD=1 (handlers on a dedicated delivery thread; off by default),
      SPU_MFC_LOOKUP_CACHE=1.
    - Next for 60: GPU-side vertex conversion (upload raw vertex buffers, decode via the input
      layout/VS) or a vertex-conversion cache; overlap the drain with command generation; make the SPU
      channel/MFC fast path lock-free. Also two SPU threads spin at 100% (synth2, image 2 polling).
    - Debug/tools added: LD_FLUSH_STATS=1 (flushes/frame by reason + fence wait ms/frame),
      LD_PRESENT_INTERVAL, PS3_VBLANK_MS (boot_main ticker), scratchpad thread_cpu.py (per-thread CPU
      with names) and rip_sample.py (IP sampling of one thread, offline symbolisation with the PDB).
28. **60 fps (locked, game speed correct) -- PLAY_DEMONS_SOULS.bat default; DES_FPS=30 for the original:**
    - Why the game was 30 even with interval 1: HighGraphics' frame loop (func_00A164B8 <- 0x00ACA488) waits
      on the vblank semaphore until the previous frame's flip has executed, then for the next vblank, so a
      frame is always >= 2 vblanks -- the PS3 original is a 30 fps game. Its game logic is a FIXED step:
      the main loop func_0001B8D0 passes the float at 0x018C8DB4 (1/30 s) to every subsystem as dt.
      Unlocking alone would run everything at double speed. Same recipe as RPCS3's "60 FPS" patch
      (Whatcookie; RPCS3 wiki, disc v1.00 BLUS30443 writes bef32 0x018c8db4 = 0.01666667, used with
      Vblank 120 + Clocks scale 200):
        DES_60FPS=1         port patch in lifted ppu_recomp_060.cpp (func_00A16360): step 1/30 -> 1/60
        PS3_VBLANK_HZ=120   2 vblanks per frame = 16.7 ms
        PS3_CLOCK_SCALE=200 new runtime knob (sys_timer.c ps3_clock_scale): timebase, system time and
                            current time run at 2x; sleeps/timeouts stay real. Keeps the game's own
                            frame skip (measured in guest time) seeing its native frame length.
      DES_STEP_STATS=1 (port debug in ppu_recomp_011.cpp, func_0001B8D0) prints steps/s and game seconds
      per real second: 60.0 steps/s x 1/60 = 1.000 at 60 fps, 30.0 x 1/30 = 1.000 at 30 fps.
    - Host work that had to fit in 16.7 ms (all measured with PS3_FTRACE, frames timed flip to flip):
      * Vblank ticker (boot_main.cpp) used GetTickCount64 = 15.6 ms granularity: vblanks landed 10-18 ms
        apart. Now QPC-based with a fractional rate (PS3_VBLANK_HZ, default 60; PS3_VBLANK_MS still
        works). 30 fps mode went from 31.2 ragged to exactly 30.0.
      * Converted-vertex cache (rsx_live_draw.c, LD_VCACHE=0 = off, LD_VCACHE_STATS=1 = hit rates):
        a draw's key = attribute registers, bases, batches, primitive, restart rule and the index bytes;
        a hit re-hashes the guest vertex ranges it was converted from and uploads the stored vertices +
        topology indices. ~70% of draws hit, ~18 MB cached. Misses use rsx_vertex_fetch_many
        (attribute-major loops) instead of one vertex at a time. Drain 12-13 ms -> ~5 ms.
      * Mid-frame kicks (LD_KICK_DRAWS=<n>, default 64, 0 = off): every flush was synchronous and the
        only one per frame was at present, so the GPU started the frame after the CPU had recorded all
        of it and the RSX thread waited ~4 ms. Kicks submit every 64 draws without waiting (own
        allocator pool, nothing reused before the next waited flush). Fence wait 4.0 -> 1.0 ms/frame.
      * SPU command generation ("spu job" thread, image 2 at 0x176C200): the MFC engine lookup cache
        is now on by default (SPU_MFC_LOOKUP_CACHE=0 = off; the locked walk over every context's
        engine was 14% + SRW traffic 14%), spu_taskset_is_down scans only up to the highest used slot
        (shut-down tasksets stay marked, so every SPU atomic scanned 64 volatile slots). The FIFO now
        fills ~5 ms after HighGraphics' flip instead of ~8-11 ms.
    - Result (tutorial, scripted run, 3 s PS3_FTRACE window): 179/179 frames exactly 2 vblanks (16.7 ms),
      [fps] 60.0-60.4; per frame the RSX drain ends ~11 ms after the flip, ~5.5 ms of slack.
      Before: 31.3 fps with the drain ending ~24 ms in.
      Walk test (PAD_KEY_SCRIPT 3 s of W at 188 s): the knight ends at the same spot through the arch
      in both modes (walk_30_vs_60.png, left 60 / right 30) -- movement and physics at the right speed.
    - Still open: "spu job" and synth2 each spin a full core; MOStreamingThread ~47% (audio, fix 26).
      The frame skip only covers big hitches -- below 60 the game runs slightly slow (57 fps = 95%).
    - PAD_NO_XINPUT=1 (cellPad.c): ignore Xbox pads. With a controller plugged in the keyboard layout
      (and PAD_KEY_SCRIPT) is never polled, and a test window would read the real pad; runs.sh sets it.
    - Debug added: SEM_TRACE=<id|-1> + SEM_TRACE_AT=<s> (sys_semaphore.c: waits/posts with three guest
      return addresses), scratchpad bench.sh (scripted tutorial run + fps + timeline), prof.sh
      (thread CPU + IP samples of one thread at 205 s), fscan.py (float loads by value).
29. **Sound and music WORK -- SPU threads could not receive events:**
    - The real audio path (fix 26 had it wrong): port 1 (8 ch, 8 blocks, 0x58200000) belongs to Sony's
      libmixer (cellSurMixer, statically linked: threads _cellsurMixerMain / _sys_MixerChStripMain /
      _sys_mixerSurBusReq, code ~0x1546000), fed by libsynth2 = synth2.elf, an lv2 SPU thread (image 11,
      tid 0x2000). Port 0 (32 blocks) is opened by MagicOrchestra itself and stays silent here (it may be
      MultiStream's for streamed ATRAC; nothing audible needs it so far).
    - Break: synth2 takes every command with sys_spu_thread_receive_event (SPU `stop 0x110`: spuq number in
      the out-mailbox, lv2 answers {CELL_OK, data1, data2, data3} in the in-mailbox). The runtime had no
      such call for lifted SPU threads (only a global "pending event" hack for another title's sim SPUs),
      and sys_spu_thread_bind_queue / unbind_queue (syscalls 193/194) were stubs. synth2 spun at 100% of a
      core on the failing receive, MagicOrchestra never got its voices running and never opened the
      streamed music bank (ds_bgm_other.mowb -- RPCS3 opens it at boot position 28).
    - Fix (runtime): bind/unbind_queue record (spuq -> queue) per SPU thread (lv2_register.c);
      spu_stop() services stop 0x110 / 0x111 (tryreceive) for lv2 SPU threads (spu_group_id != 0) via
      lv2_spu_receive_event: waits up to 200 ms for the binding (the SPU can get there first), pops the
      queue with sys_event_queue_pop_spu (sys_event.c, 20 ms slices, leaves on a stop request), replies
      like RPCS3. SPU_RECV_LOG=1 logs each receive. synth2 now gets one event per audio block (~187/s,
      data1 = a command block at 0x0FF60100) from libmixer via port 12 -> queue 14.
    - Also needed: PS3_PRIO_START=1 (threads start in PS3 priority order; without it the audio notify
      queue race of fix 26a leaves everything silent). Now in PLAY_DEMONS_SOULS.bat, run_capture.ps1
      and runs.sh. The firmware ATRAC decoder (PS3_DEV_FLASH=real dev_flash) makes no difference so far;
      the launcher keeps no_flash.
    - Verified from the recorded mix (AUDIO_WAV, raw float32 stereo 48 kHz): menu/UI sounds (mono), the
      character-creation theme in stereo whose spectral peaks are C2/C3/G3/Bb3/C4/Eb4/G4 at exact A440
      pitch (so correct speed), tutorial ambience and attack/roll sounds; lag-1 autocorrelation
      0.95-0.996 (real audio, not garbage) -- but every other block was silent, see fix 30. Same in 60 fps mode (pitch unaffected by PS3_CLOCK_SCALE: the
      audio thread is paced by real time). menu_music.wav / tutorial_audio.wav are clips of that run.
    - Debug added: SPU_LISTTRACE=<image> (spu_dma.h: each MFC list element), AUDIO_PEAK shows both ports.
      Method that found it: function-entry counts of the MagicOrchestra code (temporary PPU_MM_SNAP
      override, scratchpad fncount.py), MO init traced call by call (instr077.py), then IP sampling of
      the spinning synth2 thread -> its lifted loop is the stop 0x110 receive.
30. **Choppy audio FIXED -- cellAudio mixed in bursts:**
    - Symptom (user, 60 fps mode): sound "super choppy". Fix 29's check (pitch, autocorrelation) missed it:
      the recorded mix alternates sound / silence in 5.3 ms blocks, 8 of every 15 blocks sounding
      (scratchpad gaps.py: all-zero 256-sample blocks between sounding ones, ~150 a second).
    - Cause: libmixer's _cellsurMixerMain (0x015480F0, readable copy lua_bindings_015480F0.cpp) waits on the
      cellAudio notify queue (q16, capacity 2), reads port 1's read index and writes its block AT that index,
      so each block must be mixed within one 5.33 ms period after its event. The runtime's mix thread was
      paced by WASAPI room: the shared-mode engine wakes it every 10 ms, so it mixed 1-2 blocks back to back
      and pushed their events microseconds apart. PS3_FTRACE showed the mixer waking every 10.0 ms (100/s)
      with ~1 ms of work: the second block of each burst was read before anything wrote it.
    - Fix (libs/audio/cellAudio.c): blocks mixed on an even QPC clock (5.333 ms, Sleep(1) under
      timeBeginPeriod(1) then SwitchToThread to the mark), device buffer pre-filled half with silence and
      kept between 1/4 and 3/4 full by stretching/shrinking the period 1/16; > 50 ms behind = restart the
      schedule instead of a burst. AUDIO_DEVICE_PACED=1 = old loop.
    - Result (sandbox, 60 fps mode, 139 s title -> character creation): mixer wakes 187.5/s spaced 5.3 ms,
      1 dropout in 139 s (was ~150/s), AUDIO_RATE 0 underruns / 0 dropped. Clip: audio_fixed.wav.
31. **Black screen / garbage / stretched triangles after quit-to-title + reload FIXED -- stale RT write-back:**
    - User: after Save & Quit (Start, L2, Cross, Up, Cross) and loading again in the same process the intro
      was pixelated, fog blocky, HUD tilted; earlier a "vertex explosion" after the archstone warp. Sandbox
      repro (PAD_SCRIPT load -> quit -> reload, user save copied into testenv savedata): after the second
      loading screen every frame is exactly 0, HUD included, though the scene target 0x7A0000 is complete.
    - Chain: the final copy (draw into display buffer 0x3D0000, pso 1bbada28a104aa23) draws a full-screen quad
      at RSX local 0xD0; its vertex 0 w read -11.809 instead of 1 (LD_FPCONST dump, now with attr loc/off).
      PPU_WWATCH=C00000D0 (now prints r3/r4/r27-r31; PPU_WWATCH_STACK=1 = stack on every hit): the writer is
      the game's own DLRegularHeap free (func_00AC8CC8) on heap 0x1AD6370 = the local-memory heap (base
      0xC0000000, 0xF800000 bytes, bucket heads at 0xC0000000..0xB8, first block 0xC00000C0 = that quad).
      Its free lists held luminance floats as links (-11.8 = 0xC13CED98 looks like a local pointer).
    - Cause: fix 21's render-target write-back stored EVERY small FP32 surface in the surface cache to guest
      memory at every present. After quit the game frees the luminance targets and its heap reuses them for
      block headers; the renderer kept writing the old session's surfaces over them. LD_RT_WRITEBACK=0 run:
      no heap write into the quad after reload.
    - Fix (rsx_live_draw.c ld_rt_writeback_record): only surfaces written (draw/clear/copy, swin_wgen)
      since their last write-back are stored -- the GPU only writes memory it renders to.
    - Result: quit -> reload in the sandbox plays the intro and the corridor with HUD; brightness as before
      (frame means 16.7 fresh / 15.0-16.6 after reload); only the boot writes touch the quad.
32. **Closing the window now ends the game; F12 frame capture; Boletaria fps findings:**
    - Exit: a closed window left the process "Not Responding" on ~4 cores (twice in user sessions). With
      RSX_LIVE_DRAW=1 the window belongs to rsx_null_backend.c (not the D3D12 backend). Both window
      procedures now call rsx_window_closing(): 3 s after WM_CLOSE the process flushes (on a side thread,
      at most 1 s -- fflush(NULL) can block on a stream another thread holds) and TerminateProcess-es.
      Sandbox test: WM_CLOSE to the TEST window -> gone at t+3 s, "[exit] window closed" logged.
    - LD_F12_CAPTURE=<dir> (now set in PLAY_DEMONS_SOULS.bat -> DemonsSouls\captures): F12 with the game
      window in front records the next present interval: every draw's target before the draw
      (draw_f<frame>_i<idx>_<surf>.ppm) and draws.csv, in <dir>\f<frame>. LD_CAPTURE_AT=<frame> = the same
      without a key. For glitches that cannot be scripted (the Nexus / cutscene white-and-green shapes).
    - Boletaria (user: fps tanks): sandbox load of the user's character at the m02 archstone = ~30 fps.
      Thread CPU: spu job 103%, HighGraphics 77%, synth2 62%, MOStreamingThread 48%, live-draw thread 45%.
      HighGraphics works ~15 ms then usleep-polls ~25 ms per frame; RSX drains come in bursts with gaps
      (waiting for FIFO data). vcache ~24% misses (~143 conversions/frame); texture_content_hash 11% of the
      live-draw thread. spu job samples: spu_wrch 16%, lockline 10%, MFC ~10% -- channel/DMA emulation.
      Not fixed yet.
    - Gotchas: a sandbox run still alive locks port\build_opt\DemonsSoulsRecomp.exe, so the link fails and
      the old binary gets retested -- wait for the test process to end before rebuilding. Git Bash heredocs
      here halve backslashes: write patch scripts with the Write tool, not `python - <<EOF`.
33. **Boletarian Palace: slow motion fixed (adaptive step), SPU lock contention cut; still ~32-40 fps:**
    - User: "fps tanked" in Boletaria. Sandbox (user's save, profile 3) at the m02 archstone: ~31 fps and,
      worse, DES_STEP_STATS = 39.5 steps/s x 1/60 = 0.66 game seconds per real second -- slow motion.
    - Adaptive step (port patch, ppu_recomp_011.cpp func_0001B8D0, on with DES_60FPS; DES_ADAPTIVE_STEP=0 =
      off): the step float at 0x018C8DB4 = the mean real time of the last 24 steps, clamped to 1/60..1/30,
      smoothed 1/4 per step. Result: Boletaria 39.4 steps/s, step 0.0254, game time 1.000; tutorial still
      60.0 steps/s, step 1/60, 1.000. Walk test (3 s of W at 160 s, adaptive 60 vs DES_FPS=30): same spot.
    - Lock-line lock: SPU_JOB_STATS=1 (spu_workload.c; per-image async task counts/time + lock stats every 5 s)
      showed 7.2 M acquisitions/s, 690 k/s contended, 726 ms/s spent waiting; SPU_LOCK_SITES=<file> (callers by
      return address, rip_sample.py format) put 98% on SPU_WrEventAck -- SPURS kernels/dispatchers ack events
      in their poll loops. event_status updates are interlocked OR/AND already, so the lock there protected
      nothing: removed (SPU_EVENTACK_LOCK=1 = old). Now 1.7 M/s, 29 ms/s waiting; img7 tasks ~30% cheaper.
      fps barely moved (30 -> 32), so contention was real but not the limit.
    - Where a Boletaria frame goes (PS3_FTRACE, now with a busy span per async SPU task, who = 64 + image;
      scratchpad chain.py draws HG / per-image SPU rows / RSX): per HighGraphics cycle ~50 ms =
      ~13 ms cond_wait while the SPU animation tasks run (img10 = Havok LtSpuAnim, img5 ~7 ms single task,
      img3/4/6), ~13 ms HighGraphics own work, ~24 ms waiting at 0x00ACB0A0 for SpursTaskCommandDispatcher's
      reply (polls 0x1B50FD0, written by SPU DMA) while it builds the command stream and the live-draw thread
      drains it in bursts (that thread idles ~1/3 of the time waiting for commands). Tutorial: the same reply
      comes in 0.03 ms. 60 fps here needs all three stages ~3x faster -- a project, not a fix.
    - Ruled out: SPU_DMA_REPEAT_BACKOFF_MS (no change), thread spawning per SPU task (~20/frame, ~2 ms),
      LBP_SPU_SERIAL (off), runtime -O level (already -O2 + SSE4.1; lifted PPU is -O1).
34. **Boletarian Palace ~40 -> ~56 steps/s (presents ~60): lifted SPU code was built without SSE4.1:**
    - Frame chain, measured: HighGraphics pushes ~37k commands per frame to SpursTaskCommandDispatcher
      (img2), ~780k/s. SPU_MFC_STATS=1 / SPU_MFC_PCS=2 (spu_channels.c): per command one GETLLAR (LS
      0x4618) + PUTLLC + 128-byte GET (0x4694) and one small PUT (0xC408, 45 B avg); 5.5 M GETLLAR/s more
      are its idle loop (0x5120). At ~0.8 us a command the dispatcher fell ~17 ms behind HighGraphics' 13 ms
      of pushing -- the "reply wait" at 0xACB0A0. Timeline tools: scratchpad chain2.py (every PPU thread +
      SPU tasks + dispatcher idle + RSX), qphase.py (drain coverage inside the reply waits),
      stack_sample.py (samples charged to the lifted function on the stack), SPU_IDLE_STATS=1,
      GCM_STREAM_STATS=1, LD_FLUSH_STATS=1.
    - THE fix: port/project/CMakeLists.txt gave the lifted SPU sources "-O2" only; the runtime library has
      -msse4.1, these did not, so spu_helpers.h compiled every SSE helper to its fallback -- spu_shufb as a
      byte loop called out of line 1,558 times in the dispatcher alone. Now "-O2;/GS-;-msse4.1" (and
      spu_shufb always_inline). Dispatcher idle 38% -> 50%, SPU anim tasks ~7 ms -> ~4.5 ms, Boletaria
      42 -> 56 steps/s, game time 1.00; tutorial 60.0. Audio (synth2 is SPU) checked: 0 dropouts in 195 s.
    - Smaller, kept: channel fast path for lifted code (spu_helpers.h, SPU_NO_CHANNEL_FAST=1 = off:
      MFC_LSA/EAH/EAL/Size/TagID/WrTagMask writes and RdTagStat/RdAtomicStat reads inline; mfc_for 8% ->
      0.7%); 4-lane texture_content_hash (renderer 481 -> 380 ms/s draining); GCM streaming (cellGcmSys.c,
      GCM_STREAM=0 = off): `get` published every 256 words, a pass picks up a `put` that moved while it ran
      (<= GCM_STREAM_MS, 4), an SPU DMA of `put` kicks the present thread. The last did not move fps on its
      own (the dispatcher was the limit) but removes the walker's 4 ms naps.
    - Left: HighGraphics' own ~14 ms CPU per frame (lifted PPU, -O1, no SSE4.1 -- the PPU headers have no
      SSE-conditional code, so the flag alone would not help much); per-op cost of emulated atomics/DMA
      (~45% of the dispatcher: debug-switch checks in mfc_do_transfer / spu_mfc_atomic, lockline, coherency).
35. **Nexus / cutscene "lighting bug" (huge white, salmon, green, grey rectangles) FIXED:**
    - Repro (sandbox): with a profile already on the system, NEW GAME -> profile slots full -> OK -> overwrite
      slot 4 -> create -> "Would you like to play the journey to the Nexus?" NO -> the Nexus intro cutscene.
      Without any save the question is never asked (straight to the tutorial). LD_CAPTURE_AT now takes a
      list of frames (rsx_live_draw.c), since captures slow the run and the glitch frame drifts.
    - scratchpad drawdiff.py on the capture: the shapes are single blended quads drawn after the scene,
      each sampling a 64x64 texture of format 0x9E = D8R8G8B8 (local 0x24BA380 / 0x24BE400 / 0x24C2480) --
      the lens-flare / glare sprites. The live renderer had no case for D8R8G8B8, so the span was 0, the
      decode failed and the white fallback was bound: each flare became a solid quad in its vertex colour.
      Fix: ld_tex_base_fmt() decodes it as A8R8G8B8 (same layout; the D3D12/Vulkan backends already map
      both to B8G8R8A8). The cutscene now shows proper flares (rings, discs, starburst) and the in-game
      Nexus is no longer washed grey. The Boletaria intro uses the same sprites (not re-checked).
36. **Boletarian Palace ~56 -> ~58 steps/s (57-60, real speed): AVX2 SPU floats, present-first frames:**
    - -mavx2 for the lifted SPU sources (port/project/CMakeLists.txt; patches/port-project-CMakeLists.txt):
      spu_helpers.h's vector paths for the SPU float ops, estimates and conversions are under __AVX2__,
      so every lane went through the exact scalar emulation. No -mfma. Image 5 (FFX cluster draw) tasks
      207 -> 147 ms/s, longest 6.2 -> 4.2 ms. PS3_REQUIRE_AVX2=1 (now in the PLAY bat) makes
      boot_main.cpp stop with a message box on a CPU without AVX2 (the user's 7950X3D has it).
    - Present-first (rsx_live_draw.c, LD_PIPELINE=1, the default): the present flush submits, Present()
      hands the frame to the swap chain, THEN the walker waits for the GPU and stores the write-back. The
      GPU is still idle at every frame start. The allocator / upload arena / retired list are double-
      buffered for it (ld_pipe_present). LD_PIPELINE=0 = the old order.
    - LD_PIPELINE=2 = full pipelining (next frame recorded while the GPU finishes this one, write-back
      copies taken early -- ld_kick_after_draw when drawing moves off a small FP32 target -- and kicked,
      so a present waits only for those). Steady 60.0 in Boletaria, BUT the tutorial's exposure got stuck
      at a flat black / grey / olive screen in about one run in two (race not found; the D3D12 debug
      layer reports nothing once the kick runs after the sampled surfaces' transitions back, and its
      slower timing hides the bug). Bisect results: synchronous GPU + deferred write-back = fine; async
      GPU = broken even with the write-back disabled or committed early. Experimental only.
    - Found on the way: ld_kick_after_draw ran before a draw's sampled surfaces went back to
      RENDER_TARGET (now after); 2.16 M PPU stores/s go through the lock-line path, 1.9 M of them to the
      dispatcher queue's control line 0x01B51080 with only 0.07 SPUs actually holding it (SPU_COH_STATS=1,
      spu_coherency.c) -- about a third of HighGraphics' busy time; making those stores lock-free needs a
      PUTLLC that commits only its changed words (not done). The lock-acquire counter is now only kept
      under SPU_JOB_STATS; idle SPU event polls pause 16x (SPU_IDLE_PAUSE) -- neither moved fps.
    - Tried, no gain: -O2 for HighGraphics' 11 hottest lifted PPU units (DS_PPU_O2_UNITS, kept, harmless);
      LD_KICK_DRAWS=16 (worse GPU tail).
    - Tools: scratchpad all_sample.py (every thread; misses per-task SPU threads), capalign.py (two
      captures aligned by draw signature), blackframes.py; LD_PRESENT_DBG=1 (scanned-out surface),
      LD_CAPTURE_AT=<f1,f2,...>. Verified: tutorial x3, Boletaria standing + walking + a fight, save &
      quit -> reload, the Nexus cutscene.
37. **Boletarian Palace judder ("60 fps but not smooth") -- present pacing:**
    - Measured with DES_STEP_LOG=<file> (port debug in ppu_recomp_011.cpp func_0001B8D0: "<us> <step>"
      per game step) + LD_PRESENT_LOG=<file> (rsx_live_draw.c: "<us> <frame>" per Present), both on the
      ps3_qpc_us clock, 60 s windows from *_FROM seconds; scratchpad jitter.py. Boletaria: 64.5
      presents/s, present-interval sd 8.4 ms, 12% of presents under 4 ms apart then 25-40 ms gaps --
      when the game falls behind, HighGraphics renders two frames back to back and the walker reaches
      both flips together: 30 fps with doubled motion, though the counter says ~60.
    - LD_PRESENT_PACE=<fraction> (rsx_live_draw.c, before Present; set to 0.85 in the PLAY bat; off by
      default in the runtime): a present arriving sooner than fraction x the running average interval
      waits until then (<= 20 ms; stalls over 50 ms do not enter the average). Boletaria: present sd
      8.4 -> 3.3 ms, no sub-4 ms presents, 59.1-59.8 steps/s; tutorial sd 1.7 ms at 59.8. 0.93 was too
      tight (sd 2.5 but 47-57 steps/s -- the walker waits while the FIFO backs up).
    - Not it: DES_FRAME_INTERVAL=2 (flips capped at 60 on the 120 Hz vblank) -- worse, 54 steps/s.
    - The user's monitor runs at ~100 Hz (3440x1440): 60 fps cannot be even there without VRR (frames
      alternate 1 and 2 refreshes). G-SYNC for windowed mode, or 60 / 120 Hz, fixes that part.
38. **Lens flares "way too bright" -- real ZPASS occlusion counts:**
    - The flare code (LensFlareDrawEntity, readable copy; reads the count through cellGcmGetReport)
      draws an invisible 24x24 probe quad 300 units out along the light between ZPASS
      CLEAR_REPORT_VALUE (0x17C8) and GET_REPORT type 1 (0x1800), with SET_ZPASS_PIXEL_COUNT_ENABLE
      (0x17CC) on, and sets visibility = count / (w x h) (floats at +0x50/+0x54). The GCM walker
      answered every ZPASS report with 0xFFFF: ~114x full strength, never occluded (the orb trails and
      white blow-outs in the Nexus intro, the burst through solid rock at the Stonefang archstone).
    - rsx_live_draw.c ld_occ_*: per-draw D3D12 occlusion queries while 0x17CC is set, summed from the
      last clear, ResolveQueryData before every Close (present flush and mid-frame kicks), stored once
      that submit's fence passes (cellGcmSys.c gcm_report_store_value; g_gcm_zpass_by_host makes the
      walker leave type-1 values alone). One frame late at most -- the game checks its own label and
      reads the previous value meanwhile. LD_OCCLUSION=0 = old 0xFFFF; LD_OCC_DBG=1 logs reports;
      LD_CAPTURE_ON_ZPASS=<n> captures the frame after the n-th report.
    - Verified by reading back the depth plane at the probe (debug code since removed): in Stonefang
      and the Nexus intro the probe always sits behind real geometry (stored depth 0.97-0.998 vs the
      probe's 0.9997), sky pixels hold depth above the probe, so 0 there is the right answer. No spot
      with the sun in open sky found yet to see a flare drawn at its proper strength.
    - Gotcha: NV4097 0x1D84 is ZCULL_EN, 0x1D7C AA control, 0x1D8C ZSTENCIL_CLEAR_VALUE -- the ZPASS
      enable is 0x17CC.
39. **Frame rate across the five worlds (60 fps mode, LD_PRESENT_PACE=0.85, sandbox):**
    - DES_WARP_AT=<sec>:<area>,<block>,<point> (port debug in ppu_recomp_011.cpp func_0001B8D0): sets the
      stage manager's next map / spawn point / request byte the way the event scripts'
      proxy:WarpNextStage does (lua_WarpNextStage 0x451430). World starts (SCRIPT/m01_00_00_00.lua):
      2,0,999 Boletaria 1-1; 3,1,999 Shrine of Storms; 4,0,999 Tower of Latria; 5,0,999 Valley of
      Defilement; 6,0,999 Stonefang Tunnel; 998/997/996 = later blocks. Scratchpad area.sh.
    - steps/s and present-interval sd over 60 s: Latria 57.7-59.7 (sd 1.2 ms without the frame dump),
      Valley 59.3-59.9 (1.7), Stonefang 59.8-60.0 (1.1), Shrine 56.2-59.2 (1.3); Boletaria 59.1-59.8 (fix 37).
    - Remaining unevenness is the game: a step runs 25-40 ms about once a second in Latria/Shrine, the
      next frame repeats (the graphics thread presents with no new step). The render thread is not it:
      Present averages 0.25 ms, the GPU wait 0.5 ms (LD_PRESENT_LOG now logs pace / Present / GPU wait).
    - First visit to an area compiles 12-18 new pixel shaders (scratch\rsx_shader_cache_v3), 0.1-0.25 s
      hitches when they first come into view; none on later visits. LD_FRAME_DUMP adds a ~37 ms hitch
      per dump -- keep it off when measuring pacing.
    - Seen here, fixed in 40: coloured static over the whole screen after dying in Shrine of Storms.
40. **Coloured static after dying / black world = live-draw surface table full:**
    - Shrine of Storms, after a death: the whole scene under coloured 8x8-pixel static, the HUD clean;
      one run also had the world black with only the character drawn. Not soul form itself (the test
      character was already in soul form before it died and looked fine).
    - rsx_live_draw.c kept 64 colour surfaces (MAX_SURFACES) and never freed one. The game moves its
      post-processing chain to new local-memory addresses after map loads (Nexus -> Shrine, the reload
      after a death), so the table filled with dead entries and every new target was dropped
      ("[surfsz] surface table full (64); dropping ...", draws logged drop_surface). Dropped: the two
      160x90 bloom targets -> the final composite (0x7A0000, reads the bloom as t1) sampled raw guest
      memory nothing had rendered = the static; in another run the 16x16 exposure targets too -> the
      tone map used garbage, the world came out black.
    - Fix: surface_t.used_frame (set when bound as a target in current_surface and when sampled);
      when the table is full surface_get recreates the slot unused longest, if idle for
      LD_SURF_EVICT_FRAMES (default 120; 0 = old drop behaviour), never the last presented / drawn
      target or one with a write-back pending. Logged as "[surfsz] surface table full; slot N (...,
      idle F frames) reused for ...". Sandbox: Shrine, two deaths, no static, world normal, all 403
      draws of a soul-form frame execute, ~58 steps/s (soul_static_fix.png).
    - The zeta table (also 64) was not near full: 6 entries in the same run.
    - Capture aid: draws.csv rows now carry fp=<loc>_<offset> (matches LD_HLSL_DUMP's hlsl_fp files;
      the PSO-key file names drift with per-frame constants). LD_F12_CAPTURE wants an absolute path --
      the sandbox runs from testenv, a relative one silently writes nothing.
41. **Character name typed in a text box (cellOskDialog):** the OSK stub answered every request at
    once with OSK_TEXT, and PLAY_DEMONS_SOULS.bat always set it (DES_NAME, default "Slayer").
    - Now LoadAsync posts LOADED and opens a small Win32 window on its own thread (the game's prompt,
      "Entry Character Name"; an edit box with the initial text, limited to the field's length -- 16;
      OK / Cancel = Enter / Esc; OK disabled while empty). OK posts FINISHED with the text (UTF-16, so
      any character the edit box takes; whether the game's font has it is another matter); Cancel /
      closing it reports CANCELED (untested what DeS does then). OSK_TEXT (or SetDefaultResponse) still
      answers at once with no window: the sandbox runs.sh defaults it to Slayer; the launcher only sets it
      when DES_NAME is set by hand.
    - cellPad's focus test counted any window of the process as the game, so typing in the box would
      also have pressed E = Cross / Enter = Start: pad_host_window_focused() is false while
      g_osk_host_window_open. cellSysutilQueueEvent gained a producer lock (the box posts from its thread).
    - Sandbox check: OSK_BOX_AUTO=<text>[|<file.bmp>] (TEST) makes the box type <text>, save a picture of
      itself and press OK after 1.5 s. "Tester" -> log "text box open (limit 16 chars)", "typed Tester",
      Create Profile shows Name Tester, the profile saved with it, the Nexus intro follows
      (name_entry.png). FindWindow from a separate tool process cannot see the sandboxed game's windows,
      hence the in-process hook.
42. **"Lag" turning the camera in Boletarian Palace = 60 fps on a 100 Hz monitor -> 50 fps display lock:**
    - User's save (testenv/save_user_1029, profile 4 = Palace; scratchpad bol.sh restores it, KEYS= key
      script). Holding L (camera right) 15 s: ~57 steps/s, presents a steady 60 -- the counters look fine.
    - LD_PRESENT_LOG now also logs the swap chain's frame statistics (last present count, the present
      count + vblank of the last frame that reached the screen); scratchpad cadence.py turns that into
      refreshes per frame. Primary display = 3440x1440 at 99.97 Hz (modes 50/60/85/100 only): frames
      stayed up 1 refresh 19.5%, 2 74.5%, 3 6.0% -- 10 / 20 / 30 ms on screen, judder in every pan. Plus
      ~57 steps for 60 presents = ~6 repeated frames a second.
    - 50 fps mode: PS3_VBLANK_HZ=100 (2-vblank game loop = 50), PS3_CLOCK_SCALE=167, LD_PRESENT_INTERVAL=2
      (each frame at least 2 refreshes), LD_PRESENT_PACE=0; the adaptive step goes to 0.02. Same spin:
      2 refreshes 98.2% (1: 0.8%, 3: 0.9%), game time 0.999-1.000 s per real s. User watched the test
      window: "BUTTERY". PLAY bat: DES_FPS unset -> 50 when WMI CurrentRefreshRate is 95-105, else 60;
      DES_FPS=60/50/30 forces a mode.
    - Also measured: shader-compile freezes the first time an effect appears (walking forward: 8 new pixel
      shaders = 302 + 261 ms). LD_PSO_TIME=1 logs per new PSO: D3DCompile vs ~120 ms (up to 300),
      ps ~30 ms, CreateGraphicsPipelineState ~0.5 ms. fxc flags do not help (L0 same, skip-opt halves vs
      but slows ps; scratchpad fxc_time.py). The disk cache (scratch\rsx_shader_cache_v3) keeps them for
      later runs; the user's last Palace session compiled none. Async compile would remove the rest.
    - Gotcha: LD_FRAME_DUMP_EVERY=60 adds a 37 ms hitch every 60 frames -- use a huge value for timing runs.
43. **Frame-rate launchers: PLAY_DEMONS_SOULS_30FPS.bat / _50FPS.bat / _UNLIMITED.bat (project root):**
    each sets DES_FPS (30 / 50 / unlimited) and calls PLAY_DEMONS_SOULS.bat, which stays auto (50 on a
    ~100 Hz monitor, else 60).
    - Uncapped: DES_60FPS=1, PS3_VBLANK_HZ=480 (2-vblank loop = up to 240 fps), PS3_CLOCK_SCALE=200,
      LD_PRESENT_INTERVAL=0, LD_PRESENT_PACE=0, and DES_MAX_FPS=240 -- new port patch: the adaptive step's
      floor was a fixed 1/60 s (above 60 steps/s the game would run fast); now 1/DES_MAX_FPS
      (ppu_recomp_011.cpp, default 60; saved in patches/recompiled-port-patches.diff).
    - Sandbox, user's Palace save: uncapped 67.6 steps/s, ~79 presents/s, game time 1.000 (the 60 cap was
      not all CPU: 68 > 57); on the 100 Hz screen frames show 1-3 refreshes (uneven, as expected without
      VRR). Title screen alone ran 240. 30 fps: 30.0 steps/s, step 1/30, game time 0.99-1.00, frames
      3 / 4 refreshes (100 Hz cannot show 30 evenly either).
    - Test gotcha: uncapped boots faster, so bol.sh's PAD_SCRIPT Down at 85 s landed on the title menu
      (NEW GAME -> "profile slots full"); use PADS without 85:0x0040 there.
44. **God mode (F9 toggle; DES_GOD=1 = on from the start):** port patch at the top of func_0001B8D0
    (ppu_recomp_011.cpp; patches/recompiled-port-patches.diff), runs every game step on the main thread.
    - The event scripts' own "player does not die" switch: proxy:SetDeadMode(10000, true) (m08 tutorial,
      Shift-JIS comment). lua_SetDeadMode (0x44AB30): chr = func_004142A8(*(TOC[-0x7884] - 0x7F0C), id, 0, 0),
      then bit 0x10 of the doubleword at chr+0x310. lua_GetHp / GetHpRate: HP chr+0x3C4, max +0x3C8.
      PlayerRecover (0x4392B0) is an empty stub in retail.
    - Player stats seen with DES_GOD_DUMP=1 (chr+0x380..0x47C every 5 s; user's soul-form char):
      +3C4 HP 174, +3C8 max 276 (soul form = half of +3DC 552), +3CC MP 7, +3D0 max MP 106, +3D4 / +3D8
      stamina 91 / 91, +3E0 / +3E4 base MP / stamina. The HUD's blue bar matched MP 7/106.
    - While on: the flag is set, HP -> max, MP -> max, stamina (+3D4 -> +3D8) -> max each step; F9 off clears the flag (also a script-set
      one -- harmless outside the tutorial). The patch calls the lifted lookup with a saved/restored
      ppu_context. Runtime helpers (cellPad.c): ps3_host_hotkey(vk) = edge-triggered, game window in front
      (or PAD_KEY_SCRIPT, which now knows F9); ps3_host_title_suffix(s) sets "<title>  [GOD MODE - F9]"
      from a helper thread (SetWindowText waits for the window's thread).
    - Sandbox (user's Palace save): F9 at 160 s -> HP 174 -> 276, MP 7 -> 106 (bar full), off at 180 s.
      Stamina: 10 s of W + SPACE (sprint) with it off 91 -> 54 -> 6; the same sprint with it on stays 91.
      Not tested: an actual killing blow, falls (kill planes may bypass the flag).
45. **"Demon's Souls PC Remaster" mod (fromsoftserve, Nexus mod 106) -- PLAY_DEMONS_SOULS_REMASTER.bat:**
    - Made for RPCS3 (relit models, normal / specular maps, cubemap armour, shadows; "the whole game").
      The user downloaded "PC Remaster" (file name says 0.95, 2026-07-31, 400 MB) to Downloads; the
      optional ReShade preset is for RPCS3's Vulkan and was not used. Nexus needs a login to download.
    - DemonsSouls\game_remaster = `cp -al game` (hard links, ~0 extra space) + the mod: 618 files replaced,
      145 added (new OBJ/o0001.. objbnds the modded MSBs reference, MAPSTUDIO .msb files, drawparams, mtd,
      menu). Install script (session ca3b5f74 scratchpad, remaster_install.py): matches the
      mod's lowercase paths to the game's case, REMOVES each existing file before writing (it is a hard
      link into DemonsSouls\game -- writing through it would change the normal game), and checks no
      replaced file still shares an inode with game\. List in game_remaster\REMASTER_INSTALLED.txt.
      To remove: delete game_remaster (the normal game keeps its own links).
    - PLAY bat: DES_GAME=<folder under DemonsSouls> (default game) picks the EBOOT path, and with it the
      VFS root (boot_main derives it from the EBOOT path); title "... - PC Remaster mod". Saves, hdd1
      cache and the shader disk cache are shared. Sandbox runs.sh takes DES_GAME too.
    - Sandbox, user's Palace save: VFS root game_remaster, 54-61 fps, no pso-fail / surface-table lines;
      remaster_compare.png / remaster_compare2.png (normal above, mod below): same scene, the character
      now shaded by the room's lights. Not compared against RPCS3, other worlds not visited.
46. **Stutter recording -- PLAY_DEMONS_SOULS_RECORD.bat + tools\perf_report.py (2026-10-30):**
    - The user still saw stutters in Boletaria (camera pans, near geometry) that scripted test runs may not
      hit, so the player records and the log gets analysed. The bat = PLAY_DEMONS_SOULS.bat + DES_PERF=1,
      LD_PRESENT_LOG=DemonsSouls\perf\<date_time>\perf.txt, LD_PRESENT_LOG_FROM=0, LD_PRESENT_LOG_SECS=0
      (new: 0 = whole run; default still 60 s), DES_REFRESH (monitor Hz). ~25 MB/hour, flushed every second.
      F8 in the game window = "mark" (the player saw a stutter); title shows [RECORDING - F8 = stutter, N marked].
      (Not F10: that opens the window menu.)
    - One file, one clock: present lines (+ col 10 = render-thread CPU us since the previous present) and
      "# <us> <kind>" notes from ps3_perf_note() (rsx_live_draw.c, SRW-locked): step (011.cpp: step s,
      right stick, pad source 1 XInput / 2 kb+mouse, host polls, mouse dx/dy, game-thread CPU us via
      ps3_thread_cpu_us = QueryThreadCycleTime / TSC rate), mark, pso (compile >= 1 ms), read (ppu_fs.cpp
      cellFsRead / AIO reads >= 2 ms with path). cellPad: ps3_host_pad_debug(); "F8" key-script name.
      God-mode and recording share the title suffix (des_title() in 011.cpp).
    - perf_report.py [perf.txt | folder] (default newest perf\*): display Hz + refreshes-per-frame
      histogram, present/step interval percentiles, every hitch (frame up longer than usual, or present
      > 1.5x median) with causes (shader compile, slow reads, game step late + thread busy/waiting by CPU
      time, Present blocked, GPU wait, renderer late), F8 marks with the hitches in the 3 s before,
      worst N, hitches per 10 s, camera-input stats. --from/--to seconds, --top N.
    - Sandbox (user's Palace save, 50 fps, IJKL camera spin): display 99.75% at 2 refreshes, ~40 hitches/min
      by the CPU-side rule; most are "game step late ~40 ms, game thread WAITING (CPU ~6 ms)" -- the
      game thread blocked on something (SPU jobs / flip / RSX?) -- next lead; a few busy 160-200 ms steps
      (loads) and a 240 ms render-thread spike (161 ms CPU) at 113 s.
    - Boletaria 1-1 gate question (not a bug): m02_00_00_00.lua has THREE levers. Event 10 (lever o2211_01,
      entity 1005) and event 50 (o2211_08, 1006) open the right / left gate-tower doors (o2241 / o2251 at
      ground level, y~33). The main gate (o2221, 1001) opens only from event 0, lever o2211_00 (1000) at
      (16.3, 70.5, -37.3) -- ~37 m up, right above the gate by the gear o2160 -- which plays remo 20001
      (scn020001, "the main gate opens") and turns on the fog walls. The user had pulled the two tower levers.
47. **Stutter: every ~0.75 s a repeated frame + a lost frame -- double present of one flip (2026-10-30):**
    - Found with the fix 46 recorder + new stack sampling (DES_PERF_STACKS=1: a sampler thread suspends the
      main thread -- and DES_PERF_STACK_THREADS=<guest names>, and "rsx" -- every 4 ms once a step is
      DES_PERF_STACK_MS (28) ms old and logs exe RVAs; symbolise with llvm-symbolizer + the PDB; scratchpad
      stacks.py) and flip events in the perf log (cellGcmSys.c: vb, vbh = vblank handler delivered,
      fdone, flipreq <buf> <in_fifo>, flipexec).
    - Chain: late steps sat in sys_cond_wait under func_00D1E228 (Class0187CB90 vf12 posts a message to
      HighGraphics and waits); HighGraphics sat in HighGraphics_FrameLoop's DLSingleSignal semaphore,
      which the vblank handler posts. The event timeline showed: at every repeat, a 2nd Present 1-3 ms
      after the real one with no flipreq and ~0.3 ms render CPU, then 18-23 ms GPU wait (its sync-
      interval-2 Present queues behind the previous flip), and NO vblank ticks for ~39 ms -- the
      vblank ticker is the same thread (boot_main vblank_ticker). The game's frame loop missed its
      vblank target and lost a whole frame: on screen a repeated picture, then a jump.
    - Cause: the ticker presents on two signals -- cellGcm_take_flip_pending() (before the drain) and
      a flip-count change (bottom of the loop). gcm_flip_request set the pending flag BEFORE bumping
      the count, so the pending path could present, record the old count, and the count check then
      presented the same frame again.
    - Fix: boot_main present_pending(): the count decides, the flag only triggers a look (one present
      per flip; PS3_PRESENT_ONCE=0 = old); gcm_flip_request bumps the count, MemoryBarrier, then sets
      the flag. Sandbox, Palace camera spin, 75 s window:
        50 fps: repeated frames 97/min -> 0.8/min, steps 48.4 -> 50.0/s, worst step 54 -> 31 ms.
        60 fps (A/B with PS3_PRESENT_ONCE=0): repeats 149 -> 11/min, steps 58.1 -> 60.0/s, steps
        > 30 ms 77/min -> 0.
      Fix 37's "paired catch-up presents" (LD_PRESENT_PACE) were very likely these duplicates; pacing
      left on. GCM_PUMP_THREAD=1 was tried first: no effect (delivery wasn't the problem).
    - perf_report.py now prints "repeated frames", counted by flip: each present shows the latest flipreq
      before it; "same flip shown twice" = this bug, "flip with no new step" = the game repeating. (The
      first version compared presents with step notes directly and miscounted when a step started ~2 ms
      after a present -- 8.8/min false repeats in Shrine.)
    - Other worlds (sandbox, user's 50 fps / 100 Hz settings, scratchpad area50.sh: profile 3, warp at
      160 s, walk + camera turns, 75 s window), same flip shown twice per minute old -> new:
        Shrine 49.8 -> 0, Latria 114 -> 0, Valley 57 -> 0, Stonefang 62 -> 0; steps 48.1-49.0 -> 49.7-50.0/s;
        hitches 61-92/min -> 2-21/min. Left on the fixed build: first-time pixel-shader compiles 25-70 ms
        (new to the sandbox cache; cached on disk after), the test's own frame dumps (~22 ms render CPU),
        and one 175 ms busy game step in Valley that a rerun with stack sampling did not reproduce
        (rerun: 1.6 hitches/min, worst frame 33 ms).
48. **User's first recording after fix 47 (2026-10-30, 34 min, 50 fps / 100 Hz):**
    - 49.9 fps, 99.0% of frames up exactly 2 refreshes, same flip shown twice 3 in 34 min (fix 47 holds).
      Two F8 marks at the end, in Boletarian Palace 1-1 by the wooden scaffolding: no long frames, but
      uneven pacing -- render-thread CPU alternated ~3 / ~23 ms per frame (whole session median 6.5 ms),
      presents 13-28 ms apart; now and then a frame missed its refresh (3 then 1 refresh).
    - Reproduced from a copy of the user's save (testenv/save_user_1030, scratchpad bol2.sh SAVE=...):
      render CPU steady ~15 ms per frame there (1-2 ms on the title / load screens). New sampler mode
      DES_PERF_STACK_EVERY=<ms> samples the watched non-main threads ("rsx", named guest threads)
      continuously; scratchpad cmpstk.py / hotlines.py summarise. Renderer thread there, self time:
      sink_end_impl ~20% (memcpy of each draw's converted vertices into the upload ring, line ~8519),
      ld_vc_hash ~8% (vertex-cache mutation hash of guest vertex data every draw), texture_content_hash
      ~7% (per-texture hash every frame), get_pso fnv1a ~4%, vertex remap/fetch ~4%, idle ~22%.
      I.e. per-draw re-upload + re-hash of all geometry every frame; scales with draw count.
    - Possible fixes (not done): keep vertex-cache hits in GPU-resident buffers instead of re-copying;
      replace per-frame hashing with guest write tracking or spread it over frames; cheaper PSO key.
    - perf_report.py: F8 marks now look back 10 s and show present-interval spread and render CPU.
49. **Renderer CPU cut ~35% in heavy scenes (2026-10-30, follow-up to 48):**
    - LD_RSTATS=1 prints per-frame renderer work every 300 frames. By the Boletaria 1-1 scaffolding
      (user's save): ~800 draws a frame; every frame it re-hashed 54 MB of textures and ~22 MB of
      vertex/index source and copied 46 MB of cached converted vertices into the upload ring.
    - (a) GPU-resident vertex cache (LD_VC_GPU=0 = old): cached draws' converted vertices + indices
      are written once into a 256 MB persistently mapped upload-heap arena (~110 MB used by the
      scaffolding; when full, entries not drawn for 4 frames are evicted and that draw uses malloc) (power-of-two blocks
      256 B..16 MB, split on demand; frees wait in a pending ring for the fence covering all work
      recorded at free time) and bound in place -- ring copy 46 MB -> 0. Indices start 16-byte
      aligned after the vertices. Arena data is write-only (write-combined; never read back).
    - (b) Adaptive texture checks (LD_TEX_HASH_EVERY=1 = old): a texture unchanged for 8 full hashes
      gets a sparse probe per frame (64 B of every 4 KB + the last 64; textures < 32 KB always
      full) and a full hash every 16th frame staggered by slot; probe mismatch -> full hash now.
    - (c) Adaptive vertex-source checks (LD_VC_HASH_EVERY=1 = old): a cache entry is checked once
      per frame (repeat draws of the key reuse it); stable entries get a sparse probe (ranges
      <= 4 KB in full, else 32 B of every 1 KB + last 32) and a full check every 16th frame.
      Hashing 76 MB -> ~8 MB a frame.
    - (d) get_pso: vertex-program length / FNV hash / texture-fetch mask memoised on (start slot,
      rsx_dispatch_vp_generation -- a global bumped on every vp[] write in rsx_dispatch.c). Same
      key values (shader disk cache unaffected); was a byte-wise FNV over the program twice a draw.
    - Render-thread CPU at the scaffolding, median: 14.3 ms -> 9.5 ms (a: 11.8, +b/c: 10.0, +d: 9.5).
      Other worlds (area50.sh, 75 s): Shrine 5.4 -> 4.1, Latria 7.6 -> 5.4, Valley 6.0 -> 4.7, Stonefang 7.1 -> 4.9 ms; one 981 ms game-thread wait in one Stonefang run did not reproduce on a rerun (worst step 31 ms).
      A/B frame dumps (all three switches off vs on, same frames, standing still): identical but
      for the random embers / fire flicker. Remaining: ~2.5 ms/frame waiting for the GPU at the
      present (not CPU), ~125 vertex-cache misses a frame whose key changes every frame (dynamic
      geometry: misses land in slots not used last frame) -> full conversion each frame.
50. **Seconds-long judder after a late frame: the game's catch-up frames + a display wait on the drain
    thread (2026-10-30, user's 2nd recording after fix 49, 19 min, 50 fps / 100 Hz):**
    - Mostly smooth (99% of frames up exactly 2 refreshes), but F8 marks 3 and 4 sit in 3-4 s stretches
      (589-593 s, 944-947 s, 966-970 s) where presents alternate ~38 ms / ~3 ms: 45 presents/s, frames
      up 1-4 refreshes. Every step still has its own flip, but each pair is a full frame (~10-12 ms
      render CPU) and, 0.6 ms after it, a frame the game drew without its 3D scene -- its catch-up
      frame after a late one (sandbox draw counts: ~150-180 draws vs ~850; HUD / post). ~25 real
      pictures a second. Onset at 588.8 s: one late step (8 ms game-thread CPU, started 18 ms late).
    - What kept it going: after a pair's catch-up present, the walker's post-Present wait (LD_PIPELINE=1
      waits for the frame's fence) took 7-9 ms -- the fence came after the copy into the swap chain
      buffer, and with sync interval 2 and two presents 3 ms apart that copy waits on the GPU until
      the display gives a buffer back. The walker is the thread that drains the guest FIFO, so the next
      frame's commands sat for those ms, that frame came out late too, and the game made another
      catch-up frame. In the locked state the same wait was ~3 ms a frame in the user's log -- slack the
      drain did not have. (Vblank ticks were on time throughout; the game's DLSingleSignal post only
      fires when the semaphore is 0, so no queued wake-ups either.)
    - Fix (rsx_live_draw.c, LD_PRESENT_SPLIT=0 = old): with LD_PIPELINE=1 the present records the
      render-target write-back, submits the frame (ld_kick_now, factored out of ld_kick_after_draw) and
      notes that fence, then records the swap-chain copy and presents; after Present it waits only for
      the frame's fence. The copy still waits for the display, on the GPU queue, not on the walker.
      Post-Present wait, sandbox: scaffolding 1.52 -> 0.46 ms mean (frames waiting > 3 ms: 389 -> 0),
      Latria 3.11 -> 0.21 ms; render CPU, cadence and pictures unchanged.
    - Not reproduced in the sandbox: the user's save (testenv/save_user_1030b; profile list is most-
      recent first = no DOWN keys) loads mid-fight in the torch hall; forced late steps
      (new DES_HITCH_AT=<s>:<ms>,... port debug in ppu_recomp_011.cpp: Sleep on the main thread once)
      at the scaffolding, at the Palace start and pinned to one CCD (scratchpad runs.sh AFF=FFFF) all
      recovered after one pair. Their stretches need heavier moments than the tests reach (combat).
    - Perf log: last column = draws recorded for the frame. perf_report.py counts "game catch-up
      frames" (a light frame < 17 ms after the previous one; by draws, else by render CPU) with the
      longest alternating stretch, and per F8 mark (user's log: 608, longest 64 in a row = 2.6 s;
      marks 3 / 4: 86 / 59 in the 10 s before). Marks 1, 2, 5, 6: single frames up 3 refreshes.
    - Test-script gotcha found here: area50.sh / spot.sh / bol.sh set DES_FPS=50 but start the exe
      directly, and DES_FPS is read only by PLAY_DEMONS_SOULS.bat -- so they ran WITHOUT DES_60FPS
      (fixed 1/30 step, "game time 1.666 s per real s"): fix 47's world checks and fix 49's timings
      had the game logic at 1.67x. Renderer numbers stand; pacing results there are not the user's.
      scratchpad spot2.sh sets S60=1 (DES_60FPS=1) by default.
51. **Showcase capture (LD_VIDEO) + launcher features + the 2026-10-31 recording (2026-10-31):**
    - LD_VIDEO=<out.mkv> (rsx_live_draw.c ldv_frame, called after the LD_RECORD block in present): the
      presented surface is copied into a ring of 4 readback buffers (fence = fence_value + 1: both Signal
      sites submit g.list first), picked up at a later present once the fence passed, memcpy'd into a
      12-deep queue; a writer thread puts frames on an LD_VIDEO_FPS grid (default 60) by present time
      (frames that stayed up longer repeat) and pipes rawvideo rgba to ffmpeg (LD_VIDEO_FFMPEG, default
      "ffmpeg"; LD_VIDEO_ENC default h264_nvenc p6 cq 18). Matroska survives the sandbox's hard kill
      (remux with -c copy). Sandbox run: 19,815 presents, 0 dropped, 60.0 fps held while capturing.
      ffmpeg = imageio-ffmpeg wheel from PyPI in the session scratchpad (ffvenv), NVENC included.
    - DES_WARP_AT now takes a list "<s>:<a>,<b>,<p>;..." (up to 16, ppu_recomp_011.cpp);
      PAD_STICK_SEQ="<from>:<until>:lx,ly,rx,ry;..." (cellPad.c, up to 32 holds, stick re-centred when a
      hold ends -- the first version left it deflected and the camera kept turning).
    - Showcase (scratchpad showcase.sh): user's save copy (testenv/save_user_1031, loads in Stonefang),
      60 fps mode, DES_GOD=1, warps 160 s Boletaria (2,0,999) / 205 Shrine (3,1,999) / 250 Latria
      (4,0,999) / 295 Valley (5,0,999), 12 s pans at rx=200 (~45 deg/s) at 128/183/228/273/318 s
      (pad clock = video time). Pans: 60.0 fps everywhere except Boletaria 57.0, game time 1.002.
      Cut: DemonsSouls\showcase\demons_souls_recomp_showcase.mp4 (72 s, 720p60, x264 crf 17), full
      capture showcase_full_capture.mkv.
    - Launchers (user's + public repo): every run records (DES_PERF, perf\<ts>, newest 10 kept,
      DES_RECORD=0 = off; the RECORD bat keeps its own LD_PRESENT_LOG); DES_FPS=<31-240> custom rate:
      vblank 2N, clock N/30 (max 200), DES_MAX_FPS=N above 60, vsync with interval R/N when the
      refresh R (or R+1: Windows rounds 99.98 down) is a multiple of N, else vsync off;
      PLAY_DEMONS_SOULS_CHOOSE_FPS.bat menu; DemonsSouls\REPORT.bat + tools\make_report.py (zip for a
      GitHub issue: perf.txt, perf_report summary, system specs, log tail; user name scrubbed; trimmed
      to +-90 s around F8 marks over 24 MB). Custom 45: game time 1.000; 144: 1.000 at the cap, ~1.02
      when CPU-bound below it (Palace ~66 fps).
    - The user's 08:06 recording (14 min, 15 F8 marks): marks 4/5 and 8/11 line up with my own all-core
      jobs on the same PC (test lift 08:07-08:09, clean-room SETUP build 08:14-08:22) -- not the port.
      The last 2 min (717-839 s = 08:18:35-08:20:38: 9 fps, 1 draw per frame, game time 0.17) = a
      loading screen starved by that build: sandbox repro (save_user_1031, walk back into the Stonefang
      lava pit with DES_GOD=1): HP stays 552 at 50 fps, the pit has no way out; F9 off -> HP 0 -> death ->
      respawn, its 1-draw loading screen 1.6 s at full speed (122 s in the user's run, then quit).
      God mode needs no change; in the lava pit, F9 off is the way out.
52. **PLAY_DEMONS_SOULS_VIDEO.bat -- gameplay video with sound (2026-10-31):** sets LD_VIDEO
    (videos\<ts>ideo.mkv, fix 51), LD_VIDEO_FFMPEG = DemonsSouls	oolsfmpegfmpeg.exe (the
    imageio-ffmpeg build, NVENC) and AUDIO_WAV (raw f32 stereo 48 kHz final mix), then calls
    PLAY_DEMONS_SOULS.bat, which sets LD_VIDEO_FPS to the game's frame rate (unlimited -> 60).
    Both now log their first sample on the QPC us clock ([video] first frame qpc_us=,
    [audio-wav] first block qpc_us=); tools\make_video.py offsets the sound by the difference
    (-itsoffset / -ss), muxes AAC 192k + the H.264 copy into videos\<ts>.mp4 and deletes the
    intermediates. Sandbox: 150 s, sound 0.10 s after the first frame, mean -23.7 dB, 2:29.7 both.
53. **Guest vblank clock locked to the display (2026-10-31, user's 10:40 recording, 10 min, 3 F8 marks):**
    - Clean recording (no jobs of mine): 49.8 fps, 99.0% of frames up exactly 2 refreshes. The 3 marks
      have nothing in the 4-10 s before them (steps exactly 20.0 ms, every frame 2 refreshes, no
      catch-up frames) -- not explained by timing; next: record with PLAY_DEMONS_SOULS_VIDEO.bat + F8.
    - What the log does show: bursts of frames presented on time but up 3 / 1 refreshes ("no CPU-side
      delay", 180-182 s, 234-249 s, 418-424 s). Guest vblank ticker = QPC timer at exactly 100.000 Hz,
      display 99.99 Hz: the clocks drift past each other, and every time the hand-over lands on a
      refresh boundary the 2/2 cadence breaks for a second or two.
    - Fix: rsx_live_draw.c starts a thread after the swap chain (ldvb_thread): IDXGIOutput::WaitForVBlank
      on the window's output (re-queried every 5 s), least-squares fit of the last 256 vblank times
      (outliers > 1 ms dropped) -> rsx_live_draw_display_vblank(vb_us, period_us). boot_main's ticker,
      after each tick, snaps next_tick to the nearest grid point when its rate is a whole multiple
      (1..8, within 1.5%) of the display's -- 50 fps on 100 Hz, 60 on 120 / 60 Hz, custom N on 2N Hz.
      Not locked (logged once): 60 fps mode on 100 Hz, uncapped. LD_VBLANK_LOCK=0 = free-running,
      LD_VBLANK_LOCK_PHASE=<0..1> = tick offset after the vblank (default 0).
    - Sandbox A/B, user's save in Stonefang, 50 fps / 100 Hz, 120-480 s: free-running 26 frames not up
      2 refreshes incl. a burst 213-220 s (17), display-locked 16, only isolated 3+1 pairs (single late
      game steps), 2-refresh frames 99.74% -> 99.91%, "no CPU-side" hitches 11 -> 2; ticks 99.9717 Hz.
54. **Fire-breath slowdown: VMX float ops through fmaf() -> SSE4.1 + FMA fast path (2026-10-31):**
    - User's 18:40 recording, F8 at the Dragon God's breath hitting the player: 264-268 s and 274-276 s at
      36-40 fps; render CPU fell (fewer draws), main-thread step CPU 4.4 -> 21-23 ms. Same with and
      without god mode (not the death loop of fix 51).
    - Sandbox repro (below): every breath = ~2.5 s of 21-27 ms steps. DES_PERF_STACKS=1
      DES_PERF_STACK_MS=3 DES_PERF_STACK_THREADS=HighGraphics + scratchpad hotcmp.py (heavy vs normal
      steps): main thread in func_0032FB08 -> 011B84D0 -> 01271520 (recursive tree walk) -> 0107E040 ->
      010630E8 -> 0128AB90 / 0128D280 / 0128CF68 (the breath's collision queries, presumably): 177
      vmaddfp, 73 vaddfp, 48 vsubfp, 21 vnmsubfp in those functions. ppu_vmx.h did each lane in scalar
      with vmx_flush / vmx_fix and fmaf() -- a library call (the lifted PPU code has no -mfma).
    - Fix (ppu_vmx.h): vmx_vmaddfp / vnmsubfp / vaddfp / vsubfp take an SSE4.1 + FMA path (big-endian
      load via pshufb, NJ flush as a blend, NaN -> 0x7FC00000, vadd/vsub keep the A-then-B quieted-NaN
      rule, vnmsubfp = -(fmsub) so an exact zero is -0 like -fmaf(x,z,-y)). Functions carry
      __attribute__((target("ssse3,sse4.1,fma"))), so the PPU units need no new flags; ppu_vmx_fma
      (ppu_hle.cpp, set at static init: CPUID SSSE3 + SSE4.1 + FMA and PF_AVX2 for the OS AVX state) picks
      it per call, PPU_VMX_FAST=0 = scalar. Scratchpad vmxtest/vmxtest.cpp: 16 M random + special-value
      ops (denormals, NaN payloads, inf, +-0, x-x, a*c==b) fast vs scalar, NJ on/off, -O1 and -O2:
      0 mismatches. Full build_opt rebuild 3.5 min.
    - Result (same sandbox breath, 50 fps): breath steps median 23.0 -> 14.1 ms (max 28.7 -> 18.0),
      frames over 25 ms 325 -> 0; ordinary steps 4.2 -> 3.7 ms.
    - The Dragon God report that led here was not a bug (the rubble on the lower walkway is broken by
      the player's own hits: OnSimpleDamage(.., obj, 10000 = attacker)). Tools made for it:
      - DES_LUA_PRINT=1 (ppu_recomp_070.cpp func_00C02C78 = the game's print(), a no-op in retail): the
        event scripts' print() -> stderr "[lua] ...". Lua API: 0xC9E170 lua_gettop, 0xCA0570 lua_tostring.
      - Scripts are read from script/mXX.luabnd.dcx.sdat (BND3 of Lua *source*), not the loose .lua.
        Scratchpad luabnd.py (BND3 repack + DCX EDGE writer) and mk_game_dbg.py build
        DemonsSouls\game_dbg (cp -al game + a debug m06 luabnd: timer fires ballista 1, change-only trace
        prints of the requests the fight script sends; MSB copy with point 2889 moved onto the floor of
        breath region 2430 -- region boxes sit below the floor, a Warp() into one falls through).
        Run with DES_GAME=game_dbg SAVE=save_user_1031c (loads at the fog gate).
      - m06_02 layout (MSB): punch regions 2420-2429 on the upper path, breath regions 2430-2436 on the
        lower walkway (y -98), ballistas 2410 (x 95.8) / 2411 (x 193.6), wall 1445 beside ballista 1 is
        removed by OnEvent_6413 at the end of cutscene 60200.
55. **Renderer thread CPU -21% (2026-10-31, user's 19:27 Boletaria recording, 31 min, 11 F8 marks):**
    - Marks 6-11: catch-up frames / 3-1 refresh pairs where render CPU reached 16-20 ms (median 13.4 at
      mark 9, ~900 draws). Marks 1-4: nothing in any timing data (presents, cadence, steps, catch-ups)
      even 90 s back -- not frame pacing (asked the user; video bat suggested). Overall 99.81% of frames
      at 2 refreshes.
    - Sandbox: testenv/save_user_1031e (user's save after that session, loads in the Palace, 815 draws at
      the start). Measuring: scratchpad incl.py (inclusive/self profile, idle dropped), rcmp.py; A/Bs must
      be pinned (AFF=FFFF) and back to back -- unpinned runs drifted 8.2 -> 10.4 ms in an hour (CCD
      placement on the 7950X3D, background Vortex / cam_helper).
    - Exact memos (LD_MEMO_CHECK=1 computes both ways: 13.6 M checks, 0 mismatches):
      - Fragment program (get_pso): rsx_fp_program_size + rsx_fp_structural_hash (byte-wise FNV-1a) ran
        per draw. Memo per program address = copy of the program + its inline-constant block mask
        (rsx_fp_program_layout, new in rsx_fp_decompiler.c); when every instruction block matches, size
        and structural hash (4 seeds) are reused. LD_FP_MEMO=0 = off.
      - texture_srv_slot: linear 8-field scan of ~280 cache entries per bound texture -> 1024-slot memo of
        the last index per key (keys are unique, so starting there finds what the scan would).
        LD_TEX_MEMO=0 = off.
    - Ticker spin (boot_main + cellGcmSys.c cellGcm_fifo_kick_wait_us): the wait was whole ms, so the
      last <1 ms before each tick spun ~50,000 passes/s through PeekMessage + FIFO poll (LD_PUMP_STATS=1
      shows calls/s). Now a high-resolution waitable timer + the kick event; 1,100 passes/s, cadence
      still 100% 2-refresh at 50 fps. LD_TICK_TIMER=0 = old.
    - LD_KICK_DRAWS default 64 -> 128: render CPU -0.4 ms, uncapped fps unchanged (76.0 / 75.2 / 74.9 at
      64 / 128 / 192; 0 = 62 fps, the overlap matters).
    - Tried and dropped: vertex-constant block reuse (constants change per draw: no hits, 0 gain);
      sparse index-range hashing (ranges are mostly <= 4 KB: 0 gain).
    - Result (pinned A/B, same build, old = the env switches above): Palace start 10.92 -> 8.64 ms render
      CPU (p90 12.12 -> 9.60); walk + pan route median 4.5 -> 3.1, p99 8.6 -> 6.9 ms.
    - Left (profile after): FIFO parse/dispatch ~19% of the busy thread, draw recording (sink_end_impl
      self) 12%, D3D12 submit + Present 16% (driver), vertex/texture hashing ~12%, vertex convert 6%.
56. **Garbled music: cellAtrac streaming implemented (2026-10-31):**
    - Without dev_flash (the launchers use no_flash) MagicOrchestra plays music through libatrac3plus
      in streaming mode: SetDataAndGetMemSize with the first 100 KB of a 1.9 MB .at3, then
      GetStreamDataInfo / AddStreamData. Those 5 imports were unnamed (NIDs = SHA-1 of the name:
      0x2BFFF084 GetStreamDataInfo, 0x46CFC013 AddStreamData, 0x99EFE171 IsSecondBufferNeeded,
      0xBE07F05E GetSecondBufferInfo, 0x06DDB53E SetSecondBuffer) and Decode reported
      ALLDATA_IS_ON_MEMORY, so the game never streamed and the decoder read past the first 100 KB into
      unrelated guest memory: thousands of "Atrac3/3+: Frame data doesn't match channel configuration"
      / Invalid / Missing lines in bursts (the user's 19:27 log) = audible garbage.
    - libs/codec/cellAtrac.c: a streamed track keeps a host copy of the whole file; GetStreamDataInfo
      hands out the title's whole buffer each time (write = buffer, writable = min(buffer, rest of the
      file), read position = bytes received), AddStreamData copies the piece out at once. Decode returns
      NODATA_IN_BUFFER for a frame not received yet; remaining frames = whole frames received ahead of
      the play position, then NONLOOP / LOOP_STREAM_DATA_IS_ON_MEMORY once complete (loops read the host
      copy, so IsSecondBufferNeeded = 0). Also GetVacantSize, GetBufferInfoForResetting (+ the write
      byte of ResetPlayPosition), GetInternalErrorInfo. New handlers register by name (gen_hle_nids.py).
      ATRAC_STREAM_LOG=1 logs the stream calls.
    - Sandbox (testenv/save_user_1031e): the 1.9 MB track (loop 637552..end) arrives in 19 x 100 KB
      reads, 0 decoder errors, 0 frames requested before they arrived; the AUDIO_WAV mix is tonal music
      (spectral flatness 0.001-0.05). Sample: DemonsSouls\showcase\atrac_stream_fix_sample.mp3.
      The mono tracks with a 20 KB head (user's log) take the same path; not hit in the sandbox.
57. **Player location in the stutter recording + test teleport (2026-11-01, user's 23:48 Latria recording):**
    - The recording (26 min, 12 F8 marks, Tower of Latria after a 5.9 s load at 103 s): mark 3 = 2.5 s of
      ~45-55 ms steps with the game thread waiting (CPU 4 ms) after a 102 ms first-time shader compile;
      marks 6 / 9 / 11 / 12 = short catch-up pairs (fix 50's alternation, longest 12 frames: full frame
      30-40 ms apart at ~1100 draws / 11 ms render CPU, then a scene-less one) -- the guest's frame chain
      (HighGraphics -> SpursTaskCommandDispatcher) running past 20 ms; marks 1 / 4 / 5 / 7 / 8 / 10 = nothing
      in the timing data (sound? -- video bat suggested).
    - Not reproduced: the user's save (testenv/save_user_1101, loads on the Prison of Hope walkway at
      -6.5, 9.3, -14.6, ~1100 draws) standing, panning and walking (PAD_STICK_SEQ) stays at 2 refreshes.
      The heavy moments need the user's exact spot (enemies), which the log did not have.
    - Ruled out: the 670 MB stderr log (5,000 lines/s through one FILE lock; ps3_log.h warns about it).
      Pinned uncapped A/B with PS3_VERBOSE=0: no fps gain (uncapped runs vary 94-117 fps run to run), and
      the log only shrinks a third -- most lines (spu_workload dispatch / RETURNED / taskset, with an
      fflush each) print regardless of PS3_VERBOSE.
    - New: "# <us> pos <AA,BB> <x> <y> <z> <block id>" in the perf log once a second and with every F8
      (port patch in ppu_recomp_011.cpp func_0001B8D0, des_player_where): the character from
      func_004142A8(obj, 10000) as god mode; the position from lua_SaveChrPos's virtual call
      chr->vtable[+0x70](out, chr) (x, y, z BE floats); block id = lua_GetBlockId's func_00419610(obj);
      "AA,BB" = the last map/mAA_BB_*.mcp cellFsOpen saw (ppu_fs.cpp ps3_fs_last_map) -- the area:
      Boletaria's blocks share m02_00 (Palace = 02,00 block 3), Latria = 04,00 block 0. The stage
      manager's +0x8 is only the warp request (-1 once done; no current map id in its first 0x100 bytes).
    - perf_report.py prints per mark "player: area 4 (Tower of Latria) block 0 at x,y,z" (+ 5 s before).
    - Test helpers: DES_TELEPORT_AT=<s>:x,y,z[;...] (seconds from the first step) puts the player there via
      lua_LoadChrPos's func_00273BE0(chr, v2 = (x, y, z, 0)); DES_WHERE=<s> prints the position. Recipe:
      DES_WARP_AT=<s>:<area>,<block>,999 once in game (a warp requested during the save's load never
      settles), then DES_TELEPORT_AT after the load. Checked: user's Palace save -> warp 4,0,999 at 125 s
      -> teleport at 170 s -> standing on the Latria walkway at the logged x,y,z.
    - Follow-up (2026-11-01 01:40): the area came from the last map .mcp opened, which went stale --
      revisiting a world does not reopen it (Nexus -> Latria kept saying "Nexus"). Now both area and
      block come from the game: lua_GetBlockId's func_00419610 does X = *(TOC[-0x788C] - 0x7E70),
      func_0033BBB8(out, X[+4], X[+0x30]) -> map id bytes (area, block, ..) at out; the port makes that
      call itself. "pos <area>,<block> x y z" (Palace 2,3; Latria 4,0). The ppu_fs.cpp .mcp tracker is gone.
58. **Sound behind the picture, thread CPU in the recording, renderer -10% (2026-11-01, user's 01:14 recording):**
    - User: "a little stuttery again" + sound "out of sync" (sounds land late). Recording (12 min): judder =
      the first ~20 s on the Latria walkway by the save point (-6.5, 9.3, -14.6; ~1050 draws vs 500-650
      elsewhere) both after the save loaded and after returning from the Nexus (~135 catch-up frames
      per 20 s), and a drop at y = -77. The sandbox at the same spot: ~10 catch-ups in the first 5 s,
      then none -- not reproduced; pinned to CCD0 (AFF=FFFF) also smooth.
    - A/V measured (scratchpad avsync.sh / avpress.py): 8 scripted R1 swings, LD_VIDEO + AUDIO_WAV on
      the QPC clock, press times now logged by cellPad ("PAD_SCRIPT ... qpc_us="). Press -> swing sound
      989 ms at 50 fps vs 1007 ms at 30 fps (same), press -> picture 404 vs 498 ms: at 50 fps the
      picture answers ~95 ms sooner while the sound does not, so sound lags the picture more than in
      the original. Code audit (workflow, 20 agents): PS3_CLOCK_SCALE is not involved (the audio path
      is real time); the host queue is: a 60 ms WASAPI buffer prefilled half full and corrected only
      outside 1/4..3/4, so it drifted from 27 to the 45 ms edge (the device clock runs slow vs QPC
      here: 29 -> 31 ms in 70 s).
    - Fix (cellAudio.c): the queue is held at 15 ms +/- 1 block (PS3_AUDIO_TARGET_MS, 0 = old band);
      each underrun raises the target a block (to half the buffer). AUDIO_RATE=1 now prints queue mean
      / min. Sandbox Latria walking + pans: default 29-31 ms (min 24), target 20: 18-20 (13), 12: 13-15
      (7), 15: 15.3 (min 10) -- 0 underruns in all. ~15-30 ms less audio delay.
    - Thread CPU in the perf log (rsx_live_draw.c perf_thread_cpu, DES_PERF_THREADS=0 = off): once a
      second "# <us> thr <process %> <name>=<%> ..." (QueryThreadCycleTime per host thread, by
      ps3_thread_name), perf_report prints the whole-log means and per F8 mark the threads that rose.
      Latria standing (thread_cpu.py, per thread): one "spu job" thread 102% (spins), HighGraphics 58%
      (much of it sub-ms usleep spins at 0x00ACB0A0 waiting for the dispatcher: 17k calls / 10 s,
      PS3_POLLTOP=10), MOStreamingThread 53% (usleep polls of ~1 us at 0x010D000C / 0x010D0F8C, 25k /
      10 s: sys_timer_usleep busy-waits under 1 ms), render thread ~40%, synth2 34% (real synthesis;
      its receive wait does block). Process ~380-490% of a core.
    - Renderer survey (workflow, 21 agents, read-only, adversarially checked): ranked plan in the
      session; done here: (a) 3 swap-chain buffers (LD_SWAP_COUNT=2 = old) so the next frame's
      submits do not queue behind a swap copy that waits for the display after a catch-up pair;
      (b) cellGcmSys.c stops feeding the legacy rsx_state once live draw is up (rsx_live_draw_ready();
      GCM_LEGACY_STATE=1 = old) -- the null backend registered under live draw did nothing with the
      per-method callbacks but print viewport / RT changes (most of the 160 MB stdout log).
      Pinned A/B (abhitch.sh: Latria, pan, 45 ms forced late steps every 4 s, A B A B): render CPU per
      heavy frame median 4.44 / 4.63 -> 4.02 / 4.06 ms, p90 9.05 / 9.06 -> 8.19 / 8.11; catch-up
      frames 14 / 40 -> 13 / 27, hitches 10 / 53 -> 9 / 13. Frame dump at the same frame: 0.7% of
      pixels differ (idle animation phase), image identical otherwise.
    - Not done yet from the plan: ring reset at present (needs an upload-capacity preflight), 4-way
      vertex cache, partial vertex-constant upload, reservation cache-line padding (full rebuild),
      SIMD vertex conversion, one-CCD CPU set.
59. **Sound thread (synth2) saturated -> sound work dropped; SPU float zeros in the vector path (2026-11-01, user's 10:36 recording):**
    - The recording (42 min, Latria through the Fool's Idol, 4 marks): marks 2 / 3 have no frame hitch
      at all; the new thread lines show "spu  synth2 Group:0" (libsynth2, image 11, lv2 SPU thread that
      renders the voices for libmixer, one receive per 5.33 ms block) at 90-100% of a core for most of
      the session -- no headroom, pinned at 99-100 for minutes. Mark 4: a 1.32 s freeze (no game step
      at all, HighGraphics 91%, synth2 8%) at 4,0 46.9 9.4 -40.4 -- not reproduced by teleporting there;
      no save / file activity in the run log at that point. The launcher now records late-step stack
      samples (DES_PERF_STACKS=1, DES_PERF_STACK_THREADS=HighGraphics) so the next one says where.
    - Sandbox: synth2 has two modes, ~30% (standing) and ~90% (after the player moves: walking, a
      teleport) -- the voices the moves start. Its receive is a real blocking wait (SPU_RECV_LOG=1:
      ~187 "wait" receives a second, no polling). Stack samples in the high mode (scratchpad synhi.sh:
      retries runs until thread_cpu.py sees >= 70%, then old session's stack_sample.py): func_00000AC4
      30%, func_00001090 23% (a one-sample-per-pass 4-tap fm/fma filter), 2C20 9%, 63C8 7%, the float
      fix-up paths _x8_fa_fix / _x8_fm_fix / _sf_sum ~8%, waiting ~7-10%.
    - func_00000AC4 (entered from 0AA0 with r4 = r80 + 16, r5 = r7 = 0): clears 112 bytes of a voice
      block one byte per pass -- read the quadword, cbx + shufb r7's preferred byte in, write it back,
      r5 += 1 in all four slots until r5 == 112. Port patch at its top (port/spu/spu_0010_at_01818080/
      spu_recomp.c): all passes but the last as plain byte stores, r5 advanced to match, then the
      original loop runs the last pass -- LS and r5 / r13-r16 end exactly as before. Skipped while
      g_spu_ls_wdiag != 0 (LS write diagnostics) or r5 >= 111.
    - spu_helpers.h AVX2 fa / fs / fm / fma / fms / fnms (runtime): SPU zeros (biased exponent 0, any
      fraction) become +0 before the op and results below 2^-126 flush to +0 inside the vector path,
      as the NEON path already did (spu__x8_z0 / spu__x8_fin / spu__x8_trunc1); only extended-range
      operands and results >= 2^128 still go per lane. SPU_X8_ZERO_SLOW = old rule. Checked against the
      exact per-lane reference (spu__*_any) on 20 M random vectors x 6 ops (weighted to zeros,
      denormal patterns, tiny / huge / extended exponents, cancellation): 0 mismatches, old and new.
      Bench: ordinary values same speed, operands in the SPU-zero range 5.3x faster. No measurable
      synth2 change by itself (its remaining fix-up lanes are not zeros).
    - Result (scratchpad synab.sh: old exe copy port/build_nozero vs new, walk + pan, A B A B, in-game
      thr lines 140-178 s): synth2 90.5 / 92.0% -> 61.1 / 62.0% (max 96-97 -> 64-65), process ~496 ->
      ~465%. Standing (cheap mode): 36 -> 28%.
    - Audio (scratchpad audchk.sh, AUDIO_WAV of the mix 140-175 s): standing, old and new are
      IDENTICAL (rms 0.0144, peak 0.065, band levels equal to every digit -- the patches are exact).
      Walking, the new build is consistently louder (rms 0.0195 / 0.0220 -> 0.0254 / 0.0290, 50-2000 Hz
      bands ~2x, no silent blocks either way): with synth2 saturated, voices / effects were being
      dropped -- likely the user's "audio a bit off" and marks with smooth frames.
60. **Texture packs: dump and replace textures (2026-11-01, asked for on Reddit):**
    - Model / texture FILE mods already work (the port reads the unpacked disc files; PC Remaster =
      fix 45). New: Dolphin-style packs that need no unpacking. Runtime: libs/video/rsx_tex_pack.c / .h
      (D3D-free: folder scan, key table, 2 background threads, PNG via the stb_image already built
      in libs/codec, DDS parser, BC1-3 decoder for dumps) + the GPU half in rsx_live_draw.c ("texture
      packs, GPU half": tp_upload / tp_resident / tp_trim / tp_sweep / tp_lookup / tp_poll,
      sampler_slot_tp) hooked into texture_srv_slot's new-entry, refresh and hit paths.
    - Key = splitmix(content hash the cache already computes, mixed with base format, w, h, remap):
      content-addressed, same every run / PC. LD_TEX_DUMP=1 writes level 0 AS SAMPLED (remap applied;
      BC decoded on the CPU, remap via the same s[]={A,R,G,B} rule as write_texture_srv's BC mapping)
      to textures\dump\<KEY>_<w>x<h>_<fmt>.png + index.csv, once per key (and never over an
      existing file), in the worker; 256 MB queue cap holds the renderer. Changing textures: first 3
      contents per cache entry, re-armed (max 8x) after ~15 s unchanged.
    - textures\replace\**\<KEY>*.png|.dds: scanned once at start; loaded in the background on first
      use, uploaded by the render thread with its own upload buffer (64 MB / frame budget), drawn with
      the default SRV mapping (the dump had the remap). PNG -> RGBA8 + box mips; DDS DXT1/3/5, BC7,
      BC4 (R to RGB, alpha 1), RGBA/BGRA 32-bit, *_SRGB read as UNORM; BC5 / cubemaps / arrays refused.
      .dds beats .png on a duplicate key. A replacement 2^n larger gets sampler_slot_tp (LOD range
      reaches its extra mips; guest no-mip textures filter between levels -- else a 4x UI texture
      shimmers). A loaded replacement skips the guest decode entirely. LD_TEX_REPLACE_MB (4096) caps
      replacements nothing draws (tp_trim drops only unreferenced ones; AddRef probe); finished loads
      nobody asked for in 2 s are uploaded by tp_sweep so no RAM copy lingers; failed upload retries
      after 600 frames. LD_TEX_REPLACE=0 off, LD_TEX_DIR, LD_TEX_THREADS. Off (no files, no dump):
      one InitOnce check per new / changed texture, nothing else.
    - Reviewed by two agent passes (findings verified by skeptics): fixed sampler LOD clamp, lingering
      READY images, trimming held textures, BC4 drawn red, dump counter, sampler-cache-full fallback,
      sweep timing, re-arm limit.
    - Sandbox (Palace save): dump run 281 textures / 154 MB in 50 s, all decode
      right (normal maps, alpha particles, button atlas, loading art); identity pack (the dumps as
      replacements) looks the same as no pack, 49.6 vs 49.7 fps; 2x inverted+grid pack (219 PNG,
      57 DDS RGBA8 / BC1 with mips, nested folders) fully replaced, 49.3 fps, worst present 219 ms
      (as without, 194-226).
    - PLAY_DUMP_TEXTURES.bat (sets LD_TEX_DUMP=1); textures\README.txt.
61. **Model export / import: tools/flver_tool.py + tools/souls_formats.py (2026-11-01, asked for on Reddit):**
    - Standard library only. souls_formats.py: DCX (EDGE / DFLT / bare DCP-DFLT) read + write, BND3, FLVER0,
      PS3 TPF + BC1-3 / ARGB8 decode, PNG writer. Every reader keeps what it does not interpret, and all
      5454 FLVERs and 1781 BND3 archives in the game read and write back byte for byte (selftest).
    - FLVER0 facts (checked on the game's data): big-endian v0x15; mesh header 0x64; materials own their
      texture tables + buffer layouts; meshes with vertex-buffer offset 0 (some characters) have one
      implicit buffer; triangle strips with 0xFFFF restart; game winding = cross(b-a, c-a) opposite the
      normal (1535 of 1537 meshes) -> mirroring X for glTF lands on glTF's CCW rule; skinned (dynamic=1)
      vertices are in model space, rigid (dynamic=0) ones in their OWN bone's space (table[bone byte]);
      the mesh "default bone" is a GLOBAL bone (the model's own node bone on skinned parts, e.g.
      bd_f_5010 -> 91 'BD_F_5010'; 0 = root on map pieces) -- import keeps it; bone local = T*Ry*Rz*Rx*S; UVs
      short/1024; normals byte (b-127)/127 with W byte 127; tangent = dP/dv with w = -UV handedness
      (21908 of 21934 vertices); vertex colour RGBA bytes; header 0x40 = non-degenerate triangles.
    - export: glTF + .bin + textures\*.png (diffuse / normal from the model's own TPF, a .tpf beside it,
      or the area's MAP\mXX\*.tpf), skeleton as joint nodes WITHOUT bone scale (Blender's rest pose
      cannot hold it; vertices still placed with the real scaled matrices), IBM = inverse joint world,
      every vertex skinned (rigid ones weight 1 to their bone), meshes named m00_<material>, unique
      material names (#index) + extras.flver_material.
    - import: model-space positions = sum w * (joint world * IBM) * p from the glTF itself (so Blender's
      bone re-orientation does not matter), mirrored back; rigid meshes back into their bone's space;
      per-mesh bone tables rebuilt, >28 bones or >65535 vertices split; strips rebuilt greedily
      (triangles_to_strip, fewer indices and restarts than the game's own); tangents rebuilt in game
      convention; colour alpha (Blender drops it) / missing colours from the nearest original vertex
      (then normal, then UV); inside-out primitives (mirrored objects, skinned or not) flipped by a
      face-normal vote; unskinned objects rigid to their nearest bone ancestor; faces with another of
      the model's materials go to a mesh in the file using it (never one left out); bounds grow only. Writes into game_mod\ (hard links to game\, .links_complete marker; files are unlinked
      before writing, and a realpath guard refuses anything in game\); an already-modded copy is the base
      (other FLVERs in the archive / PC Remaster files kept); the loose and .dcx twins both written; a
      note for the _l / l1 low-detail twin. PLAY_MODDED.bat runs game_mod;
      models\README.txt for modders.
    - THE LOAD HANG: the game's DCX reader skips h[0x14] - (h[0x10] + DCA size) bytes before the block
      data (unit_00AFF944). The first writer left 0x14 stale, so any import whose payload crossed a 64 KB
      block boundary hung the map loader on the loading screen (bisected in game: same-size variant loads
      112 map files, resized variant stops after 7). dcx_compress now writes 0x14 = 0x10 + DCA size and
      DCS csize = block data only, as every game file; selftest checks a grown and a shrunk rewrite.
    - Tests: Blender 4.5 headless (scripted import, render, edit, default GLB export): o2455, c1040, m2501b0, wp_a_0256, bd_m_0000, m4000b0, bd_f_5010 back with 0.0000 position
      error (scaled-bone models were off by up to 1.26 before the skeleton fix). In game (a test copy
      via DES_GAME): all 140 Palace map pieces re-imported + Blender-inflated body
      armour (skins and animates) + 1.8x shield + a new cube in a map piece: loads, 49.7 fps.
    - Three agent review rounds (findings checked by skeptics, real Blender round trips) found the DCX
      field, bone scale, tangent convention, guard, multi-FLVER overwrite, alpha (exact through Blender
      now: 0 of 36k map vertices wrong), duplicate materials, mirrored objects, Draco, default bone,
      material routing, quadratic splits -- all fixed. Full selftest: 6485 files byte for byte, DCX
      resize OK, 40 models export -> import with 0.00000 position error.
62. **New-area stutters: shaders built off the drain thread, a flip wakes the ticker (2026-11-01, a
    9-min Latria 4-2 recording + "loading into 1-1 and running forward at once is stuttery"):**
    - Recording: worst frame 828 ms = two skinned-character vertex shaders, D3DCompile ~300 ms each
      (cache files V_1F5A80C6132AF6C2 / V_5E922260BCA37EA9). fxc takes as long at every optimisation
      level; SKIP_OPTIMIZATION still 120 ms with 4x the bytecode. The bone reads
      `vp_c[(K + a0.w) & 511u]` cost about half (unmasked 278 -> 159 ms) but an unmasked index can read
      outside the constant ring (root CBV: no bounds check) -- not done; vp_mul (0*x = 0) ~40% more.
    - Most "game step late (thread waiting)" steps are the drain thread being stuck: boot_main's
      vblank_ticker drains the FIFO, presents AND runs the guest vblank clock, so vbh notes arrive in
      bursts with jumped counts; main waits for HighGraphics, which waits for the vblank handler's
      DLSingleSignal. Sandbox late-step stacks: main sys_cond_wait, HighGraphics sys_semaphore_wait,
      rsx in build_pso (D3DCompile), shader_disk_cache_load (fopen) and CreateCommittedResource.
    - Fix (rsx_live_draw.c): a pipeline whose shaders are already compiled (memory or disk cache) is
      still built on the drain thread -- identical frames. One that needs fxc goes to LD_PSO_THREADS
      (2) workers and its draws are skipped until it is ready (the object appears a few frames late),
      except "critical" draws -- display-buffer target, or a full-screen pass (no depth test, <= 6
      vertices) -- which build it here (taking the queued job) or wait, as before. Also: blob caches
      under an SRW lock with a duplicate-insert check, ld_compile_claim (two pipelines needing the same
      new shader share one compile), thread-local compile timers, interlocked disk-cache counters,
      thread id in the temp name, stale *.tmp.* swept at start, no DRED dump from a worker.
      LD_PSO_ASYNC=0 = the old path everywhere.
    - A design-review agent found a use-after-free in the first version (worker published state 2,
      then SetEvent on a job the renderer could already have freed) and that a per-frame wait budget
      made warm-cache output timing-dependent and wasted the budget on compiles that cannot finish;
      both fixed by the narrowed design above.
    - cellGcmSys.c gcm_flip_request: a direct flip now signals the kick event; Present came ~3.9 ms
      after every flip (the ticker's idle wait). LD_FLIP_KICK=0 = old.
    - Perf log: "psof <n> <ms> <disk ms>" (all pipeline builds on the drain thread in a frame, also
      those under 1 ms), "psow" (a critical draw waited), "psoa" (worker-built, no stall), "texc <n>
      <ms>" (texture creation in a frame); perf_report counts psof/psow as shader compile and texc as
      "texture creation".
    - Results, pinned A/B (AFF=FFFF), both runs from the same pre-test shader-cache snapshot, a
      Latria 4-2 save, walk from the archstone + teleport to marks 3/4: worst frame
      1571 / 808 ms -> 139 ms, big hitches 15 -> 5, frames up exactly 2 refreshes 99.52 -> 99.81%.
      Cold-cache frame dumps at the compiles: while the
      player's armour shaders compiled (~0.36 s, up to 156 draws skipped) the body armour showed as a
      black shape -- its depth pass was drawn, its colour pass skipped (the reviewer predicted these
      holes); normal a few frames later. Only the first time a shader is ever seen; accepted over a
      0.3-1.3 s freeze (LD_PSO_ASYNC=0 for the old behaviour).
    - Boletaria 1-1 arrival + immediate run (warm cache): unchanged, other causes. ~126 s: two game
      steps of ~180 ms with the game thread busy (game script code right after arrival). ~130 s: a 95 ms
      render frame, ~70 ms of it CreateCommittedResource for ~200 new textures (0.37 ms each; tried
      D3D12_HEAP_FLAG_CREATE_NOT_ZEROED: no change, removed) + 15 ms pipeline builds. Next: create
      textures as placed resources in large heaps (needs an allocator: textures are LRU-evicted at
      1024 and refreshed) or keep pre-created spares of common sizes.
    - Also from the analysis, not acted on: marks 3/4 are a ~1000-draw view where the frame chain runs
      21-22 ms (flip period tracks render CPU); an agent claims 0-draw catch-up flips show the buffer
      from two flips back -- unverified (fix 50 saw ~150-draw HUD catch-up frames).
63. **Textures in big heaps + shader cache read at start (2026-11-01, Boletaria 1-1 arrival + run):**
    - Fix 62 left the arrival frame (~130 s in the b11 test: running into the first soldiers) at 95-138
      ms: ~200-250 new textures that frame, each its own CreateCommittedResource (~0.37 ms; driver
      allocation -- D3D12_HEAP_FLAG_CREATE_NOT_ZEROED made no difference).
    - Textures from create_texture_mipped are now placed resources in LD_TEX_HEAP_MB (64) MB heaps
      (ALLOW_ONLY_NON_RT_DS_TEXTURES, 4 KB small-resource alignment when allowed, else 64 KB; first-fit
      free list per heap, coalescing). Freeing needs no release-site change: each placed texture
      carries a private-data IUnknown (SetPrivateDataInterface) whose last Release -- when D3D12
      destroys the texture, which retire_texture already delays past the GPU fence -- returns the
      block. Reused memory gets an aliasing barrier and is fully overwritten by the copies; textures
      whose mips would not all fit in the upload ring, or whose mip copies would not cover the whole
      subresource (DXT with a base not a multiple of 4), stay committed. LD_TEX_PLACED=0 = old.
      Arrival texture creation 126 ms -> 11 ms (worst frame 51 -> 6 ms); Latria needed one 64 MB heap.
    - Review (2 lenses + a skeptic per finding): unchecked SetPrivateDataInterface (would free a live
      texture's block) and new-heap malloc -- fixed; the partial-mip-copy case above -- fixed; extent
      math, locking, fence discipline confirmed. Heaps are not torn down at shutdown (nothing calls
      rsx_live_draw_shutdown).
    - Disk shader cache read whole at start (shader_disk_preload, background thread from
      rsx_live_draw_init; RSX_SHADER_PRELOAD=0 = off): when the cache files were not in the OS file
      cache, each first-use read cost ~6 ms and the first gameplay frame after loading the save built
      87 pipelines in 584 ms, 542 of it disk reads (a 670 ms freeze). Now 602 shaders (8.6 MB) load in
      ~2 s during the logos; load-in frame disk time 0, worst frame there 104 ms.
    - Boletaria arrival, pinned, all of fixes 62/63 off (LD_PSO_ASYNC=0 LD_FLIP_KICK=0 LD_TEX_PLACED=0
      RSX_SHADER_PRELOAD=0) vs on: worst frame at the soldiers 169 -> 88 ms (texture creation 23 -> 4 ms
      in it), catch-up frames 51 -> 22; the ~180 ms game-script steps at ~126 s unchanged.
    - Remaining at the arrival: ~180 ms of game script code on the main thread (~126 s); at ~130 s
      ~45 ms where main/HighGraphics wait with the drain idle (likely SPU work), then the drain's
      ~50 ms of texture decode (decode_texel) and draw submission for ~1100 draws, plus ~14 ms
      creating ~40 pipelines from cached shaders (driver). Ideas: pipeline pre-creation from a saved
      list at start; texture decode off the drain thread.
64. **Storm King arena missing geometry: a draw's packet list held 256 entries (2026-11-02, user report):**
    - The live renderer queued a draw's DRAW_ARRAYS / DRAW_INDEX_ARRAY packets in dc.arr / dc.idx[256].
      An RSX packet covers at most 256 vertices/indices, so any draw over 65,536 indices silently lost
      the rest: the stats line's packets[... qfull=N] counted them. The Shrine 3-3 beach (Storm King)
      has such meshes: the user's 4-min session there dropped 416,836 packets, their 2-hour session
      16M; Latria / Boletaria runs 0. Old limit, not from fixes 62/63.
    - Fix: DC_MAX_BATCHES 16384 (4M vertices per draw); everything downstream already loops over the
      counts and grows its vertex buffers.
    - Repro: a save in the Nexus, DES_GOD=1, DES_WARP_AT=125:3,3,995 (Storm King archstone; the
      Nexus script m01_00_00_00.lua lists every archstone's warp). Before: qfull 724,905, rock spires
      behind the archstone missing; after: qfull 0, 49.8 fps, 99.3% of frames up 2 refreshes. Lesson: grep "qfull=" when geometry is missing.
65. **Valley of Defilement judder in the 100 fps mode: pin the game to the biggest L3 (2026-11-02, a
    25-min recording, 9 F8 marks, DES_FPS=100 on a 100 Hz monitor):**
    - Not freezes: in the busy swamp parts (5-1 area, map 5,1) the game could not hold 100 fps, so frames
      mixed 1 and 2 refreshes (and fix 50's catch-up pairs). Sandbox at mark 4/5 (117.6,-25.7,-350.1):
      100 fps mode 77 fps (68% one refresh, 31% two); the 50 fps mode at the same spot (and marks 1, 2)
      99.9-100% exactly 2 refreshes -- 50 is smooth there.
    - PS3_FTRACE at the spot (100 fps): one serial chain per frame -- main ~2 ms, HighGraphics ~7 ms
      running (draw-list build, SPU jobs alongside), ~3 ms of hand-off waits; renderer drain 3.3 ms, not
      the limit. Late-step stacks (the recorder has them now): main in sys_cond_wait under
      func_001D1A80, HighGraphics in sys_cond_wait (60/68), renderer idle.
    - Fix (boot_main.cpp pin_to_biggest_l3): at start, with two or more L3 caches and the biggest serving
      >= 12 logical CPUs, the process is pinned to it (the 96 MB V-Cache CCD on a 7950X3D). The
      HighGraphics <-> SPU dispatcher lock-line hand-offs no longer cross dies. 77 -> 89.8 fps at the
      spot (same as AFF=FFFF by hand). DES_AFFINITY=0 = off, =<hex> = mask. Single-L3 CPUs untouched.
66. **Lifted PPU code built with SSE4.1 / AVX2 / FMA, no stack cookies, fp-contract off (2026-11-02):**
    - port/project/CMakeLists.txt (copy in patches/port-project-CMakeLists.txt): clang-cl lifted PPU
      units get "-msse4.1;-mavx2;-mfma;/GS-;/clang:-ffp-contract=off" (DS_PPU_SIMD), like the SPU
      sources. ppu_vmx.h's fast paths can inline; fma()/trunc()/nearbyint() become instructions with
      the same results; -ffp-contract=off keeps every PPC multiply and add separate. Full rebuild 4.8 min.
    - Exactness: a VMX fast-vs-scalar test (fix 54's) with these flags at -O1 and -O2: 16 M ops, 0 mismatches.
    - Valley spot, 100 fps, pinned, back to back: 89.2 -> 92.8 fps, frames held 2 refreshes 12.1 ->
      8.1%, catch-up frames 29 -> 7. Latria 50 fps sanity: 99.8% even, frames normal.
    - Left for 100 fps in the heaviest spots (scoping agents, fact-checked): the HighGraphics stores to
      SPU-reserved lines (vm_write32 -> lock-line lock, PPU reservation walk, SPU walk with a seq_cst
      fence; reservation fields share cache lines with hot registers), the out-of-line ds_toc_check
      after every guest call (DRAIN_TRAMPOLINE), ctx __restrict; or an automatic 100<->50 switch
      (vblank 200<->100 Hz + present interval 1<->2 at a fixed clock 167; clock scale must not change
      mid-run: absolute multiply in sys_timer.c / ppu_sysprx.cpp). Repro: a save in the Nexus,
      DES_WARP_AT=125:5,1,997 (lands at a boss arena; DES_GOD=1) + DES_TELEPORT_AT=150:<mark>.
67. **Cheaper PPU stores to SPU-reserved lines: a held-line table (2026-11-02, Valley 100 fps):**
    - Profile (DES_PERF_STACK_EVERY=2, HighGraphics at the Valley spot, 100 fps): 16.9% of its samples
      in the store path for lines an SPU kernel has reserved -- vm_write32 -> lock-line lock ->
      spu_coh_notify_write (walk of ~8.7 listed SPU contexts reading resv_valid/resv_ea from cache
      lines their threads write, seq_cst fence) + ppu_resv_break_line (walk of the PPU contexts).
      SPU_COH_STATS: 2.5 M such stores/s, 2.1 M of them to one line (0x01B51080), a holder found 6%.
      The per-call ds_toc_check was only 0.7% -- left alone.
    - spu_coherency.c: each listed context gets a slot in s_coh_held[64] (line|1 it may hold). The
      locked GETLLAR path publishes under the lock-line lock, spu_coh_reserve_fast before its seq_cst
      fence (the same store-buffering argument as resv_valid); only the owner clears its slot
      (spu_coh_release after PUTLLC / PUTLLUC / lost-poll / failed GETLLAR) or the lock when the context
      leaves the list; a notifier never clears one (it could erase a fresh publication). A write visits
      only the contexts whose slot shows its line (s_coh_slot_ctx), or the whole list when some listed
      context has no slot. SPU_COH_HELD=0 = walk everything as before.
    - spu_coh_notify_write_ppu (VM_WRITE_COH in ppu_loader.cpp / ppu_memory.h): a plain PPU store no
      longer breaks other PPU threads' lwarx reservations on such a line -- ordinary lines never did
      (value-CAS per word); SPU writes (PUTLLC, PUTLLUC, DMA, workload) still do, which is what the
      Havok queue needed. SPU_COH_PPU_BREAK=1 = as before. MSVC /alternatename falls the new symbol
      back to spu_coh_notify_write in builds without spu_coherency.c (unit tests).
    - Two agent review rounds: round 1 found a real hole -- spu_context_init memsets a context that is
      still listed (raw SPU stop/restart), its coh_slot became 0 while its node kept the slot, so its
      reservations were never published and stores skipped it (missed SPU_EVENT_LR); fixed by
      re-syncing coh_slot from the node in spu_coh_reserve's existing-node branch. Round 2 (final
      version): no findings. runtime/spu/tests/test_spu_coherency.c: 195 passed, 0 failed.
    - Result: store path 16.9% -> 7.6% of HighGraphics' samples, its idle (usleep) 16.7 -> 20.3%.
      Valley spot fps is noisy run to run (87.5 / 91.4 old vs 95.7 / 91.6 new); HighGraphics CPU per
      step 10.8 / 10.4 -> 9.0 / 10.1 ms. Safety: Boletaria 1-1 arrival fight at 50 fps (Havok + SPU heavy), 75 s: no hangs, game time 1.000 s/s, 99.0% of frames 2 refreshes.
68. **Guest function-pointer calls: a fast path (2026-11-02, Valley 100 fps):**
    - After fix 67 the HighGraphics profile (DES_PERF_STACK_EVERY=2 samples, self time by function):
      lifted game code 53%, waits (usleep / SPURS queue pop / semaphore / cond) ~30%, ps3_indirect_call
      4.9%, lock-line lock 3.9%, notify 2.6%, ds_toc_check 0.8%.
    - ppu_loader.cpp ps3_indirect_call: when none of its debug switches is set (PPU_CSCHECK,
      PS3_ICALL_GATE, BCTRL_RING, PS3_BREADCRUMB, PPU_TOCWATCH, PS3_CALLTRACE*, FLOW_FORCE_RTCFG,
      PPU_TOCFIX, PPU_RETWATCH -- checked once), a call goes straight to lookup + call + trampoline
      drain, with a per-thread direct-mapped cache (1024 entries) in front of the registry's
      two-array hash probe. Explicit targets, null / unregistered addresses and the depth cap take
      the full path. PS3_ICALL_SLOW=1 = always the full path.
    - Dispatcher share of HighGraphics 4.9 -> 2.4%; fps within noise (90.7 vs 90.8 at the spot).
      Boletaria arrival fight at 50 fps: game time 1.000, 99.3% even, no null-call / recursion /
      garbage-vcall reports (same as before).
    - Where the rest goes: the hottest lifted function (func_00A43718, 4.9%) is VMX culling maths;
      lifted VMX keeps vector registers in guest byte order in ctx->vr, so each op loads, shuffles,
      computes and stores -- a lifter-level change, not a runtime one. ctx __restrict would not help
      that code. Lock-line lock contention (3.9%) would need per-line lock striping.
69. **Borderless fullscreen + keyboard by key position (2026-11-02, GitHub issues #2/#14 and #8):**
    - rsx_null_backend.c: Alt+Enter or F11 toggles a borderless window covering the monitor
      (DES_FULLSCREEN=1 starts in it); key auto-repeat ignored. rsx_live_draw.c: MakeWindowAssociation
      (DXGI_MWA_NO_ALT_ENTER) -- before, Alt+Enter was DXGI's exclusive-fullscreen switch, and in a test
      every Present then failed with 0x887A0001 (the picture froze).
      The swap chain stays at 1280x720 and DXGI stretches it: a monitor that is not 16:9 shows the
      picture stretched (as a resized window already did) -- letterboxing would need the present path
      to draw into a sub-rect of a client-sized swap chain.
    - cellPad.c: the keyboard layouts name keys by US letter; pad_pos_key turns a letter into the US
      scan code and back into the virtual key of that physical key on the game window's layout
      (MapVirtualKeyEx, refreshed once a second), so WASD/IJKL/E/F/R/C sit in the same place on AZERTY /
      QWERTZ. PAD_KEYS_BY_LETTER=1 = old. Enter is not START while Alt is held (Alt+Enter = fullscreen;
      a review agent caught that every toggle opened the game menu). The mouse is already released when
      the window loses focus (the recentre only runs while it has focus); F1 toggles it.
70. **White shadows: depth-texture comparison was never enabled in the live renderer (2026-11-02,
    GitHub issue #10, tutorial screenshot: the player's shadow on a torch-lit wall came out brighter):**
    - Demon's Souls' lit materials (171 fragment programs in the tutorial) sample the 2048x2048 D24
      shadow map on unit 7 with TXP and a TEXTURE_ADDRESS zfunc (LESS): the RSX compares and returns 0/1.
      The translator supports it (rsx_fp_shadow_desc; the shared engine and Metal pass it), but
      rsx_live_draw.c called rsx_fp_decompile_buffered_ex, which takes no shadow state, so every lookup
      returned the raw stored depth (~1.0) and the shader subtracted light where it should not.
    - get_pso builds the descriptors for sampled units (rsx_fp_shadow_desc_from_texture, as
      rsx_draw_engine.c does), hashes them into the PSO key and uses
      rsx_fp_decompile_buffered_shadow_ex. Raw sampling is kept where the compare cannot work: layouts
      the translator rejects (enabled=2), a compare unit read by TXB/TXL/TXD/TEXBEM/TXPBEM (translation
      fails -> retried raw), DEPTH16 and D24 textures not backed by a written zeta snapshot (the
      compare reads depth from .r of the R32F snapshot). Literal-constant mode (non-buffered) is
      unchanged. LD_SHADOW_COMPARE=0 = raw everywhere. LD_FORCE_GREEN now patches main's return.
    - Agent review (3 lenses + verify) found: Alt+Enter = START, auto-repeat, non-16:9 stretch, the
      TXB fallback, D16 / guest-memory D24, LD_FORCE_GREEN -- all handled above except the stretch.
    - Result: tutorial corridor (frame dumps, LD_SHADOW_COMPARE=0 vs default): the bright glow on the wall around the player becomes a proper darker shadow, floor shadow ahead of the player appears; 171 programs compile with _rsx_shadow7 (LESS). Final build: no [shadow] fallbacks or pso-fail in the tutorial or a Latria run (99.85% frames even, frames normal).
    - Repro: a save in the Nexus, DES_WARP_AT=130:8,1,10 (tutorial corridor), DES_GOD=1;
      LD_F12_CAPTURE + LD_CAPTURE_AT=<frame> for per-draw captures, LD_HLSL_DUMP for the programs.
71. **Movies play: real cellSail + PAMF playback (2026-11-02, GitHub issues #4 black title screen and #11):**
    - Before: cellSail was a stub and every launcher sets PS3_NO_SAIL=1, so the player failed to create and
      the game skipped all six movies: ds_title (the logo drawing itself out of smoke on the title screen),
      ds_advertise (the attract film after the boot logos and on title idle), ds_oldtale, ds_opening,
      ds_goodending, ds_badending. The title screen stayed black where the logo should be (issue #4).
      Without PS3_NO_SAIL the stub never sent the events the game waits for and it hung on a black screen.
    - How the game drives it (ppu_recomp_089.cpp 5951-16042, wrapper ppu_recomp_056.cpp 52431-55473):
      MemAllocatorInitialize -> PlayerInitialize2 -> sound/graphics adapter init (callbacks: makeup, cleanup,
      formatChanged [, alloc, free]) -> SetParameter(0x19 = buffer release delay 2) -> FutureInitialize ->
      Boot (its CALL_COMPLETED(BOOT) handler calls FutureSet + ReplaceEventHandler) -> per movie
      CreateDescriptor("x-cell-fs://...pam") -> OpenStream -> on STREAM_OPENED: DescriptorGetStreamType (the
      RETURN value), CreateDatabase (= a CellPamfReader) + OpenEsVideo -> on ES_OPENED(video): PAMF reader
      queries (0x15 = any audio) + OpenEsAudio -> on ES_OPENED(audio) "ready" -> Start -> per frame
      GraphicsAdapterGetFrame (RGBA into the title's 4 buffers, texture remap 0xA993) + UpdateAvSync; its
      sound thread pulls SoundAdapterGetFrame. End: SOURCE_EOS, STATE 7, STATE 4 -> CloseStream -> teardown
      (Unsubscribe x9, adapter Finalize, PlayerFinalize). The game finalizes and re-creates the player for
      every movie. The wrapper is a state machine (handler table EBOOT 0x18716C0: 2 wait-open, 3 start,
      4 wait-finished, 5 close); its close (func_00FDBEC8) polls with no timeout until STREAM_CLOSED arrives.
    - New: libs/codec/sail_engine.c (reader thread: 64 KB reads -> sail_mpegps.c program-stream demux;
      decoder thread: vdec_mf.c = the Windows Media Foundation MPEG-2 decoder MFT -> I420 -> RGBA BT.709,
      ring of 6 frames; LPCM into a 4 s byte ring). cellSail.c rewritten: real state machine and events,
      futures, descriptors in guest memory, adapters keep their callbacks, frame buffers and PCM slots from
      the title's own allocator, movie clock = host QPC since Start (never guest time, so PS3_CLOCK_SCALE does
      not speed movies up), frames handed out when due (late ones dropped), PCM as f32 BE, end of stream once
      the pictures are out and the audio drained (or 1 s past the movie's end). cellPamf.c: readers bound to
      the header copy (pamf_reader_bind_host / unbind), SDK error codes and struct sizes, the 0x14/0x15
      wildcards, SetStreamWithTypeAndIndex / GetStreamTypeAndChannel. Movie paths resolve like cellFs
      (ppu_vfs_root + PS3_GAME fallback); sys_fs_translate_path gave .\USRDIR\movie\... (wrong root).
      mfplat + mfuuid linked. ppu_loader.cpp: ppu_guest_callers() = the whole guest call chain (debug).
    - Gotcha (the last bug): the game reads ONE event per poll, and its start routine (func_00FD8FB8) only
      calls cellSailPlayerStart when the state it has recorded is OPENED (4). ES_OPENED(audio) marks the movie
      ready, so it must come AFTER CALL_COMPLETED(OPEN_STREAM) + STATE_CHANGED(4); in the other order the game
      tried to start in state 3, skipped Start, judged the movie finished and closed it.
    - Agent review (4 areas + adversarial verify, 11 findings, 3 confirmed, all fixed): a skipped movie
      (PS3_SAIL_SKIP / no decoder) sent no STREAM_CLOSED, so the close loop hung; Initialize2 refused every
      title's player when no decoder was found (would break Midway/Tokyo Jungle's legacy path -- the player is
      now always created and only PAMF movies are skipped); end of stream cut the audio tail. Also fixed: the
      reader no longer waits forever if the decoder fails to open, GetUri writes through guest memory,
      INVALID_STATE = 0x80610702.
    - Kept: anything that is not a playable PAMF (other containers, no allocator) takes the old
      instant-open/instant-end path that Midway Arcade Origins and Tokyo Jungle rely on.
    - Switches: PS3_NO_SAIL=1 (skip all movies, the old behaviour), PS3_SAIL_SKIP=<name,...>,
      PS3_SAIL_DECODER=none, PS3_SAIL_FORCE=<host .pam> (tests), PS3_SAIL_PCM=s16, PS3_SAIL_AV_MS=<n>,
      PS3_SAIL_LOG=1 (events, Open/CloseStream call chains, a line a second: frames shown/dropped, PCM
      buffered, sound pulls).
    - Result (sandbox, frame dumps + AUDIO_WAV): boot logos -> ds_advertise plays (picture right, captured
      mix vs the movie's own LPCM: envelope correlation 0.92); ENTER stops it -> ds_title draws the logo,
      the last frame stays up under PRESS START BUTTON, ~20 s later the attract film again (as on a PS3).
      Each other movie forced through the first slot for 75 s: opening 0.95, old tale 0.98, good ending
      0.82, bad ending 0.65 correlation, all programme audio (spectral flatness < 0.08), 0-1 frames dropped
      (17 in one run where the game itself ran at 29.7 fps: the movie keeps real time). 60 fps mode (200%
      guest clock): 30.0 movie fps, same flow. PS3_NO_SAIL=1, PS3_SAIL_SKIP=ds_advertise and
      PS3_SAIL_DECODER=none: movies skipped, no hang.
    - Launchers: movies on by default; `set DES_MOVIES=0` sets PS3_NO_SAIL=1 (skip them, the old
      behaviour). An inherited PS3_NO_SAIL is cleared.
    - Repro: PS3_SAIL_LOG=1, no PS3_NO_SAIL; past the auto-save notice the attract movie starts ~44 s in;
      ENTER skips it to the title. Audio check: AUDIO_WAV capture vs the movie's own LPCM track.
    - Follow-up (same day): at 50 and 60 fps the movie flashed black 2 game frames in 5 (50) or every other
      one (60). The game's player (func_00FDBB10) clears "frame this tick" (+0x7B4) on every poll and sets it
      only when cellSailGraphicsAdapterGetFrame succeeds; the movie is drawn only when it is set. At 30 fps a
      ~30 fps movie has a frame due almost every tick, so sparse frame dumps never caught it. Fix: GetFrame
      hands the last frame back again (same buffer and pts, new tag) while the movie runs and nothing new is
      due; Start clears it, close/Stop end it. Stats line: "repeats N". Result (LD_VIDEO on a 100 fps grid,
      per-frame luma): 50 fps 1390 of 3457 movie frames black -> 0; 60 fps -> 0; 30 fps 0 with 0 repeats
      (unchanged). The title logo still draws and holds under PRESS START BUTTON.
72. **Boletaria choppy on a Ryzen 7 5800X: the game's frame skip locked in (2026-11-02, recordings from a
    5800X + RTX 3070, 60 Hz):**
    - Symptom: tutorial and Nexus smooth, Boletarian Palace "super choppy" at 60 fps; unlimited better but uneven.
      In the Palace about 30 real pictures a second: a full frame, then 1-5 ms later a frame without its 3D
      scene (0-250 draws), over and over; one stretch in the unlimited log lasted 31 s. GPU waits tiny, so
      not a renderer API question (Vulkan would not help); the 5800X is ~1.4-1.6x slower per thread on the
      serial game -> HighGraphics -> SPU command dispatcher chain, which put Palace frames just over 18 ms.
    - The skip (found with a timer-caller count, then a log of HighGraphics' frame controller): func_000CBB70
      takes the time since the previous flip in guest timebase ticks as a percentage of 1/30 s (tb freq / 30 by
      a mulhdu with 0x8888888888888889). Over 109% it sets byte +0x24 of the frame controller (vtable 0x01855328,
      object at [[HighGraphics+4]+0x34]); while set it keeps skipping as long as two frames take over 210%.
      HighGraphics (func_00D1F188) asks vtable +0x2C (func_000CB7E8: returns 0 when +0x24 and +0x35 are set)
      at 0x00D1F59C and on 0 jumps past the scene draw (func_00D21528 at 0x00D1F694).
    - Why it locked in: PS3_CLOCK_SCALE=200 (fix 28) makes guest time run 2x, so 109% tripped at 18.3 ms of
      REAL time. On PS3 a scene-less frame saved GPU/SPU time; in the port it costs a whole step slot, so the
      next full frame's interval spans two slots (26-34 ms) and is late again: P(late | previous late) = 0.95.
      The adaptive step (fix 33) already keeps game speed right down to 30 fps, so the skip only made pairs.
    - Fix (PORT PATCH in ppu_recomp_015.cpp, des_skip_limit): both limits are scaled by ps3_clock_scale(), so
      the skip fires at the original 36 ms of real time in every mode (30 fps unchanged: clock 100).
      DES_FRAME_SKIP=0 never skips, =1 the lifted limits; "[des] frame skip: ..." says which.
    - DES_STALL_MS=<n> (default 100, 0 = off; adaptive step in ppu_recomp_011.cpp): step intervals longer than
      that (shader compile, OS hiccup) stay out of the 24-step average, which now keeps intervals, not stamps.
      Before, a 770 ms stall in a recorded tutorial run was paid back at 3.1x speed for 0.3 s (step stuck at
      1/30); now the game freezes and resumes, as on PS3.
    - cellPad.c pad_now_ms: QPC instead of GetTickCount64 (~15.6 ms ticks), so the 4 ms poll gate really is
      250 Hz. Above 60 fps ~40% of steps got no new pad report (a recorded unlimited log: 62.6 polls/s at 102
      steps/s). Sandbox at 100 steps/s: 99.7 polls/s, 0 steps without one.
    - perf_report.py catch-up count: light frame (< 40% of the previous frame's draws, previous >= 400) whose
      ready time (present minus pacing hold) is < 20 ms after the previous frame; stretch = a catch-up every
      2nd frame, timed from the log. The old count (whole-log median draws, 17 ms gap) also took menus and
      loading frames: three recorded runs 8625 -> 966, 2670 -> 919, 2233 (agrees with hand counts).
    - A/B (a save in the Palace torch hall, 60 fps mode, window 115-150 s of the present log;
      "full" = frames with >= 300 draws), pinned to 4 cores (DES_AFFINITY=FF0000) to
      stand in for the 5800X:  lifted skip 38.0 full frames/s, 58.7 presents/s, full-frame gap median 29.6 ms,
      sd 7.3, 55% over 25 ms  ->  new 51.0 full/s, 51.0 presents/s, median 19.3, sd 2.1, 2% over 25 ms; game
      time 0.99 both. Unpinned (7950X3D): 48.5 -> 53.1 full/s, gaps over 25 ms 20% -> 3%. LD_PRESENT_PACE 0.85
      vs 0 with the new limits: no difference (51.0 / 50.6 full/s), so the launchers keep it. Unlimited
      (480 Hz) + DES_HITCH_AT=118:600,130:400: 49 full/s, 0 catch-ups, step max 20.3 ms after the stalls
      (no 1/30 fast-forward), game time 0.96 for that window = the 1 s of stalls not paid back. Frames normal.
    - Not done: making DES_MAX_FPS a real frame cap (a refresh-rate cap would turn unlimited back into the
      60 fps mode); the dispatcher's per-command cost and a core plan for 8-core CPUs (next, if a 5800X still
      drops below 60 in the Palace).
    - Debug used (removed again): DES_TB_CALLERS (callers of the timer vtable 0x018796D0 +4/+8 per thread:
      HighGraphics reads it ~20 times a frame, profiling scopes) and DES_SKIP_LOG at 0x00D1F564.
73. **Keyboard dead with a controller connected; repo updates never applied (2026-11-03: no way past PRESS START
    BUTTON with mouse + keyboard; GitHub issue #8: AZERTY tested, not working):**
    - cellPad.c read the keyboard only when XInput slot 0 had no pad. A pad that was merely on, or a virtual one
      (Steam Input, DS4Windows/ViGEm, Parsec), made Enter = START and every key do nothing: stuck at PRESS START
      BUTTON with mouse + keyboard. Now pad_poll_keyboard runs after every XInput poll while the window has focus:
      no pad -> the keyboard is port 0 (as before); with a pad its buttons are ORed in (pressure 255), a stick the
      keys / mouse move replaces the pad's, triggers take the max. The souls layout captures the mouse only when
      there is no pad or the keyboard / mouse was used last (kb_last: a key or mouse button sets it, any pad input
      clears it), so a pad player's cursor stays free. Focus loss releases keys only when there is no pad.
      PAD_TEST_FAKE_PAD=1 (TEST) = port 0 is a connected idle pad. Default layout = pad_poll_keyboard_basic.
    - Sandbox (PAD_TEST_FAKE_PAD=1, PAD_KEY_SCRIPT E at 30-38 s, ENTER at 75 / 80 s): log "keyboard input on port 0
      (merged with the XInput pad)"; PRESS START BUTTON -> NEW GAME / LOAD GAME -> LOAD GAME (server notice).
    - Updates: SETUP.bat applied patches/ps3recomp-local.patch (step 3, mark deps/ps3recomp/.ds_patched) and
      patches/lifted-code.patch (step 5, mark port/.lifted) ONCE; a later SETUP said "already done" and BUILD.bat
      only compiled. So no pushed fix since the first setup reached anyone who updated (the AZERTY tester still had
      keys by letter: fix 69 was in the patch, never applied). setup/patch_sync.py (repo): the marks now hold the
      patch's sha256; on a change the runtime files the old patch touched (git status) go back to the commit and the
      new patch is applied in the checkout; the lifted code has the old patch reversed (the saved port/.lifted.patch,
      or for old setups the version from the checkout's git history whose reverse --check passes) and the new one
      applied. Files whose bytes end up the same get their old mtimes back, so ninja rebuilds only what changed.
      No match -> 'relift' (SETUP recompiles, a few minutes); HEAD moved -> step 3 from scratch. BUILD.bat runs the
      sync first (and says to run SETUP when it needs a relift). README: "Updating".
    - Update tests (scripted, on throwaway copies): installs at 1e51be0's and 5e9f3a7's patches
      with old-style marks -> only ppu_recomp_011/015 (lifted) or cellPad.c (runtime) rewritten, trees equal the new
      patch; again -> 'current'; hand-edited file -> 'relift'; moved ps3recomp HEAD -> set up again.
    - Agent review (2 areas + adversarial verify, 9 confirmed, 8 fixed): kb_last started at 1 (an idle pad player's
      cursor was captured from launch) -> 0; WASD / IJKL now count as keyboard use; the click that focuses the
      window, Alt+Tab's Tab and Alt+Enter with Alt let go first reached the game (R1 / R3 / START): pad_game_down
      ignores a key that was down when focus came back or while Alt / Win was held until it is released (replaces
      the Enter-only Alt check); focus loss without a pad releases triggers too (pad_host_release). patch_sync:
      the runtime update reverted everything that differed from the commit (user files too) -> only paths the old
      and new patch name, old version from the saved deps/ps3recomp/.ds_patched.patch or the history; a new lifted
      patch that does not fit -> 'relift' instead of an exit on every SETUP; the lifted mark holds the lift inputs
      (commit, LIFT_ARGS, SPURS_JOBS, lift_spurs_jobs.py hash: setup.lift_inputs) -> relift when they change; the
      history pick takes, of all versions that reverse cleanly, the one whose +/- lines contain the others'
      (comparing whole hunks failed: context shifts between versions). Not fixed: a poll publishes port 0 in two
      steps (XInput, then the keys), so a reader can see one report without the keys -- the XInput poll already
      wrote field by field. Extra tests: inputs changed -> relift; new patch broken -> relift, files unchanged;
      a stray file + an edited README in deps/ps3recomp survive a runtime update; 99feea3 -> 1 file.
    - Gotcha: with core.autocrlf=true, git apply writes CRLF even outside a repository, so port/ files are CRLF after
      step 5 on most PCs (compiles the same; compare ignoring CR).
74. **Higher internal resolution + the swap chain follows the window (2026-11-03, GitHub #14/#15):**
    - DES_RES_SCALE=<2..4> (or LD_RES_SCALE) renders the game's targets at that multiple; default 1. Fixed at
      startup. Measured (Palace torch hall, 60 fps mode, 7950X3D): 1x and 2x both 59 fps, 0 catch-ups, game
      time right, brightness equal (frame mean 31.6 vs 31.6); full-frame gap sd 1.2 -> 3.4 ms (>25 ms 0.2% ->
      0.6%). 2x is visibly sharper (hair, face, edges).
    - rsx_live_draw.c: surface_t / zdepth_t keep the GUEST w/h (cache key, texture-alias size match, swin,
      surface_containing, write-back, every guest comparison) and gain sc; the D3D12 resources are w*sc x h*sc
      (LD_HW/LD_HH). ld_surface_scale: targets from 128x128 up inside the canvas get S; bigger than the canvas
      (2048 shadow map + its dummy colour target) only with LD_RES_SCALE_SHADOW=1; under 128 stay 1x (the
      16x16 / 64x64 FP32 luminance results written back to guest memory, fix 21; write-back also skips sc!=1).
      Zetas scale by their canvas-padded backing. First rule (>= half the canvas) thrashed: zeta 0xB50000 is
      bound by the 1280x720 scene AND by four 128x128 passes (logged "live new #0" on every switch) -> 128 rule.
      The 64x64 / 16x16 luminance passes still bind the 2x zeta 0x0 at 1x ("[res-scale] colour ... drawn with
      zeta" logged); they do not depth-test (review checked the captured state).
    - Draw: host viewport = clip*tsc, the NDC transform stays over guest pixels, scissor *aa*tsc. Blits:
      same-scale copies multiply their boxes; across scales ld_scaled_blit (guest units both sides now, the
      destination multiplied inside). Occlusion: each query's count divided by its target's sc^2, rounded up
      (flares stay at native brightness, fix 38). get_pso: programs reading WPOS on a scaled target get
      rsx_fp_apply_wpos_grid; UNNORM depth compares on a scaled snapshot get coordinate*(sc/size) -- both only
      in the key when > 1, so 1x keys and the disk shader cache are unchanged. Frame dumps / LD_VIDEO at host
      size (LD_VIDEO over 4096 wide: ffmpeg scales to 2160 lines for NVENC). Movie caption overlay skips scaled
      surfaces. Legacy DSV slot 0 at canvas*S.
    - Present: ld_swap_follow_window() -- the swap chain was fixed at 1280x720 and DXGI stretched it to any window
      or borderless fullscreen (aspect too), which also threw a higher resolution away. Now a client size stable
      for 3 presents waits for the GPU and ResizeBuffers; a surface of another size than the back buffer is drawn
      letterboxed at its own aspect (black bars): box filter (ld_downsample_to) when the host size is an exact
      multiple, bilinear (ld_present_bilinear) otherwise; same size = the old CopyResource. LD_SWAP_RESIZE=0 =
      old. Checked with back-buffer dumps (TEST LD_TEST_CLIENT=<w>x<h>, LD_BB_DUMP=<ppm> + LD_BB_DUMP_AT=<frame>):
      2x in 1720x720 = 1280x720 box + bars, 2x / 1x in 1920x1080 = bilinear, full window.
    - Agent reviews: map (5 readers + critic) before; after, 3 lenses + verify: 7 real
      (zeta size merged across scales -> 4096^2 + rebuilds; UNNORM shadow compare used host GetDimensions; WPOS
      patch only in the buffered branch; movie overlay copy; LD_VIDEO over NVENC width; duplicate), all fixed;
      7 refuted (descriptor ring, VRAM growth -- the table fills with 16x16 targets first --, 1x behaviour).
    - Not done: DLSS/FSR (no motion vectors in a PS3 game; the GPU is idle anyway, supersampling is better here);
      a launcher option (next: the launcher replacing the .bat files).
75. **DemonsSoulsLauncher.exe: one window instead of ten .bat files (2026-11-03, GitHub #3/#17):**
    - project/launcher/launcher.cpp: plain Win32 + GDI+ (the banner is the user's own game\PS3_GAME\ICON0.PNG,
      none ships), no runtime. Its own CMake target (project/launcher/CMakeLists.txt, added by the main project
      on Windows hosts only, not the Linux cross build); a ninja target copies it next to PLAY.bat on every
      build (copy_to_root.cmake: an open launcher locks the exe -> warning, the build goes on).
    - It does not reimplement PLAY.bat: it sets DES_FPS / DES_RES_SCALE / LD_RES_SCALE_SHADOW / DES_GAME /
      DES_FULLSCREEN / DES_MOVIES / DES_GOD / DES_RECORD / LD_TEX_DUMP / PAD_KEYS_BY_LETTER / DES_AFFINITY
      (every one set or cleared, LD_RES_SCALE cleared since it wins over DES_RES_SCALE), then the "Extra
      settings" NAME=value pairs, then runs PLAY.bat hidden (cmd /d /c, CREATE_NO_WINDOW). DES_LAUNCHER=1 makes
      PLAY.bat skip its three `pause`s; a non-zero exit comes back through cmd and the launcher offers
      REPORT.bat. launcher.ini in the port folder; `--play` = start with the saved settings, no window.
    - The fps hint repeats PLAY.bat's vsync rule (refresh or refresh+1 a multiple of N) using
      EnumDisplaySettings (100 Hz where PLAY.bat's CIM query says 99; both pass the 95-105 test).
    - Check for updates: git fetch + rev-list --count HEAD..@{u} (hidden, GIT_TERMINAL_PROMPT=0), the new
      commits' subjects in the question; on yes git pull --ff-only + BUILD.bat from a script in %TEMP% (the build replaces the running exe), which
      reopens the launcher; a ZIP copy (no .git) only rebuilds. Full paths in that script: with
      NoDefaultCurrentDirectoryInExePath set, `call BUILD.bat` was "not recognized" in a test.
    - Tested on a scratch copy with a fake DemonsSoulsRecomp.exe that writes its path, args and environment:
      defaults (auto -> 50 on the 100 Hz screen, same variables PLAY.bat sets), every option flipped (custom 72
      -> 144 Hz vblank, clock 200, DES_MAX_FPS 72; stale LD_RES_SCALE=3 / DES_GOD=0 in the parent environment
      overridden), fake crash (exit 3) -> report prompt, Update against a local bare remote + fake BUILD.bat,
      locked-copy build. The .bat files are unchanged apart from the pauses.
    - Agent review (4 lenses + one refuter per finding): 7 real, all fixed, 1 refuted (the fps hint's refresh
      source). Fixed: Update while the game ran (rebuild fails on the locked exe; the button is now off while
      playing); git fetch on the UI thread with a timeout that could never fire (blocking pipe read before the
      wait) -> check on its own thread, git in a kill-on-close job, GCM_INTERACTIVE=never,
      GIT_HTTP_LOW_SPEED_LIMIT/TIME 1000/20 (stalled server test: answer after 20 s, window responsive);
      extra settings stayed in the launcher's own environment for later runs -> PLAY.bat now gets its own
      block (CREATE_UNICODE_ENVIRONMENT), the launcher's is never changed; an empty Custom box ran the old
      rate; the build-tree copy (port\build_opt\launcher) could not find PLAY.bat (3 levels up, needs 4); a
      failed BUILD.bat after git pull left "you have the newest version" -> update_pending.txt, removed by the
      script after a good build (or ignored once the exe is newer), makes the button offer the build again;
      DS_XWIN=1 Windows builds skipped the launcher (CMAKE_CROSSCOMPILING) -> gate on CMAKE_HOST_WIN32.
75. **Low-end CPUs: the heavy Palace spot profiled; usleep no longer spins; crash-proof stack sampler
    (2026-11-03, a 5800X + RTX 3070 recording: Palace mostly 59.9 fps, two heavy spots ~52):**
    - The recording: fix 72 works on the 5800X (catch-ups 10 in 4.4 min, 100-230 s 99.92% even); around marks 2/3
      (area 2 block 0, -96,57,-61 / -88,59,-62) 743 draws/frame, render CPU 7-10 ms, HighGraphics 52-81% of a core,
      frames ~19 ms. Repro: a Palace save, DES_TELEPORT_AT=135:-88.37,59.50,-62.08, two 0.35 s L presses: 773 draws, render 8.5 ms. HighGraphics at that view: 77% (5800X) vs 50% (7950X3D),
      render thread 50% vs 45% -> HighGraphics (lifted game code) is what limits the 5800X there. Pinned to 2 cores
      (DES_AFFINITY=0F0000) a 7950X3D runs the spot at ~43 fps with the CPU saturated (380% of 400) = low-end stand-in.
    - Profile (DES_PERF_STACK_EVERY=2, symbolised self/inclusive counts): no single hot spot.
      HighGraphics: half in sys_semaphore_wait; func_00D21528 (scene) -> func_000F88E0 (SPU job-queue writer: 16-byte
      entries into a ring an SPU job reads, usleep(30) while full -- 2.5% here) ~18%; the VM_WRITE_COH lock + notify
      + fence for stores to SPU-reserved lines ~7% of samples (~15% of its busy time); 80% of its lifted time is
      already in the -O2 units. Render thread: busy ~50% at 773 draws, spread (fifo 42% incl., sink_end 31%, get_pso
      5%, vertex fetch 5%, texture hashing 4%, the 8 KB constant memcpy per draw ~1%). synth2: 42% waiting, the
      resampler loop spu_0010 func_00001090/1120 ~26%, x8 fa/fm slow lanes 8%.
    - sys_timer_usleep (sys_timer.c): waits under 1 ms were busy-waited (QPC + SwitchToThread). MOStreamingThread
      polls usleep(~800 us) 640x a second -> 52% of a core, all run long (PS3_POLLTOP: tid 18 lr 0x00D64EC4). Now
      waits >= PS3_USLEEP_SPIN_US (default 200) sleep on a per-thread high-resolution waitable timer (Windows 10
      1803+; one per thread, closed when the guest thread ends; the >= 1 ms path reuses it instead of creating one
      per call); shorter waits still spin (HighGraphics' 30 us ring wait). PS3_USLEEP_SPIN_US=1000 = old timing
      everywhere (plain timer). A/B at 2 cores (two rounds each): 44.8/42.0 old vs 42.5/44.8 new fps -- same; worst
      frame 89/106 -> 54/55 ms, 99th pct 36-44 -> 30-37 ms. At 2 cores the spin had throttled itself (8%); on CPUs
      with idle cores it frees ~half a core (and the hyperthread sibling it shared).
    - Stack sampler (rsx_live_draw.c perf_sample): sampling an SPU group thread (synth2) crashed the game inside ntdll
      (unwinding lifted SPU frames without unwind data through a garbage stack pointer), and unwinding while the
      thread is suspended can block on an ntdll lock it holds. Now: suspend, read the stack range from the TEB,
      copy up to 64 KB of the stack, resume, unwind the copy (Rsp/Rbp rebased, bounded to the copy, __try/__except).
      Slot 0 is reserved for main (the old shuffle raced a thread registering at the same moment). SPU group threads
      can be named in DES_PERF_STACK_THREADS (lv2_register.c; "spu__synth2_Group:0" -- spaces match '_'). Short-lived
      "spu job" threads are not hooked (a slot per dispatch).
    - Agent review (2 areas + verify): 6 real, all fixed (MinGW TLS, SPIN_US=1000 not fully old, handle leak per
      thread, unwinder deadlock, TEB read race, slot-0 race); 2 refuted.
    - Next (measuring on a 5800X): native synth2 resampler loop, cheaper VM_WRITE_COH,
      per-draw renderer costs, -O2 for the remaining hot -O1 units.
76. **Straight into offline play: no "Cannot connect (009)" / "Start the game in Offline Mode" boxes
    (2026-11-03, GitHub issue #5):**
    - NEW GAME and LOAD GAME build a login task (func_0019AFE8; state +0x8, handler table of 28 states filled by
      func_001993F0, message to show at +0x64). State 0 (func_00197890) asks func_0052BD50(*netmgr) for the
      "network connected" byte (net singleton +0x69), always 0 here -> +0x64 = 0xC546 (msg 50502 "Cannot connect to the
      Demon's Souls server ... (009)"), state 0x10 (func_00199C00: func_0020DC58(0) = online-mode byte 0, the box,
      func_0052B260(*netmgr) = net session shut down) -> 0x11 (func_00199B88: 0xC545 = 50501 "Start the game in
      Offline Mode") -> 0x13 -> 0x1B -> -1. Messages from MSG/NA_ENGLISH/menu.msgbnd entry 78 (FMG v1 BE); every ID is
      loaded as li 0 + ori 0xC5xx. The game's own automatic-offline route (state 1 -> C549 -> 0x13) does the same
      teardown without the 009 box.
    - PORT PATCH (ppu_recomp_018.cpp func_00197890, loc_001978F0): with no network it does func_0020DC58(0) +
      func_0052B260(*netmgr), +0x64 = -1, state 0x13 -- the two boxes' side effects without the boxes. Log once
      "[des] auto-offline: ...". DES_AUTO_OFFLINE=0 = the prompts again. HLE answers were not changed: reporting a
      connection sends the game down sign-in / server login, which still ends in the Offline Mode box.
    - Checked (sandbox, frame dumps): LOAD GAME -> Profile List directly; NEW GAME -> Create Profile path (with 4
      profiles: "Profile slots full", the normal box); a save loads into the Palace (heavy75 flow); DES_AUTO_OFFLINE=0
      -> the 009 box. Old test PAD_SCRIPTs that pressed Cross for these boxes now press it in the world (harmless in
      the runs so far; retime if one matters).
    - Found with an agent workflow (message IDs from the FMGs + the login state machine).
77. **Heavy Palace spot 49 -> 59.4 fps on a 5800X: the SPU dispatcher's per-command runtime cost (2026-11-03,
    measured on the 5800X + RTX 3070, 60 Hz):**
    - Repro (sandbox on that PC: a copy of a Palace save, menus by PAD_KEY_SCRIPT, DES_TELEPORT_AT=175:-88.37,59.50,-62.08,
      then ONE J (camera left) press -- 764 draws, render 10.3 ms): 47-50 fps with fix 75, HighGraphics 78-80%.
    - Profile: HighGraphics' own work is only ~40% of the frame. 37.5% of its stack samples are sys_timer_usleep from
      one site, func_00ACAFA8's loop at 0x00ACB098: it writes command 0x9023 into the SpursTaskCommandDispatcher's
      ring (func_00011720) and polls usleep(30) until the SPU sets the done word (r26) -- i.e. HighGraphics waits for
      the dispatcher (SPU image 1, one "spu job" host thread at 100%). The in-game sampler skips "spu job" threads, so
      the dispatcher was sampled from outside (scratchpad ripsample.cs: suspend / GetThreadContext RIP at ~1 kHz,
      QPC-stamped and joined to HighGraphics' samples): while HighGraphics waits, the dispatcher is 35% lifted code and
      ~60% runtime -- spu_wrch 11.6, mfc_do_transfer 8.4, mfc_submit 8.2, ppu_resv_break_line 6.6, coh notify 3.9,
      taskset_is_down 2.2, mfc_for 1.7, overlay / gcm / lockguard / atom-trace / lockstep hooks ~1 each.
      SPU_MFC_STATS: that one thread issues ~6.8 M MFC commands/s (PUT 1.43 M ~41 B, GET 1.6 M ~132 B, GETLLAR 2.43 M,
      PUTLLC 1.36 M) -- ~150 ns each, so per-command overhead is the frame rate. (synth2, the HighGraphics store path
      and the renderer are not on this path; the renderer idles 40% at this spot.)
    - Fix (runtime only, exact with every switch unset AND set; workflow: 4 readers + synthesis, 3 implementers on
      disjoint files, 2 review lenses + verify: 0 findings):
      - spu_dma.h: the ~40 env-gated diagnostics in mfc_submit / mfc_do_transfer / mfc_run_list moved verbatim into
        noinline helpers called at their original points under one lazily read flag (mfc_diag_init: any of the
        switches set); functional code (LAX, DSP_IMAGE_EA, LBP skip, s_desc_ea, CRI, repeat detector, barrier return,
        wws batch) stays inline. mfc_ea_range_committed: page test inline, VirtualQuery miss out of line.
        Reserved-line tests inline (spu_coh_line_reserved_now, compiler fence + relaxed loads, re-read each time);
        a single-line reserved PUT calls notify_write_except directly. Overlay / lockguard calls gated by header
        globals g_spu_ovl_gate / g_spu_lockguard_gate (selectany, 1 = call). POISON scan only while it can still print.
      - spu_channels.c: spu_wrch / spu_mfc_atomic diagnostics into cold helpers behind s_wrch_diag (frame 0x588 ->
        0x138); mfc_for inline cache check + noinline slow path; yz_lockstep_tick / spu_taskset_line_committed /
        spu_atom_trace called only when their switch or state needs them; spu_lockguard_check closes its gate once
        SPU_LOCKGUARD is known unset; the overlay gate closes while no overlay source exists and SPU_DUMP_OVL is off,
        and registration reopens it before (and re-checks after) the count grows; g_spu_putllc_count++ dropped (never
        read). spu_workload.c: spu_taskset_is_down memoised per thread with a generation bumped on shutdown / revive.
      - spu_coherency.c: SPU_COH_STATS block cold; walk counters only under it; s_coh_from_ppu global -> parameter;
        lock-line lock fast path = one xchg, the spin + QPC wait accounting (SPU_JOB_STATS only) out of line.
      - CMakeLists.txt: spu_channels.c / spu_coherency.c built /GS- (as the lifted SPU code).
    - A/B at the spot, back to back (B C B C): 49.0 / 50.2 -> 59.4 / 59.4 fps (the 60 cap), frame median 19.9 / 19.5 ->
      16.7 / 16.6 ms, p99 30.4 / 27.9 -> 23.7 / 23.4, frames over 25 ms per minute 121 / 88 -> 14 / 16; HighGraphics
      79 / 78 -> 57 / 55%; game time 1.002; 99.1% of frames held one refresh. Safety: Palace -> DES_WARP_AT 4,0
      (Latria load, SPU zlib) -> walk / attacks / roll / block / pans: 59.4 fps, game time 0.997, no new errors
      (same watchdog boot dumps as before). test_spu_coherency: 195 passed, 0 failed; test_mfc_resume_elements OK.
      Most other SPU/SPURS fixture tests are POSIX-only and skip on Windows; test_spu_drain_launch fails to link on
      Windows before and after (lv2_spu_receive_event).
    - Also tried: one logical CPU per core (DES_AFFINITY=5555) -- 49.9 / 48.7 vs 50.0 / 51.3 fps, within noise; left off.
    - Next: the reserve_addr / reserve_value fields on their own cache line in ppu_context (ppu_resv_break_line, 6.6%
      of the dispatcher, reads every PPU context's line -- needs the lifter template + both struct copies + a relift);
      a fast path for plain small PUT / GET in mfc_submit.
78. **Real mouse look; the cursor no longer locked to the window (2026-11-03, GitHub #6 / #13 / #18):**
    - Before: the mouse was read every 4 ms poll (cursor offset from the window centre, recentred) and became that
      poll's right-stick deflection. The game takes one report a frame, so it saw only the last poll's slice (jitter,
      most movement lost); the stick then goes through the game's 0.37 RADIAL deadzone (func_001C3000:
      clamp((m - 0.37) * 1.7241, 0, 1)) and tops out at RotSpeed -- small moves vanished, big ones capped. And the
      cursor was captured whenever the window had focus.
    - Camera (agent trace + pin): the player camera is ChrExFollowCam, update func_00119670 (ppu_recomp_016.cpp):
      pitch at cam+0x130, yaw at +0x134, += stick * RotSpeed (+0x1E8/+0x1EC) * dt at loc_0011C7D8, 2 pi wrap,
      pitch clamp [cam+0x1D4, cam+0x1D0] (-0.698 .. 1.222 rad). Stick comes from PadManipulator +0x40 (func_0030F7A0:
      pitch = func_001B6B40, yaw = func_001B6A80, signs from the invert options opt+0x2B / +0x2A).
    - PORT PATCH (016): des_mouse_look_apply at loc_0011C7D8 adds the mouse counts since the last frame straight to
      the stored angles (PAD_MOUSE_LOOK_SENS rad per count, default 0.0012; signs = the game's invert options, so the
      mouse turns like the stick for that player; pitch clamped to the game's limits first -- a big step could wrap
      through +-pi). A mouse frame counts as hand control (loc_0011C8DC) so pitch does not drift back. Lock-on, aim,
      menus and cutscenes never reach that label.
    - cellPad.c: raw counts from WM_INPUT (rsx_null_backend.c RegisterRawInputDevices; no pointer acceleration)
      accumulate; the camera takes them each frame (ps3_host_mouse_look_take); otherwise, at the next fresh report,
      they become right-stick deflection in THAT packet (not the shared state): magnitude 0.37 + 0.58 |v| (cancels
      the radial deadzone), |v| = counts * PAD_MOUSE_SENS (default 0.04) capped 0.97, rest carried -- lock-on target
      switching by flick and bow aim keep working. Ownership counted in reports (the camera took them since the
      last report), not time. Capture: a click into the game window (that click is swallowed, also when the window
      already had focus), F1 toggles, leaving the window or using the pad releases; captured = hidden cursor
      (WM_SETCURSOR) and ClipCursor to the client area. Cursor-delta fallback without WM_INPUT (no jump on the
      capturing poll). PAD_MOUSE_LOOK=0 = stick only; PAD_MOUSE=0 = no mouse.
    - Sandbox (PAD_TEST_MOUSE="<s>:<dx>,<dy>:<dur>;..." TEST counts per poll; DES_MLOOK_LOG=1 angles per 15 mouse
      frames, =2 every free-camera frame): 3 counts/frame -> 0.054 rad per 15 frames exactly; dy -30 for 1 s ->
      pitch stops at 1.2217; directions = the stick's (this save has both invert options set).
    - Agent review (2 areas + verify): 8 real, all fixed (capturing click leaked one R1 frame; stick span 0.63 vs
      the game's 0.58 + cap margin; test hook touched the real cursor; first-capture jump in the fallback; packet vs
      shared state race; PAD_ALWAYS_CHANGE path; pitch flip on big steps; time-based ownership); 4 refuted.
    - Follow-up (same day, first real-mouse test): the mouse turned opposite to the stick on both axes -- the
      sign was the wrong way round for the invert option bytes (sandbox, both options set: stick right raised yaw,
      mouse +dx lowered it; stick down raised pitch, mouse +dy lowered it). Now +1 with the option byte set, -1
      unset, measured equal to the stick on both axes (mouse down raises pitch, up lowers it, right = stick right).
    - Esc destroyed the game window WITHOUT the 3 s exit guard (only WM_CLOSE armed it), so the game ran on with
      no window and its sound playing -- what pressing Esc to free the mouse did. Esc now releases the mouse (null
      and D3D12 windows; the X / Alt+F4 quit), WM_DESTROY arms the guard however the window goes, and the guard
      thread starts before its log line (stderr is block-buffered: a killed process loses the tail of the log).
      Sandbox: Esc -> still presenting 30 s later; X -> gone in 3 s. Agent review (3 areas + verify): 2 real,
      fixed (the pad thread could clip the cursor again right after an Esc release from the window thread -- it
      re-checks after ClipCursor; the D3D12 fallback window's Esc still quit), signs confirmed.
79. **Linux perf logs were half blind; sleep precision in the log (2026-11-03, Ubuntu 24.04 + Proton, i7 Haswell
    4c/8t + GTX 980, tutorial):**
    - The two Ubuntu recordings: 57.5 / 57.8 fps average in 60 fps mode, median frame 16.7 ms, game speed right;
      35-42 hitches a minute, nearly all one missed refresh (27-35 ms). Present returns in ~7 us (vkd3d-proton
      presents on its own thread) and the GPU wait is 1-4 ms even on slow frames, and slow frames draw more
      (median 291 vs 204 draws): CPU-bound, not GPU / vsync. 113 of 130 HighGraphics stack samples in late steps
      are one chain (runtime usleep -> syscall -> thunk -> one lifted caller): the same shape as fix 77's
      HighGraphics usleep(30) poll on the SPU dispatcher. The 450-550 ms hitches are first-time shader builds.
    - But every "thr" line read 0 and there was no render / step CPU: Wine's QueryThreadCycleTime /
      QueryProcessCycleTime are stubs (0). rsx_live_draw.c now falls back to GetThreadTimes / GetProcessTimes
      when the process cycle counter reads 0 (100 ns units at scheduler-tick resolution: right for the 1 s
      lines, coarse per frame); "info cpu_clock cycles|thread_times" says which, "info host windows|wine <ver>"
      the host. LD_PERF_CPU_TIMES=1 (TEST) forces the fallback on Windows: the same sandbox spot read
      spu_job 103 / synth2 52 / HighGraphics 50 by cycles and 101-108 / 53-55 / 49-51 by thread times.
    - Wine's waitable timers go through wineserver and may be ~1 ms coarse, which would stretch every
      0.2-1 ms usleep. Now measured: sys_timer.c counts the sleeps taken (timer / Sleep path), microseconds asked
      and microseconds past the deadline; once a second "slp <sleeps> <us asked> <us late> <1 ms+ late>" in the
      perf log, summarised by tools/perf_report.py. Windows baseline (5950X sandbox, 50 fps): ~1000 sleeps/s,
      7.0 ms asked on average, 0.26-0.28 ms late on average, 0.5% 1 ms or more late. Next: the same tutorial
      route recorded on the Ubuntu box, then act on what it shows.
      Agent review (2 areas + verify): 5 real, fixed -- per-frame / per-step CPU are not read under the
      times clock (10 ms ticks are noise per frame, and each read was a wineserver round trip under the log
      lock): 0 in the log and "not measured" in the report, which also treats all-zero older Linux logs so;
      the first slp line counted all of start-up (cleared when the perf thread starts); a failed / 0 thread
      read wrapped into an absurd %; threads that never used a tick were never dropped from the table.
80. **In-engine cutscenes moved in pairs at 60 fps: the camera picked the nearest of its 30 Hz keys (2026-11-03,
    report: the tutorial's opening, the knight walking through the black void, "frame drops / low framerate"):**
    - Not dropped frames: in the sandbox (60 fps mode) the cutscene presents held 60/s with no long frames. But the
      picture moved in pairs. Measured from an LD_VIDEO capture: per second, the median frame-to-frame change on even
      vs odd frames; ratio > 2 in 19 of 59 s of the tutorial opening (remo scn080000) and in 56 of 64 s of the Nexus
      intro; gameplay sits at 1.0-1.5.
    - Cause (lifted code; the same finding as JonathanDC64/DemonsSoulsRecomp, MIT, its docs/40 and docs/62): the remo
      clock is the step dt (func_00612300: dt * PlayRate; func_005FD730: cut+0x1C += it), and characters (Havok, linear
      between frames) and the FOV (Hermite) are sampled at that fractional time. The camera track sampler
      func_005F71D0 (func_005FD730 -> func_00615208 -> func_00614DE8 -> here) finds the keys either side of t (keys are
      baked one per 1/30 s: time = frame / 30), puts the fraction in f10 (s) and their gap in f11, copies both keys of
      each channel to its stack and then loads the earlier when s < 0.5, else the later. At 30 fps t lands on keys; at
      60 every other frame is half way, so the camera moved 30 times a second while the characters moved 60.
    - PORT PATCH (ppu_recomp_040.cpp): des_cut_decide at 0x005F7254 (once a call, before the loads) and des_cut_blend
      after the position (v4: earlier r1+0xA0, later +0xB0), rotation (v12: +0xD0 / +0xA0, before the code's own
      2 pi wrap) and scale (v2: +0x70 / +0xA0) loads. Blended by s when t is strictly between keys one frame apart;
      rotation the short way round. The nearest key stays (as lifted) for keys further apart (holds), a step that
      moves over 2 m, turns over 0.5 rad or changes scale over 0.25 (a shot change inside one track), an unset index,
      or a register holding neither key. A turn over 0.5 rad whose other Euler set is within 0.5 rad is a flip, not a
      turn: the camera matrix is R = Rx(x) Rz(z) Ry(y) (row vectors, 0x00054D48), so (x + pi, y + pi, pi - z) is the
      same rotation, and the blend goes to that set. DES_CUT_BLEND=0 = the lifted nearest key; DES_CUT_LOG=1 counts.
    - Result: tutorial opening 19 of 59 paired seconds -> 0 of 49 (and 0 of 42 on the final build: 2579 presents in
      43 s, none over 30 ms); Nexus intro 56 of 64 -> 0 of 64 (DES_CUT_BLEND=0 vs on, same build). DES_CUT_LOG:
      tutorial 2000 calls between keys, 1998 blended (2 Euler flips), 2 jumps kept (6.9 m and 7.1 m: real shot
      changes); Nexus 3000, 2994 blended (5 flips), 6 jumps kept. Game time 1.000; frame dumps show the same shots and
      framing. 30 fps: steps 30.0, game time 1.000; the cut clock sits a little off the keys there too, so 999 of
      1000 calls blend (sub-frame), 1 jump kept.
    - Agent review (3 lenses + adversarial verify): no correctness defects; 3 low findings about hypothetical track
      data (shot changes under the limits, scale steps) refuted; the scale-change guard was added anyway.
    - Not changed: the pre-rendered movies (cellSail, fix 71) are 30 fps MPEG-2 by nature.
81. **A folder updated but not rebuilt; the real internal resolution in the title; release downloads with the
    launcher (2026-11-03, GitHub #4 and #19):**
    - #4 (Ryzen 5600X + RX 6600: a black screen at the title that never moves on, "draws: 4", 50-60 fps): the
      folder had no DemonsSoulsLauncher.exe, which SETUP.bat / BUILD.bat build. So a newer ZIP had been unpacked
      over the folder and the game was never rebuilt: the OLD exe (before fix 71, cellSail a stub) ran with the
      NEW PLAY.bat, which turns movies on -- the stub never sends the events the game waits for, which fix 71
      recorded as a black screen forever.
    - PLAY.bat now checks for that. A successful full build (setup/build.py finish, not "BUILD.bat <target>")
      leaves copies of the patches it was made from in port/build_opt/built/; PLAY.bat's :stale compares them with
      patches/. Different or missing (a build from before this, or a rebuild that failed or was stopped) = not
      rebuilt: run directly it runs BUILD.bat first (no question; an up-to-date folder starts at once); from the
      launcher (no window) it runs BUILD.bat in a window of its own and WAITS (start /wait: the launcher keeps Play greyed out meanwhile; the
      window closes by itself after a good build and stays open on an error), then starts the game if the
      build is now current, else exits 1. PS3_REQUIRE_AVX2 is decided again after it (a rebuild may
      switch to the plain build). gotos, not ( ) blocks: a ")" in the folder's path would end a block. Not the
      copies patch_sync keeps (deps/ps3recomp/.ds_patched.patch, port/.lifted.patch): those are written when a
      patch is applied, before the compile, so a failed rebuild would have looked current (review finding).
    - Tested in a stand-in folder "t (x86) dir" (fake exe, a fake BUILD.bat doing what build.py does): current ->
      plays; built from old patches -> builds, plays, the next run is current; no record -> builds; build fails
      -> no game, tries again next time; launcher + stale -> build window, then the game;
      launcher + failing build -> no game, exit 1. (PLAY.bat as a whole does not survive a "&" in the folder's
      path -- it was already so; the README asks for a plain path.)
    - End-to-end test (a separate install: v6cd6887 set up from the disc, the v2026.11.03.4 release ZIP copied
      over it, its launcher started, Play pressed): the rebuild window came up but BUILD.bat failed with
      "ninja: error: manifest 'build.ninja' still dirty after 100 tries". ZIP times carry no time zone; the
      release job (and GitHub's own "Download ZIP") store UTC, so west of UTC every unpacked file is dated hours
      in the FUTURE (here 22:46 at 15:56, UTC-7) and CMake re-runs itself forever. Fixed twice: the release
      job writes every entry a day back (unix modes kept: linux/*.sh stay executable), and setup/build.py
      fix_future_times() dates any repo file more than 2 minutes in the future "now" before configuring (also
      covers Code-button ZIPs and the releases already out).
    - GitHub report: "No Python at ...\Python312\python.exe" from BUILD.bat -- the Python that made .venv was
      removed or upgraded. SETUP.bat now tests .venv and makes it again when broken; BUILD.bat does the same
      itself (py -3 / python >= 3.10, then pip install -r setup/requirements.txt) and only then builds.
    - Review (2 lenses + adversarial verify): 5 confirmed, all fixed -- the release job's out/ folder never
      created (no launcher would have been attached), the copies written before the compile, a second Play
      during the launcher's rebuild, AVX2 decided before the rebuild, CALL and a "^" / "%" in the path (CALL
      kept: rare, and & / ( ) in quotes are fine); 4 refuted.
    - #19 ("resolution changes do nothing", the title always 1280x720): works in the sandbox. Palace, 4x, a
      3840-wide window: the presented surface is 5120x2880 and the screen clearly sharper than 1x (hair, jacket,
      sword); character creation too (face, armour, text). The reporter's crops step in 3-pixel stairs on a 4K
      screen = a 1280x720 picture upscaled, so that run was at 1x (started without the launcher, or a build that
      did not take the update -- not confirmed). The title gave the game's framebuffer size only; with a scale it
      now reads "1280x720 x4 = 5120x2880" (rsx_live_draw_get_res_scale, rsx_null_backend.c). The perf log's info
      line also lists DES_RES_SCALE, LD_RES_SCALE, LD_RES_SCALE_SHADOW, DES_FULLSCREEN, DES_MOVIES and DES_CUT_BLEND
      (ppu_recomp_011.cpp), so a report shows the setting.
    - Releases: GitHub Releases (first v2026.11.03). .github/workflows/release.yml, on a published release or by
      hand for a tag: builds DemonsSoulsLauncher.exe on windows-2022 with the static C runtime (dumpbin: only
      system DLLs, or the job fails) and attaches DemonsSoulsRecomp-<tag>.zip (git archive of the tag + the
      launcher at its top level; game-file extensions refused). The same build here imports COMCTL32 / gdiplus / SHELL32 /
      USER32 / GDI32 / KERNEL32 only and holds no paths from the building PC.
82. **Nothing to install: SETUP downloads a portable Python, Git, compiler and RPCS3 (2026-11-03, GitHub report
    "Python is installed, but launcher cant read it" -- "pre-compile all executables to not rely on Python or
    Visual Code"):**
    - The game exe itself cannot be shipped (it is recompiled game code), so everything else comes without an
      installer or administrator rights, into deps\, and only when the PC lacks it:
      * Python: python.org's NuGet build 3.13.17 (15 MB, pinned sha256) into deps\python when no py -3 / python
        >= 3.10. Git: Git for Windows' MinGit 2.56.0.4 (40 MB, pinned) into deps\mingit, first on PATH for
        SETUP.bat and BUILD.bat. Both through setup/fetch.ps1 (.NET download, Get-FileHash, ZipFile into
        <dest>.part, renamed when complete), which SETUP.bat runs as a script block from environment variables:
        powershell -File treats the script's path as a wildcard pattern.
      * Compiler: no Visual Studio C++ tools (or no LLVM >= 17) -> offer_portable [Y/n] -> deps/.portable_compiler
        -> the xwin route (Linux's): LLVM 23.1.4's Windows .tar.zst (277 MB, pinned sha256) streamed through
        zstandard (zstd long mode, 2 GB window); only clang-cl, lld-link, llvm-lib, llvm-rc, llvm-mt and lib/clang/**
        (362 files, ~250 MB of 4 GB) into deps/llvm.part, renamed to deps/llvm when complete; Microsoft's CRT + SDK
        via xwin (~1 GB, Microsoft's license). The exe then imports only system DLLs (static CRT) -- the game needs
        no Visual C++ runtime either. A build_opt configured by Visual Studio before is reconfigured afresh.
        Delete deps/.portable_compiler (or set DS_XWIN=0) to go back to Visual Studio.
      * RPCS3: the latest RPCS3/rpcs3-binaries-win build (35 MB, the sha256 it publishes) into deps\rpcs3, unpacked
        by Windows' own tar.exe, else (Windows 10 / 11 before 23H2: tar without LZMA; the archive uses BCJ2, which
        py7zr cannot read) by 7-Zip's 7zr.exe 26.05 (600 KB, pinned). RPCS3 needs the Visual C++ runtime >= 14.40
        (it is built with 14.51): vc_runtime_ok reads the DLL versions (64-bit System32 / Sysnative) and offers
        winget Microsoft.VCRedist.2015+.x64.
    - SETUP.bat and BUILD.bat refuse a folder path with [ ] or & up front (CMake's file(GLOB) treats [ ] as a
      pattern and finds nothing; cmd breaks on &): "move or rename the folder".
    - Test switches: DS_TEST_NO_PYTHON / _GIT / _VS / _LLVM / _TAR, DS_ASSUME_YES (take [Y/n] defaults).
    - Tests: a release-style ZIP of the commit (files a day back, the CI-built launcher) unpacked with Expand-Archive
      into a new folder; game files hard-linked from a test install, no EBOOT.elf; SETUP with every DS_TEST_NO_*:
      Python + Git downloaded, .venv + packages, RPCS3 downloaded, EBOOT decrypted (sha256 = tested), ps3recomp
      cloned with MinGit, lifted, LLVM unpacked, xwin SDK, game + launcher built -- 6.5 minutes on the 16-core
      test PC -- then the launcher's Play started the game (50 fps on the 100 Hz test screen). Run twice (before and
      after the review fixes). The 7zr path on its own (DS_TEST_NO_TAR): same rpcs3.exe as tar's. fetch.ps1 from a
      folder "Games [BLUS-30443]": good download unpacked, a wrong checksum -> exit 1 and nothing left behind.
      BUILD.bat in "Games [BLUS-30443]" and "Tom & Jerry": the clear message.
    - Review (2 lenses + adversarial verify): 9 confirmed, 1 left (the launcher's Check for updates looks for git only
      on PATH: matters for git clones only, which have Git) -- fixed: Windows 10's tar cannot read the .7z, [ ] in
      the folder path, half-unpacked Python / Git / LLVM taken as installed, a Visual Studio build_opt refusing the
      portable compiler, an old Visual C++ runtime passing the check, a 32-bit Python checking SysWOW64.
83. **Updates without Git; the Visual C++ runtime without winget; checkouts owned by another account (2026-11-03,
    a tester's recording + the first Windows Sandbox test):**
    - The tester's perf.txt (GitHub #4): 59.4 fps, startup boxes and logos as normal, then 4 draws a frame for over three
      minutes from 40 s on = the attract movie: an exe from before fix 71 (no info host / cpu_clock lines) with the new
      PLAY.bat's movies on. He never rebuilt (the broken .venv stopped BUILD.bat) and cannot update: no Git.
    - Updates for a copy that is not a git clone: setup/update.py --check asks GitHub's releases/latest (latest=,
      current= from VERSION, note= lines from "New in this release", stdout forced to UTF-8 for the launcher's pipe);
      --install downloads the release ZIP, checks it against the sha256 digest GitHub publishes for the asset, copies
      the files under DemonsSoulsRecomp-<tag>/ over the folder through <file>.new + os.replace (waits for the closing
      launcher's exe, last resort renames it aside), never anything in KEEP (game, port, deps, .venv, saves, logs,
      launcher.ini, ...; any letter case), and writes VERSION last. The release job writes VERSION into the ZIP.
    - Launcher: Check for updates on a copy without .git runs update.py --check on a thread (git_run), shows the
      version and what is new, and on Yes its %TEMP% script runs update.py --install, then .\BUILD.bat, then opens
      the launcher again (script written as UTF-8 under chcp 65001, % doubled; .\BUILD.bat because call expands %
      again). A git clone keeps git pull (a clone without git.exe on PATH keeps the old message: copying release
      files over a checkout would block its next pull). An update that stopped is offered again in full (download +
      build). At start a copy without .git checks quietly once: a newer release shows in the status line. The status
      line shows VERSION. A broken .venv says "press PLAY: it repairs it" instead of "no internet".
    - Visual C++ runtime (RPCS3 needs it; Windows Sandbox has no winget): without winget, Microsoft's own
      vc_redist.x64.exe from https://aka.ms/vs/17/release/vc_redist.x64.exe, used only if Get-AuthenticodeSignature
      says Valid and the signer is Microsoft Corporation, run elevated (one Windows prompt; a "No" is reported as such,
      exit 1223; 3010 = restart Windows first); the DLL versions are checked again after.
    - Git's "detected dubious ownership" (a folder owned by another Windows account: shared into Windows Sandbox,
      made by an admin, copied from another PC): patch_sync trusts the kit's checkouts for the git commands the
      setup runs, through GIT_CONFIG_COUNT (command-line scope, which safe.directory honours), never globally.
    - Tests on a test install marked as the older v2026.11.03.5: Check for updates -> "Version v2026.11.03.6 is
      available" with the notes -> Yes -> the real v2026.11.03.6 downloaded and verified, copied over while the
      launcher closed, BUILD.bat, the launcher back -- 6-9 s, three runs; the status line at start: "New version ... is
      available", nothing when current. The update script in a folder "Démon's Sôuls 100%" with
      NoDefaultCurrentDirectoryInExePath=1. vc_redist: download + Microsoft signature check (a fake file refused);
      the elevated run is for the Sandbox re-test. safe.directory shows at "command" scope.
    - Review (2 lenses + adversarial verify): 12 confirmed, 3 refuted; fixed: notes characters crashing --check
      (cp1252 pipe), a clone without git on PATH overwritten, a stopped update only rebuilt, a declined prompt read as
      success, 3010 not explained, a broken .venv reported as no internet, OEM / % in the script's paths, ZIP names
      (drive letters, other top folders, KEEP in another case), a raw middle dot in the source. Left: a Code-button
      ZIP copy has no VERSION, so it is offered the newest release even if its own files are newer (rare).
84. **The build shows a progress line, not thousands of warnings (2026-11-03, the Windows Sandbox test: "should I
    stop it?"):**
    - The compile printed clang's warnings (-Weverything-style: unsafe-buffer-usage, padding, pre-C11 ...) by the
      thousand, harmless but alarming. setup/build.py run_quiet() runs cmake / ninja (both the Visual Studio and the
      portable route) with the output piped: one line updated in place, "compiling 47/322 (15%) - 3:12" (ninja's
      [n/N]; a ticker thread keeps the time moving while one big lifted file compiles for minutes); a failed step
      (FAILED:, ninja: error, CMake Error, or an error line) is printed in full above it; a failure with no line
      recognised prints the output's last 25 lines; the whole output goes to logs/build_last.txt.
      DS_BUILD_VERBOSE=1 = the old full output. No compiler flags change (that would recompile every install).
    - Tested: a fake build (5 steps, 2000 warning lines, a failed file) shows the progress and the failure only; a
      real incremental build on a test install printed 4 lines (log 4086).
85. **A click in the setup window paused it (2026-11-03, Windows Sandbox test: "stuck waiting for 30 mins"):**
    - Windows consoles have QuickEdit on by default: while text is selected (one click is enough) any program writing
      to the window is blocked until a key or a right-click ends the selection -- the build stood still for half an
      hour, then "zoomed right on" after the right-click. setup/build.py no_quickedit() clears ENABLE_QUICK_EDIT_MODE
      (with ENABLE_EXTENDED_FLAGS) on the console's input handle: called by build.py and setup.py at start and by
      update.py --install. Only that window; the full output is in logs/build_last.txt anyway (fix 84).
    - Tested in a real console window: mode 0x1F7 (QuickEdit on) -> 0x1B7 (off), the other flags kept.
86. **SETUP opens Redump's page when it needs the disc key (2026-11-03):**
    - An encrypted Redump image without a .dkey next to it: setup.py disc_key() opens REDUMP_PAGE
      (http://redump.org/disc/16199/, BLUS-30443 v1.00) in the default browser and says to copy its "Disc Key" line
      and paste it with Ctrl+V (right-click no longer pastes with QuickEdit off, fix 85). The key itself stays out of
      the kit (a decryption key in the repo would make it the thing handing the key out). DS_NO_BROWSER=1 = no browser.
    - Tested with the browser call intercepted: the page URL is opened, the hint printed, then the prompt.
87. **SETUP's RPCS3 decrypt and a crashing GPU driver (2026-11-03, Windows Sandbox test of v2026.11.03.9):**
    - rpcs3 --decrypt still builds RPCS3's render_creator, which creates a Vulkan instance to list GPUs before anything
      else. In Windows Sandbox (GPU-PV, host NVIDIA driver) a driver thread then faults in RtlAllocateHeap (log stack:
      RtlAllocateHeap / vk_icdNegotiateLoaderICDInterfaceVersion / DrvPresentBuffers = nvoglv64.dll) and RPCS3 dies
      with 0xC0000409 before EBOOT.elf is written. Intermittent: earlier sandbox runs decrypted.
    - setup.py step 2 now runs RPCS3 with VK_ICD_FILENAMES / VK_DRIVER_FILES pointing at a missing json and
      VK_LOADER_DRIVERS_DISABLE=*, stdin=DEVNULL (a failed decrypt asks for a KLIC on stdin), up to 3 tries, and prints
      the exit code + RPCS3.log path. On a normal (Medium-integrity) PC no vendor driver DLL loads at all (module list
      checked); EBOOT.elf matches. BUT the Vulkan loader ignores those variables in an elevated process, and Windows
      Sandbox runs everything as administrator, so the sandbox still crashed. Tried: a generated vulkan-1.dll stub next
      to rpcs3.exe (loads fine) -- RPCS3 refuses it ("module vulkan-1.dll was incorrectly installed", fatal box).
      README troubleshooting: in a sandbox/VM decrypt on another PC and copy EBOOT.elf in.
    - Test kit: scratch\DemonsSoulsTest.wsb has VGpu Disable (did not stop the crash in one run, unconfirmed);
      scratch\sandbox_games\rpcs3-diag.bat lists the DLLs RPCS3 loads inside the sandbox (not run yet).
88. **Latria 4-2 start 49.6 -> 55.4 fps on a 5800X: PPU reservation scans skipped for lines no PPU thread ever
    reserved; the SPU decrementer clock without divides (2026-11-03, 5800X + RTX 3070, 60 Hz):**
    - A god-mode tour of every archstone (DES_WARP_AT, two camera turns + a walk per stop) on fix 77: Latria 4-2's
      start (4,0,998, arrival view, 252.00 69.57 -91.00, ~910 draws) and Boletaria 1-1's (2,0,999, ~990 draws) were the
      heaviest views; the Shrine, Stonefang and most of the rest hold 60. The tour's first pass measured 38-42 fps at
      Latria 4-2, the same spot loaded directly ~50: that pass was the first visit ever (rsx_pso_worker 29%,
      shaders compiling) -- the same route again gives 49.6. Repro: DES_WARP_AT=140:4,0,998, stand still, 150-200 s.
    - Same shape as the Palace (fix 77): HighGraphics does ~13 ms of its own work per frame and waits 31-51% in the
      0x9023 usleep loop (func_00ACAFA8) for the SPU dispatcher ("spu job", 100%). Dispatcher RIP samples: lifted
      code 45%, spu_wrch 16, ppu_resv_break_line 8, mfc_do_transfer 5, mfc_channel_write 5, coh notify 3, decrementer
      (spu_host_ns: QPC + two 64-bit divides) ~2. Ceiling test (test-only switches, not kept): skipping
      ppu_resv_break_line 49.2 -> 53.7 fps, the divide-free clock 49.2 -> 51.9.
    - Not the cause: false sharing. reserve_addr sits in the cache line with cr / lr / ctr / xer, so the first try
      moved the reservation fields onto their own padded lines (needs both struct copies + lifted-code.patch): no
      change (51.3 -> 51.0 fps), break_line still 7.2% with samples spread over the loop. A registration log showed 30
      PPU contexts, no duplicates (the registry never shrinks, but threads are not re-registered): the cost is a
      30-entry scan on every SPU write to an SPU-reserved line, ~1M+/s.
    - Fix:
      - g_ppu_resv_filter (spu_coherency.c; block in ppu_context.h and ppu_recomp.h): 65536 bits, one per 128-byte line
        hash, set by every PPU reservation and never cleared. ppu_resv_break_line and ppu_resv_break return at once
        when the line's bit is clear (no PPU thread has ever reserved it, so none can hold it). The lifted lwarx /
        ldarx write `ctx->reserve_addr = ea` inline; in ppu_recomp.h (lifted-code.patch: its first hunk, no relift --
        the field is reached by name) reserve_addr is a C++ wrapper of the same size whose assignment marks the bit
        first (acquire load, seq_cst fetch_or only when missing), then stores. x86 makes stores visible in order, so a
        scan that sees the bit clear could not have seen the reservation either; the lwarx-vs-SPU-write window that
        predates this (no StoreLoad fence on either side) is unchanged. Runtime ppu_lwarx / ppu_ldarx mark too.
        The loader uses the filter only when ppu_recomp.h defines PPU_RESV_ADDR_T (the wrapper); with a stock lifter
        header (Linux boot smoke, check_ppu_scaffold.py) it scans as before.
      - spu_host_ns: QPC * 100 when QPC runs at 10 MHz (Windows 10+; exact, same value as before), else the old path.
    - A/B at Latria 4-2 (E = cdaca1d, H = this, H built by BUILD from the pre-fix state, i.e. the update path, code
      byte-identical to what was measured): 50.5 / 48.6 -> 55.6 / 55.1 fps, frames over 25 ms 89 / 130 -> 40 / 34,
      HighGraphics 87 / 88 -> 78 / 77%. Palace spot (60 cap): 59.0 / 58.8 -> 59.0 / 59.2, over 25 ms 15 / 17 -> 5 / 5.
      Tour on H (Shrine 3-1 x2, Latria 4-1 / 4-2, Boletaria 1-1, Stonefang 1-1, turns + walks): every stop 58.4-60 mean
      (Latria 4-2 58.4, Boletaria 1-1 59.4, was 43-49); no aborts or null calls. test_spu_coherency 195 passed, 0
      failed (its PPU lwarx cases mark the filter); test_mfc_resume_elements OK in all four modes. Review (3 lenses +
      verify): one real finding, fixed -- the loader called the filter with a stock lifter header (above).
    - Next: spu_wrch itself (16% of the dispatcher); the 30-context scan on lines the PPU does use could index by
      line instead; the intermittent abort at Boletaria 2-2 (2,0,996, -104 91 744: tid 35 null calls in the
      func_00CCBDD8 -> func_00CAD6F0 chain) also happens on builds before fix 77.
89. **The mouse in the menus: wheel, left click = confirm, right click = back (2026-11-03, asked for: "use the mouse
    for the HUD"):**
    - Before: in every menu LMB / RMB / MMB were still R1 / L1 / R3 (they switched tabs or did nothing), the wheel was
      not read at all, and the first click into the window was eaten to capture the mouse.
    - The game knows when a menu is open: the menu manager (*0x01B4B114) keeps one open flag per menu at
      menuMan+0x14+id*4, and func_00720F80 folds about 30 of them into a bitmask; the player's action buttons are
      ignored while (mask & 0x7FFF777F) != 0 (PadManipulator helpers, unit_001B615C). Measured: title screen 0x8,
      Start menu 0x40, inventory list 0x240, equipment 0x41, closed 0.
    - PORT PATCH (ppu_recomp_011.cpp, the per-step hook next to god mode): func_00720F80 on the saved registers (stack
      pointer 0x400 lower, menuMan null-checked first: the function does not; it only loads) ->
      ps3_host_menu_state(mask).
    - cellPad.c (souls layout), while (mask & 0x7FFF777F):
      - LMB = CROSS (confirm), RMB = CIRCLE (back); mouse side buttons X1 / X2 and PageUp / PageDown = L1 / R1.
        Shift / Ctrl stay R2 / L2, which switch the top tabs (Inventory -> Equipment ...).
      - Each wheel notch = one d-pad up / down press, held for PAD_WHEEL_HOLD (default 2) fresh reports and released
        for as many. Notches queue (at most 8); the queue is dropped when the mask changes (a submenu opened, backed
        out, closed) and on a confirm / back click, so leftover notches never move another menu's cursor. The wheel
        only counts while a menu is open, and is dropped when the window loses focus.
      - Uncaptured, a click counts only if it starts over the game window's client area, and a click in a menu does
        not capture the mouse (no wasted first click).
      - Mouse buttons across a menu's edges: one held when a menu opens stays dead in it (a held block does not become
        "back"); one pressed in the menu and still held when it closes stays dead until released (the click that
        closes a menu does not then attack); one held right through (block held while picking something up) works
        again when the prompt closes, as a pad's L1 does.
      - The same mask gates the game's own action buttons, so a click can never confirm and attack at once.
        Outside menus nothing changed. PAD_MENU_MOUSE=0 = off; DES_MENU_LOG=1 = the mask with times.
    - rsx_null_backend.c WM_INPUT: RI_MOUSE_WHEEL -> ps3_host_mouse_wheel (also from absolute pointers).
    - Test (PAD_TEST_WHEEL="<sec>:<notches>" new, LMB / RMB through PAD_KEY_SCRIPT, frame dumps): Start menu (0x40);
      LMB opened the inventory (0x240); 3 notches down moved the list cursor Crescent Moon Grass -> Full Moon Grass,
      2 up -> Half Moon Grass; RMB back to the tab bar, RMB again closed the menu (0); LMB in the game then cast the
      right-hand spell (R1) as before. 8 queued notches + RMB 0.3 s later: back out, no stray moves.
    - Agent review (2 lenses + adversarial verify): 2 confirmed (Shift read per queued notch instead of per notch;
      queued notches outliving the menu they were meant for) -> fixed as above; low findings fixed too (a click
      starting on the title bar, wheel counts saved up while nothing polled, a block held through a prompt, the
      pulse one report too long, keyboard-only L1 / R1). Shift + wheel = L1 / R1 was dropped: Shift is R2, which
      already changes the top tab the moment it is pressed. The hook itself (pointer, load-only callee, register
      restore) was checked clean.
    - Not yet: pointing (hover / click on an item). Every item rectangle is in MENU\menu.drb (1280x720 design space),
      but which stacked dialog has focus and the slide-in animations still need work.
90. **Latria 4-2 54.2 -> 55.2 fps on a 5800X, frames over 25 ms 42 -> 25: the watch list skipped on coherent stores
    (2026-11-03, 5800X + RTX 3070, 60 Hz):**
    - What the SPU dispatcher ("spu job", SPU image 2 here) does at the heavy spot, from per-channel counters: it
      consumes a PPU->SPU command queue whose control line is 0x01B51080 at ~1.8M commands/s (~32k per frame), 69%
      of them command 8 (one 32-bit store into a local-store table, handler 0x49C0) and 14% command 7. Per command:
      GETLLAR (4618), a PUTLLC of the unchanged line (4694), a 128-byte GET of the entry, a 16-byte PUT (C358), and
      when the queue is empty (0.87 times per command) RdEventStat + GETLLAR again (5120). The producer is
      HighGraphics: 98% of PPU coherent stores are to that line, ~1.75M/s, and an SPU holds the line at store time
      for only ~12% of them.
    - HighGraphics RIP samples (in exe): spu_coherency.c 16%, spu_coh_notify_write_ppu alone 9.6%, most of it in
      spu_coh_wake_watches -- a walk of the WAIT_SIGNAL watch list (6 nodes, each on a parked task's stack) on every
      coherent store, a dependent cache miss per node; the list head also shares a cache line with
      g_lockline_wait_ticks / g_lockline_contended.
    - Fix (spu_coherency.c): s_coh_watch_mask, one bit per watched line hash ((line >> 7) & 63) on its own 64-byte
      line, set by spu_coh_watch_add and rebuilt by spu_coh_watch_remove, both under the lock-line lock like every
      notifier. spu_coh_wake_watches returns at once when the line's bit is clear (no watch can have it).
    - A/B at Latria 4-2 (K = fix 88, L = this, alternating, 150-200 s): 55.1 / 53.2 / 54.3 -> 55.6 / 55.1 / 55.0 fps,
      over 25 ms 36 / 64 / 27 -> 23 / 28 / 25. test_spu_coherency 195 passed, 0 failed. test_spurs_task_signal and
      test_spu_workload_masked (the watch users) are POSIX-only and were not run here.
    - Tried and dropped: taking those stores off the lock-line lock. Design (agent audit of every lock holder, two
      designs, three adversarial reviews, none refuted): the PPU store announces itself in a per-line-hash counter
      (xadd, 8 padded buckets), takes the lock-free path only if the lock is free, no slot shows the line, nothing is
      unslotted and the watch bit is clear, then stores and retracts; every lock holder drains all buckets after
      acquiring and spu_coh_reserve_fast drains its line's bucket after its fence -- so no fast store overlaps a
      PUTLLC's compare-and-commit and no SPU-side change is needed. It worked (80% of the stores took the fast path;
      lock busy 10%, holder 9%), tests passed, but Latria 4-2 went 55.2 -> 54.4 fps (3 runs each), over 25 ms 29 -> 38.
      Each fast store still touches three lines the dispatcher writes (the bucket, the lock word, the slots), about
      what the lock cost, and every SPU lock taker now pays a miss on the bucket. The lock was not the expensive
      part; the queue line ping-pong between HighGraphics and the dispatcher is.
    - Next: fewer round trips per command rather than cheaper ones -- e.g. the dispatcher's empty-queue spin
      (GETLLAR + RdEventStat, 0.87 per command) re-reads the very line HighGraphics is writing.
91. **Keyboard / mouse button icons instead of the PS3 ones while the keyboard / mouse is used (2026-11-04, asked
    for: "mouse and keyboard icons for the HUD instead of the ps3 ones when mnk is used"; the art was shown and
    approved before this went in):**
    - Where the game's button art is: every in-text button (key guides, "Pick up" prompts, messages) is a FMG tag
      that draws an icon character (U+2460..) from the font page DSFont24_1000 (FONT\NA_ENGLISH\dsfont24.tpf; the
      glyph table dsfont24.ccm says which cell); the HUD equipment boxes take L / R / square from Menu08, the Start
      menu's tab bar its L1 / R1 plates and engraved L2 / R2 from Menu00 (MENU\menu.tpf). Three atlases cover them
      all, and as texture-pack keys (fix 60) they are CE4F0427E62376F5, 073A392EE5388F44 and 0740A345421ED259.
    - tools/kbm_icons.py redraws each PS3 button cell of those atlases as the key / mouse button it is on the souls
      layout: E / Space / R / F for cross / circle / square / triangle, a mouse with the left / right button lit for
      R1 / L1, Shift / Ctrl for R2 / L2, Tab and C for R3 / L3, arrow keys for the d-pad, a moving mouse for the
      right stick, a 4-key cluster without letters for the left stick (keys go by position: AZERTY = ZQSD), Enter /
      Backspace for START / SELECT, and Ctrl / Shift engraved next to the tabs. Letters are cut from the game's own
      serif font, plates / mice / arrows drawn in the colours of the game's own button art (cream lettering, gold
      arrows, dark plates). Built from the player's own disc: setup/build.py runs it after every successful build
      when textures\kbm\version.txt differs from the script's VERSION (installs Pillow into .venv if a setup from
      before this lacks it; a failure only leaves the PS3 icons). Each atlas is checked against the English
      BLUS-30443 one first (sha1 of the decoded texture); another disc's is left alone. textures\kbm is ignored by
      git: it is made from the game.
    - rsx_tex_pack.c: <dir>\kbm (LD_TEX_DIR, default textures) is scanned like replace\ into the same table under
      KEY ^ a salt; texpack_kbm_find(key), texpack_kbm_want() (LD_TEX_KBM=0 never, 1 always, else
      ps3_host_kbm_active()). LD_TEX_KBM_DIR = another folder.
    - rsx_live_draw.c: a texture cache entry remembers its kbm slot (kbm_idx) and which set it was made for
      (kbm_shown). tp_lookup takes the kbm file while it is wanted, else the replace\ file or the guest art. On a
      cache hit whose set no longer matches (read once a frame), tp_kbm_switch rebuilds the entry from the same
      content (no dump) and swaps it in; a kbm file still loading shows the PS3 art until tp_poll swaps it in.
    - cellPad.c: ps3_host_kbm_active() = no pad on port 0, or a key / mouse button / captured mouse used after the
      pad (the same "keyboard used last" that already decides mouse capture); kept while the window is in the
      background; 0 with PAD_NO_KEYBOARD. PAD_TEST_FAKE_PAD="<sec>:<hex mask>:<dur>,..." (TEST) also holds buttons
      on the fake pad.
    - Test (2x internal resolution, a save in the Nexus, fake pad + scripted keys): pad -> L / R / square on the
      HUD; C pressed -> both mice and R at once; L3 on the pad -> PS3 again; Start menu opened with Enter -> "arrows
      :Select E:Enter Space:Close", the pad -> "d-pad:Select cross:Enter circle:Close", a key -> keyboard again.
      The generated atlases are pixel-identical to the approved prototype's.
    - Not covered: "PRESS START BUTTON" on the title is plain text (no icon), and other languages' font pages
      (another FONT folder) keep the PS3 icons.
92. **"PRESS ENTER BUTTON" on the title while the keyboard / mouse icons are shown (2026-11-04, asked for: "since its
    plain text could you make it say press enter button instead if its mnk?"):**
    - The title's "PRESS START BUTTON" is FMG 77 ("menu other") id 30000 -- data, not code: menu.drb's T00_text dialog
      has a Text shape text_press_start_button with type byte 1 (FMG text), category 0x4D, id 0x7530, which
      DsMenuDlgTitle_vf24_007D9EE0 instantiates. The shape factory (Class018836B0_ctor_dtor_00F76308) looks the text
      up once through the menu host's GetText (Class01865EC0_vf07_0071C7E8 = func_005C2810(category) +
      func_005C2848(fmg, id)) and keeps the pointer at shape+0x30; the draw (Shared_vf02_00F9E0A8) hands that pointer
      to the font renderer on every frame. The pointer goes straight into the message manager's heap copy of the FMG
      (MSG MAN = *0x01B485D8, the FMG of category c at +4+c*4; groups {first index, first id, last id} at fmg+0x1C,
      count at +0xC, string-offset table at +0x14, made absolute by the loader func_005C3CD8; file size at +4).
    - PORT PATCH (ppu_recomp_011.cpp, the per-step hook after the fix 89 menu state): the string is found by the same
      group walk func_005C2848 does, and its 5 letters START are rewritten in place as ENTER while texpack_kbm_want()
      (the keyboard / mouse icons, fix 91: same choice, same LD_TEX_KBM) and back for the pad. "START" and "ENTER"
      are both 5 letters, so nothing moves. Written only when the choice changes and only when all 18 units plus the
      terminator still read one of the two (another language or a reload is left alone). The walk trusts a table
      only once +0x14 points inside the FMG (the loader stores the FMG pointer before it copies the file); while not
      found it looks again every 64 steps.
    - rsx_tex_pack.c: texpack_kbm_want() runs tp_ensure() first (the game thread can now ask before the renderer
      touched the texture pack).
    - Test (fake pad + scripted keys, title screen held): pad -> "PRESS START BUTTON"; C pressed -> "PRESS ENTER
      BUTTON" on the next frames; L3 on the pad -> START again; a key -> ENTER again. In game unchanged.
    - Agent review (2 lenses + adversarial verify): the walk matches func_005C2848; the two findings (a same-address
      reload, a walk during the load's copy) were judged impractical, and hardened anyway as above.
93. **Pointing in menus: the item under the mouse arrow is selected, a click confirms it (2026-11-04, asked for: "look
    into pointing now"; tried with a real mouse before release: "it works!"):**
    - Stage 0 (logging, kept behind DES_POINT_LOG=1): every menu item is a Null shape (cursor%d_%d, cursor_button0_%d,
      list_cursor%d_0, tab_cursor0_%d, button%d_%d) that the dialog draw loop (func_00F5F878, child draw at 0x00F6054C;
      func_00F5EAC0 for the alternate path) draws right after putting its world matrix at drawer+0x30 (Class01865C80):
      the GetRect output on the draw's stack (r1+0x19C / r1+0x174) through that matrix = its rectangle in 1280x720 menu
      units, at any internal resolution. Checked against frame dumps in 18 menus (title, profile select, Start tabs,
      inventory, item popup, equipment grid, R03 boxes, System, Options, Maiden talk / level-up, blacksmith Forge /
      Repair, archstone warp list + its confirm). Child name = **(child+0x1C), dialog names UTF-16BE (dlg+0xD4 variant).
      Focus: exactly one dialog asks the input gate func_00F55A18 with dlg+0xA0 bit 31 set (a list under a popup still
      draws and still calls the gate, with the bit clear). Key ids: down 0x81 (+0x79, also repeats), up 0x80 (+0x78),
      right 0x83 (+0x7A), left 0x82 (+0x7B), confirm 0x88, back 0x89, Start tab open / close 0x9D / 0x9E.
    - cellPad.c: while a menu is open a captured mouse is released (Windows arrow) and captured again on close (not after
      Esc). The arrow's place in menu units comes from ps3_host_client_to_guest (rsx_live_draw.c: the present records its
      letterbox, both branches) -- checked with the window resized to 1684x721. "Pointer authority": the arrow moved 3+
      client pixels in an unchanged client area; cleared by arrows / wheel / WASD / pad d-pad or sticks / leaving the
      picture / menu close / focus loss, and each menu opening starts without it, so a resting mouse never fights keys
      or pad. The click rule: the game publishes once per step what the arrow is over in the focused dialog; a left
      click on the selected item confirms, on another item selects it and confirms once the game has moved there, on no
      item does nothing (after waiting up to 3 reports for the state, which lags a fast move); a dialog without pointing
      support keeps the fix 89 click = confirm anywhere. A pointing-aware dialog with focus counts as a menu even with
      menu mask 0 (title, profile select).
    - PORT PATCH (ppu_recomp_086.cpp): the item table (filled by the draw hook, swapped per game step by des_pt_step from
      the ppu_recomp_011.cpp step hook; 8-step guard after a menu mask change for open / slide animations) and per-class
      steps that move the selection the game's own way, so its sound, help text and highlight follow:
      - Start tabs (048 func_0079BBF8 entry): param 0x4B via sound + func_0079B2C0(this, right, 0) steps;
      - R03 boxes (049 func_007BEA58 entry): +0x110 via vtable +0x8C / +0x90 (r4 = 0);
      - from the input gate (only the dialog with input): Listbox family (vf34 == 0x00781658 or SoulStatusList:
        +0x100 row of +0xF4 visible / +0x104 count / +0x108 top, vf33(up, 1) + vf35) = talk choices, level-up list,
        inventory, equipment lists, shops; ButtonGroup family (equipment grid, item popup, gestures: +0xF4 / +0xF8,
        vf33(1) + func_00F889E0 snap with UTF-16 names in free stack space); profile select +0xF8; warp list +0xFC;
        level-up confirm +0xF4 (OK only if byte +0x104); title +0xF8 (LOAD GAME only if byte +0xFE; func_007DAC50;
        its buttons belong to the EzMenuDialog beside it); System menu +0xFC via func_008AC558.
    - Tests (sandbox, scripted pointer PAD_TEST_CLIENT / PAD_TEST_POINT): each family hovered and clicked, keys / pad
      taking over, empty rows and disabled buttons ignored, title hover choosing LOAD GAME with the scripted move removed.
      Agent review (2 lenses + verify) -> pad / WASD clears, alt-tab, resize under the arrow, torn x / y, r4, Esc
      fixed; a list under the item popup moving with the arrow (found by a test) fixed by the input-bit check.
    - On by default; DES_POINT=0 = the fix 89 menu mouse only. Not covered (keys / wheel / click as before): Options rows
      (row and values in menu params), key config, the number spinner's value, face edit.
94. **Black screen under Wine / Proton without Microsoft's shader compiler: the depth snapshot shaders no longer
    call RWTexture2D.GetDimensions (2026-11-05, found on Ubuntu 24.04 with Wine 9.0 and WineHQ 11.0):**
    - Log: `[zetatrack] depth snapshot shader compile failed ... E5002: Type 'RWTexture2D<float>' does not have
      methods` (Wine 9.0; Wine 11.0: `E5005: Method 'GetDimensions' is not defined on type 'RWTexture2D<float>'`),
      then `[rsx] live-draw init FAILED -- falling back to the D3D12 backend`: the fallback backend draws a black
      window (title bar `draws: 19`). Wine's d3dcompiler is vkd3d-shader's HLSL compiler, which has no methods on
      RWTexture2D; with Microsoft's d3dcompiler_47 in the prefix (`play.sh --ms-d3dcompiler`) it compiled.
    - rsx_live_draw.c: depth_snapshot_compute and depth_argb_compute read their output size from 2 root constants
      (cbuffer b0, root parameter 2 of the depth snapshot root signature, set before each Dispatch from
      snapshot_w / argb_w * sc) instead of GetDimensions. Same result on Windows (Nexus frame dump matches the
      fix 93 one).
95. **Dash in slow motion above 150 fps: the game's "pressing into a wall" check assumed 1/30 s steps (2026-11-05,
    GitHub issues #23 "with unlimited frames the player runs slower than he walks" and #22, only walking at 165 fps):**
    - Measured with a new PORT DEBUG knob, DES_FIXED_STEP=<s>[@<sec>] (every game step is <s> seconds from <sec>
      seconds on, at any real frame rate, so short steps can be tested on any PC), and per-step positions
      (DES_WHERE=0.000001). Plain running is 3.67 m per game second at every step from 1/60 to 1/480 s, whatever
      the real frame rate or PS3_CLOCK_SCALE. The DASH (circle held) is 6.3 up to a 1/150 s step, then 2.96-3.16
      at 1/160, 1/200 and 1/240: a cliff, with every step exactly half as long. Stamina is not involved.
    - Found by diffing the character object between full-speed and slow dashes (DES_CHR_DUMP=<sec>:<file>, PORT
      DEBUG: the player character's 0x1000 bytes and 0x800 bytes behind every pointer in it): ChrCtrl+0x128, a
      speed factor, is 1.0 vs 0.5, next to the target speed at +0x12C (6.33 dash, 3.67 run). PPU_WWATCH on it (the
      character's address changes between runs; rerun until the dump matches) gives the writer, func_002EC2B8
      (ChrCtrl): while the move speed is over 5.0 (or a virtual-call value is over 0.3), it takes |position -
      previous position| x 30.0, i.e. metres per second at the PS3's 1/30 s step. Under 1.0 (moving under
      1 m/s = pressing into a wall) the factor goes x0.8 per step down to 0.5, otherwise x1.2 per step back up to
      1.0. At a 1/160 s step a dash speeding up through 5 m/s reads 0.94, and the factor locks at 0.5, because at
      half speed it keeps reading "stuck". 5 m/s x 30 x step = 1 puts the cliff at exactly 1/150.
    - Fix (port patch, ppu_recomp_025.cpp, des_wallslow_step): x (1 / step) instead of x 30, and the two rates as
      0.8^(step x 30) and 1.2^(step x 30). The check is the same in real time at any frame rate and unchanged at
      30 fps. DES_WALLSLOW_FIX=0 = the original.
    - Result (sandbox, a Nexus save, dashing across the floor): top dash speed 6.33 m/s at 1/30, 1/60, 1/160 and
      1/240; 1/160 and 1/240 cover the same ground per game second (1.5 s: 6.57 m both); at 60 fps the fix changes
      nothing measurable (6.15 vs 6.18 m). Dashing into the statue wall still slows down: 1.0 -> 0.5 in ~0.13 game
      seconds at both 1/60 (8 steps) and 1/240 (32 steps).
    - Also checked, because the check runs for every character: the Storm King's mantas (entity ids 400-411 in the
      map's MSB, the Storm King 822; DES_TRACK=<id>,... PORT DEBUG prints their positions with DES_WHERE) fly at
      9.02 m per game second at 1/60 and at 1/240, with the fix on and off, and their spikes fly and spawn per game
      second the same way. Not done here: the sound drifting above 60 fps (#16).
96. **Skip the intro: straight to PRESS START (2026-11-05, asked for: "a boot option that skips straight to the
    press start button screen and skips the intro logos and movie"):** DES_SKIP_INTRO=1, launcher checkbox
    "Skip the intro (straight to PRESS START)".
    - The boot sequence cannot simply be cut short, because it also sets the save system up (the autosave notice and
      "Checking SAVE DATA"). Its logos (Atlus, Sony, Japan Studio, FromSoftware, Havok) time themselves in game
      time, so the port fast-forwards them instead. Until the title screen is up, every game step is 0.25 game
      seconds (DES_SKIP_INTRO_STEP; at 1.0 the boot never reaches the title). CROSS and START are pulsed, 6 steps
      down and 6 up: CROSS confirms the autosave notice, START skips the opening movie as a player would. The
      window stays black meanwhile, then everything goes back to normal.
    - End marker: DsMenuDlgTitle_vf03 (func_007D9958, an empty function) runs on every frame of the title screen
      and on none before it (function counts, logos vs title). Its first call sets g_des_title_shown
      (ppu_recomp_049.cpp). The fast-forward runs in the step hook after the adaptive step (ppu_recomp_011.cpp).
    - Runtime: cellPad.c g_ps3_pad_inject (a button mask the port presses, PAD_SCRIPT encoding, ORed into port 0);
      rsx_live_draw.c g_ps3_present_black (while set, the swap chain buffer is cleared after the frame's copy, so
      the window shows black).
    - Result (sandbox, movies on, no input): the title screen after 293 fast steps, about 7 s after launch
      (before: about 38 s plus the opening movie); it stays on PRESS START without opening the menu; START ->
      LOAD GAME loads the save into the Nexus with the game clock normal again (0.995 game s per real s). The
      story movies still play: the movie player is not refused, only the opening movie is skipped by START.
97. **SETUP decrypts EBOOT.BIN without RPCS3 (2026-11-06, asked for after PR #30: "can we do the fetch keys for ours
    too? makes it easier on the end user"):**
    - Step 2 first runs `tools/fetch_keys.py` (from PR #30): it downloads RPCS3's `Crypto/key_vault.cpp` at a pinned
      commit, checks its SHA-256 and writes the PS3 application keys to a private per-user file outside the port
      folder (Windows `%LOCALAPPDATA%\demons-souls-recomp\keys`, macOS Application Support, Linux XDG data). Then
      `tools/decrypt_self.py` decrypts with those keys. SETUP asks before the download, as for every other.
    - The result must match the tested EBOOT.elf (`EBOOT_ELF_SHA256`) when EBOOT.BIN is the tested one. Otherwise,
      or when the download / decrypt fails, SETUP falls back to RPCS3 exactly as before. `--rpcs3 <exe>` still goes
      straight to RPCS3.
    - `decrypt_self.py` used pycryptodome. SETUP installs `cryptography`, so the same three AES modes (ECB, CBC,
      CTR with a 16-byte initial counter block) now go through it when pycryptodome is missing. Its `--selftest`
      round trip passes on `cryptography` alone.
    - Checked: the user's EBOOT.BIN decrypts in 0.24 s to EBOOT.elf sha256 `90eaa5e9...`, byte-identical to
      RPCS3's (the tested hash). SETUP step 2 in a scratch folder with only `cryptography`: "decrypted without
      RPCS3", "EBOOT.elf OK". With the download blocked (a dead proxy): "could not get the keys ... using RPCS3
      instead", no EBOOT.elf left behind.
    - What this removes for most players: the ~40 MB RPCS3 download, its Visual C++ runtime check, the Vulkan
      driver hiding and its administrator / virtual-machine crashes (NOTES fixes 81-83).
98. **Updates rebuild after Python was uninstalled (2026-11-06, reported on Discord by zackcage6: "since i
    uninstalled python and other stuff ... i thought the build will run the game normally cuz its recompiled
    already"):**
    - `.venv` points at the Python that made it. With that Python uninstalled, BUILD.bat (and so Play's rebuild
      after an update) remade `.venv` only from an installed Python or SETUP's portable `deps\python`; with
      neither it stopped with "Python 3.10 or newer is needed: run SETUP.bat".
    - SETUP's download of python.org's portable Python (the NuGet package, pinned SHA-256) moved to
      `setup\get_python.bat`; SETUP.bat and BUILD.bat both call it, so BUILD now fetches it itself.
    - Checked in scratch copies with no Python on PATH (no `py`, no `python`) and a `.venv` whose base Python is
      gone: BUILD.bat downloaded Python 3.13.17 into deps\python, remade `.venv`, installed the requirements and
      ran setup\build.py; also in a folder named "Demon's Souls test". SETUP.bat with DS_TEST_NO_PYTHON=1: same
      download, "Creating the Python environment", setup.py ran.
99. **Updates no longer send you to SETUP.bat, and a game left running is found (2026-11-06, zackcage6's videos:
    "could not update in place ... Run SETUP.bat", then "perf.txt - The process cannot access the file because it
    is being used by another process" and a launch that never starts):**
    - An update whose lifted-code.patch cannot be re-applied in place (a Code-ZIP copy has no git history to find
      the old patch in, or an update stopped halfway) made BUILD.bat stop with "Run SETUP.bat". setup/build.py
      `sync_patches()` now does that SETUP step itself: the game code recompiled from the extracted EBOOT.elf
      (`setup.step_lift()`, steps 4 + 5) or ps3recomp set up again (`step_ps3recomp()`). SETUP.bat is only asked
      for when there is no extracted game.
    - The old build with the new files stayed on a black screen and kept running without a window, so the next
      Play could not start (its recording file was taken). PLAY.bat now looks for a running DemonsSoulsRecomp.exe
      before it starts and asks whether to close it: a Y/N question, or a Yes/No message box when the launcher
      runs PLAY.bat without a window. It waits for the old one to be gone before clearing its cache. `findstr`,
      not `find`: with Git's usr\bin early on PATH, `find` is the Unix one and the check never matched.
    - Checked: the scratch release setup (relsetup) with its saved patch made unmatchable and its git history
      hidden: `sync_patches()` recompiled in 1 min 39 s and recorded the current patch. The running-game block
      (copied with a fake process name, so no real game could be closed): nothing running -> starts; running + N
      -> stops; running + Y -> the process ends, starts. The message box command parses and maps Yes/No right.
- **Test runs vs the user's game:** a test helper's `taskkill /F /IM DemonsSoulsRecomp.exe` killed the
  user's PLAY_DEMONS_SOULS.bat session (exit code 1). Test runs now live in DemonsSouls\testenv (own
  gamedata/saves and hdd0/hdd1, cwd there), end only their own process, run with AUDIO_MUTE=1,
  PAD_MOUSE=0 and no live keyboard.
- **Methodology:** every run is killed, and a run killed mid-copy leaves truncated files in hdd1/cache that the
  next run trusts -- this caused much of the run-to-run variation. Wipe hdd1/cache before every run
  (run_capture.ps1 does). `logs/ref_order.txt` = RPCS3's 148 distinct disc files in boot order; compare a run's
  last `/dev_bdvd` open against it.
- Debug switches added this round: SPU_ATOM_EAS=<ea,...> (per-task lock-line trace), SPURS_TASK_WATCH_ELF=<hex>,
  LFQ_DBG also dumps the polled queue line.

### Where it stands (2026-10-27)
New game -> Create Profile -> tutorial loads, the opening cutscene plays and gameplay renders the corridor
with the player at the game's own auto-exposure (fix 21) and full sharpness and fog (fix 22). Open problems:
- Sound and music work (fix 29: SPU thread receive_event + PS3_PRIO_START). 60 fps locked with correct game speed (fix 28;
  DES_FPS=30 for the original);
  shield fixed (fix 25). ATRAC on (real dev_flash) no longer stalls boot. Movies skipped (PS3_NO_SAIL). Live input works (fix 24,
  PLAY_DEMONS_SOULS.bat); not yet tested with a physical controller or a long play session.

### Readable copy (2026-10-27)
`readable\` is a separate, buildable copy of the lifted PPU code for reading (README.md there). Its tools
only read port\recompiled; the playable build is untouched.
- analyze.py follows register constants: TOC -> per-module constant pool in .data -> literal (SNC reaches
  strings through pools, not straight from the TOC). An epilogue's `rN = _cs_N` restore must not count
  as a new value, or every pool base is lost (fixing that took string refs 8.9k -> 25k). Strings are
  ASCII / UTF-16BE / UTF-8 / Shift-JIS (Japanese only if real kana/kanji: debug-menu labels).
- collect_names.py: 44,302 of 94,017 functions named -- Lua binding tables (687), Havok RTTI vtables,
  all vtables in 0x1852338-0x18C82A8, vptr-storing ctor/dtors, imports, assert strings, names\manual.tsv,
  and the game's own classes via Dantelion runtime classes: a class's static initialiser loads a
  pointer-to-static X, then the class name (ASCII + UTF-16) and stores both into *X (+0x1C/+0x20); the
  class vtable's slot 0 (GetRuntimeClass) and the runtime-class get-or-create function (stores the
  DLRuntimeClassImpl vtable) also use X. 685 game classes named this way (ExposureReaderEntity =
  vtable 0x01852800, checked by hand; all 747 named game vtables sit within 0x20000 of their
  initialiser). Methods inherited by more than 3 vtables are Shared_vfNN.
- Later the same day: 57,041 named. Runtime-class rule refined -- the class static is the .bss global
  with 2-12 users in the 40 lines before the name; DLRuntimeClassImpl<T> vtables always have 13 slots
  (others a user stores are the class's own, the largest one a constructor stores); manager classes
  have GetRuntimeClass in slot 2; a name must exist as UTF-16 too and be CamelCase; a vtable more than
  0x40000 from its initialiser is rejected. 840 game classes (PlayerIns, ChrIns, EnemyIns, ChrCtrl...),
  RuntimeClass_<T>_Init/_Get, Name_SubXXXXXXXX for tied classes without their own runtime class,
  thunks (11k) and single-caller helpers.
- Compilation units recovered (tools\units.py): every SNC unit has its own constant pool, so a
  function's most-read pool base names its unit; 2,052 of 2,110 pools are one contiguous run.
  readable\recompiled is now 2,589 unit files (PlayerIns.cpp, EzStateMapState.cpp, ...) + ppu_prelude.h;
  a method inherited by several vtables goes to the sharing class whose unit defines it.
  Full build 4m45s; same sandbox result.
- Control flow recovered (tools\structure.py, run by apply_names): shared return blocks copied to
  each exit, SNC's out-of-line else blocks moved back, then if/else, do-while, while, for(;;) with
  break/continue; compare shown as a comment on each branch. Gotos 471,344 -> 164,163; 80,956 of
  94,017 functions have none. Each rewritten function is checked by walking both control-flow graphs
  side by side; planted bugs (lost negation, then/else swap, dropped statement, do vs while) are caught.
  Bug found on the way: 'if (CR_EQ(cr7)) return;' (conditional blr, ~900 lines) ends in "return;"
  but is NOT an exit -- treating it as one copied blocks wrongly and the game hung at boot with
  black frames; the checker now has its own exit test. Sandbox: 30 fps, frame 6000 same tutorial
  spot, same null-write messages as the playable build. Leftover gotos: mostly loops SNC enters in
  the middle (goto to the test at the bottom).
- Control flow, round 2: loops entered in the middle (also behind an early-return guard) ->
  for(;;)/while; gotos to a block's join point -> inverted if, moving (or, up to 4 plain lines,
  copying) the code before the join into an else when that removes a goto; search loops (goto to
  the "found" code) -> break with the exit block copied in; out-of-line blocks reached from a nested
  if; guard clauses; dead code after return dropped. Gotos 164,163 -> 128,294; goto-free functions
  80,956 -> 85,260; for(;;) 2,174 -> 7,233; else 15,779 -> 21,212. Check caught one real bug
  (func_0036DA58): a new inner loop wrapped an outer loop's `continue`; loops are no longer formed
  around an outer break/continue. 14 planted bugs for the new rules all rejected. Left: rotated
  while loops whose `continue` jumps to the duplicated top test (needs a provably-idempotent
  re-compare) and big crossing diamonds. Regenerate 48 s, build exit 0; sandbox (own copy of
  testenv): 30.0 fps, frame 6000 same tutorial spot (mean diff 5.2, fog), null writes only from
  guest-fn 0x00A9DD58 like the playable runs (count varies run to run: 1-4).
- apply_names.py writes readable\recompiled with r3/f1/LR, cmpwi(cr7,..), CR_EQ(cr7), CALL() macros
  (readable.h, each expands to the lifter's text). readable\build.bat -> readable\build builds clean;
  the scripted new-game run matches the playable build (same 627 file opens, 30.0 fps, identical menu
  frames, same tutorial spot: readable\playable_vs_readable.png).

### Where it stood (2026-10-26, night)
Clean-cache runs reached ref pos ~100 at best; the particle assert (fix 14) and the Havok queue flood (fix 15)
were the two blockers.

### Where it stood (2026-10-26, late)
**First visible screen** (first_screen.png): the real "Now Loading" screen (Demon's Souls logo + soul orbs)
renders from frame ~120 while the game loads fonts, msg/param banks, sound banks, menus, nowloading*.drb,
envlight/lensflare and parts/*.partsbnd. Loading then stops after parts/bd_f_0000.partsbnd.dcx (99 opens;
RPCS3 continues with bd_f_0000_l, lg_*, common_ghost, fc_m_9900...) and the screen goes black ~frame 660.
Next: find what the 99th-open stall waits on (likely the dir=0 SPURS queue the game polls with
QueuePopBody, or another SPU workload), using the RPCS3 log as the reference.
Unresolved NIDs still seen: cellAudioSetPortLevel, cellSpursLFQueueDetachLv2EventQueue,
cellSpursTaskAttributeSetExitCodeContainer, sceNpBasicGetMatchingInvitationEntryCount.
