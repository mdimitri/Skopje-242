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


class SegFormer:
    name = "segformer"

    def __init__(self, log):
        import torch
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
        self.torch = torch
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        mid = MODEL_GPU if self.dev == "cuda" else MODEL_CPU
        log(f"модел {mid} на {self.dev} (прв пат се симнува)")
        self.proc = SegformerImageProcessor.from_pretrained(mid)
        self.model = SegformerForSemanticSegmentation.from_pretrained(mid).to(self.dev).eval()

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
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"] + args
    log("инсталирам: " + " ".join(args))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in p.stdout:
        line = line.strip()
        if line.startswith(("Downloading", "Installing", "Successfully", "ERROR")):
            log("  " + line[:110])
    return p.wait() == 0


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
