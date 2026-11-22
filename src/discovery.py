"""Finding games without a server of ours: LAN broadcast + public STUN (own address) + a public MQTT broker as a notice board.

Everything is stdlib and runs inside the game. The brokers/STUN servers are free public infrastructure; only game
name, host name and a public ip:port are published (no chat, no gameplay data).
Topics:  skopje242/v1/games/<hostid>  host advertises (every 4 s)      skopje242/v1/join/<hostid>  client announces its address
"""
import json
import os
import socket
import struct
import threading
import time

LAN_PORT = 24243
STUN = [("stun.l.google.com", 19302), ("stun1.l.google.com", 19302), ("stun.cloudflare.com", 3478)]
BROKERS = [("broker.hivemq.com", 1883), ("broker.emqx.io", 1883), ("test.mosquitto.org", 1883)]
TOPIC = "skopje242/v1/"
VER = 1


def stun_addr(sock, timeout=1.5, servers=None):
    """Public (ip, port) of this UDP socket as seen from outside (RFC 5389 binding request), or None."""
    tid = os.urandom(12)
    req = struct.pack("!HHI", 0x0001, 0, 0x2112A442) + tid
    old = sock.gettimeout()
    sock.settimeout(timeout)
    try:
        for host in (servers or STUN) * 3:              # a lost request (WiFi, busy router) is simply asked again
            try:
                sock.sendto(req, socket.getaddrinfo(host[0], host[1], socket.AF_INET, socket.SOCK_DGRAM)[0][4])
                while True:
                    data, _ = sock.recvfrom(2048)
                    if len(data) >= 20 and data[8:20] == tid and data[:2] == b"\x01\x01":
                        i = 20
                        while i + 4 <= len(data):
                            t, ln = struct.unpack_from("!HH", data, i)
                            if t == 0x0020 and ln >= 8:      # XOR-MAPPED-ADDRESS
                                port = struct.unpack_from("!H", data, i + 6)[0] ^ 0x2112
                                ip = bytes(a ^ b for a, b in zip(data[i + 8:i + 12], b"\x21\x12\xa4\x42"))
                                return socket.inet_ntoa(ip), port
                            i += 4 + ((ln + 3) & ~3)
            except (OSError, socket.timeout):
                if sock.fileno() == -1:                 # closed under us: asking again is pointless
                    return None
                continue
    finally:
        try:
            sock.settimeout(old)
        except OSError:                                 # the socket was closed meanwhile (WinError 10038): nothing to restore
            pass
    return None


def nat_kind(sock, first):
    """'symmetric' when a second STUN server sees another public port than the first (hole punching cannot work then),
    'cone' when it is the same, None when it could not be measured."""
    if not first:
        return None
    answered = set()
    for host in STUN:
        try:
            ip = socket.getaddrinfo(host[0], host[1], socket.AF_INET, socket.SOCK_DGRAM)[0][4][0]
        except OSError:
            continue
        b = stun_addr(sock, 1.0, [host])
        if b and b != first:
            return "symmetric" if b[0] == first[0] else "multi-ip"
        if b:
            answered.add(ip)
    return "cone" if len(answered) > 1 else None


# ---------------------------------------------------------------------------- minimal MQTT 3.1.1 client
def _vlen(n):
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


