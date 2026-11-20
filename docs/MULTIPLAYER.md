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
