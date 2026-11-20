"""Loopback transport test for reliable retries and unreliable reordering."""
import os, random, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import mpnet as net

random.seed(1)
host, cli = net.Net(0, accept=True), net.Net(0)

class LossySocket:
    def __init__(self, sock):
        self.sock = sock

    def sendto(self, packet, addr):
        if random.random() < 0.3:
            return len(packet)
        return self.sock.sendto(packet, addr)

    def recvfrom(self, size):
        return self.sock.recvfrom(size)

for endpoint in (host, cli):
    endpoint.sock = LossySocket(endpoint.sock)
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

for endpoint in (host, cli):
    endpoint.sock = endpoint.sock.sock

def datagrams(seqs, expected):
    for seq in seqs:
        cli._raw(ha, net.UNREL, seq, bytes([seq]))
    received, until = [], time.monotonic() + 0.5
    while time.monotonic() < until:
        received.extend(payload[0] for kind, _, payload in host.poll() if kind == "unrel")
        if len(received) >= len(expected):
            break
        time.sleep(.005)
    assert received == expected, received

datagrams([3, 2, 3, 4], [3, 4])
host.unrel_reorder = True
datagrams([7, 5, 6, 5, 8], [7, 5, 6, 8])
host.probe_rtt = cli.probe_rtt = True
deadline = time.monotonic() + 1
while time.monotonic() < deadline:
    host.poll()
    cli.poll()
    if all(endpoint.ping_ms(time.monotonic()) is not None for endpoint in (host, cli)):
        break
    time.sleep(.005)
for endpoint in (host, cli):
    now = time.monotonic()
    assert 0 <= endpoint.ping_ms(now) < 1000
    assert endpoint.ping_ms(now + net.PING_FRESH) is None
    endpoint.probe_rtt = False

keepalive, timeout = net.KEEPALIVE, net.TIMEOUT
try:
    net.KEEPALIVE, net.TIMEOUT = .05, .2
    host.start_heartbeat()
    cli.poll()
    deadline = time.monotonic() + .55
    while time.monotonic() < deadline:
        assert all(kind != "gone" for kind, _, _ in cli.poll())
        time.sleep(.01)
    assert ha in cli.peers
finally:
    host.stop_heartbeat()
    net.KEEPALIVE, net.TIMEOUT = keepalive, timeout
host.close()
cli.close()
print("OK: default newest-wins, gameplay reorder, RTT probes and heartbeat during a stalled frame loop")
