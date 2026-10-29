# Story chapters

The Story and Dungeons selectors share a compact header row. While either
map is open, the covered character and appearance panels are not spawned,
so their controls cannot receive clicks through the map. Closing the map
restores those panels through the normal picker rebuild. Native regression
calls verify both covered panel gates in all three states. A geometry snapshot
protects every map card position and connector segment. The rule Node template
is verified independently of other headings so suppressing the covered panels
does not remove the connector paths.
Locked overview cards use a short status line so their titles stay readable;
the regular list retains the full boss and zone unlock requirements. The same
compact tabs fit both the regular picker and the map header.

The Story panel follows two faction roads that meet in Stranglethorn Vale:

| Chapter | Alliance | Horde |
|---|---|---|
| 1 | Elwynn Forest | Durotar |
| 2 | Westfall | The Barrens |
| 3 | The Deadmines | Wailing Caverns |
| 4 | Duskwood | Stonetalon Mountains |
| 5 | Stranglethorn Vale (together) | |
| 6+ | Warsong Gulch, Un'Goro Crater, … in the original order | |

`launcher/story_chapters.py` is applied by `launcher/starter_missions.py`, on
the same final payload. It adds Westfall, The Deadmines, The Barrens, Wailing
Caverns, Stonetalon Mountains and Stranglethorn Vale as catalog records 13-18.

## Built zones (phase 2)

Westfall, The Deadmines, The Barrens, Wailing Caverns, Stonetalon Mountains and Stranglethorn Vale are real zones. `launcher/story_assets.py` builds
`patch-S.MPQ` from the vanilla 1.12.1 client (`downloads/durotar-assets/vanilla-1.12.1/app/Data`):
terrain tiles, every WMO, doodad and texture they reference, creature models,
minimap tiles and The Deadmines' loading-screen card. Only files the installed
game lacks are added (1,150 files, about 106 MB in the current local build). Westfall's terrain was already in the game.

```powershell
python launcher/story_assets.py downloads/durotar-assets/vanilla-1.12.1/app/Data `
  --installed downloads/race-expansion/Data --out downloads/story-assets/patch-S.MPQ
```

| Zone | Map | Start | Enemies (creature IDs) | Bosses |
|---|---|---|---|---|
| Westfall | Azeroth (0), area 40 | the Dead Acre fields, (-10850, 900, 35) | goretusks, coyotes, Riverpaw gnolls, murlocs, Defias, Fleshrippers, Harvest Watchers (1620-1631) | Vultros, Old Murk-Eye, Sergeant Brashclaw, Foe Reaper 4000, Klaven Mortwake (1700-1704) |
| The Deadmines | DeadminesInstance (36), area 1581 | the Mast Room at (-291, -515, 49.58) | Defias miners, watchmen, evokers, pirates, goblin craftsmen, a shredder (1640-1651) | Rhahk'Zor, Sneed's Shredder, Gilnid, Mr. Smite, Edwin VanCleef (1710-1714) |

Enemy and boss records are cloned from Elwynn's (stats, timing and loot tier
follow the zone's scaling rank). Bosses keep no inherited adds. The native
creature-query switch routes the new IDs to these records, as it does for
Durotar. Elwynn Forest's last three bosses are now Fedfennel, Princess and
Morgan the Collector, in the same slots, timings, loot and creature IDs; the
Deadmines owns Rhahk'Zor, Mr. Smite and Edwin VanCleef.

Deadmines runs start on level ground in the Mast Room at (-291, -515, 49.58).
The walkable boundary follows the Mast Room and its adjoining western cave.
The original western arch is open; the barricade is at the cave's far choke
point instead. The other barricade is recessed behind its doorway and its
visible frame fits below the arch. A 110-yard safety circle stays outside the
actual polygon boundary. This follows the Monastery's native approach of a
fitted polygon and adjoining passage rather than a circle through the room.

`launcher/deadmines_arena.py` builds `Data/patch-T.MPQ` with barriers inside
the existing passage groups 7 and 20. The root, portal graph and camera groups
are untouched. The southern barrier is at the far end of the tunnel, beyond
its far arch (local y about 60-73), with the arena boundary extended to it.

Visible timber uses an EXT batch with zero lighting alpha: INT-batch alpha is
self-illumination, not ordinary opacity. The boards are DETAIL/non-colliding,
so they cannot form climbable steps. A continuous hidden collision volume
extends below the floor and above the ceiling and seals both sides of each
passage, including the visible gaps between boards.

```powershell
python launcher/deadmines_arena.py downloads/durotar-assets/vanilla-1.12.1/app/Data `
  --out downloads/race-expansion/Data/patch-T.MPQ
```

