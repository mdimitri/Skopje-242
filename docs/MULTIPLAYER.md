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

## Join code

The host's room shows `S242-XXXX-...` (Копирај код copies it). It packs version, public ip:port, LAN ip:port, relay id
(stable per player: crc32 of the profile uid) and NAT type, with a 16-bit checksum. The guest pastes it under Внеси код:
case, spaces, dashes and Cyrillic look-alike letters do not matter; a wrong/short code says why. A plain `ip:port`
also works. Joining by code uses the same ladder (plus knocking on the LAN address at the same time). The lab runs it
with `CODE=1 tools/natlab/lab.sh ...`.

Short code: the host also gets a slang word + number („ШМЕКЕР 42“, src/joinwords.py, ~190 words from the slang bible)
and publishes its info on `code/<slug>` of the notice board every 4 s (another game with the same word -> new word).
The guest types it in Внеси код in Cyrillic or Latin; it needs the notice board, the long S242 code does not.
Lab: `WORD=1 tools/natlab/lab.sh ...`.

Lab v2 (2-4 players): `sudo python3 tools/natlab/lab2.py home public 5g strict` - first is the host; profiles home
(normal NAT), public (symmetric NAT), strict (UDP blocked except DNS: relay only, host too), 5g (hotspot behind carrier
symmetric NAT), same (same router as the previous player). Joins use the short word code; prints route + voice per pair.

## Reverse punching, guest-to-guest voice, host migration

- **Reverse punching** (host behind symmetric NAT, guest behind a normal one): the guest posts `rev` in its join notice and knocks on random ports of the host's IP (20 per frame, 8 s); the host opens 256 sockets that all say HELLO to the guest's one public address. The socket that hears the guest becomes that guest's own socket (`Net.alt`). Lab: `lab2.py public home` now connects P2P instead of through the relay.
- **Guest-to-guest voice**: every 2 s the host sends `mesh` (the guests' public UDP addresses and relay ids). Guests knock on each other; once a link answers, voice goes straight there and the guest lists that pid in `vst.dir`, so the host stops relaying its voice to it. LAN addresses are used only by guests that are on the host's LAN. Voice that comes over a direct link is stamped with the pid of that link; other messages on it are ignored.
- **Host migration** (in game, 2+ guests left): when the host goes silent or closes, the guest with the lowest player number becomes host as player 0 (others kept as 90 s ghosts); the rest send `rebind` to it over the direct link or its relay id and keep their player numbers. `Session.migrated` makes mpgame drop puppets and re-sync. Lab: `lab2.py home home home down@0:12:100 40` -> new host in about 1 s, both still hear each other.
