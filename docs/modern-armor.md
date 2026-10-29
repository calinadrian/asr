# Modern armor for the built story chapters

The existing early armor items now use coordinated modern WoW class artwork
and converted equipment meshes. This is an appearance replacement: collection
keys, ownership, item names, stats, prices, boss rewards and drop probabilities
retain their existing meanings. The native gear catalog's first two display
arrays change; its later appearance arrays and gameplay fields are preserved.

The current story loot tables intentionally share tiers:

| Existing armor tier | Built zones using it | Appearance |
|---|---|---|
| 0 | Elwynn, Durotar, Westfall, Barrens, Deadmines, Wailing Caverns, Duskwood, Stonetalon | First modern class set |
| 1 | Stranglethorn Vale | Second modern class set |

There are **18 class looks**, two each for Warrior, Paladin, Hunter, Rogue,
Priest, Shaman, Mage, Warlock and Druid. The same item keeps its appearance
wherever it is used, including later zones that share an early loot tier.
Higher armor tiers are not replaced. Weapons and shields are unchanged.

Each set supplies eight armor-slot displays, sex-specific or unisex body
materials, shoulders and compatible race/body helmet variants. New display
IDs occupy a checked, previously unused range under 65536. Original
ItemDisplayInfo records remain byte-identical, preserving unrelated armor
and story NPC outfits. The new archive is `patch-R.MPQ`; upgraded characters
and the existing compatible armor remain in W and V.

Starting clothes also use the class's first modern body materials. The native
starting-item display cache and CharStartOutfit visual fields are updated;
their item IDs are preserved. The native packed-outfit layout check remains
active and verifies the new intended Human Warrior outfit instead of requiring
the old shirt/pants/boots displays. Empty armor slots remain empty and grant
no equipment bonuses.

The prepared archive contains 144 display rows and 900 helmet variants.
Dragon-form Dracthyr still has no compatible humanoid helmets; its 36 omitted
variants are recorded explicitly. This does not substitute another race's mesh.
The original converter's material/geometry limits still apply: these are
compatible native armor appearances, not the retail client's layered armor
renderer or particle effects.

Build the archive from the local retail installation:

```powershell
tools/python/python.exe launcher/modern_armor_assets.py `
  'D:\Personal\Battle.net\World of Warcraft' `
  --installed downloads/main-build/Data `
  --listfile downloads/wow-listfile/community-listfile.csv `
  --out downloads/modern-armor/patch-R.MPQ
```

The builder validates converted models and dependencies, requires the core
clothing materials for both sexes, records source FileDataIDs and hashes, and
updates the reviewed archive hash in `launcher/native-modern-armor.json`.
`asr build-main` includes that archive and refuses a missing or mismatched
version. Native tests verify that only the intended appearance fields change.

Native review uses disposable executable fixtures and copies of the save;
the original profile is never opened as a writable test save. Evidence is
under `downloads/modern-armor/previews` and `user-copy-review`.

Full eight-piece review uses `launcher/preview_modern_armor.py --candidate
<staged-build> --save <read-only-source-save>`. Each disposable executable
forces all eight real armor item IDs at the equipment resolver, independently
of ownership; the copied profile and fixture executables are never installed.
Native character screenshots are under `downloads/modern-armor/full-armory`.

Retail additive effect passes needing unsupported shaders are omitted while
retaining solid armor geometry. Chest materials receive matching opaque fabric
under the retail texture where retail-only layered meshes would otherwise
leave holes. These corrections are covered by material and native-patch tests.
