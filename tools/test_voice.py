"""Voice chat test (no sound card needed): codec quality, jitter buffer under loss/jitter/reorder, host relay over loopback UDP,
both-direction reports, blocked voice path, malformed packets, missing PortAudio / silent-mic reasons."""
import os, random, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np
import mp, mpprofile as profile, voice

def speech(n, seed=0):
    """Speech-like test signal: voiced harmonics with a syllable envelope plus a little noise."""
    r = np.random.default_rng(seed); t = np.arange(n) / voice.RATE
    f0 = 140 + 30 * np.sin(2 * np.pi * 0.7 * t)
    ph = 2 * np.pi * np.cumsum(f0) / voice.RATE
    x = sum(np.sin(k * ph) / k for k in range(1, 12))
    env = np.clip(np.sin(2 * np.pi * 3 * t), 0, None) ** 0.7
    return (0.25 * x * env + 0.003 * r.standard_normal(n)).astype(np.float32)

# ---- 1 codec
x = speech(voice.RATE * 2)
y = np.concatenate([voice.decode(voice.encode(f)) for f in x.reshape(-1, voice.FRAME)])
snr = 10 * np.log10(np.sum(x ** 2) / np.sum((x - y) ** 2))
assert len(voice.encode(x[:voice.FRAME])) == voice.FRAME_BYTES == 170
assert snr > 20, snr
q = voice.decode(voice.encode(0.001 * x[:voice.FRAME]))         # quiet input keeps its level
assert abs(np.abs(q).max() / np.abs(0.001 * x[:voice.FRAME]).max() - 1) < 0.15
print("OK codec: %d B/frame, %.0f kbit/s, SNR %.1f dB" % (voice.FRAME_BYTES, voice.FRAME_BYTES * 8 * 50 / 1000, snr))

# narrow band + FEC tiers
yn = np.concatenate([voice.dec_frame(voice.enc_frame(f, True), True) for f in x.reshape(-1, voice.FRAME)])
snr_n = 10 * np.log10(np.sum(x ** 2) / np.sum((x - yn) ** 2))
assert len(voice.enc_frame(x[:320], True)) == voice.NARROW_BYTES == 85 and snr_n > 10, snr_n
v = voice.Voice({"voice_mode": 2}); v.ins = object(); v.tier = 2
for k in range(12): v.mic_frame(x[k * 320:(k + 1) * 320], k * .02)
pk = v.take_packets(); assert len(pk) == 4 and all(p[4] & voice.F_NARROW for p in pk) and pk[1][4] & voice.F_FEC
r = voice.Voice({}); r.receive(1, pk[0], 0); r.receive(1, pk[2], .12); r.receive(1, pk[3], .16)     # pk[1] lost
assert r.jit[1].fixed == 3, r.jit[1].fixed
print("OK tiers: 8 kHz %d B/frame SNR %.1f dB (vs 16 kHz input), FEC rebuilt a lost packet (%d frames)" % (voice.NARROW_BYTES, snr_n, r.jit[1].fixed))
v = voice.Voice({}); v.adapt(1, 10, 40, 0); assert v.tier == 0
v.adapt(12, 10, 40, 1); assert v.tier == 2 and "загуба" in v.link
v.adapt(0, 10, 40, 5); assert v.tier == 2
v.adapt(0, 10, 40, 12); assert v.tier == 1
v.adapt(0, 10, 400, 30); assert v.tier == 1 and "пинг" in v.link
v.adapt(0, 10, 40, 45); assert v.tier == 0
v = voice.Voice({"voice_quality": 3}); v.adapt(0, 0, 10, 0); assert v.tier == 2
print("OK adaptive quality: drops at once on loss, climbs back one step per 10 s, ping/jitter, manual override")