class Mqtt:
    """Background thread: connects to the first reachable public broker, subscribes, delivers (topic, dict) to `on_msg`."""

    def __init__(self, subs, on_msg, brokers=None):
        self.subs, self.on_msg, self.brokers = subs, on_msg, brokers or BROKERS
        self.sock, self.run, self.lock = None, True, threading.Lock()
        self.connected = ""
        self.on_raw = None            # callback(topic, bytes) for binary relay topics ("r/...")
        threading.Thread(target=self._loop, daemon=True).start()

    def _send(self, b):
        with self.lock:
            if self.sock:
                try:
                    self.sock.sendall(b)
                except OSError:
                    pass

    def publish(self, topic, obj):
        t = (TOPIC + topic).encode()
        body = struct.pack("!H", len(t)) + t + json.dumps(obj, separators=(",", ":")).encode()
        self._send(b"\x30" + _vlen(len(body)) + body)

    def publish_raw(self, topic, data):
        t = (TOPIC + topic).encode()
        body = struct.pack("!H", len(t)) + t + data
        self._send(b"\x30" + _vlen(len(body)) + body)

    def subscribe(self, sub):
        """Add a subscription now (if connected) and after every reconnect."""
        if sub not in self.subs:
            self.subs = self.subs + [sub]
        t = (TOPIC + sub).encode()
        self._send(b"\x82" + _vlen(5 + len(t)) + struct.pack("!HH", len(self.subs), len(t)) + t + b"\x00")

    def _loop(self):
        while self.run:
            for host, port in self.brokers:
                if not self.run:
                    return
                try:
                    s = socket.create_connection((host, port), timeout=5)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)      # relayed game packets: no 40 ms Nagle wait
                    cid = ("s242" + os.urandom(5).hex()).encode()
                    vh = b"\x00\x04MQTT\x04\x02" + struct.pack("!H", 30)
                    pl = struct.pack("!H", len(cid)) + cid
                    s.sendall(b"\x10" + _vlen(len(vh) + len(pl)) + vh + pl)
                    if s.recv(4)[:2] != b"\x20\x02":
                        raise OSError("refused")
                    for i, sub in enumerate(self.subs):
                        t = (TOPIC + sub).encode()
                        body = struct.pack("!HH", i + 1, len(t)) + t + b"\x00"
                        s.sendall(b"\x82" + _vlen(len(body)) + body)
                    s.settimeout(1.0)
                    with self.lock:
                        self.sock = s
                    self.connected = host
                    self._read(s)
                except OSError:
                    pass
                finally:
                    with self.lock:
                        self.sock = None
                    self.connected = ""
            time.sleep(3)

    def _read(self, s):
        buf, ping = b"", time.monotonic()
        while self.run:
            if time.monotonic() - ping > 20:
                self._send(b"\xc0\x00")
                ping = time.monotonic()
            try:
                d = s.recv(4096)
                if not d:
                    return
                buf += d
            except socket.timeout:
                continue
            while len(buf) >= 2:
                ln, mul, i = 0, 1, 1
                while i < len(buf):
                    ln += (buf[i] & 0x7F) * mul
                    mul <<= 7
                    i += 1
                    if not buf[i - 1] & 0x80:
                        break
                else:
                    break
                if len(buf) < i + ln:
                    break
                typ, body, buf = buf[0] >> 4, buf[i:i + ln], buf[i + ln:]
                if typ == 3 and len(body) > 2:
                    tl = struct.unpack_from("!H", body)[0]
                    topic = body[2:2 + tl].decode("utf-8", "replace")[len(TOPIC):]
                    if topic.startswith("r/"):
                        if self.on_raw is not None:
                            self.on_raw(topic, body[2 + tl:])
                        continue
                    try:
                        self.on_msg(body[2:2 + tl].decode()[len(TOPIC):], json.loads(body[2 + tl:]))
                    except (ValueError, UnicodeDecodeError):
                        pass

    def close(self):
        self.run = False
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except OSError:
                    pass


# ---------------------------------------------------------------------------- LAN
class Lan:
    """Host: beacon(info) now and then. Browser: games() = {hostid: info with 'addr'}."""

    def __init__(self):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self.s.bind(("0.0.0.0", LAN_PORT))
        except OSError:
            pass
        self.s.setblocking(False)
        self.seen = {}

    def beacon(self, info):
        try:
            self.s.sendto(b"S242" + json.dumps(info, separators=(",", ":")).encode(), ("255.255.255.255", LAN_PORT))
        except OSError:
            pass

    def games(self):
        now = time.monotonic()
        for _ in range(64):
            try:
                d, a = self.s.recvfrom(1500)
            except (BlockingIOError, OSError):
                break
            if d[:4] == b"S242":
                try:
                    g = json.loads(d[4:])
                    g["addr"] = [a[0], g.get("port", 24242)]
                    g["lan"] = True
                    self.seen[g["id"]] = (now, g)
                except (ValueError, KeyError):
                    pass
        self.seen = {k: v for k, v in self.seen.items() if now - v[0] < 10}
        return {k: v[1] for k, v in self.seen.items()}


