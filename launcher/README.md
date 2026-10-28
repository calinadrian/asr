# Installer, game updates and the old launcher

## ASR-Setup.exe

Players download `ASR-Setup.exe` from the `game` release (built with `.\asr setup` from `launcher/Setup.cs`). It is a normal per-user installer, no administrator rights:

1. **Install to:** `%LOCALAPPDATA%\Programs\ASR` by default, or any folder the player picks (an `ASR` folder is created inside it). It refuses folders it can't write to, which the game needs for its own updates, and folders with other files in them. Running it again finds the existing installation and only downloads what changed.
2. It downloads `base.json`, `patches.json` and `game.json` (`latest.json` on a release from before it existed) from the `game` release and the gzip parts they list, checks each file's SHA-256, and writes the game as `ASR.exe` last, so its presence means the installation is complete.
3. It saves four user environment variables the game reads: `WOW_ROGUE_UPDATE_URL` and `WOW_ROGUE_DATA_URL` (our `game` release), `WOW_ROGUE_COOP_URL` (`wss://game.hassian.duckdns.org:47770/coop/lobby/`) and `WOW_ROGUE_PRESENCE=0` (otherwise the game browses its author's lobby).
4. It adds an **ASR** Start menu shortcut (and a desktop one if chosen), an **ASR** entry in Settings > Apps, `Play ASR.exe`, `Uninstall ASR.exe` and `asr-install.json` in the folder.

Uninstalling removes the folder, the shortcuts, the entry and those four variables; characters live in the player's AppData and are kept.

## Play ASR.exe

The shortcuts start `Play ASR.exe --play`, a copy of ASR-Setup (`launcher/Relay.cs`). It starts the game with `WOW_ROGUE_COOP_URL` pointing at itself on loopback, a connection that never breaks, and carries the lobby traffic to the server's `/coop/relay/`. When the player's internet drops it reconnects every second and resumes the same lobby session; the server keeps the player's place for two minutes and both sides resend what the other missed. The game itself never reconnects to a party or run, so without this a dropped guest leaves the run and a dropped host's party ends. It stays running until the game exits (including the game's restart after an update) and writes `coop-relay.log` next to itself.

What it does not cover: the host's game crashing or quitting still ends the party, and while a link is down the other players' copies of the run stand still. Starting `ASR.exe` directly connects to `/coop/lobby/` without resume. Installations made before Play ASR existed get it with their next in-game update (below), or by running ASR-Setup again.

## Game updates

The game updates itself from the `game` release: at start it reads `latest.json`, and when the version there is higher than its own it shows "A new version is out!", downloads the parts, replaces its executable and restarts. What `latest.json` names is not the game but the update helper, ASR-Setup built from the same source: restarted as `ASR.exe`, it shows "Updating ASR", downloads the game named in `game.json` (same version), adds `Play ASR.exe` and points the shortcuts at it in an ASR-Setup installation, swaps the game in and starts it (through Play ASR, or under the Play ASR that is already running). The game's updater can't add files or change shortcuts, so this is how installations made before Play ASR get it. If the download fails, `ASR.exe` stays the helper and opening ASR again retries; it keeps the replaced helper as `ASR.exe.old` until Play ASR next starts. Old launchers' games have no `asr-install.json`, so the helper only swaps the game in. It updates data files from `patches.json` the same way. Manifests list each file's size, SHA-256 and gzip parts named relative to the manifest; the game checks the size and hash but no signature, so anyone who controls the GitHub account controls what players run. Publish with:

```powershell
launcher\set_game_icon.ps1 -Exe path\to\AzerothSurvivors.exe
.\asr publish-game path\to\AzerothSurvivors.exe 0.120.8 "What changed"
.\asr publish-data path\to\Data
```

`publish-game` stamps the executable it uploads (`launcher/stamp_game.py`):

It also applies ASR branding (`launcher/brand_game.py`): the exact window title, in-game name in all 12 languages, runtime window/taskbar icon, and Windows executable icon. Branding checks the supported native layouts (0.120/0.121 and 0.124.0) and refuses unknown builds; zone cards and the addon refresh bridge support the same two. Reapplying it is safe.


- the version you give, which the game's updater and the co-op lobby read;
- the first 8 characters of this repository's current commit, shown next to it in the game's corner label, e.g. `v0.120.6 (54467733)`; it refuses until that commit is pushed;
- the file-name check removed: the game only updates itself when its file is named `AzerothSurvivors`, and players' copies are `ASR.exe`.

The version must keep the length of the current one (`0.120.6`, not `0.121.10`), be higher than the players' current one, and be accepted by the server (`SUPPORTED_VERSIONS` in `server/native_lobby.py`, then restart the server) before you publish. `server/verify_native_desktop.py --game <exe>` runs two copies of a build in a private co-op party first.

## The old launcher

Players who installed with `ASR.exe` 0.1.8 or earlier have a launcher that starts the game with the same settings and keeps a helper running that forwards co-op through the certificate it pins on TCP 47770. It updates itself from GitHub Releases on [calinadrian/asr](https://github.com/calinadrian/asr/releases): `releases/latest/download/latest-envelope.json`, then `releases/download/v<version>/<sha256>.zip`. Launchers up to 0.1.4 read `https://hassian.duckdns.org:47770/launcher/latest-envelope.json`, which the server mirrors from GitHub. Each release is checked against the release-verification public key the launcher embeds.

The server supports games 0.120.1, 0.120.4, 0.120.5, 0.120.6, 0.120.7, 0.120.8, 0.120.9, 0.121.0, 0.121.1, 0.124.0, 0.124.1, 0.124.2 and 0.124.3 / protocol 3 and enforces four people per room. Choose four in the game's Host form; its picker still offers five, but the server refuses a fifth player.

## Publish an old-launcher update

Edit `launcher/ASR.cs` and/or our files under `launcher/client/`, test locally, raise both `version` and `sequence` in `launcher/version.json`, and push to `main`:

```powershell
.\asr stage 0.1.9 10
.\asr test
```

The `Publish launcher` workflow (`.github/workflows/publish.yml`, `launcher/ci_publish.py`) runs only when started manually from GitHub Actions; pushing commits does not start it. Leave `dry_run` enabled to check the build, or disable it to publish a staged and tested version. It builds on a Windows runner, signs with the `RELEASE_SIGNING_KEY` secret, pins the `SERVER_CERT` secret, and creates the GitHub release. Its build is not the one `asr test` tested: the TLS test needs the server's private key, which stays on this PC, so test the same source before pushing. The server mirrors the release for launchers up to 0.1.4 within ten minutes.

To publish from this PC instead (for example if Actions are down), run `.\asr publish <version> <sequence>` after staging and testing; it promotes that exact tested candidate.

Both the version and integer sequence must increase. Staging compiles the executable, packages our client files and signs the release with RSA/SHA-256 without changing the live channel. The publish command promotes that candidate without rebuilding it, atomically publishes its manifest/signature envelope on our server, then creates the GitHub release `v<version>` with `gh` (log in once with `gh auth login`). If the GitHub step fails, retry it alone with `asr upload <version> <sequence>`. Pushing commits to GitHub does not publish anything; only this command does. Players receive it on their next launcher start or when they choose Check for updates. A running game is never forcibly interrupted; the update check is blocked while that launcher's room browser is running.

The update package can replace only the launcher, `server-cert.pem` and files under `client/`. Inside the package the launcher is still named `WorldOfSurvive.exe`, the only name launchers up to 0.1.6 accept; 0.1.7 and newer install it as `ASR.exe`. A launcher that an older one updated starts as `WorldOfSurvive.exe` once and hands over to `ASR.exe`. It cannot target the game's characters, settings, saves or third-party binaries. Download and extraction limits, per-file hashes, path checks and signature checks run before installation. A separate copy of the launcher waits for the old process to exit before replacing it; an ordinary apply failure restores files from a backup. Staging folders retain backups for recovery. Updates require free space and write access; process crashes or power loss can require retrying the launcher.

## Operator files

Back up `server/state/release-signing-key.pem` securely. It is private and excluded from Git, the download routes and player packages. Losing it prevents issuing updates accepted by existing launchers. `server/state/updates/` contains the release archives and current signed release. Retain previous archives so clients already downloading can finish.

The current launcher pins the current TLS certificate. Certificate renewal requires preparing a compatibility release with both old and new trust pins before switching the server. Do not simply replace the certificate first: existing launchers will reject the new connection. The initial certificate's validity is one year; plan renewal before expiry. The DuckDNS hostname may continue pointing to a new public IP without rebuilding the launcher.

On the server PC, start the executable once with `--local-server` to save the operator-only LAN connection setting and avoid router hairpin NAT for game connections. Do not use this flag on remote players' PCs. The update channel still uses the public hostname; testing from the host without hairpin support uses the isolated test runner instead.

For local verification, `launcher/test_launcher.py` exercises the compiled updater against a separate TLS fixture server and isolated installation folders. It does not publish test releases to the live channel. The native window can render itself for visual verification with `ASR.exe --render-preview <PNG-path>`.

## Native zone cards

`publish-game` also applies `launcher/zone_cards.py` and its reviewed `zone-cards-profile.json`. The supported desktop layout gets larger collapsed rows and unlock text, more padding and separation, quieter artwork behind readable text, and larger boss schedule labels. Selection and unlock rules are unchanged. New constants live in a separate read-only PE section; shared UI constants are never modified. Every code edit checks its original instruction and refuses unknown layouts. Reapplying the patch verifies the existing section and does not add another one.

## Zone scenery photos

The current zone-card patch uses distinct scenery screenshots for all twelve zones, taller photo cards, larger headings and requirements, and a dark backing for readable text. See `launcher/zone-photos/README.md` and `sources.json` for the image sources. Normal loading-screen assets and zone unlock rules are unchanged.

`publish-data` builds and includes `patch-Z.MPQ` from the prepared native textures. Run it before `publish-game`, which checks that the matching photos are present in the live data manifest before uploading a game. Locally, install the archive in Data alongside the patched game. The patch safely upgrades both original supported binaries and the previous ASR zone-card refinement.

The decorative zone-tier dots are omitted. The scroll viewport has 20 px of top and bottom padding so the first card and its hover outline remain inside the visible region; selection, unlock rules and hover feedback are retained.

Locked-zone requirement lines render in red, independently of the normal zone heading colour. The actual unlock checks are unchanged.

To publish only the zone photos while retaining all other data entries, run `.\asr publish-zone-photos` before publishing the game. The existing base-data manifest and earlier game parts stay available to players already downloading.

## Zone lighting

Duskwood and other gloomy or night-time zones author their light colours so dark that walls blend into the ground. `launcher/zone_light.py` builds `patch-Y.MPQ`, which overrides only `DBFilesClient\LightIntBand.dbc`: in every zone and at every time of day, the sun diffuse, ambient and fog colours (rows 0, 1 and 7) darker than a minimum brightness are raised to it, keeping their hue where they can. Brighter colours, the sky and water are unchanged.

The same archive makes the arena's red boundary walls ("Edge of the Battlefield") visible in every zone. They are drawn with the `AuraRed`, `AuraRedShort`, `AuraRedTall` and `AuraRedVeryTall` glow models: additive red smoke at 25-45% strength, covered by the zone's fog. The archive carries those models at full strength, with their colours at full brightness, and unfogged and unlit, so neither fog nor a dark zone hides them.

The table and models are read from the game's own Data folder at publish time, so no game data enters the repository.

`publish-data` builds and includes it. To publish only the lighting while retaining all other data entries, run `.\asr publish-lighting path\to\Data`. To try it locally, build it with `tools\python\python.exe launcher\zone_light.py path\to\Data --out path\to\Data\patch-Y.MPQ`; delete that file to go back to the original lighting.

## Durotar

Durotar is a thirteenth zone and a second starter beside Elwynn Forest. A fresh character may enter either, and a victory in either opens Duskwood; completing one does not complete the other. Its run follows Elwynn's structure, difficulty and rewards, with Durotar terrain, twelve Durotar enemies and five bosses (theme: The Burning Blade). See `docs/durotar-test.md`.

`publish-game` applies `launcher/durotar_patch.py` with its reviewed `native-durotar.json`, after every other executable patch because it owns the base-relocation directory. It supports the 0.124 layout only. The twelve original zone records, Elwynn's enemy and boss tables and the zone tier table are copied into a new `.asrzone` PE section with Durotar appended, and every validated code reference is pointed at the copies. Durotar keeps zone index 12 for its own records, completion and difficulty progress; starter validation, selection, picker availability, victory unlocks and reward/level scaling treat it as Elwynn's rank. The picker and the Armory list Durotar right after Elwynn without changing any zone's index, so saved progress keeps its meaning. Every edit checks its original bytes, unknown layouts are refused, and reapplying verifies the existing section.

The zone's terrain, creatures and card come from a vanilla 1.12.1 client, which is not in the repository. `launcher/durotar_assets.py` builds `patch-X.MPQ` with only the files the game's Data lacks, including baked NPC textures. Publish it before the game, which checks that the live data feed has it:

```powershell
.\asr publish-durotar path\to\vanilla\Data path\to\Data
```

To try it locally, build it with `tools\python\python.exe launcher\durotar_assets.py path\to\vanilla\Data --installed path\to\Data --out path\to\Data\patch-X.MPQ` and patch a copy of the game with `tools\python\python.exe launcher\durotar_patch.py ASR.exe --out ASR-durotar.exe`. Run `python -m unittest discover -s launcher -p test_durotar.py -v` for the patch, asset and release checks.

## Blood Elf race (in progress)

Blood Elf is planned as a ninth playable race (DBC race 10). Its models and textures come from a retail World of Warcraft install, which is not in the repository; see `docs/blood-elf.md`. `launcher/bloodelf_assets.py` builds `patch-W.MPQ` from it. It contains both models down-converted to the 1.12 layout (`retail_m2.py`), their customization textures cut into 1.12 pieces (`retail_textures.py`, `blp.py`), and the installed game's DBCs with race 10 rows. It reads the retail install through `casc.py` and `db2.py` and never writes to it, and it refuses to build if any row names a missing model, geoset or texture.

```powershell
tools\python\python.exe launcher\bloodelf_assets.py "path\to\World of Warcraft" --installed path\to\Data --out downloads\bloodelf\patch-W.MPQ
```

The game does not offer the race until its executable is patched, which is not written yet, so the archive is not published. Run `python -m unittest discover -s launcher -p "test_bl*.py"` and `-p test_retail_m2.py` for the table, converter and texture checks.

## ASR addons

`ASR_Nameplates` is an independent compact nameplate addon: 72 x 6 health bars,
names on hover, no decorative borders or level badges, with native reaction
colours, raid markers and click targeting retained. `/asrplates` lists its size
and name-display options. See `addon/ASR_Nameplates/README.md` for installation.

`launcher/addon/` holds ASR's own addons for the game's AddOns system (WoW 1.12 Lua and XML, read from `benilla-config\AddOns` in the game folder). `ASR_HUD` shows the run's chests on the minimap, from the game's `AZS_CHESTS` addon data, and a health bar with numbers for every boss and lair guardian alive, from `AZS_GetBosses()` and `AZS_GetGuardians()`. Those bars replace the game's own thin ones, so the addon turns off Interface > Show Boss Bars when it loads; turn it back on after removing the addon.

Players open **Options > AddOns > Manage AddOns**. The manager is embedded in the game window and lists catalog addons alongside installed ones. **Install** downloads and verifies a catalog ZIP; **Install ZIP...** imports a local WoW 1.12 addon, including a single-addon GitHub branch ZIP; **Remove** deletes the selected addon's folder after confirmation. Back to game or Escape returns to the native tab. Changes apply on the next run; existing native checkboxes still control whether an installed addon is enabled.

To offer an addon, place its folder and matching `<Folder>.toc` under `launcher/addon/`, then run `.\asr publish-addons`. This uploads ZIPs and `addons.json` to the `game` release, with each archive's size/hash and title/notes/version from the TOC. No GitHub sign-in is needed to browse the public catalog. Data patches cannot carry addons.

The manager and background updater share `AddonStore.cs`. Startup updates only catalog addons already installed with an ASR ownership marker. New entries require an explicit Install, removed addons stay removed through `benilla-config/asr-addons.json`, and local copies are not silently replaced. Extraction rejects traversal, junctions/symlinks, duplicate paths, executable/command-script files, more than 4,096 entries, compressed files over 16 MB, and expansion beyond 64 MB. Replacements are staged outside the game's addon index and roll back on installation failure.

`addon_manager_patch.py` preserves the native process-launch function and its unwind metadata. It redirects one verified string reference from Explorer to `ASRAddOn.exe` and relabels the folder button in all 14 embedded languages. It supports the inspected 0.120/0.121 layout and the upstream 0.123.0 and 0.124.0 handlers, rejects unknown function hashes, and is idempotent. `stamp_game.py` applies it to published games; the existing branding/zone-card patches have their own, narrower build support. The installer and game-update helper install `ASRAddOn.exe` as a copy of ASR-Setup, independently of a running Play ASR relay. The update helper also supplies it to portable and legacy-launcher games without changing their shortcuts or adding an uninstall registration.

Run `python -m unittest discover -s launcher -p test_addon_manager.py -v` for native-patch checks and the Windows compiled-backend contracts. Tests use disposable folders and a fixture catalog; they do not publish or change player files.

Successful installs, ZIP imports and removals also refresh the native AddOns checkbox list. The manager signals its parent game with a per-process marker; the guarded x64 bridge rescans using the game's own parser, releases the old rows, resets scrolling and advances the UI revision. Code and mutable state use separate PE sections, with an extended exception table for normal x64 unwinding. Unknown native layouts are rejected. This refresh updates the list; addon scripts still load at the next run.

The addon manager uses the native Options palette and button styling. `GameUi.cs` reads Friz Quadrata and Morpheus from the player's existing MPQs into process-private font resources; no game font assets are bundled in this repository or installed into Windows. Its centered panel adapts to 640×360 through larger game windows.
