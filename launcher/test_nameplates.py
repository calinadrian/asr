"""Lua behaviour checks. Requires lupa (test dependency only, not shipped).

PYTHONPATH=downloads/lua-test-runtime python -m unittest discover -s launcher -p test_nameplates.py
"""
from pathlib import Path
import unittest

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None


@unittest.skipIf(LuaRuntime is None, 'Lua tests require lupa')
class NameplatesTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.execute(r'''
table.getn = table.getn or function(t) return #t end
SlashCmdList = {}
local methods = {}
function methods:GetRegions() return unpack(self.regions or {}) end
function methods:GetChildren() return unpack(self.children or {}) end
function methods:GetTexture() return self.texture end
function methods:GetObjectType() return self.kind end
function methods:IsShown() return self.shown end
function methods:SetAlpha(a) self.alpha = a end
function methods:SetWidth(w) self.width = w end
function methods:SetHeight(h) self.height = h end
function methods:GetWidth() return self.width end
function methods:GetHeight() return self.height end
function methods:ClearAllPoints() self.points = {} end
function methods:SetPoint(...) table.insert(self.points, {...}) end
function methods:SetStatusBarTexture(t) self.texture = t end
function methods:SetTexture(...) self.texture = {...} end
function methods:SetFont(...) self.font = {...} end
function methods:SetShadowColor(...) end
function methods:SetShadowOffset(...) end
function methods:RegisterEvent(...) end
function methods:SetScript(k,v) self[k] = v end
function widget(kind)
    return setmetatable({kind=kind, shown=true, alpha=1, points={}, width=110, height=20}, {__index=methods})
end
function methods:CreateTexture() self.background = widget('Texture'); return self.background end
function plate()
    local p = widget('Button')
    p.regions = {widget('Texture'), widget('Texture'), widget('FontString'), widget('FontString'), widget('Texture'), widget('Texture')}
    p.regions[1].texture = 'Interface\\Tooltips\\Nameplate-Border'
    p.regions[2].shown = false
    p.children = {widget('StatusBar')}
    p.children[1].health = 123
    p.click = 'native-click-handler'
    return p
end
function CreateFrame() driver=widget('Frame'); return driver end
WorldFrame=widget('Frame')
p=plate(); unrelated=widget('Frame'); WorldFrame.children={p,unrelated}
function tick() arg1=0.06; driver.OnUpdate() end
''')
        source = Path(__file__).parent / 'addon/ASR_Nameplates/Nameplates.lua'
        self.lua.execute(source.read_text())

    def test_compact_health_and_native_clicks_are_preserved(self):
        self.lua.execute('''tick()
assert(p.children[1].width==72 and p.children[1].height==6)
assert(p.children[1].health==123 and p.click=='native-click-handler')
assert(p.regions[1].alpha==0 and p.regions[4].alpha==0 and p.regions[5].alpha==0)
assert(p.regions[6].width==12 and unrelated.width==110)
p.children[1].health=25; tick(); assert(p.children[1].health==25)
''')

    def test_hover_and_reused_plate_do_not_leak_names(self):
        self.lua.execute('''tick(); assert(p.regions[3].alpha==0)
p.regions[2].shown=true; tick(); assert(p.regions[3].alpha==1)
p.shown=false; tick(); p.shown=true; p.regions[2].shown=false
tick(); assert(p.regions[3].alpha==0)
local bg=p.children[1].background; tick(); assert(p.children[1].background==bg)
''')

    def test_settings_resize_resolution_reset_and_late_spawn(self):
        self.lua.execute('''tick()
SlashCmdList.ASRPLATES('names all'); assert(p.regions[3].alpha==1)
SlashCmdList.ASRPLATES('names off'); assert(p.regions[3].alpha==0)
SlashCmdList.ASRPLATES('size 999 1')
assert(p.children[1].width==140 and p.children[1].height==3)
p.children[1].width=110; tick(); assert(p.children[1].width==140)
q=plate(); WorldFrame.children={p,q}; tick(); assert(q.children[1].width==140)
SlashCmdList.ASRPLATES('reset'); assert(q.children[1].width==72)
assert(ASR_NameplatesDB.names=='hover')
''')

    def test_invalid_saved_settings_recover(self):
        self.lua.execute('''ASR_NameplatesDB={width='bad',height=-7,names='bad'}
tick(); assert(p.children[1].width==72 and p.children[1].height==3)
assert(ASR_NameplatesDB.names=='hover')
''')


if __name__ == '__main__':
    unittest.main()