# ---------------------------------------------------------------------------- connection test (lobby button)
def selftest(out):
    """Fills `out` (a list, read by the UI while this runs in a thread) with (label, ok, detail) rows. ok: True/False/None."""
    import mpnet
    def row(label, ok, detail):
        out.append((label, ok, detail))
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 9))
        lan = s.getsockname()[0]
        s.close()
        row("Мрежа (LAN)", True, "адреса " + lan)
    except OSError as e:
        row("Мрежа (LAN)", False, "нема мрежа: %s" % e)
    try:
        socket.getaddrinfo(STUN[0][0], STUN[0][1])
        row("DNS", True, "имињата се преведуваат")
    except OSError as e:
        row("DNS", False, "нема интернет или DNS (%s)" % e)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", 0))
        pub = stun_addr(sock)
        if pub:
            row("UDP кон интернет", True, "јавна адреса %s:%d" % pub)
            kind = nat_kind(sock, pub)
            row("Тип на NAT", kind == "cone" if kind else None,
                {"cone": "обичен: директна врска (P2P) работи",
                 "symmetric": "симетричен (јавен Wi-Fi / мобилен): гостите влегуваат преку пробивање или реле; подобро некој од дома да биде домаќин",
                 "multi-ip": "симетричен со повеќе IP (мобилен оператор): најчесто реле"}.get(kind, "не може да се измери"))
        else:
            row("UDP кон интернет", False, "блокиран (строг Wi-Fi/фајервол): играта ќе оди само преку реле, побавно")
    finally:
        sock.close()
    for host, port in BROKERS:
        t0 = time.monotonic()
        try:
            c = socket.create_connection((host, port), timeout=4)
            c.close()
            row("Табла " + host, True, "достапна, %d ms" % ((time.monotonic() - t0) * 1000))
        except OSError as e:
            row("Табла " + host, False, "недостапна (%s)" % (str(e) or type(e).__name__))
    if os.name == "nt":
        row("Windows фајервол", None, "при првата игра Windows прашува: дозволи (јавни и приватни мрежи)")
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("0.0.0.0", mpnet.PORT))
        probe.close()
        row("Порта UDP %d" % mpnet.PORT, True, "слободна (за домаќин)")
    except OSError:
        row("Порта UDP %d" % mpnet.PORT, None, "зафатена (друга игра отворена?): домаќинот ќе земе друга порта, сѐ уште работи")
    out.append(None)        # done


class Board:
    """Two MQTT connections to different public brokers at once: if one broker dies or throttles, the notice board,
    the short codes and the relay keep working on the other. Same interface as Mqtt; duplicates are fine upstream
    (listings/notices are idempotent, relayed packets are de-duplicated in mpnet)."""

    def __init__(self, subs, on_msg, brokers=None):
        b = list(brokers or BROKERS)
        self.links = [Mqtt(list(subs), on_msg, b)]
        if len(b) > 1:
            self.links.append(Mqtt(list(subs), on_msg, b[1:] + b[:1]))
        self._raw = None

    @property
    def connected(self):
        c = [m.connected for m in self.links if m.connected]
        return " + ".join(dict.fromkeys(c)) if c else ""

    @property
    def on_raw(self):
        return self._raw

    @on_raw.setter
    def on_raw(self, f):
        self._raw = f
        for m in self.links:
            m.on_raw = f

    def publish(self, topic, obj):
        for m in self.links:
            m.publish(topic, obj)

    def publish_raw(self, topic, data):
        for m in self.links:
            m.publish_raw(topic, data)

    def subscribe(self, sub):
        for m in self.links:
            m.subscribe(sub)

    def close(self):
        for m in self.links:
            m.close()
