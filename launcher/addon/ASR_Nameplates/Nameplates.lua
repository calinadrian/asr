-- WoW 1.12: discover the native plates by their border, then keep the
-- original health bar and button so health, reaction colours and clicks work.
local plates = {};
local elapsed = 0;
local defaults = { width = 72, height = 6, names = "hover" };

local function Settings()
    if ( type(ASR_NameplatesDB) ~= "table" ) then ASR_NameplatesDB = {}; end
    local db = ASR_NameplatesDB;
    db.width = math.max(40, math.min(140, tonumber(db.width) or defaults.width));
    db.height = math.max(3, math.min(14, tonumber(db.height) or defaults.height));
    if ( db.names ~= "all" and db.names ~= "off" and db.names ~= "hover" ) then
        db.names = defaults.names;
    end
    return db;
end

local function Layout(p, db)
    -- Do not scale or move the projected root: that would move it off the unit.
    p.frame:SetWidth(db.width + 8);
    p.frame:SetHeight(db.height + 14);
    p.bar:ClearAllPoints();
    p.bar:SetPoint("TOP", p.frame, "TOP", 0, -12);
    p.bar:SetWidth(db.width);
    p.bar:SetHeight(db.height);
    p.bar:SetStatusBarTexture("Interface\\Buttons\\WHITE8X8");
    p.background:ClearAllPoints();
    p.background:SetPoint("TOPLEFT", p.bar, "TOPLEFT", -1, 1);
    p.background:SetPoint("BOTTOMRIGHT", p.bar, "BOTTOMRIGHT", 1, -1);
    p.name:ClearAllPoints();
    p.name:SetPoint("BOTTOM", p.bar, "TOP", 0, 2);
    p.name:SetWidth(db.width + 24);
    p.name:SetHeight(11);
    p.name:SetFont("Fonts\\FRIZQT__.TTF", 10, "OUTLINE");
    p.name:SetShadowColor(0, 0, 0, 1);
    p.name:SetShadowOffset(1, -1);
    p.raid:ClearAllPoints();
    p.raid:SetPoint("RIGHT", p.bar, "LEFT", -3, 0);
    p.raid:SetWidth(12);
    p.raid:SetHeight(12);
end

local function Discover(frame, db)
    if ( plates[frame] or not frame.GetRegions or not frame.GetChildren ) then return; end
    local border, glow, name, level, skull, raid = frame:GetRegions();
    if ( not border or not border.GetTexture or
         border:GetTexture() ~= "Interface\\Tooltips\\Nameplate-Border" ) then return; end
    local bar = frame:GetChildren();
    if ( not bar or not bar.GetObjectType or bar:GetObjectType() ~= "StatusBar" or
         not glow or not name or not name.SetFont or not level or not skull or not raid ) then return; end
    local p = { frame = frame, bar = bar, border = border, glow = glow,
                name = name, level = level, skull = skull, raid = raid };
    p.background = bar:CreateTexture(nil, "BACKGROUND");
    p.background:SetTexture(0.025, 0.025, 0.025, 0.95);
    -- Alpha hides the art while retaining the glow's native hover signal.
    border:SetAlpha(0);
    glow:SetAlpha(0);
    level:SetAlpha(0);
    skull:SetAlpha(0);
    plates[frame] = p;
    Layout(p, db);
end

local function Update()
    if ( not WorldFrame ) then return; end
    local db = Settings();
    -- A full scan also discovers recycled/new plates when the child count stays equal.
    local children = { WorldFrame:GetChildren() };
    for i = 1, table.getn(children) do Discover(children[i], db); end
    for frame, p in pairs(plates) do
        if ( frame:IsShown() ) then
            -- Native resolution changes can reset dimensions and anchors.
            if ( p.bar:GetWidth() ~= db.width or p.bar:GetHeight() ~= db.height or
                 p.frame:GetWidth() ~= db.width + 8 or p.frame:GetHeight() ~= db.height + 14 ) then
                Layout(p, db);
            end
            local show = db.names == "all" or (db.names == "hover" and p.glow:IsShown());
            if ( show ) then p.name:SetAlpha(1); else p.name:SetAlpha(0); end
        end
    end
end

local driver = CreateFrame("Frame");
driver:RegisterEvent("PLAYER_ENTERING_WORLD");
driver:SetScript("OnEvent", Update);
driver:SetScript("OnUpdate", function()
    elapsed = elapsed + arg1;
    if ( elapsed >= 0.05 ) then elapsed = 0; Update(); end
end);

SLASH_ASRPLATES1 = "/asrplates";
SlashCmdList["ASRPLATES"] = function(message)
    local db = Settings();
    local _, _, names = string.find(string.lower(message or ""), "^names%s+(%a+)%s*$");
    local _, _, width, height = string.find(message or "", "^size%s+(%d+)%s+(%d+)%s*$");
    if ( names == "all" or names == "hover" or names == "off" ) then
        db.names = names;
    elseif ( width and height ) then
        db.width = tonumber(width); db.height = tonumber(height); Settings();
    elseif ( string.lower(message or "") == "reset" ) then
        ASR_NameplatesDB = {}; db = Settings();
    else
        if ( DEFAULT_CHAT_FRAME ) then
            DEFAULT_CHAT_FRAME:AddMessage("ASR plates: /asrplates names hover|all|off; /asrplates size 72 6; /asrplates reset");
        end
        return;
    end
    Update();
    if ( DEFAULT_CHAT_FRAME ) then
        DEFAULT_CHAT_FRAME:AddMessage(string.format("ASR plates: %d x %d, names %s.", db.width, db.height, db.names));
    end
end;
