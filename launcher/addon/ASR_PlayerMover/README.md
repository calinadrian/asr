# ASR Player Frame Mover

Move the character portrait, name, level and health/mana bars together.

Install `ASR_PlayerMover.zip` with **Manage AddOns > Install ZIP...**, enable
**ASR Player Frame Mover** and restart the game. Alternatively, copy this addon
folder into the game's `benilla-config/AddOns` folder.

1. Inside a run, click **Move** at the bottom right of the character frame.
2. Drag the highlighted character frame with the left mouse button.
3. Click **Done** to lock the frame in place.

Your position is saved between runs. It adapts to the screen size and keeps the
frame within the screen. While moving, **Reset** restores the original position.
The mover starts locked each session. While locked, the overlay is hidden and
normal character-frame clicks work. Health and mana remain the game's own bars.

Chat commands `/asrplayer unlock`, `/asrplayer lock`, and `/asrplayer reset`
remain available as shortcuts. No chat command is required to move the frame.

Disable and restart to return control to the native UI. Avoid enabling another
addon that also positions PlayerFrame. Native children anchored to PlayerFrame,
such as pet frames, follow it too.
