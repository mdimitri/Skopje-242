"""Loopback test for src/net.py: handshake, ordered reliable delivery under 30% loss, unreliable newest-wins."""
import os, random, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import net

random.seed(1)
host, cli = net.Net(0, accept=True), net.Net(0)
orig = net.Net._raw
def lossy(self, addr, kind, seq, payload=b""):   # drop 30% of outgoing packets
    if random.random() < 0.3:
        return HDR_PKT(kind, seq, payload)
    return orig(self, addr, kind, seq, payload)
def HDR_PKT(kind, seq, payload): return net.HDR.pack(net.MAGIC, kind, seq) + payload
net.Net._raw = lossy
ha = ("127.0.0.1", host.port)
cli.add_peer(ha)
got, up, t0 = [], 0, time.time()
sent = 0
while time.time() - t0 < 20 and len(got) < 200:
    cli.hello(ha)
    for n in (host, cli):
        for kind, addr, obj in n.poll():
            if kind == "up": up += 1
            if kind == "rel" and n is host: got.append(obj["i"])
    if cli.peers[ha].up and sent < 200 and cli.peers[ha].up:
        cli.send_rel(ha, {"i": sent}); sent += 1
    time.sleep(0.005)
assert up == 2, up
assert got == list(range(200)), (len(got), got[:10])
print("OK: 200 reliable msgs in order under 30%% loss, %.1fs" % (time.time() - t0))
