# ASR

ASR is an RPG survivor-like game: pick a hero, fight off endless waves, level up and choose upgrades, and survive as long as you can, alone or in co-op with up to four players.

This repository holds what runs around the game: the Windows launcher, the co-op lobby server, and the signed update channel players receive updates through.

## For players

Download `ASR.exe` from the [latest release](https://github.com/calinadrian/asr/releases/latest) and run it. The first time, it downloads the game (about 1.4 GB) into your user folder, no administrator rights needed. After that, ASR.exe just opens the game. The game updates itself from this repository when it starts, and co-op connects to our server. Your characters, settings and saves are never touched by updates.

## How updates reach players

Every [release](https://github.com/calinadrian/asr/releases) here is an update. The launcher reads the newest release, checks its signature against the release key built into it, and only then installs it. A file that was changed or not signed by us is refused, wherever it was downloaded from.

**The game:** it updates itself, inside the game, from the [`game`](https://github.com/calinadrian/asr/releases/tag/game) release, distributed with its author's permission. Publish a tested build with `.\asr publish-game <exe> <version>`, and data files with `.\asr publish-data <Data folder>`.

**ASR.exe** (it has no window; it starts the game with our settings): raise both numbers in [`launcher/version.json`](launcher/version.json) and push. GitHub Actions builds, signs and publishes it; it updates itself quietly the next time a player opens ASR. A push that leaves `version.json` alone publishes nothing.

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
