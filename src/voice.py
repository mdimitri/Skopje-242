"""Multiplayer voice chat: microphone capture, a small loss-tolerant codec, per-player jitter buffers and playback.

Audio runs in PortAudio callbacks (the optional `sounddevice` module); the network side (mp.Session) calls
take_packets() / receive() from the game thread. Every failure is kept as a technical reason for the UI
(no module, no device, device refused, silent mic = privacy block, packet loss, malformed packets, timeouts).

Codec "BC4": 16 kHz mono, 20 ms frames, blocks of 32 samples = a log scale byte + 4-bit mu-law samples.
170 bytes per frame (68 kbit/s), every frame decodes on its own, so a lost packet never damages the next one.
"""
import math
import struct
import threading
import time

import numpy as np

RATE = 16000
FRAME = 320                      # 20 ms
BLOCK = 32
NBLK = FRAME // BLOCK
FRAME_BYTES = NBLK + FRAME // 2  # 170
FPP = 2                          # frames per packet (40 ms)
VHDR = struct.Struct("!BHBB")    # pid, seq of the first frame, frame count, flags
F_END = 1                        # last packet of a talk spurt (the gap after it is not loss)
F_NARROW = 2                     # frames are 8 kHz (160 samples, 85 B): half the bit rate
F_FEC = 4                        # the previous packet's frames ride along again: one lost packet in a row is rebuilt
NARROW_BYTES = FRAME // 2 // BLOCK + FRAME // 4
# adaptive quality: (label, narrow, frames per packet, fec)
TIERS = [("16 kHz, 68 kbit/s", False, 2, False), ("8 kHz, 36 kbit/s", True, 2, False), ("8 kHz + FEC, 60 kbit/s", True, 3, True),
         ("8 kHz преку реле, 34 kbit/s", True, 4, False)]       # relay (TCP): no loss to protect from, fewer messages
QUALITY = ["Автоматски (според врската)", "Високо (16 kHz)", "Ниско (8 kHz)", "Ниско + заштита од загуби"]
CODEC = 1
_MU = 4.0
_LV = 7
PTT_KEYS = ["V", "Лев Alt", "Caps Lock", "Средно копче (глувче)"]
MODES = ["Глас вклучува (автоматски)", "Држи копче за зборување", "Секогаш вклучен"]


