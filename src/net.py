"""Multiplayer transport: UDP with a tiny reliable-ordered channel (stdlib only, nothing extra to install).

Packet = MAGIC(4) kind(1) seq(4) payload.
  UNREL  snapshots / inputs (newest wins, dropped if late)    REL  ordered, acked, resent (JSON objects)
  ACK    acknowledges a REL seq                               HELLO  hole-punch / keep-alive / join request
Poll returns events: ("rel", addr, obj) | ("unrel", addr, bytes) | ("up", addr, None) | ("gone", addr, None)
"""
import json
import socket
import struct
import time

MAGIC = b"S242"
HDR = struct.Struct("!4sBI")
UNREL, REL, ACK, HELLO = 0, 1, 2, 3
MAX_PAYLOAD = 1100          # stays under typical MTU so no IP fragmentation
RESEND = 0.12               # s before an unacked REL packet is sent again
TIMEOUT = 8.0               # s of silence before a peer is dropped
KEEPALIVE = 1.0


class Peer:
    __slots__ = ("addr", "out", "q", "expect", "ooo", "last_rx", "last_tx", "up", "rtt", "unrel_seq", "rx_unrel")

    def __init__(self, addr, now):
        self.addr, self.out, self.q = addr, 1, {}      # q: seq -> [packet, first_sent, last_sent]
        self.expect, self.ooo = 1, {}
        self.last_rx = self.last_tx = now
        self.up, self.rtt, self.unrel_seq, self.rx_unrel = False, 0.1, 0, 0


class Net:
    def __init__(self, port=0, accept=False):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", port))
        self.sock.setblocking(False)
        self.port = self.sock.getsockname()[1]
        self.accept = accept          # host: create peers for unknown senders that say HELLO
        self.peers = {}
        self.bytes_tx = self.bytes_rx = 0

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
        pkt = HDR.pack(MAGIC, kind, seq) + payload
        try:
            self.sock.sendto(pkt, addr)
            self.bytes_tx += len(pkt)
        except OSError:
            pass
        return pkt

    def send_rel(self, addr, obj):
        p = self.peers.get(addr)
        if p is None:
            return
        data = json.dumps(obj, separators=(",", ":")).encode()
        if len(data) > MAX_PAYLOAD:
            raise ValueError("reliable message too large")
        now = time.monotonic()
        pkt = self._raw(addr, REL, p.out, data)
        p.q[p.out] = [pkt, now, now]
        p.out += 1
        p.last_tx = now

    def send_unrel(self, addr, data):
        p = self.peers.get(addr)
        if p is None or len(data) > MAX_PAYLOAD:
            return
        p.unrel_seq = (p.unrel_seq + 1) & 0xFFFFFFFF
        self._raw(addr, UNREL, p.unrel_seq, data)
        p.last_tx = time.monotonic()

    def broadcast_rel(self, obj, skip=None):
        for a in list(self.peers):
            if a != skip and self.peers[a].up:
                self.send_rel(a, obj)

    def broadcast_unrel(self, data):
        for a, p in self.peers.items():
            if p.up:
                self.send_unrel(a, data)

    # ---- receiving / timers
    def poll(self):
        ev, now = [], time.monotonic()
        for _ in range(512):
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
                if not (self.accept and kind == HELLO):
                    continue
                p = self.add_peer(addr)
            p.last_rx = now
            if not p.up:
                p.up = True
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
            elif kind == UNREL:
                if ((seq - p.rx_unrel) & 0xFFFFFFFF) < 0x80000000 and seq != p.rx_unrel:   # newer only
                    p.rx_unrel = seq
                    ev.append(("unrel", addr, body))
        for a, p in list(self.peers.items()):
            if p.up and now - p.last_rx > TIMEOUT:
                self.peers.pop(a)
                ev.append(("gone", a, None))
                continue
            for seq, e in p.q.items():
                if now - e[2] > RESEND:
                    try:
                        self.sock.sendto(e[0], a)
                    except OSError:
                        pass
                    e[2] = now
            if now - p.last_tx > KEEPALIVE:
                self._raw(a, HELLO, 0)
                p.last_tx = now
        return ev

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
