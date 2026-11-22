"""NAT lab v2: 2-4 players, each on a network profile. Run as root (netns + iptables):
    python3 lab2.py home public 5g      -> host on home Wi-Fi, guests on public Wi-Fi and a 5G hotspot
Profiles: home (normal NAT, 1% loss) | public (symmetric NAT, 3% loss) | strict (public Wi-Fi that blocks all UDP but DNS)
          5g (phone hotspot NAT behind carrier-grade symmetric NAT, 2% loss) | same (same router as the previous player)
Prints one line per player: how it connected, voice heard from every other player."""
import json, os, subprocess, sys, time
D = os.path.dirname(os.path.abspath(__file__))
PROF = {"home": dict(nat="cone", loss=.01), "public": dict(nat="symmetric", loss=.03), "strict": dict(nat="symmetric", loss=.02, noudp=True),
        "5g": dict(nat="cone", loss=.02, cgnat=True)}

def sh(c):
    subprocess.run(c, shell=True, check=True)

def ns(n, c):
    sh("ip netns exec %s %s" % (n, c))

def nat(n, wan, kind):
    ns(n, "sysctl -qw net.ipv4.ip_forward=1")
    ns(n, "iptables -t nat -A POSTROUTING -o %s -j MASQUERADE%s" % (wan, " --random-fully" if kind == "symmetric" else ""))
    ns(n, "iptables -A FORWARD -i %s -m state --state NEW -j DROP" % wan)
    ns(n, "iptables -A INPUT -i %s -m state --state NEW -j DROP" % wan)

