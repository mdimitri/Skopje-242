"""NAT lab player: peer.py host|guest <internet server ip> <seconds of talk> -> JSON result on stdout (last line)."""
import json, os, sys, time
sl = None
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
import numpy as np
import discovery, mp, mpprofile as profile, voice
role, srv, talk = sys.argv[1], sys.argv[2], float(sys.argv[3])
discovery.STUN[:] = [(srv, 3478), (srv[:-1] + "2", 3478)]
discovery.BROKERS[:] = [(srv, 1883)]
p = profile.Profile("/nonexistent/p.json"); p.name, p.uid = ("Мартин", "hA") if role == "host" else ("Ана", "gB")
ses = mp.Session(p)
ses.voice = v = voice.Voice({"voice_on": True, "voice_mode": 0, "voice_vad": 0.02})
v.ins = object(); v.mic_name = "lab"; v.mic_rate = 16000
t = np.arange(voice.RATE * 4) / voice.RATE
sig = (0.3 * np.sin(2 * np.pi * (220 if role == "host" else 330) * t) * (np.sin(2 * np.pi * 0.5 * t) > -0.3)).astype(np.float32)
log, t0 = [], time.time()
clock = {"mic": time.monotonic(), "out": time.monotonic()}
def step(feed=False, k=[0]):
    now = time.monotonic()                       # real-time pacing like the sound card: one frame per 20 ms elapsed
    while clock["mic"] < now:
        clock["mic"] += 0.02
        if feed:
            v.mic_frame(sig[(k[0] * 320) % (len(sig) - 320):][:320], clock["mic"]); k[0] += 1
    ses.update()
    while clock["out"] < time.monotonic():
        clock["out"] += 0.02; v.mix(clock["out"])
    time.sleep(0.01)
if role == "host":
    ses.host(internet=True)
    wrote = False
    while time.time() - t0 < 40 and len(ses.players) < 2:
        step()
        if not wrote and not ses._busy:
            open("/tmp/natlab_code", "w").write(mp.make_code(ses._info())); wrote = True
        if ses.word and ses.mqtt and ses.mqtt.connected and not os.path.exists("/tmp/natlab_word"):
            open("/tmp/natlab_word", "w").write(ses.word)
    log.append("pub %s, players %d" % (ses.pub, len(ses.players)))
    for _ in range(50): step()
    ses.send_chat("здраво од домаќинот")
    for _ in range(50): step()
    ses.start()
else:
    ses.browse()
    g = None
    while time.time() - t0 < 30 and not g:
        step()
        if os.environ.get("WORD"):                 # join with the short word code read out on the phone
            if os.path.exists("/tmp/natlab_word") and not log:
                w = open("/tmp/natlab_word").read()
                log.append("word " + w)
                import joinwords
                sl = joinwords.slug(w.upper().replace(" ", "-"))
                ses.lookup(sl)
            if log:
                g = ses.code_hits.get(sl)
                ses.found.clear()
        elif os.environ.get("CODE"):                 # join with the code the host "sent over WhatsApp"
            if os.path.exists("/tmp/natlab_code"):
                code = open("/tmp/natlab_code").read()
                log.append("code " + code)
                g = mp.parse_code(code.lower().replace("-", " "))
                ses.found.clear()
        else:
            g = next(iter(ses.games().values()), None)
    log.append("found %s" % (g and {k: g[k] for k in ("name", "addr", "laddr")}))
    if g: ses.join(g)
    while time.time() - t0 < 50 and ses.state == "connecting": step()
    log.append("state %s err %r route %r" % (ses.state, ses.error, ses.route))
    for _ in range(50): step()
    ses.send_chat("здраво од гостинот")
    while time.time() - t0 < 60 and ses.state == "lobby": step()
t1 = time.time()
while time.time() - t1 < talk: step(feed=True)
for _ in range(150): step()                      # let the 2 s reports and the quality decision settle
other = 1 if role == "host" else 0
hear, them = ses.voice_report(other)
j = v.jit.get(other)
print(json.dumps({"role": role, "log": log, "state": ses.state, "chat": [c[1] for c in ses.chat], "info": ses.info(),
                  "voice_rx_frames": j.recv if j else 0, "loss": j.loss_pct() if j else None, "jitter_ms": int(j.jit) if j else None,
                  "fec_fixed": j.fixed if j else 0, "tier": voice.TIERS[v.tier][0], "why": v.link, "hear": hear, "them": them,
                  "tx_packets": v.tx_packets, "nat": ses.nat, "error": ses.error}, ensure_ascii=False))
