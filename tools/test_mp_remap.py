"""Join through a relay whose replies come from a different port than the guest sent to (NAT port remap): the guest must follow it."""
import os, socket, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import mp, mpprofile as profile

def prof(name, uid):
    p = profile.Profile("/nonexistent/p.json"); p.name, p.uid = name, uid; return p
h = mp.Session(prof("Домаќин", "h1")); h.host(internet=False)
mk = lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
r1, r2, s = mk(), mk(), mk()
for x in (r1, r2, s): x.bind(("127.0.0.1", 0)); x.settimeout(0.05)
guest, stop = [None], [False]
def relay():
    while not stop[0]:
        for x in (r1, r2, s):
            try: d, a = x.recvfrom(2048)
            except OSError: continue
            if x is s: r2.sendto(d, guest[0])
            else: guest[0] = a; s.sendto(d, ("127.0.0.1", h.net.port))
threading.Thread(target=relay, daemon=True).start()
g = mp.Session(prof("Гост", "g1")); g.join({"addr": ["127.0.0.1", r1.getsockname()[1]], "lan": True})
t = time.time()
while time.time() - t < 5 and g.state != "lobby":
    h.update(); g.update(); time.sleep(0.005)
stop[0] = True
assert g.state == "lobby" and len(h.players) == 2, (g.state, g.error, h.players)
print("OK remapped reply port followed")
