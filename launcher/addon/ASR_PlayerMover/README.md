# ASR Player Frame Mover

Move the character portrait, name, level and health/mana bars together. The
selected enemy's portrait and HP frame has its own grip and saved position too.

Install `ASR_PlayerMover.zip` with **Manage AddOns > Install ZIP...**, enable
**ASR Player Frame Mover** and restart the game. Alternatively, copy this addon
folder into the game's `benilla-config/AddOns` folder.

1. Inside a run, click the small six-dot grip at the bottom right of the character frame.
2. Drag the highlighted character frame with the left mouse button.
3. Click **Done** to lock the frame in place.

Your position is saved between runs. It adapts to the screen size and keeps the
frame within the screen. While moving, **Reset** restores the original position.
The mover starts locked each session. While locked, the overlay is hidden and
normal character-frame clicks work. Health and mana remain the game's own bars.
The grip brightens on hover and explains how to move the frame in a tooltip.
While editing, a subtle outline and a compact Done/Reset strip appear; the
portrait and bars stay visible.

Select an enemy to show its target frame, then use that frame's grip to move it.
Its Done and Reset controls work independently of the character frame. Changing
targets keeps the saved position. Resetting one frame leaves the other in place.
Floating health bars above enemies are unaffected.

Chat commands `/asrplayer unlock`, `/asrplayer lock`, and `/asrplayer reset`
remain available as shortcuts. No chat command is required to move the frame.
Use `/asrtarget unlock`, `/asrtarget lock`, or `/asrtarget reset` for the target frame.

Disable and restart to return control to the native UI. Avoid enabling another
addon that also positions PlayerFrame. Native children anchored to PlayerFrame,
such as pet frames, follow it too.