Stationary elite camps use the native tagged placement table (`+56/+64`), not
the ordinary enemy spawn path. Deadmines creates three camps on checked floor
positions, currently 57-94 yards apart and at least 24 yards from the player
start. Its fourth fallback camp is disabled; other zones retain their original
count. Boss/event placement (`+104/+112`) also uses clear in-dungeon positions.
The original camp AI and encounter membership remain intact. The spawn delay
is 20 seconds; this value is not an aggro radius. Ordinary elite reinforcements
retain normal nearest-clear-cell placement rather than being scattered among
unrelated camps by template ID.

The cave height lookup is enabled during run initialization, before camp
positions are built, instead of waiting for the first ordinary enemy spawn.

The game has no reliable native height data for DeadminesInstance. Its height
lookup (0x5ba3040: rcx = terrain, xmm1/xmm2 = x/y; returns al = found and
xmm0 = height) can return dummy ADT terrain above the mine. The chapter supplies
its own map from `launcher/assets/deadmines_ground.bin`, built by
`launcher/deadmines_ground.py` from the vanilla ADT and AZ_Deadmines_B WMO:

- WMO triangles are rasterized at exact 2-yard cell centres (x -340 to 60,
  y -1020 to -280). Each column keeps its lowest dry floor with standing room.
- Floors are followed from the Mast Room start through steps of at most 3 yards
  per cell. Disconnected roofs and overhead logs are excluded. This correction
  currently covers the connected mine floors, not the disconnected ship/cove.
- Spawnable cells need 8 yards of headroom and level neighbours. They must be
  at least 4 yards inside the room outline and at least 4 yards
  from WMO walls/logs and the new barricades through a 6-yard body height,
  allowing room for elites.
  Triangle clipping checks vertical faces too, rather than only floor cells.
  Both common enemy spawn paths (0x5c005af and 0x5c005f4) snap to the exact
  tested cell centre, even when the random position started in a safe cell.
- Missing cells use the nearest safe cave ground height. Out-of-grid queries
  clamp to safe edge ground. Neither falls back to the native overhead terrain
  while this chapter is active. Other chapters retain their native lookup.

Native regression tests verify the compiled outline and safety radius, both
blocked passage edges, solid barricade coverage in both directions, the Mast Room
start and neighbours, both enemy spawn paths, an overhead-log location that
previously returned ~71 instead of ~50 yards, and lookups outside the map.

## Wailing Caverns

Horde chapter 3 now uses map 43, area 718 (`WailingCaverns`), in the dry
Pit of Fangs chamber. The start is (-31, 451, -101.85), with a 190-yard native
safety circle beyond the room walls. This is a survival arena within the original dungeon.

