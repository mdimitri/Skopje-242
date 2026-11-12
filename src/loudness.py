"""One loudness scale for every sound in the game.

Loudness is K-weighted (ITU BS.1770, the LUFS filter) over the active part of a sound: a loop counts whole, a one-shot only the
100 ms blocks within 25 dB of its loudest, so a short bang and a long rumble can be compared.  REF gives, per sound key (longest
matching prefix wins), the loudness in LUFS the sound has when the game asks for it at volume 1.0; the call sites then scale that by
their own volume (footsteps ask for 0.3-0.55, an explosion 1.0, ...), so the numbers below are what you hear at the volume the code
uses plus 20*log10(volume).  Music files are already at -18 LUFS (radio plays at 0.56 x -> about -23 effective), speech is levelled
per clip (SPEECH_LUFS).  Procedural sounds (audio.build) and library files (soundproc) both end up here, so they match each other.
"""
import math

import numpy as np

SPEECH_LUFS = -20.0
BED = -24.0                                  # background ambience at volume 1.0 (the game mixes beds at 0.1-0.55)

REF = (
    # explosions, weapons
    ("boom_distant", -23), ("boom_rocket", -13), ("boom", -13), ("rocket_launch", -17), ("fire_crackle", -27), ("fire_ignite", -20), ("fire_out_hiss", -25),
    ("shot_distant", -24), ("shot", -16), ("bullet_", -21), ("weapon_pickup", -20), ("gun_jingle", -22),
    # impacts
    ("crash_light", -21), ("crash_glass", -20), ("crash_metal", -20), ("crash_wood", -21), ("crash", -17), ("tree_break", -19), ("prop_thud", -22),
    ("kerb_bump", -22), ("bin_clang", -21), ("glass_bottle", -22), ("tin_roof_bang", -22),
    # fighting and bodies
    ("punch", -19), ("kick", -19), ("bat_hit", -18), ("knuckles_hit", -19), ("chain_hit", -19), ("chain_swing", -24), ("swing", -24), ("body_fall", -20),
    ("body_hit_car", -20), ("hurt_thud", -21), ("cpr_pump", -24), ("defib_zap", -23),
    # vehicles
    ("horn_jingle", -22), ("horn", -18), ("siren_distant", -29), ("siren", -15), ("train_horn", -24), ("car_alarm", -20),
    ("engine_start", -19), ("engine_stall", -22), ("engine_misfire", -21), ("engine_knock", -21), ("ai_engine", -20), ("engine", -20),
    ("car_passby", -20), ("truck_passby", -19), ("tyre_roll", -30), ("tyre_gravel", -27), ("screech", -22), ("car_door", -21), ("handbrake", -24),
    ("bus_", -21), ("fuel_", -22),
    # people, animals
    ("step_run", -22), ("step_", -23), ("land_", -22), ("jump_up", -26), ("vault_car", -22), ("puddle_step", -24),
    ("bark_", -18), ("yip", -19), ("dog", -20), ("bird_", -27), ("cat_", -23), ("cow_bell", -23), ("sheep", -23), ("donkey", -22), ("horse", -22),
    ("frog_croak", -26), ("rat_", -26), ("bee_", -29), ("fly_", -29), ("crowd_applause", -24), ("crowd_", -22), ("kids_laugh", -23), ("baby_cry", -23),
    ("whistle_ref", -21), ("coughing", -26), ("sneeze", -26), ("clap_hands", -24),
    # pick-ups and interface
    ("chime", -20), ("tick", -24), ("pick", -21), ("cash", -21), ("revive", -19), ("eat", -21), ("ui_click", -22), ("ui_confirm", -20),
    ("denied_buzz", -22), ("teleport_whoosh", -22), ("map_paper", -24),
    # water
    ("splash_big", -17), ("splash", -20), ("swim_stroke", -25), ("spray", -27),
    # buildings, city, machines
    ("door", -21), ("window_open", -25), ("shutter_roll", -23), ("laundry_flap", -26), ("tv_apartment", -28), ("scooter_bell", -23), ("bicycle_pass", -26),
    ("sweeper_machine", -24), ("garbage_truck", -21), ("bell", -21), ("clock_tower", -22),
    ("jackhammer", -24), ("concrete_mixer", -26), ("construction", -26), ("crane_hum", -27), ("hammer", -22), ("drill", -22), ("angle_grinder", -22),
    ("saw_wood", -24), ("shovel_gravel", -25), ("metal_clank", -22), ("truck_reverse_beep", -24), ("fence_rattle", -25), ("wheelbarrow", -26),
    ("street_lamp_buzz", -30), ("power_transformer_hum", -30), ("neon_buzz", -30),
    # beds (procedural fallbacks and library ambiences)
    ("crickets", -27), ("birds", -27), ("wind", -26), ("city", BED), ("traffic", BED), ("crowd", BED),
)


