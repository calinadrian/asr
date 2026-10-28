# Blood Elf race — integration draft

Status: investigation only. Nothing in the game or its data has been changed. This
document is not a configuration file loaded by the game.

## Confirmed request

Add Blood Elf as a ninth playable race beside the eight vanilla races already in
the native 0.124 game (Human, Orc, Dwarf, Night Elf, Undead, Tauren, Gnome, Troll).

## Native evidence (0.124.3, `D:\Personal\ASR\ASR.exe`, read-only, 2026-10-28)

The race catalog is an eight-record table at RVA `0x6fe7bc0`, 88 (`0x58`) bytes per
record, in DBC race-ID order. Each record holds five `(ptr, len)` slices and a
`u64` race ID:

| Offset | Field | Orc example |
|---|---|---|
| `0x00` | display name | `Orc` |
| `0x10` | upper-case key | `ORC` |
| `0x20` | passive effects, `(u32 kind, f32 value)` pairs | `(0, 0.10)`: +10% max health |
| `0x30` | active racial ID | `blood_fury` |
| `0x40` | description lines, a slice of `&str` | Blood Fury, Hardiness |
| `0x50` | DBC race ID | `2` |

Passive kinds seen so far: `0` max health, `3` movement speed, `5` damage reduction.
A `(records, 8)` slice at `0x6feff20` sits beside the class list `(0x6fe8ae0, 9)`;
it is probably what the picker iterates.

Race lookup is `race_def(id)` at `0x5ab4f70`. It maps IDs 2..8 through a
seven-entry pointer table (`0x6ff0f90`) and returns Human for anything else, so an
unknown race silently becomes Human instead of failing. Fourteen code sites reference
the Human record: inlined copies of that lookup with their own pointer tables
(`0x7689348`, `0x76bc3d8`, `0x76bc450`, ...), one loop bounded by
`8 * 0x58 = 0x2c0`, and others not yet classified. There are ten
`id - 2 <= 6` comparisons in `.text`.

Other race-indexed data that needs extending: a model path table at `0x6368270`
(`Human`, `Orc`, ... `Troll` beside `Female`/`Male`), icon names at `0x77355b0`,
and per-class allowed-race lists at `0x6f8210b` and `0x6f86a8b`
(`..._ALLOWED`). Translations live in the embedded locale JSON as
`race.<key>.name` and `race.<key>.line1..3`. The Armory's
"Open a race to every class" unlock is stored per race, and its storage
(likely a bitmask or a fixed array) has not been found yet.

## Assets

The 1.12.1 client data has no Blood Elf. `ChrRaces.dbc` stops at Goblin (9),
`CharSections.dbc` covers races 1 to 9, and there is no `Character\BloodElf`
model. Goblin's model and skins are already present.

Blood Elf (DBC race 10) therefore needs:

- `Character\BloodElf\{Male,Female}` models, textures and hair and facial-hair
  geosets in the 1.12 M2 format (version 256, views inside the file).
- Rows for race 10 in `ChrRaces`, `CharSections`, `CharHairGeosets`,
  `CharacterFacialHairStyles` and `CharBaseInfo`, in 1.12 layouts.
- Packing as their own `patch-*.MPQ`, as Durotar's assets are.

Chosen source: the retail 12.1.5 install at `D:\Personal\Battle.net\World of Warcraft`
(build 70575). A WotLK 3.3.5a client would have been the easier source, but none is on
this PC.

## Retail source findings (2026-10-28)

`launcher/casc.py` reads the install by FileDataID (local index v7, encoding table,
TSFM root v2, raw and zlib BLTE blocks; encrypted blocks are refused). It indexes
1.9 million files in about 3 seconds and never writes to the install.

Character models and DB2 tables have no name hashes in the root. Their IDs come from
the community listfile (`wowdev/wow-listfile`, kept locally in the ignored
`downloads/wow-listfile/`).

