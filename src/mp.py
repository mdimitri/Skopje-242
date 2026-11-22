"""Multiplayer session: lobby protocol (join, roster, chat, settings, start) on top of net.Net. No UI, no raylib.

The host owns the world; guests send inputs and render what the host sends (added in later steps).
"""
import os
import random
import struct
import threading
import time
import zlib

import discovery
import joinwords
import mpnet as net

VER = 1
MAX_PLAYERS = 4
COLORS = [(230, 60, 60), (60, 140, 235), (80, 200, 90), (240, 200, 60)]      # red blue green yellow
COLOR_NAMES = ["црвена", "сина", "зелена", "жолта"]


class Session:
    def __init__(self, prof):
        self.prof = prof
        self.net = None
        self.role = None                      # "host" | "guest"
        self.state = "idle"                   # idle | connecting | lobby | playing | closed
        self.error = ""
        self.pid = 0
        self.players = {}                     # pid -> {"name","color","uid","addr"}
        self.cfg = {"spawn": 0, "ff": False}
        self.chat = []                        # (pid or -1, text)
        self.gid = prof.uid
        self.start_info = None
        self.route = ""                       # how the guest reached the host: LAN | internet | same router
        self._rx = self._tx = 0
        self._rate = (0.0, 0.0)
        self._rate_at = time.monotonic()
        self.ready = False                    # host: public address resolved, listening
        self.pub = None
        self.lan = None
        self.mqtt = None
        self.found = {}                       # internet games seen on the notice board: id -> info
        self._punch = {}                      # addr -> give-up time (host answering a join notice)
        self._adv = self._adv2 = 0.0
        self._busy = False
        self._spraying = set()
        self.blips = []
        self._ghosts = {}                     # host: uid -> (pid, player, time gone) for rejoining in game
        self._rec = None                      # guest: {"at", "stage", "old"} while recovering a dead link                       # "join" / "leave" for the UI to chime (lobby and game)
        self.word = ""                        # host: short code „шмекер 42“ (published on the notice board)
        self.code_hits = {}                   # guest: slug -> host info heard on code/<slug>
        self._bd = []                         # guest: birthday-punch sockets
        self.nat = None                       # cone | symmetric | multi-ip | None (not measured)
        self.host_nat = None                  # guest: the host's NAT type from its notice-board entry
        self.voice = None                     # voice.Voice, set by the lobby; packets go through this session
        self.vstats = {}                      # pid -> {"mic": code, "rx": {pid: [recv, lost, late, jitter ms, bad]}, "at": time}
        self._vst_at = 0.0

    # ------------------------------------------------------------------ host
    def host(self, internet=True):
        self.role, self.state = "host", "lobby"
        threading.Thread(target=net.ensure_firewall, daemon=True).start()
        try:
            self.net = net.Net(net.PORT, accept=True)
        except OSError:
            self.net = net.Net(0, accept=True)
        self.net.probe_rtt = True
        self.net.rid = zlib.crc32(self.prof.uid.encode()) & 0x7FFFFFFF     # stable: a join code stays valid after a restart
        self.pid, self.players = 0, {0: self._me(0)}
        self.lan = discovery.Lan()
        if internet:
            self._busy = True
            threading.Thread(target=self._host_net, daemon=True).start()
            self.mqtt = discovery.Board(["join/" + self.gid, "join/r%d" % self.net.rid], self._on_mqtt)
            self.net.use_relay(self.mqtt)                # guests whose UDP cannot get through come in over the notice board
            self._new_word()
        self.ready = True

    def _host_net(self):
        for _ in range(4):
            self.pub = discovery.stun_addr(self.net.sock)
            if self.pub or self.state != "lobby":
                break
            net.log("host: STUN gave no public address, asking again")
        self.nat = discovery.nat_kind(self.net.sock, self.pub)
        net.log("host: NAT type %s" % self.nat)
        net.log("host: UDP port %d, public address %s, ver %d" % (self.net.port, self.pub, VER))
        self._busy = False

    def _new_word(self):
        self._word_try = getattr(self, "_word_try", -1) + 1          # same word every time you host (friends remember it)
        rng = random.Random(self.prof.uid + ("" if not self._word_try else str(self._word_try)))
        self.word = joinwords.pick(rng)
        self.mqtt.subscribe("code/" + joinwords.slug(self.word))

    def _on_mqtt(self, topic, obj):
        if topic.startswith("code/"):                       # somebody else hosting with the same word: take another
            if isinstance(obj, dict) and obj.get("id") not in (None, self.gid) and self.state == "lobby":
                net.log("host: code %r is taken by another game, picking a new one" % self.word)
                self._new_word()
            return
        try:
            a = (str(obj["addr"][0]), int(obj["addr"][1]))
        except (KeyError, TypeError, ValueError, IndexError):
            return
        if self.state == "lobby" and len(self.players) < MAX_PLAYERS and obj.get("bday") and a[0] not in self._spraying:
            threading.Thread(target=self._spray, args=(a,), daemon=True).start()
        if self.state == "lobby" and len(self.players) < MAX_PLAYERS:
            if a not in self._punch:
                net.log("host: join notice from %s:%d, punching" % a)
            self._punch[a] = time.monotonic() + 30
            self.net.add_peer(a)

    def _spray(self, a):
        """Birthday punching for a guest behind symmetric NAT: the guest holds many ports open towards us, we answer
        HELLO to random ports of its IP (plus ports next to the one STUN saw, for routers that count up)."""
        self._spraying.add(a[0])                            # one spray per guest IP; several guests may spray at once
        net.log("host: guest %s is behind symmetric NAT: spraying HELLO at its ports" % a[0])
        rnd = random.Random()
        near = [p for d in range(1, 300) for p in (a[1] + d, a[1] - d) if 1024 <= p < 65536]
        try:
            for i in range(2000):
                if self.net is None or self.state != "lobby":
                    break
                port = near[i] if i < len(near) else rnd.randrange(1024, 65536)
                self.net._raw((a[0], port), net.HELLO, 0)
                if i % 50 == 49:
                    time.sleep(0.02)
        except (OSError, AttributeError):
            pass
        self._spraying.discard(a[0])

    def _info(self):
        return {"id": self.gid, "name": self.players[0]["name"], "n": len(self.players), "max": MAX_PLAYERS, "ver": VER,
                "port": self.net.port, "laddr": _lan_ip(), "addr": list(self.pub) if self.pub else None, "st": self.state, "nat": self.nat,
                "rid": self.net.rid if self.mqtt else None, "word": self.word}

    # ------------------------------------------------------------------ guest
    def browse(self):
        """Start looking for games (LAN + internet notice board)."""
        if self.lan is None:
            self.lan = discovery.Lan()
        if self.mqtt is None:
            self.mqtt = discovery.Board(["games/#"], self._on_game)

    def lookup(self, code_slug):
        """Guest: ask the notice board for the host that uses this short code; answers land in code_hits."""
        self.browse()
        self.code_hits.pop(code_slug, None)
        self.mqtt.subscribe("code/" + code_slug)

    def _on_game(self, topic, obj):
        if topic.startswith("code/"):
            if isinstance(obj, dict) and (obj.get("addr") or obj.get("laddr") or obj.get("rid")):
                g = dict(obj, seen=time.monotonic(), code=True)
                if not g.get("addr") and not g.get("rid"):
                    g["addr"], g["lan"] = [g["laddr"], g.get("port", net.PORT)], True
                self.code_hits[topic[5:]] = g
            return
        if isinstance(obj, dict) and obj.get("id") and (obj.get("addr") or obj.get("rid")) and obj.get("ver") == VER:
            self.found[obj["id"]] = dict(obj, seen=time.monotonic())

    def games(self):
        now = time.monotonic()
        out = {k: v for k, v in self.found.items() if now - v["seen"] < 12}
        if self.lan:
            for k, g in self.lan.games().items():
                if g.get("ver") == VER and k != self.gid:
                    out[k] = g
        return out

    def join(self, game):
        """game = entry of games(); direct (LAN / typed address) or through the internet notice board."""
        self.role, self.state, self.error = "guest", "connecting", ""
        threading.Thread(target=net.ensure_firewall, daemon=True).start()
        self.net = net.Net(0)
        self.net.probe_rtt = True
        relay_only = not game.get("addr") and game.get("rid")        # host has no UDP to the internet at all (strict Wi-Fi)
        addr = ("mqtt", int(game["rid"])) if relay_only else (game["addr"][0], int(game["addr"][1]))
        self._target = self._orig = addr
        self._t0 = time.monotonic()
        self._notice = 0.0
        self._mine = None
        self._game = game
        net.log("guest: joining %s (%s) at %s:%s, ver %d, notice board %s" % (
            game.get("name"), "LAN" if game.get("lan") else "internet", addr[0], addr[1], VER,
            "connected to " + self.mqtt.connected if self.mqtt and self.mqtt.connected else "OFFLINE"))
        self.net.follow[addr[0]] = addr
        self.route = "LAN" if game.get("lan") else "интернет"
        self.relayed = bool(relay_only)
        if self.mqtt is not None and not game.get("lan") and game.get("rid"):
            self.net.use_relay(self.mqtt)
        if game.get("laddr") and not game.get("lan"):
            la = (game["laddr"], int(game.get("port") or net.PORT))       # maybe the same Wi-Fi: knock on the LAN address too
            self.net.add_peer(la)
            self._also = la
        if relay_only:
            self.route = "реле преку MQTT (домаќинот нема UDP)"
            self.net.add_peer(addr)
            return
        if game.get("lan") or self.mqtt is None:
            self.net.add_peer(addr)
        else:
            self._busy = True
            threading.Thread(target=self._guest_net, args=(game["id"], addr), daemon=True).start()

    def _guest_net(self, hid, addr):
        mine = discovery.stun_addr(self.net.sock)
        self.nat = discovery.nat_kind(self.net.sock, mine)
        self._mine, self._hid = mine, hid
        net.log("guest: NAT type %s" % self.nat)
        net.log("guest: my public address %s%s" % (mine, "" if mine else " (STUN failed: the host cannot be told where to punch)"))
        la = self._game.get("laddr")
        if mine and la and mine[0] == addr[0]:       # same public IP = same router: most routers cannot loop back, use the LAN address
            addr = self._target = (la, int(self._game.get("port", addr[1])))
            self._also = None
            self.net.follow[addr[0]] = addr
            self.route = "ист рутер (LAN)"
            net.log("guest: host is behind the same router (%s), connecting to its LAN address %s:%d" % (mine[0], addr[0], addr[1]))
        elif mine:
            self.mqtt.publish("join/" + hid, {"addr": list(mine)})
            self._notice = time.monotonic()
        self.net.add_peer(addr)
        self._busy = False

    # ------------------------------------------------------------------ common
    def info(self):
        """Technical lines for the lobby: [(label, value)]."""
        n, now = self.net, time.monotonic()
        if n is None:
            return []
        if now - self._rate_at >= 1:
            dt = now - self._rate_at
            self._rate = ((n.bytes_rx - self._rx) / 1000 / dt, (n.bytes_tx - self._tx) / 1000 / dt)
            self._rx, self._tx, self._rate_at = n.bytes_rx, n.bytes_tx, now
        fmt = lambda a: "%s:%d" % (a[0], a[1]) if a else "?"
        host = self.role == "host"
        out = [("Улога", "домаќин" if host else "гостин"), ("Верзија", "v%d" % VER),
               ("Локална адреса", "%s:%d" % (_lan_ip() or "?", n.port))]
        if host:
            out.append(("Јавна адреса", fmt(self.pub) if self.pub else "се бара…"))
            out.append(("NAT", {"cone": "обичен (може директно)", "symmetric": "СИМЕТРИЧЕН: гостите од интернет нема да влезат", "multi-ip": "СИМЕТРИЧЕН (повеќе IP)"}.get(self.nat, "не е измерен")))
            out.append(("Интернет-објава", "поврзано (" + self.mqtt.connected + ")" if self.mqtt and self.mqtt.connected else "нема"))
            for pid, p in sorted(self.players.items()):
                if pid:
                    pm = n.ping_ms(now, [p["addr"]])
                    out.append((p["name"], "%s  %s" % (fmt(p["addr"]), ("%d ms" % pm) if pm is not None else "… ms")))
        else:
            out.append(("Јавна адреса", fmt(self._mine) if getattr(self, "_mine", None) else "?"))
            out.append(("Домаќин", fmt(self._target)))
            out.append(("Врска", self.route or "?"))
            out.append(("NAT", {"cone": "обичен (може директно)", "symmetric": "СИМЕТРИЧЕН", "multi-ip": "СИМЕТРИЧЕН (повеќе IP)"}.get(self.nat, "не е измерен")))
            pm = n.ping_ms(now, [self._target])
            out.append(("Пинг", ("%d ms" % pm) if pm is not None else "се мери…"))
        out.append(("Сообраќај", "↓ %.1f  ↑ %.1f kB/s" % self._rate))
        return out

    def _me(self, pid):
        used = {p["color"] for p in self.players.values()}
        col = next((i for i in range(len(COLORS)) if i not in used), 0)
        return {"name": self.prof.name, "color": col, "uid": self.prof.uid, "addr": None}

    def send_chat(self, text):
        text = text.strip()[:120]
        if not text:
            return
        if self.role == "host":
            self._chat(0, text)
        elif self.net and self.net.peers:
            self.net.send_rel(self._target, {"t": "chat", "m": text})

    def _chat(self, pid, text):
        self.chat = (self.chat + [(pid, text)])[-60:]
        self.net.broadcast_rel({"t": "chat", "p": pid, "m": text})

    def set_cfg(self, **kw):
        if self.role == "host" and self.state == "lobby":
            self.cfg.update(kw)
            self._roster()

    def set_color(self, c):
        if self.role == "host":
            self._color(self.pid, c)
        elif self.net and self.net.peers:
            self.net.send_rel(self._target, {"t": "color", "c": c})

    def _color(self, pid, c):
        if 0 <= c < len(COLORS) and all(p["color"] != c for p in self.players.values()):
            self.players[pid]["color"] = c
            self._roster()

    def chime(self, aud):
        """Play (and forget) the join / leave sounds; aud = audio.Audio or None."""
        b, self.blips = self.blips, []
        if aud is not None:
            for k in b[-2:]:
                try:
                    aud.play("ui_confirm" if k == "join" else "ui_click", 0.8 if k == "join" else 0.6, 1.0 if k == "join" else 0.7)
                except Exception:      # noqa: BLE001 - a missing sound never breaks the lobby
                    pass

    def _roster_seen(self, new):
        old = set(self.players)
        if self.state in ("lobby", "playing") and old:
            if set(new) - old:
                self.blips.append("join")
            if old - set(new):
                self.blips.append("leave")

    def _roster(self):
        self.net.broadcast_rel({"t": "roster", "pl": {str(k): [p["name"], p["color"], p["uid"]] for k, p in self.players.items()},
                                "cfg": self.cfg})

    def start(self):
        if self.role == "host" and self.state == "lobby":
            self.start_info = {"spawn": self.cfg["spawn"], "ff": self.cfg["ff"], "seed": random.randrange(1 << 30)}
            self.state = "playing"
            self.net.broadcast_rel(dict(self.start_info, t="start"))
            # the notice board stays open in game: a guest whose UDP dies switches to the relay or rejoins through it

    def leave(self):
        if self.voice is not None and self.state == "playing":
            self.voice.close()
        if self.net:
            if self.role == "guest" and self.net.peers:
                self.net.send_rel(self._target, {"t": "bye"})
                self.net.poll()
            elif self.role == "host":
                self.net.broadcast_rel({"t": "closed"})
            self.net.close()
        if self.mqtt:
            self.mqtt.close()
        self.net, self.mqtt, self.state = None, None, "closed"

    def update(self):
        """Call every frame (also while the lobby is on screen). Returns the list of net events handled."""
        if not self.net or self._busy:
            return []
        now = time.monotonic()
        if self.role == "host" and self.state == "lobby":
            if now - self._adv > 2 and self.lan:
                self._adv = now
                self.lan.beacon(self._info())
            if now - self._adv2 > 4 and self.mqtt and (self.pub or not self._busy):     # no STUN answer: still listed, relay only
                self._adv2 = now
                self.mqtt.publish("games/" + self.gid, self._info())
                if self.word:
                    self.mqtt.publish("code/" + joinwords.slug(self.word), self._info())
        for a, until in list(self._punch.items()):
            p = self.net.peers.get(a)
            if now > until or (p and p.up):
                del self._punch[a]
            else:
                self.net.hello(a)
        if self.role == "guest" and self.state == "connecting":
            self._birthday(now)
            rid = self._game.get("rid")
            sym = "symmetric" in (self.nat, self._game.get("nat")) or "multi-ip" in (self.nat, self._game.get("nat"))
            if (not self.relayed and rid and self.net.relay is not None and self.mqtt.connected
                    and now - self._t0 > (8 if self._bd else 2 if sym else 6)):
                self._bd_close()
                self.relayed = True                       # direct UDP did not come up: go through the notice board
                net.log("guest: no direct UDP after %.0f s (NAT %s / host %s): switching to the MQTT relay" % (
                    now - self._t0, self.nat, self._game.get("nat")))
                self.net.drop_peer(self._target)
                if getattr(self, "_also", None):
                    self.net.drop_peer(self._also)
                    self._also = None
                self._target = ("mqtt", int(rid))
                self.net.add_peer(self._target)
                self.route = "реле преку MQTT (%s)" % self.mqtt.connected
                self._t0 = now - 2
            if now - self._t0 > 15:
                self.state, self.error = "closed", self._why_failed()
                net.log("guest: no answer from %s:%d in 15 s (notice sent: %s). Host firewall / NAT is the usual cause" % (
                    self._target + (bool(self._mine),)))
            elif self.net.peers.get(self._target) is not None:
                self.net.hello(self._target, b"")
            if getattr(self, "_also", None) in self.net.peers:
                self.net.hello(self._also, b"")
                if self._mine and self.mqtt and self._notice and now - self._notice > 2:      # a single notice can be lost: repeat it
                    self._notice = now
                    self.mqtt.publish("join/" + self._hid, {"addr": list(self._mine)})
        evs = self.net.poll()
        for old, new in list(self.net.moved.items()):
            del self.net.moved[old]
            if old == getattr(self, "_target", None):
                self._target = new
        for kind, addr, obj in evs:
            if kind == "up" and self.role == "guest" and self._rec is not None and addr in self._rec["ways"]:
                net.log("guest: %s:%s answers, asking to be taken back" % addr)
                for w in self._rec["ways"] + [self._rec.get("old")]:
                    if w and w != addr:
                        self.net.drop_peer(w)
                self._rec["ways"] = [addr]
                self._target = addr
                self.route = "реле преку MQTT (%s)" % self.mqtt.connected if addr[0] == "mqtt" else "%s:%s" % addr
                self.relayed = addr[0] == "mqtt"
                self.net.send_rel(addr, {"t": "rebind", "uid": self.prof.uid, "name": self.prof.name, "ver": VER})
                continue
            if kind == "up" and self.role == "guest" and addr == getattr(self, "_also", None) and addr != self._target \
                    and self.state == "connecting":
                net.log("guest: the host answered on its LAN address %s:%d (same network)" % addr)
                self.net.drop_peer(self._target)
                self._target, self._also, self.route = addr, None, "LAN (код)"
            if kind == "up" and self.role == "guest" and addr == self._target:
                self.net.send_rel(addr, {"t": "join", "name": self.prof.name, "uid": self.prof.uid, "ver": VER})
            elif kind == "gone":
                self._gone(addr)
            elif kind == "rel":
                self._msg(addr, obj)
            elif kind == "voice":
                self._voice_in(addr, obj)
        if self.role == "guest" and self.net is not None:
            self._recover_tick(now)
        self._voice_out(now)
        return evs

    # ------------------------------------------------------------------ voice chat (star: guests -> host -> other guests)
    def _voice_in(self, addr, data):
        if self.voice is None or len(data) < 1:
            return
        if self.role == "host":
            pid = self._pid_of(addr)
            if pid is None:
                return
            data = bytes((pid,)) + data[1:]              # the host stamps the sender: nobody can speak as somebody else
            for k, p in self.players.items():
                if k and k != pid and p["addr"] is not None:
                    self.net.send_voice(p["addr"], data)
        else:
            pid = data[0]
            if pid == self.pid:
                return
        self.voice.receive(pid, data)

    def _voice_out(self, now):
        v = self.voice
        if v is None or self.state not in ("lobby", "playing"):
            return
        for pkt in v.take_packets():
            pkt = bytes((self.pid,)) + pkt[1:]
            if self.role == "host":
                for k, p in self.players.items():
                    if k and p["addr"] is not None:
                        self.net.send_voice(p["addr"], pkt)
            elif self.net.peers.get(self._target) is not None:
                self.net.send_voice(self._target, pkt)
        if now - self._vst_at > 2:
            self._vst_at = now
            loss = jit = None                            # how the others hear me -> quality of what I send
            for k, st in self.vstats.items():
                r = (st.get("rx") or {}).get(str(self.pid)) if k != self.pid and now - st.get("at", 0) < 7 else None
                if isinstance(r, list) and len(r) >= 4 and r[0] > 10:
                    loss, jit = max(loss or 0, int(r[1])), max(jit or 0, int(r[3]))
            v.relayed = getattr(self, "relayed", False) or any(
                isinstance(p["addr"], tuple) and p["addr"][0] == "mqtt" for p in self.players.values())
            v.adapt(loss, jit, self.net.ping_ms(now), now)
            v.watchdog(now)
            mine = {"mic": v.mic_state(), "rx": v.rx_stats(), "talk": v.talking}
            if self.role == "host":
                self.vstats[0] = dict(mine, at=now)
                self.net.broadcast_rel({"t": "vsa", "s": {str(k): {"mic": x["mic"], "rx": x["rx"]} for k, x in self.vstats.items()
                                                          if k in self.players}})
            elif self.net.peers.get(self._target) is not None and self.state != "connecting":
                self.net.send_rel(self._target, dict(mine, t="vst"))

    def voice_report(self, pid):
        """-> (my side: how I hear pid, their side: mic state + how they hear me) as text for the lobby / pause menu."""
        v = self.voice
        if v is None:
            return "", ""
        st = self.vstats.get(pid)
        if st is None:
            return v.peer_line(pid), "нема извештај (стара верзија на играта или гласот не е вклучен)"
        import voice as vmod
        theirs = vmod.MIC_CODES.get(st.get("mic"), str(st.get("mic")))
        rx = (st.get("rx") or {}).get(str(self.pid))
        if v.tx_packets == 0:
            theirs += " · ти уште не си зборувал"
        elif rx is None:
            theirs += " · НЕ ПРИМА твој глас (UDP пакетите за глас се губат: фајервол/NAT/рутер)"
        else:
            theirs += " · те слуша, загуба %d%%, џитер %d ms" % (rx[1], rx[3])
        return v.peer_line(pid), theirs

    def _birthday(self, now):
        """Guest behind symmetric NAT, host behind a normal one: open 256 ports towards the host; one of them will match
        a port the host sprays at. The socket that hears the host becomes the game socket."""
        if self._bd == [] and self.nat in ("symmetric", "multi-ip") and self._game.get("nat") == "cone" and not self.relayed \
                and self._mine and self.mqtt and self.mqtt.connected and now - self._t0 > 1.5 and not getattr(self, "_bd_done", False):
            self._bd_done = True
            import socket
            for _ in range(256):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.bind(("0.0.0.0", 0))
                    s.setblocking(False)
                    self._bd.append(s)
                except OSError:
                    break
            self._bd_at = 0.0
            net.log("guest: symmetric NAT, host normal NAT: birthday punching with %d ports" % len(self._bd))
            self.mqtt.publish("join/" + self._hid, {"addr": list(self._mine), "bday": 1})
        if not self._bd:
            return
        hello = net.HDR.pack(net.MAGIC, net.HELLO, 0)
        if now - self._bd_at > 0.5:
            self._bd_at = now
            for s in self._bd:
                try:
                    s.sendto(hello, self._target)
                except OSError:
                    pass
        for s in self._bd:
            try:
                pkt, a = s.recvfrom(2048)
            except OSError:
                continue
            if pkt[:4] == net.MAGIC and a[0] == self._target[0]:
                net.log("guest: birthday punch hit: port %d heard the host from %s:%d" % ((s.getsockname()[1],) + a))
                self._bd.remove(s)
                self.net.sock.close()
                self.net.sock, self.net.port = s, s.getsockname()[1]
                self.net.drop_peer(self._target)
                self._target = a
                self.net.add_peer(a)
                self.net.hello(a)
                self.route = "интернет (P2P, пробивање со многу порти)"
                self._bd_close()
                return

    def _bd_close(self):
        for s in self._bd:
            s.close()
        self._bd = []

    # ------------------------------------------------------------------ guest: keep the game alive when the line breaks
    def _recover_start(self, now, stage):
        """stage 'relay': UDP silent 3 s -> knock through the MQTT relay. 'rejoin': the link is gone -> try every way
        (old UDP address, LAN address, relay) for 30 s, then give up with the reason."""
        g = getattr(self, "_game", None) or {}
        if self._rec is not None and stage == "relay":
            return False
        ways = []
        if stage == "rejoin":
            ways.append(self._orig)
            if g.get("laddr"):
                ways.append((g["laddr"], int(g.get("port") or net.PORT)))
        if g.get("rid") and self.net.relay is None and self.mqtt is not None:
            self.net.use_relay(self.mqtt)
        if g.get("rid") and self.mqtt is not None and self.mqtt.connected:
            ways.append(("mqtt", int(g["rid"])))
        ways = [w for w in dict.fromkeys(ways) if w and w != (self._target if stage == "relay" else None)]
        if not ways:
            return False
        net.log("guest: link to the host %s (%s): trying %s" % ("silent 3 s" if stage == "relay" else "lost", self.route,
                                                               ", ".join("%s:%s" % w for w in ways)))
        old = self._target
        if stage == "rejoin":                                # fresh port + relay id: the host must not mix old and new packet counters
            import socket
            try:
                ns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                ns.bind(("0.0.0.0", 0))
                ns.setblocking(False)
                self.net.sock.close()
                self.net.sock, self.net.port = ns, ns.getsockname()[1]
            except OSError as e:
                net.log("guest: new socket failed: %r" % e)
            self.net.peers.clear()
            self.net.rid = int.from_bytes(os.urandom(4), "big") & 0x7FFFFFFF
            if self.net.relay is not None:
                self.net.relay.subscribe("r/%d" % self.net.rid)
        if self._rec is None:
            self._rec = {"at": now, "stage": stage, "ways": ways}
        else:
            self._rec.update(stage=stage, ways=ways)
        for w in ways:
            self.net.drop_peer(w)
            self.net.add_peer(w)
            self.net.hello(w)
        if stage == "relay" and old in self.net.peers:
            self._rec["old"] = old
        self.route_note = "се поврзува повторно…"
        return True

    def _recover_tick(self, now):
        r = self._rec
        if r is None:
            if self.role == "guest" and self.state in ("lobby", "playing"):
                p = self.net.peers.get(self._target)
                if p is not None and p.up and now - p.last_rx > 3 and self._target[0] != "mqtt":
                    self._recover_start(now, "relay")
            return
        for w in r["ways"]:
            p = self.net.peers.get(w)
            if p is not None and not p.up:
                self.net.hello(w)
        if now - r["at"] > 30:
            self._rec = None
            self.state, self.error = "closed", "Врската се прекина: домаќинот не се јавува 30 s ни директно ни преку реле"
            net.log("guest: recovery failed after 30 s")

    def _why_failed(self):
        """Technical reason for a join that got no answer."""
        if self._game.get("lan"):
            return "Нема врска: домаќинот не одговара на LAN (фајервол на Windows блокира UDP %d?)" % self._target[1]
        if self.mqtt is None or not self.mqtt.connected:
            return "Нема врска: интернет-таблата (MQTT) не е достапна, домаќинот не дозна за тебе"
        if not self._mine:
            return "Нема врска: STUN не одговори (UDP кон интернет блокиран?), не знаеме твоја јавна адреса"
        if self.relayed:
            return "Нема врска: ни директно ни преку релето (MQTT %s): домаќинот не одговара" % (self.mqtt.connected or "прекинат")
        sym = [w for w, n in (("ти", self.nat), ("домаќинот", self._game.get("nat"))) if n in ("symmetric", "multi-ip")]
        if sym:
            return "Нема врска: симетричен NAT кај %s, директна врска не е можна (port forward UDP %d кај домаќинот, или VPN/ZeroTier)" % (
                " и ".join(sym), net.PORT)
        return "Нема врска: домаќинот не одговори 15 s (NAT/фајервол на рутерот го блокира UDP)"

    def _comeback(self, addr, m):
        """Host: a known player (same uid) arrives from a new address - switched to the relay, changed Wi-Fi, or rejoined
        after a drop. Give back the same pid / colour / name; the game state follows from its next packets."""
        uid = str(m.get("uid", ""))[:12]
        if not uid or m.get("ver", VER) != VER:
            return False
        old = next((k for k, p in self.players.items() if p["uid"] == uid and k), None)
        if old is not None:
            prev = self.players[old]["addr"]
            if prev != addr:
                self.players[old]["addr"] = addr
                if prev is not None:
                    self.net.drop_peer(prev)                  # silently: this is not a leave
            pid = old
        else:
            g = self._ghosts.pop(uid, None)
            if g is None or time.monotonic() - g[2] > 90 or len(self.players) >= MAX_PLAYERS or g[0] in self.players:
                return False
            pid = g[0]
            self.players[pid] = dict(g[1], addr=addr)
            self.blips.append("join")
        net.log("host: player %d (%s) is back from %s:%s (%s)" % (pid, self.players[pid]["name"], addr[0], addr[1], m.get("t")))
        self.net.send_rel(addr, {"t": "welcome", "pid": pid, "back": 1})
        if self.state == "playing" and self.start_info:
            self.net.send_rel(addr, dict(self.start_info, t="start"))
        self._roster()
        return True

    def _pid_of(self, addr):
        for k, p in self.players.items():
            if p["addr"] == addr:
                return k
        return None

    def _gone(self, addr):
        if self.role == "guest":
            if addr != self._target:
                return
            if self.state in ("lobby", "playing") and self._recover_start(time.monotonic(), "rejoin"):
                return
            self.state, self.error = "closed", self.error or "Врската се прекина"
            net.log("guest: connection lost: host silent for %.0f s or closed" % net.TIMEOUT)
        else:
            pid = self._pid_of(addr)
            if pid is not None:
                if self.state == "playing":               # kept 90 s: the same player (uid) may come back after a Wi-Fi drop
                    self._ghosts[self.players[pid]["uid"]] = (pid, dict(self.players[pid]), time.monotonic())
                del self.players[pid]
                self.blips.append("leave")
                self.vstats.pop(pid, None)
                if self.voice is not None:
                    self.voice.forget(pid)
                self._roster()                           # also in game: the others drop the name, voice and arrow

    def _msg(self, addr, m):
        t = m.get("t") if isinstance(m, dict) else None
        if self.role == "host":
            pid = self._pid_of(addr)
            if t in ("rebind", "join") and pid is None and self._comeback(addr, m):
                pass
            elif t == "join" and pid is None and self.state == "lobby":
                net.log("host: join request from %s:%d name %r ver %r" % (addr + (m.get("name"), m.get("ver"))))
                if m.get("ver") != VER:
                    self.net.send_rel(addr, {"t": "deny", "why": "ver"})
                elif len(self.players) >= MAX_PLAYERS:
                    self.net.send_rel(addr, {"t": "deny", "why": "full"})
                else:
                    new = max(self.players) + 1
                    self.blips.append("join")
                    self.players[new] = dict(self._me(new), name=_name(m.get("name"), self.players), uid=str(m.get("uid", ""))[:12], addr=addr)
                    self.net.send_rel(addr, {"t": "welcome", "pid": new})
                    self._roster()
            elif pid is not None:
                if t == "chat":
                    self._chat(pid, str(m.get("m", ""))[:120])
                elif t == "color" and isinstance(m.get("c"), int):
                    self._color(pid, m["c"])
                elif t == "vst":
                    self.vstats[pid] = {"mic": str(m.get("mic", ""))[:8], "rx": m.get("rx") if isinstance(m.get("rx"), dict) else {},
                                        "at": time.monotonic()}
                elif t == "bye":
                    self.net.drop_peer(addr)
                    self._gone(addr)
        else:
            if t == "welcome" and m.get("back") and self._rec is not None:
                net.log("guest: the host took me back as player %s over %s" % (m.get("pid"), self.route))
                self.pid, self._rec = int(m["pid"]), None
                if self.state == "connecting":
                    self.state = "lobby"
            elif t == "welcome":
                self.pid, self.state = int(m["pid"]), "lobby"
                g = self._game
                try:                                      # remember it for one-click quick join next time
                    code = make_code(g) if g.get("rid") or g.get("addr") else ""
                except (OSError, ValueError, TypeError, KeyError, struct.error):
                    code = ""
                self.prof.last = {"name": str(g.get("name") or "")[:30], "word": str(g.get("word") or "")[:30], "code": code}
                self.prof.save()
                net.log("guest: welcome, I am player %d" % self.pid)
            elif t == "deny":
                net.log("guest: host denied the join: %s" % m.get("why"))
                self.state, self.error = "closed", {"full": "Игрот е полн", "ver": "Друга верзија на играта"}.get(m.get("why"), "Одбиено")
            elif t == "roster":
                self._roster_seen({int(k) for k in m["pl"]})
                self.players = {int(k): {"name": v[0], "color": v[1], "uid": v[2], "addr": None} for k, v in m["pl"].items()}
                self.cfg = m.get("cfg", self.cfg)
            elif t == "chat":
                self.chat = (self.chat + [(int(m["p"]), str(m["m"])[:120])])[-60:]
            elif t == "start":
                if self.state != "playing":
                    self.start_info = {"spawn": m["spawn"], "ff": m["ff"], "seed": m["seed"]}
                self.state = "playing"
            elif t == "vsa" and isinstance(m.get("s"), dict):
                now = time.monotonic()
                for k, x in m["s"].items():
                    if str(k).isdigit() and isinstance(x, dict):
                        self.vstats[int(k)] = {"mic": str(x.get("mic", ""))[:8], "rx": x.get("rx") if isinstance(x.get("rx"), dict) else {}, "at": now}
            elif t == "closed":
                self.state, self.error = "closed", "Домаќинот ја затвори играта"