def ref(key, level=None):
    """LUFS at volume 1.0 for a sound key; library ambiences (amb_*) follow the catalogue level (0.4-0.7) around BED."""
    for p, v in REF:
        if key.startswith(p):
            return v
    return BED + (20 * math.log10(max(0.2, level) / 0.55) if level else 0.0)


_KW = {}


def _kfilter(n, sr):
    k = (n, sr)
    if k not in _KW:
        f = np.fft.rfftfreq(n, 1.0 / sr)
        z = np.exp(-2j * np.pi * f / sr)

        def bq(b, a):
            return (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
        G, Q, fc = 3.999843853973347, 0.7071752369554196, 1681.9744509555319
        K = math.tan(math.pi * fc / sr); Vh = 10 ** (G / 20); Vb = Vh ** 0.4996667741545416; a0 = 1 + K / Q + K * K
        shelf = bq([(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0], [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0])
        Q2, fc2 = 0.5003270373238773, 38.13547087613982
        K2 = math.tan(math.pi * fc2 / sr); d = 1 + K2 / Q2 + K2 * K2
        hp = bq([1, -2, 1], [1, 2 * (K2 * K2 - 1) / d, (1 - K2 / Q2 + K2 * K2) / d])
        if len(_KW) > 8:
            _KW.clear()
        _KW[k] = shelf * hp
    return _KW[k]


def lufs(x, sr, loop=False):
    """K-weighted loudness: whole signal for loops, the active 100 ms blocks (within 25 dB of the loudest) for one-shots."""
    x = np.asarray(x, np.float64)
    if len(x) < 64 or not np.abs(x).max() > 1e-6:
        return -99.0
    x = x[:1 << 20]
    pad = max(0, int(0.4 * sr) - len(x))
    xx = np.concatenate([x, np.zeros(pad)]) if pad else x
    w = np.fft.irfft(np.fft.rfft(xx) * _kfilter(len(xx), sr), len(xx))
    if loop:
        ms = float((w[:len(x)] ** 2).mean())
    else:
        hop = max(1, sr // 10)
        m = max(1, len(w) // hop)
        e = (w[:m * hop].reshape(m, hop) ** 2).mean(axis=1) if len(w) >= hop else np.array([(w ** 2).mean()])
        e = e[e > e.max() * 10 ** (-2.5)]
        ms = float(e.mean())
    return -0.691 + 10 * math.log10(ms + 1e-12)


PEAK = 0.89                                    # -1 dBFS


def level(x, sr, target, loop=False):
    """x scaled to the target LUFS.  If that would clip, the peaks are soft-clipped (tanh) rather than the sound made quieter,
    but never by more than 4 dB of loudness (a bang with a very high crest is then a little quieter than its target)."""
    cur = lufs(x, sr, loop)
    if cur < -90:
        return x.astype(np.float32)
    g = 10 ** ((target - cur) / 20.0)
    y = x.astype(np.float64) * g
    pk = float(np.abs(y).max())
    if pk > PEAK:
        y = np.tanh(y / PEAK) * PEAK
        lost = cur + 20 * math.log10(g) - lufs(y, sr, loop)
        if lost > 4.0:                                  # soft-clipping already cost too much: bring the peak down instead
            y = x.astype(np.float64) * g * 10 ** (-(lost - 4.0) / 20.0)
            y = np.tanh(y / PEAK) * PEAK
    return y.astype(np.float32)


def level_all(S, loops, sr):
    """Level a dict of procedural sounds in place.  Aliases of the same array (ai_ engines) are levelled once."""
    done = {}
    for k in list(S):
        i = id(S[k])
        if i not in done:
            done[i] = level(S[k], sr, ref(k), k in loops or any(k.startswith(p) for p in ("amb_",)))
        S[k] = done[i]
    return S