The twelve enemy records use the dungeon's Deviate beasts, ectoplasms and
Druids of the Fang (IDs 1660-1671). The five-boss schedule is Lady Anacondra,
Lord Cobrahn, Lord Pythas, Lord Serpentis and Mutanus the Devourer (1720-1724).
Creature display IDs were checked against the [CMaNGOS Classic database](https://github.com/cmangos/classic-db).
Stats, timings and loot follow the existing chapter-3 scaling.

Unlike Deadmines, this map has no ADT tiles: its WDT loads a global WMO.
`story_assets.py` follows that WMO's groups, props and texture dependencies
and supplies the original loading-screen artwork. Rebuilding patch-S excludes
the previous patch-S from the installed baseline so earlier chapter assets
are retained in the replacement archive.

`launcher/wailing_ground.py` rasterizes the original Pit of Fangs group at
2-yard cell centres. It follows connected dry floors from the start, rejects
steep surfaces and inadequate headroom, and keeps spawns 4 yards from walls
and 6 yards on the arena side of the lower barricade. The packaged grid has 1,373 safe
spawn cells. Three manual camp anchors also supply boss/event placement:
(-81, 411, -106.85), (1, 475, -90.43), and (-99, 453, -72.30).

`launcher/wailing_arena.py` builds `Data/patch-U.MPQ`: a timber barricade across
the lower tunnel throat, inside WMO group 2. The upper-ramp barricade and its
collision were removed; the upper ramp is open. Existing faces,
the root and the portal/camera graph are preserved. The boards are decorative
and nonclimbable; continuous collision slabs extend from z -130 to -40 so
neither the board gaps nor the sloping floor allow passage. The red safety
circle increased from 95 to 190 yards and lies beyond the whole room, with
at least 15 yards of clearance. The remaining lower barricade closes the dungeon exit.

```powershell
python launcher/wailing_arena.py downloads/durotar-assets/vanilla-1.12.1/app/Data --out downloads/wailing-caverns/Data/patch-U.MPQ
python -m unittest discover -s launcher -p test_wailing_arena.py
```

Both ordinary spawn paths snap to safe cells; cave height lookups use the
correct per-zone floor grid. Run initialization and transitions reset each
cave's flag independently.

Player movement also guards both native grid-height call sites (0x5be8623 and
0x5be8a8f). The physical WMO mover supplies the incoming packet height in
xmm14. If the 2-D grid differs by more than 3 yards, validation retains that
physical height instead of snapping to an overlapping upper/lower ledge.
The correction path cancels its native +0.5 offset when retaining the incoming
height. This is restricted to Wailing; ordinary floor queries and creature
spawn placement retain the grid. Native regression calls cover both directions
of all 538 neighboring wall/ledge discontinuities and inactive-zone behavior.


```powershell
python launcher/wailing_ground.py downloads/durotar-assets/vanilla-1.12.1/app/Data
python -m unittest discover -s launcher -p test_wailing_ground.py
```

The chapter remains after The Barrens and before Stonetalon Mountains. The
Barrens now also uses its own savannah terrain. Current work is a local candidate,
not a published game or data update. Completion, co-op and a full-length
Wailing Caverns victory still need live verification.

## Stonetalon Mountains

Horde chapter 4 uses Kalimdor (map 1), Stonetalon Mountains (area 406), in
Windshear Crag (terrain subarea 461). The start is (1380, -350, 8.7909), one yard above the source terrain floor,
with a 110-yard arena. The vanilla ADT triangles provide normal outdoor
movement and ground heights; the cave ground overrides are inactive here.
Source terrain checks cover the start, all three manually placed elite
camps and two rings around the arena, avoiding the nearby Blackwolf River.

The twelve enemy types include Venture Co. operators, loggers, cutters,
deforesters, engineers, machine smiths and shredders, plus local Windshear,
Deepmoss and Pridewing creatures (1680-1691). The five-boss schedule is XT:4,
XT:9, Foreman Rigger, Taskmaster Whipfang and Gerenzo Wrenchwhistle (1730-1734).
Display IDs were checked against the locally downloaded CMaNGOS Classic
creature table. Boss timings, stats and loot use the existing chapter-4 rank.

`launcher/story_npc_assets.py` merges isolated vanilla NPC meshes and targeted
NPC display/model rows into the existing final `patch-Z.MPQ`, preserving its
zone photos and all playable-race DBC rows. The six Venture Co. goblin displays
now use `Creature/ASRStoryNPC/GoblinMale.m2`, avoiding the upgraded playable
Goblin model whose mesh/UV choices do not match their baked Classic NPC skins.
The same isolation covers the chapter's human and gnome bosses. Rebuild with:

```powershell
python launcher/story_npc_assets.py downloads/durotar-assets/vanilla-1.12.1/app/Data --installed downloads/stonetalon/Data --out downloads/stonetalon/patch-Z-npc-fixed.MPQ
```

`launcher/stonetalon_zone.py` defines the arena and manual camps. The tagged
camp table and boss/event table use the checked positions, with three camps
and no fourth fallback. Clearing Wailing Caverns opens Stonetalon; clearing
Stonetalon continues to the existing Stranglethorn chapter. Saves are unchanged.

`patch-S.MPQ` includes the surrounding Kalimdor tiles, terrain dependencies,
creatures and a dedicated card using the original Kalimdor loading artwork.
The local candidate is `downloads/stonetalon/ASR.exe`, with its own `Data`
folder, including the existing Wailing lower barricade archive. It preserves
the Wailing wall-height guard and open upper ramp. Full Stonetalon victory
and co-op still need live verification; this build has not been published.

```powershell
python -m unittest discover -s launcher -p test_stonetalon_zone.py
```

## Stranglethorn Vale: jungle version

The original arena-based chapter is frozen as a runnable local build under
`downloads/stranglethorn-preserved/`, including its Data folder, executable,
source-before-jungle.zip and snapshot-sha256.json. The independent new build
is `downloads/stranglethorn-jungle/ASR.exe`. The native Gurubashi Arena record
and zone remain unchanged; regression tests compare its compiled bytes.

The new shared chapter 5 uses actual northern Stranglethorn jungle terrain on
Azeroth (map 0, area 33), at (-11920, -180, 18.1614), with a 100-yard arena
radius. The source floor is 17.1614; the start adds one yard of collision
clearance. Source checks cover dry terrain, gentle camp slopes and arena
rings outside both Gurubashi Arena and Zul'Gurub. `stranglethorn_zone.py`
defines the start and three manually placed elite/boss-event anchors.

The boss schedule is Sin'Dall, Bhag'thera, Tethis, Colonel Kurzen and King
Bangalash (1760-1764). These are outdoor Stranglethorn enemies. The chapter
uses 12 local enemy types (1740-1751): jungle cats and raptors, Skullsplitter
trolls, and the elite slots Kurzen Elite, Mosh'Ogg Shaman and Mosh'Ogg Lord.
The bosses have no copied raid phase/add lists. Enemy/boss records use the
existing story scaling and reward rank rather than inherited raid rosters.

The final NPC archive isolates the human and troll NPC meshes from playable
race upgrades, preserving baked NPC torsos and the earlier goblin fixes.
Both faction roads still meet here, then continue to Warsong Gulch. Save IDs,
Wailing's wall guard, its open upper ramp, and the corrected Stonetalon spawn
are retained. Live jungle combat/rendering passed; full victory and co-op
remain unverified. This version has not been published.

```powershell
python -m unittest discover -s launcher -p test_stranglethorn_zone.py
```

## The Barrens

Horde chapter 2 uses the open savannah south of the Crossroads, on Kalimdor
(map 1, area 17), at (-800, -2600, 94.153), with a 150-yard radius. The start
adds one yard above the source terrain floor (93.153). `barrens_zone.py`
checks the start, all three manual elite camps and two arena rings against
dry, gently sloping terrain. Native outdoor movement/height lookup is used.

The boss schedule is Barak Kodobane, Hezrul Bloodmark, Echeyakee, Snort the
Heckler and Humar the Pridelord (1820-1824). Twelve local enemy types
(1800-1811) include plainstriders, zhevras, lions, raptors, Razormane quilboar,
Kolkar centaurs and hyenas. The last three slots are the Barrens elite patrol
NPCs Aean Swiftriver, Hannah Bladeleaf and Marcus Bel, each at a manual camp.
Their source creature rows are rank 2 (rare elite); no raid roster is used.

The story remains Durotar > The Barrens > Wailing Caverns. Durotar's native
gameplay record is unchanged. Existing chapter-2 scaling/rewards and saves
are retained. The final NPC archive now also isolates these humanoid NPCs
from upgraded player models, preserving their baked body atlases.

The complete local build is `downloads/barrens/ASR.exe`, with its own Data
folder. It includes the new Stranglethorn jungle and earlier Wailing,
Stonetalon spawn and NPC-torso corrections. The preserved arena version is
still available separately. Rendering and live combat passed; full victory
and co-op remain unverified. The build has not been published.

```powershell
python -m unittest discover -s launcher -p test_barrens_zone.py
```

## Chapter terrain

All six added chapter zones now use their own terrain and creature rosters.

| Zone | Plays on | Difficulty, rewards and loot as |
|---|---|---|
| Westfall | built | Elwynn Forest |
| The Deadmines | built | Duskwood |
| The Barrens | built | Elwynn Forest |
| Wailing Caverns | built | Duskwood |
| Stonetalon Mountains | built | Duskwood |
| Stranglethorn Vale | built | Warsong Gulch |

## Progress

Saves are unchanged. The native per-class "zones opened" counter is kept.

- A chapter opens once the chapter before it on the hero's road has been
  cleared, using the game's existing per-zone completion records.
- Chapters 1 to 4 are faction roads. Another faction's road chapters can't be
  picked solo.
- Dungeons (chapter 3) are open to both factions: clearing your own road's
  chapter 2 (Westfall or The Barrens) opens The Deadmines and Wailing Caverns.
  Chapter 4 still follows your own road's dungeon.
- Clearing Stranglethorn Vale advances the counter to 3, opening Warsong
  Gulch. From there the original counter rules apply. Victories in chapters
  1 to 4 no longer advance it.
- Older saves keep what they had opened. A counter of 2 (Duskwood reached)
  opens the hero's whole faction road, and 3 or more also opens Stranglethorn.
  A Horde hero that had Duskwood open now has Stonetalon Mountains instead.
- Locked cards name the final boss of the previous zone on the hero's road.

The validator computes an open-zone mask for every hero it checks. The zone
cards, the Armory's drop tables, picker validation and the Story panel's hero
correction all read that mask. It is stored in the patch payload, so the
`.asrrace` section is writable.

## Story map and Dungeons

The Story panel's heading is replaced by two buttons, made with the picker's
own button helper (as for Armory and Talents):

- **Story** opens the panel as one wide map over the picker. The Horde road
  (Durotar, The Barrens, Wailing Caverns, Stonetalon Mountains) runs across the
  top and the Alliance road (Elwynn Forest, Westfall, The Deadmines, Duskwood)
  across the middle; both turn into Stranglethorn Vale. The shared zones
  continue as one chain in unlock order: right to Warsong Gulch and Un'Goro
  Crater, down the right edge to Arathi Basin and Feralas, then back left
  along the bottom to Naxxramas. Gold lines join each card to the next.
- **Dungeons** opens the dungeons this hero has unlocked (The Deadmines and
  Wailing Caverns) as big cards.

The open overlay's button is lit; clicking it again, or picking another zone,
closes it. Every card shows its art, name and status line, and the selected
zone keeps its gold frame.

Status lines: Elwynn Forest and Durotar always show their faction. The other
road chapters (Westfall, Duskwood, The Barrens, Stonetalon Mountains) show
"Alliance only" or "Horde only", except while this hero's own chapter is still
locked, when the lock hint shows instead. The Deadmines and Wailing Caverns
show "Dungeon" once open.

Card art: each story chapter has its own scenery screenshot (Westfall,
Durotar, The Barrens, Stonetalon Mountains, Stranglethorn Vale, The Deadmines,
Wailing Caverns), from Wowhead's Classic zone pages like the native cards'
photos, cropped to 2:1 at 512x256. They are the `loadscreenasr*` textures in
`launcher/zone-photos` (sources in its `sources.json`) and ship in
`patch-Z.MPQ`, which now holds nineteen photos.

`launcher/story_map.py` builds it (the picker is Bevy UI, laid out by taffy):

- The buttons send the zone-pick Action with the IDs `story-map` and
  `dungeon-map`. The zone lookup resolves both to the last picked zone, so
  nothing sees an unknown zone; the picker's rebuild hook sees the ID, sets
  the overlay and restores the real zone as a static String.
- In an overlay the Story column's Node becomes absolute and covers the
  panels, and the card list gets a fixed height. Each card's Node is placed
  in viewport units (Vw/Vh), so the layout keeps its shape at any window size;
  the Dungeons overlay moves every other card off-screen. An opaque backdrop is
  spawned under the cards.
- Connectors are copies of the heading's gold rule (0x110f10 + 0x187c90), with
  the rule's forced 1px height and fading gradient replaced by a solid line.

`test_starter_missions` checks the layout (every zone placed, no overlaps,
connectors never cross a card), runs the rebuild hook natively (open, same
zone keeps it open, another zone closes it, lookup) and every status line for
both factions, locked and unlocked.

## Co-op

Co-op ignores zone progress. A guest of either faction may join and play any
party's map; the lobby lists every room as opened. Heroic difficulty still
needs the guest's own stars for that zone. A guest in a Durotar party still
reports `zoneOk: false` in the party data; it doesn't block anything.

## Native details

Beyond the Durotar profile's references, tier tables and achievement scores,
the Durotar patch's 17 hard-coded 13-zone bounds (loops, boss and completion
table bounds, picker rows) are raised to 19 using each edit's own step. The
new IDs are resolved ahead of the Durotar lookup bridge. Card and Armory order
use a successor table.

