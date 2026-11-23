# Co-op (EXPERIMENTAL, incomplete, branch `coop`)

> **Status (2026-11-19): an experiment, not confirmed complete.** Nothing here is in a release, on `main`, or in
> a launcher. It has only run as two copies of the game on one machine (macOS), against the local test server,
> at 30 fps, mostly with scripted tests and one short play test by hand. Not tested: two machines, the internet,
> Windows and Linux builds of the changed network code, 60 fps, most of the game's areas and bosses. Expect
> things to break; the "known problems" below are the ones found so far, not all of them.

The goal is co-op like the "seamless co-op" mods for the later Souls games: friends join your world without soul
signs, stay through boss fights, and follow you between areas. It is built on the game's own white-phantom summon
and session code. FROM's servers are gone, so nothing here talks to them. Everything below is **developer-only and
untested end to end**.

**Run game tests for this on the RTX 3070 / 5800X PC.** On the 4090 PC, test runs keep tripping the power supply
(NOTES fixes 203 / 207). Never use the player's own install or saves: the runner copies a save into its own folders.

## How step 1 works

Goal: two copies of the game on one PC, where one summons the other.

- **Login.** With `DES_COOP` set, login state 6 (func_00199EF8) skips StartLogin and the "Logging into the server"
  box and goes straight to state 0x14 (logged in, online mode on). IsLoggedIn (func_00568400) answers yes and logs
  each caller once. The HTTP request queue's own gate (I+0x19C) stays shut, so the game sends no HTTP.
- **Host.** The per-step hook (func_0001B8D0 -> des_coop_step in `patches/lifted-code.patch`, ppu_recomp_011.cpp)
  does two things. First, with no session yet (netmgr+8 == 0), it calls func_00540D90(netmgr, f1 = *(TOC table -
  0x7F90)), the same call the sign-touch handler makes at 0x3A1218. Second, once the session key is valid
  (func_0052C2D8 -> func_00E00D10 -> func_00DFE110), it serialises the key exactly as the host branch of
  func_003A1700 does (join type -1, then func_00DFE2F0) and writes it to `<mailbox>\host_key.bin`
  (project/ds_coop.cpp).
- **Guest.** The same hook reads that file and runs the guest branch of func_003A1700:
  - a reader over the bytes (func_00A8B770 / func_00A8B580) reads the s32 join type;
  - SetJoinType func_002107B8;
  - func_00DFE9F8 + func_00DFF0D0 rebuild the key;
  - func_0053CFE8(netmgr, key) joins;
  - func_00DFE768 frees the key.
- **The network manager pointer** is `*(*(*(TOC - 0x79AC) - 0x7F98))`.
- **Rooms and P2P** go through the runtime's sceNpMatching2-over-psnr client to **our own test server**,
  `tools/coop/mini_psnr.py`. It handles rooms, members, room data, messages and members' P2P endpoints, written
  from our client code. `psnr_selftest.py` (57 checks) proves the byte layouts.
- **Switches:**
  - `DES_COOP=host|guest`
  - `DES_COOP_AUTO=1`: the host writes its key every second; the guest joins when a new key appears and retries
    every 3 s.
  - `DES_COOP_MAILBOX=<folder>`
  - F6 (host) / F7 (guest) do the same by hand.
  - The usual `PS3_NET_ONLINE=1 PSNR_SERVER=127.0.0.1 PS3_NP_ONLINE_ID=<unique> PS3_NET_P2P_PORT=<unique>`.

## Where it stands (2026-11-15, 4090 PC; runs cut short by power cuts)

- **Checked in a host-only run:**
  - the login is skipped, with no server box and no Offline Mode box;
  - the network comes up (cellNetCtl IPObtained, NP ONLINE, Matching2 context);
  - the copy says HELLO to mini_psnr;
  - the game loads and plays at 30 fps;
  - netmgr was found (0x11110870 in that run).
- **IsLoggedIn callers:** 0x0053E904, 0x0053E5E0, 0x0052E3F0, 0x003A5CC0, 0x0052E008.
- **The host had no session** (netmgr+8 = 0, state 0). That fits the original game, where the host only creates
  a session when it touches a sign. This is what the func_00540D90 call above is for. It is **built but never run**:
  the build that included it lost the edit, and the next run ended in a power cut.

## Step 1 works (2026-11-16, MacBook M2 Pro, two copies on one Mac)

