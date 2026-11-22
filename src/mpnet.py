"""Multiplayer transport: UDP with a tiny reliable-ordered channel (stdlib only, nothing extra to install).

Packet = MAGIC(4) kind(1) seq(4) payload.
  UNREL  snapshots / inputs (newest wins, dropped if late)    REL  ordered, acked, resent (JSON objects)
  ACK    acknowledges a REL seq                               HELLO  hole-punch / keep-alive / join request
  PING/PONG measure the gameplay round trip without entering the reliable queue.
Poll returns events: ("rel", addr, obj) | ("unrel", addr, bytes) | ("voice", addr, bytes) | ("up", addr, None) | ("gone", addr, None)
"""
import collections
import hashlib
import hmac
import json
import os
import zlib
import socket
import struct
import threading
import time

PORT = 24242
MAGIC = b"S242"
HDR = struct.Struct("!4sBI")
UNREL, REL, ACK, HELLO = 0, 1, 2, 3
PING, PONG = 4, 5
VOICE = 6                   # voice chat frames (voice.py): unreliable, never reordered here, the jitter buffer sorts them
MAX_PAYLOAD = 1100          # stays under typical MTU so no IP fragmentation
RESEND = 0.12               # s before an unacked REL packet is sent again
TIMEOUT = 8.0               # s of silence before a peer is dropped
KEEPALIVE = 1.0
PING_PERIOD, PING_FRESH = 1.0, 3.0


# Packet signing: Diffie-Hellman (RFC 3526 group 14) in the first HELLOs, then every packet carries a 6-byte HMAC tag.
# Strangers on the public relay topics or spoofing UDP cannot inject packets once a link is signed.
_P = int("FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DD"
         "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
         "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
         "83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
         "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
         "15728E5A8AACAA68FFFFFFFFFFFFFFFF", 16)
SIGNED = 0x80                 # kind bit: packet ends with a tag
TAG = 6


def _tag(key, data):
    return hmac.new(key, data, hashlib.sha256).digest()[:TAG]


_LOGF = None


def log(msg):
    """Join / connection steps go to logs/multiplayer.log (append, timestamped) so a failed join can be diagnosed from both PCs."""
    global _LOGF
    try:
        if _LOGF is None:
            d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
            os.makedirs(d, exist_ok=True)
            _LOGF = open(os.path.join(d, "multiplayer.log"), "a", encoding="utf-8")
        _LOGF.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
        _LOGF.flush()
    except OSError:
        pass


_FW_DONE = False


def ensure_firewall():
    """Windows: make sure inbound UDP is allowed for this program on private AND public networks.
    Checks the rule without admin rights; if missing, asks once through the normal UAC prompt to add it."""
    global _FW_DONE
    if _FW_DONE or os.name != "nt":
        return
    _FW_DONE = True
    import subprocess
    import sys
    name = "Skopje-242 multiplayer"
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=" + name, "verbose"],
                           capture_output=True, text=True, timeout=10, creationflags=0x08000000)
        exe = os.path.abspath(sys.executable).lower()
        if exe in r.stdout.lower() and "any" in r.stdout.lower().split("profiles:")[-1][:40]:
            log("firewall: rule already present")
            return
        args = ('advfirewall firewall delete rule name="%s" & netsh advfirewall firewall add rule name="%s" dir=in action=allow '
                'protocol=UDP program="%s" profile=any' % (name, name, sys.executable))
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", '/c netsh ' + args, None, 0)
        log("firewall: asked Windows to allow %s (public + private), result %s" % (sys.executable, rc))
    except Exception as e:      # noqa: BLE001 - never block multiplayer on this
        log("firewall: check failed: %r" % e)


class Peer:
    __slots__ = ("addr", "out", "q", "expect", "ooo", "last_rx", "last_tx", "up", "rtt", "unrel_seq", "rx_unrel", "rx_unrel_mask")
    __slots__ += ("ping_sent", "ping_seq", "ping_at", "ping_ms", "key", "their_ok", "signed_rx")

    def __init__(self, addr, now):
        self.addr, self.out, self.q = addr, 1, {}      # q: seq -> [packet, first_sent, last_sent]
        self.expect, self.ooo = 1, {}
        self.last_rx = self.last_tx = now
        self.up, self.rtt, self.unrel_seq, self.rx_unrel = False, 0.1, 0, 0
        self.rx_unrel_mask = 1
        self.ping_sent, self.ping_seq = now - PING_PERIOD, None
        self.ping_at, self.ping_ms = -float("inf"), 0.0
        self.key, self.their_ok, self.signed_rx = None, False, False     # signing state (see _tag)


