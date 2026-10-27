# Windows launcher and updates

After publishing, distribute `downloads/ASR.exe` (also attached to every GitHub release). A build awaiting publication is in `downloads/launcher-candidate/ASR.exe`. It installs its own launcher files under `%LOCALAPPDATA%\ASR` without administrator rights (installations made before the rename keep `%LOCALAPPDATA%\WorldOfSurvive`), checks our update channel, and offers Install game / Play. The co-op game is installed by its author's pinned installer into that personal folder's `game` directory. No downloaded game files are bundled into our executable or committed here.

Our update channel is GitHub Releases on [calinadrian/asr](https://github.com/calinadrian/asr/releases): the launcher reads `releases/latest/download/latest-envelope.json`, then downloads `releases/download/v<version>/<sha256>.zip`. Launchers up to 0.1.4 still read `https://hassian.duckdns.org:47770/launcher/latest-envelope.json`, so every release is also published there; that is how they move to GitHub. Players do not need to configure anything. The launcher embeds our server certificate and release-verification public key; every update is checked against that key whichever host served it. This authenticates our updates; it is separate from Windows Authenticode code signing.

`ASR.exe` is the only program players run. Install game puts the game in the launcher folder's `game` directory; Play starts it with its built-in Co-op menu connected to our service. Installations that chose an existing game with launchers up to 0.1.7 keep using it through `desktop-game.txt`. The native service supports games 0.120.1 and 0.120.4 / protocol 3 and enforces four people per room. Choose four in the game's Host form; its original picker still offers five, but the server refuses a fifth member.

## Game updates

The game updates its own executable from our pre-release `game` on GitHub: the launcher starts it with `WOW_ROGUE_UPDATE_URL=https://github.com/calinadrian/asr/releases/download/game/latest.json` and `WOW_ROGUE_UPDATE_AUTO=1`, so at start it downloads a newer listed version, replaces itself and restarts without asking. Its manifest lists the version, notes, size, SHA-256 and gzip parts named relative to it; the game checks the size and hash but no signature, so anyone who controls the GitHub account controls what players run. Publish a tested executable with:

```powershell
asr publish-game path\to\AzerothSurvivors.exe 0.120.4 "What changed"
```

The version must be higher than the players' current one to reach them, and the server must already accept it (`SUPPORTED_VERSIONS` in `server/native_lobby.py`). The game's data files still update from its author's data manifest.

The launcher starts a separate helper for the lifetime of the desktop game. It passes the game's `WOW_ROGUE_COOP_URL` override to a random, token-protected loopback WebSocket endpoint and forwards that connection through certificate-pinned TLS to `/coop/lobby/` on TCP 47770. The helper survives closing the launcher window and the game's restart after an update, and ends when its game exits. There is no fallback to the original game's public lobby. No normal save file is touched by this integration. `native-network.log` in the launcher folder records connection errors without room tokens or gameplay payloads.

## Publish a client update

Edit `launcher/ASR.cs` and/or our files under `launcher/client/`, then build a candidate and test it from this project folder:

```powershell
asr stage 0.1.7 8
asr test
```

When ready to publish that exact tested candidate:

```powershell
asr publish 0.1.7 8
```

Both the version and integer sequence must increase. Staging compiles the executable, packages our client files and signs the release with RSA/SHA-256 without changing the live channel. The publish command promotes that candidate without rebuilding it, atomically publishes its manifest/signature envelope on our server, then creates the GitHub release `v<version>` with `gh` (log in once with `gh auth login`). If the GitHub step fails, retry it alone with `asr upload <version> <sequence>`. Pushing commits to GitHub does not publish anything; only this command does. Players receive it on their next launcher start or when they choose Check for updates. A running game is never forcibly interrupted; the update check is blocked while that launcher's room browser is running.

The update package can replace only the launcher, `server-cert.pem` and files under `client/`. Inside the package the launcher is still named `WorldOfSurvive.exe`, the only name launchers up to 0.1.6 accept; 0.1.7 and newer install it as `ASR.exe`. A launcher that an older one updated starts as `WorldOfSurvive.exe` once and hands over to `ASR.exe`. It cannot target the game's characters, settings, saves or third-party binaries. Download and extraction limits, per-file hashes, path checks and signature checks run before installation. A separate copy of the launcher waits for the old process to exit before replacing it; an ordinary apply failure restores files from a backup. Staging folders retain backups for recovery. Updates require free space and write access; process crashes or power loss can require retrying the launcher.

The existing co-op updater continues to handle the upstream game and co-op mod through `Start-Coop.cmd`. Our updater does not turn changes to the repository's independent Rust game into compatible co-op patches: changing that executable requires rebuilding the game and updating/testing the co-op mod's supported build profiles. Add such a distribution mechanism only after compatibility is established.

## Operator files

Back up `server/state/release-signing-key.pem` securely. It is private and excluded from Git, the download routes and player packages. Losing it prevents issuing updates accepted by existing launchers. `server/state/updates/` contains the release archives and current signed release. Retain previous archives so clients already downloading can finish.

The current launcher pins the current TLS certificate. Certificate renewal requires preparing a compatibility release with both old and new trust pins before switching the server. Do not simply replace the certificate first: existing launchers will reject the new connection. The initial certificate's validity is one year; plan renewal before expiry. The DuckDNS hostname may continue pointing to a new public IP without rebuilding the launcher.

On the server PC, start the executable once with `--local-server` to save the operator-only LAN connection setting and avoid router hairpin NAT for game connections. Do not use this flag on remote players' PCs. The update channel still uses the public hostname; testing from the host without hairpin support uses the isolated test runner instead.

For local verification, `launcher/test_launcher.py` exercises the compiled updater against a separate TLS fixture server and isolated installation folders. It does not publish test releases to the live channel. The native window can render itself for visual verification with `ASR.exe --render-preview <PNG-path>`.
