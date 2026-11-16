"""Render one long sentence in Suze + per-character voice colour. Usage: make_samples.py OUTDIR"""
import os, sys, subprocess, time, numpy as np, soundfile as sf
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
import voicelab as V
TEXT = ("Добар ден, јас сум жител на Скопје и секое утро одам преку Каменот мост, го гледам Вардар како тече под него, "
        "а потоа пијам кафе на плоштадот и ги слушам сите муабети за градот. Ако ме прашате, ова е најубавото место на светот!")
# (file, display name, params)
C = [
 ("00_suze_original", "Сузе (оригинал, без обработка)", None),
 ("mile", "Таксист Миле", dict(f0=108, rng=1.0, alpha=.90, tilt=-2, rough=.25, rate=1.12)),
 ("doktor", "Доктор Владимир", dict(f0=98, rng=.8, alpha=.86, tilt=-3, rate=.95)),
 ("influenser", "Инфлуенсер Давид", dict(f0=145, rng=1.5, alpha=.98, tilt=3, rate=1.2)),
 ("influenserka", "Инфлуенсерка Сара", dict(f0=235, rng=1.5, alpha=1.08, tilt=2, breath=.1, rate=1.2)),
 ("tetkica", "Теткица Весна", dict(f0=205, rng=1.25, alpha=1.04, vib=.2, rate=1.05)),
 ("baba", "Баба Велика", dict(f0=172, rng=.9, alpha=1.0, vib=1.0, rough=.3, tilt=-4, rate=.8)),
 ("dedo", "Дедо Димче", dict(f0=95, rng=.9, alpha=.93, vib=.9, rough=.35, tilt=-4, rate=.78)),
 ("pandur", "Пандур Бобан", dict(f0=88, rng=.7, alpha=.83, tilt=-2, rough=.35, rate=1.0)),
 ("radnik", "Работник Момчило", dict(f0=100, rng=.9, alpha=.90, rough=.4, rate=1.0)),
 ("burek", "Бурек-мајстор Благоја", dict(f0=114, rng=1.3, alpha=.92, rate=1.1)),
 ("boza", "Боза-мајстор Љупчо", dict(f0=122, rng=1.1, alpha=.95, vib=.2, rate=1.0)),
 ("fitka", "Фит-женска Теа", dict(f0=230, rng=1.3, alpha=1.08, tilt=3, rate=1.15)),
 ("bilder", "Билдер Дарко", dict(f0=80, rng=.6, alpha=.80, tilt=-3, rate=.95)),
 ("shmizla", "Шмизла Кики", dict(f0=262, rng=1.5, alpha=1.12, breath=.3, rate=1.1)),
 ("srednoskolec", "Средношколец Михаил", dict(f0=150, rng=1.3, alpha=.98, rough=.1, rate=1.2)),
 ("vojnik", "Војник Сашо", dict(f0=105, rng=.6, alpha=.90, tilt=1, rate=1.15)),
 ("navivac", "Навивач Дуле", dict(f0=118, rng=1.4, alpha=.90, rough=.5, rate=1.15)),
 ("administratorka", "Административка Славица", dict(f0=195, rng=.7, alpha=1.02, tilt=1, rate=1.0)),
 ("nastavnica", "Наставничка Снежана", dict(f0=185, rng=1.1, alpha=1.0, rate=.95)),
 ("mali", "Мали (дете)", dict(f0=300, rng=1.4, alpha=1.22, rate=1.1)),
 ("kumplung", "Чичко Кумплунг", dict(f0=92, rng=.9, alpha=.87, rough=.3, vib=.3, rate=.9)),
 ("maca", "Певаљка Маца", dict(f0=215, rng=1.6, alpha=1.05, breath=.35, vib=.5, rate=.95)),
 ("stojan", "Студент Стојан", dict(f0=125, rng=1.1, alpha=.96, rate=1.1)),
 ("palavko", "Палавко", dict(f0=130, rng=1.5, alpha=.97, rate=1.25)),
]
if __name__ == "__main__":
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    raw = os.path.join(out, "raw.wav")
    subprocess.run(["/home/user/rhvoice/RHVoice/build/linux/test/RHVoice-test", "-o", raw], input=TEXT.encode(), check=True,
                   env=dict(os.environ, RHVOICE_DATA_PATH="/home/user/rhvoice/data"))
    x, sr = sf.read(raw)
    t = time.time(); cache = V.analyse(x, sr, fast=False); ta = time.time() - t
    print("analysis %.2fs for %.1fs of speech" % (ta, len(x) / sr))
    for fn, name, p in C:
        t = time.time()
        y = x.astype(np.float32) * .9 / np.max(np.abs(x)) if p is None else V.transform(x, p, sr, cache)
        dt = time.time() - t
        sf.write(os.path.join(out, fn + ".wav"), y, sr)
        print("%-18s %-28s synth %.2fs  %.1fs audio" % (fn, name, dt, len(y) / sr))