## Verification

`python -m unittest test_starter_missions` (run in `launcher/`) executes the
mask routine against a stubbed completion lookup (fresh, partly cleared and
legacy saves for both factions). It also covers card locks, validation
fallbacks, lookup, card order, victory unlocks, faction lines, lock-hint
predecessors and the co-op checks. Live runs covered both factions' Story
lists, Westfall and Stranglethorn stand-in runs, and co-op with a Human guest
in Durotar, an Orc guest in Elwynn, and a fresh Orc guest in Westfall.

## Next

- Phase 2: all added zones are built locally; publishing `patch-S.MPQ` to the game's data feed remains.
- Phase 3: the Story map and Dungeons overlay are built.

Local Wailing candidate: `downloads/wailing-caverns/ASR.exe`, with its own
`Data` folder and `validation.json`. An isolated unattended fixture rendered
the Pit of Fangs and ran combat; it does not validate normal faction unlocks
or completion. The candidate itself contains no fixture overrides.

## Complete boss-body audit

`launcher/audit_story_bodies.py` covers all 38 added bosses: five per built
chapter, five from Durotar, and three retitled Elwynn bosses. Its model-array,
bone, submesh and dependency checks run against the mounted final archive.
`story_npc_assets.py` now selects every built story NPC, the full Durotar
roster and retitled Elwynn bosses, instead of only the newest three zones.

The audit corrected 11 remaining shared-player-model conflicts (Klaven,
Gilnid, Mr. Smite, VanCleef, the four Wailing serpent lords, the two Burning
Blade bosses and Morgan). Stranglethorn's five models were already complete.
The resulting archive protects 41 humanoid display records with eight
isolated Classic character meshes, preserving all playable-race rows/models.

38 individual native boss spawn/render previews completed without missing
body assets. Review fixtures use an accelerated schedule and normalized
scale in a common scene; those preview edits are not in the regular game.
Evidence and per-boss screenshots: `downloads/boss-body-audit/REPORT.md`.
The installed fix is in `downloads/barrens/Data/patch-Z.MPQ`; restart that
local candidate to reload the cached model/texture tables.

```powershell
python launcher/audit_story_bodies.py downloads/barrens/Data --source downloads/durotar-assets/vanilla-1.12.1/app/Data --out downloads/boss-body-audit/body-assets.json
python -m unittest discover -s launcher -p test_story_boss_bodies.py
```