# ---- 2 jitter buffer: 10 % loss, 0-80 ms jitter (reorders), 2 packets duplicated
for loss in (0.0, 0.1, 0.3):
    rng = random.Random(1)
    j, arr, seq = voice.Jitter(), [], 0
    for k in range(250):                         # 10 s, 2 frames per packet
        if rng.random() >= loss:
            arr.append((k * 0.04 + rng.uniform(0, 0.08), seq, k == 249))
        seq = (seq + 2) & 0xFFFF
    arr += [arr[10], arr[50]]
    arr.sort()
    got, i, t = 0, 0, 0.0
    while t < 11:
        while i < len(arr) and arr[i][0] <= t:
            j.push(arr[i][1], [np.full(voice.FRAME, .1, np.float32)] * 2, arr[i][2], arr[i][0]); i += 1
        f = j.pop(t)
        got += f is not None and f[0] == np.float32(.1)
        t += 0.02
    ratio = got / 500
    assert ratio > (1 - loss) * 0.9, (loss, ratio, j.late, j.lost)
    print("OK jitter: loss %d%% -> %.0f%% of frames played, late %d, buffer %d ms, jitter %.0f ms" % (loss * 100, ratio * 100, j.late, j.target() * 20, j.jit))
# 16-bit sequence wrap
j = voice.Jitter(); j.push(0xFFFE, [np.ones(voice.FRAME, np.float32)] * 2, False, 0); j.push(0, [np.ones(voice.FRAME, np.float32)] * 2, True, .04)
assert sum(j.pop(.1 + k * .02) is not None for k in range(4)) == 4
print("OK jitter: sequence wrap")
# a frame stuck behind the play head (old FEC copy) must not keep the buffer "busy" and push the play head ahead of new speech
j = voice.Jitter(); one = [np.ones(voice.FRAME, np.float32)] * 2
j.push(10, one, False, 0); j.frames[5] = one[0]
for k in range(30): j.pop(.1 + k * .02)
j.push(12, one, True, 1.0)
assert j.late == 0 and sum(j.pop(1.1 + k * .02) is not None for k in range(4)) == 2, (j.late, j.next)
print("OK jitter: stale frames dropped, next spurt plays")

# ---- 3 host + 2 guests over loopback, voice relayed by the host
def prof(name, uid):
    p = profile.Profile("/nonexistent/p.json"); p.name, p.uid = name, uid; return p
def pump(ss, secs, feed=(), until=None):
    t0 = time.time(); k = 0
    while time.time() - t0 < secs:
        for v, sig in feed:
            v.mic_frame(sig[(k * voice.FRAME) % (len(sig) - voice.FRAME):][:voice.FRAME], time.monotonic())
        k += 1
        for s in ss: s.update()
        if until and until(): return
        time.sleep(0.02)
cfg = {"voice_on": True, "voice_mode": 2, "voice_gain": 1.0, "voice_vol": 1.0}
h = mp.Session(prof("Мартин", "h1")); h.host(internet=False)
g = [mp.Session(prof(n, "g%d" % i)) for i, n in enumerate(["Ана", "Кико"])]
for s in [h] + g:
    s.voice = voice.Voice(cfg)
    s.voice.ins = object()                       # pretend a microphone is open (no sound card in the cloud)
for s in g: s.join({"addr": ["127.0.0.1", h.net.port], "lan": True})
pump([h] + g, 3, until=lambda: all(s.state == "lobby" for s in g) and len(h.players) == 3)
assert all(s.state == "lobby" for s in g)
# drop 15 % of every voice packet the guests send (lossy WiFi)
import mpnet
rng = random.Random(3)
real = mpnet.Net.send_voice
mpnet.Net.send_voice = lambda self, a, d: None if rng.random() < .15 else real(self, a, d)
sig = speech(voice.RATE * 3)
pump([h] + g, 3, feed=[(g[0].voice, sig), (h.voice, sig)])
mpnet.Net.send_voice = real
p1 = g[0].pid
assert p1 in h.voice.jit and p1 in g[1].voice.jit and 0 in g[1].voice.jit and 0 in g[0].voice.jit, \
    (h.voice.jit.keys(), g[1].voice.jit.keys())