# ------------------------------------------------------------------ join code (shared privately, e.g. over WhatsApp)
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"                 # Crockford: no I L O U
_LOOK = {"O": "0", "I": "1", "L": "1", "U": "V",           # typed by hand, or with a Cyrillic keyboard layout
         "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M", "О": "0", "Р": "P", "Т": "T", "Х": "X",
         "Ѕ": "S", "Ј": "J", "З": "3", "Б": "6"}
_NATS = [None, "cone", "symmetric", "multi-ip"]
_CODE = struct.Struct("!B4sH4sHIB")                      # version, public ip, port, LAN ip, port, relay id, NAT type


def make_code(info):
    """Host's _info() -> 'S242-XXXX-XXXX-...' (35 chars). Carries every way in: public address, LAN address, relay id."""
    import socket
    pub = info.get("addr") or ["0.0.0.0", 0]
    raw = _CODE.pack(VER, socket.inet_aton(pub[0]), int(pub[1]), socket.inet_aton(info.get("laddr") or "0.0.0.0"),
                     int(info.get("port", 0)), int(info.get("rid") or 0), _NATS.index(info.get("nat")) if info.get("nat") in _NATS else 0)
    raw += struct.pack("!H", zlib.crc32(raw) & 0xFFFF)
    n, bits, out = int.from_bytes(raw, "big"), len(raw) * 8, ""
    for i in range((bits + 4) // 5):
        out = _B32[n & 31] + out
        n >>= 5
    return "S242-" + "-".join(out[i:i + 4] for i in range(0, len(out), 4))


def parse_code(text):
    """Join code (any case, spaces, dashes, look-alike letters) or a plain 'ip:port' -> game dict for join().
    Raises ValueError with the reason shown to the player."""
    import socket
    t = (text or "").strip()
    if ":" in t and t.replace(".", "").replace(":", "").isdigit():       # typed address, e.g. 85.12.3.4:24242
        ip, port = t.rsplit(":", 1)
        try:
            socket.inet_aton(ip)
            return {"addr": [ip, int(port)], "port": int(port), "name": ip, "code": True}
        except (OSError, ValueError):
            raise ValueError("адресата не е IP:порта")
    t = "".join(_LOOK.get(c, c) for c in t.upper())
    if t.startswith("S242"):
        t = t[4:]
    t = "".join(c for c in t if c not in " -_.,\t\n")
    bad = [c for c in t if c not in _B32]
    if bad:
        raise ValueError("кодот има непознат знак „%s“" % bad[0])
    need = ((_CODE.size + 2) * 8 + 4) // 5
    if len(t) != need:
        raise ValueError("кодот има %d знаци наместо %d (копирај го целиот)" % (len(t), need))
    n = 0
    for c in t:
        n = n * 32 + _B32.index(c)
    raw = n.to_bytes(_CODE.size + 2, "big") if n < 1 << ((_CODE.size + 2) * 8) else b""
    if len(raw) != _CODE.size + 2 or struct.unpack("!H", raw[-2:])[0] != zlib.crc32(raw[:-2]) & 0xFFFF:
        raise ValueError("кодот не е точен (некој знак е погрешен)")
    ver, pip, pport, lip, lport, rid, nat = _CODE.unpack(raw[:-2])
    if ver != VER:
        raise ValueError("кодот е од друга верзија на играта (v%d, ти имаш v%d)" % (ver, VER))
    pub, lan = socket.inet_ntoa(pip), socket.inet_ntoa(lip)
    g = {"id": "r%d" % rid, "rid": rid or None, "nat": _NATS[nat] if nat < len(_NATS) else None, "ver": ver,
         "laddr": lan if lan != "0.0.0.0" else None, "port": lport, "name": "код", "code": True}
    if pub != "0.0.0.0" and pport:
        g["addr"] = [pub, pport]
    elif rid:
        g["addr"] = None                                         # host has no public UDP: relay (and a LAN knock)
    elif g["laddr"]:
        g["addr"], g["lan"] = [lan, lport], True                 # host had no internet address: LAN only
    else:
        raise ValueError("кодот нема адреса (домаќинот нема ни интернет ни LAN)")
    return g


def _lan_ip():
    """This PC's LAN address (no packet is sent), or None."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _name(n, players):
    import mpprofile as profile
    n = profile.clean(str(n or "")) or "Играч"
    base, i = n, 2
    while any(p["name"] == n for p in players.values()):
        n, i = "%s%d" % (base[:14], i), i + 1
    return n