`tools/coop/run_coop_test.sh <work> both 185 <a copy of gamedata>` (the macOS runner; same switches as the
PowerShell one, `COOP_FRAME_DUMP=1` keeps each copy's last picture): the host sees a blue phantom "Guest1" beside
it, the guest sees "Host1", each with name plate and health bar, and both stay in the room until the run ends.
Three things were missing:

- **P2P vports (runtime, libs/network/sysNet.c).** The game binds three SOCK_DGRAM_P2P sockets (vports 6001,
  6002 and one more) on the one P2P port. The runtime gave each its own UDP socket on that port, so the second
  bind failed, and the game left its room 20 ms after creating it, once a second (CREATE_ROOM / LEAVE_ROOM pairs
  in psnr.log, "host key not valid yet" for ever). Now one host UDP socket per copy (the "hub") owns the P2P
  port; datagrams go out as `dst vport | src vport | payload`, and a thread forwards what arrives to the guest
  socket bound to that vport (each has a loopback port of its own, so poll / select / nonblocking reads are
  unchanged). psnr's own probes and punches are taken out first, as before. Both ends must run this build.
  **Not built or run on Windows**: the thread and socket calls have `_WIN32` branches written blind.
- **Session creation** (func_00540D90, already on the branch) does return 1 once the sockets bind:
  `[coop] host create session -> 1`, `host key valid`, `host key written: 169 bytes`.
- **Where the guest arrives.** The join ran the game's own sequence on the guest (Lua: OnJoinMutiplay,
  OnBeJoinStart_White, SummonReloadStart, OnBeSummoned_White; then the map's scripts again as a client), but
  the reload put it at the map's origin, (0, 1.5, 0), outside the level: a real summon arrives at its sign, and
  this join has none. The host now writes its block and position to `<mailbox>/host_pos.txt` four times a second
  (coop_host_pos); a guest within 3 m of the origin while a join is under way is put 1 m beside it
  (des_player_place, in des_coop_step). It fires several times around the reload (15 in one run), until the
  guest is in the level.

Seen in the logs on the way, harmless so far: before both copies are in the game the guest joins and both leave
again three or four times (rooms 1-5 in psnr.log); the room made once both are in 1-1 is the one that stays.
The host's own Lua prints nothing for the join (no SummonSuccess_White).

Not checked: anything past standing next to each other -- movement and attacks as seen by the other side,
enemies, damage, death, a boss, leaving the area, 60 fps, two machines, a character other than a copy of the
same save in both copies (both loaded the user's first slot, body form; the guest became a phantom anyway).

## The seamless rules: a script module (2026-11-16, MacBook)

The user's goal: the player who joins is an equal player, not a phantom, and a boss killed together counts in both
saves. The game's multiplayer rules are all in its event scripts (global_event.lua), so they are changed there, the
way boss rush changes them: `tools/make_coop.py` builds `game_coop/` (hard links to game/) with
`tools/coop/coop.lua` appended to global_event.lua in every map's script bundle; the last definition of a Lua global
wins. Run it with `COOP_GAME=game_coop` in front of the test runner.

- **A. Body form (works).** InGameStart is wrapped: a client that arrives as a white phantom gets
  `proxy:SetChrType(10000, CHR_TYPE_LivePlayer)`. Both screens then show the guest in body form with a full HP bar
  (soul-form effect 101 is no longer applied), and the scripts' IsWhiteGhost() branches no longer apply to it.
- **B. Everybody stays after a boss (works).** BlockClear2_1 is replaced: no rating menu, no LeaveSession, no walk
  home; a soul-form player is revived as the lone-player version does, and after 3 s everyone takes
  GetSoloClearBonus and the death / reload locks are released. Tested with
  `COOP_TEST_KILL=800:50` (make_coop.py --test-kill: the host ForceDeads Phalanx 50 s after the guest is in its
  party, from the 1-1 start): OnEvent_4096 and BlockClear2 ran on both copies, souls 4102 -> 6384 on the host and
  -> 5738 on the guest, the host (soul form in this save) came back to body form, no LEAVE_ROOM in psnr.log, and
  both still saw each other 70 s later. If the kill comes while the guest is still loading in, its picture was
  black at the end of that run (one run, not looked into).
- **C. The kill in the guest's own save (works).** While in the host's world the guest's event flags are the
  session's, and the game's ways home roll them back (`proxy:SetFlagInitState(2)`, applied during the next map
  load). Those ways home only fire for phantoms: OnIrregularLeaveSession_1 and OnRoomDisappeared return at once
  for a live player, which the guest now is, so it would have stayed in a copy of the host's world. coop.lua's
  COOP_GoHome is the guest's way home (hooked into both; the host going away arrives as OnRoomDisappeared): note
  the boss kill flags set now that were not set when it arrived, roll back, SetSummonedPos / SetDefaultMapUid(-1)
  / WarpNextStageKick as the game does; the first g_Initialize at home sets those flags before the map's scripts
  read them.
  - Nothing in the scripts lives through that load: globals are gone after every load, and no event flag
    survives the rollback (tried 4131, 4999, 7999 ... 19999). So the notes are kept by the port:
    `print("COOPQ set <name> <n>")` / `print("COOPQ get <name>")`, answered by coop_lua_query in ds_coop.cpp; the
    scripts' print (func_00C02C78) pushes the answer with lua_pushnumber (func_00C9E5B0; lua_pushboolean is
    func_00C9E5D0, lua_pushnil func_00C9E590) and returns 1. In memory only.
  - Tested (`COOP_TEST_KILL=800:30 COOP_STOP_HOST_AT=160`, 250 s): arrival "bosses already dead in the host's
    world: none"; Phalanx killed; the host stopped; guest: "goes home (the host's room is gone); bosses killed
    together: 1", then at home "boss flag 4096 set in the guest's own world", at its old position, in body form
    with the 5738 souls. Then the guest's copy started again alone from its own save: "boss flags: 4096".
  - Open: a game closed while still in the session (the notes are in memory, and what that save holds is not
    known); the guest's own form if no boss died (it goes home in body form either way now); the demon's soul
    item; bosses with more flags than the kill flag (BR_B's clr lists); a guest that leaves by the menu.
- **D. The guest follows the host to another map (works for a warp).** What happened without it: the host's
  room disappears on its map change, and every join after that failed (OnFailedJoinSession on the guest, the host
  re-creating its room each time, 37 rooms in a run). Two causes:
  - A join only works with both players in the same map. The port now knows both (the guest's block from the
    step hook, the host's from host_pos.txt, fresh for 4 s) and the guest does not try to join while they
    differ. coop.lua asks `COOP_Get("follow")` from a check registered at every load on its own: 1 = the host is
    in another map, and the guest goes there by itself (`proxy:WarpNextStage(area, block, 0, 0, point)`, point
    999 for a world's first map, 998 - block otherwise: the archstone after that block's boss); then the join
    brings it to the host as before.
  - The summon only takes a player in soul form: after the first session the guest is a live player (step A),
    and the join failed even in the same map. A guest on its own between two of the host's maps is put back in
    soul form (COOP_Joinable); arriving makes it a live player again. At home it gets the form it had before
    the first join, or body form if a boss died.
  - OnRoomDisappeared therefore no longer sends the guest home at once: it notes the bosses killed together so
    far, waits, follows; `follow` = 2 (no fresh host position for a minute) sends it home with the credit.
  - A summoned player is a white phantom at InGameStart whether or not IsClient() is true yet (it was false in
    one run, and the "alone" branch then broke the session): arrival is IsWhiteGhost(), alone is "not white and
    not in a party".
  - Tested with `COOP_ENV_A="DES_WARP_AT=125:3,1,999"` (the host warps from 1-1 to the Shrine of Storms with
    the guest in its party): "following the host to map 3,1, point 999", one join, no failed join, both screens
    show both players in the Shrine. The boss test (kill, host stops) still ends with the flag in the guest's
    world, now after the one-minute wait, and "home after a boss: body form".
  - Known problems: (1) the guest's screen showed "Host1 has left." (event text 20001020), a box that waits
    for OK, at every host map change. It is not opened by the scripts (OnLeavePlayer and LeaveMessage never run;
    the id is not built as a constant anywhere in the lifted code either) and `proxy:CloseMenu()` leaves it up
    although IsShowMenu_InfoMenu() sees it. Worked around: while the guest waits for the host, and at 1 / 3 / 6 /
    10 s after it arrives, an info box on screen makes the port press OK (coop.lua COOP_CloseLeaveBox ->
    `COOP_Set("press_ok", 1)` -> coop_pad_inject holds CROSS for 6 steps through g_ps3_pad_inject). In the follow
    test it pressed three times while waiting and the box was gone on arrival. Any other info box that happens
    to be open at those moments gets the same press.
    (2) The guest's
    souls went up at the load it makes by itself on the way to the host (4102 -> 6361 or 8611; the step hook
    now logs every change, "[coop] souls a -> b"): once, natively, between the map's Second_Initialize and
    g_second_Initialize, with no script of ours in between, with or without the switch to soul form and with or
    without ResetSummonParam. g_Initialize's `proxy:AddBlockClearBonus()` ("souls not obtained yet") is the
    suspect; the cause is not known. Worked around: coop.lua says `souls_keep` 1 before that warp and 2 at the
    next InGameStart, and the step hook puts the count back ("[coop] souls put back: 6361 -> 4102",
    coop_souls_fix in ds_coop.cpp). The real rewards are untouched: with Phalanx killed the guest's log reads
    4102 -> 4786 -> 5738 and the host's 4102 -> 5432 -> 6384, and going home adds nothing.
    (3) The guest goes to the host's map in its own world first:
    with the boss of that block alive in its world, the archstone point is inside the arena for the seconds
    until the join. (4) Walking into another block of the same world, a fog gate and the Nexus are not tested.
- **A guest that dies** (first seen in the user's own play test, then with `COOP_ENV_B="COOP_TEST_DIE=25"` and
  `COOP_GOD=0`): the game's death handling runs (OnEvent_4000, souls 4102 -> 0), the guest drops out of the
  session, and the follow logic brings it back by itself about 5 s later, beside the host, in body form. The host
  got "Guest1 has left." each time; it now has a watch of its own (COOP_HostWatch, registered at every load):
  for a few seconds after its party empties, an info box gets the same OK press. Checked: no box on the host
  after the guest's death and return.
- **The guest stays in the session when it goes down** (coop.lua step E). The drop was the death's own map load
  (SoloPlayDeath_2: WarpNextStageKick), and a map load takes a client out of the session. Tried first: no load,
  and the dead guest brought back in place (SetAlive, SetHp, RequestFullRecover, animation 6100). The session
  held and IsAlive was true again, but the character could not move any more (a walk scripted with
  PAD_STICK_SEQ and logged with DES_WHERE=2: 5 m before the death, 0 m after). What works is not dying: an
  arriving guest is put in the game's own dead mode (`SetDeadMode(10000, true)`, the tutorial's: health stops
  at 1), a check every few steps (`GetHpRate(10000) <= 0.004`; `OnCharacterHP(.., 0.0)` never ran) starts
  COOP_GuestDown: "YOU DIED", DisableMove + EnableInvincible for 4 s (`COOP_DOWN_SECS` in the copy's
  environment changes it), then `set regroup 1` (the step hook puts the guest next to the host:
  coop_guest_host_pos returns 2), full health, the stand-up animation, and the check again. Tested with
  `COOP_GOD=0 COOP_ENV_B="COOP_TEST_DIE=25 DES_WHERE=2 PAD_STICK_SEQ=..."` (the test sets the health to 0, as
  damage does): down at 15.9, 67.9, 89.2, held there through a scripted walk, up at the host's 11.9, 67.9, 86.7
  with a full bar, walking again afterwards (to 17.3), souls 4102 throughout, and no LEAVE_ROOM / JOIN_ROOM in
  psnr.log after the first join. Not tested: real damage from an enemy, a fall (a kill plane may get past dead
  mode: then it is the game's death as before, out and back in; `COOP_TEST_FORCE=1` tests that path), the guest
  going down in a boss fight. The guest loses nothing when it goes down: no souls, no body form. That is a
  choice, not a limit (there is no bloodstain it could go back to).
- **The host dies** (`COOP_ENV_A="COOP_TEST_DIE=160"`): the game's own death, with its reload. The guest gets
  HostDead, the room is made again, and the follow logic brings the guest back by itself; in the one test it
  took two rounds (rooms 5 -> 6 -> 7 in psnr.log, about 10 s) and the host's OK press ran 14 times in between.
  At the end both stood at the archstone, the host in soul form with 0 souls, the guest with its 4102.
- Not looked at yet: the session lock BlockClear2 sets (LockSession: it may refuse a new join after a boss),
  black phantoms, a guest in body form joining for the first time.

## The Windows build, under Proton (2026-11-23, RTX 3070 PC, Linux)

The 4090 PC cannot run two copies (its power supply cuts out), so the Windows build was tested on the 3070 PC,
which runs Linux: the same DemonsSoulsRecomp.exe through Proton (UMU-Proton 11, Wine's Winsock). That runs the
`_WIN32` branches of the P2P hub in sysNet.c for the first time; real Windows is still not tested.

- **Runner.** Proton starts one launch at a time (a second `umu-run` waits until the first ends: the guest only
  started as the host was stopped), so one launch runs a master batch file that starts the host's batch, waits
  70 s (`ping -n 71 127.0.0.1`; Wine's `choice /t` does not wait) and starts the guest's. Each copy's settings are
  `set` lines in its own batch. The runner is a dev script kept outside the repo, like coop_run.ps1.
- **The save.** The sandbox save's first slot is a character in the tutorial (m08). Scripted d-pad presses on the
  profile list did not work (the first DOWN moved the cursor up, from slot 1 to 4; later presses were ignored;
  the stick did nothing), so both copies load slot 1 and `DES_WARP_AT=70:2,0,999` takes them to 1-1.
- **Fix: a guest in body form never got in.** Both copies arrived in 1-1 in body form. Every join reached the
  server (JOIN_ROOM, MEMBER_JOINED) and failed 1.2 s later (OnJoinMutiplay -> OnFailedJoinSession on the guest,
  LEAVE_ROOM), every 6 s to the end of the run. COOP_Joinable (back to soul form) only ran after a first session.
  coop.lua now also calls it on the guest's first time alone at home, after noting its form (`orig`), which going
  home restores. With that the guest joins and stays.
- **Checked (all with that fix, 30 fps, god mode, the host and guest from the same save):**
  - join: one JOIN_ROOM once both are in 1-1 and no LEAVE_ROOM after it until the run ends (3 min); OnBeSummoned_White,
    "white phantom -> live player", "guest arrived"; the host's screen shows "Guest1" beside it in body form with
    its health bar, the guest's shows "Host1". The P2P hub's Windows branches work under Wine.
  - stay after a boss (`make_coop.py --test-kill 800:50`): Phalanx killed, OnEvent_4096 / BlockClear2 on both,
    "BlockClear2_1: boss 800 dead, staying together", souls 0 -> 2282 (host) and 0 -> 1636 (guest), still together.
  - follow (`DES_WARP_AT=...;230:3,1,999` for the host): "following the host to map 3,1, point 999", one JOIN_ROOM
    13 s after the host's warp, both screens in the Shrine of Storms with each other.
  - the guest goes down (`COOP_TEST_DIE=25 DES_GOD=0` for the guest): "the guest is down: it stays with the host",
    "the guest gets up (alive true, in party true)" beside the host, no LEAVE_ROOM.
- Still seen: before both copies are in 1-1 the guest joins and leaves two or three times (it joins while still
  in the title screen or the tutorial); "the 'has left' box is up: OK pressed" many times on the guest meanwhile.
  Not tested here: real Windows, two machines, 60 fps, real enemy damage, the host's death.

## Next steps

1. Host alone: `tools\coop\run_coop_test.ps1 -Work C:\coop_test -Who host -Save <a copy of a gamedata folder>`.
   Look for `[coop] host create session -> 1`, CREATE_ROOM in psnr.log, then `host key written: N bytes`.
   - If func_00540D90 returns 0, it stopped at func_00E43640 (online check) or func_00DFC008(netmgr+8). Trace
     which one.
2. Both copies, `-Who both`. The host should be in body form and the guest in soul form (only a soul can be a
   white phantom), both in the same world, e.g. 1-1. The default PAD_SCRIPT only loads the first save slot; drive
   the menus or pick the save so the two copies load different characters.
   - **Guest log:** `guest join: key N bytes`, then `join call returned 1`.
   - **psnr.log:** JOIN_ROOM, with MEMBER_JOINED pushed to the host.
   - **Lua prints:** OnBeSummoned_White / SummonSuccess_White.
3. Then the seamless rules, one at a time:
   - summon without a sign or soul-form limits;
   - stay after a boss;
   - re-summon automatically after the host changes area.
4. Then a launcher Host / Join, two real PCs (NAT; relay?), and separate co-op saves.

**Risks:**
- The guest may already hold an NR2 handle (func_0053CFE8 refuses then); see the refusal checks at 0x53D0BC-0x53D0F4.
- The Lua summon handlers may expect sign-server fields filled in (this+0x50 / +0x60).
- 60 fps sync: test at 30 fps first.

## Editing the lifted code: the order matters

1. `python tools\coop\lifted_patch_tool.py pristine ppu_recomp_NNN.cpp` saves the file as lifted.
2. Edit `port\recompiled\ppu_recomp_NNN.cpp`.
3. `python tools\coop\lifted_patch_tool.py regen ppu_recomp_NNN.cpp` writes the section into
   patches/lifted-code.patch and checks it.
4. BUILD.bat.

Do step 3 **before** building. When the patch differs from what was applied, BUILD re-applies it and overwrites
any edit that is not in it. That is how the session-create edit was lost once. Run the tool from the repo root;
its working files (lifted game code) are git-ignored and must never be committed.
