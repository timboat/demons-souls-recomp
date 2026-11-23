-- Demon's Souls co-op (EXPERIMENTAL, incomplete: docs/COOP_DEV.md): the event-script module. tools/make_coop.py appends it
-- to global_event.lua in every map's script bundle of game_coop/. It redefines the game's own multiplayer handlers:
-- the goal is the "seamless co-op" of the later games' mods -- the player who joins is an equal player, stays through
-- boss fights, and a boss killed together counts in both saves.
-- Everything it does prints a "[coop]" line (DES_LUA_PRINT=1 shows them in the log).

-- Step A: the guest is a player in body form, not a blue phantom. The join itself is still the game's white-phantom
-- summon (the only way in); once the guest has loaded into the host's world, its character type is set to "live
-- player", so the scripts' IsWhiteGhost() branches (soul-form HP, the walk home after a boss) no longer apply to it.
COOP_InGameStart = InGameStart;
function InGameStart(proxy, param)
	-- (a summoned player is a white phantom at this point whether or not IsClient() says so yet: it does not always)
	if proxy:IsWhiteGhost() == true then
		print("[coop] guest: white phantom -> live player");
		proxy:SetChrType(10000, CHR_TYPE_LivePlayer);
	end
	COOP_InGameStart(proxy, param);
	print("[coop] InGameStart: client " .. tostring(proxy:IsClient()) .. " host " .. tostring(proxy:IsHost()) ..
	      " live " .. tostring(proxy:IsLivePlayer()) .. " white " .. tostring(proxy:IsWhiteGhost()) ..
	      " party " .. tostring(proxy:IsInParty()));
end

