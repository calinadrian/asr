# ASR Player Frame Mover

Move the character portrait, name, level and health/mana bars together.

Install `ASR_PlayerMover.zip` with **Manage AddOns > Install ZIP...**, enable
**ASR Player Frame Mover** and restart the game. Alternatively, copy this addon
folder into the game's `benilla-config/AddOns` folder.

1. Inside a run, type `/asrplayer unlock`.
2. Drag the highlighted character frame with the left mouse button.
3. Type `/asrplayer lock` to finish.

Your position is saved between runs. It adapts to the screen size and keeps the
frame within the screen. `/asrplayer reset` restores the original position.
The mover starts locked each session. While locked, the overlay is hidden and
normal character-frame clicks work. Health and mana remain the game's own bars.

Disable and restart to return control to the native UI. Avoid enabling another
addon that also positions PlayerFrame. Native children anchored to PlayerFrame,
such as pet frames, follow it too.
