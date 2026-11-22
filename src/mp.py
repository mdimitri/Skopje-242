"""Multiplayer session: lobby protocol (join, roster, chat, settings, start) on top of net.Net. No UI, no raylib.

The host owns the world; guests send inputs and render what the host sends (added in later steps).
"""
import os
import random
import threading
import time

import discovery
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
        self._spraying = False
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
        self.pid, self.players = 0, {0: self._me(0)}
        self.lan = discovery.Lan()
        if internet:
            self._busy = True
            threading.Thread(target=self._host_net, daemon=True).start()
            self.mqtt = discovery.Mqtt(["join/" + self.gid], self._on_mqtt)
            self.net.use_relay(self.mqtt)                # guests whose UDP cannot get through come in over the notice board
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

    def _on_mqtt(self, topic, obj):
        try:
            a = (str(obj["addr"][0]), int(obj["addr"][1]))
        except (KeyError, TypeError, ValueError, IndexError):
            return
        if self.state == "lobby" and len(self.players) < MAX_PLAYERS and obj.get("bday") and not self._spraying:
            threading.Thread(target=self._spray, args=(a,), daemon=True).start()
        if self.state == "lobby" and len(self.players) < MAX_PLAYERS:
            if a not in self._punch:
                net.log("host: join notice from %s:%d, punching" % a)
            self._punch[a] = time.monotonic() + 30
            self.net.add_peer(a)

    def _spray(self, a):
        """Birthday punching for a guest behind symmetric NAT: the guest holds many ports open towards us, we answer
        HELLO to random ports of its IP (plus ports next to the one STUN saw, for routers that count up)."""
        self._spraying = True
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
        self._spraying = False

    def _info(self):
        return {"id": self.gid, "name": self.players[0]["name"], "n": len(self.players), "max": MAX_PLAYERS, "ver": VER,
                "port": self.net.port, "laddr": _lan_ip(), "addr": list(self.pub) if self.pub else None, "st": self.state, "nat": self.nat,
                "rid": self.net.rid if self.mqtt else None}

    # ------------------------------------------------------------------ guest
    def browse(self):
        """Start looking for games (LAN + internet notice board)."""
        if self.lan is None:
            self.lan = discovery.Lan()
        if self.mqtt is None:
            self.mqtt = discovery.Mqtt(["games/#"], self._on_game)

    def _on_game(self, topic, obj):
        if isinstance(obj, dict) and obj.get("id") and obj.get("addr") and obj.get("ver") == VER:
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
        addr = (game["addr"][0], int(game["addr"][1]))
        self._target = addr
        self._t0 = time.monotonic()
        self._notice = 0.0
        self._mine = None
        self._game = game
        net.log("guest: joining %s (%s) at %s:%d, ver %d, notice board %s" % (
            game.get("name"), "LAN" if game.get("lan") else "internet", addr[0], addr[1], VER,
            "connected to " + self.mqtt.connected if self.mqtt and self.mqtt.connected else "OFFLINE"))
        self.net.follow[addr[0]] = addr
        self.route = "LAN" if game.get("lan") else "интернет"
        self.relayed = False
        if self.mqtt is not None and not game.get("lan") and game.get("rid"):
            self.net.use_relay(self.mqtt)
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

    def _roster(self):
        self.net.broadcast_rel({"t": "roster", "pl": {str(k): [p["name"], p["color"], p["uid"]] for k, p in self.players.items()},
                                "cfg": self.cfg})

    def start(self):
        if self.role == "host" and self.state == "lobby":
            self.start_info = {"spawn": self.cfg["spawn"], "ff": self.cfg["ff"], "seed": random.randrange(1 << 30)}
            self.state = "playing"
            self.net.broadcast_rel(dict(self.start_info, t="start"))
            if self.mqtt and not any(isinstance(p["addr"], tuple) and p["addr"][0] == "mqtt" for p in self.players.values()):
                self.mqtt.close()
                self.mqtt = None

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
            if now - self._adv2 > 4 and self.mqtt and self.pub:
                self._adv2 = now
                self.mqtt.publish("games/" + self.gid, self._info())
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
                if self._mine and self.mqtt and self._notice and now - self._notice > 2:      # a single notice can be lost: repeat it
                    self._notice = now
                    self.mqtt.publish("join/" + self._hid, {"addr": list(self._mine)})
        evs = self.net.poll()
        for old, new in list(self.net.moved.items()):
            del self.net.moved[old]
            if old == getattr(self, "_target", None):
                self._target = new
        for kind, addr, obj in evs:
            if kind == "up" and self.role == "guest" and addr == self._target:
                self.net.send_rel(addr, {"t": "join", "name": self.prof.name, "uid": self.prof.uid, "ver": VER})
            elif kind == "gone":
                self._gone(addr)
            elif kind == "rel":
                self._msg(addr, obj)
            elif kind == "voice":
                self._voice_in(addr, obj)
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

    def _pid_of(self, addr):
        for k, p in self.players.items():
            if p["addr"] == addr:
                return k
        return None

    def _gone(self, addr):
        if self.role == "guest":
            self.state, self.error = "closed", self.error or "Врската се прекина"
            net.log("guest: connection lost: host silent for %.0f s or closed" % net.TIMEOUT)
        else:
            pid = self._pid_of(addr)
            if pid is not None:
                del self.players[pid]
                self.vstats.pop(pid, None)
                if self.voice is not None:
                    self.voice.forget(pid)
                if self.state == "lobby":
                    self._roster()

    def _msg(self, addr, m):
        t = m.get("t") if isinstance(m, dict) else None
        if self.role == "host":
            pid = self._pid_of(addr)
            if t == "join" and pid is None and self.state == "lobby":
                net.log("host: join request from %s:%d name %r ver %r" % (addr + (m.get("name"), m.get("ver"))))
                if m.get("ver") != VER:
                    self.net.send_rel(addr, {"t": "deny", "why": "ver"})
                elif len(self.players) >= MAX_PLAYERS:
                    self.net.send_rel(addr, {"t": "deny", "why": "full"})
                else:
                    new = max(self.players) + 1
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
            if t == "welcome":
                self.pid, self.state = int(m["pid"]), "lobby"
                net.log("guest: welcome, I am player %d" % self.pid)
            elif t == "deny":
                net.log("guest: host denied the join: %s" % m.get("why"))
                self.state, self.error = "closed", {"full": "Игрот е полн", "ver": "Друга верзија на играта"}.get(m.get("why"), "Одбиено")
            elif t == "roster":
                self.players = {int(k): {"name": v[0], "color": v[1], "uid": v[2], "addr": None} for k, v in m["pl"].items()}
                self.cfg = m.get("cfg", self.cfg)
            elif t == "chat":
                self.chat = (self.chat + [(int(m["p"]), str(m["m"])[:120])])[-60:]
            elif t == "start":
                self.start_info = {"spawn": m["spawn"], "ff": m["ff"], "seed": m["seed"]}
                self.state = "playing"
            elif t == "vsa" and isinstance(m.get("s"), dict):
                now = time.monotonic()
                for k, x in m["s"].items():
                    if str(k).isdigit() and isinstance(x, dict):
                        self.vstats[int(k)] = {"mic": str(x.get("mic", ""))[:8], "rx": x.get("rx") if isinstance(x.get("rx"), dict) else {}, "at": now}
            elif t == "closed":
                self.state, self.error = "closed", "Домаќинот ја затвори играта"


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
