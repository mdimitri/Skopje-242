"""The batch report: one self-contained HTML file (inline SVG charts, heatmaps as embedded PNG) comparing the variants
on efficiency, safety and speed, with 95 % confidence intervals and significance against the baseline."""
import base64
import collections
import html
import io
import json
import math
import time

from . import batch, core

COLORS = ["#2f6fd6", "#e4572e", "#29a36a", "#a65fd8", "#e0a100", "#17a2b8", "#d63384", "#6c757d"]
LOS_COL = {"A": "#1a9850", "B": "#91cf60", "C": "#d9ef8b", "D": "#fee08b", "E": "#fc8d59", "F": "#d73027"}
CSS = """
:root{--bg:#f6f7f9;--fg:#1d2330;--mut:#667085;--card:#fff;--line:#e3e6ec;--good:#1a7f4b;--bad:#c0362c}
@media (prefers-color-scheme: dark){:root{--bg:#14171c;--fg:#e8eaee;--mut:#9aa3b2;--card:#1d2128;--line:#2c323c;--good:#4cc38a;--bad:#ff6b5e}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;margin:0;padding:24px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 10px;border-bottom:1px solid var(--line);padding-bottom:4px}
.mut{color:var(--mut)}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:4px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card)}
.good{color:var(--good);font-weight:600}.bad{color:var(--bad);font-weight:600}.score{font-size:30px;font-weight:700}
.wrap{overflow-x:auto}.chip{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:middle}
svg text{fill:var(--fg);font:11px system-ui,Arial}svg .ax{stroke:var(--mut);stroke-width:1}svg .gr{stroke:var(--line);stroke-width:1}
img{max-width:100%;border-radius:6px;border:1px solid var(--line)}
"""


def _f(v, d=1):
    if v is None:
        return "–"
    if isinstance(v, float):
        if abs(v) < 1 and v != 0:
            return f"{v:.3f}"
        return f"{v:.{d}f}"
    return str(v)


def _bar_svg(title, unit, rows):
    """rows: [(label, mean, ci, color)] -> horizontal bars with CI whiskers."""
    W, rh = 330, 22
    H = 30 + rh * len(rows)
    vals = [abs(m or 0) + (c or 0) for _l, m, c, _col in rows] or [1]
    top = max(vals) or 1.0
    out = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}"><text x="0" y="14" style="font-weight:600">{html.escape(title)}'
           f'{" (" + unit + ")" if unit else ""}</text>']
    for i, (label, m, ci, col) in enumerate(rows):
        y = 24 + i * rh
        if m is None:
            continue
        w = 200 * abs(m) / top
        out.append(f'<rect x="110" y="{y}" width="{w:.1f}" height="{rh - 8}" fill="{col}" rx="2"/>')
        if ci:
            x0, x1 = 110 + 200 * max(0, abs(m) - ci) / top, 110 + 200 * (abs(m) + ci) / top
            yc = y + (rh - 8) / 2
            out.append(f'<line x1="{x0:.1f}" y1="{yc}" x2="{x1:.1f}" y2="{yc}" stroke="currentColor" stroke-width="1.5" style="color:var(--fg)"/>')
        out.append(f'<text x="0" y="{y + 11}">{html.escape(label[:16])}</text><text x="{114 + w:.1f}" y="{y + 11}">{_f(m)}</text>')
    out.append("</svg>")
    return "".join(out)


def _line_svg(title, series, ylabel=""):
    """series: [(label, [(x, y)], color)]."""
    W, H, L, B = 520, 220, 44, 26
    pts = [p for _l, s, _c in series for p in s]
    if not pts:
        return ""
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts) or 1
    y1 = max(p[1] for p in pts) * 1.1 or 1
    sx = lambda x: L + (x - x0) / max(1e-9, x1 - x0) * (W - L - 10)       # noqa: E731
    sy = lambda y: H - B - y / y1 * (H - B - 24)                           # noqa: E731
    out = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}"><text x="0" y="14" style="font-weight:600">{html.escape(title)}</text>']
    for k in range(5):
        y = y1 * k / 4
        out.append(f'<line class="gr" x1="{L}" x2="{W - 10}" y1="{sy(y):.1f}" y2="{sy(y):.1f}"/><text x="2" y="{sy(y) + 4:.1f}">{_f(y)}</text>')
    out.append(f'<text x="{W - 60}" y="{H - 6}">{html.escape(ylabel)}</text>')
    for label, s, col in series:
        if len(s) > 1:
            d = " ".join(f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(s))
            out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2"/>')
    out.append("</svg>")
    return "".join(out)


