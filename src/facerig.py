"""A deformable head of the real character mesh (characterart.sculpt) rendered by raylib into a tiny render texture.
The head is built once per hero (head + hair + neck/shoulders, plus a mouth cavity and a tongue) and then deformed on the CPU with numpy
(jaw, smile, eyelids/eye size, pupils, brows, tilt/squash of the whole head); ~2-6k vertices, uploaded into one dynamic mesh."""
import math
import os

import numpy as np
import pyray as rl
from raylib import ffi

import characterart as ca

NECK = (0.0, .599, .035)                 # head bone origin in torso space
HAIR_OFF = (0.0, .224, -.04)
PIVOT = np.array((0.0, .03, 0.0), np.float32)            # the head turns on the neck here
JAW_PIVOT_Y, JAW_PIVOT_Z = .115, -.03
FOV = 26.0
_KEY = ca._KEY_LIGHT
_FILL = ca._FILL_LIGHT
_CAVITY, _TONGUE = (92, 16, 28), (205, 84, 96)
EYE_COLS = ((0xef, 0xe4, 0xce), (0x55, 0x3c, 0x32), (0x47, 0x69, 0x76), (0xff, 0xf3, 0xdd))


def _ellipsoid(center, radii, color, rings=6, segs=10):
    pts = []
    for i in range(rings):
        a0, a1 = math.pi * i / rings - math.pi / 2, math.pi * (i + 1) / rings - math.pi / 2
        for j in range(segs):
            b0, b1 = math.tau * j / segs, math.tau * (j + 1) / segs
            q = lambda a, b: (math.cos(a) * math.sin(b), math.sin(a), math.cos(a) * math.cos(b))
            p00, p01, p10, p11 = q(a0, b0), q(a0, b1), q(a1, b0), q(a1, b1)
            pts += [p00, p10, p11, p00, p11, p01]
    n = np.array(pts, np.float32)
    return n * np.array(radii, np.float32) + np.array(center, np.float32), n, np.tile(np.array(color, np.float32), (len(n), 1))


def tg_(g):
    return g("tongue", 0.0)


def _rows(mask_fn, *arrs):
    return [a[mask_fn] for a in arrs]


def _match(col, c):
    return (np.abs(col - np.array(c, np.float32)).sum(axis=1) < 3)


def rotx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array(((1, 0, 0), (0, c, -s), (0, s, c)), np.float32)


def roty(a):
    c, s = math.cos(a), math.sin(a)
    return np.array(((c, 0, s), (0, 1, 0), (-s, 0, c)), np.float32)


def rotz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array(((c, -s, 0), (s, c, 0), (0, 0, 1)), np.float32)


