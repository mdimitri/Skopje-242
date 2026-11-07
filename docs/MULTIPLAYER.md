# Multiplayer (up to 4 players, no server of ours)

Modules (all `src/`): `mpnet.py` UDP transport (reliable + unreliable), `discovery.py` LAN beacon + STUN + public MQTT notice board,
`mp.py` session / lobby protocol, `mpprofile.py` username + lifetime stats (`profile.json`), `lobby.py` screens, `mpgame.py` in-game sync.
Tests: `tools/test_net.py`, `test_mqtt.py`, `test_mp.py` (lobby), `test_mpgame.py <world_dir>` (sync, groups, PvP, shared things),
`shot_lobby.py` / `shot_players.py` (headless screenshots).

* Star network: guests talk only to the host; the host forwards packets addressed to another guest (`dst`) or to everybody.
* Every PC simulates the world round its own player. Players closer than 560 m (apart again at 700 m) form a group; the lowest
  numbered member (kept while it stays) is the group's *authority*: it simulates traffic / pedestrians / buses round all members
  (`Traffic.extra`, `Peds.extra`) and sends each follower what is near that follower (15 Hz). Followers run `Sim.client = True`
  and draw puppets; on a split the puppets are adopted into real cars / pedestrians (`Traffic.adopt`, `Peds.adopt`).
* Each player owns his own character (20 Hz state). Hits on other players are reported by the attacker to the victim (`dmg`),
  who applies them; friendly fire off = hits ignored. Deaths / kills go to `profile.json`.
* Shared things (reliable, via host): parked cars taken (`gone`), car left standing (`drop` / `undrop` / `claim`),
  stolen traffic car (`take`, follower -> authority). Riding a bus: boards the puppet bus; others see nothing drawn for the rider.
* Names clash: do not rename `mpnet.py` / `mpprofile.py` to `net.py` / `profile.py` (tools/net.py and the stdlib `profile` exist).
* Not verified: real internet (STUN / public MQTT brokers / NAT hole punching are blocked in the cloud), real window with two players.