# ---------------------------------------------------------------- codec
def encode(x):
    """float32[n] in [-1, 1] (n a multiple of BLOCK) -> n // BLOCK + n // 2 bytes."""
    x = np.nan_to_num(np.asarray(x, np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    b = np.clip(x, -1, 1).reshape(-1, BLOCK)
    peak = np.maximum(np.abs(b).max(1), 1e-5)
    s = np.clip(np.ceil(np.log2(peak * 32768) * 8), 0, 127).astype(np.uint8)
    q = (2.0 ** (s / 8.0) / 32768.0)[:, None]
    y = np.clip(b / q, -1, 1)
    c = np.rint(np.sign(y) * np.log1p(_MU * np.abs(y)) / math.log1p(_MU) * _LV).astype(np.int8) + 8   # 1..15
    c = c.reshape(-1).astype(np.uint8)
    return s.tobytes() + (c[0::2] << 4 | c[1::2]).astype(np.uint8).tobytes()


def decode(data, n=FRAME):
    nb = n // BLOCK
    if len(data) != nb + n // 2:
        raise ValueError("frame %d B, expected %d" % (len(data), nb + n // 2))
    s = np.frombuffer(data, np.uint8, nb).astype(np.float32)
    if s.max() > 127:
        raise ValueError("bad scale byte")
    p = np.frombuffer(data, np.uint8, n // 2, nb)
    c = np.empty(n, np.float32)
    c[0::2], c[1::2] = p >> 4, p & 15
    y = (c - 8) / _LV
    x = np.sign(y) * np.expm1(np.abs(y) * math.log1p(_MU)) / _MU
    return (x.reshape(nb, BLOCK) * (2.0 ** (s / 8.0) / 32768.0)[:, None]).reshape(-1).astype(np.float32)


def enc_frame(f, narrow):
    if narrow:                                   # 2:1 with a [1 2 1] low-pass so nothing above 4 kHz folds back
        g = np.convolve(f, (.25, .5, .25), "same")
        return encode(g[0::2])
    return encode(f)


def dec_frame(data, narrow):
    if narrow:
        h = decode(data, FRAME // 2)
        return np.interp(np.arange(FRAME) / 2.0, np.arange(FRAME // 2), h).astype(np.float32)
    return decode(data)


def _d16(a, b):
    """a - b on the 16-bit sequence circle."""
    return ((a - b + 0x8000) & 0xFFFF) - 0x8000


# ---------------------------------------------------------------- jitter buffer
class Jitter:
    """Frames of one speaker in, one frame every 20 ms out. Playout delay follows the measured jitter (40..240 ms)."""

    def __init__(self):
        self.frames, self.next, self.playing = {}, None, False
        self.jit = 0.0                    # ms, RFC 3550 style estimate
        self._ref = None                  # (arrival, seq) of the last packet
        self.last = None
        self.miss = 0
        self.ended = False
        self.recv = self.lost = self.late = self.bad = 0
        self.hi = None                    # newest frame seq seen; gaps below it that never arrive = network loss
        self.seen = 0
        self.fixed = 0
        self.floor = 2                    # minimum playout delay in frames (6 = 120 ms over the TCP relay)
        self.last_rx = 0.0
        self.level = 0.0
        self.wait_from = 0.0

    def loss_pct(self):
        return max(0, 100 * (self.seen - self.recv) // max(1, self.seen))

    def target(self):
        return max(self.floor, min(12, int(math.ceil((2.5 * self.jit + 20) / 20))))

    def push(self, seq, frames, end, now):
        self.last_rx = now
        if self._ref is not None:
            d = (now - self._ref[0]) * 1000 - _d16(seq, self._ref[1]) * 20
            if abs(d) < 2000:
                self.jit += (abs(d) - self.jit) / 16
        self._ref = (now, seq)
        top = (seq + len(frames) - 1) & 0xFFFF
        if self.hi is None:
            self.hi, self.seen = top, len(frames)
        elif _d16(top, self.hi) > 0:
            self.seen += _d16(top, self.hi)
            self.hi = top
        for i, f in enumerate(frames):
            s = (seq + i) & 0xFFFF
            if self.next is not None and self.playing and _d16(s, self.next) < 0:
                self.late += 1
                continue
            if self.next is not None and abs(_d16(s, self.next)) > 200:      # a long pause or a restart: start over
                self.frames.clear()
                self.next, self.playing = None, False
            if self.next is None:
                self.next, self.wait_from = s, now
            elif not self.playing and _d16(s, self.next) < 0:
                self.next = s
            self.frames[s] = f
            self.recv += 1
        self.ended = end

    def fill(self, seq, frames):
        """Frames rebuilt from forward error correction: only holes are filled, stats stay those of the network."""
        for i, f in enumerate(frames):
            s = (seq + i) & 0xFFFF
            if self.next is None or s in self.frames or _d16(s, self.next) < 0 or _d16(s, self.hi) > 0:
                continue
            self.frames[s] = f
            self.fixed += 1

    def pop(self, now):
        if self.next is None:
            return None
        if not self.playing:
            if len(self.frames) >= self.target() or self.ended or now - self.wait_from > self.target() * 0.02 + 0.06:
                self.playing, self.miss = True, 0
            else:
                return None
        f = self.frames.pop(self.next, None)
        if f is None and self.frames:                  # anything stuck behind the play head can never play: drop it
            for k in [k for k in self.frames if _d16(k, self.next) < 0]:
                del self.frames[k]
        self.next = (self.next + 1) & 0xFFFF
        if f is not None:
            self.miss, self.last = 0, f
            self.level = max(self.level * 0.8, float(np.abs(f).max()))
            return f
        self.miss += 1
        if not self.frames:                       # ran dry: end of speech, or a stall
            if not self.ended and self.miss <= 3:
                self.lost += 1
            if self.miss > 3 or self.ended:
                self.playing, self.next, self.ended = False, None, False
                self.last = None
                return None
        else:
            self.lost += 1
        if self.last is not None and self.miss <= 3:   # concealment: repeat the last frame, fading
            self.last = self.last * 0.5
            return self.last
        return None


# ---------------------------------------------------------------- devices
def _sd():
    import sounddevice as sd      # noqa: PLC0415 - optional dependency
    return sd


def input_devices():
    """[(index, name)] of capture devices, default first; [] when nothing can be listed."""
    try:
        sd = _sd()
        out, seen = [], set()
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                n = d["name"]
                api = sd.query_hostapis(d["hostapi"])["name"]
                if (n, api) not in seen:
                    seen.add((n, api))
                    out.append((i, "%s (%s)" % (n, api)))
        return out
    except Exception:      # noqa: BLE001 - no module / PortAudio error: the UI says why
        return []


def input_names():
    return ["Стандарден (системски)"] + [n for _, n in input_devices()]


def _resample(x, n):
    if len(x) == n:
        return x
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


# ---------------------------------------------------------------- engine
class Voice:
    def __init__(self, cfg=None):
        self.cfg = dict(cfg or {})
        self.lock = threading.Lock()
        self.jit = {}                    # pid -> Jitter
        self.peer_vol = {}               # pid -> 0..2 (0 = muted)
        self.out_q = []                  # encoded packets waiting for the game thread
        self.seq = 0
        self.mic_err = self.out_err = ""
        self.mic_name = ""
        self.mic_rate = self.out_rate = 0
        self.level = 0.0                 # mic peak after gain, 0..1
        self.talking = False
        self.ptt = False
        self._hang = 0.0
        self._pending = []
        self._was_tx = False
        self._prev = None                # (narrow, encoded frames, seq that follows them): FEC copy for the next packet
        self.tier = 0
        self.relayed = False
        self._good_since = 0.0
        self.link = ""                   # why this quality was chosen
        self._zero = 0                   # consecutive all-zero mic frames
        self._frames_in = 0
        self.overflow = self.underflow = 0
        self._last_in = self._reopen = 0.0
        self.restarts = 0
        self.cb_err = ""
        self._ovf0 = 0
        self.tx_packets = 0
        self.bad_rx = 0
        self.bad_why = ""
        self._acc = np.zeros(0, np.float32)
        self.ins = self.outs = None
        self.started = False

    # ---- settings
    def apply(self, cfg):
        old = (self.cfg.get("voice_on"), self.cfg.get("voice_mic"))
        self.cfg = {k: cfg[k] for k in ("voice_on", "voice_mic", "voice_mode", "voice_ptt", "voice_gain", "voice_vol", "voice_vad", "voice_quality")
                    if k in cfg}
        if self.started and old != (self.cfg.get("voice_on"), self.cfg.get("voice_mic")):
            self.close()
            self.start()

    def start(self):
        self.started = True
        self.mic_err = self.out_err = ""
        if not self.cfg.get("voice_on", True):
            self.mic_err = self.out_err = "исклучено во Поставки → Звук"
            return
        try:
            sd = _sd()
        except ImportError:
            self.mic_err = self.out_err = "нема модул sounddevice: пушти run.bat setup"
            return
        except Exception as e:      # noqa: BLE001 - sounddevice present but PortAudio cannot load
            self.mic_err = self.out_err = "PortAudio не се вчитува (sounddevice): %s" % _short(e)
            return
        self._open_out(sd)
        self._open_in(sd)

    def _open_out(self, sd):
        try:
            dev = sd.query_devices(kind="output")
        except Exception as e:      # noqa: BLE001
            self.out_err = "нема уред за звук (звучници/слушалки): %s" % _short(e)
            return
        for rate in (RATE, int(dev["default_samplerate"])):
            try:
                self.out_rate = rate
                self.outs = sd.OutputStream(samplerate=rate, channels=1, dtype="float32", blocksize=int(rate * 0.02),
                                            latency="low", callback=self._out_cb)
                self.outs.start()
                self.out_rate = rate
                return
            except Exception as e:      # noqa: BLE001
                self.outs = None
                self.out_err = "излезот не се отвора (%d Hz): %s" % (rate, _short(e))

    def _open_in(self, sd):
        want = self.cfg.get("voice_mic", "")
        devs = input_devices()
        if not devs:
            self.mic_err = "нема микрофон (ниеден уред за снимање во системот)"
            return
        idx = None
        if want:
            idx = next((i for i, n in devs if n == want), None)
            if idx is None:
                self.mic_err = "избраниот микрофон „%s“ го нема (исклучен?): се користи стандардниот" % want
        try:
            dev = sd.query_devices(idx, kind="input") if idx is not None else sd.query_devices(kind="input")
        except Exception as e:      # noqa: BLE001
            self.mic_err = "нема стандарден микрофон: %s" % _short(e)
            return
        self.mic_name = dev["name"]
        err = ""
        for rate in (RATE, int(dev["default_samplerate"])):
            try:
                self.mic_rate = rate
                self.ins = sd.InputStream(device=idx, samplerate=rate, channels=1, dtype="float32", blocksize=int(rate * 0.02),
                                          latency="low", callback=self._in_cb)
                self.ins.start()
                self.mic_rate = rate
                if not self.mic_err.startswith("избраниот"):
                    self.mic_err = ""
                return
            except Exception as e:      # noqa: BLE001
                self.ins = None
                err = _short(e)
        low = err.lower()
        if "unanticipated host error" in low or "access" in low or "denied" in low or "-9999" in low:
            self.mic_err = "пристапот до микрофонот е одбиен (Windows → Приватност → Микрофон): %s" % err
        elif "busy" in low or "in use" in low or "-9985" in low:
            self.mic_err = "микрофонот го користи друга програма: %s" % err
        else:
            self.mic_err = "микрофонот не се отвора: %s" % err

    def close(self):
        for s in (self.ins, self.outs):
            if s is not None:
                try:
                    s.stop()
                    s.close()
                except Exception:      # noqa: BLE001
                    pass
        self.ins = self.outs = None
        self.started = False

    # ---- capture (PortAudio thread)
    def _in_cb(self, indata, frames, t, status):
        try:
            self._in(indata, status)
        except Exception as e:      # noqa: BLE001 - an exception would stop the stream for good
            self.cb_err = "снимање: %s" % _short(e)

    def _in(self, indata, status):
        if status and status.input_overflow:
            self.overflow += 1
        x = np.nan_to_num(indata[:, 0], nan=0.0, posinf=0.0, neginf=0.0)
        if self.mic_rate != RATE:
            x = _resample(x, int(round(len(x) * RATE / self.mic_rate)))
        self._acc = np.concatenate((self._acc, x))
        while len(self._acc) >= FRAME:
            f, self._acc = self._acc[:FRAME], self._acc[FRAME:]
            self.mic_frame(f, time.monotonic())

    def mic_frame(self, f, now):
        """One 20 ms frame from the microphone (also called by tests)."""
        self._frames_in += 1
        self._last_in = now
        self._zero = self._zero + 1 if not np.any(f) else 0
        f = np.clip(f * float(self.cfg.get("voice_gain", 1.0)), -1, 1)
        pk = float(np.abs(f).max())
        self.level = max(pk, self.level * 0.85)
        mode = self.cfg.get("voice_mode", 0)
        if mode == 1:
            tx = self.ptt
        elif mode == 2:
            tx = True
        else:
            rms = float(np.sqrt(np.mean(f * f)))
            if rms > float(self.cfg.get("voice_vad", 0.02)):
                self._hang = now + 0.35
            tx = now < self._hang
        self.talking = tx
        if tx or self._was_tx:                   # the first silent frame closes the spurt and carries the end flag
            self._pending.append(f)
        self._was_tx = tx
        _, narrow, fpp, fec = TIERS[self.tier]
        if self._pending and (len(self._pending) >= fpp or not tx):
            end = not tx
            body = b"".join(enc_frame(x, narrow) for x in self._pending)
            flags = (F_END if end else 0) | (F_NARROW if narrow else 0)
            if fec and self._prev and self._prev[0] == narrow and self._prev[2] == self.seq:
                flags |= F_FEC
            pkt = VHDR.pack(0, self.seq, len(self._pending), flags) + body + (self._prev[1] if flags & F_FEC else b"")
            self.seq = (self.seq + len(self._pending)) & 0xFFFF
            self._prev = None if end else (narrow, body, self.seq)
            self._pending = []
            with self.lock:
                self.out_q.append(pkt)
                del self.out_q[:-50]          # never pile up while the game thread is blocked

    # ---- playback (PortAudio thread)
    def _out_cb(self, outdata, frames, t, status):
        try:
            self._out(outdata, frames, status)
        except Exception as e:      # noqa: BLE001
            outdata.fill(0)
            self.cb_err = "репродукција: %s" % _short(e)

    def _out(self, outdata, frames, status):
        if status and status.output_underflow:
            self.underflow += 1
        mix = self.mix(time.monotonic())
        if self.out_rate != RATE:
            mix = _resample(mix, frames)
        outdata[:, 0] = mix[:frames] if len(mix) >= frames else np.pad(mix, (0, frames - len(mix)))

    def mix(self, now):
        out = np.zeros(FRAME, np.float32)
        with self.lock:
            for pid, j in self.jit.items():
                f = j.pop(now)
                v = self.peer_vol.get(pid, 1.0)
                if f is not None and v > 0:
                    out += f * v
        return np.clip(out * float(self.cfg.get("voice_vol", 1.0)), -1, 1)

    # ---- network side (game thread)
    def take_packets(self):
        with self.lock:
            q, self.out_q = self.out_q, []
        self.tx_packets += len(q)
        return q

    def receive(self, pid, data, now=None):
        """A voice packet (VHDR + frames) from player pid. Bad packets are counted, never raised."""
        now = time.monotonic() if now is None else now
        try:
            _, seq, n, flags = VHDR.unpack_from(data)
            narrow = bool(flags & F_NARROW)
            fb = NARROW_BYTES if narrow else FRAME_BYTES
            extra = len(data) - VHDR.size - n * fb
            if n < 1 or n > 8 or extra < 0 or extra % fb or (extra and not flags & F_FEC) or extra // fb > 8:
                raise ValueError("%d B for %d frames" % (len(data), n))
            frames = [dec_frame(data[VHDR.size + i * fb: VHDR.size + (i + 1) * fb], narrow) for i in range(n)]
            k, o = extra // fb, VHDR.size + n * fb
            prev = [dec_frame(data[o + i * fb: o + (i + 1) * fb], narrow) for i in range(k)]
        except (struct.error, ValueError) as e:
            self.bad_rx += 1
            self.bad_why = str(e)
            with self.lock:
                if pid in self.jit:
                    self.jit[pid].bad += 1
            return False
        with self.lock:
            j = self.jit.get(pid)
            if j is None:
                j = self.jit[pid] = Jitter()
            j.floor = 6 if self.relayed else 2
            j.push(seq, frames, bool(flags & F_END), now)
            if prev:
                j.fill((seq - k) & 0xFFFF, prev)
        return True

    def adapt(self, loss, jitter, rtt, now):
        """Pick the quality from how the other players receive me (worst listener): drop at once, climb one step after 10 s good."""
        q = int(self.cfg.get("voice_quality", 0))
        if self.relayed:
            self.tier, self.link = 3, "врската оди преку реле (MQTT)"
            return
        if q:
            self.tier, self.link = {1: 0, 2: 1, 3: 2}[q], "рачно поставено"
            return
        why = []
        want = 0
        if loss is not None and loss >= 8:
            want, _ = 2, why.append("загуба %d%%" % loss)
        elif loss is not None and loss >= 3:
            want, _ = 1, why.append("загуба %d%%" % loss)
        if jitter is not None and jitter >= 60:
            want, _ = max(want, 1), why.append("џитер %d ms" % jitter)
        if rtt is not None and rtt >= 250:
            want, _ = max(want, 1), why.append("пинг %d ms" % rtt)
        if self.overflow > self._ovf0 + 5:
            want, _ = max(want, 1), why.append("компјутерот доцни")
        self._ovf0 = self.overflow
        if want >= self.tier:                    # _good_since = last moment the current quality was still needed
            self.tier, self._good_since = want, now
        elif now - self._good_since > 10:
            self.tier, self._good_since = self.tier - 1, now
        self.link = ", ".join(why) or "врската е добра"

    def watchdog(self, now):
        """A stream that stopped delivering (USB mic pulled, driver reset, Bluetooth headset switched) is opened again."""
        if not self.started or not self.cfg.get("voice_on", True) or now - self._reopen < 5:
            return
        dead_in = self.ins is not None and self._last_in and now - self._last_in > 3
        dead = dead_in or (self.ins is None and self.mic_err and "sounddevice" not in self.mic_err and "PortAudio" not in self.mic_err)
        if dead:
            self._reopen = now
            self.restarts += 1
            self.close()
            self.start()
            self._last_in = now if self.ins is not None else 0.0
            if dead_in and self.ins is None:
                self.mic_err = "микрофонот престана да праќа звук (исклучен?): " + self.mic_err

    def quality_line(self):
        return "%s (%s)" % (TIERS[self.tier][0], self.link or "се мери…")

    def forget(self, pid):
        with self.lock:
            self.jit.pop(pid, None)

    # ---- diagnostics
    def mic_state(self):
        """Short code the other players see: ok | off | nomod | nodev | err | silent | muted."""
        if not self.cfg.get("voice_on", True):
            return "off"
        if self.ins is None:
            return "nomod" if "sounddevice" in self.mic_err else ("nodev" if "нема микрофон" in self.mic_err else "err")
        if self._zero > 150:
            return "silent"
        return "ok"

    def mic_line(self):
        if self.ins is None:
            return self.mic_err or "не е стартуван"
        if self._zero > 150:
            return "микрофонот праќа чиста тишина 3 s: Windows ја блокира (Приватност → Микрофон) или е исклучен на уредот"
        if self._frames_in == 0 and self.started:
            return "микрофонот е отворен но не праќа звук (драјвер?)"
        if self.level < 0.003:
            return "%s: многу тивко, зголеми го засилувањето" % self.mic_name
        if self.cb_err:
            return "грешка во звучниот тек: " + self.cb_err
        s = "%s · %d Hz" % (self.mic_name, self.mic_rate) + (" · повторно отворен %d×" % self.restarts if self.restarts else "")
        return s + (" · препреполнет бафер %d" % self.overflow if self.overflow else "")

    def peer_line(self, pid, now=None):
        """How this player's voice reaches me (loss, late, jitter, buffer, last packet)."""
        now = time.monotonic() if now is None else now
        j = self.jit.get(pid)
        if j is None:
            return "уште нема глас"
        s = "загуба %d%% · доцнат %d · џитер %d ms · бафер %d ms" % (j.loss_pct(), j.late, j.jit, j.target() * 20)
        if now - j.last_rx > 2 and j.recv:
            s += " · тишина %.0f s" % (now - j.last_rx)
        if j.bad:
            s += " · оштетени %d" % j.bad
        return s

    def rx_stats(self):
        with self.lock:
            return {str(p): [j.recv, j.loss_pct(), j.late, int(j.jit), j.bad] for p, j in self.jit.items()}

    def speaking(self, pid, now=None):
        now = time.monotonic() if now is None else now
        j = self.jit.get(pid)
        return j is not None and now - j.last_rx < 0.3


def _short(e):
    return (str(e) or type(e).__name__).replace("\n", " ")[:120]


MIC_CODES = {"ok": "микрофон во ред", "off": "гласот му е исклучен", "nomod": "нема sounddevice модул", "nodev": "нема микрофон",
             "err": "микрофонот не се отвора", "silent": "микрофонот му е блокиран (тишина)"}
