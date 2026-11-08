-- Demon's Souls boss rush: the event-script module (tools/make_boss_rush.py appends it to global_event.lua in every
-- map's script bundle of game_bossrush/, with a BR_MapLoad(proxy) call at the end of g_Initialize).
--
-- A run: a new character starts in the Nexus with 3,000 souls (the tutorial and the Vanguard skipped), every Nexus
-- trader present. Each world's archstone in the Nexus offers the world's next unbeaten boss ("Fight <boss>?") and
-- puts you at its fog gate (make_boss_rush.py moved each boss map's archstone warp point onto the fog). After a kill
-- the boss's archstone asks "Fight <next boss>?" / "Return to the Nexus?" (they alternate per touch; a world's
-- last boss only asks for the Nexus). Dying during a boss: back to its fog in body form, the boss reset (unless it is
-- already dead). The run ends when King Allant dies; his fight and the endings are the game's own.
-- The timer (the port, ds_boss_rush.cpp, DES_BOSS_RUSH=1) gets its events as print("BRX ...") lines.
--
-- Event flags used (none is used by any game script): 4106-4110 = the boss to set up on the next load,
-- 4120-4124 = the boss being fought (5 bits each, 0 = none), 4129 = this character's rush has begun.
-- Event / timer ids 9950-9969 (unused by the game scripts).

-- n, map a/b, warp point in that map, fog region, fog-entry flag, flags to clear for a reset (the kill flag first),
-- soul pickup flag, archstone warp event + object, world (1 Boletaria 2 Storms 3 Latria 4 Valley 5 Stonefang), next
-- boss in that world (0 = back to the Nexus). From the game's own map scripts (docs/NOTES.md, boss rush).
BR_B = {
 {n="Phalanx",      a=2,b=0,pt=998,fog=2895,e=110, clr={4096},           p=4103,w=4105,o=1982,wd=1,nx=2},
 {n="Tower Knight", a=2,b=1,pt=997,fog=2894,e=582, clr={4224},           p=4252,w=4254,o=1981,wd=1,nx=3},
 {n="Penetrator",   a=2,b=2,pt=996,fog=2893,e=1034,clr={4360,1431},      p=4372,w=4374,o=1980,wd=1,nx=4},
 {n="False King",   a=2,b=3,pt=995,fog=2892,e=1570,clr={4480},           p=4503,w=4505,o=1979,wd=1,nx=0},
 {n="Adjudicator",  a=3,b=1,pt=997,fog=2894,e=594, clr={4756,4800},      p=4804,w=4805,o=1981,wd=2,nx=6},
 {n="Old Hero",     a=3,b=2,pt=996,fog=2893,e=1190,clr={4895,4870},      p=4874,w=4875,o=1980,wd=2,nx=7},
 {n="Storm King",   a=3,b=3,pt=995,fog=2892,e=1542,clr={4992,4995,4991}, p=4996,w=4998,o=1979,wd=2,nx=0},
 {n="Fool's Idol",  a=4,b=0,pt=998,fog=2895,e=380, clr={5123},           p=5121,w=5122,o=1982,wd=3,nx=9},
 {n="Maneater",     a=4,b=1,pt=997,fog=2894,e=523, clr={5251,5250,5253}, p=5261,w=5262,o=1981,wd=3,nx=10},
 {n="Old Monk",     a=4,b=2,pt=996,fog=2893,e=1031,clr={5380},           p=5381,w=5382,o=1980,wd=3,nx=0},
 {n="Leechmonger",  a=5,b=0,pt=998,fog=2895,e=160, clr={5650},           p=5653,w=5654,o=1982,wd=4,nx=12},
 {n="Dirty Colossus", a=5,b=1,pt=997,fog=2894,e=533, clr={5770},         p=5773,w=5774,o=1981,wd=4,nx=13},
 {n="Maiden Astraea", a=5,b=2,pt=996,fog=2893,e=1031,clr={5889,5888},    p=5893,w=5895,o=1980,wd=4,nx=0},
 {n="Armor Spider", a=6,b=0,pt=998,fog=2895,e=111, clr={6174},           p=6193,w=6194,o=1982,wd=5,nx=15},
 {n="Flamelurker",  a=6,b=1,pt=997,fog=2894,e=520, clr={6272},           p=6283,w=6284,o=1981,wd=5,nx=16},
 {n="Dragon God",   a=6,b=2,pt=996,fog=2893,e=1050,clr={6400},           p=6403,w=6404,o=1980,wd=5,nx=0},
};
-- "Fight <boss>?" (event text FMG 30: empty slots make_boss_rush.py fills), in the Nexus and after a kill
BR_MSG = {10010700, 10010701, 10010702, 10010703, 10010704, 10010705, 10010706, 10010707, 10010708, 10010709,
          10010713, 10010714, 10010715, 10010716, 10010717, 10010718};