| | Male | Female |
|---|---|---|
| Model (`MD21`, version 274) | 1100087 | 1100258 |
| Skins (`SFID`, LOD 0 first) | 1100099, 1103060, 1103061, 2130875, ... | 1100298, 1103218, 1103233, 2131915, ... |
| Skeleton (`SKID`) | 1838675: 252 bones, 407 sequences | 1838505: 245 bones, 398 sequences |
| External animation files (`AFID`) | 54 | 54 |
| Vertices in the model / used by LOD 0 | 256,979 / 39,373 | 195,499 / 32,939 |
| Submeshes in LOD 0 | 103 | 114 |

The DB2 tables are WDC5. `CreatureDisplayInfo` has TACT-encrypted sections; the
`ChrModel` and `ChrCustomization*` tables do not.

`launcher/db2.py` reads the WDC5 tables. The chain that defines the race:

- `ChrRaces` 10 is `BloodElf` (prefix `Be`). `ChrRaceXChrModel` links it to `ChrModel`
  19 (male, display 62127) and 20 (female, display 62128). Both use texture layout 121.
- `ChrCustomizationOption` (field 4 is the `ChrModel`) → `ChrCustomizationChoice`
  (field 2 is the option) → `ChrCustomizationElement` (choice, related choice,
  geoset, skinned model, material, ...). The male has 14 options. Skin Color (31),
  Face (20), Hair Style (21), Hair Color (21), Facial Hair (13) and Ears (3) have 1.12
  equivalents. Horns, Blindfold and Tattoo are Demon Hunter options and are dropped.
- `ChrCustomizationMaterial` is (texture target, material resource), and
  `TextureFileData` maps the resource to BLP files. For example, skin choice 1599 gives
  `bloodelfmaleskin00_00_hd.blp` (target 1) and `...nakedpelvisskin00_00_hd.blp` (13).
  Face choice 1626 combined with that skin gives `...faceupper00_00_hd.blp` (5).
  Hair style choices give `scalpupperhair00_00.blp` per hair colour (12).

Textures are BLP2 DXT (DXT5 where there is alpha): a 1024x512 skin, 512x512 faces
and scalp, a 256x128 pelvis. The 1.12 equivalents are 256x256, 128x32 and 128x64.

**Texture layout.** `CharComponentTextureSections` shows that layout 121 (2048x1024)
has the same body sections as the classic layout 1 (1024x1024, the 1.12 256x256 layout
scaled by 4) in its left half. The face (sections 9 and 10) has its own 1024x1024
square on the right instead of the classic strips at (0,640) and (0,768). The converter
therefore remaps UVs instead of baking:

- Body vertices (u < 0.5): u × 2, v unchanged.
- Face vertices (u ≥ 0.5): mapped affinely onto the classic face rectangle,
  (0, 0.625)–(0.5, 1.0).
- Each retail texture is cut and scaled to its 1.12 section size and stored as
  ordinary `CharSections` rows: the face square's top third becomes the face upper
  texture and the rest the face lower texture.

The game then composites Blood Elf skins, faces and underwear like any 1.12 race,
and 1.12 armour textures land in the right body regions.

**Geosets.** LOD 0 has 155,163 (male) and 136,254 (female) indices. Group 0 (body and
21 hair styles) alone is 70,785 for the male. 1.12's 16-bit index starts mean the kept
set should stay below 65,536 indices. Keep groups that exist in 1.12 (0, 1xx–3xx facial,
4xx gloves, 5xx boots, 7xx ears, 8xx–13xx and 15xx clothing). Fold the default choice of
retail-only groups that close the body (for example 20xx feet and 32xx face) into
group 0. Drop the rest (17xx eye glow, 35xx and up, 51xx eyesight, the Demon Hunter
pieces), and drop hair styles until the index count fits.

What the down-conversion to the 1.12 layout (version 256, one file) has to do:

- Merge the model, its `.skel` (bones, sequences, key bones) and the needed `.anim` files.
  Retail keeps no bones or sequences in the model itself.
