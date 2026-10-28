-- ASR boss bars: the bosses fighting you, each a health bar under the run's clock, from the
-- game's AZS_GetBosses() and AZS_GetGuardians(). Bosses come for you as soon as they appear;
-- a lair guardian only once it is awake. The final boss is purple, an enraged boss pulses
-- orange, the rest are red. A pale trail drains behind the bar after every hit.

local WIDTH, HEIGHT, GAP, TOP = 420, 24, 14, -62;
local TRAIL_RATE = 0.6;  -- of the bar's length per second the trail drains
local bars = {};
local elapsed = 0;

local function Bar(i)
	if ( bars[i] ) then
		return bars[i];
	end
	local frame = CreateFrame("Frame", nil, UIParent);
	frame:SetWidth(WIDTH);
	frame:SetHeight(HEIGHT);
	frame:SetPoint("TOP", UIParent, "TOP", 12, TOP - (i - 1) * (HEIGHT + GAP));
	frame:SetFrameStrata("HIGH");
	frame:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
		edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 14,
		insets = { left = 3, right = 3, top = 3, bottom = 3 } });
	frame:SetBackdropColor(0, 0, 0, 0.85);
	frame:SetBackdropBorderColor(1, 0.82, 0.3);

	local trail = CreateFrame("StatusBar", nil, frame);
	trail:SetPoint("TOPLEFT", frame, "TOPLEFT", 4, -4);
	trail:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -4, 4);
	trail:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar");
	trail:SetStatusBarColor(1, 0.9, 0.6, 0.85);
	frame.trail = trail;

	local health = CreateFrame("StatusBar", nil, frame);
	health:SetAllPoints(trail);
	health:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar");
	health:SetFrameLevel(trail:GetFrameLevel() + 1);
	frame.health = health;

	-- A soft white shine on the top half, and a spark riding the bar's edge.
	local shine = health:CreateTexture(nil, "OVERLAY");
	shine:SetTexture(1, 1, 1, 0.12);
	shine:SetPoint("TOPLEFT", health, "TOPLEFT");
	shine:SetPoint("TOPRIGHT", health, "TOPRIGHT");
	shine:SetHeight((HEIGHT - 8) / 2);
	local spark = health:CreateTexture(nil, "OVERLAY");
	spark:SetTexture("Interface\\CastingBar\\UI-CastingBar-Spark");
	spark:SetBlendMode("ADD");
	spark:SetWidth(20);
	spark:SetHeight(HEIGHT * 2);
	frame.spark = spark;

	local text = CreateFrame("Frame", nil, frame);
	text:SetAllPoints(frame);
	text:SetFrameLevel(health:GetFrameLevel() + 2);
	frame.name = text:CreateFontString(nil, "OVERLAY", "GameFontNormal");
	frame.name:SetPoint("LEFT", frame, "LEFT", 10, 0);
	frame.name:SetTextColor(1, 0.85, 0.3);
	frame.value = text:CreateFontString(nil, "OVERLAY", "GameFontHighlight");
	frame.value:SetPoint("RIGHT", frame, "RIGHT", -10, 0);

	-- The skull badge on the left end.
	local skull = text:CreateTexture(nil, "OVERLAY");
	skull:SetTexture("Interface\\TargetingFrame\\UI-TargetingFrame-Skull");
	skull:SetWidth(30);
	skull:SetHeight(30);
	skull:SetPoint("RIGHT", frame, "LEFT", 4, 0);

	bars[i] = frame;
	return frame;
end

-- 1234567 as "1,234,567".
local function Number(n)
	local text = tostring(math.floor(n));
	local out = "";
	while ( string.len(text) > 3 ) do
		out = "," .. string.sub(text, -3) .. out;
		text = string.sub(text, 1, -4);
	end
	return text .. out;
end

-- The bosses and awake guardians, bosses first.
local function Fighting()
	local list = AZS_GetBosses and AZS_GetBosses() or {};
	local guardians = AZS_GetGuardians and AZS_GetGuardians() or {};
	for i = 1, table.getn(guardians) do
		if ( guardians[i].awake ) then
			table.insert(list, guardians[i]);
		end
	end
	return list;
end

local function Update(dt)
	local list = Fighting();
	local shown = 0;
	local pulse = 0.5 + 0.5 * math.sin(GetTime() * 6);
	for i = 1, table.getn(list) do
		local b = list[i];
		local hp, hpm = tonumber(b.hp) or 0, tonumber(b.hpm) or 0;
		if ( hpm > 0 and hp > 0 ) then
			shown = shown + 1;
			local bar = Bar(shown);
			-- A new boss in this slot starts its trail full, not where the last one's was.
			if ( bar.id ~= b.id ) then
				bar.id = b.id;
				bar.trailValue = hp;
			end
			bar.health:SetMinMaxValues(0, hpm);
			bar.health:SetValue(hp);
			bar.trailValue = math.max(hp, (bar.trailValue or hp) - hpm * TRAIL_RATE * dt);
			bar.trail:SetMinMaxValues(0, hpm);
			bar.trail:SetValue(bar.trailValue);
			bar.spark:SetPoint("CENTER", bar.health, "LEFT", bar.health:GetWidth() * hp / hpm, 0);
			if ( b.final ) then
				bar.health:SetStatusBarColor(0.62, 0.2, 0.95);
				bar:SetBackdropBorderColor(0.8, 0.5, 1);
			elseif ( b.enraged ) then
				bar.health:SetStatusBarColor(1, 0.35 + 0.25 * pulse, 0);
				bar:SetBackdropBorderColor(1, 0.4 + 0.4 * pulse, 0.1);
			else
				bar.health:SetStatusBarColor(0.8, 0.08, 0.06);
				bar:SetBackdropBorderColor(1, 0.82, 0.3);
			end
			bar.name:SetText(b.name);
			bar.value:SetText(string.format("%s / %s  |cffffd100%d%%|r", Number(hp), Number(hpm), math.floor(hp / hpm * 100 + 0.5)));
			bar:Show();
		end
	end
	for i = shown + 1, table.getn(bars) do
		bars[i]:Hide();
		bars[i].id = nil;
	end
end

local frame = CreateFrame("Frame");
-- These bars replace the game's own thin ones (Interface > Show Boss Bars), which show the same
-- bosses: turn those off once in, so the bar is not drawn twice.
frame:RegisterEvent("PLAYER_ENTERING_WORLD");
frame:SetScript("OnEvent", function()
	if ( AZS_IsHudShown and AZS_IsHudShown("bosses") ) then
		AZS_SetHudShown("bosses", false);
	end
end);
frame:SetScript("OnUpdate", function()
	elapsed = elapsed + arg1;
	if ( elapsed >= 0.03 ) then
		Update(elapsed);
		elapsed = 0;
	end
end);
