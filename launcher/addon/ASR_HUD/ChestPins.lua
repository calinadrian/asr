-- ASR Chest Pins: the run's chests on the minimap, from the game's AZS_CHESTS addon data.
-- Chests and lairs carry both world yards (x, y) and map fractions (mx, my); the spread between
-- any two of them gives the zone's yards per map fraction, which places each chest around the
-- player's own map position at the minimap's current zoom.

-- View diameter in yards per Minimap:GetZoom() outdoors (14 to 4 chunks of 33.33 yd).
local DIAMETER = { [0] = 466.67, 400, 333.33, 266.67, 200, 133.33 };
local ICON = "Interface\\Icons\\INV_Box_02";
local SIZE = 14;
local pins = {};
local scale;
local elapsed = 0;

local function Pin(i)
	if ( not pins[i] ) then
		local pin = CreateFrame("Frame", nil, Minimap);
		pin:SetWidth(SIZE);
		pin:SetHeight(SIZE);
		pin:SetFrameLevel(Minimap:GetFrameLevel() + 5);
		local icon = pin:CreateTexture(nil, "OVERLAY");
		icon:SetAllPoints(pin);
		icon:SetTexture(ICON);
		icon:SetTexCoord(0.08, 0.92, 0.08, 0.92);
		pin.icon = icon;
		pins[i] = pin;
	end
	return pins[i];
end

-- Yards per map fraction east and south, from the two points farthest apart on each axis.
local function Scale()
	local points = {};
	for _, list in ipairs({ AZS_CHESTS or {}, AZS_LAIRS or {} }) do
		for i = 1, table.getn(list) do
			local p = list[i];
			if ( tonumber(p.x) and tonumber(p.y) and tonumber(p.mx) and tonumber(p.my) ) then
				table.insert(points, p);
			end
		end
	end
	local east, south, spreadE, spreadS;
	for i = 1, table.getn(points) do
		for j = i + 1, table.getn(points) do
			local a, b = points[i], points[j];
			local dmx, dmy = math.abs(a.mx - b.mx), math.abs(a.my - b.my);
			if ( dmx > 0.01 and dmx > (spreadE or 0) ) then
				east, spreadE = math.abs(a.y - b.y) / dmx, dmx;
			end
			if ( dmy > 0.01 and dmy > (spreadS or 0) ) then
				south, spreadS = math.abs(a.x - b.x) / dmy, dmy;
			end
		end
	end
	if ( east and south ) then
		return { east = east, south = south };
	end
	-- Too few points spread out on an axis: keep the zone's last good scale rather than guess.
	return scale;
end

local function Update()
	local chests = AZS_CHESTS or {};
	local count = table.getn(chests);
	if ( count > 0 and not (WorldMapFrame and WorldMapFrame:IsShown()) ) then
		SetMapToCurrentZone();
	end
	local px, py = GetPlayerMapPosition("player");
	scale = Scale();
	local shown = 0;
	if ( scale and Minimap:IsVisible() and (px ~= 0 or py ~= 0) ) then
		local radius = (DIAMETER[Minimap:GetZoom()] or DIAMETER[0]) / 2;
		local rim = Minimap:GetWidth() / 2 - SIZE / 2;
		for i = 1, count do
			local c = chests[i];
			if ( tonumber(c.mx) and tonumber(c.my) ) then
				local east = (c.mx - px) * scale.east;
				local south = (c.my - py) * scale.south;
				local dx, dy = east / radius * (Minimap:GetWidth() / 2), -south / radius * (Minimap:GetHeight() / 2);
				local far = math.sqrt(dx * dx + dy * dy);
				local pin = Pin(i);
				-- Out of view: held on the rim, pointing the way, and dimmer.
				if ( far > rim ) then
					dx, dy = dx * rim / far, dy * rim / far;
					pin:SetAlpha(0.6);
				else
					pin:SetAlpha(1);
				end
				pin:ClearAllPoints();
				pin:SetPoint("CENTER", Minimap, "CENTER", dx, dy);
				pin:Show();
				shown = i;
			end
		end
	end
	for i = shown + 1, table.getn(pins) do
		pins[i]:Hide();
	end
end

local frame = CreateFrame("Frame");
frame:RegisterEvent("ZONE_CHANGED_NEW_AREA");
frame:SetScript("OnEvent", function()
	scale = nil;
end);
frame:SetScript("OnUpdate", function()
	elapsed = elapsed + arg1;
	if ( elapsed >= 0.1 ) then
		elapsed = 0;
		Update();
	end
end);
