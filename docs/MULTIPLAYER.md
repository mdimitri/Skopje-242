# Multiplayer (up to 4 players, no server of ours)

Modules (all `src/`): `mpnet.py` UDP transport (reliable + unreliable), `discovery.py` LAN beacon + STUN + public MQTT notice board,
`mp.py` session / lobby protocol, `mpprofile.py` username + lifetime stats (`profile.json`), `lobby.py` screens, `mpgame.py` in-game sync.
Tests: `tools/test_net.py`, `test_mqtt.py`, `test_mp.py` (lobby), `test_mpgame.py <world_dir>` (sync, groups, PvP, shared things),
`shot_lobby.py` / `shot_players.py` (headless screenshots).

* Star network: guests talk only to the host; the host forwards packets addressed to another guest (`dst`) or to everybody.
* Every PC renders its own camera. Separate players simulate their traffic and pedestrians locally. Players closer than 560 m
  (apart again at 700 m) form a group. The host leads groups that contain the host. Another player can lead a separate group.
  The authority simulates entities around each follower and sends snapshots centered on that follower. A follower keeps its
  simulation running until usable snapshots arrive. If it drifts away or snapshots stop, it adopts nearby puppets back into
  local simulation.
* Each player owns his own character (20 Hz state). Hits on other players are reported by the attacker to the victim (`dmg`),
  who applies them; friendly fire off = hits ignored. Deaths / kills go to `profile.json`.
* Shared things (reliable, via host): parked cars taken (`gone`), car left standing (`drop` / `undrop` / `claim`),
  stolen traffic car (`take`, follower -> authority). Riding a bus: boards the puppet bus; others see nothing drawn for the rider.
* Names clash: do not rename `mpnet.py` / `mpprofile.py` to `net.py` / `profile.py` (tools/net.py and the stdlib `profile` exist).
* Verified with two rendered Windows instances over a local relay with delay, jitter and packet loss. Public STUN, MQTT and
  NAT traversal across independent networks need separate verification.

## Voice chat (src/voice.py)

- Capture/playback through `sounddevice` (PortAudio, in requirements.txt; run.bat installs it). Missing module, missing PortAudio, no mic, refused mic (Windows privacy), busy mic, silent mic (all zeros 3 s), dead stream (watchdog reopens it), callback errors: each is shown as a reason in the lobby and the in-game HUD.
- Wire: mpnet kind `VOICE` (6), unreliable. Star: guests -> host -> other guests; the host stamps the sender pid.
- Codec BC4: blocks of 32 samples, log scale byte + 4-bit mu-law. Tiers (adaptive): 16 kHz 68 kbit/s; 8 kHz 36 kbit/s; 8 kHz + FEC (previous packet repeated) 60 kbit/s. Quality drops at once on listener loss >=3/8 %, jitter >=60 ms, ping >=250 ms or capture overflows, and climbs one step after 10 s good. Manual override in Поставки → Звук.
- Per-speaker jitter buffer: playout delay 40-240 ms from the RFC 3550 jitter estimate, concealment repeats the last frame fading, FEC fills holes.
- Every 2 s each player reports mic state + per-speaker loss/jitter (`vst` -> host -> `vsa`), so the lobby shows both directions ("← Ана" how I hear her, "→ Ана" whether she hears me, "НЕ ПРИМА" when my voice never arrives).
- Test: `python tools/test_voice.py` (no sound card needed).

## Connection ladder and the NAT lab

Guest join order: direct UDP (LAN / hole punch via the notice board) -> birthday punching when the guest is behind
symmetric NAT and the host is not (256 guest ports, host sprays HELLO) -> MQTT relay (packets as binary messages on
`r/<rid>` of the same public broker) when nothing direct works, e.g. symmetric NAT on both sides. NAT type is measured
with two STUN servers and shown in the lobby; a failed join names the technical reason.

`sudo tools/natlab/lab.sh <cone|mixed|symmetric> <loss per router or none> <talk s>` builds two home networks
(both 192.168.1.0/24) behind Linux NAT routers on a fake internet with its own STUN + MQTT (tools/natlab/servers.py)
and runs a host and a guest (tools/natlab/peer.py) through join, chat, start and two-way voice. Needs root + iproute2.