-- Step B: a boss dies and everybody stays. The game's BlockClear2 (event 4050, sent to every player when a boss
-- dies) ends five seconds later in BlockClear2_1: with friends in the party it opens the "rate your helpers" menu,
-- then leaves the session and walks the phantoms home. Here it does what a lone player's version does -- revive a
-- soul-form player, take the real clear bonus (souls and the demon's soul, GetSoloClearBonus), let death and
-- reloads happen again -- and nobody leaves.
function BlockClear2_1(proxy, param)
	print("[coop] BlockClear2_1: boss " .. tostring(ClearBossId) .. " dead, staying together");
	if proxy:IsGreyGhost() == true then
		if proxy:IsAlive(10000) == true then
			proxy:RevivePlayer();
			proxy:SetReviveWait( false );
		end
		proxy:SetEventFlag( 15112,true );
		proxy:SetEventFlag( 15113,true );
		proxy:SetEventFlag( 15114,true );
		proxy:SetEventFlag( 15115,true );
		proxy:SetEventFlag( 15116,true );
		proxy:SetEventFlag( 15117,true );
		proxy:SetEventFlag( 15118,true );
		proxy:SetEventFlag( 15119,true );
		proxy:EraseEventSpecialEffect( 10000, 101 );
	end
	proxy:NotNetMessage_begin();
		proxy:OnKeyTime2( 4050, "COOP_BlockClearDone", 3.0, 0, 6, once );
	proxy:NotNetMessage_end();
end

function COOP_BlockClearDone(proxy, param)
	proxy:SetSubMenuBrake( false );
	proxy:GetSoloClearBonus(ClearBossId);
	proxy:SetEventFlag(4047, false);
	proxy:SetEventFlag( 4000, false );
	if proxy:IsAlive(10000) == true then
		proxy:SetEventFlag( 4067, false );
	end
	print("[coop] boss " .. tostring(ClearBossId) .. ": bonus taken, nobody left; client " .. tostring(proxy:IsClient()) ..
	      " party " .. tostring(proxy:IsInParty()) .. " live " .. tostring(proxy:IsLivePlayer()));
end

-- DEV TEST (tools/make_coop.py --test-kill <character id>:<seconds>): the host kills that character that many
-- seconds after a guest is in its party, so a boss's death can be tested without fighting it. COOP_TEST_KILL is
-- set by a line make_coop.py puts after this module; it is nil in a normal build.
function COOP_TestKillCheck(proxy, param)
	return proxy:IsInParty() == true;
end
function COOP_TestKillArm(proxy, param)
	print("[coop] test: a guest is here; character " .. tostring(COOP_TEST_KILL) .. " dies in " .. tostring(COOP_TEST_AFTER) .. " s");
	proxy:NotNetMessage_begin();
		proxy:OnKeyTime2( 9971, "COOP_TestKill", COOP_TEST_AFTER, 0, 0, once );
	proxy:NotNetMessage_end();
end
function COOP_TestKill(proxy, param)
	print("[coop] test: ForceDead " .. tostring(COOP_TEST_KILL));
	proxy:ForceDead(COOP_TEST_KILL);
end
COOP_InGameStart_B = InGameStart;
function InGameStart(proxy, param)
	COOP_InGameStart_B(proxy, param);
	if COOP_TEST_KILL ~= nil and COOP_Get("mode") == 1 then
		proxy:NotNetMessage_begin();
			proxy:OnRegistFunc( 9970, "COOP_TestKillCheck", "COOP_TestKillArm", 30, once );
		proxy:NotNetMessage_end();
	end
end

-- Step C: a boss killed together counts in the guest's own world.
-- In the host's world the guest's event flags are the session's. The game's ways home roll them back
-- (proxy:SetFlagInitState(2), applied during the next map load), and they only fire for phantoms:
-- OnIrregularLeaveSession_1 and OnRoomDisappeared do nothing for a live player, which the guest now is, so without
-- this the guest would stay in a copy of the host's world when the session ends. COOP_GoHome is the guest's way
-- home: note which boss kill flags were set while it was there, roll back, go back to where it was summoned from;
-- the first load at home sets those flags in the guest's own world.
-- Nothing in the scripts lives through that load -- not globals, and no event flag in any range survives the
-- rollback (tried: 4131, 4999, 7999 ... 19999) -- so the notes are kept by the port: COOP_Set / COOP_Get
-- (print("COOPQ ...") answered by project/ds_coop.cpp).
-- The kill flags, as bossrush.lua's BR_B lists them: Phalanx, Tower Knight, Penetrator, False King, Adjudicator,
-- Old Hero, Storm King, Fool's Idol, Maneater, Old Monk, Leechmonger, Dirty Colossus, Maiden Astraea, Armor Spider,
-- Flamelurker, Dragon God.
COOP_BOSS_FLAGS = {4096, 4224, 4360, 4480, 4756, 4895, 4992, 5123, 5251, 5380, 5650, 5770, 5889, 6174, 6272, 6400};
COOP_BOSS_N = 16;

function COOP_Set(name, value)
	print("COOPQ set " .. name .. " " .. tostring(value));
end
function COOP_Get(name)
	local v = print("COOPQ get " .. name);
	if v == nil then return 0; end      -- not a co-op run: nobody answers
	return v;
end

function COOP_BossFlagsText(proxy)
	local s = "";
	for i = 1, COOP_BOSS_N do
		if proxy:IsCompleteEvent(COOP_BOSS_FLAGS[i]) == true then s = s .. " " .. COOP_BOSS_FLAGS[i]; end
	end
	if s == "" then s = " none"; end
	return s;
end

-- At the start of every map load, before the map's own scripts look at the flags: a guest just back home gets
-- the bosses killed together.
COOP_g_Initialize = g_Initialize;
function g_Initialize(proxy)
	if COOP_Get("home") == 1 and proxy:IsClient() == false then
		for i = 1, COOP_BOSS_N do
			if COOP_Get("credit" .. i) == 1 then
				proxy:SetEventFlag(COOP_BOSS_FLAGS[i], true);
				COOP_Set("credit" .. i, 0);
				COOP_Set("revive", 1);       -- a boss kill gives the body back, as it does for the host
				print("[coop] home: boss flag " .. COOP_BOSS_FLAGS[i] .. " set in the guest's own world");
			end
		end
		COOP_Set("home", 0);
	end
	COOP_g_Initialize(proxy);
end

COOP_InGameStart_C = InGameStart;
function InGameStart(proxy, param)
	local arriving = (proxy:IsWhiteGhost() == true);
	COOP_InGameStart_C(proxy, param);
	if arriving == true then
		COOP_Set("guest", 1);
		for i = 1, COOP_BOSS_N do
			local dead = 0;
			if proxy:IsCompleteEvent(COOP_BOSS_FLAGS[i]) == true then dead = 1; end
			COOP_Set("base" .. i, dead);
		end
		print("[coop] guest arrived; bosses already dead in the host's world:" .. COOP_BossFlagsText(proxy));
	end
	print("[coop] loaded: client " .. tostring(proxy:IsClient()) .. " guest " .. COOP_Get("guest") ..
	      " type " .. tostring(proxy:GetLocalPlayerChrType()) .. " boss flags:" .. COOP_BossFlagsText(proxy));
end

function COOP_GoHome(proxy, why)
	local n = 0;
	for i = 1, COOP_BOSS_N do
		if proxy:IsCompleteEvent(COOP_BOSS_FLAGS[i]) == true and COOP_Get("base" .. i) ~= 1 then
			COOP_Set("credit" .. i, 1);
			n = n + 1;
		end
	end
	print("[coop] guest goes home (" .. why .. "); bosses killed together: " .. n ..
	      "; flags in the host's world:" .. COOP_BossFlagsText(proxy));
	COOP_Set("guest", 0);
	COOP_Set("home", 1);
	proxy:SetEventFlag(4047, true);
	proxy:SetLoadWait();
	proxy:SetFlagInitState(2);
	proxy:SetSummonedPos();
	proxy:SetDefaultMapUid(-1);
	proxy:WarpNextStageKick();
end

COOP_OnIrregularLeaveSession_1 = OnIrregularLeaveSession_1;
function OnIrregularLeaveSession_1(proxy, param)
	if COOP_Get("guest") == 1 then
		COOP_GoHome(proxy, "the session ended");
		return;
	end
	COOP_OnIrregularLeaveSession_1(proxy, param);
end

-- The host going away reaches the guest as OnRoomDisappeared (the server's MEMBER_LEFT).
COOP_OnRoomDisappeared = OnRoomDisappeared;
function OnRoomDisappeared(proxy, param)
	if COOP_Get("guest") == 1 then
		if proxy:IsCompleteEvent( 4047 ) == true then
			print("[coop] OnRoomDisappeared: a reload is already under way");
			return;
		end
		COOP_GoHome(proxy, "the host's room is gone");
		return;
	end
	COOP_OnRoomDisappeared(proxy, param);
end

-- "<name> has left." is a dialog that waits for OK; in a co-op run the other player comes and goes with every
-- map change, so it is not shown (the original still runs for the local player's own leaving).
COOP_OnLeavePlayer = OnLeavePlayer;
function OnLeavePlayer(proxy, param)
	if COOP_Get("mode") ~= 0 and param:GetParam3() ~= proxy:GetLocalPlayerId() then
		print("[coop] OnLeavePlayer: the other player left (no dialog)");
		return;
	end
	COOP_OnLeavePlayer(proxy, param);
end

-- Step D: the guest follows the host to another map.
-- A join only works with both players in the same map, so when the host has gone somewhere else the guest first
-- goes to that map by itself, to the archstone point of that block, and the port's automatic join then brings it
-- to the host as before. The port (ds_coop.cpp) knows both maps and answers COOP_Get("follow"): 0 wait, 1 the host
-- is in another map (host_area / host_block), 2 no sign of the host for a minute.
-- When the host's room disappears the guest therefore no longer goes home at once: it notes the bosses killed
-- together so far, waits, follows, and goes home only when the host stays away.
function COOP_PointFor(area, block)
	if block == 0 then return 999; end
	if area == 3 and block == 1 then return 999; end      -- the Shrine of Storms starts in block 1
	return 998 - block;                                    -- 997, 996, 995: the archstones after each boss
end

function COOP_NoteCredit(proxy)
	local n = 0;
	for i = 1, COOP_BOSS_N do
		if proxy:IsCompleteEvent(COOP_BOSS_FLAGS[i]) == true and COOP_Get("base" .. i) ~= 1 then
			COOP_Set("credit" .. i, 1);
			n = n + 1;
		end
	end
	return n;
end

-- "Host1 has left." (event text 20001020) is a box that waits for OK. It shows on the guest every time the host
-- changes map, and not through the scripts' OnLeavePlayer (that never runs here), so it cannot be kept from
-- opening; proxy:CloseMenu() does not close it either. So the port presses OK for the player
-- (COOP_Set("press_ok", 1): ds_coop.cpp, coop_pad_inject), while the guest waits for the host and for a few
-- seconds after it arrives -- the only moments this looks at the info box at all.
function COOP_CloseLeaveBox(proxy, param)
	if COOP_Get("mode") == 0 then return; end
	if proxy:IsShowMenu_InfoMenu() == true then
		print("[coop] the \"has left\" box is up: OK pressed");
		COOP_Set("press_ok", 1);
	end
end

function COOP_FollowCheck(proxy, param)
	COOP_CloseLeaveBox(proxy, param);
	if proxy:IsClient() == true then return false; end       -- with the host
	COOP_follow = COOP_Get("follow");
	if COOP_follow == 2 and COOP_Get("guest") ~= 1 then return false; end   -- never had a host: nowhere to go back to
	return COOP_follow ~= 0;
end
function COOP_FollowAct(proxy, param)
	if COOP_follow == 1 then
		local area = COOP_Get("host_area");
		local block = COOP_Get("host_block");
		if area < 0 then return; end
		print("[coop] following the host to map " .. area .. "," .. block .. ", point " .. COOP_PointFor(area, block));
		COOP_Set("souls_keep", 1);       -- this load must not change the souls (ds_coop.cpp, coop_souls_fix)
		proxy:SetEventFlag(4047, true);
		proxy:SetLoadWait();
		proxy:WarpNextStage(area, block, 0, 0, COOP_PointFor(area, block));
	else
		COOP_GoHome(proxy, "the host did not come back");
	end
end

-- The join is the game's white-phantom summon, and that only takes a player in soul form with no summon left
-- over: after the first session the guest is a live player, and every later join failed (OnFailedJoinSession).
-- So a guest that is on its own is put back in soul form, with the last summon's leftovers cleared, until the
-- next join makes it a live player again (step A).
function COOP_Joinable(proxy)
	if COOP_Get("mode") ~= 2 then return; end
	if proxy:IsGreyGhost() == false and COOP_Get("env_NOGREY") ~= 1 then
		print("[coop] guest alone: back to soul form for the next join (was type " .. tostring(proxy:GetLocalPlayerChrType()) .. ")");
		proxy:SetChrType(10000, CHR_TYPE_GreyGhost);
	end
end

COOP_InGameStart_D = InGameStart;
function InGameStart(proxy, param)
	local arriving = (proxy:IsWhiteGhost() == true);
	COOP_InGameStart_D(proxy, param);
	COOP_Set("souls_keep", 2);       -- a map is in: if this was the load on the way to the host, the souls go back
	if arriving == false and proxy:IsInParty() == false then      -- on its own
		proxy:SetEventFlag(4047, false);
		if COOP_Get("guest") == 1 then
			COOP_Joinable(proxy);                     -- between two maps of the host's
		elseif COOP_Get("mode") == 2 then
			-- on its own, at home: the form it had before the first join, or its body after a boss
			if COOP_Get("revive") == 1 then
				COOP_Set("revive", 0);
				COOP_Set("orig", CHR_TYPE_LivePlayer + 1);
				proxy:SetChrType(10000, CHR_TYPE_LivePlayer);
				print("[coop] home after a boss: body form");
			elseif COOP_Get("orig") == 0 then
				COOP_Set("orig", proxy:GetLocalPlayerChrType() + 1);
				COOP_Joinable(proxy);                 -- the first join too: the summon only takes a soul
			elseif proxy:GetLocalPlayerChrType() ~= COOP_Get("orig") - 1 then
				print("[coop] home: back to the form from before the join (type " .. (COOP_Get("orig") - 1) .. ")");
				proxy:SetChrType(10000, COOP_Get("orig") - 1);
			end
		end
		proxy:NotNetMessage_begin();
			proxy:OnRegistFunc( 9972, "COOP_FollowCheck", "COOP_FollowAct", 60, once );
		proxy:NotNetMessage_end();
	elseif arriving == true then
		COOP_Set("lost", 0);
		proxy:NotNetMessage_begin();
			proxy:OnKeyTime2( 9973, "COOP_CloseLeaveBox", 1.0, 0, 0, once );
			proxy:OnKeyTime2( 9974, "COOP_CloseLeaveBox", 3.0, 0, 1, once );
			proxy:OnKeyTime2( 9975, "COOP_CloseLeaveBox", 6.0, 0, 2, once );
			proxy:OnKeyTime2( 9976, "COOP_CloseLeaveBox", 10.0, 0, 3, once );
		proxy:NotNetMessage_end();
	end
end

function OnRoomDisappeared(proxy, param)
	if COOP_Get("guest") == 1 then
		if proxy:IsCompleteEvent( 4047 ) == true then
			print("[coop] OnRoomDisappeared: a reload is already under way");
			return;
		end
		print("[coop] the host's room is gone; bosses killed together so far: " .. COOP_NoteCredit(proxy) .. "; waiting for the host");
		COOP_Set("lost", 1);
		COOP_Joinable(proxy);
		proxy:NotNetMessage_begin();
			proxy:OnRegistFunc( 9972, "COOP_FollowCheck", "COOP_FollowAct", 60, once );
		proxy:NotNetMessage_end();
		return;
	end
	COOP_OnRoomDisappeared(proxy, param);
end

-- The host gets the same box ("Guest1 has left.") whenever the guest drops out and comes straight back -- when it
-- dies, for one. The host has no waiting loop of its own, so one is registered at every load: it watches the party,
-- and for a short while after the party empties an info box on screen gets the OK press. (Only then: any other
-- info box the host opens is left alone.)
function COOP_HostWatch(proxy, param)
	local party = proxy:IsInParty();
	if COOP_h_party == true and party == false then
		COOP_h_left = 40;                      -- checks, a few seconds
		print("[coop] host: the guest dropped out");
	end
	COOP_h_party = party;
	if COOP_h_left ~= nil and COOP_h_left > 0 then
		COOP_h_left = COOP_h_left - 1;
		COOP_CloseLeaveBox(proxy, param);
	end
	return false;                               -- never "done": keep watching
end
function COOP_HostWatchDone(proxy, param)
end

-- DEV TEST (COOP_TEST_DIE=<seconds> in a copy's environment): the guest dies that long after arriving, the host
-- that long after its map came in.
function COOP_TestDie(proxy, param)
	print("[coop] test: this player dies now");
	if COOP_Get("mode") == 2 and COOP_Get("env_TEST_FORCE") == 0 then
		proxy:SetHp(10000, 0.0);          -- as damage does it (COOP_TEST_FORCE=1: ForceDead, which is a death)
	else
		proxy:ForceDead(10000);
	end
end

COOP_InGameStart_E = InGameStart;
function InGameStart(proxy, param)
	local arriving = (proxy:IsWhiteGhost() == true);
	COOP_InGameStart_E(proxy, param);
	if COOP_Get("mode") == 1 then
		COOP_h_party = proxy:IsInParty();
		if COOP_Get("env_TEST_DIE") > 0 and COOP_Get("died") == 0 then      -- DEV TEST: the host dies
			COOP_Set("died", 1);
			proxy:NotNetMessage_begin();
				proxy:OnKeyTime2( 9978, "COOP_TestDie", COOP_Get("env_TEST_DIE"), 0, 0, once );
			proxy:NotNetMessage_end();
		end
		proxy:NotNetMessage_begin();
			proxy:OnRegistFunc( 9977, "COOP_HostWatch", "COOP_HostWatchDone", 10, once );
		proxy:NotNetMessage_end();
	end
	if arriving == true and COOP_Get("env_TEST_DIE") > 0 and COOP_Get("died") == 0 then
		COOP_Set("died", 1);
		proxy:NotNetMessage_begin();
			proxy:OnKeyTime2( 9978, "COOP_TestDie", COOP_Get("env_TEST_DIE"), 0, 0, once );
		proxy:NotNetMessage_end();
	end
end

-- Step E: a guest that goes down stays with the host. The game's death (OnEvent_4000 -> SoloPlayDeath) reloads
-- the map, and a map load takes a client out of the session: the guest dropped out and joined again a few
-- seconds later, with a "has left" on the host's screen. A dead player cannot be brought back without that
-- load either (SetAlive + SetHp gave a living character that could not move). So the guest does not die: it is
-- in the game's own "dead mode" (the tutorial's: health stops at zero, SetDeadMode), and at zero health it gets
-- "YOU DIED", a few seconds out of the fight, and then stands up next to the host with full health. Its souls
-- stay: there is no bloodstain to go back to. A death that gets past dead mode is still the game's own death
-- (out and back in, as before).
function COOP_GuestGuard(proxy)
	proxy:SetDeadMode(10000, true);
	proxy:NotNetMessage_begin();
		proxy:OnRegistFunc( 9981, "COOP_GuestDownCheck", "COOP_GuestDown", 10, once );
	proxy:NotNetMessage_end();
end
-- (In dead mode the health stops at 1, and OnCharacterHP(.., 0.0) never ran in the tests: this looks instead.)
function COOP_GuestDownCheck(proxy, param)
	return proxy:GetHpRate(10000) <= 0.004;
end
function COOP_GuestDown(proxy, param)
	print("[coop] the guest is down: it stays with the host");
	proxy:SetTextEffect(TEXT_TYPE_Dead);
	proxy:EnableInvincible(10000, true);
	proxy:DisableMove(10000, 1);
	local secs = COOP_Get("env_DOWN_SECS");
	if secs <= 0 then secs = 4.0; end
	proxy:NotNetMessage_begin();
		proxy:OnKeyTime2( 9979, "COOP_GuestGetUp", secs, 0, 0, once );
	proxy:NotNetMessage_end();
end
function COOP_GuestGetUp(proxy, param)
	print("[coop] the guest gets up (alive " .. tostring(proxy:IsAlive(10000)) .. ", in party " .. tostring(proxy:IsInParty()) .. ")");
	COOP_Set("regroup", 1);
	proxy:SetHp(10000, 1.0);
	proxy:RequestFullRecover();
	proxy:DisableMove(10000, 0);
	proxy:PlayAnimation(10000, 6100);
	proxy:NotNetMessage_begin();
		proxy:OnKeyTime2( 9980, "COOP_GuestUp", 2.0, 0, 0, once );
	proxy:NotNetMessage_end();
end
function COOP_GuestUp(proxy, param)
	proxy:EnableInvincible(10000, false);
	proxy:NotNetMessage_begin();
		proxy:OnRegistFunc( 9981, "COOP_GuestDownCheck", "COOP_GuestDown", 10, once );
	proxy:NotNetMessage_end();
end

COOP_InGameStart_F = InGameStart;
function InGameStart(proxy, param)
	local arriving = (proxy:IsWhiteGhost() == true);
	COOP_InGameStart_F(proxy, param);
	if COOP_Get("mode") == 2 then
		if arriving == true then
			COOP_GuestGuard(proxy);
		else
			proxy:SetDeadMode(10000, false);
		end
	end
end
