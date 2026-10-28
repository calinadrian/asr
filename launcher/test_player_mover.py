"""Player mover Lua contracts; uses the same optional lupa runtime as test_nameplates."""
from pathlib import Path
import unittest

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None


@unittest.skipIf(LuaRuntime is None, 'Lua tests require lupa')
class PlayerMoverTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.execute('''
SlashCmdList={}; frames={}
local methods={}
function frame()
 return setmetatable({points={},shown=true,width=250,height=100,scale=1,scripts={}}, {__index=methods})
end
function methods:GetNumPoints() return #self.points end
function methods:GetPoint(i) return unpack(self.points[i]) end
function methods:ClearAllPoints() self.points={} end
function methods:SetPoint(...) table.insert(self.points,{...}) end
function methods:GetWidth() return self.width end
function methods:GetHeight() return self.height end
function methods:SetWidth(value) self.width=value end
function methods:SetHeight(value) self.height=value end
function methods:SetAlpha(value) self.alpha=value end
function methods:SetFontString(value) self.font=value end
function methods:SetTextColor(...) end
function methods:CreateTexture() local t=frame(); self.textures=self.textures or {}; table.insert(self.textures,t); return t end
function methods:SetTexture(...) end
function methods:GetEffectiveScale() return self.scale end
function methods:GetCenter() return self.x,self.y end
function methods:GetFrameLevel() return 1 end
function methods:SetMovable(v) self.movable=v end
function methods:SetClampedToScreen(v) self.clamped=v end
function methods:SetUserPlaced(v) self.userPlaced=v end
function methods:StartMoving() self.moving=true end
function methods:StopMovingOrSizing() self.moving=false end
function methods:SetScript(k,v) self.scripts[k]=v end
function methods:Hide()
 local was=self.shown; self.shown=false
 if was and self.scripts.OnHide then self.scripts.OnHide() end
end
function methods:Show() self.shown=true end
function methods:SetAllPoints(...) end
function methods:SetFrameLevel(...) end
function methods:EnableMouse(...) end
function methods:RegisterForDrag(...) end
function methods:SetBackdrop(value) self.backdrop=value end
function methods:SetBackdropColor(...) end
function methods:SetBackdropBorderColor(...) end
function methods:CreateFontString() return frame() end
function methods:SetText(text) self.text=text end
function methods:RegisterEvent(...) end
function CreateFrame(_,name,parent)
 local f=frame(); f.parent=parent; table.insert(frames,f)
 if name then _G[name]=f end
 return f
end
UIParent=frame(); UIParent.width=1000; UIParent.height=800
PlayerFrame=frame(); PlayerFrame.points={{'TOPLEFT',UIParent,'TOPLEFT',20,-20}}
TargetFrame=frame(); TargetFrame.points={{'TOPLEFT',UIParent,'TOPLEFT',300,-20}}
TargetFrame.scripts.OnClick=function() end; nativeTargetClick=TargetFrame.scripts.OnClick
local click=function() end; PlayerFrame.scripts.OnClick=click; nativeClick=click
function command(c) SlashCmdList.ASRPLAYER(c) end
function enter() frames[1].scripts.OnEvent() end
function targetEnter() frames[2].scripts.OnEvent() end
function drag(x,y)
 ASR_PlayerMoverHandle.scripts.OnDragStart()
 PlayerFrame.x=x; PlayerFrame.y=y
 ASR_PlayerMoverHandle.scripts.OnDragStop()
end
''')
        self.lua.execute((Path(__file__).parent / 'addon/ASR_PlayerMover/PlayerMover.lua').read_text())

    def test_drag_saves_and_lock_preserves_native_clicks(self):
        self.lua.execute('''enter(); assert(not ASR_PlayerMoverHandle.shown)
command('unlock'); assert(ASR_PlayerMoverHandle.shown)
drag(500,400); assert(ASR_PlayerMoverDB.x==0.5 and ASR_PlayerMoverDB.y==0.5)
assert(not PlayerFrame.userPlaced and not PlayerFrame.moving)
command('lock'); assert(not ASR_PlayerMoverHandle.shown)
assert(PlayerFrame.scripts.OnClick==nativeClick)
''')

    def test_saved_position_scale_resolution_and_clamping(self):
        self.lua.execute('''ASR_PlayerMoverDB={x=0.5,y=0.5}; PlayerFrame.scale=0.5
enter(); assert(PlayerFrame.points[1][4]==1000 and PlayerFrame.points[1][5]==800)
UIParent.width=1600; enter(); assert(PlayerFrame.points[1][4]==1600)
command('unlock'); drag(-200,99999)
assert(PlayerFrame.points[1][4]>=125)
assert(PlayerFrame.points[1][5]<=1550)
''')

    def test_reset_during_drag_restores_original_anchors(self):
        self.lua.execute('''enter(); command('unlock')
ASR_PlayerMoverHandle.scripts.OnDragStart(); PlayerFrame.x=500; PlayerFrame.y=400
command('reset'); assert(not PlayerFrame.moving and not ASR_PlayerMoverHandle.shown)
assert(ASR_PlayerMoverDB.x==nil)
assert(PlayerFrame.points[1][1]=='TOPLEFT' and PlayerFrame.points[1][4]==20)
''')

    def test_missing_frame_can_be_initialized_later(self):
        self.lua.execute('''local saved=PlayerFrame; PlayerFrame=nil
enter(); command('unlock'); assert(ASR_PlayerMoverHandle==nil)
PlayerFrame=saved; command('unlock'); assert(ASR_PlayerMoverHandle.shown)
''')

    def test_bad_saved_position_uses_original(self):
        self.lua.execute('''ASR_PlayerMoverDB={x='bad',y=1}; enter()
assert(PlayerFrame.points[1][1]=='TOPLEFT' and ASR_PlayerMoverDB.x==nil)
''')

    def test_visible_toggle_moves_and_locks_without_chat(self):
        self.lua.execute('''enter()
assert(ASR_PlayerMoverToggle.shown and ASR_PlayerMoverToggle.width==22)
assert(ASR_PlayerMoverToggle.text=='')
assert(not ASR_PlayerMoverReset.shown)
ASR_PlayerMoverToggle.scripts.OnClick()
assert(ASR_PlayerMoverHandle.shown and ASR_PlayerMoverReset.shown)
assert(ASR_PlayerMoverToggle.text=='Done')
drag(500,400); ASR_PlayerMoverToggle.scripts.OnClick()
assert(not ASR_PlayerMoverHandle.shown and not ASR_PlayerMoverReset.shown)
assert(ASR_PlayerMoverToggle.text=='' and ASR_PlayerMoverDB.x==0.5)
assert(PlayerFrame.scripts.OnClick==nativeClick)
''')

    def test_reset_button_and_world_change_restore_locked_controls(self):
        self.lua.execute('''enter(); ASR_PlayerMoverToggle.scripts.OnClick()
drag(500,400); ASR_PlayerMoverReset.scripts.OnClick()
assert(ASR_PlayerMoverDB.x==nil and PlayerFrame.points[1][1]=='TOPLEFT')
assert(ASR_PlayerMoverToggle.text=='' and not ASR_PlayerMoverHandle.shown)
ASR_PlayerMoverToggle.scripts.OnClick(); enter()
assert(ASR_PlayerMoverToggle.text=='' and not ASR_PlayerMoverReset.shown)
''')

    def test_grip_hover_and_unobscured_edit_state(self):
        self.lua.execute('''enter()
assert(not ASR_PlayerMoverToolbar.shown)
assert(#ASR_PlayerMoverToggle.textures==6 and ASR_PlayerMoverToggle.alpha==0.6)
ASR_PlayerMoverToggle.scripts.OnEnter(); assert(ASR_PlayerMoverToggle.alpha==1)
ASR_PlayerMoverToggle.scripts.OnLeave(); assert(ASR_PlayerMoverToggle.alpha==0.6)
ASR_PlayerMoverToggle.scripts.OnClick()
assert(ASR_PlayerMoverToolbar.shown and ASR_PlayerMoverHandle.backdrop.bgFile==nil)
for _,dot in ipairs(ASR_PlayerMoverToggle.textures) do assert(not dot.shown) end
ASR_PlayerMoverToggle.scripts.OnClick()
assert(not ASR_PlayerMoverToolbar.shown and ASR_PlayerMoverToggle.width==22)
for _,dot in ipairs(ASR_PlayerMoverToggle.textures) do assert(dot.shown) end
''')

    def test_target_drag_saves_independently_and_preserves_native_clicks(self):
        self.lua.execute('''ASR_PlayerMoverDB={x=0.3,y=0.4}; enter(); targetEnter()
assert(ASR_TargetMoverToggle.shown and not ASR_TargetMoverHandle.shown)
ASR_TargetMoverToggle.scripts.OnClick()
ASR_TargetMoverHandle.scripts.OnDragStart(); TargetFrame.x=700; TargetFrame.y=500
ASR_TargetMoverHandle.scripts.OnDragStop(); ASR_TargetMoverToggle.scripts.OnClick()
assert(ASR_PlayerMoverDB.target.x==0.7 and ASR_PlayerMoverDB.target.y==0.625)
assert(ASR_PlayerMoverDB.x==0.3 and ASR_PlayerMoverDB.y==0.4)
assert(TargetFrame.scripts.OnClick==nativeTargetClick and not TargetFrame.userPlaced)
targetEnter(); assert(TargetFrame.points[1][4]==700)
''')

    def test_frame_resets_do_not_erase_other_position(self):
        self.lua.execute('''ASR_PlayerMoverDB={x=0.3,y=0.4,target={x=0.7,y=0.625}}
enter(); targetEnter(); command('reset')
assert(ASR_PlayerMoverDB.x==nil and ASR_PlayerMoverDB.target.x==0.7)
ASR_PlayerMoverDB.x=0.3; ASR_PlayerMoverDB.y=0.4
SlashCmdList.ASRTARGET('reset')
assert(ASR_PlayerMoverDB.x==0.3 and ASR_PlayerMoverDB.target.x==nil)
assert(TargetFrame.points[1][1]=='TOPLEFT' and TargetFrame.points[1][4]==300)
''')

    def test_target_can_appear_later_and_saved_player_settings_survive(self):
        self.lua.execute('''local target=TargetFrame; TargetFrame=nil
ASR_PlayerMoverDB={x=0.3,y=0.4}; enter(); targetEnter()
assert(ASR_TargetMoverToggle==nil and ASR_PlayerMoverDB.x==0.3)
TargetFrame=target; targetEnter()
assert(ASR_TargetMoverToggle.shown and ASR_PlayerMoverDB.x==0.3)
''')


if __name__ == '__main__':
    unittest.main()