class Head:
    """Rest geometry for one hero + the deformation / rendering."""

    mode = "gl"                                              # "gl": render target; "cpu": PIL raster (set by faces when the target is empty or never visible)
    ok = None                                                # None: not probed yet, True: the render target holds a head, False: it stayed empty
    _probes = 0

    def __init__(self, hero_i, size):
        index = ca.DESIGNS[100 + hero_i]
        parts = ca.sculpt(index, 2)
        self.skin = np.array(ca.rgb(ca._PALETTES[index][-1]), np.float32)
        hp, hn, _, hc = parts["head"]
        P, N, C = [hp.astype(np.float32)], [hn.astype(np.float32)], [hc.astype(np.float32)]
        self.n_head = len(hp)
        for nm in ("hair-1", "hair1"):
            if nm in parts:
                p, n, _, c = parts[nm]
                P.append(p.astype(np.float32) + np.array(HAIR_OFF, np.float32)); N.append(n.astype(np.float32)); C.append(c.astype(np.float32))
        self.n_hh = sum(len(p) for p in P)                    # head + hair rows (they turn with the head)
        tp, tn, _, tc = parts["torso"]
        tri = tp.reshape(-1, 3, 3)
        keep = (tri[:, :, 1].mean(axis=1) > .45)
        keep = np.repeat(keep, 3)
        P.append(tp[keep].astype(np.float32) - np.array(NECK, np.float32)); N.append(tn[keep].astype(np.float32)); C.append(tc[keep].astype(np.float32))
        cp, cn, cc = _ellipsoid((0, 0, 0), (1, 1, 1), _CAVITY)           # unit spheres, placed every pose
        tpn, tnn, tcc = _ellipsoid((0, 0, 0), (1, 1, 1), _TONGUE, 4, 8)
        mp_, mn_, mc_ = _ellipsoid((0, 0, 0), (1, 1, 1), (240, 236, 224), 3, 8)
        self.n_cav, self.n_tongue, self.n_teeth = len(cp), len(tpn), len(mp_)
        self.U = [cp.copy(), tpn.copy(), mp_.copy()]
        P += [cp, tpn, mp_]; N += [cn, tnn, mn_]; C += [cc, tcc, mc_]
        self.P = np.concatenate(P); self.N = np.concatenate(N); self.C = np.concatenate(C)
        n_hh = self.n_hh
        p, c = self.P[:n_hh], self.C[:n_hh]
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        eye = np.zeros(n_hh, bool)
        for col in EYE_COLS:
            eye |= _match(c, col)
        eye &= (z > .10) & (y > .09) & (y < .22)
        self.eye = np.nonzero(eye)[0]
        pup = (_match(c, EYE_COLS[1]) | _match(c, EYE_COLS[2]) | _match(c, EYE_COLS[3])) & eye
        self.pupil = np.nonzero(pup)[0]
        hair = np.array(ca.rgb(ca._PALETTES[index][4]), np.float32)
        brow = _match(c, hair) & (z > .112) & (y > .195) & (y < .248) & (np.abs(x) > .012)
        self.brow = np.nonzero(brow)[0]
        # jaw weight: the chin and lower lip follow the hinge, the upper lip / nose / moustache stay, and everything in between (cheeks, mouth corners,
        # moustache ends) is blended smoothly so nothing shears along a line
        ax = np.abs(x)
        top = .093 + np.clip((ax - .03) / .04, 0, 1) * .045
        t = np.clip((top - y) / .03, 0, 1)
        self.jawk = (t * t * (3 - 2 * t)) * np.clip((z + .06) / .06, 0, 1) * (1 - .9 * np.clip((ax - .035) / .045, 0, 1))
        self.jawk[:self.n_head][self.eye[self.eye < self.n_head]] = 0
        # a moustache is fastened to the upper lip: it stays with the face when the jaw drops (a beard lower down follows the jaw)
        skin_d = np.abs(c - self.skin).sum(axis=1)
        lipish = (c[:, 0] - c[:, 1] > 60) & (c[:, 0] > 140)
        stache = (skin_d > 70) & ~lipish & (z > .10) & (y > .06) & (y < .135) & (ax < .11)
        for col in EYE_COLS:
            stache &= ~_match(c, col)
        self.jawk[stache] = 0
        band = np.clip(1 - np.abs(y - .075) / .035, 0, 1) * np.clip((z - .07) / .05, 0, 1)
        self.band = band
        self.eye_y = float(y[self.eye].mean()) if len(self.eye) else .17
        side = np.sign(x[self.eye]) if len(self.eye) else np.zeros(0)
        self.eye_c = {s: np.array((float(x[self.eye][side == s].mean()) if (side == s).any() else s * .05, self.eye_y, .125), np.float32) for s in (-1, 1)}
        # glasses: opaque lenses (dark sunglasses, tinted or skin-coloured glass) would hide the eyes, so the eyes sit in front of the lens
        # surface and a dark lens is lightened: they are always clearly visible
        lens = (_match(c, (51, 41, 54)) | _match(c, (203, 161, 129))) & (z > .09) & (y > .09) & (y < .24) & (ax > .015) & (ax < .09)
        if lens.any() and len(self.eye):
            dz = max(0.0, float(z[lens].max()) - float(z[self.eye].max())) + .008
            p[self.eye, 2] += dz
            dark = lens & _match(c, (51, 41, 54))
            c[dark] = (118, 108, 134)                            # a smoky lens that the eyes read against, not a black plate
        self.top = float(p[:n_hh, 1].max())
        # camera: frame hat/hair top down to the neck
        lo, hi = -.03, self.top + .015
        self.cy = (lo + hi) / 2
        self.dist = ((hi - lo) / 2 * 1.04) / math.tan(math.radians(FOV / 2))
        self.cam = rl.Camera3D(rl.Vector3(0, self.cy, self.dist), rl.Vector3(0, self.cy, 0), rl.Vector3(0, 1, 0), FOV, rl.CAMERA_PERSPECTIVE)
        self.size = size
        self.rt = rl.load_render_texture(size, size)
        rl.set_texture_filter(self.rt.texture, rl.TEXTURE_FILTER_BILINEAR)
        self._pos = np.zeros((len(self.P), 3), np.float32)
        self._col = np.full((len(self.P), 4), 255, np.uint8)
        self._uv = np.zeros((len(self.P), 2), np.float32)
        self.model = None
        self.last = {}

    # -------------------------------------------------------------- deformation
    def pose(self, e):
        """e: dict of expression numbers -> fills self._pos/_col."""
        g = e.get
        P0, N0, C0 = self.P, self.N, self.C
        n_hh = self.n_hh
        p = P0[:n_hh].copy()
        n = N0[:n_hh].copy()
        c = C0[:n_hh].copy()
        jaw, smile = g("jaw", 0.0), g("smile", 0.0)
        if jaw > .002:                                           # lower face swings down around the jaw hinge
            a = self.jawk * (jaw * .40)
            ca_, sa_ = np.cos(a), np.sin(a)
            dy, dz = p[:, 1] - JAW_PIVOT_Y, p[:, 2] - JAW_PIVOT_Z
            p[:, 1] = JAW_PIVOT_Y + dy * ca_ + dz * sa_
            p[:, 2] = JAW_PIVOT_Z - dy * sa_ + dz * ca_
        if abs(smile) > .002:
            p[:, 1] += smile * .022 * (np.minimum(np.abs(p[:, 0]), .07) / .06) ** 2 * self.band - smile * .006 * self.band
        e_i = self.eye
        if len(e_i):
            o = g("eye", 1.0)
            q = p[e_i]
            side = np.sign(q[:, 0])
            cen = np.where(side[:, None] < 0, self.eye_c[-1], self.eye_c[1])
            k = np.array((1.0, max(.05, o), 1.0), np.float32) * g("bulge", 1.0)
            if g("bulge", 1.0) != 1.0:
                k = k * np.array((1, 1, 1), np.float32)
            q = cen + (q - cen) * k
            p[e_i] = q
            if o < .4:                                           # a closed lid is skin coloured
                t = np.clip((.4 - o) / .25, 0, 1)
                c[e_i] = c[e_i] * (1 - t) + self.skin * .86 * t
        if len(self.pupil):
            sd = np.sign(p[self.pupil, 0])
            p[self.pupil, 0] += g("gx", 0.0) * .013 - sd * g("cross", 0.0) * .016
            p[self.pupil, 1] += g("gy", 0.0) * .008 + g("dizzy_y", 0.0) * .01
            p[self.pupil, 0] += g("dizzy_x", 0.0) * .012
            p[self.pupil, 2] -= g("sink", 0.0) * .02
        if len(self.brow):
            q = p[self.brow]
            sd = np.sign(q[:, 0])
            inner = (.05 - np.abs(q[:, 0]))
            q[:, 1] += g("brow", 0.0) * .026 + g("angry", 0.0) * (-inner * .55) + g("worry", 0.0) * inner * .55 + g("brow_l", 0.0) * (sd < 0) * .02 + g("brow_r", 0.0) * (sd > 0) * .02
            p[self.brow] = q
        # whole head: squash/stretch, tilt, turn, shake
        sx, sy = g("sx", 1.0), g("sy", 1.0)
        R = roty(g("yaw", 0.0)) @ rotx(g("pitch", 0.0)) @ rotz(g("roll", 0.0))
        q = (p - PIVOT) * np.array((sx, sy, sx), np.float32)
        q = q @ R.T + PIVOT + np.array((g("tx", 0.0), g("ty", 0.0), 0.0), np.float32)
        n = n @ R.T
        k = np.maximum(0., n @ _KEY)
        shade = .65 + .36 * k + .13 * np.maximum(0., n @ _FILL)
        col = np.clip(c * shade[:, None] + 8, 0, 255)
        out_p, out_c = [q], [col]
        # neck / shoulders (follow the body bob only)
        a, b = n_hh, n_hh + (len(self.P) - n_hh - self.n_cav - self.n_tongue - self.n_teeth)
        tp = P0[a:b] + np.array((0.0, g("body_y", 0.0), 0.0), np.float32)
        tcol = np.clip(C0[a:b] * (.65 + .36 * np.maximum(0., N0[a:b] @ _KEY) + .13 * np.maximum(0., N0[a:b] @ _FILL))[:, None] + 8, 0, 255)
        out_p.append(tp); out_c.append(tcol)
        # the open mouth: a dark oval (lips are part of the skin, so the opening is a decal poking out of them), teeth and tongue
        b = n_hh + (len(self.P) - n_hh - self.n_cav - self.n_tongue - self.n_teeth)
        T = np.array((g("tx", 0.0), g("ty", 0.0), 0.0), np.float32)
        S3 = np.array((sx, sy, sx), np.float32)
        wide = 1.0 + .35 * smile
        parts = ((self.U[0], (0, .088 - jaw * .026, .150), (.020 + .018 * jaw, .004 + .030 * jaw, .026 if jaw > .03 else .001), 0, self.n_cav),
                 (self.U[1], (0, .064 - jaw * .030 - tg_(g) * .012, .152 + tg_(g) * .05), (.014, .006 + .004 * tg_(g), .020 + .05 * tg_(g)), 0, self.n_tongue),
                 (self.U[2], (0, .088 + .003, .160), (.017 * wide, .004, .014 if jaw > .12 else .001), 0, self.n_teeth))
        off = b
        for unit, ctr, rad, _, cnt in parts:
            q = unit * np.array(rad, np.float32) + np.array(ctr, np.float32)
            q = ((q - PIVOT) * S3) @ R.T + PIVOT + T
            out_p.append(q); out_c.append(np.clip(C0[off:off + cnt] * .95, 0, 255)); off += cnt
        self._pos[:] = np.concatenate(out_p)
        self._col[:, :3] = np.concatenate(out_c).astype(np.uint8)

    # -------------------------------------------------------------- render
    def render(self, e, bg):
        self.pose(e)
        if self.model is None:
            m = rl.Mesh()
            n = len(self._pos)
            m.vertexCount, m.triangleCount = n, n // 3
            m.vertices = ffi.cast("float *", ffi.from_buffer(self._pos))
            m.texcoords = ffi.cast("float *", ffi.from_buffer(self._uv))
            m.colors = ffi.cast("unsigned char *", ffi.from_buffer(self._col))
            rl.upload_mesh(ffi.addressof(m), True)
            m.vertices = ffi.NULL; m.texcoords = ffi.NULL; m.colors = ffi.NULL
            self.model = rl.load_model_from_mesh(m)
        else:
            mesh = self.model.meshes[0]
            rl.update_mesh_buffer(mesh, 0, ffi.cast("void *", ffi.from_buffer(self._pos)), self._pos.nbytes, 0)
            rl.update_mesh_buffer(mesh, 3, ffi.cast("void *", ffi.from_buffer(self._col)), self._col.nbytes, 0)
        rl.rl_set_texture(0)                                   # the frame may open with other passes' GL state left over (the heads render before begin_drawing now)
        rl.end_shader_mode(); rl.end_blend_mode(); rl.end_scissor_mode()
        rl.rl_enable_depth_test(); rl.rl_enable_depth_mask(); rl.rl_enable_color_blend()
        rl.begin_texture_mode(self.rt)
        rl.clear_background(bg)
        rl.rl_set_clip_planes(0.02, 20.0)                      # the renderer sets its own (near ~1 m+) every frame: a head 1 m from its camera would be clipped away entirely
        rl.begin_mode_3d(self.cam)
        rl.rl_disable_backface_culling()
        rl.draw_model(self.model, rl.Vector3(0, 0, 0), 1.0, rl.WHITE)
        rl.rl_draw_render_batch_active()
        rl.rl_enable_backface_culling()
        rl.end_mode_3d()
        rl.rl_set_blend_factors_separate(0, 1, 1, 0, 0x8006, 0x8006)        # alpha := 1 everywhere, colour untouched: the HUD layer composites with the texture's alpha,
        rl.begin_blend_mode(rl.BLEND_CUSTOM_SEPARATE)                       # and a head that came out transparent on some GPUs looked like an empty box
        rl.draw_rectangle(0, 0, self.size, self.size, rl.Color(0, 0, 0, 255))
        rl.end_blend_mode()
        rl.end_texture_mode()
        if self.ok is not True and self._probes < 4:           # evidence in logs/game.log, and the picture fallback when the target stays empty
            self._probes += 1
            try:
                import os
                img = rl.load_image_from_texture(self.rt.texture)
                n = img.width
                st = max(1, n // 12)
                px = [rl.get_image_color(img, x, y) for x in range(4, n, st) for y in range(4, n, st)]
                cols = {(c.r // 8, c.g // 8, c.b // 8) for c in px}
                if min(c.a for c in px) < 250:                    # transparent pixels: the HUD would show nothing there
                    cols = set()
                rl.unload_image(img)
                good = len(cols) > 6
                if good:
                    self.ok = True
                elif self._probes >= 4:
                    self.ok = False
                if good or self.ok is False or self._probes == 1:
                    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs"); os.makedirs(d, exist_ok=True)
                    with open(os.path.join(d, "game%s.log" % os.environ.get("SK242_LOG_SUFFIX", "")), "a", encoding="utf-8") as fh:
                        fh.write("[faces] head target id %d tex %d %dpx render #%d: %d distinct colours -> %s\n" % (
                            self.rt.id, self.rt.texture.id, n, self._probes, len(cols), "ok" if good else ("EMPTY, using the picture fallback" if self.ok is False else "empty so far")))
            except Exception:                                 # noqa: BLE001
                self.ok = True

    # ---------------------------------------------------------- CPU fallback: the same posed mesh, painted by PIL (no GL target involved)
    def cpu_render(self, e, bg):
        """Painter's-algorithm raster of the actual hero head mesh into self.cpu (a plain texture); returns it.  ~15 ms, used only when the GL
        target never reaches the screen on this GPU."""
        from PIL import Image, ImageDraw
        self.pose(e)
        n = self.size
        P = self._pos.reshape(-1, 3, 3)
        C = self._col.reshape(-1, 3, 4)[:, :, :3].astype(np.float32).mean(axis=1)
        d = self.dist - P[:, :, 2]
        t = math.tan(math.radians(FOV / 2))
        ok = (d > .01).all(axis=1)
        d = np.maximum(d, .01)
        X = (.5 + .5 * P[:, :, 0] / (d * t)) * n
        Y = (.5 - .5 * (P[:, :, 1] - self.cy) / (d * t)) * n
        order = np.argsort(P[:, :, 2].mean(axis=1))                   # far (small z) to near
        img = Image.new("RGB", (n, n), (bg.r, bg.g, bg.b))
        dr = ImageDraw.Draw(img)
        for i in order:
            if ok[i]:
                c = C[i]
                dr.polygon([(float(X[i, 0]), float(Y[i, 0])), (float(X[i, 1]), float(Y[i, 1])), (float(X[i, 2]), float(Y[i, 2]))],
                           fill=(int(c[0]), int(c[1]), int(c[2])))
        buf = img.convert("RGBA").tobytes()
        if getattr(self, "cpu", None) is None:
            im = rl.gen_image_color(n, n, rl.BLACK)
            self.cpu = rl.load_texture_from_image(im)
            rl.unload_image(im)
            rl.set_texture_filter(self.cpu, rl.TEXTURE_FILTER_BILINEAR)
        rl.update_texture(self.cpu, ffi.cast("void *", ffi.from_buffer(buf)))
        return self.cpu

    def project(self, pt, e):
        """Window position (0..1, 0..1) of a head-space point under the current head turn (for 2D overlays on the eyes)."""
        R = roty(e.get("yaw", 0.0)) @ rotx(e.get("pitch", 0.0)) @ rotz(e.get("roll", 0.0))
        q = (np.asarray(pt, np.float32) - PIVOT) @ R.T + PIVOT + np.array((e.get("tx", 0.0), e.get("ty", 0.0), 0.0))
        d = self.dist - q[2]
        t = math.tan(math.radians(FOV / 2))
        return .5 + .5 * q[0] / (d * t), .5 - .5 * (q[1] - self.cy) / (d * t)

    def free(self):
        if self.model is not None:
            rl.unload_model(self.model)
        rl.unload_render_texture(self.rt)
