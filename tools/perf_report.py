"""Generate the runtime audit PDF from matched tools/perf.py captures."""
import argparse
import json
from pathlib import Path
from statistics import mean

from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
INK = "#152539"
MUTED = "#456077"
GRID = "#D9E3EB"
PALETTE = ("#2358AB", "#167A7A", "#BE6130", "#7D50A4", "#508A39",
           "#A33163", "#677D98", "#B38929", "#CE4670", "#4B96C3",
           "#745640", "#5C6B44", "#AF7194", "#537BBD")
SCENARIOS = {
    "chase_car": "Day chase",
    "top_car": "Day overhead",
    "chase_foot": "Night walk",
}


def average(samples, getter):
    return mean(getter(sample) for sample in samples)


def matches(key, prefix):
    return key == prefix or key.startswith(prefix + "/")


def aggregate(sample, groups, root=None):
    sections = [0.0] * (len(groups) + 1)
    frame = sample["exclusive_ms"]
    for key, ms in frame.items():
        if root and not matches(key, root):
            continue
        index = next((i for i, (_, prefixes) in enumerate(groups)
                      if any(matches(key, prefix) for prefix in prefixes)), len(groups))
        sections[index] += ms
    if root is None:
        remaining = sample["frame"] - sum(frame.values())
        if remaining < -0.01:
            raise ValueError("Exclusive timings exceed the frame")
        sections[-1] += max(0, remaining)
    return sections


def capture(phase, scenario):
    path = ROOT / "logs" / f"perf_runtime_{phase}_{scenario}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data["complete"] or data["errors"] or len(data["samples"]) != data["frames"]:
        raise ValueError(f"Incomplete or failed capture: {path}")
    return data