assert p1 not in g[0].voice.jit                  # nobody hears himself
assert g[1].voice.jit[p1].recv > 50
out = np.concatenate([g[1].voice.mix(time.monotonic() + k * .02) for k in range(10)])
assert np.abs(out).max() > 0.01, "nothing audible in the mix"
pump([h] + g, 2.5)
hear, them = g[0].voice_report(0)
assert "загуба" in hear and "те слуша" in them, (hear, them)
lp = h.voice.jit[p1].loss_pct(); assert 8 <= lp <= 25, lp       # 15 % dropped on the way to the host
print("OK relay: host->guests and guest->host->guest, 15%% loss: %s | %s" % (hear, them))
print("   report on Ана about host:", g[1].voice_report(p1))

# ---- 4 voice blocked one way (e.g. a firewall that passes the game but not big UDP packets): the speaker is told
g[1].voice.tx_packets = 0
mpnet.Net.send_voice = lambda self, a, d: None if self is g[1].net else real(self, a, d)
pump([h] + g, 3, feed=[(g[1].voice, sig)])
mpnet.Net.send_voice = real
hear, them = g[1].voice_report(0)
assert "НЕ ПРИМА" in them, them
print("OK blocked voice path reported:", them)

# ---- 5 malformed packets are counted, not raised; spoofed pid is restamped by the host
bad = voice.VHDR.pack(0, 1, 2, 0) + b"x" * 10
assert not h.voice.receive(5, bad) and h.voice.bad_rx == 1 and "B for 2 frames" in h.voice.bad_why
assert not h.voice.receive(5, b"\x00")
bad2 = voice.VHDR.pack(0, 1, 1, 0) + b"\xff" * voice.FRAME_BYTES
assert not h.voice.receive(5, bad2) and "scale" in h.voice.bad_why
print("OK malformed packets: %d counted (%s)" % (h.voice.bad_rx, h.voice.bad_why))
for s in [h] + g: s.leave()

# ---- 6 device reasons
v = voice.Voice({"voice_on": True}); v.start()
print("   start() here:", v.mic_err or "mic ok", "|", v.out_err or "out ok")
import time as _t; _t.sleep(1); v.mic_frame  # real PortAudio (null device) here when libportaudio2 is installed
assert v.mic_err or (v._frames_in > 0 and not v.cb_err), (v.mic_err, v.cb_err)
v.close()
real_sd = voice._sd
def nopa(): raise OSError("PortAudio library not found")
voice._sd = nopa
v = voice.Voice({"voice_on": True}); v.start(); voice._sd = real_sd
assert "PortAudio" in v.mic_err and v.mic_state() == "nomod", v.mic_err
def noimp(): raise ImportError("No module named 'sounddevice'")
voice._sd = noimp
v = voice.Voice({"voice_on": True}); v.start(); voice._sd = real_sd
assert "run.bat setup" in v.mic_err and v.mic_state() == "nomod"
v = voice.Voice({"voice_on": True}); v.ins = object(); v.mic_name = "USB"; v.started = True
for k in range(200): v.mic_frame(np.zeros(voice.FRAME, np.float32), k * .02)
assert v.mic_state() == "silent" and "тишина" in v.mic_line()
v = voice.Voice({"voice_on": False}); v.start(); assert v.mic_state() == "off"
v = voice.Voice({"voice_on": True, "voice_mode": 0, "voice_vad": .02}); v.ins = object()
for k in range(50): v.mic_frame(0.001 * sig[:voice.FRAME], k * .02)
assert not v.take_packets(), "voice activation sent background noise"
for k in range(50): v.mic_frame(sig[1300:1300 + voice.FRAME], 1 + k * .02)
assert v.take_packets()
v = voice.Voice({"voice_on": True, "voice_mode": 1}); v.ins = object()
v.mic_frame(sig[1300:1620], 0); assert not v.take_packets(); v.ptt = True
for k in range(4): v.mic_frame(sig[1300:1620], k * .02)
v.ptt = False; v.mic_frame(sig[1300:1620], 1)
pk = v.take_packets(); assert len(pk) == 3 and pk[-1][4] & voice.F_END and not pk[0][4] & voice.F_END, [(len(x), x[4]) for x in pk]
print("OK reasons: no PortAudio, silent mic, off, voice activation gate, push-to-talk + end flag")
print("ALL VOICE TESTS PASSED")
