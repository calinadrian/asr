# Starter missions

Elwynn Forest is the Alliance starter and Durotar is the Horde starter. Both
missions are titled **A hero is born**. Their card descriptions use the supplied Alliance and Horde paragraphs
verbatim.

The Appearance picker lists every race in its faction row, but only the
Classic four per faction are lit and selectable: Human, Dwarf, Night Elf and
Gnome; Orc, Undead, Tauren and Troll. Every other race is a dimmed, empty tile
that can't be clicked and doesn't reveal which race it is. Class restrictions
still apply. Saved characters of other races stay valid, because the picker
filters its own copy of the allowed list and the save validator builds its own.
Unlock requirements for the other races haven't been specified yet.

The zone panel is titled **Story**. Expanded cards show the mission title,
description and boss chips, with no list of regular enemies. Elwynn Forest
always carries "Alliance only" (blue) and Durotar "Horde only" (orange) where
other cards show their lock hint. A Horde hero is placed on Durotar and an
Alliance hero on Elwynn, including right after a race change in the Armory.

`launcher/starter_missions.py` applies after the Durotar and race patches in
`stamp_game.py`. It patches the mission catalog, the English Elwynn title and
panel title, the faction card locks and lines, central character validation
and the live picker check. An old cross-faction starter selection is normalized
through the native string allocation path.
Other zone IDs, difficulty and completion records retain their meanings.

The zones after the starters follow the faction chapters described in
[story-chapters.md](story-chapters.md).

The in-run story narration (`launcher/starter_story.lua`) is **not loaded** for
now; the file and its Lua tests stay in place for when it returns.

Co-op is cross-faction and ignores zone progress; see
[story-chapters.md](story-chapters.md).

Build a separate local candidate:

```powershell
python launcher/starter_missions.py downloads/race-expansion/ASR.exe --out downloads/race-expansion/ASR-story.exe
```

Reapplying validates the payload hash and owned edits. `remove()` verifies
and reverses the final patch before restamping. Race and addon locale copies
are excluded from the original translation-count checks in the branding and
addon-manager patches, so already expanded native builds can be restamped.

Verification includes executing the native card/validation/roster bridges,
carrying race data through the native UI closure, Lua 5.1 story lifecycle
tests, and byte-identical restamping. Visual checks use an isolated client,
config and save under `downloads/starter-missions`; installed player saves
are not used.
