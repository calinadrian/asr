# Complete main build

`asr build-main` assembles the current changes into `downloads/main-build`.
The local build retains version 0.124.4 for compatibility with the existing
co-op service. A public release must receive a new version and matching server
support before publication.

Inputs are the frozen executable under `downloads/race-expansion/baseline`,
the validated expanded character/armor archives and their JSON reports under
`downloads/race-expansion`, the original vanilla client under
`downloads/durotar-assets/vanilla-1.12.1/app/Data`, and the base archives in
`D:\Personal\ASR\Data`. All paths can be overridden through
`python launcher/main_build.py --help`. Output must be a new directory.

The normal stamp pipeline now applies the 26-race catalog and racial kits
before the final story payload. The story retains the current unlock rules:
the original eight races are selectable, while added races remain locked.
Saved characters of added races remain supported.

The build includes upgraded characters and armor, fitted preview cameras,
all six added story zones, the Story/Dungeons map, dungeon floor/spawn and
barricade fixes, updated card artwork and isolated humanoid NPC models.
It rebuilds patch-S, patch-T, patch-U and patch-Z from their owning sources.
Patch-Z includes both artwork and NPC model/DBC overrides; photo-only
publication is refused because replacing it would remove those overrides.

The builder verifies the entire expanded race asset closure and all 38 story
boss bodies, records the installed file hashes in `build.json`, and writes
the reviewed data hashes to `launcher/native-main-build.json`. Public game
publication requires every matching archive in that profile. `publish-data`
packs the verified files without replacing the combined patch-Z.

To install a verified build, preserving rollback copies:

```powershell
tools/python/python.exe launcher/main_build.py --install `
  --backup downloads/main-build-rollback
```

Installation validates candidate hashes, backs up changed installed files,
writes data first and the executable last, and verifies the final hashes.
On failure it restores changed files. Saves and configuration are untouched.
Restart the game to load the combined build.
