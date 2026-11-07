"""Tests discovery.Mqtt against a tiny in-process fake MQTT 3.1.1 broker (real public brokers are not reachable from CI)."""
import os, socket, struct, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import discovery

subs, conns = [], []
def rd(c):
    h = c.recv(1)
    if not h: return None, None
    ln, mul = 0, 1
    while True:
        b = c.recv(1)[0]; ln += (b & 0x7F) * mul; mul <<= 7
        if not b & 0x80: break
    body = b""
    while len(body) < ln: body += c.recv(ln - len(body))
    return h[0] >> 4, body
def serve(c):
    conns.append(c)
    while True:
        try: t, b = rd(c)
        except OSError: return
        if t is None: return
        if t == 1: c.sendall(b"\x20\x02\x00\x00")
        elif t == 8: subs.append(c); c.sendall(b"\x90\x03" + b[:2] + b"\x00")
        elif t == 3:
            for s in subs: s.sendall(b"\x30" + discovery._vlen(len(b)) + b)
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(4)
threading.Thread(target=lambda: [threading.Thread(target=serve, args=(srv.accept()[0],), daemon=True).start() for _ in iter(int, 1)], daemon=True).start()
got = []
a = discovery.Mqtt(["games/#"], lambda t, o: got.append((t, o)), brokers=[("127.0.0.1", srv.getsockname()[1])])
b = discovery.Mqtt(["join/#"], lambda t, o: None, brokers=[("127.0.0.1", srv.getsockname()[1])])
time.sleep(1.5)
b.publish("games/h1", {"name": "Партија", "addr": ["1.2.3.4", 5]})
time.sleep(1)
assert got == [("games/h1", {"name": "Партија", "addr": ["1.2.3.4", 5]})], got
print("OK mqtt client")