- Keep only the animations the game plays (stand, walk, run, attacks, casts, death and
  a few more). Move their per-sequence tracks onto 1.12's single global timeline, and
  expand compressed quaternions to the floats 1.12 bones use.
- Build one embedded view from the LOD 0 skin. Its vertex count fits the 16-bit limit.
  Drop retail-only geosets, keep hair and equipment geosets that match 1.12 IDs, and
  use 1.12's 32-byte submesh records.
- Map textures. Types 1 (body), 2 (cape) and 6 (hair) exist in 1.12. Types 9 and 15
  to 20 are retail-only (eyes, jewellery, ...) and must be baked into the body or
  hair texture or dropped. Body skins come from `ChrCustomizationMaterial`, not the
  model's `TXID`, and are handled by the UV remap above.
- Check the native renderer's joint limit against 245 to 252 bones.

## Model converter (`launcher/retail_m2.py`)

`Converter(model, skel, skin, name, keep_ids, geosets, playable)` writes a 1.12 MD20
v256 file:
- bones and their tracks, with retail per-sequence keys moved onto one global timeline
  and int16 quaternions expanded to floats;
- the embedded sequences whose IDs 1.12 knows, and 1.12's PlayableAnimationLookup with
  missing animations falling back to stand;
- attachments, one embedded view built from the LOD 0 skin, textures, materials, lookups,
  and texture weight and transform tracks.

Cameras, events, lights, ribbons, particles and the external `.anim` sequences are
not carried over.

Results with the animation IDs of 1.12 `HumanMale.m2` / `HumanFemale.m2`, checked by
reading the output back (every array, range, lookup and bone index in bounds, unit
quaternions) and by skinning it at the first frame of stand and run:

| | Male | Female |
|---|---|---|
| Sequences | 95 | 94 |
| Vertices / indices | 15,843 / 63,516 | 13,260 / 57,534 |
| Hair styles kept | 6 (geosets 2–7) | 12 (geosets 2–13) |
| Facial hair kept | 6 (102–107) | none |
| File size | 9.9 MB | 10.3 MB |

Geoset mapping used:
- **Kept as is:** 401–404, 501–504, 701–702, 802–803, 902–903, 1002, 1102, 1202,
  1301–1302 and 1502–1504.
- **Folded into geoset 0:** 1801 (bare waist under belts), 2001 (feet), 2201 (torso),
  2301 (hands), 3202 (face), 3301 (eyes) and 3401 (eyebrows).
- **Dropped:** everything else: retail-only clothing variants (505–510, 905, 1104–1105,
  1203–1204, 1303, 1505–1510), eye glows, Demon Hunter pieces and the remaining hair
  styles.
- **Why:** the male's clothing alone is 46,000 indices, so the 65,535 limit leaves room
  for six hair styles.

The eyes (3301) draw a retail eye-colour texture (type 19). `texture_files` turns that
into a type 0 texture naming `Character\BloodElf\BloodElf<Sex>Eyes.blp`. Type 9 is the
Demon Hunter blindfold; batches of any retail-only type without a file are dropped, and
so is a submesh left with no batch (one 6-index submesh in geoset 0).

## Textures (`launcher/blp.py`, `launcher/retail_textures.py`)

`blp.py` decodes BLP2 (palettized, DXT1/3/5, BGRA) at any mip level. It encodes 1.12
DXT1, or DXT3 when there is alpha, with a full mip chain. `retail_textures.Builder`
writes the `CharSections` pieces from the customization tables. Only ordinary player
choices are used: no Death Knight (class mask 32) or Demon Hunter (2048) choices,
nothing that needs an unlock or a requirement other than type 3.

