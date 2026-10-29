# Character and compatible armor upgrade

This is the original nine-race upgrade pipeline. For the expanded **26-race**
roster, use [race-expansion.md](race-expansion.md) and its separate builders.

The native client reads 1.12 M2 v256 models. Retail files cannot be copied into
its Data directory directly. This pipeline converts the nine playable races
(Human, Orc, Dwarf, Night Elf, Undead, Tauren, Gnome, Troll and Blood Elf), both
sexes, and the compatible armor referenced by the existing item display table.
It preserves item IDs, stats, progression, and the keys/order/flags of existing
customization rows. New retail appearances are mapped onto the existing choices;
this is not a new item catalog or a retail customization UI.

## Build separately from the installed game

Run from the repository root with Python 3.12 or later:

```powershell
python launcher/character_upgrade.py 'D:\Personal\Battle.net\World of Warcraft' `
  --installed 'D:\Personal\ASR\Data' `
  --out downloads/character-upgrade/patch-W.MPQ
python launcher/armor_upgrade.py 'D:\Personal\Battle.net\World of Warcraft' `
  --installed 'D:\Personal\ASR\Data' `
  --listfile downloads/wow-listfile/community-listfile.csv `
  --out downloads/character-upgrade/patch-V.MPQ
python launcher/character_equipment_patch.py 'D:\Personal\ASR\ASR.exe' `
  --out downloads/character-upgrade/ASR.exe
python launcher/verify_character_upgrade.py `
  downloads/character-upgrade/patch-W.MPQ downloads/character-upgrade/patch-V.MPQ `
  --installed 'D:\Personal\ASR\Data' `
  --out downloads/character-upgrade/validation.json
```

Use the original installation as the input when rebuilding. The builders do not
modify either installation or publish anything. Each archive has a JSON manifest
with source FileDataIDs, hashes and any unsupported assets. The native loader
mounts only `patch-?.MPQ`, with exactly one character after the hyphen. The character
builder replaces `patch-W.MPQ`, merging its original race/display tables and atlas
with the upgraded models and customization tables. Armor uses `patch-V.MPQ`.
Multi-character suffixes do not load; a separate lower-priority character archive
would lose to W's existing customization tables. The validator rejects such names.

## Compatibility details

- Keep the complete selected body, clothing and customization geosets. Choose the
  first retail LOD fitting the legacy 65,535-index view limit, rather than removing
  triangles or truncating saved hair choices. Dwarf models and male Undead need a
  lower LOD; the other models in the current build retain LOD 0.
  Modern LOD skin indices are relative to their global vertex window; the converter
  applies `lodVertexBase` before reading vertices and writes the legacy view limit
  separately. See the [skin format specification](https://github.com/sc2-arcade-watcher/WhiteoutLib/blob/libmodkit/docs/M2_FILE_FORMAT_SPECIFICATION.md).
- Expand skeleton tracks and rotations, including Troll's embedded skeleton.
  Remap body and face UVs to the legacy composite layout. Equipment UVs remain
  unchanged. Tauren's fur retains replaceable texture type 8 and its extra skin.
  Tauren's larger retail rig is scaled at its roots to match the legacy head
  attachment height (male 0.776, female 0.837). Bounds follow that scale; helmets,
  shoulders and held items inherit it through the rig, keeping them attached.
- Horns, tusks, jewelry, hair and facial features are mapped to legacy selectors.
  Jewelry uses the default retail color. Facial paint uses the retail mask cut into
  the same face strips as the model UVs. A geoset-only beard has no painted overlay;
  old face overlays must never be reused on a new head. Retail texture repeat flags
  are preserved for hair and eyebrow UVs extending beyond the texture rectangle.
  An unavailable face variation uses another face with the same skin color where
  possible. These mappings can change the appearance of a saved customization;
  they preserve its key, not a pixel-identical old face or hair style.
- Female Tauren has oral-detail UVs in the body region overwritten by the legacy
  face strips. Its extended skin-extra atlas keeps fur on the left and the original
  body palette on the right. Affected oral triangles use that palette while the
  rest of the face retains its ordinary customizable body texture. This avoids
  sampling an unused white patch under the jaw and works across skin colors.
- Import race/sex helmet variants, shared shoulders and existing armor textures.
  Known legacy filename aliases are explicit in `armor_upgrade.ALIASES`. Unsupported
  assets retain the installed version when one exists. They are never filled with
  another race's helmet mesh. Existing armor artwork may itself remain low detail
  in retail; conversion does not create an HD redesign of every old item.
- The reviewed native equipment loader clamps race IDs to 1–8. Blood Elf therefore
  requested Troll helmets. The guarded bridge selects `Be` for race 10 and executes
  the original lookup for every other ID. It uses RIP-relative addresses and adds
  no absolute relocations. Unknown executable layouts are refused; reapplying the
  bridge verifies it without adding another copy.

## Current staged build

The 2026-10-29 preparation contains 18 characters, 2,196 helmet variants, 222
shoulder models and 10,030 armor textures; including supporting character assets,
the two archives contain 18,521 distinct files and 2,436 models. The character
archive also retains W's original supporting race and display records.

Thirty-one source variants are unsupported. Twenty-six also have no corresponding
asset in the original installation (mostly unused Ahn'Qiraj placeholder names).
Five existing assets retain the legacy version: three plate shoulder models whose
retail sources are empty, and the male/female lower torso textures for
`Plate_RaidWarrior_C_01_Chest_TL`. See `validation.json` for exact paths and reasons.

Validation checks archive hashes, model array bounds, vertex/bone/attachment and
triangle ranges, texture dependencies, all 18 character models, every saved
customization key, and the geosets/texture files those rows reference. The bridge
tests execute its machine code for all 256 race IDs and verify that only race 10
changes. Native Armory screenshots provide separate visual evidence; structural
validation alone does not prove that every armor and animation looks correct.
Close-up follow-up checks corrected legacy facial overlays on male Orc, Undead,
Gnome and Night Elf, plus the female Tauren oral-palette collision. The validator
now rejects legacy facial-overlay paths in converted customization rows.

For a local installation, back up the executable and the original `patch-W.MPQ`,
copy both archives, and replace the executable with the tested bridge candidate. Keep
backups until in-game verification is complete. A running game uses its current
assets until restarted. Restore the original W archive and executable, and remove
V (or restore its prior copy), to roll back; this does not require editing saves.

`launcher/install_character_upgrade.py --candidate downloads/character-upgrade
--installed D:\Personal\ASR --backup downloads/character-upgrade/rollback-20261029`
performs inspection only. Add `--apply` to make verified backups, atomically replace
the three files, and verify their hashes. A failed replacement restores prior
files. The backup's `installation.json` records every before/after hash.
