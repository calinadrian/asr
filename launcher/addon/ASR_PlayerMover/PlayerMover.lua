-- An edit-mode overlay leaves the native player frame's scripts untouched.
local player, handle, original, toggle, reset, toolbar;
local grip = {};
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

local function Edit(value)
    Stop();
    unlocked = value;
    if ( unlocked ) then
        handle:Show(); toolbar:Show(); reset:Show();
        toggle:SetWidth(48); toggle:SetText("Done"); toggle:SetAlpha(1);
        for i = 1, table.getn(grip) do grip[i]:Hide(); end
    else
        handle:Hide(); toolbar:Hide(); reset:Hide();
        toggle:SetWidth(22); toggle:SetText(""); toggle:SetAlpha(0.6);
        for i = 1, table.getn(grip) do grip[i]:Show(); end
    end
    if ( GameTooltip ) then GameTooltip:Hide(); end
end

local function Reset()
    Edit(false); ASR_PlayerMoverDB = {};
    player:ClearAllPoints();
    for i = 1, table.getn(original) do player:SetPoint(unpack(original[i])); end
    player:SetUserPlaced(false);
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
    -- Only an outline: the portrait, name and live bars stay unobscured.
    handle:SetBackdrop({ edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 });
    handle:SetBackdropBorderColor(0.85, 0.72, 0.45, 0.45);
    handle:SetScript("OnDragStart", function()
        if ( unlocked ) then player:StartMoving(); moving = true; end
    end);
    handle:SetScript("OnDragStop", Stop);
    handle:SetScript("OnHide", Stop);
    handle:Hide();
    toolbar = CreateFrame("Frame", "ASR_PlayerMoverToolbar", player);
    toolbar:SetWidth(108); toolbar:SetHeight(24);
    toolbar:SetPoint("BOTTOMRIGHT", player, "BOTTOMRIGHT", -6, 2);
    toolbar:SetFrameLevel(handle:GetFrameLevel() + 1);
    toolbar:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 10,
        insets = { left = 3, right = 3, top = 3, bottom = 3 } });
    toolbar:SetBackdropColor(0.055, 0.05, 0.04, 0.95);
    toolbar:SetBackdropBorderColor(0.5, 0.46, 0.36, 0.85);
    toolbar:Hide();
    -- A quiet six-dot grip rather than a permanent action button.
    toggle = CreateFrame("Button", "ASR_PlayerMoverToggle", player);
    toggle:SetWidth(22); toggle:SetHeight(22);
    toggle:SetPoint("BOTTOMRIGHT", player, "BOTTOMRIGHT", -10, 3);
    toggle:SetFrameLevel(handle:GetFrameLevel() + 1);
    local doneText = toggle:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall");
    doneText:SetPoint("CENTER", toggle, "CENTER", 0, 0);
    toggle:SetFontString(doneText);
    for row = 0, 2 do
        for column = 0, 1 do
            local dot = toggle:CreateTexture(nil, "ARTWORK");
            dot:SetTexture(0.85, 0.78, 0.6, 1);
            dot:SetWidth(2); dot:SetHeight(2);
            dot:SetPoint("CENTER", toggle, "CENTER", -3 + column * 6, 5 - row * 5);
            table.insert(grip, dot);
        end
    end
    toggle:SetAlpha(0.6);
    toggle:SetScript("OnClick", function() Edit(not unlocked); end);
    toggle:SetScript("OnEnter", function()
        toggle:SetAlpha(1);
        if ( GameTooltip ) then
            GameTooltip:SetOwner(toggle, "ANCHOR_TOPLEFT");
            GameTooltip:SetText(unlocked and "Save position" or "Move character frame", 1, 0.82, 0.3);
            GameTooltip:AddLine(unlocked and "Click Done to lock the frame." or "Click the grip, then drag the frame.", 1, 1, 1);
            GameTooltip:Show();
        end
    end);
    toggle:SetScript("OnLeave", function()
        if ( not unlocked ) then toggle:SetAlpha(0.6); end
        if ( GameTooltip ) then GameTooltip:Hide(); end
    end);
    reset = CreateFrame("Button", "ASR_PlayerMoverReset", toolbar);
    reset:SetWidth(48); reset:SetHeight(22);
    reset:SetPoint("RIGHT", toggle, "LEFT", -4, 0);
    reset:SetFrameLevel(toggle:GetFrameLevel());
    local resetText = reset:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall");
    resetText:SetPoint("CENTER", reset, "CENTER", 0, 0);
    resetText:SetTextColor(0.75, 0.71, 0.62);
    reset:SetFontString(resetText);
    reset:SetText("Reset");
    reset:SetScript("OnEnter", function() resetText:SetTextColor(1, 0.82, 0.3); end);
    reset:SetScript("OnLeave", function() resetText:SetTextColor(0.75, 0.71, 0.62); end);
    reset:SetScript("OnClick", Reset);
    reset:Hide();
    local db = Settings();
    if ( db.x and db.y ) then Place(db.x, db.y); end
    return true;
end

SLASH_ASRPLAYER1 = "/asrplayer";
SlashCmdList["ASRPLAYER"] = function(message)
    if ( not Initialize() ) then Say("The character frame is not available yet. Try again inside a run."); return; end
    local command = string.lower(message or "");
    if ( command == "unlock" ) then
        Edit(true);
        Say("Drag the highlighted character frame, then click Done.");
    elseif ( command == "lock" ) then
        Edit(false); Say("Position locked.");
    elseif ( command == "reset" ) then
        Reset();
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
        Edit(false);
        local db = Settings();
        if ( db.x and db.y ) then Place(db.x, db.y); end
    end
end);
