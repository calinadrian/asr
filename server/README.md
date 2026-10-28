# ASR server

`asr server` runs everything players connect to, on HTTPS port 47770:

- `/coop/lobby/`: the in-game co-op lobby. It supports games 0.120.1 to 0.121.1 and 0.124.0 (protocol 3; 0.124.0 adds the run's difficulty to the hero record), relays game traffic between the players of each room and allows at most four people per room, host included. Choose four in the game's Host form; its picker still offers five, but the server refuses a fifth player. Rooms live in memory, so a restart closes them. Its public list starts with an "Update ASR for co-op reconnects" entry (code `UPDATE`, never a real room) telling players to restart ASR and accept the update; clicking it shows the same advice. Games connected through `/coop/relay/` don't see it.
- `/coop/relay/`: the same lobby for games started by `Play ASR.exe` (see [launcher/README.md](../launcher/README.md)), over resumable sessions (`server/native_relay.py`). A player whose link drops keeps their place for two minutes; messages for them wait here (up to 32 MB) and are delivered when they reconnect. After that, or when their game closes the connection, they leave as on `/coop/lobby/`.
- `/launcher/`: the update channel for launchers up to 0.1.4. Every 10 minutes the server copies the newest signed release from GitHub into `server/state/updates/` (`server/mirror.py`), so those players keep updating. Newer launchers read GitHub directly.

Leave it running; it does not start by itself after a reboot. Launchers keep the game's co-op connection on loopback and forward it to this port with certificate pinning.

## This PC

`asr play` opens the game in `downloads/desktop-launcher/desktop-game.txt` (`D:\Personal\World of Survival\AzerothSurvivors.exe`) with co-op on this server over the LAN, which avoids the router's missing hairpin NAT.

## Router and firewall

Reserve this PC's address, `192.168.100.10`, and forward TCP 47770 to it. The ISP must provide a reachable public IPv4. Keep `hassian.duckdns.org` pointing at the current public address.

Run `server/Enable-Coop-Firewall.ps1` once in an administrator PowerShell. It allows TCP 47770 for `tools\python\python.exe` on Ethernet's Public profile only.

## Certificate

The server's certificate and private key are in `server/state/`; keep that folder private. Launchers pin this certificate, so renewing it needs a launcher release that trusts both the old and new certificate before the server switches. The certificate lasts one year. `public_server.py configure --host <hostname> --lan <LAN-IP>` creates one on a fresh `server/state`.

## Checks

```powershell
tools\python\python.exe -m unittest discover -s server -p "test_native*.py"
tools\python\python.exe server\verify_native_server.py
tools\python\python.exe server\verify_native_desktop.py --game "D:\Personal\World of Survival\AzerothSurvivors.exe"
```

The second needs the running server; the third starts two real games against a private test lobby. None of them prove reachability from outside your network.
