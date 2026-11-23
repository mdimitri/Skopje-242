"""Contact sheet of all heroes' mesh heads: row 1 neutral, row 2 mouth wide open + smile: shot_heads.py <out.png> [jaw]"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import pyray as rl
rl.init_window(200, 200, "t")
import facerig, characters
from PIL import Image
ONLY = [int(v) for v in os.environ["HEROES"].split(",")] if os.environ.get("HEROES") else list(range(len(characters.LIKOVI)))
N = len(ONLY); S = int(os.environ.get("S", 120)); cols = int(os.environ.get("COLS", 12))
jaw = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
sheet = Image.new("RGB", (cols * S, (N // cols + 1) * 2 * S), (40, 40, 50))
for k, i in enumerate(ONLY):
    h = facerig.Head(i, 176)
    for r, e in enumerate(({}, {"jaw": jaw, "smile": .3, "tongue": .5})):
        h.render(e, rl.Color(30, 30, 40, 255))
        img = rl.load_image_from_texture(h.rt.texture)
        im = Image.frombytes("RGBA", (img.width, img.height), bytes(rl.ffi.buffer(img.data, img.width * img.height * 4))).transpose(Image.FLIP_TOP_BOTTOM)
        sheet.paste(im.convert("RGB").resize((S, S)), ((k % cols) * S, ((k // cols) * 2 + r) * S))
sheet.save(sys.argv[1])
