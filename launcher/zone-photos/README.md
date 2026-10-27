# Zone scenery backgrounds

These twelve BLP2 textures are converted World of Warcraft scenery screenshots, used only by ASR's zone-selection cards. Original image and source-page URLs are recorded in `sources.json`; the Warcraft artwork belongs to Blizzard and the screenshots to their respective contributors. These are photographs/screenshots of the game environments, not generated illustrations.

`python launcher/photo_archive.py launcher/zone-photos --out downloads/patch-Z.MPQ` builds the deterministic stored-file archive. The custom `interface/asr/zone-photos_____/` path keeps normal loading screens unchanged. The final archive contains these twelve textures and its listfile, with no scripts or gameplay records.

`publish-data` includes this archive automatically. Publish data before a game build that uses the photo backgrounds; `publish-game` verifies the live data manifest has the matching archive first. For local installation, place `patch-Z.MPQ` in the game's Data folder together with the matching executable.
