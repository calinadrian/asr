# ASR.exe and updates

`ASR.exe` is the only program players run, and it has no window of its own. On every start it:

1. checks GitHub for a newer signed ASR.exe and, if there is one, installs it quietly and restarts;
2. on the first run only, downloads the game into its folder's `game` directory with a small progress window (`base.json`, `patches.json` and `latest.json` from the `game` release, each file checked against its SHA-256, the executable last);
3. starts the game with co-op on our server and game updates from our GitHub, and stays in the background until the game exits.

A downloaded ASR.exe installs itself under `%LOCALAPPDATA%\ASR` without administrator rights and forwards to that copy (installations made before the rename keep `%LOCALAPPDATA%\WorldOfSurvive`). Installations that chose an existing game with launchers up to 0.1.7 keep using it through `desktop-game.txt`. Problems are written to `asr.log` and `native-network.log` in that folder. A build awaiting publication is in `downloads/launcher-candidate/ASR.exe`.

ASR.exe updates come from GitHub Releases on [calinadrian/asr](https://github.com/calinadrian/asr/releases): it reads `releases/latest/download/latest-envelope.json`, then downloads `releases/download/v<version>/<sha256>.zip`. Launchers up to 0.1.4 still read `https://hassian.duckdns.org:47770/launcher/latest-envelope.json`, which the server mirrors from GitHub. ASR.exe embeds our server certificate and release-verification public key; every update is checked against that key whichever host served it. This authenticates our updates; it is separate from Windows Authenticode code signing.

The server supports games 0.120.1, 0.120.4 and 0.120.5 / protocol 3 and enforces four people per room. Choose four in the game's Host form; its picker still offers five, but the server refuses a fifth player.

## Game updates

The game updates itself, inside the game, from our pre-release `game` on GitHub: ASR.exe starts it with `WOW_ROGUE_UPDATE_URL` (`latest.json`, the executable) and `WOW_ROGUE_DATA_URL` (`patches.json`, data files) pointing there and `WOW_ROGUE_UPDATE_AUTO=1`, so at start it downloads a newer listed version, replaces itself and restarts without asking. Manifests list each file's size, SHA-256 and gzip parts named relative to the manifest; the game checks the size and hash but no signature, so anyone who controls the GitHub account controls what players run. `base.json` holds `patch.MPQ`, which only a fresh install needs. Publish with:

```powershell
launcher\set_game_icon.ps1 -Exe path\to\AzerothSurvivors.exe
.\asr publish-game path\to\AzerothSurvivors.exe 0.120.5 "What changed"
.\asr publish-data path\to\Data
```

The version must be the one the executable itself reports (`publish-game` refuses otherwise, since the game would download it again on every start), higher than the players' current one, and accepted by the server (`SUPPORTED_VERSIONS` in `server/native_lobby.py`, then restart the server) before you publish.

ASR.exe keeps a helper running for the lifetime of the game. It passes the game's `WOW_ROGUE_COOP_URL` override to a random, token-protected loopback WebSocket endpoint and forwards that connection through certificate-pinned TLS to `/coop/lobby/` on TCP 47770. It survives the game's restart after an update and ends when the game exits. There is no fallback to the original game's public lobby (`WOW_ROGUE_PRESENCE=0`). No save file is touched.

## Publish an ASR.exe update

Edit `launcher/ASR.cs` and/or our files under `launcher/client/`, test locally, raise both `version` and `sequence` in `launcher/version.json`, and push to `main`:

```powershell
.\asr stage 0.1.9 10
.\asr test
```

The `Publish launcher` workflow (`.github/workflows/publish.yml`, `launcher/ci_publish.py`) builds on a Windows runner, signs with the `RELEASE_SIGNING_KEY` secret, pins the `SERVER_CERT` secret, and creates the GitHub release. Its build is not the one `asr test` tested: the TLS test needs the server's private key, which stays on this PC, so test the same source before pushing. The server mirrors the release for launchers up to 0.1.4 within ten minutes.

To publish from this PC instead (for example if Actions are down), run `.\asr publish <version> <sequence>` after staging and testing; it promotes that exact tested candidate.

Both the version and integer sequence must increase. Staging compiles the executable, packages our client files and signs the release with RSA/SHA-256 without changing the live channel. The publish command promotes that candidate without rebuilding it, atomically publishes its manifest/signature envelope on our server, then creates the GitHub release `v<version>` with `gh` (log in once with `gh auth login`). If the GitHub step fails, retry it alone with `asr upload <version> <sequence>`. Pushing commits to GitHub does not publish anything; only this command does. Players receive it on their next launcher start or when they choose Check for updates. A running game is never forcibly interrupted; the update check is blocked while that launcher's room browser is running.

The update package can replace only the launcher, `server-cert.pem` and files under `client/`. Inside the package the launcher is still named `WorldOfSurvive.exe`, the only name launchers up to 0.1.6 accept; 0.1.7 and newer install it as `ASR.exe`. A launcher that an older one updated starts as `WorldOfSurvive.exe` once and hands over to `ASR.exe`. It cannot target the game's characters, settings, saves or third-party binaries. Download and extraction limits, per-file hashes, path checks and signature checks run before installation. A separate copy of the launcher waits for the old process to exit before replacing it; an ordinary apply failure restores files from a backup. Staging folders retain backups for recovery. Updates require free space and write access; process crashes or power loss can require retrying the launcher.

## Operator files

Back up `server/state/release-signing-key.pem` securely. It is private and excluded from Git, the download routes and player packages. Losing it prevents issuing updates accepted by existing launchers. `server/state/updates/` contains the release archives and current signed release. Retain previous archives so clients already downloading can finish.

The current launcher pins the current TLS certificate. Certificate renewal requires preparing a compatibility release with both old and new trust pins before switching the server. Do not simply replace the certificate first: existing launchers will reject the new connection. The initial certificate's validity is one year; plan renewal before expiry. The DuckDNS hostname may continue pointing to a new public IP without rebuilding the launcher.

On the server PC, start the executable once with `--local-server` to save the operator-only LAN connection setting and avoid router hairpin NAT for game connections. Do not use this flag on remote players' PCs. The update channel still uses the public hostname; testing from the host without hairpin support uses the isolated test runner instead.

For local verification, `launcher/test_launcher.py` exercises the compiled updater against a separate TLS fixture server and isolated installation folders. It does not publish test releases to the live channel. The native window can render itself for visual verification with `ASR.exe --render-preview <PNG-path>`.