| Section | From (retail target) | 1.12 piece |
|---|---|---|
| 0 skin | 1, left half | `<Sex>\BloodElf<Sex>Skin00_CC` 256x256, face square squeezed into the strips |
| 1 face | 5, face square | `FaceLowerVV_CC` 128x64 + `FaceUpperVV_CC` 128x32 |
| 3 hair | 10 hair colour, 12 scalp | `Hair00_CC` 256x256 (shared by both sexes), `ScalpLower/UpperHairVV_CC` |
| 4 underwear | 13 pelvis, 14 torso | `NakedPelvisSkin00_CC`, `NakedTorsoSkin00_CC` 128x64 |
| 2 facial hair | geosets only | empty rows, one per kept style and hair colour |

| | Male | Female |
|---|---|---|
| Skin colours / faces | 14 / 10 | 14 / 10 |
| Hair colours | 20 | 20 |
| Files / size | 569 / 5.6 MB | 823 / 8.1 MB |
| Build time | 28 s | 33 s |

Checked by compositing skin, face, underwear and scalp the 1.12 way on a 256x256 canvas
and rasterizing the converted models posed at stand. Both show correct faces, eyes,
ears, hair and underwear.

## Tables and archive (`launcher/bloodelf_assets.py`)

`bloodelf_assets.py RETAIL --installed DATA --out patch-W.MPQ` converts both models,
cuts their textures and writes patch-W.MPQ (stored files, built by `photo_archive.build`)
in about a minute. Only `patch.MPQ` carries the DBCs it changes, so no other ASR patch
overrides them. Hair styles are added in display order while the model fits 65,535
indices: 6 for the male, 15 for the female.