def main(profiles, talk=8, events=()):
    names = ["inet"]
    clean = lambda: [subprocess.run("ip netns del %s" % n, shell=True, stderr=subprocess.DEVNULL) for n in os.popen("ip netns list").read().split() if n.startswith(("lab_",))]
    clean()
    def mk(n):
        sh("ip netns add lab_%s" % n); ns("lab_" + n, "ip link set lo up"); return "lab_" + n
    inet = mk("inet")
    ns(inet, "ip link add br0 type bridge"); ns(inet, "ip addr add 203.0.113.1/24 dev br0"); ns(inet, "ip addr add 203.0.113.2/24 dev br0"); ns(inet, "ip link set br0 up")
    pcs, net_of, k = [], [], 0
    for i, p in enumerate(profiles):
        if p == "same":
            r = net_of[-1]
        else:
            k += 1
            cfg = PROF[p]
            r = mk("r%d" % k)
            up_ns, up_ip, up_gw = inet, "203.0.113.%d/24" % (10 + k), None
            if cfg.get("cgnat"):                                     # carrier NAT between the phone and the internet
                c = mk("c%d" % k)
                sh("ip link add cw%d netns %s type veth peer name cb%d netns %s" % (k, c, k, inet))
                ns(inet, "ip link set cb%d master br0" % k); ns(inet, "ip link set cb%d up" % k)
                ns(c, "ip addr add 203.0.113.%d/24 dev cw%d" % (10 + k, k)); ns(c, "ip link set cw%d up" % k)
                sh("ip link add w%d netns %s type veth peer name ci%d netns %s" % (k, r, k, c))
                ns(c, "ip addr add 100.64.%d.1/24 dev ci%d" % (k, k)); ns(c, "ip link set ci%d up" % k)
                ns(r, "ip addr add 100.64.%d.2/24 dev w%d" % (k, k)); ns(r, "ip link set w%d up" % k)
                ns(r, "ip route add default via 100.64.%d.1" % k)
                nat(c, "cw%d" % k, "symmetric")
            else:
                sh("ip link add w%d netns %s type veth peer name b%d netns %s" % (k, r, k, inet))
                ns(inet, "ip link set b%d master br0" % k); ns(inet, "ip link set b%d up" % k)
                ns(r, "ip addr add 203.0.113.%d/24 dev w%d" % (10 + k, k)); ns(r, "ip link set w%d up" % k)
                ns(r, "ip route add default via 203.0.113.1")
            nat(r, "w%d" % k, cfg["nat"])
            ns(r, "ip link add lan type bridge"); ns(r, "ip addr add 192.168.1.1/24 dev lan"); ns(r, "ip link set lan up")
            if cfg.get("noudp"):
                ns(r, "iptables -I FORWARD -i lan -p udp ! --dport 53 -j DROP")
            if cfg["loss"]:
                ns(r, "iptables -I FORWARD -p udp -m statistic --mode random --probability %s -j DROP" % cfg["loss"])
        net_of.append(r)
        pc = mk("pc%d" % i)
        sh("ip link add v%d netns %s type veth peer name e0 netns %s" % (i, r, pc))
        ns(r, "ip link set v%d master lan" % i); ns(r, "ip link set v%d up" % i)
        ns(pc, "ip addr add 192.168.1.%d/24 dev e0" % (10 + i)); ns(pc, "ip link set e0 up"); ns(pc, "ip route add default via 192.168.1.1")
        pcs.append(pc)
    srv = subprocess.Popen("ip netns exec %s python3 -u %s/servers.py 203.0.113.1 203.0.113.2" % (inet, D), shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for f in ("/tmp/natlab_code", "/tmp/natlab_word"):
        if os.path.exists(f): os.remove(f)
    time.sleep(1)
    n = len(profiles)
    procs = []
    for i, pc in enumerate(pcs):
        role = "host" if i == 0 else "guest"
        procs.append(subprocess.Popen("ip netns exec %s env WORD=1 NPL=%d PNAME=P%d python3 %s/peer.py %s 203.0.113.1 %s" % (pc, n, i, D, role, talk),
                                      shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
        time.sleep(3 if i == 0 else 0.5)
    import threading
    def disturb():                       # ("udp", i, t) block UDP for player i's network at t s; ("down", i, t, d) cut it all for d s
        t0 = time.time()
        for ev in sorted(events, key=lambda e: e[2]):
            time.sleep(max(0, ev[2] - (time.time() - t0)))
            r = net_of[ev[1]]
            if ev[0] == "udp":
                ns(r, "iptables -I FORWARD -p udp -j DROP"); print("[lab] UDP blocked for P%d" % ev[1], flush=True)
            else:
                ns(r, "iptables -I FORWARD -j DROP"); print("[lab] P%d offline for %d s" % (ev[1], ev[3]), flush=True)
                time.sleep(ev[3]); ns(r, "iptables -D FORWARD -j DROP"); print("[lab] P%d back online" % ev[1], flush=True)
    threading.Thread(target=disturb, daemon=True).start()
    outs = [p.communicate(timeout=300)[0] for p in procs]
    for i, o in enumerate(outs):
        open("/tmp/lab2_P%d.out" % i, "w").write(o)
    srv.kill()
    clean()
    res = []
    for i, o in enumerate(outs):
        try:
            res.append(json.loads(o.strip().splitlines()[-1]))
        except Exception:
            res.append({"crash": o[-1500:]})
    return res

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.replace(".", "").isdigit() and "@" not in a]
    evs = []
    for a in sys.argv[1:]:
        if a.startswith("udp@"):                          # udp@1:40  -> block UDP for P1 at 40 s
            i, t = a[4:].split(":"); evs.append(("udp", int(i), float(t)))
        elif a.startswith("down@"):                       # down@1:40:12 -> P1 offline at 40 s for 12 s
            i, t, d = a[5:].split(":"); evs.append(("down", int(i), float(t), float(d)))
    talk = next((float(a) for a in sys.argv[1:] if a.replace(".", "").isdigit()), 30 if evs else 8)
    for i, r in enumerate(main(args, talk, evs)):
        if "crash" in r:
            print("P%d %-6s CRASH %s" % (i, args[i], r["crash"])); continue
        print("P%d %-6s %-8s NAT %-9s route %-40s err %r" % (i, args[i], r["state"], r["nat"], r.get("route", ""), r["error"]))
        for k, v in sorted(r.get("voices", {}).items()):
            print("      hears %s: %s" % (k, v))
