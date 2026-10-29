# Expanded playable roster

The requested list contains **17 additional races**, bringing ASR's roster from
nine to **26**. It includes Worgen, Kul Tiran, Draenei, Earthen, Dark Iron Dwarf,
Lightforged Draenei, Void Elf, Mechagnome, Dracthyr, Haranir, Nightborne,
Highmountain Tauren, Mag'har Orc, Zandalari Troll, Vulpera, Pandaren and Goblin.

The builders operate in the workspace. They do not install files, change saves,
publish a release or modify the retail installation.

## Build

```powershell
python launcher/race_assets.py 'D:\Personal\Battle.net\World of Warcraft' `
  --installed downloads/race-expansion/baseline/Data `
  --listfile downloads/wow-listfile/community-listfile.csv `
  --out downloads/race-expansion/patch-W.MPQ
python launcher/race_armor_assets.py 'D:\Personal\Battle.net\World of Warcraft' `
  --installed downloads/race-expansion/baseline/Data `
  --listfile downloads/wow-listfile/community-listfile.csv `
  --out downloads/race-expansion/patch-V.MPQ
python launcher/race_patch.py downloads/race-expansion/baseline/ASR.exe `
  --assets downloads/race-expansion/patch-W.json `
  --out downloads/race-expansion/ASR.exe
python launcher/verify_race_expansion.py --candidate downloads/race-expansion `
  --installed downloads/race-expansion/baseline/Data `
  --out downloads/race-expansion/validation.json
python -m unittest discover -s launcher -p test_race_expansion.py -v
```

The example uses the frozen original nine-race inputs in `baseline/`, whose
hashes are recorded in `baseline.json`. Character checkpoints retain
source IDs, file hashes and a converter revision; a changed retail build or
altered checkpoint is refused. A failed character prevents emission of a new
playable archive. `build-report.json` records any failures independently of the
last successful archive. Do not mistake an older archive for a failed rebuild.

## Implementation

- Native race IDs remain sparse and match the source data. Draenei is 11,
  Worgen 22, Pandaren 24, Dracthyr 52, Earthen 84 and Haranir 86. Unlisted IDs
  retain Human's lookup/display fallback; widening an interval does not make
  NPC races playable.
- `ChrRaceXChrModel` resolves customization models. Arithmetic such as
  `(race - 1) * 2 + sex + 1` is invalid for newer races. Haranir's internal
  asset folder is `Harronir`; Mag'har uses the shared Orc mesh with its own
  customization model. Both Dracthyr body selectors use the dragon mesh.
- The native catalog, lookup bounds, per-race faction/display/language tables,
  Horde check, class lists, customization loader and run validator are extended.
  The Appearance picker uses bounded faction grids and a 1024×256 portrait
  atlas. Existing equipment scrolling accommodates the larger race picker.
- The W archive preserves the original nine races and adds 34 character models.
  Existing player customization records remain byte-for-byte unchanged.
  New race display IDs use `200000 + race_id * 2 + sex` and are checked for
  collisions. Goblin replaces its previously non-playable race/customization row;
  its old creature display records are retained.
- Collection models contain many mutually exclusive meshes. The builder selects
  only each `ChrCustomizationSkinnedModel` record's exact geoset; zero/negative
  selectors mean none. Hair, beards, horns and mechanical limbs are merged into
  the legacy view, retaining the body's animation rig and attachment points.
  Key bones and exact pivots resolve accessory bindings. Accessory-only secondary
  bones follow a mapped ancestor rather than retaining independent physics.
- Complete body and accessory LODs must fit the 65,535-index legacy view limit.
  Accessories use their smallest complete source LOD; the body uses the first
  complete LOD fitting the combined budget. Geometry is never truncated.
- Dragon body textures use a separate skin-extra atlas rather than the humanoid
  face-strip layout. They remain customizable without painting humanoid armor
  textures over the dragon's body. Retail visage transformation and Worgen human
  transformation are outside this integration.

## Gameplay and compatibility limits

The integration inherits **existing ASR class restrictions** from explicit
templates. Each added race now has its own three-trait ASR passive kit; borrowed
active abilities and template passives are removed. These are survival-game
adaptations of racial themes, not retail spell implementations. Gathering,
profession, damage-school, conditional proc and pet-specific mechanics are
adapted to supported ASR stats, and the tooltip states the exact applied effect.
The update does not introduce Monk/Evoker classes. Added race names and passive
descriptions currently use English in every locale. See [race-passives.md](race-passives.md)
for all kits and verification details.

