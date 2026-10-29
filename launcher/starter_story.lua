-- ASR starter story v1. Loaded with the native ASR API, before optional addons.
-- Read authoritative run metadata; location/subzone names are not mission IDs.
local stories = {
    elwynn = { "Elwynn Forest", "Alliance", 0.35, 0.62, 1,
        "Beneath the calm forests of Elwynn, the first chapter of a greater destiny begins. A young adventurer leaves Northshire Abbey and sets out across Elwynn Forest, helping those in need while unknowingly taking the first steps toward becoming one of Azeroth's greatest heroes." },
    durotar = { "Durotar", "Horde", 1, 0.44, 0.3,
        "Beneath the harsh skies of Durotar, a young warrior begins their journey among the newly founded Horde. Helping their people survive in a rugged land, they battle wild beasts, rebellious quilboar, and ancient threats, unaware that their path will one day shape the fate of all Azeroth." },
};
local watcher = CreateFrame("Frame");
local panel, title, location, body, skip;
local active, age, shown, previousTime, previousZone;
local poll = 0;

local function Layout()
    local width = math.min(760, math.max(280, UIParent:GetWidth() - 80));
    panel:SetWidth(width);
    panel:SetHeight(236);
    body:SetWidth(width - 56);
    -- Let actual wrapped text determine height on smaller windows/UI scales.
    if ( body.GetStringHeight ) then
        panel:SetHeight(math.max(236, body:GetStringHeight() + 128));
    end
end

local function Create()
    if ( panel ) then return; end
    panel = CreateFrame("Frame", "ASRStarterStory", UIParent);
    panel:SetPoint("BOTTOM", UIParent, "BOTTOM", 0, 100);
    panel:SetFrameStrata("DIALOG");
    -- Only the dismiss button takes mouse input. Movement, targeting and the
    -- native co-op clock keep working while the story is on screen.
    panel:EnableMouse(false);
    panel:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } });
    panel:SetBackdropColor(0.025, 0.025, 0.035, 0.96);
    title = panel:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge");
    title:SetPoint("TOP", panel, "TOP", 0, -24);
    title:SetText("A hero is born");
    title:SetTextColor(1, 0.82, 0.35);
    location = panel:CreateFontString(nil, "OVERLAY", "GameFontNormal");
    location:SetPoint("TOP", title, "BOTTOM", 0, -10);
    body = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlight");
    body:SetPoint("TOP", location, "BOTTOM", 0, -18);
    body:SetJustifyH("LEFT");
    body:SetTextColor(0.96, 0.94, 0.88);
    if ( body.SetFont ) then body:SetFont("Fonts\\FRIZQT__.TTF", 16); end
    skip = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate");
    skip:SetWidth(108); skip:SetHeight(24);
    skip:SetPoint("BOTTOMRIGHT", panel, "BOTTOMRIGHT", -18, 14);
    skip:SetText("Continue");
    skip:SetScript("OnClick", function() active = nil; panel:Hide(); end);
    panel:Hide();
end

local function Check()
    local phase = AZS_GetPhase and AZS_GetPhase();
    local time = AZS_GetRunTime and AZS_GetRunTime();
    -- Native wire fields: zone is the stable ID; zname/zsub are display text.
    local zone = AZS_ZONE and AZS_ZONE.zone;
    if ( not phase ) then
        shown = nil; previousTime = nil; previousZone = nil; active = nil;
        if ( panel ) then panel:Hide(); end
        return;
    end
    -- A retry can reset the run clock without reloading FrameXML.
    if ( previousTime and time and time + 2 < previousTime ) then shown = nil; end
    if ( previousZone ~= zone ) then
        shown = nil; active = nil;
        if ( panel ) then panel:Hide(); end
    end
    previousTime = time; previousZone = zone;
    if ( phase == "dead" or phase == "victory" ) then
        active = nil;
        if ( panel ) then panel:Hide(); end
        return;
    end
    if ( shown or not stories[zone] or not time or time > 5 ) then return; end
    if ( phase ~= "ready" and phase ~= "playing" ) then return; end
    Create();
    local story = stories[zone];
    location:SetText(story[1] .. " - " .. story[2]);
    location:SetTextColor(story[3], story[4], story[5]);
    panel:SetBackdropBorderColor(story[3], story[4], story[5], 1);
    body:SetText(story[6]);
    Layout();
    shown = true; active = true; age = 0;
    panel:SetAlpha(0); panel:Show();
end

watcher:SetScript("OnUpdate", function()
    local elapsed = arg1 or 0;
    poll = poll + elapsed;
    if ( poll >= 0.1 ) then poll = 0; Check(); end
    if ( not active ) then return; end
    age = age + elapsed;
    if ( age >= 19 ) then active = nil; panel:Hide(); return; end
    local alpha = math.min(1, age / 0.65, (19 - age) / 0.8);
    panel:SetAlpha(math.max(0, alpha));
end);
watcher:RegisterEvent("DISPLAY_SIZE_CHANGED");
watcher:SetScript("OnEvent", function() if ( panel ) then Layout(); end end);
