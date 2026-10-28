# Durotar test zone — integration draft

Status: implemented for the native 0.124 layout (`launcher/durotar_patch.py`,
`launcher/native-durotar.json`, assets from `launcher/durotar_assets.py` as
`patch-X.MPQ`) and applied by `publish-game`. Not yet verified in play: a full
victory opening Duskwood, an old save, and a co-op party. This document is not a
configuration file loaded by the game.

## 0.124 port and local verification (2026-10-28)

The 0.121.1 candidate's sites were remapped to 0.124.1 by masked-instruction
alignment of each function, then reviewed by hand. The zone record (240 bytes),
enemy (80) and boss (104) layouts, the tier table and the zone-ID lookup are
unchanged. 0.124 rewrote picker availability around heroic difficulty, so its
three `zone < unlocked` comparisons are hooked instead of the old string-length
code; difficulty progress lives in sorted `(class, zone)` vectors that accept
index 12, and one new progress list that skipped indexes above 11 now includes
Durotar. Durotar keeps its own difficulty progress. Creature IDs 1600-1611 and
1690-1694 stay clear of the catalog (highest 1594) and the query switch.

Each hook was disassembled after patching, the game was stamped twice through
`stamp_game.py` (stable), and an isolated copy with a separate save ran a
fresh Durotar warrior: the picker offered Durotar with Duskwood locked, the run
loaded red Durotar terrain with scorpids, reached level 5, and logged no missing
assets or panics. The earlier test archive replaced the game's own
`patch-B.MPQ`; Durotar now has its own `patch-X.MPQ`, which also carries the
baked NPC textures the Burning Blade humanoids need.

The zone picker and the Armory's drop tables list zones from a static
(records, count) slice that 0.124.2 left at twelve, so Durotar was missing.
0.124.3 points it at the thirteen-zone catalog, makes both lists visit Elwynn,
Durotar, then the rest (every zone keeps its index, so saved progress is
unchanged), treats Durotar as unlocked in their lock checks, and gives it
Elwynn's tier in the Armory. A victory in either starter raises the class's
unlocked count to two only when it is lower, opening Duskwood without
reducing any progress.

## Confirmed behavior

- Add Durotar as a thirteenth zone; preserve all twelve existing zones.
- Durotar and Elwynn Forest are both available to a new character.
- Completing either starter opens Duskwood, the current next zone, using the
  same character/class progression scope as the existing Elwynn completion.
- Completing one starter must not mark the other as completed. Later unlocks
  continue through the existing progression.
- Preserve existing zone IDs, saved completion records and unlocks. Append
  `durotar` to the internal catalog and display it alongside Elwynn in the picker.

## Proposed first playable pass

Use Elwynn's current run structure, difficulty, rewards, twelve enemy slots and
five timed boss encounters as the initial balance baseline. Use Durotar enemies
and terrain rather than renaming Elwynn or replacing its slot.

Suggested theme: **The Burning Blade**. Begin with scorpids, boars and small
raptors, introduce Razormane quilboar, then Burning Blade cultists and demons.
Candidate boss names include Sarkoth, Fizzle Darkstorm, Zalazane and Gazz'uz;
the final five encounters, their identities, models and abilities need
verification against the asset source before implementation.

Map ID 1, area ID 14. A candidate center from the separate Rust reconstruction
is `(587.5, -4311.4, 19.0)`. This is only a starting point: ground height,
traversability, scenery collision and the full battlefield boundary need a live
check. Do not treat these coordinates as verified for the native game.

## Current native evidence

Read-only inspection on 2026-10-28 of `D:\Personal\ASR\ASR.exe` recovered a
twelve-record native zone catalog at RVA `0x72b48c8`, with 240-byte records
(the first ID string pointer is eight bytes into its record at `0x72b48d0`).
Elwynn has twelve enemy entries, five boss entries, map 0, area 12 and center
`(-9396, -633, 68)`. The game contains bounds checks against twelve zones and
separate lookup tables; extending the data catalog alone is insufficient.

The local source under `downloads/azeroth-survivors-re` contains a different
survivors implementation. It is not the source of the installed client's
`wenilla-rogue` / `wenilla-rogue-app` crates.

All installed MPQ archives were checked for the nine Kalimdor terrain tiles at
indices x=39..41, y=29..31 around the candidate Durotar center. None were present.
The shipped Durotar world-map pictures do not supply playable terrain.
The ignored local report `downloads/durotar-analysis/inspection.json` records
the executable hash, existing zone records and asset checks. No executable or
installed data was changed.

## Full asset source prepared

The user supplied
`D:\Downloads\World_of_Warcraft_Client_and_Installation_Archive\ISO\Wowinstall classic`.
That extracted folder contained only two installer parts. Its sibling
`WoW-1.12.1_install.rar` supplied all four parts and `setup.exe`.

The complete client was extracted into
`D:\Projects\ASR\downloads\durotar-assets\vanilla-1.12.1\app` without executing
the installer. `WoW.exe` reports version 1.12.1, build 5875. The extractor
completed successfully. The Data folder contains thirteen MPQ archives,
totalling 5,270,829,495 bytes, excluding `backup.MPQ`.

All nine proposed arena-adjacent ADTs are present in the full client's
`patch.MPQ`. Each decompresses successfully, has version 18, and contains 256
terrain chunks with valid chunk boundaries. The local
`downloads/durotar-assets/verification.json` records hashes for those nine files
and 220 direct texture/model/scenery dependency names. Dependency names have
been collected, not recursively verified or packaged for ASR yet.

This resolves the missing asset-source requirement. Native catalog and unlock
integration remain unimplemented; the installed ASR game has not been changed.

## Integration requirements

Obtain the owning native source project, or finish a separately validated native
catalog extension. Package the prepared compatible terrain assets. Cover
the picker, zone lookup, enemy/boss tables, co-op serialization, completion
handling, localization, zone photo and progress-count achievements. A native
patch must validate its supported executable layout before writing output.

For the two starter routes, use the existing completion predicate as:
`completed(elwynn) OR completed(durotar)`. Keep downstream conditions intact.
Old saves must continue to unlock Duskwood after Elwynn, and an old save with
no completed zones must gain access to Durotar.

Before release, verify a fresh character sees both starters; victory in either
opens Duskwood; defeat in either does not; old progress survives; Durotar runs
load terrain and all scheduled enemies/bosses; boundaries are traversable and
visible; and peers agree on the selected zone and completion rewards. Use a
separate save file for local gameplay verification.