BR_NEXUS_PT = {1006, 1007, 1008, 1009, 1010};   -- the Nexus arrival point of each world
BR_WORLD_NPC = {"GO_TO_WARP_OUJOU", "GO_TO_WARP_FURUTORIDE", "GO_TO_WARP_ROUJOU", "GO_TO_WARP_FUJOU", "GO_TO_WARP_KOUDOU"};
BR_START_SOULS = 3000;
BR_POW = {1, 2, 4, 8, 16};
BR_ASKED = {};       -- per boss: 1 after "next boss?" was asked (the next touch asks for the Nexus)
BR_NEXUS_ORIG = {};  -- the Nexus archstones' own handlers
BR_NEXUS_WRAP = {};  -- and ours in their place

-- Arriving at a boss (1 s after the load). False King's fog is at the top of an elevator (object 1620) that his
-- map's init parks at the bottom: his warp point is on the elevator at the bottom, and this starts the ride up
-- (the LuaCall the map's own "ride up" action sends).
BR_ARRIVE = {};
BR_ARRIVE[4] = function(proxy) proxy:LuaCallStart( 1635, 3 ); end
-- Normal enemies at a fog, switched off on arrival (the game's InvalidCharactor). Adjudicator: the Shrine of
-- Storms skeletons within 30 m of his fog (m03_01 wakes each one when you come within 30 m; one lies 2.5 m from it).
BR_QUIET = {};
BR_QUIET[5] = {379, 378, 376, 429, 363, 431, 364, 432};
-- Flags set before a boss map's init when we warp there. Fool's Idol: her reviver (the Revival Enchanter, 500)
-- counts as dead (390, 391 -- RevivalEnchanterDead_390). Her death only counts once he is dead (OnEvent_5123_call
-- checks 390); with him alive she is revived and the cutscene that carries you to her archstone never comes. With
-- 390 set, m04_00's init removes him.
BR_SETUP = {};
BR_SETUP[8] = {390, 391};

function BR_Get5(proxy, base)
	local v = 0;
	for k = 0, 4 do
		if proxy:IsCompleteEvent( base + k ) == true then v = v + BR_POW[k + 1]; end
	end
	return v;
end
function BR_Set5(proxy, base, v)
	for k = 0, 4 do
		proxy:SetEventFlag( base + k, math.mod(math.floor(v / BR_POW[k + 1]), 2) == 1 );
	end
end
function BR_GetPending(proxy) return BR_Get5(proxy, 4106); end
function BR_SetPending(proxy, v) BR_Set5(proxy, 4106, v); end
function BR_GetCurrent(proxy) return BR_Get5(proxy, 4120); end
function BR_SetCurrent(proxy, v) BR_Set5(proxy, 4120, v); end
-- The boss being fought, from its flags (Lua variables start over whenever the scripts are run again, e.g. a
-- block of the same area loading mid-fight; the flags do not), or nil. Every handler that runs later goes
-- through this: an error in an event handler ends the game.
function BR_Boss(proxy)
	local i = BR_GetCurrent(proxy);
	if i >= 1 and i <= 16 then return i, BR_B[i]; end
	return nil, nil;
end

-- A boss back to life: its map's init rebuilds the room (fog walls, the boss) from these flags.
function BR_Reset(proxy, i)
	local b = BR_B[i];
	for _, f in ipairs(b.clr) do proxy:SetEventFlag( f, false ); end
	proxy:SetEventFlag( b.p, false );
	proxy:SetEventFlag( b.w, false );
	print("BR:reset " .. b.n);
end

-- At the end of g_Initialize, before the map's own Initialize: flag changes here decide how the map loads.
function BR_MapLoad(proxy)
	print("BRX loading");   -- the run timer pauses until "BRX ingame" (the map is loading)
	BR_Traders(proxy);
	BR_NexusStory(proxy);
	local pend = BR_GetPending(proxy);
	print("BR:load, pending=" .. pend);
	BR_ARRIVED = pend >= 1 and pend <= 16;   -- this load is one of our warps to a boss
	if BR_ARRIVED then
		BR_Reset( proxy, pend );
		if BR_SETUP[pend] ~= nil then
			for _, f in ipairs(BR_SETUP[pend]) do proxy:SetEventFlag( f, true ); end
		end
		BR_SetPending( proxy, 0 );
		BR_SetCurrent( proxy, pend );
		proxy:OnKeyTime2( 9960, "BR_ToFog", 1.0, 0, 0, once );
	end
	proxy:OnKeyTime2( 9950, "BR_Hook", 1.0, 0, 0, once );
end

function BR_ToFog(proxy, param)
	local i, b = BR_Boss(proxy);
	if b == nil then return; end
	print("BR:at the fog of " .. b.n);
	if proxy:IsLivePlayer() == false then
		-- always in body form at a boss (as the tutorial revives you after the Vanguard)
		proxy:PlayerParamRecover();
		proxy:SetChrType( 10000, 0 );
	end
	proxy:RequestFullRecover();
	if BR_ARRIVE[i] ~= nil then BR_ARRIVE[i](proxy); end
	if BR_QUIET[i] ~= nil and InvalidCharactor ~= nil then
		for _, id in ipairs(BR_QUIET[i]) do InvalidCharactor( proxy, id ); end
	end
end

function BR_EntryCheck(proxy)
	local i, b = BR_Boss(proxy);
	return b ~= nil and proxy:IsCompleteEvent( b.e ) == true;
end
function BR_Entered(proxy, param)
	local i, b = BR_Boss(proxy);
	if b == nil then return; end
	print("BRX start");   -- the first fog of a run starts the timer
	print("BRX boss " .. b.n);
end

function BR_KillCheck(proxy)
	local i, b = BR_Boss(proxy);
	return b ~= nil and proxy:IsCompleteEvent( b.clr[1] ) == true;
end
function BR_Killed(proxy, param)
	local i, b = BR_Boss(proxy);
	if b == nil then return; end
	print("BRX split " .. b.n);
end

-- 1 s after every load: the boss archstones' warp actions, a character's first load, the Nexus archstones and
-- King Allant.
function BR_Hook(proxy, param)
	print("BRX ingame");   -- the timer shows from the first one on (not on the title or character creation)
	local ci, cb = BR_Boss(proxy);   -- a boss being fought
	if cb ~= nil and _G["Initialize_m01_00_00_00"] ~= nil then
		-- in the Nexus (the Nexial Binding, Evacuate): no boss is being fought any more, so a death here is the
		-- game's own
		print("BR:in the Nexus, " .. cb.n .. " left");
		BR_SetCurrent( proxy, 0 );
		ci, cb = nil, nil;
	end
	if cb ~= nil and not BR_ARRIVED and proxy:IsCompleteEvent( cb.clr[1] ) == false
	   and _G["Initialize_m01_00_00_00"] == nil then
		-- a save continued in the middle of this boss (a quit or a crash): back to its fog, like a death
		print("BR:continued in the middle of " .. cb.n .. " -> back to its fog");
		BR_SetPending( proxy, ci );
		print("BRX loading");
		proxy:WarpNextStage( cb.a, cb.b, 0, 0, cb.pt );
		return;
	end
	if cb ~= nil then
		proxy:OnRegistFunc( 9961, "BR_EntryCheck", "BR_Entered", 0, once );
		if proxy:IsCompleteEvent( cb.clr[1] ) == false then
			proxy:OnRegistFunc( 9967, "BR_KillCheck", "BR_Killed", 0, once );
		end
	end
	for i, b in ipairs(BR_B) do   -- only the current map's archstone can ever fire
		local name = "OnEvent_" .. b.w;
		if _G[name] ~= nil then
			local idx = i;
			_G[name] = function(proxy, param) BR_Arch(proxy, idx); end
		end
	end
	if proxy:IsCompleteEvent( 4129 ) == false then
		-- a character's first load: the rush begins; in the tutorial it is skipped too (a save that has done the
		-- tutorial before starts a new character in the Nexus)
		if _G["Initialize_m08_00_00_00"] ~= nil then
			BR_SkipTutorial(proxy);
			return;
		end
		BR_Begin(proxy);
	end
	if _G["Initialize_m01_00_00_00"] ~= nil then
		for w = 1, 5 do   -- (a load runs the map's script again: wrap whatever handler is there now)
			local name = "OnEvent_" .. (w - 1);
			if _G[name] ~= nil and _G[name] ~= BR_NEXUS_WRAP[w] then
				BR_NEXUS_ORIG[w] = _G[name];
				local ww = w;
				BR_NEXUS_WRAP[w] = function(proxy, param) BR_NexusStone(proxy, param, ww); end
				_G[name] = BR_NEXUS_WRAP[w];
			end
		end
		if proxy:IsCompleteEvent( 70 ) == false then
			proxy:OnRegistFunc( 9968, "BR_AllantFogCheck", "BR_AllantFog", 0, once );
			proxy:OnRegistFunc( 9969, "BR_AllantDeadCheck", "BR_AllantDead", 0, once );
		end
	end
end

-- A boss's archstone after the kill: "Fight <next boss>?", the next touch "Return to the Nexus?", and so on.
function BR_Arch(proxy, i)
	local b = BR_B[i];
	local nexus = (b.nx == 0) or (BR_ASKED[i] == 1);
	BR_ASKED[i] = nexus and 0 or 1;
	BR_PICK = i;
	proxy:RepeatMessage_begin();
	proxy:NotNetMessage_begin();
		proxy:OnSelectMenu( 9951, nexus and "BR_YesNexus" or "BR_YesNext", nexus and 10010710 or BR_MSG[b.nx], 0, 2, b.o, 2, once );
	proxy:NotNetMessage_end();
	proxy:RepeatMessage_end();
end
function BR_YesNext(proxy, param) BR_Leave(proxy, BR_PICK, false); end
function BR_YesNexus(proxy, param) BR_Leave(proxy, BR_PICK, true); end
function BR_Leave(proxy, i, nexus)   -- the game's archstone touch animation, then BR_Go
	if i == nil or BR_B[i] == nil then return; end
	BR_LEAVE_I = i;
	BR_LEAVE_NEXUS = nexus;
	proxy:PlayAnimation( LOCAL_PLAYER, 8283 );
	proxy:NoAnimeTurnCharactor( 10000, BR_B[i].o, TURNSKIP_ANGLE );
	proxy:NotNetMessage_begin();
		proxy:OnChrAnimEnd( 9952, LOCAL_PLAYER, 8283, "BR_Go", once );
	proxy:NotNetMessage_end();
end
function BR_Go(proxy, param)
	local b = BR_LEAVE_I ~= nil and BR_B[BR_LEAVE_I] or nil;
	if b == nil then return; end
	proxy:PlayAnimation( 10000, 8284 );
	proxy:RequestFullRecover();
	if BR_LEAVE_NEXUS or b.nx == 0 then
		BR_SetCurrent( proxy, 0 );
		proxy:SetEventFlag( 8083, true );
		print("BRX loading");
		proxy:WarpNextStage( 1, 0, 0, 0, BR_NEXUS_PT[b.wd] );
	else
		local n = BR_B[b.nx];
		BR_SetPending( proxy, b.nx );
		print("BRX loading");
		proxy:WarpNextStage( n.a, n.b, 0, 0, n.pt );
	end
end

-- Dying during a boss: back to its fog in body form (the game's SoloPlayDeath_2 without the soul-form step), the
-- boss reset unless it is already dead. With no boss being fought, the game's own death.
BR_ORIG_DEATH2 = SoloPlayDeath_2;
function SoloPlayDeath_2(proxy, param)
	local cur = BR_GetCurrent(proxy);
	if cur < 1 or cur > 16 then
		BR_ORIG_DEATH2(proxy, param);
		return;
	end
	local b = BR_B[cur];
	local dead = proxy:IsCompleteEvent( b.clr[1] ) == true;
	print("BR:died at " .. b.n .. " -> back to its fog");
	proxy:SetFlagInitState(1);
	if not dead then BR_SetPending( proxy, cur ); end
	proxy:SetEventFlag( 16700, false );
	print("BRX loading");
	proxy:WarpNextStage( b.a, b.b, 0, 0, b.pt );
	proxy:PlayAnimation( 10000, 6100 );
	proxy:SetEventFlag( 4000, false );
	proxy:LuaCallStart( 4000, 100 );
	proxy:UpDateBloodMark();
end

-- A Nexus world archstone (object 999 + w): the world's next unbeaten boss, "Fight <boss>?" -> its fog. A world
-- with every boss dead opens the game's own travel menu.
function BR_NexusStone(proxy, param, w)
	local pick = 0;
	for i, b in ipairs(BR_B) do
		if pick == 0 and b.wd == w and proxy:IsCompleteEvent( b.clr[1] ) == false then pick = i; end
	end
	if pick == 0 then
		BR_NEXUS_ORIG[w](proxy, param);
		return;
	end
	BR_NEXUS_PICK = pick;
	BR_NEXUS_W = w;
	proxy:RepeatMessage_begin();
	proxy:NotNetMessage_begin();
		proxy:OnSelectMenu( 9956, "BR_NexusYes", BR_MSG[pick], 0, 2, 999 + w, 2, once );
	proxy:NotNetMessage_end();
	proxy:RepeatMessage_end();
end
function BR_NexusYes(proxy, param)
	if BR_NEXUS_PICK == nil or BR_NEXUS_W == nil then return; end
	proxy:WarpDmy( 10000, 999 + BR_NEXUS_W, 191 );
	proxy:PlayAnimation( 10000, 8283 );
	proxy:NotNetMessage_begin();
		proxy:OnChrAnimEnd( 9957, 10000, 8283, "BR_NexusGo", once );
	proxy:NotNetMessage_end();
end
function BR_NexusGo(proxy, param)
	local b = BR_NEXUS_PICK ~= nil and BR_B[BR_NEXUS_PICK] or nil;
	if b == nil or BR_NEXUS_W == nil then return; end
	proxy:PlayAnimation( 10000, 8284 );
	proxy:RequestFullRecover();
	local npc = _G[BR_WORLD_NPC[BR_NEXUS_W]];
	if SetNpcStateFlag ~= nil and warp_list ~= nil and npc ~= nil then
		SetNpcStateFlag( proxy, param, warp_list, npc );   -- what the game's own archstone does for the NPCs
	end
	BR_SetPending( proxy, BR_NEXUS_PICK );
	print("BRX loading");
	proxy:WarpNextStage( b.a, b.b, 0, 0, b.pt );
end

-- Every trader in the Nexus from the start (normally they come after you rescue them in the worlds). Each NPC's
-- states are one group of flags with exactly one set (the game's SetNpcStateFlag); a trader who is hostile or
-- dead stays that way. Yurt and Mephistopheles are left out: in the Nexus they murder the others. ROGARN in the
-- scripts is Sage Freke.
BR_TRADERS = {
	{n = "Yuria",            lo = 16110, hi = 16116, want = 16115, bad = {16112, 16113, 16116}},
	{n = "Saint Urbain",     lo = 16120, hi = 16125, want = 16124, bad = {16122, 16123, 16125}},
	{n = "Sage Freke",       lo = 16190, hi = 16196, want = 16191, bad = {16192, 16193, 16194}},
	{n = "Patches",          lo = 16240, hi = 16256, want = 16255, bad = {16244, 16245, 16249, 16254, 16256}},
	{n = "Stockpile Thomas", lo = 16350, hi = 16353, want = 16350, bad = {16351, 16352}},
	{n = "Boldwin",          lo = 16440, hi = 16443, want = 16440, bad = {16441, 16442}},
	{n = "the info seller",  lo = 16340, hi = 16343, want = 16341, bad = {16342, 16343}},
};
function BR_Traders(proxy)
	for _, t in ipairs(BR_TRADERS) do
		local hostile = false;
		for _, f in ipairs(t.bad) do
			if proxy:IsCompleteEvent( f ) == true then hostile = true; end
		end
		if not hostile and proxy:IsCompleteEvent( t.want ) == false then
			for f = t.lo, t.hi do proxy:SetEventFlag( f, false ); end
			proxy:SetEventFlag( t.want, true );
		end
	end
end

-- The Monumental's first visit counts as seen: the Maiden in Black only levels you up after it (her talk script
-- t0615 checks 303). 31 = the revival cutscene after Phalanx, 303 = his old tale, 34 / 36 / 8802 / 8030 = the
-- archstones unsealed (m01 OnEvent_34 / _36). Their item gifts (304 / 305) stay with the talks.
BR_STORY_FLAGS = {31, 303, 34, 36, 8802, 8030};
function BR_NexusStory(proxy)
	for _, f in ipairs(BR_STORY_FLAGS) do
		if proxy:IsCompleteEvent( f ) == false then proxy:SetEventFlag( f, true ); end
	end
end

-- A character's first load: the rush begins (the starting souls, the timer cleared; it starts at the first fog).
function BR_Begin(proxy)
	proxy:SetEventFlag( 4129, true );
	print("BR:the rush begins: " .. BR_START_SOULS .. " souls");
	BR_NexusStory(proxy);
	print("BRX reset");
	print("BRX souls " .. BR_START_SOULS);
end

-- In the tutorial: its own ending (m08_01 OnEvent_14300_3), straight to the Nexus in soul form. (The port sends a
-- new rush character to the Nexus directly -- ppu_recomp_018.cpp, func_00185158 -- so this is only a fallback.)
function BR_SkipTutorial(proxy)
	BR_Begin(proxy);
	proxy:SetEventFlag( 4000, 0 );
	proxy:Tutorial_end();
	proxy:ChangeGreyGhost();
	proxy:RequestFullRecover();
	print("BRX loading");
	proxy:WarpNextStage( 1, 0, 0, 0, -1 );
end

-- King Allant ends the run. His fight, deaths and the endings stay the game's own: only his fog entry (flag 61) and
-- his death (flag 70) are watched, for the timer.
function BR_AllantFogCheck(proxy) return proxy:IsCompleteEvent( 61 ) == true; end
function BR_AllantFog(proxy, param)
	print("BRX start");
	print("BRX boss King Allant");
end
function BR_AllantDeadCheck(proxy) return proxy:IsCompleteEvent( 70 ) == true; end
function BR_AllantDead(proxy, param)
	print("BRX split King Allant");
	print("BRX end");
end
