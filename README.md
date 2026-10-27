# ASR

ASR is an RPG survivor-like game: pick a hero, fight off endless waves, level up and choose upgrades, and survive as long as you can, alone or in co-op with up to four players.

This repository holds what runs around the game: the Windows launcher, the co-op lobby and relay server, and the signed update channel players receive updates through.

## For players

Download `ASR.exe` from the [latest release](https://github.com/calinadrian/asr/releases/latest) and run it. It is the only program you need: it installs itself and the game into your user folder (no administrator rights), keeps both updated, and opens the game with co-op connected to our server. Your characters, settings and saves are never touched by updates.

## How updates reach players

Every [release](https://github.com/calinadrian/asr/releases) here is an update. The launcher reads the newest release, checks its signature against the release key built into it, and only then installs it. A file that was changed or not signed by us is refused, wherever it was downloaded from.

Pushing commits does **not** update anyone. An update goes out when the operator publishes one:

```powershell
asr stage 0.1.8 9
asr test
asr publish 0.1.8 9
```

This builds and signs the launcher, tests it, then publishes it on our server and as a GitHub release. Run `asr` alone for every command, including `asr server` and `asr play`. The game updates itself from the [`game`](https://github.com/calinadrian/asr/releases/tag/game) release, distributed with its author's permission; publish a tested build with `asr publish-game`. Details are in [launcher/README.md](launcher/README.md).

## Running the server

See [server/README.md](server/README.md). Local checks:

```powershell
python -m unittest discover -s server -p "test_native*.py"
```

## License

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE).
