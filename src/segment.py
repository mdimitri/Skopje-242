"""Street-scene labels for src/photogram.py: which pixels are building facade, and which are sky, vegetation, vehicles / people,
ground or something else.  Two backends:

  segformer  SegFormer trained on Cityscapes (street scenes: building, vegetation, car, sky, road ... as classes of their own).
             torch + transformers are installed into the game's Python on first use (CUDA build when there is an NVIDIA card),
             the model weights come from Hugging Face (cached in the user's profile).
  simple     colour rules, no download: green / yellow-green = vegetation, blue or bright-grey at the top = sky.  Only good enough
             to keep the builder working when the model cannot be had.
Label maps are cached as PNGs next to the photos (<folder>/_photogram/<name>.<backend>.png).
"""
import importlib
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image

OTHER, BUILDING, SKY, VEG, VEHICLE, GROUND = 0, 1, 2, 3, 4, 5
MODEL_GPU = "nvidia/segformer-b5-finetuned-cityscapes-1024-1024"
MODEL_CPU = "nvidia/segformer-b2-finetuned-cityscapes-1024-1024"
# Cityscapes train ids -> ours: road, sidewalk | building | wall, fence, pole, light, sign | vegetation | terrain | sky | person,
# rider, car, truck, bus, train, motorcycle, bicycle
CITYSCAPES = np.array([GROUND, GROUND, BUILDING, OTHER, OTHER, OTHER, OTHER, OTHER, VEG, GROUND, SKY,
                       VEHICLE, VEHICLE, VEHICLE, VEHICLE, VEHICLE, VEHICLE, VEHICLE, VEHICLE], np.uint8)
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
_ONE = {}


def _cached(path):
    try:
        return np.asarray(Image.open(path))
    except OSError:
        return None


def _save(lab, path):
    try:
        Image.fromarray(lab).save(path)
    except OSError:
        pass


class Simple:
    name = "simple"

    def labels(self, img, cache=None):
        got = _cached(cache) if cache else None
        if got is not None and got.shape == img.shape[:2]:
            return got
        f = img.astype(np.int16)
        r, g, b = f[..., 0], f[..., 1], f[..., 2]
        lum = (3 * r + 6 * g + b) // 10
        lab = np.full(img.shape[:2], BUILDING, np.uint8)
        H = img.shape[0]
        top = np.zeros(img.shape[:2], bool)
        top[: int(H * 0.6)] = True
        sky = top & (((b > r + 12) & (lum > 120)) | ((lum > 200) & (np.abs(r - b) < 18) & (np.abs(g - b) < 18)))
        veg = ((g > r + 6) & (g > b + 4)) | ((2 * g - r - b > 26) & (lum < 170)) | ((r > b + 30) & (g > b + 30) & (np.abs(r - g) < 25) & (lum < 150))
        lab[veg] = VEG
        lab[sky] = SKY
        if cache:
            _save(lab, cache)
        return lab


def _quiet():
    """Library chatter that is not ours (missing torchvision, no HF token, no symlinks on Windows) out of the builder log."""
    import warnings
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
    warnings.filterwarnings("ignore", module="huggingface_hub")
    warnings.filterwarnings("ignore", module="transformers")
    try:
        from transformers.utils import logging as tl
        tl.set_verbosity_error()
        from huggingface_hub.utils import logging as hl
        hl.set_verbosity_error()
    except Exception:  # noqa: BLE001
        pass


FETCH = """import sys
from huggingface_hub import list_repo_files, snapshot_download
mid = sys.argv[1]
files = list_repo_files(mid)
w = ["*.safetensors"] if any(f.endswith(".safetensors") for f in files) else ["pytorch_model.bin"]
snapshot_download(mid, allow_patterns=["*.json"] + w)
"""