def _scatter_svg(title, groups, xl, yl):
    """groups: [(label, [(x, y)], color)] with binned means drawn as lines."""
    W, H, L, B = 520, 260, 50, 30
    pts = [p for _l, s, _c in groups for p in s]
    if not pts:
        return ""
    x1 = max(p[0] for p in pts) * 1.05 or 1
    y1 = max(p[1] for p in pts) * 1.1 or 1
    sx = lambda x: L + x / x1 * (W - L - 10)                               # noqa: E731
    sy = lambda y: H - B - y / y1 * (H - B - 24)                           # noqa: E731
    out = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}"><text x="0" y="14" style="font-weight:600">{html.escape(title)}</text>']
    for k in range(5):
        y, x = y1 * k / 4, x1 * k / 4
        out.append(f'<line class="gr" x1="{L}" x2="{W - 10}" y1="{sy(y):.1f}" y2="{sy(y):.1f}"/><text x="2" y="{sy(y) + 4:.1f}">{y:.0f}</text>')
        out.append(f'<text x="{sx(x) - 8:.1f}" y="{H - 14}">{x:.0f}</text>')
    out.append(f'<text x="{W / 2 - 40}" y="{H - 2}">{html.escape(xl)}</text><text x="{L + 4}" y="30">{html.escape(yl)}</text>')
    for _label, s, col in groups:
        for x, y in s[:1500]:
            out.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="1.6" fill="{col}" fill-opacity="0.35"/>')
        bins = collections.defaultdict(list)
        step = x1 / 16
        for x, y in s:
            bins[int(x / step)].append(y)
        line = [((b + 0.5) * step, sum(v) / len(v)) for b, v in sorted(bins.items()) if len(v) >= 3]
        if len(line) > 1:
            d = " ".join(f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(line))
            out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.5"/>')
    out.append("</svg>")
    return "".join(out)


