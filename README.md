# World of Survive

Private source repository for our Windows game integration, native co-op service, and update tooling.

Players should open the game directly. Updates should appear inside the game window; a separate launcher interface is not the intended player flow.

## What is implemented

- Native in-game co-op lobby and relay for desktop game 0.120.1 / protocol 3, with four people per room.
- A certificate-pinned background connection helper; the project Play command opens the game directly.
- Signed update packaging and delivery for our existing desktop integration files.

## What is not connected yet

GitHub commits do not currently trigger game updates. The installed desktop game has an in-game updater, but its current source is not included here. This repository can hold our integration code and tested release metadata; compiling that desktop game from source requires its actual source and build process. The older independent Rust reconstruction in the original workspace is a different game build and is not represented as the installed executable's source.

The intended distribution path is a tested, versioned GitHub release, published through our server to the in-game updater. A build-and-release step is needed between editing code and delivering an update. Private GitHub credentials must stay on the server, never in players' games.

## Local checks

```powershell
python -m unittest discover -s server -p "test_native*.py"
```

See [server/README.md](server/README.md) and [launcher/README.md](launcher/README.md) for the current implementation and its operator prerequisites. The legacy launcher interface remains in the source while the in-game update flow is prepared.

Game art, WoW data, installed game binaries, player saves, server private keys and signing private keys are not stored in Git. Runtime dependencies are supplied separately. Preserve the original game's authorship and notices.