class Net:
    def __init__(self, port=0, accept=False):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", port))
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]
        self.accept = accept          # host: create peers for unknown senders that say HELLO
        self.unrel_reorder = False    # gameplay packets carry their own per-stream revisions
        self.probe_rtt = False
        self.peers = {}
        self.follow = {}              # guest: host ip -> expected addr; a reply from the same ip on another port (NAT) re-targets the peer
        self.moved = {}               # old addr -> new addr, read by mp.Session
        self._stray = 0
        self.bytes_tx = self.bytes_rx = 0
        self._tx_lock = threading.Lock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat = None
        self.relay = None             # discovery.Mqtt: fallback path when UDP hole punching fails (symmetric NAT both sides)
        self.rid = int.from_bytes(os.urandom(4), "big") & 0x7FFFFFFF      # my relay address = ("mqtt", rid)
        self._rin = collections.deque(maxlen=2000)
        self._rseen = {}
        self._rout = {}                          # relay batches: addr -> [packets], one MQTT message per frame and peer
        self.relay_msgs = self.relay_bytes = self.relay_bad = 0
        self._rflush = 0.0
        self._dh = int.from_bytes(os.urandom(32), "big")
        self._dhpub = pow(2, self._dh, _P).to_bytes(256, "big")
        self.forged = 0                          # packets dropped for a missing / wrong tag

    def use_relay(self, mqtt):
        """Packets to ("mqtt", rid) addresses go through the MQTT notice board; packets for me arrive on r/<my rid>."""
        self.relay = mqtt
        mqtt.on_raw = self._relay_rx
        mqtt.subscribe("r/%d" % self.rid)

    def _relay_rx(self, topic, body):
        if len(body) > 5:
            h, now = hash(body), time.monotonic()  # the same packet arrives once per broker (discovery.Board): keep one
            if now - self._rseen.get(h, -9) < 0.5:   # (identical keep-alives are >= 1 s apart, so a short window is safe)
                return
            self._rseen[h] = now
            if len(self._rseen) > 4000:
                self._rseen = {k: t for k, t in self._rseen.items() if now - t < 0.5}
            src = ("mqtt", int.from_bytes(body[:4], "big"))
            data = body[5:]
            try:
                if body[4] & 1:
                    data = zlib.decompress(data)
                i = 0
                while i + 2 <= len(data):                # a batch: [len u16][packet] ...
                    n = int.from_bytes(data[i:i + 2], "big")
                    self._rin.append((data[i + 2:i + 2 + n], src))
                    i += 2 + n
            except (zlib.error, IndexError):
                self.relay_bad += 1

    def start_heartbeat(self):
        """Keep established game connections alive while the window thread is blocked."""
        if self._heartbeat is None:
            self._heartbeat_stop.clear()
            self._heartbeat = threading.Thread(target=self._keepalive, daemon=True)
            self._heartbeat.start()

    def _keepalive(self):
        while not self._heartbeat_stop.wait(KEEPALIVE):
            now = time.monotonic()
            for addr, p in list(self.peers.items()):
                if p.up and now - p.last_tx >= KEEPALIVE:
                    self.hello(addr)
            self.flush_relay(True)

    def stop_heartbeat(self):
        if self._heartbeat is not None:
            self._heartbeat_stop.set()
            self._heartbeat.join(timeout=.25)
            self._heartbeat = None

    # ---- peers
    def add_peer(self, addr):
        if addr not in self.peers:
            self.peers[addr] = Peer(addr, time.monotonic())
        return self.peers[addr]

    def drop_peer(self, addr):
        self.peers.pop(addr, None)

    def hello(self, addr, body=b""):
        """Punch / keep-alive; also the client's first packet to the host."""
        self._raw(addr, HELLO, 0, body)

    # ---- sending
    def _raw(self, addr, kind, seq, payload=b""):
        p = self.peers.get(addr)
        if p is not None and kind == HELLO and not (p.their_ok and p.signed_rx):
            payload = b"DH" + bytes((p.key is not None,)) + self._dhpub      # until both sides proved the key
        pkt = HDR.pack(MAGIC, kind, seq) + payload
        if p is not None and p.key is not None and p.their_ok:
            pkt = HDR.pack(MAGIC, kind | SIGNED, seq) + payload
            pkt += _tag(p.key, pkt)
        self._send_packet(addr, pkt)
        return pkt

    def _send_packet(self, addr, pkt):
        if addr[0] == "mqtt":
            if self.relay is not None:
                with self._tx_lock:
                    self._rout.setdefault(addr, []).append(pkt)
            return
        try:
            sent = self.sock.sendto(pkt, addr)
        except OSError:
            return
        with self._tx_lock:
            self.bytes_tx += sent

    def flush_relay(self, force=False):
        """Send the queued relay packets: one message per peer, zlib-compressed when that is smaller (cuts the message
        rate the free brokers see from ~60/s to the frame rate, and the bytes by about a half on game snapshots)."""
        now = time.monotonic()
        if not self._rout or (not force and now - self._rflush < 0.03 and sum(map(len, self._rout.values())) < 12):
            return                                   # at most ~33 messages/s per peer: the free brokers stay happy
        self._rflush = now
        with self._tx_lock:
            out, self._rout = self._rout, {}
        for addr, pkts in out.items():
            raw = b"".join(len(p).to_bytes(2, "big") + p for p in pkts)
            z = zlib.compress(raw, 1)
            flag, data = (1, z) if len(z) < len(raw) else (0, raw)
            if self.relay is not None:
                self.relay.publish_raw("r/%d" % addr[1], self.rid.to_bytes(4, "big") + bytes((flag,)) + data)
            with self._tx_lock:
                self.bytes_tx += len(data) + 40
                self.relay_msgs += 1
                self.relay_bytes += len(data) + 40

    def ping_ms(self, now, addresses=None):
        peers = self.peers.values() if addresses is None else (self.peers[a] for a in addresses if a in self.peers)
        return max((p.ping_ms for p in peers if p.up and now - p.ping_at < PING_FRESH), default=None)

    def send_rel(self, addr, obj):
        p = self.peers.get(addr)
        if p is None:
            return
        data = json.dumps(obj, separators=(",", ":")).encode()
        if len(data) > MAX_PAYLOAD:
            raise ValueError("reliable message too large")
        now = time.monotonic()
        pkt = self._raw(addr, REL, p.out, data)
        p.q[p.out] = [data, now, now]              # payload: resends are built again (signed once the link is)
        p.out += 1
        p.last_tx = now

    def send_unrel(self, addr, data):
        p = self.peers.get(addr)
        if p is None or len(data) > MAX_PAYLOAD:
            return
        p.unrel_seq = (p.unrel_seq + 1) & 0xFFFFFFFF
        self._raw(addr, UNREL, p.unrel_seq, data)
        p.last_tx = time.monotonic()

    def send_voice(self, addr, data):
        p = self.peers.get(addr)
        if p is None or not p.up or len(data) > MAX_PAYLOAD:
            return
        self._raw(addr, VOICE, 0, data)
        p.last_tx = time.monotonic()

    def broadcast_rel(self, obj, skip=None):
        for a in list(self.peers):
            if a != skip and self.peers[a].up:
                self.send_rel(a, obj)

    def broadcast_unrel(self, data):
        for a, p in list(self.peers.items()):      # list(): the notice-board thread adds peers (mp.Session._on_mqtt)
            if p.up:
                self.send_unrel(a, data)

    # ---- receiving / timers
    def poll(self):
        self.flush_relay()
        ev, now = [], time.monotonic()
        for _ in range(512):
            if self._rin:
                pkt, addr = self._rin.popleft()
            else:
                try:
                    pkt, addr = self.sock.recvfrom(2048)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:           # e.g. ICMP unreachable on Windows
                    continue
            self.bytes_rx += len(pkt)
            if len(pkt) < HDR.size:
                continue
            magic, kind, seq = HDR.unpack_from(pkt)
            if magic != MAGIC:
                continue
            p = self.peers.get(addr)
            if p is None:
                old = self.follow.get(addr[0])
                if old in self.peers and not self.peers[old].up:
                    p = self.peers.pop(old)
                    p.addr = addr
                    self.peers[addr] = p
                    self.moved[old] = addr
                    log("reply came from %s:%d, not %s:%d (NAT remapped the port): following it" % (addr + old))
                elif not (self.accept and kind == HELLO):
                    if self._stray < 5:
                        self._stray += 1
                        log("ignored packet kind %d from unknown %s:%d" % ((kind,) + addr))
                    continue
                else:
                    p = self.add_peer(addr)
                    log("host: HELLO from new address %s:%d" % addr)
            if kind & SIGNED:
                if p.key is None or len(pkt) < HDR.size + TAG or not hmac.compare_digest(_tag(p.key, pkt[:-TAG]), pkt[-TAG:]):
                    self.forged += 1
                    continue
                pkt, kind, p.signed_rx = pkt[:-TAG], kind & 0x7F, True
            elif p.signed_rx:                      # this link is signed: an unsigned packet is somebody else's
                self.forged += 1
                continue
            if kind == HELLO and pkt[HDR.size:HDR.size + 2] == b"DH" and len(pkt) == HDR.size + 3 + 256:
                if p.key is None:
                    their = int.from_bytes(pkt[HDR.size + 3:], "big")
                    if 1 < their < _P - 1:
                        p.key = hashlib.sha256(pow(their, self._dh, _P).to_bytes(256, "big")).digest()
                        self._raw(addr, HELLO, 0)          # tell them at once that we have their key
                if pkt[HDR.size + 2] and p.key is not None:
                    p.their_ok = True
                pkt = pkt[:HDR.size]
            p.last_rx = now
            if not p.up:
                p.up = True
                log("peer %s:%d up (first packet kind %d)" % (addr + (kind,)))
                ev.append(("up", addr, pkt[HDR.size:] if kind == HELLO else None))
                self._raw(addr, HELLO, 0)      # answer so the other side comes up too
            body = pkt[HDR.size:]
            if kind == REL:
                self._raw(addr, ACK, seq)
                if seq >= p.expect:
                    p.ooo[seq] = body
                    while p.expect in p.ooo:
                        try:
                            ev.append(("rel", addr, json.loads(p.ooo.pop(p.expect))))
                        except ValueError:
                            pass
                        p.expect += 1
            elif kind == ACK:
                e = p.q.pop(seq, None)
                if e:
                    p.rtt = 0.8 * p.rtt + 0.2 * (now - e[1])
            elif kind == PING:
                self._raw(addr, PONG, seq)
            elif kind == PONG and seq == p.ping_seq:
                sample = (now - p.ping_sent) * 1000
                p.ping_ms = p.ping_ms * .6 + sample * .4 if now - p.ping_at < PING_FRESH else sample
                p.ping_at, p.ping_seq = now, None
            elif kind == VOICE:
                ev.append(("voice", addr, body))
            elif kind == UNREL:
                ahead = (seq - p.rx_unrel) & 0xFFFFFFFF
                if 0 < ahead < 0x80000000:
                    p.rx_unrel = seq
                    p.rx_unrel_mask = ((p.rx_unrel_mask << ahead) & ((1 << 64) - 1) if ahead < 64 else 0) | 1
                    ev.append(("unrel", addr, body))
                elif self.unrel_reorder and ahead:
                    behind = (p.rx_unrel - seq) & 0xFFFFFFFF
                    if behind < 64 and not p.rx_unrel_mask & (1 << behind):
                        p.rx_unrel_mask |= 1 << behind
                        ev.append(("unrel", addr, body))
        for a, p in list(self.peers.items()):
            if p.up and now - p.last_rx > TIMEOUT:
                self.peers.pop(a)
                log("peer %s:%d silent for %.1f s: dropped" % (a + (now - p.last_rx,)))
                ev.append(("gone", a, None))
                continue
            for seq, e in p.q.items():
                if now - e[2] > RESEND:
                    self._raw(a, REL, seq, e[0])
                    e[2] = now
            probe_wait = PING_PERIOD if p.ping_seq is None else PING_FRESH
            if self.probe_rtt and p.up and now - p.ping_sent >= probe_wait:
                p.ping_sent, p.ping_seq = now, int(now * 1000) & 0xFFFFFFFF
                self._raw(a, PING, p.ping_seq)
            if now - p.last_tx > KEEPALIVE and (not p.up or self._heartbeat is None):
                self._raw(a, HELLO, 0)
                p.last_tx = now
        self.flush_relay()
        return ev

    def close(self):
        self.stop_heartbeat()
        try:
            self.sock.close()
        except OSError:
            pass