class Report:
    def __init__(self, file):
        self.canvas = Canvas(str(file), pagesize=(780, 610))
        self.canvas.setTitle("Skopje 242 | Frame-time audit")
        self.page_no = 0
        self.page_count = 18

    def text(self, x, y, value, size=10, color=INK, font="Helvetica"):
        self.canvas.setFont(font, size)
        self.canvas.setFillColor(HexColor(color))
        self.canvas.drawString(x, y, str(value))

    def rect(self, x, y, width, height, color):
        self.canvas.setFillColor(HexColor(color))
        self.canvas.rect(x, y, width, height, fill=1, stroke=0)

    def paragraph(self, x, y, value, width=680, size=11, color=MUTED):
        line = ""
        for word in value.split():
            candidate = f"{line} {word}".lstrip()
            if stringWidth(candidate, "Helvetica", size) > width:
                self.text(x, y, line, size, color)
                y -= size + 4
                line = word
            else:
                line = candidate
        if line:
            self.text(x, y, line, size, color)
        return y - size - 9

    def page(self, label, title, subtitle):
        if self.page_no:
            self.canvas.showPage()
        self.page_no += 1
        self.rect(0, 0, 780, 610, "#F8FAFC")
        self.rect(0, 603, 780, 7, "#167A7A")
        self.text(48, 568, f"SKOPJE 242  /  RUNTIME AUDIT  /  {label.upper()}", 10, "#167A7A", "Helvetica-Bold")
        self.text(48, 526, title, 28, INK, "Helvetica-Bold")
        self.paragraph(49, 497, subtitle, size=11)
        self.rect(48, 49, 684, 1, GRID)
        self.text(48, 32, "LOCAL WINDOWS CAPTURE  /  19 NOV 2026", 8, MUTED)
        self.text(696, 32, f"{self.page_no:02d} / {self.page_count}", 8, MUTED)

    def notes(self, notes, y=165):
        for title, detail in notes:
            self.text(49, y, title, 10, INK, "Helvetica-Bold")
            y = self.paragraph(49, y - 15, detail, size=10)
        if y < 55:
            raise ValueError(f"Notes extend past footer on page {self.page_no}")

    def stack(self, rows, labels, unit="ms per frame", budget=False, y=437):
        chart_x, chart_width, dy = 179, 480, min(27, 144 // len(rows))
        highest = max(sum(values) for _, values in rows)
        scale = max(highest * 1.05, 18 if budget else 0.001)
        digits = 2 if scale < 1 else 1
        for tick in range(6):
            x = chart_x + chart_width * tick / 5
            self.rect(x, y - (len(rows) - 1) * dy - 15, 0.6, (len(rows) - 1) * dy + 34, GRID)
            self.text(x - 7, y - len(rows) * dy - 8, f"{scale * tick / 5:.{digits}f}", 8, MUTED)
        self.text(chart_x, y + 25, unit, 8, MUTED, "Helvetica-Bold")
        for i, (label, values) in enumerate(rows):
            row_y = y - i * dy
            self.text(49, row_y + 2, label, 9, INK)
            x = chart_x
            for color, value in zip(PALETTE, values):
                w = chart_width * value / scale
                if w > 0:
                    self.rect(x, row_y, w, 12, color)
                x += w
            self.text(min(x + 6, 691), row_y + 2, f"{sum(values):.2f}", 8, INK, "Helvetica-Bold")
        if budget:
            x = chart_x + chart_width * 16.667 / scale
            self.rect(x, y - (len(rows) - 1) * dy - 4, 1, (len(rows) - 1) * dy + 20, INK)
            self.text(x - 20, y + 24, "60 Hz budget", 8, INK)
        legend_y = y - len(rows) * dy - 33
        for i, label in enumerate(labels):
            x = 49 + (i % 4) * 173
            at = legend_y - 15 * (i // 4)
            self.rect(x, at - 1, 8, 8, PALETTE[i])
            self.text(x + 13, at, label, 8, MUTED)

    def finish(self):
        if self.page_no != self.page_count:
            raise ValueError("Unexpected page count")
        self.canvas.save()


def paired(captures):
    for scenario, name in SCENARIOS.items():
        for phase in ("before", "after"):
            yield f"{name} / {phase}", captures[phase, scenario]["samples"]


def rows_for(captures, groups, root=None):
    return [(name, [mean(col) for col in zip(*(aggregate(s, groups, root) for s in samples))])
            for name, samples in paired(captures)]


def describe(data):
    frame = data["frame_ms"]
    return f"{frame['mean']:.2f} ms mean, {frame['median']:.2f} median, {frame['p95']:.2f} p95"


def ratio(before, after):
    return (after / before - 1) * 100


def report(output):
    captures = {(p, s): capture(p, s) for p in ("before", "after") for s in SCENARIOS}
    gpu = {p: capture(p, "gpu") for p in ("before", "after")}
    discovery = capture_discovery()
    repeat = {p: capture(p, "night_repeat") for p in ("before", "after")}
    settings = captures["before", "chase_car"]["settings"]
    for scenario in SCENARIOS:
        a, b = (captures[p, scenario] for p in ("before", "after"))
        if any(a[k] != b[k] for k in ("settings", "arguments", "warm", "frames")):
            raise ValueError(f"Capture settings differ for {scenario}")

    if any(repeat["before"][k] != repeat["after"][k] for k in ("settings", "arguments", "warm", "frames")):
        raise ValueError("Night repeat capture settings differ")

    frame_groups = [
        ("Simulation", ("sim",)),
        ("3D scene", ("render", "selfie.sky", "selfie.haze")),
        ("Lighting / atmosphere", ("sun", "nightprep", "night", "smog", "dust", "gloss")),
        ("HUD / composition", ("hud", "popups", "gains", "waypoint", "players", "escapes",
                                 "gate pins", "mall_doors", "mall_labels", "labels", "selfie.overlay",
                                 "poi.draw", "present.activate", "present.begin", "present.ui_layer", "present.end")),
        ("Audio / nearby radio", ("audio", "radio", "cabin")),
        ("Streaming", ("stream",)),
        ("Frame end / swap", ("swap",)),
    ]
    sim_groups = [(label, tuple("sim/" + x for x in keys)) for label, keys in [
        ("Pedestrians", ("actors.Peds.update",)),
        ("Traffic IPC / local traffic", ("trafficproc.step", "actors.Traffic.update")),
        ("Transit / rail", ("transit.Transit.update", "trains.Trains.update")),
        ("Services / dispatch", ("services.Services.update", "actors._dispatch")),
        ("Traffic crashes / parking", ("actors._traffic_crashes", "actors._parked")),
        ("Walking / combat", ("actors.Walker.update", "actors._swing_tick", "projectiles.Projectiles.update")),
        ("Kids / dogs / birds", ("kids.Kids.update", "dogs.Dogs.update", "birds.Birds.update")),
        ("Other game systems", ("works.Works.update", "clock.GameClock.update", "stations.Stations.update",
                                "signals.Signals.update", "compounds.Compounds.update", "rentals.Rentals.update",
                                "chaos.Chaos.update")),
    ]]
    actor = "render/render._actors"
    render_groups = [
        ("Actor setup and drawing", (actor,)),
        ("Road and street decals", ("render/render._decals",)),
        ("Particles", ("render/fx.draw",)),
        ("Signals / trains", ("render/signals.draw", "render/trains.draw")),
        ("Collect models", ("render/render._collect_models",)),
        ("Overview / mesh culling", ("render/render._overview", "render/render._visible_meshes")),
        ("Shots / balls", ("render/render._shots", "render/render._balls")),
    ]
    r = Report(output)
    r.page("Results", "Where each frame went",
           "Paired real-map runs with exclusive CPU wall time. Each bar averages 179 measured frames.")
    frame_rows = rows_for(captures, frame_groups)
    r.stack(frame_rows, [g[0] for g in frame_groups] + ["Other / loop remainder"], budget=True)
    r.notes([(name, f"Before {describe(captures['before', key])}. After {describe(captures['after', key])}.")
             for key, name in SCENARIOS.items()] + [
                 ("Reading the night result", "See the repeat in reverse order on page 13. Daytime means were nearly flat."),
             ], y=205)

    r.page("Protocol", "How the captures were made",
           "Windowed 1280 x 720, baked Skopje map, audio enabled, uncapped render rate, scripted 60 Hz simulation step.")
    r.notes([
        ("Match the workload", "Each capture starts a fresh process, runs 239 scripted frames, and discards the first 60 after game readiness. Day runs start at hour 13 in a car. The night run starts at hour 23 on foot. Captures run sequentially on a Windows i9-13900H host."),
        ("Reproduce the daytime chase path", "Use the game Python to run tools/perf.py --windowed --world data/cache/world --size 1280x720 --view chase --mode car --hour 13 --warm 60 --frames 239 --trace --audio --tag NAME. Use --gpu in a separate diagnostic. Run --prof separately for call attribution."),
        ("Common settings", f"Recorded detail {settings['detail']}, scale {settings['scale']}, AA {settings['aa']}, traffic {settings['traffic']}, pedestrians {settings['peds']}, smog {settings['smog']}, depth of field {settings['dof']} with strength {settings['dof_k']:.2f}."),
        ("Exclusive CPU attribution", "Spans use perf_counter_ns. The trace subtracts child durations from their parent and restores untimed bookkeeping to the frame remainder. Times include blocking or descheduling within an instrumented call. GPU query durations and traffic worker compute overlap the frame and have separate charts."),
        ("Scope and repeatability", "The test route exercises gameplay, collision checks, crowds, streaming, sound, and lighting. Menus, a multiplayer session, heavy combat, interactive quality scaling and post-swap streaming were outside these scripted runs. The primary set is one short paired run per scenario. Night has an additional paired check in reverse order. Driver behavior, caches, process scheduling and audio can affect measurements."),
    ], y=448)

    r.page("Simulation", "Pedestrians, vehicles and city systems",
           "Simulation spans include traffic handoff, collisions, pedestrians and the city services that run within Sim.update.")
    r.stack(rows_for(captures, sim_groups, "sim"), [g[0] for g in sim_groups] + ["Other simulation / inline work"])
    r.notes([
        ("Simulation self time", "The remainder of Sim.update includes inline player controls, vehicle integration, interactions and collision handling. Individual callees from the discovery pass include terrain queries and spatial lookups."),
        ("Same candidate order", "The applied cell lookup change keeps object insertion order and the original x-then-y cell traversal. It skips absent columns and reuses the y-range per query."),
    ], y=188)

    r.page("Scene", "3D scene submission",
           "CPU wall time spent preparing and issuing scene draws, including raylib and synchronous driver work.")
    r.stack(rows_for(captures, render_groups, "render"), [g[0] for g in render_groups] + ["Ground / meshes / setup"])
    r.notes([
        ("Model and mesh calls", "The benchmark counts selected raylib model, mesh and instanced submissions. Immediate-mode vertices and batched UI issue work through other APIs and are outside that counter."),
        ("Read the scene remainder", "The remaining Renderer.draw time includes inline ground and building mesh submission and mode transitions. The separately timed scene GPU window also contains the sky and frame-target setup."),
    ], y=188)

    shadow_groups = [
        ("Distant shadow batch", (actor + "/render._shadow_batch",)),
        ("Projected mesh shadow", (actor + "/render._proj_shadow",)),
    ]
    r.page("Actors", "Shadow work inside the actor pass",
           "Anchoring the triangle fan at a corner fills the same convex footprint and saves two triangles per shadow.")
    r.stack(rows_for(captures, shadow_groups, actor), [g[0] for g in shadow_groups] + ["Actor pass remainder"])
    r.notes([
        ("Applied draw-path change", "The old center fan emitted n triangles for an n-vertex hull. The new fan emits n - 2, saving six immediate-mode vertices per nondegenerate shadow. The hull, y offset, color, reversed winding, and depth-write state are preserved."),
        ("Draw calls and vertex count", "The change reduces vertices inside the existing batch. The model/mesh call counter is therefore a separate workload indicator."),
    ], y=192)

    light = [("Shadow map", ("sun",)), ("Night preparation", ("nightprep",)),
             ("Night draw", ("night",)), ("Smog / dust", ("smog", "dust")),
             ("Sky / haze", ("selfie.sky", "selfie.haze")), ("Gloss uniforms", ("gloss",))]
    hud = frame_groups[3][1]
    overlays = light + [("HUD", ("hud",)), ("Other markers / overlays", tuple(k for k in hud if not k.startswith("present.") and k != "hud")),
                        ("Frame target / UI layer", tuple(k for k in hud if k.startswith("present.") and k != "present.end")),
                        ("Final composition", ("present.end",))]
    r.page("Lighting and display", "Atmosphere, HUD and post-processing",
           "Selected passes from the scene, lighting and HUD budgets. The night walk emphasizes dynamic light submission.")
    r.stack(subset_rows(captures, overlays), [g[0] for g in overlays])
    r.notes([
        ("Post-processing has two clocks", "Present.end measures CPU submission. The GPU composite interval covers the final target and shader work and can be much larger."),
        ("Conditions gate the work", "Chase and overhead have different sky, smog and depth-of-field paths. A zero-height segment means the path was inactive or below the chart's visible resolution."),
    ], y=178)

    streaming = [("Mesh upload", ("stream/bake._load_meshes",)),
                 ("Ground bake", ("stream/bake._bake",)),
                 ("Eviction and decals", ("stream/bake._evict", "stream/bake._flush_decals"))]
    r.page("Streaming", "Streaming and upload budget",
           "Per-frame CPU time in Streamer.update. Much of the initial world preparation happens before the measured window.")
    r.stack(rows_for(captures, streaming, "stream"), [g[0] for g in streaming] + ["Streaming remainder"])
    startup = "; ".join(f"{name} {captures['before', key]['startup_s']:.1f} / {captures['after', key]['startup_s']:.1f} s"
                        for key, name in SCENARIOS.items())
    r.notes([
        ("Ready time, before / after", startup + "."),
        ("Operations outside the sample", "Game readiness excludes the full loading sequence from frame averages. Interactive streaming can also use slack after presentation. The test route takes an in-frame streaming path."),
        ("Improvement candidate", "Keep streaming budgets tied to observed p95 and peak upload cost. Measure a fast traversal before changing chunk sizes or scheduling."),
    ], y=200)

    audio = [("Audio housekeeping", ("audio/audio.Audio.update",)),
             ("Other audio handling", ("audio",)), ("Car radio", ("radio",)), ("Nearby cabin audio", ("cabin",))]
    r.page("Audio and workers", "Audio on the main thread",
           "Main-thread audio hooks include gameplay sound management and the two in-game radio update paths.")
    r.stack(subset_rows(captures, audio), [g[0] for g in audio])
    worker_lines = []
    for scenario, label in SCENARIOS.items():
        values = []
        for phase in ("before", "after"):
            frames = captures[phase, scenario]["samples"]
            compute, wait = (average(frames, lambda s: s["worker_ms"].get(name, 0.0))
                             for name in ("compute_ms", "wait_ms"))
            values.append(f"{compute:.2f} compute / {wait:.2f} wait")
        worker_lines.append(f"{label} {values[0]} to {values[1]} ms")
    r.notes([
        ("Traffic worker telemetry, before to after", ". ".join(worker_lines) + "."),
        ("Overlap", "Compute is the latest reported worker-step duration, sampled each frame. The worker can retain the same value until a fresh reply arrives. Main-thread receive time is included in simulation's traffic span. Audio device and background thread costs can overlap the main thread too."),
    ], y=194)

    loop = [
        ("POI and interior update", ("poi", "mall", "enter")),
        ("Places", ("places",)),
        ("Event dispatch", ("events",)),
        ("Particle update", ("effects/fx.Particles.update",)),
        ("Effects remainder", ("effects",)),
        ("Exhaust", ("exhaust",)),
        ("Multiplayer", ("mp",)),
    ]
    r.page("Frame orchestration", "Gameplay glue around the simulation",
           "Main-loop hooks for interactions, particles, location events and multiplayer dispatch.")
    r.stack(subset_rows(captures, loop), [g[0] for g in loop])
    remainders = []
    for key, label in SCENARIOS.items():
        means = []
        for phase in ("before", "after"):
            samples = captures[phase, key]["samples"]
            means.append(average(samples, lambda row: row["frame"] - sum(row["exclusive_ms"].values())))
        remainders.append(f"{label} {means[0]:.2f} / {means[1]:.2f} ms")
    r.notes([
        ("Untimed frame remainder, before / after", "; ".join(remainders) + "."),
        ("What sits between hooks", "The remainder includes input, camera calculations, prompt selection, bookkeeping, profiling overhead and driver calls outside the named spans. Multiplayer has a timing hook and was inactive for this workload."),
        ("Garbage collection", "The raw captures also carry per-generation garbage collection times. These are inclusive and already charge time to the frame or the interrupted span."),
    ], y=204)

    r.page("OpenGL", "GPU timestamp intervals",
           "Diagnostic daytime chase runs. The GPU timestamps bracket issued OpenGL work and may include queue starvation.")
    gpu_labels = ("scene", "overlays", "composite")
    timed = []
    intervals = []
    for phase, data in gpu.items():
        samples = [f["gpu_ms"] for f in data["samples"] if "gpu_ms" in f]
        if samples and any(set(s) != set(gpu_labels) for s in samples):
            raise ValueError(f"Unexpected GPU timestamp boundaries in {phase}")
        if samples:
            intervals.append((phase, [mean(s[k] for s in samples) for k in gpu_labels]))
        timed.append(f"{phase} {len(samples)}/{data['frames']}")
    if intervals:
        r.stack(intervals, ["Scene and sky", "Lighting and overlays", "Final composition"], unit="GPU timestamp interval (ms)")
    r.notes([
        ("Query coverage", ", ".join(timed) + ". " + " ".join(d["gpu_error"] for d in gpu.values() if d["gpu_error"])),
        ("Boundaries and measurement effects", "Queries begin at BeginDrawing, cut after the main scene and immediately before Present.end, and finish before buffer swap. Pre-draw uploads, shadow-map work, and light preparation are visible in the CPU trace. Each query boundary flushes the raylib batch. These diagnostic runs are excluded from the paired CPU chart."),
        ("Readback", "Older frames are polled for availability. The final pending queries are drained during teardown while the GL context is current."),
    ], y=266)

    r.page("Frame tails", "Where the slow frames clustered",
           "Mean composition of the slowest 5% of frames in each capture. The frame budget line marks 16.67 ms.")
    tails = []
    for name, samples in paired(captures):
        slow = sorted(samples, key=lambda s: s["frame"], reverse=True)[:max(1, (len(samples) + 19) // 20)]
        tails.append((name, [mean(col) for col in zip(*(aggregate(s, frame_groups) for s in slow))]))
    r.stack(tails, [g[0] for g in frame_groups] + ["Other / loop remainder"], budget=True)
    tail_notes = []
    for key, label in SCENARIOS.items():
        notes = []
        for phase in ("before", "after"):
            sample = max(captures[phase, key]["samples"], key=lambda s: s["frame"])
            hottest = max(sample["exclusive_ms"], key=sample["exclusive_ms"].get)
            notes.append(f"{phase} {sample['frame']:.2f} ms ({hottest})")
        tail_notes.append((label, "; ".join(notes) + "."))
    r.notes(tail_notes, y=205)

    r.page("Applied improvements", "Changes and measured effect",
           "Two targeted changes from the discovery profile. Values below are paired observed changes in mean CPU wall time.")
    r.stack(subset_rows(captures, [sim_groups[0], shadow_groups[0], shadow_groups[1]]),
            ["Pedestrian update self and descendants", "Distant shadow batch", "Projected mesh shadow"])
    details = []
    for key, label in SCENARIOS.items():
        a, b = (captures[p, key] for p in ("before", "after"))
        ped = "actors.Peds.update"
        shadow = "render._shadow_batch"
        fmt = f"Frame {ratio(a['frame_ms']['mean'], b['frame_ms']['mean']):+.1f}%"
        for name, hook in (("pedestrians", ped), ("distant shadows", shadow)):
            old, new = (c["per_frame"].get(hook, 0) for c in (a, b))
            fmt += f"; {name} {old:.2f} to {new:.2f} ms"
        details.append((label, fmt + "."))
    r.notes(details + [
        ("Attribution limits", "Both changes were present in each after capture. Each named span contains other work and the differences include run-to-run variability. All 2,400 grid queries matched a reference scan. All 400 shadow cases preserved area and winding."),
    ], y=205)

    r.page("Repeatability", "Night walk in reverse order",
           "The night comparison was repeated with identical game settings, running the optimized build first and then the original two functions.")
    night_rows = []
    for pair, source in (("Initial", {p: captures[p, "chase_foot"] for p in ("before", "after")}), ("Repeat", repeat)):
        for phase in ("before", "after"):
            samples = source[phase]["samples"]
            night_rows.append((f"{pair} / {phase}", [mean(col) for col in zip(*(aggregate(s, frame_groups) for s in samples))]))
    r.stack(night_rows, [g[0] for g in frame_groups] + ["Other / loop remainder"], budget=True)
    r.notes([
        ("Reverse-order check",
         f"Original lookup and shadow code {describe(repeat['before'])}. Optimized code {describe(repeat['after'])}."),
        ("Interpretation", "The initial night slowdown also affected lighting, audio and presentation, which the changes did not touch. The repeated pair ran slower overall and reversed the direction of the mean change. The night timing does not establish a consistent effect."),
        ("GPU measurements", "The diagnostic chase runs also show substantial between-run variation. The intervals locate work on the GPU timeline. A GPU speedup remains unverified."),
    ], y=231)

    r.page("Initial recommendations", "What the first profile proposed",
           "These proposals came from the initial profile. Pages 15 through 18 show the follow-up measurements.")
    focus = sorted(discovery["top_tottime"], key=lambda row: -row[2])
    r.notes([
        ("1. Investigate service-update stalls", "Capture a longer run around the slow service frames and attribute routing and route setup individually. If route searches explain the spikes, evaluate moving searches behind a bounded queue while preserving route selection and arrival behavior."),
        ("2. Split actor submission further", "Separate character poses, decals, instanced vehicles, projected shadows and immediate-mode effects in a focused trace. Evaluate batching projected shadows where state, material and depth-order constraints permit."),
        ("3. Profile GPU lighting and shader cost", "Place individual timestamp pairs around the shadow-map and light draws in another diagnostic run. Repeat at multiple resolutions and depth-of-field settings to distinguish pixel work from submission latency."),
        ("4. Avoid repeated terrain work if a call-site audit confirms duplication", f"The cProfile discovery run found {next(row[2] for row in focus if ' ground_y' in row[0]):.3f} ms/frame in ground_y's own time. Start by reusing exact same-point samples within a tick, with parity checks for quay, road, and kerb heights."),
        ("Evidence and reproduction", "tools/perf.py collects the traces with tools/perf_gl.py. logs/perf_runtime_before_*, logs/perf_runtime_after_* and logs/perf_runtime_discovery.json carry the underlying measurements. This PDF is reproducible with tools/perf_report.py."),
    ], y=448)
    follow_up(r, frame_groups)
    r.finish()



def optimization_capture(tag):
    path = ROOT / "logs" / f"perf_halving_{tag}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data["complete"] or data["errors"] or len(data["samples"]) != data["frames"]:
        raise ValueError(f"Failed optimization capture: {path}")
    return data


def follow_up(r, frame_groups):
    scenarios = (
        ("Day chase", "chase_car_1280x720"),
        ("Day overhead", "top_car_1280x720"),
        ("Night walk", "chase_foot_1280x720"),
        ("Night walk 540p", "chase_foot_960x540"),
    )
    pairs = {label: [optimization_capture(f"{p}_{tag}") for p in ("before", "after")]
             for label, tag in scenarios}
    for label, (before, after) in pairs.items():
        if any(before[k] != after[k] for k in ("arguments", "settings", "warm", "frames")):
            raise ValueError(f"Mismatched pair for {label}")

    r.page("Follow-up results", "The 50% frame-time target",
           "Fresh before and after captures measure the second round of changes. Each bar shows the composition of the median-ranked frame.")
    rows = []
    for label, _ in scenarios[:3]:
        for phase, data in zip(("before", "after"), pairs[label]):
            ordered = sorted(data["samples"], key=lambda s: s["frame"])
            rows.append((f"{label} / {phase}", aggregate(ordered[len(ordered) // 2], frame_groups)))
    r.stack(rows, [group[0] for group in frame_groups] + ["Other / loop remainder"], budget=True)
    notes = []
    for label, _ in scenarios:
        before, after = pairs[label]
        a, b = before["frame_ms"], after["frame_ms"]
        notes.append((label, f"Median {a['median']:.2f} to {b['median']:.2f} ms ({ratio(a['median'], b['median']):+.1f}%). "
                             f"Mean {a['mean']:.2f} to {b['mean']:.2f} ms. p95 {a['p95']:.2f} to {b['p95']:.2f} ms."))
    r.notes(notes, y=205)

    r.page("Follow-up CPU", "Dispatch, streaming and terrain",
           "Service startup work moved outside the frame. Upload preparation and repeated exact-point terrain sampling were reduced.")
    groups = [
        ("Emergency services", ("sim/services.Services.update",)),
        ("Chunk streaming", ("stream",)),
    ]
    rows = [(f"{label} / {phase}", [average(d["samples"], lambda row: value_for(row, keys))
                                    for _, keys in groups])
            for label, _ in scenarios[:3] for phase, d in zip(("before", "after"), pairs[label])]
    r.stack(rows, [group[0] for group in groups])
    peaks = []
    for label, _ in scenarios[:2]:
        values = []
        for data in pairs[label]:
            values.append(max(value_for(row, groups[0][1]) for row in data["samples"]))
        peaks.append(f"{label} {values[0]:.2f} to {values[1]:.2f} ms")
    r.notes([
        ("Worst service-update spans", ". ".join(peaks) + "."),
        ("Routing", "Build the graph and invariant edge costs during loading. Query traffic queues live and preserve direction, candidate order and route budgets. The refined trace split graph construction, nearest-node queries and searches. The scripted workload does not justify a new asynchronous routing queue."),
        ("Terrain and uploads", "Use exact previously sampled height at unchanged coordinates, reuse stationary lamp heights and retain bridge / platform selection. Streamer avoids broken-prop filtering on skipped materials and checks time after processing filtered entries."),
    ], y=205)

    r.page("Follow-up rendering", "Terrain lighting and actor submission",
           "The night overlay uses the same terrain grid with indexed triangles and bulk GPU buffer updates.")
    draw_groups = [
        ("Night terrain overlay", ("night/night.draw/lightmap.overlay",)),
        ("Glowing windows", ("night/night.draw/lightmap.windows",)),
        ("Projected shadows", ("render/render._actors/render._proj_shadow",
                               "render/render._actors/render._draw_vehicle_models/render._proj_shadow",
                               "render/render._actors/render._draw_ped_models/render._proj_shadow")),
    ]
    rows = [(f"{label} / {phase}", [average(d["samples"], lambda row: value_for(row, keys))
                                    for _, keys in draw_groups])
            for label, _ in (scenarios[0], scenarios[2], scenarios[3])
            for phase, d in zip(("before", "after"), pairs[label])]
    r.stack(rows, [group[0] for group in draw_groups])
    overlay = [d["per_frame"].get("lightmap.overlay", 0.0) for d in pairs["Night walk"]]
    r.notes([
        ("Night terrain overlay at 720p", f"{overlay[0]:.2f} to {overlay[1]:.2f} ms mean CPU wall time per frame."),
        ("Scene timing and projected shadows", "Vehicle draws, wheels, pedestrian poses, decals and both shadow paths now have distinct timing. Projected shadows interleave with opaque models and use strict depth. A global batch would change draw order for overlapping shadows, so this pass retains its depth and ordering rules."),
        ("Window lighting", "The shader rejects fragments outside the light radius before sampling facade textures. It passes the original UV derivatives explicitly to preserve mip selection."),
    ], y=205)

    r.page("Follow-up GPU", "Pre-draw through post-processing",
           "Separate OpenGL timestamp diagnostics compare resolution and depth of field and time previously unmeasured pre-draw passes.")
    gpu_groups = (("Upload", "stream"), ("Sun depth", "sun"), ("Light-map prepare", "nightprep"),
                  ("Scene and sky", "scene"), ("Lighting and HUD", "overlays"), ("Composite", "composite"))
    configs = (
        ("720p / before", "before_night_gpu"),
        ("720p / after", "after_gpu_1280x720_dof"),
        ("540p / after", "after_gpu_960x540_dof"),
        ("720p no DOF / after", "after_gpu_1280x720_plain"),
    )
    rows = []
    for label, tag in configs:
        data = optimization_capture(tag)
        samples = [f["gpu_ms"] for f in data["samples"] if "gpu_ms" in f]
        if not samples or data["gpu_error"]:
            raise ValueError(f"Missing GPU timeline for {tag}")
        rows.append((label, [mean(sample.get(key, 0.0) for sample in samples) for _, key in gpu_groups]))
    r.stack(rows, [label for label, _ in gpu_groups], unit="GPU timestamp interval (ms)")
    r.notes([
        ("Interpreting the bars", "The plotted intervals surround submission for each named pass. They can include periods when the GPU waits on CPU submission. Query cuts flush raylib batches. Unlabelled time between passes is excluded from these bars."),
        ("Presentation stalls", "The inclusive CPU samples retain swap stalls, including outliers of hundreds of milliseconds. These can dominate a mean without indicating a comparable slowdown in the named game systems. Read median and p95 alongside mean."),
        ("Reproduce", "Use tools/perf.py with --trace for the CPU set or --gpu for graphics diagnostics. The latter adds pre-draw timestamps and supports --no-dof for the graphics control."),
    ], y=220)


def subset_rows(captures, groups):
    return [(name, [average(samples, lambda s: value_for(s, prefixes)) for _, prefixes in groups])
            for name, samples in paired(captures)]


def value_for(sample, prefixes):
    return sum(value for key, value in sample["exclusive_ms"].items() if any(matches(key, p) for p in prefixes)
               and not (prefixes == ("audio",) and matches(key, "audio/audio.Audio.update"))
               and not (prefixes == ("effects",) and matches(key, "effects/fx.Particles.update")))


def capture_discovery():
    path = ROOT / "logs/perf_runtime_discovery.json"
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf/skopje-242-frame-time-profiling.pdf")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report(args.output)
