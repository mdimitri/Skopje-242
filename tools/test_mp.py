"""Lobby protocol test: host + 3 guests over loopback, chat, colours, full-game denial, duplicate names, start, host closing."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import mp, mpprofile as profile

def prof(name, uid):
    p = profile.Profile("/nonexistent/p.json"); p.name, p.uid = name, uid; return p
def pump(ss, secs=0.6, until=None):
    t = time.time()
    while time.time() - t < secs:
        for s in ss: s.update()
        if until and until(): return
        time.sleep(0.005)

h = mp.Session(prof("Мартин", "h1")); h.host(internet=False)
g = [mp.Session(prof(n, "g%d" % i)) for i, n in enumerate(["Мартин", "Ана", "Кико", "Лазе"])]
for s in g[:3]: s.join({"addr": ["127.0.0.1", h.net.port], "lan": True})
pump([h] + g, 3, lambda: len(h.players) == 4 and all(s.state == "lobby" for s in g[:3]))
assert len(h.players) == 4 and all(s.state == "lobby" for s in g[:3]), (h.players, [s.state for s in g])
assert sorted(p["name"] for p in h.players.values()) == ["Ана", "Кико", "Мартин", "Мартин2"], h.players
g[3].join({"addr": ["127.0.0.1", h.net.port], "lan": True}); pump([h] + g, 2)
assert g[3].state == "closed" and g[3].error == "Игрот е полн", (g[3].state, g[3].error)
g[0].send_chat("Ајде кај Кале"); g[1].set_color(0); g[1].set_color(1)
h.set_cfg(spawn=3, ff=True); pump([h] + g, 0.6)
assert all(s.chat and s.chat[-1][1] == "Ајде кај Кале" for s in [h] + g[:3])
assert g[1].cfg == {"spawn": 3, "ff": True}
cols = [p["color"] for p in h.players.values()]; assert len(set(cols)) == 4, cols
h.start(); pump([h] + g, 0.8)
assert all(s.state == "playing" and s.start_info["spawn"] == 3 and s.start_info["ff"] for s in g[:3])
assert len({s.start_info["seed"] for s in g[:3]}) == 1
print("OK lobby: 4 players, deny-full, unique names, chat, colours, cfg, start")

# same-router join: the host advertises its LAN address; a guest with the same public IP must use it, not the public one
import discovery
discovery.stun_addr = lambda sock, timeout=1.5: ("9.9.9.9", sock.getsockname()[1])
class FakeMqtt:
    connected = "x"
    def publish(self, *a): pass
h2 = mp.Session(prof("Домаќин", "h9")); h2.host(internet=False)
g2 = mp.Session(prof("Гост", "g9")); g2.mqtt = FakeMqtt()
g2.join({"id": "h9", "name": "x", "addr": ["9.9.9.9", 5], "laddr": "127.0.0.1", "port": h2.net.port})
pump([h2, g2], 3, lambda: g2.state == "lobby")
assert g2.state == "lobby", (g2.state, g2.error)
print("OK same-router join through the LAN address")

# join codes (shared over WhatsApp): round trip, sloppy typing / Cyrillic look-alikes, typos and truncation give reasons
c = mp.make_code({"addr": ["85.12.3.4", 24242], "laddr": "192.168.1.10", "port": 24242, "rid": 123456789, "nat": "cone"})
g0 = mp.parse_code(c)
assert g0["addr"] == ["85.12.3.4", 24242] and g0["rid"] == 123456789 and g0["laddr"] == "192.168.1.10" and g0["id"] == "r123456789"
assert mp.parse_code("  " + c.lower().replace("-", " ").replace("0", "о") + "\n") == g0
for bad, why in ((c[:-2], "знаци"), (c[:-1] + ("Z" if c[-1] != "Z" else "Y"), "погрешен"), (c + "!", "непознат")):
    try:
        mp.parse_code(bad); raise AssertionError(bad)
    except ValueError as e:
        assert why in str(e), e
assert mp.parse_code("10.0.0.5:24242")["addr"] == ["10.0.0.5", 24242]
gl = mp.parse_code(mp.make_code({"addr": None, "laddr": "192.168.1.10", "port": 24242, "rid": 5, "nat": None}))
assert gl["addr"] is None and gl["rid"] == 5 and gl["laddr"] == "192.168.1.10"
# join a real host by its code over loopback
h3 = mp.Session(prof("Код", "hc")); h3.host(internet=False)
g3 = mp.Session(prof("Гост", "gc"))
g3.join(mp.parse_code(mp.make_code(dict(h3._info(), addr=None, laddr="127.0.0.1"))))
pump([h3, g3], 3, lambda: g3.state == "lobby")
assert g3.state == "lobby", (g3.state, g3.error)
print("OK join codes: round trip, sloppy input, reasons for bad codes, LAN-only code joins")
import joinwords
assert len(joinwords.WORDS) >= 180 and len({joinwords.slug(w + "1") for w in joinwords.WORDS}) == len(joinwords.WORDS)
assert joinwords.slug("ШМЕКЕР 42") == joinwords.slug("shmeker-42") == "shmeker42" and joinwords.slug("S242-05AG") is None
print("OK short word codes: %d words, Cyrillic/Latin typing match" % len(joinwords.WORDS))