def heat_png(base_cells, heat_cells, area, title=""):
    """Road cells (grey, from where cars drove) and a heat overlay (yellow -> red), as an embedded PNG."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = area
    c0x, c0y = int(x0 // core.CELL), int(y0 // core.CELL)
    nx, ny = int(x1 // core.CELL) - c0x + 1, int(y1 // core.CELL) - c0y + 1
    s = max(1, min(12, 600 // max(nx, ny)))
    img = Image.new("RGB", (nx * s, ny * s + 18), (24, 27, 33))
    d = ImageDraw.Draw(img)
    for cx, cy in base_cells:
        d.rectangle([(cx - c0x) * s, 18 + (cy - c0y) * s, (cx - c0x + 1) * s - 1, 18 + (cy - c0y + 1) * s - 1], fill=(70, 76, 88))
    top = max([v for _x, _y, v in heat_cells] or [1.0])
    for cx, cy, v in heat_cells:
        f = min(1.0, math.sqrt(v / top))
        col = (255, int(230 - 200 * f), int(60 * (1 - f)))
        d.rectangle([(cx - c0x) * s, 18 + (cy - c0y) * s, (cx - c0x + 1) * s - 1, 18 + (cy - c0y + 1) * s - 1], fill=col)
    d.text((4, 3), f"{title}   max {top:.1f}", fill=(230, 230, 230))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _merge_cells(runs, key):
    acc = collections.Counter()
    for r in runs:
        for cx, cy, v in r.get(key, ()):
            acc[(cx, cy)] += v
    n = max(1, len(runs))
    return [(cx, cy, v / n) for (cx, cy), v in acc.items()]


def write(summary, results, spec, path):
    variants = summary["variants"]
    col = {v["name"]: COLORS[i % len(COLORS)] for i, v in enumerate(variants)}
    by = collections.defaultdict(list)
    for r in results:
        by[r["variant"]].append(r)
    sc = spec["scenario"]
    area = core.norm_area(sc["area"])
    ntiles = len(core.tiles(sc["area"]))
    h = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Traffic lab report</title><style>{CSS}</style></head><body>"]
    h.append(f"<h1>Traffic lab report — {html.escape(sc.get('name', 'scenario'))}</h1>")
    h.append(f"<div class='mut'>{time.strftime('%Y-%m-%d %H:%M')} · {len(results)} runs · {len(variants)} variants × "
             f"{summary.get('seeds')} seeds · {summary.get('workers')} workers · {summary.get('wall_s', 0) / 60:.1f} min · study area "
             f"{area[2] - area[0]:.0f} × {area[3] - area[1]:.0f} m ({ntiles} tile{'s' if ntiles > 1 else ''} of ≤ {core.TILE:.0f} m, each its own simulation) at ({(area[0] + area[2]) / 2:.0f}, {(area[1] + area[3]) / 2:.0f}) · "
             f"world {html.escape(str(spec.get('world')))}</div>")
    h.append("<div class='card mut'>Every run is the game's own traffic code (actors.Sim: AI cars, buses, emergency services, "
             "trains, pedestrians, signals) on the built world; the lab only sets the game's constants and measures. "
             "Collisions use the game's collision boxes (actors.parts) and box test (actors._sat). Values are means over seeds "
             "± the 95 % confidence interval; <span class='good'>green</span> / <span class='bad'>red</span> mark a "
             "significant (p &lt; 0.05, Welch t-test) improvement / worsening against the baseline "
             f"<b>{html.escape(summary['baseline'])}</b>.</div>")
    # scorecards
    h.append("<h2>Scores</h2><div class='grid'>")
    for v in variants:
        m = v["metrics"]
        sets = ", ".join(f"{k} = {val}" for k, val in v["settings"].items()) or "baseline settings"
        h.append(f"<div class='card'><div><span class='chip' style='background:{col[v['name']]}'></span><b>{html.escape(v['name'])}</b></div>"
                 f"<div class='mut' style='font-size:12px'>{html.escape(sets)}</div><table><tr>")
        for key, label in (("score_efficiency", "Efficiency"), ("score_safety", "Safety"), ("score_speed", "Speed")):
            s = m[key]
            h.append(f"<td style='text-align:center'><div class='score'>{_f(s['mean'], 0)}</div><div class='mut'>{label}</div></td>")
        h.append("</tr></table>")
        h.append(f"<div class='mut' style='font-size:12px'>{_f(m['speed_kmh']['mean'])} km/h · {_f(m['throughput_h']['mean'], 0)} veh/h through "
                 f"junctions · {_f(m['delay_s_km']['mean'], 0)} s/km delay · {_f(m['collisions']['mean'])} collisions · "
                 f"{_f(m['near_misses']['mean'])} near misses</div></div>")
    h.append("</div>")
    # comparison table
    h.append("<h2>All metrics</h2><div class='card wrap'><table><tr><th>Metric</th>")
    for v in variants:
        h.append(f"<th><span class='chip' style='background:{col[v['name']]}'></span>{html.escape(v['name'][:28])}</th>")
    h.append("</tr>")
    group = None
    for key, label, unit, better, g in batch.HEADLINE:
        if g != group:
            group = g
            h.append(f"<tr><td colspan='{len(variants) + 1}' style='padding-top:10px'><b>{g}</b></td></tr>")
        h.append(f"<tr><td>{html.escape(label)} <span class='mut'>{unit} {'↑' if better == 'hi' else '↓'}</span></td>")
        for v in variants:
            s = v["metrics"][key]
            cls = "" if s.get("better") is None else ("good" if s["better"] else "bad")
            extra = ""
            if s.get("diff") is not None:
                extra = f" <span class='mut'>({'+' if s['diff'] >= 0 else ''}{_f(s['diff'])}, p={s['p']:.3f})</span>"
            h.append(f"<td class='{cls}'>{_f(s['mean'])} <span class='mut'>± {_f(s['ci'])}</span>{extra}</td>")
        h.append("</tr>")
    h.append("</table></div>")
    # bar charts
    h.append("<h2>Comparison charts</h2><div class='grid'>")
    for key, label, unit, _b, _g in batch.HEADLINE:
        if key in ("speed_kmh", "throughput_h", "delay_s_km", "stuck4_share", "jams", "collisions", "near_misses", "redruns",
                   "ems_response", "bus_kmh", "gridlock_s", "ped_conflicts"):
            rows = [(v["name"], v["metrics"][key]["mean"], v["metrics"][key]["ci"], col[v["name"]]) for v in variants]
            h.append(f"<div class='card'>{_bar_svg(label, unit, rows)}</div>")
    h.append("</div>")
    # time series
    h.append("<h2>Over time (mean of seeds)</h2><div class='grid'>")
    for idx, title, yl in ((2, "Mean speed in the area", "m/s"), (3, "Standing share", ""), (1, "Cars in the area", ""), (4, "Junction passes per 5 s", "")):
        ser = []
        for v in variants:
            acc = collections.defaultdict(list)
            for r in by[v["name"]]:
                for row in r.get("series", ()):
                    acc[row[0]].append(row[idx])
            ser.append((v["name"], [(t, sum(a) / len(a)) for t, a in sorted(acc.items())], col[v["name"]]))
        h.append(f"<div class='card'>{_line_svg(title, ser, yl)}</div>")
    h.append("</div>")
    # fundamental diagram
    h.append("<h2>Fundamental diagram (per road segment, every 10 s)</h2><div class='grid'>")
    fq = [(v["name"], [(k, q) for r in by[v["name"]] for k, q, _s in r.get("fd", ())], col[v["name"]]) for v in variants]
    fv = [(v["name"], [(k, s) for r in by[v["name"]] for k, _q, s in r.get("fd", ())], col[v["name"]]) for v in variants]
    h.append(f"<div class='card'>{_scatter_svg('Flow vs density', fq, 'density (veh/km/lane)', 'flow (veh/h/lane)')}</div>")
    h.append(f"<div class='card'>{_scatter_svg('Speed vs density', fv, 'density (veh/km/lane)', 'speed (km/h)')}</div>")
    hist = []
    for v in variants:
        tot = [0] * 30
        for r in by[v["name"]]:
            for i, n in enumerate(r.get("speed_hist", ())):
                tot[i] += n
        s = sum(tot) or 1
        hist.append((v["name"], [(i * 2 * 3.6, n / s * 100) for i, n in enumerate(tot)], col[v["name"]]))
    h.append(f"<div class='card'>{_line_svg('Speed distribution (% of samples)', hist, 'km/h')}</div></div>")
    # junctions
    h.append("<h2>Junctions (level of service by HCM control delay)</h2><div class='grid'>")
    for v in variants:
        agg = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in by[v["name"]]:
            for j in r.get("junctions", ()):
                for k in ("veh_h", "delay", "queue_max", "queue_mean", "redruns"):
                    agg[j["node"]][k].append(j[k])
                agg[j["node"]]["xy"] = (j["x"], j["y"])
                agg[j["node"]]["signal"] = j["signal"]
        rows = sorted(agg.items(), key=lambda kv: -sum(kv[1]["veh_h"]) / len(kv[1]["veh_h"]))[:25]
        mix = collections.Counter()
        tbl = ["<table><tr><th>Junction (x, y)</th><th>veh/h</th><th>delay s</th><th>LOS</th><th>queue max m</th><th>red runs</th></tr>"]
        for _node, a in rows:
            mean = lambda k: sum(a[k]) / max(1, len(a[k]))                    # noqa: E731
            L = core.los(mean("delay"), a["signal"])
            mix[L] += 1
            tbl.append(f"<tr><td>{'🚦 ' if a['signal'] else ''}({a['xy'][0]}, {a['xy'][1]})</td><td>{mean('veh_h'):.0f}</td>"
                       f"<td>{mean('delay'):.1f}</td><td style='background:{LOS_COL[L]};color:#111;text-align:center'>{L}</td>"
                       f"<td>{mean('queue_max'):.0f}</td><td>{mean('redruns'):.1f}</td></tr>")
        tbl.append("</table>")
        h.append(f"<div class='card wrap'><b><span class='chip' style='background:{col[v['name']]}'></span>{html.escape(v['name'])}</b> "
                 f"<span class='mut'>LOS mix of the busiest 25: {' '.join(f'{k}:{n}' for k, n in sorted(mix.items()))}</span>{''.join(tbl)}</div>")
    h.append("</div>")
    # heatmaps
    h.append("<h2>Heatmaps (mean per run)</h2><div class='grid'>")
    for v in variants:
        rs = by[v["name"]]
        base = [(cx, cy) for cx, cy, _v in _merge_cells(rs, "heat_speed")]
        for key, title in (("heat_stand", "standing vehicle-seconds"), ("heat_conf", "collisions + near misses")):
            h.append(f"<div class='card'><b>{html.escape(v['name'])}</b> <span class='mut'>{title}</span><br>"
                     f"<img src='{heat_png(base, _merge_cells(rs, key), area, title)}'></div>")
    h.append("</div>")
    # tiles of a big study rectangle
    if any(r.get("tiles") for r in results):
        h.append("<h2>Tiles (where the study rectangle has problems)</h2><div class='grid'>")
        for v in variants:
            acc = collections.defaultdict(lambda: collections.defaultdict(list))
            for r in by[v["name"]]:
                for t in r.get("tiles", ()):
                    for k2, val in t.items():
                        if k2 not in ("tile", "area"):
                            acc[t["tile"]][k2].append(val)
                    acc[t["tile"]]["area"] = t["area"]
            rows = sorted(acc.items(), key=lambda kv: sum(kv[1]["score_efficiency"]) / len(kv[1]["score_efficiency"]))
            tbl = ["<table><tr><th>tile centre</th><th>cars</th><th>km/h</th><th>> 4 s</th><th>jams</th><th>collisions</th>"
                   "<th>near</th><th>E / S / V</th></tr>"]
            for _ti, a in rows[:30]:
                mean = lambda k: sum(a[k]) / max(1, len(a[k]))                    # noqa: E731
                ar = a["area"] or [0, 0, 0, 0]
                tbl.append(f"<tr><td>({(ar[0] + ar[2]) / 2:.0f}, {(ar[1] + ar[3]) / 2:.0f})</td><td>{mean('cars_mean'):.0f}</td>"
                           f"<td>{mean('speed_kmh'):.1f}</td><td>{mean('stuck4_share') * 100:.0f} %</td><td>{mean('jams'):.1f}</td>"
                           f"<td>{mean('collisions'):.1f}</td><td>{mean('near_misses'):.1f}</td><td>{mean('score_efficiency'):.0f} / "
                           f"{mean('score_safety'):.0f} / {mean('score_speed'):.0f}</td></tr>")
            tbl.append("</table>")
            h.append(f"<div class='card wrap'><b>{html.escape(v['name'])}</b> <span class='mut'>worst efficiency first</span>{''.join(tbl)}</div>")
        h.append("</div>")
    # where things happened
    h.append("<h2>Worst places (all runs)</h2><div class='grid'>")
    for key, title in (("jam_list", "Jams"), ("collision_list", "Collisions"), ("redrun_list", "Red-light runs"), ("near_list", "Near misses")):
        cnt = collections.Counter()
        for r in results:
            for row in r.get(key, ()):
                cnt[(round(row[1] / 25) * 25, round(row[2] / 25) * 25)] += 1
        rows = "".join(f"<tr><td>({x}, {y})</td><td>{n}</td></tr>" for (x, y), n in cnt.most_common(12))
        h.append(f"<div class='card'><b>{title}</b><table><tr><th>25 m cell</th><th>count</th></tr>{rows or '<tr><td>none</td><td></td></tr>'}</table></div>")
    h.append("</div>")
    h.append("<h2>Method</h2><div class='card mut'>Efficiency: throughput = vehicles through junctions per hour in the area; "
             "delay = time lost against each driver's own free speed (limit × pace, vehicle top speed); standing = speed &lt; 0.3 m/s; "
             "jam = standing &gt; 25 s outside a red-light queue; gridlock = ≥ 3 cars standing &gt; 60 s in one junction box. "
             "Speed: space-mean speed = vehicle-km / vehicle-hours. Safety: collision = the game's boxes overlap &gt; 5 cm with at "
             "least one vehicle moving (ghosting cars, the game's last-resort pass-through, counted apart); near miss = straight-line "
             "time to collision &lt; 1.5 s; pedestrian conflict = a car passes within 1 m of a walking pedestrian at &gt; 3 m/s; "
             "red-light run = the front crosses the stop line while its approach is red. LOS: HCM thresholds on control delay "
             "(from 60 m before the junction until through it), signalised A ≤ 10, B ≤ 20, C ≤ 35, D ≤ 55, E ≤ 80 s; "
             "unsignalised A ≤ 10, B ≤ 15, C ≤ 25, D ≤ 35, E ≤ 50 s. Scores: efficiency = 100 × (1 − time lost share); "
             "safety = 100 / (1 + conflicts per 1000 veh-km / 50); speed = 100 × speed / limit.</div>")
    h.append("<h2>Spec</h2><div class='card wrap'><pre style='font-size:11px'>" +
             html.escape(json.dumps({k: v for k, v in spec.items() if k != "scenario"} | {"scenario": {k: v for k, v in sc.items()}},
                                    ensure_ascii=False, indent=1)[:20000]) + "</pre></div>")
    h.append("</body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(h))
    return path
