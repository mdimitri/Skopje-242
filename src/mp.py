"""Multiplayer session: lobby protocol (join, roster, chat, settings, start) on top of net.Net. No UI, no raylib.

The host owns the world; guests send inputs and render what the host sends (added in later steps).
"""
import os
import random
import threading
import time

import discovery
import net

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
        self.ready = False                    # host: public address resolved, listening
        self.pub = None
        self.lan = None
        self.mqtt = None
        self.found = {}                       # internet games seen on the notice board: id -> info
        self._punch = {}                      # addr -> give-up time (host answering a join notice)
        self._adv = self._adv2 = 0.0
        self._busy = False

    # ------------------------------------------------------------------ host
    def host(self, internet=True):
        self.role, self.state = "host", "lobby"
        try:
            self.net = net.Net(net.PORT, accept=True)
        except OSError:
            self.net = net.Net(0, accept=True)
        self.pid, self.players = 0, {0: self._me(0)}
        self.lan = discovery.Lan()
        if internet:
            self._busy = True
            threading.Thread(target=self._host_net, daemon=True).start()
            self.mqtt = discovery.Mqtt(["join/" + self.gid], self._on_mqtt)
        self.ready = True

    def _host_net(self):
        self.pub = discovery.stun_addr(self.net.sock)
        self._busy = False

    def _on_mqtt(self, topic, obj):
        try:
            a = (str(obj["addr"][0]), int(obj["addr"][1]))
        except (KeyError, TypeError, ValueError, IndexError):
            return
        if self.state == "lobby" and len(self.players) < MAX_PLAYERS:
            self._punch[a] = time.monotonic() + 12
            self.net.add_peer(a)

    def _info(self):
        return {"id": self.gid, "name": self.players[0]["name"], "n": len(self.players), "max": MAX_PLAYERS, "ver": VER,
                "port": self.net.port, "addr": list(self.pub) if self.pub else None, "st": self.state}

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
        self.net = net.Net(0)
        addr = (game["addr"][0], int(game["addr"][1]))
        self._target = addr
        self._t0 = time.monotonic()
        if game.get("lan") or self.mqtt is None:
            self.net.add_peer(addr)
        else:
            self._busy = True
            threading.Thread(target=self._guest_net, args=(game["id"], addr), daemon=True).start()

    def _guest_net(self, hid, addr):
        mine = discovery.stun_addr(self.net.sock)
        if mine:
            self.mqtt.publish("join/" + hid, {"addr": list(mine)})
        self.net.add_peer(addr)
        self._busy = False

    # ------------------------------------------------------------------ common
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
            if self.mqtt:
                self.mqtt.close()
                self.mqtt = None

    def leave(self):
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
            if now - self._t0 > 15:
                self.state, self.error = "closed", "Нема врска"
            elif self.net.peers.get(self._target) is not None:
                self.net.hello(self._target, b"")
        evs = self.net.poll()
        for kind, addr, obj in evs:
            if kind == "up" and self.role == "guest" and addr == self._target:
                self.net.send_rel(addr, {"t": "join", "name": self.prof.name, "uid": self.prof.uid, "ver": VER})
            elif kind == "gone":
                self._gone(addr)
            elif kind == "rel":
                self._msg(addr, obj)
        return evs

    def _pid_of(self, addr):
        for k, p in self.players.items():
            if p["addr"] == addr:
                return k
        return None

    def _gone(self, addr):
        if self.role == "guest":
            self.state, self.error = "closed", self.error or "Врската се прекина"
        else:
            pid = self._pid_of(addr)
            if pid is not None:
                del self.players[pid]
                if self.state == "lobby":
                    self._roster()

    def _msg(self, addr, m):
        t = m.get("t") if isinstance(m, dict) else None
        if self.role == "host":
            pid = self._pid_of(addr)
            if t == "join" and pid is None and self.state == "lobby":
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
                elif t == "bye":
                    self.net.drop_peer(addr)
                    self._gone(addr)
        else:
            if t == "welcome":
                self.pid, self.state = int(m["pid"]), "lobby"
            elif t == "deny":
                self.state, self.error = "closed", {"full": "Игрот е полн", "ver": "Друга верзија на играта"}.get(m.get("why"), "Одбиено")
            elif t == "roster":
                self.players = {int(k): {"name": v[0], "color": v[1], "uid": v[2], "addr": None} for k, v in m["pl"].items()}
                self.cfg = m.get("cfg", self.cfg)
            elif t == "chat":
                self.chat = (self.chat + [(int(m["p"]), str(m["m"])[:120])])[-60:]
            elif t == "start":
                self.start_info = {"spawn": m["spawn"], "ff": m["ff"], "seed": m["seed"]}
                self.state = "playing"
            elif t == "closed":
                self.state, self.error = "closed", "Домаќинот ја затвори играта"


def _name(n, players):
    import profile
    n = profile.clean(str(n or "")) or "Играч"
    base, i = n, 2
    while any(p["name"] == n for p in players.values()):
        n, i = "%s%d" % (base[:14], i), i + 1
    return n
