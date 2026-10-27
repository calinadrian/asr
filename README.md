# ASR

ASR is an RPG survivor-like game: pick a hero, fight off endless waves, level up and choose upgrades, and survive as long as you can, alone or in co-op with up to four players.

This repository holds what runs around the game: the Windows launcher, the co-op lobby and relay server, and the signed update channel players receive updates through.

## For players

Download `WorldOfSurvive.exe` from the [latest release](https://github.com/calinadrian/asr/releases/latest) and run it. It installs itself into your user folder (no administrator rights), checks for updates every time it starts, and opens the game with co-op connected to our server. Your characters, settings and saves are never touched by updates.

## How updates reach players

Every [release](https://github.com/calinadrian/asr/releases) here is an update. The launcher reads the newest release, checks its signature against the release key built into it, and only then installs it. A file that was changed or not signed by us is refused, wherever it was downloaded from.

Pushing commits does **not** update anyone. An update goes out when the operator publishes one:

```powershell
& '.\Azeroth Survivors Together\.coop-runtime\python.exe' launcher\release.py --version 0.1.5 --sequence 6 --stage-only
& '.\Azeroth Survivors Together\.coop-runtime\python.exe' launcher\test_launcher.py
.\Publish-Client-Update.cmd 0.1.5 6
```

This builds and signs the launcher, tests it, then publishes it on our server and as a GitHub release. Updates cover the launcher and its client files; the game executable itself is not distributed here. Details are in [launcher/README.md](launcher/README.md).

## Running the server

See [server/README.md](server/README.md). Local checks:

```powershell
python -m unittest discover -s server -p "test_native*.py"
```

## What is not in this repository

Game art and data, installed game binaries, player saves, the server's TLS private key and the release signing key. Runtime dependencies are supplied separately. The co-op mode builds on [Azeroth Survivors Together](https://github.com/bymarvin/azeroth-survivors-together); its authorship and notices are preserved.

## License

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE).