Neutral races appear in both faction groups as the same saved race identity;
they use the Alliance/default native faction and language rules. This does not
add a separate faction-choice system.

The helmet builder records each source and explicit retail shared-rig alias.
Dragon-form Dracthyr have no substituted humanoid helmets; missing compatible
legacy helmet sources are listed in V's manifest. Equipment stats are unchanged.
Independent accessory physics, layered retail materials and every possible
armor/customization combination require visual compatibility review. Structural
validation does not establish that all combinations look correct.

The native tests execute the actual emitted machine code in a relocated image.
They cover all 256 race-byte lookups, accepted run identities, equipment prefixes,
Horde membership, all class lists, faction picker loops, sparse customization IDs,
portrait coordinates, malformed hooks and repeat application. Archive validation
checks every manifest hash, model structure, texture dependency, character display,
customization geoset and existing player customization record.

## Staged build, 2026-10-29

`downloads/race-expansion/` contains the candidate executable, both archives,
manifests and `validation.json`. The validated candidate has 26 races, 52
character models, 6,374 total models and 32,485 distinct assets. V adds 3,904
helmet variants and lists 278 unsupported variants, including dragon-form
Dracthyr's intentionally absent humanoid helmets. Sixteen targeted tests and
the ten existing retail converter tests pass locally.

Native model fixtures rendered both body types for Dracthyr, Haranir, Earthen,
Mechagnome, Worgen, Kul Tiran and Draenei. These fixtures substitute assets into
an existing character slot to inspect geometry and textures; their headings
still name the fixture character. They are **not evidence of selecting, saving
or entering a run as the new race**. The unmodified picker itself was captured
with all 26 races and their portraits. End-to-end selection, save/reload and live
run verification remain outstanding. The candidate has not been installed.
The installed copy currently has the published nine-race Blood Elf archive after
an updater run; the original HD archive is preserved in the frozen build inputs.
The user's updated installation was left as-is.

Follow-up visual fixes resolve Highmountain horn-color textures through their
default horn-marking dependency, and connect Zandalari tusks to the facial
selector for both body types. Model fixtures confirm textured antlers and
visible tusks. Earthen and Haranir now use separate character head portraits
for both body types, rendered from their converted models, instead of the
achievement symbols used initially.

Character preview cameras are fitted for all 52 models, retaining existing head
portrait cameras and all model geometry, animation and gameplay scales. Framing
allows room for enlarged hair and antler roots, without allowing small effect
roots to zoom the whole character in. The native armory's two yellow floor
gradient stops are transparent. Four camera regression checks cover relative
framing, a common floor baseline, unchanged gameplay data, idempotence and
unknown-native-layout refusal.
All races use the same 10.5-unit camera distance, preserving their actual relative
sizes instead of enlarging small races to fill the same screen height. Each
camera targets the same height above the model's ground so feet share one
baseline rather than centring each body independently.
The shared distance was reduced from 12 units for approximately 14% more zoom;
the target offset changed proportionally to keep the projected floor in place.

## Local co-op smoke test, 2026-10-29

All 17 added races passed a two-native-client localhost join-and-start test
across nine race pairs in Elwynn. Each client reported a two-player connection,
the expected race in its `ready` event, and gameplay `start`. Void Elf and
Dracthyr were tested as Rogue under their inherited class restrictions; the
other races used Warrior. The earlier Warrior fixtures for those two races
were rejected by the existing race/class rules and were superseded by the
allowed-class retests.

Disposable executable fixtures change initial character selection and starter
zone only; native transport, serialization, remote spawning and gameplay code
are unchanged. Fresh guest profiles avoid duplicate saved identity, and the
starter zone is selected before connection to avoid the Durotar unlock gate.
The production executable hash remained unchanged. The user's saves were not
used as writable test profiles.

Evidence: `downloads/race-expansion/coop-test/summary.json`, individual pair logs,
and native game screenshots under `matrix/` and `allowed-class-retest/`.
Sixteen native catalog checks, fourteen lobby checks and eight relay checks
also passed. This is a local smoke test, not cross-PC/public internet validation,
a completed-match or reconnect soak test, exhaustive race/class/sex coverage,
or independent visual verification of every remote character model.
