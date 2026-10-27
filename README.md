# ASR

ASR is an RPG survivor-like game: pick a hero, fight off endless waves, level up and choose upgrades, and survive as long as you can, alone or in co-op with up to four players.

This repository holds what runs around the game: its installer, the co-op lobby server, and the tools that publish game updates to this repository's releases.

## For players

Download and run **[ASR-Setup.exe](https://github.com/calinadrian/asr/releases/download/game/ASR-Setup.exe)**. Choose where to install (no administrator rights needed); it downloads the game (about 1.4 GB), adds **ASR** to your Start menu and, if you like, your desktop. From then on, open ASR from the shortcut. Uninstall it in Settings > Apps. When a new version is out, the game tells you and updates itself. Co-op rooms are on our server. Your characters, settings and saves are never touched by updates.

## How updates reach players

**The game** updates itself, inside the game, from the [`game`](https://github.com/calinadrian/asr/releases/tag/game) release, distributed with its author's permission. ASR-Setup saves four settings for the player's Windows account that point the game there and at our co-op server (`launcher/Setup.cs`). Publish a tested build with `.\asr publish-game <exe> <version>` and data files with `.\asr publish-data <Data folder>`; players get the game's "A new version is out!" prompt the next time they start it. Pushing commits publishes nothing.

**ASR-Setup.exe** is built with `.\asr setup` and lives on the `game` release next to the game files.

**Old launchers:** players who installed with ASR.exe 0.1.8 or earlier keep using it; it still updates from the newest `v*` release (raise [`launcher/version.json`](launcher/version.json) and push to publish one).

Details are in [launcher/README.md](launcher/README.md).

## This folder on the operator PC

| Path | What | In Git |
|---|---|---|
| `launcher/` | source of `ASR.exe` and its release tools | yes |
| `server/` | the co-op lobby and update server | yes |
| `asr.cmd` | every operator command; run `.\asr` to list them | yes |
| `server/state/` | server certificate and key, release signing key, published updates | **no, private** |
| `tools/python/` | the Python the tools run with | no |
| `downloads/` | local launcher builds, `desktop-launcher/` for `asr play` | no |

## Running the server

Run `.\asr server`. See [server/README.md](server/README.md).

## License

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE).
