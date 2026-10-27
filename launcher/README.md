# Installer, game updates and the old launcher

## ASR-Setup.exe

Players download `ASR-Setup.exe` from the `game` release (built with `.\asr setup` from `launcher/Setup.cs`). It is a normal per-user installer, no administrator rights:

1. **Install to:** `%LOCALAPPDATA%\Programs\ASR` by default, or any folder the player picks (an `ASR` folder is created inside it). It refuses folders it can't write to, which the game needs for its own updates, and folders with other files in them. Running it again finds the existing installation and only downloads what changed.
2. It downloads `base.json`, `patches.json` and `latest.json` from the `game` release and the gzip parts they list, checks each file's SHA-256, and writes the game as `ASR.exe` last, so its presence means the installation is complete.
3. It saves four user environment variables the game reads: `WOW_ROGUE_UPDATE_URL` and `WOW_ROGUE_DATA_URL` (our `game` release), `WOW_ROGUE_COOP_URL` (`wss://game.hassian.duckdns.org:47770/coop/lobby/`) and `WOW_ROGUE_PRESENCE=0` (otherwise the game browses its author's lobby).
4. It adds an **ASR** Start menu shortcut (and a desktop one if chosen), an **ASR** entry in Settings > Apps, `Uninstall ASR.exe` and `asr-install.json` in the folder.

Uninstalling removes the folder, the shortcuts, the entry and those four variables; characters live in the player's AppData and are kept. Nothing of ours runs after installation.

## Game updates

The game updates itself from the `game` release: at start it reads `latest.json`, and when the version there is higher than its own it shows "A new version is out!", downloads the parts, replaces its executable and restarts. It updates data files from `patches.json` the same way. Manifests list each file's size, SHA-256 and gzip parts named relative to the manifest; the game checks the size and hash but no signature, so anyone who controls the GitHub account controls what players run. Publish with:

```powershell
launcher\set_game_icon.ps1 -Exe path\to\AzerothSurvivors.exe
.\asr publish-game path\to\AzerothSurvivors.exe 0.120.8 "What changed"
.\asr publish-data path\to\Data
```

`publish-game` stamps the executable it uploads (`launcher/stamp_game.py`):

It also applies ASR branding (`launcher/brand_game.py`): the exact window title, in-game name in all 12 languages, runtime window/taskbar icon, and Windows executable icon. Branding checks the supported native layout and refuses unknown builds. Reapplying it is safe.


- the version you give, which the game's updater and the co-op lobby read;
- the first 8 characters of this repository's current commit, shown next to it in the game's corner label, e.g. `v0.120.6 (54467733)`; it refuses until that commit is pushed;
- the file-name check removed: the game only updates itself when its file is named `AzerothSurvivors`, and players' copies are `ASR.exe`.

The version must keep the length of the current one (`0.120.6`, not `0.121.10`), be higher than the players' current one, and be accepted by the server (`SUPPORTED_VERSIONS` in `server/native_lobby.py`, then restart the server) before you publish. `server/verify_native_desktop.py --game <exe>` runs two copies of a build in a private co-op party first.

## The old launcher

Players who installed with `ASR.exe` 0.1.8 or earlier have a launcher that starts the game with the same settings and keeps a helper running that forwards co-op through the certificate it pins on TCP 47770. It updates itself from GitHub Releases on [calinadrian/asr](https://github.com/calinadrian/asr/releases): `releases/latest/download/latest-envelope.json`, then `releases/download/v<version>/<sha256>.zip`. Launchers up to 0.1.4 read `https://hassian.duckdns.org:47770/launcher/latest-envelope.json`, which the server mirrors from GitHub. Each release is checked against the release-verification public key the launcher embeds.

The server supports games 0.120.1, 0.120.4, 0.120.5, 0.120.6, 0.120.7 and 0.120.8 / protocol 3 and enforces four people per room. Choose four in the game's Host form; its picker still offers five, but the server refuses a fifth player.

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