def fetch(mid, log, stall=90.0):
    """The model weights into the Hugging Face cache, in a child process that can be killed: Xet transfer first, plain HTTPS
    when that stalls (no new bytes for `stall` s), MB progress in the log.  -> True when the files are there."""
    import time
    try:
        from huggingface_hub import constants
        root = os.path.join(constants.HF_HUB_CACHE, "models--" + mid.replace("/", "--"))
    except Exception:  # noqa: BLE001
        root = None

    def size():
        if not root or not os.path.isdir(root):
            return 0
        return sum(os.path.getsize(os.path.join(dp, f)) for dp, _d, fn in os.walk(root) for f in fn
                   if not os.path.islink(os.path.join(dp, f)))
    for extra, how in (({}, "Xet"), ({"HF_HUB_DISABLE_XET": "1"}, "HTTPS")):
        log(f"веси на моделот ({how}) ...")
        p = subprocess.Popen([sys.executable, "-c", FETCH, mid], env={**os.environ, **extra}, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        last, t_last = size(), time.time()
        while p.poll() is None:
            time.sleep(3.0)
            got = size()
            if got != last:
                log(f"  веси: {got / 1e6:.0f} MB")
                last, t_last = got, time.time()
            elif time.time() - t_last > stall:
                log(f"  {how}: нема нови бајти {stall:.0f} s, прекинувам")
                p.kill()
                break
        if p.wait() == 0:
            return True
        err = (p.stderr.read() or "").strip().splitlines()
        if err:
            log("  " + err[-1][:110])
    return False


class SegFormer:
    name = "segformer"

    def __init__(self, log):
        _quiet()
        import torch
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
        self.torch = torch
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        mid = MODEL_GPU if self.dev == "cuda" else MODEL_CPU
        log(f"модел {mid} на {self.dev} (прв пат се симнува)")
        if not fetch(mid, log):
            raise RuntimeError("the model weights could not be downloaded")
        self.proc = SegformerImageProcessor.from_pretrained(mid)
        self.model = SegformerForSemanticSegmentation.from_pretrained(mid).to(self.dev).eval()
        log(f"модел вчитан ({'GPU: ' + torch.cuda.get_device_name(0) if self.dev == 'cuda' else 'CPU'})")

    def labels(self, img, cache=None):
        got = _cached(cache) if cache else None
        if got is not None and got.shape == img.shape[:2]:
            return got
        torch = self.torch
        with torch.no_grad():
            inp = self.proc(images=img, return_tensors="pt").to(self.dev)
            logits = self.model(**inp).logits
            up = torch.nn.functional.interpolate(logits, size=img.shape[:2], mode="bilinear", align_corners=False)
            cls = up.argmax(1)[0].to("cpu").numpy()
        lab = CITYSCAPES[np.clip(cls, 0, len(CITYSCAPES) - 1)]
        if cache:
            _save(lab, cache)
        return lab


def _pip(args, log):
    """pip install with its lines in the log; downloads report MB done every ~5 % (pip's raw progress bar)."""
    def go(extra):
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"] + extra + args
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        last, bad = -1, False
        for line in p.stdout:
            line = line.strip()
            if line.startswith("Progress ") and " of " in line:          # "Progress 123456 of 2887000000"
                try:
                    a, b = (int(v) for v in line[9:].split(" of "))
                    pc = int(100 * a / max(1, b))
                    if pc // 5 != last // 5 or a == b:
                        last = pc
                        log(f"  {a / 1e6:.0f} / {b / 1e6:.0f} MB ({pc} %)")
                except ValueError:
                    pass
            elif "no such option" in line or "invalid choice" in line:
                bad = True
            elif line and not bad and not line.startswith(("Usage:", sys.executable)):
                log("  " + line[:110])
        return p.wait() == 0, bad
    log("инсталирам: " + " ".join(args))
    ok, bad = go(["--progress-bar", "raw"])
    if bad:                                                           # an old pip: no raw progress
        ok, _ = go([])
    return ok


def install(log):
    """torch (+ CUDA when nvidia-smi is there) and transformers into this Python, when missing -> True when both import."""
    def has(m):
        try:
            importlib.import_module(m)
            return True
        except ImportError:
            return False
    if not has("torch"):
        _pip(["torch"] + (["--index-url", TORCH_INDEX] if shutil.which("nvidia-smi") else []), log)
    if not has("transformers"):
        _pip(["transformers"], log)
    importlib.invalidate_caches()
    return has("torch") and has("transformers")


def get(kind="auto", log=print):
    """The labeller: 'segformer', 'simple' or 'auto' (SegFormer, installed when missing; the colour rules when that fails)."""
    if kind in _ONE:
        return _ONE[kind]
    seg = None
    if kind in ("auto", "segformer"):
        try:
            if os.environ.get("SK242_NO_INSTALL") != "1":
                install(log)
            seg = SegFormer(log)
        except Exception as e:  # noqa: BLE001 - no network / no disk / no wheel for this Python
            log(f"SegFormer не може ({type(e).__name__}: {str(e)[:120]}); боја-правила наместо модел")
    if seg is None:
        seg = Simple()
    _ONE[kind] = seg
    return seg