| Table | Race 10 rows |
|---|---|
| `ChrRaces` | Human's row with ID 10, the Undead's Horde faction template, displays 15476/15475, prefix `Be`, file string `BloodElf`, name "Blood Elf", no cinematic, Human's customization words |
| `CharBaseInfo` | (10, class) for paladin, hunter, rogue, priest, mage, warlock |
| `CreatureDisplayInfo` / `CreatureModelData` | 15476 and 15475 (TBC's IDs, free in 1.12), copied from the Human displays 49/50, naming `Character\BloodElf\<Sex>\BloodElf<Sex>.mdx` |
| `CharSections` | 428 male and 488 female rows from `retail_textures` |
| `CharHairGeosets` | one per kept hair style, scalp hidden |
| `CharacterFacialHairStyles` | male: clean and six beards (1xx value only); female: one empty row |

The 1.12 layouts confirmed on the installed tables:
- **`CharSections`:** ID, race, sex, section, variation, colour, three textures, flags.
- **`CharHairGeosets`:** ID, race, sex, variation, geoset, show-scalp.
- **`CharacterFacialHairStyles`:** race, sex, variation, three unused words, then 1xx, 3xx and 2xx values.
- **`CharBaseInfo`:** two-byte records.

Before writing, `verify` follows race 10 through the patched tables to every model
file, geoset and texture they name, and the build stops on any gap. The first build
(1,501 files, 35,257,175 bytes) also read back by name through the MPQ reader, and
both extracted models passed the v256 checks. The archive is not installed or published.

## Executable patch (`launcher/bloodelf_patch.py`)

`bloodelf_patch.py ASR.exe --out ASR-bloodelf.exe` applies to the 0.124.3 layout after
`durotar_patch` and refuses anything else. `native-bloodelf.json` lists every site; it was
generated from the installed game with each site asserted against its expected
instruction and target. The patch adds an `.asrrace` section, appends its relocations to
the directory Durotar wrote, and re-applying it changes nothing.

| Mechanism | Before | After |
|---|---|---|
| Race catalog | 8 records at `0x6fe7bc0`, slice `(records, 8)` at `0x6feff20` | 9 records (Blood Elf last) in `.asrrace`, slice count 9 |
| Race ID → record | 5 pointer tables for IDs 2–8, 13 bounds `≤ 6` / `< 7`, Human fallback | one 9-entry table for IDs 2–10 (9 stays Human), bounds `≤ 8` / `< 9` |
| Loops over all races | 3 × `cmp rax, 0x2c0` | `0x318` |
| Faction template (IDs 2–8, default 1) | 2, 3, 4, 5, 6, 115, 116 | + 1 (race 9), 5 (Blood Elf, the Undead's) |
| Player display IDs | female / male tables, default 50 / 49 | + 15475 / 15476 |
| Language / team | Orcish 1, Common 7 | Blood Elf 1 (Horde) |
| Horde test | `0x59 >> (race - 2)` for races below 9 | a bridge using mask `0x159` below 11 |
| Ability catalog | 113 records of 120 bytes; 55 references, 44 `cmp ..., 0x34f8` | 114, with `arcane_torrent`; bounds `0x3570` |
| Locales | 14 embedded JSON files | each gains `race.bloodelf.name`, `line1`–`line3` and `ability.arcane_torrent.name` |

The Blood Elf record:
- **Passives:** damage reduction +5% (kind 5) and cooldowns −5% (kind 2).
- **Active:** `arcane_torrent`.

Arcane Torrent is War Stomp's ability record with:
- the name "Arcane Torrent" and the icon `Spell_Shadow_Teleport` (present in 1.12);
- spell 1449 (Arcane Explosion) for its visual;
- a 20 s cooldown.

It keeps War Stomp's stun: 2 s, radius 8.

The locale lines reuse each language's own Tauren, Night Elf and Gnome phrasing, with the
racial name and number swapped. The race and racial names are the official WoW
localizations where they exist.

Known gaps, left for the in-game check:
- **Cosmetic engine tables:** the temporary portrait name, the item "races allowed"
  tooltip and the race-name list beside `CharStartOutfit` stop at 8. Blood Elf gets
  their fallbacks.
- **Field `+0x75` tables:** sixteen `race - 2`-shaped tables read field `+0x75` of a
  non-player struct; no class lookup reads `+0x74` beside it. They are treated as not
  racial and left alone.
- **Armory unlock and saves:** the per-race unlock and the save format are not mapped.
  Saves are encrypted (`RSE1`).

### In-game check

The game resolves its save folder from the `APPDATA` environment variable plus
`wenilla-rogue`. For a local test, use a copy of the game:
- hard-link its MPQs into a new folder;
- add `patch-W.MPQ` and the patched exe;
- change that exe's `APPDATA` folder name to `wenilla-rogux` (same length);
- start it with `APPDATA` pointing at an empty folder.

The player's characters are then never read or written.

A patched copy started this way (2026-10-28) ran to its menu, responded and logged no
crash. The picker, a Blood Elf run, co-op and saving have not been checked yet: the game's
GPU-rendered window can't be captured for automated inspection.

## Proposed first playable pass

- DBC race ID 10, key `BLOODELF`, name "Blood Elf", in every supported locale.
- Classes: Paladin, Hunter, Rogue, Priest, Mage, Warlock (TBC's set).
- Racials in the existing format:
  - Arcane Torrent (active): every 30 sec, silences and interrupts nearby enemies
    for 2 sec. This needs a new active, so it's new code and not only table data.
  - Magic Resistance: +5% damage reduction (passive kind 5).
  - Arcane Affinity: -5% cooldowns (passive kind unknown; Gnome's Expansive Mind uses one).
  The balance numbers above are placeholders.

## Native patch outline

Follow `durotar_patch.py`: copy the eight race records into a new section, append
Blood Elf, then repoint and validate every site against a reviewed
`native-bloodelf.json`, and refuse unknown layouts. Every lookup that sends
unknown IDs to Human must map 10 to the new record; loops and counts go from 8
to 9. Extend the model path, icon and class-allowed tables the same way. Add the
active racial as a hook. Keep `.asrzone` working and decide which patch owns
the base-relocation directory.

## Verification before release

A fresh character can pick Blood Elf with every allowed class, in both genders.
The model, skin, face and hair load in the picker and in a run without missing-asset
logs. All three racials take effect. A save survives a restart. Old saves are
unchanged. In a co-op party, every peer sees the Blood Elf model, and a peer
without the update is refused, not shown a Human. Use a separate save file.
