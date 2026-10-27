# ASR

Windows players install and update a native four-player co-op client, browse public rooms on Hassian's server inside the game window, and play with other people over the internet. The operator hosts the directory and relay at hassian.duckdns.org and publishes client updates. These product and platform requirements were confirmed in this conversation.

## Platform

Windows desktop. The desired player flow opens the game directly and offers updates inside the game window, without a separate launcher interface. The current desktop game's own Co-op menu connects to our native lobby. Background connection support can remain invisible to the player. Each match needs a player host; this is not a persistent shared world or a dedicated gameplay server.

## Source and update distribution

The public GitHub repository is `calinadrian/asr`. It stores our server and desktop integration source. The installed native game's current source is not present here; the independent Rust reconstruction in this workspace is a different build. Distributing a tested native game build and compiling that game from source are separate capabilities. The native game's existing in-game update interface should be used for the player-facing update flow. Launcher and client-file updates are delivered from its GitHub Releases, published by `asr publish`; a push alone publishes nothing.

## Constraints

Use the existing verified third-party co-op installer for the game, preserve its authorship, and keep our signed release channel separate. Player characters and settings must survive updates. Downloaded game assets, private signing keys and server keys never enter source control. Internet reachability depends on the operator's port forwarding. Do not promise zero lag.
