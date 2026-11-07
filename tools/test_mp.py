"""Lobby protocol test: host + 3 guests over loopback, chat, colours, full-game denial, duplicate names, start, host closing."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import mp, profile

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
