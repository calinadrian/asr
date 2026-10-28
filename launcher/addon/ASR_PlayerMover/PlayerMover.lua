-- An edit-mode overlay leaves the native player frame's scripts untouched.
local player, handle, original;
local unlocked, moving = false, false;

local function Say(text)
    if ( DEFAULT_CHAT_FRAME ) then DEFAULT_CHAT_FRAME:AddMessage("ASR Player Mover: " .. text); end
end

local function Settings()
    if ( type(ASR_PlayerMoverDB) ~= "table" ) then ASR_PlayerMoverDB = {}; end
    local db = ASR_PlayerMoverDB;
    if ( type(db.x) ~= "number" or type(db.y) ~= "number" or
         db.x ~= db.x or db.y ~= db.y ) then db.x = nil; db.y = nil; end
    return db;
end

local function Place(x, y)
    local scale = player:GetEffectiveScale() / UIParent:GetEffectiveScale();
    local width, height = UIParent:GetWidth(), UIParent:GetHeight();
    if ( width <= 0 or height <= 0 or scale <= 0 ) then return; end
    local halfW = math.min(0.5, player:GetWidth() * scale / width / 2);
    local halfH = math.min(0.5, player:GetHeight() * scale / height / 2);
    x = math.max(halfW, math.min(1 - halfW, x));
    y = math.max(halfH, math.min(1 - halfH, y));
    player:ClearAllPoints();
    player:SetPoint("CENTER", UIParent, "BOTTOMLEFT", x * width / scale, y * height / scale);
end

local function Stop()
    if ( not moving ) then return; end
    moving = false;
    player:StopMovingOrSizing();
    -- This addon owns persistence, not the engine's layout cache.
    player:SetUserPlaced(false);
    local x, y = player:GetCenter();
    local width, height = UIParent:GetWidth(), UIParent:GetHeight();
    if ( not x or not y or width <= 0 or height <= 0 ) then return; end
    local scale = player:GetEffectiveScale() / UIParent:GetEffectiveScale();
    local db = Settings();
    db.x = x * scale / width;
    db.y = y * scale / height;
    Place(db.x, db.y);
end

local function Initialize()
    if ( player ) then return true; end
    if ( not PlayerFrame or not UIParent ) then return false; end
    player = PlayerFrame;
    original = {};
    for i = 1, player:GetNumPoints() do
        original[i] = { player:GetPoint(i) };
    end
    player:SetMovable(true);
    player:SetClampedToScreen(true);
    handle = CreateFrame("Frame", "ASR_PlayerMoverHandle", player);
    handle:SetAllPoints(player);
    handle:SetFrameLevel(player:GetFrameLevel() + 20);
    handle:EnableMouse(true);
    handle:RegisterForDrag("LeftButton");
    handle:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8",
        edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 });
    handle:SetBackdropColor(0, 0, 0, 0.7);
    handle:SetBackdropBorderColor(1, 0.82, 0.3, 1);
    local label = handle:CreateFontString(nil, "OVERLAY", "GameFontNormal");
    label:SetPoint("CENTER", handle, "CENTER", 0, 0);
    label:SetText("Drag player frame\n/asrplayer lock to finish");
    handle:SetScript("OnDragStart", function()
        if ( unlocked ) then player:StartMoving(); moving = true; end
    end);
    handle:SetScript("OnDragStop", Stop);
    handle:SetScript("OnHide", Stop);
    handle:Hide();
    local db = Settings();
    if ( db.x and db.y ) then Place(db.x, db.y); end
    return true;
end

SLASH_ASRPLAYER1 = "/asrplayer";
SlashCmdList["ASRPLAYER"] = function(message)
    if ( not Initialize() ) then Say("The character frame is not available yet. Try again inside a run."); return; end
    local command = string.lower(message or "");
    if ( command == "unlock" ) then
        unlocked = true; handle:Show();
        Say("Drag the highlighted character frame, then use /asrplayer lock.");
    elseif ( command == "lock" ) then
        Stop(); unlocked = false; handle:Hide(); Say("Position locked.");
    elseif ( command == "reset" ) then
        Stop(); unlocked = false; handle:Hide(); ASR_PlayerMoverDB = {};
        player:ClearAllPoints();
        for i = 1, table.getn(original) do player:SetPoint(unpack(original[i])); end
        player:SetUserPlaced(false);
        Say("Original position restored.");
    else
        Say("/asrplayer unlock, /asrplayer lock, /asrplayer reset");
    end
end;

local driver = CreateFrame("Frame");
driver:RegisterEvent("PLAYER_ENTERING_WORLD");
driver:RegisterEvent("DISPLAY_SIZE_CHANGED");
driver:RegisterEvent("UI_SCALE_CHANGED");
driver:SetScript("OnEvent", function()
    Stop(); unlocked = false;
    if ( Initialize() ) then
        handle:Hide();
        local db = Settings();
        if ( db.x and db.y ) then Place(db.x, db.y); end
    end
end);
