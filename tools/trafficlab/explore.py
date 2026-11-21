"""Explore: search the game's traffic rules and constants for better settings, on every core.

Generation 0 samples candidates at random (uniform over each chosen parameter's range, or "informed": around the
game's current values); later generations keep the best (elite), mutate them with a shrinking step, cross two of
them, and add a few random newcomers so wild ideas keep coming.  Every candidate runs on the same search seeds, so
candidates are compared on the same traffic.  Objective = weighted mean of the efficiency, safety and speed scores
(0..100 each, see core.Metrics.summary), averaged over seeds.

Overfitting guard: at the end the best candidates and the game's own settings (the baseline) are re-run on fresh
seeds nobody was selected on; the leaderboard ranks by that validation score with its 95 % confidence interval and
a Welch t-test against the baseline, and the full batch report is written for them.

Spec: {"world", "osm", "scenario", "base": {settings}, "keys": [param keys to vary], "weights": [eff, safety, speed],
       "population": 16, "generations": 6, "elite": 4, "seeds": 2, "validate_seeds": 6, "finalists": 5,
       "informed": true, "seed0": 1, "workers": 0}
Command line: python tools/traffic_lab.py --explore spec.json"""
import json
import os
import random
import time

from . import OUT, batch, core, params

DEFAULT_KEYS = ("aggro", "speed_factor", "wait_scale", "squeeze_v", "lane_v", "lane_hold", "plan_m", "appr", "claim_lead",
                "cycle", "green", "yellow", "clear", "wave")
SLIM = ("score_efficiency", "score_safety", "score_speed", "speed_kmh", "throughput_h", "delay_s_km", "stuck4_share", "jams",
        "collisions", "near_misses", "redruns", "gridlock_s")


def objective(r, weights):
    we, ws, wv = weights
    tot = (we + ws + wv) or 1.0
    return (we * r["score_efficiency"] + ws * r["score_safety"] + wv * r["score_speed"]) / tot


def _sample(p, rng, informed, around=None, sigma=0.25):
    if p.kind == "bool":
        if around is not None:
            return (not around) if rng.random() < 0.2 else around
        return rng.random() < 0.5
    lo, hi = p.lo, p.hi
    if around is None and not informed:
        v = rng.uniform(lo, hi)
    else:
        c = p.default if around is None else around
        v = rng.gauss(c, sigma * (hi - lo))
    return params.clamp(p, min(hi, max(lo, v)))


class Explorer:
    def __init__(self, spec, progress=None, cancel=None):
        self.spec = spec
        self.keys = [k for k in (spec.get("keys") or DEFAULT_KEYS) if k in params.BY_KEY]
        self.w = spec.get("weights") or [0.4, 0.4, 0.2]
        self.rng = random.Random(int(spec.get("seed0", 1)) * 31 + 7)
        self.progress = progress or (lambda *a: None)
        self.cancel = cancel or (lambda: False)
        self.cands = []                       # {"id", "gen", "settings", "runs": [slim results], "score", "ci"}
        self.leader = []                      # validated finalists
        self.state = "idle"
        self.out = os.path.join(OUT, "explore", time.strftime("%Y%m%d-%H%M%S"))
        self.base = dict(params.defaults())
        self.base.update(spec.get("base") or {})

    # ---------------------------------------------------------- candidates
    def _new(self, settings, gen, how):
        c = {"id": len(self.cands), "gen": gen, "how": how, "settings": settings, "runs": [], "score": None, "ci": None}
        self.cands.append(c)
        return c

    def _random(self, gen):
        informed = bool(self.spec.get("informed", True))
        return {k: _sample(params.BY_KEY[k], self.rng, informed) for k in self.keys}

    def _mutate(self, parent, gen):
        sigma = 0.25 * (0.7 ** gen)
        s = dict(parent["settings"])
        for k in self.rng.sample(self.keys, max(1, len(self.keys) // 3)):
            s[k] = _sample(params.BY_KEY[k], self.rng, True, s.get(k, params.BY_KEY[k].default), sigma)
        return s

    def _cross(self, a, b):
        return {k: (a["settings"] if self.rng.random() < 0.5 else b["settings"]).get(k, params.BY_KEY[k].default) for k in self.keys}

    def _jobs(self, cands, seeds):
        out = []
        for c in cands:
            st = dict(self.base)
            st.update(c["settings"])
            for s in seeds:
                for ti in range(len(core.tiles(self.spec["scenario"]["area"]))):
                    out.append((self.spec["world"], self.spec["osm"], st, dict(self.spec["scenario"], tile=ti), s, f"c{c['id']}"))
        return out

    def _evaluate(self, cands, seeds, field="runs"):
        by = {f"c{c['id']}": c for c in cands}
        jobs = self._jobs(cands, seeds)
        done = [0]
        ntiles = len(core.tiles(self.spec["scenario"]["area"]))
        parts = {}

        def got(r0):
            done[0] += 1
            key = (r0["variant"], r0["seed"])
            parts.setdefault(key, []).append(r0)
            if len(parts[key]) < ntiles:
                self.progress(self, f"{self.state}: {done[0]}/{len(jobs)} runs")
                return
            r = batch.merge_tiles(parts.pop(key))[0] if ntiles > 1 else r0
            c = by[r["variant"]]
            c[field].append({k: r.get(k) for k in SLIM} | {"seed": r["seed"]})
            if field == "vruns":
                self._vfull.append(r)
            vals = [objective(x, self.w) for x in c[field]]
            st = batch.stats(vals)
            c["score" if field == "runs" else "vscore"], c["ci" if field == "runs" else "vci"] = st["mean"], st["ci"]
            self.progress(self, f"{self.state}: {done[0]}/{len(jobs)} runs")
        return batch.pool_map(jobs, self.n, got, self.cancel)

    # ---------------------------------------------------------- the search
    def run(self):
        sp = self.spec
        pop, gens = int(sp.get("population", 16)), int(sp.get("generations", 6))
        elite_n = max(2, int(sp.get("elite", 4)))
        s0 = int(sp.get("seed0", 1))
        seeds = [s0 + k for k in range(int(sp.get("seeds", 2)))]
        self.n = batch.auto_workers(sp["world"], int(sp.get("workers") or 0), pop * len(seeds))
        os.makedirs(self.out, exist_ok=True)
        baseline = self._new({}, 0, "game settings")
        gen0 = [baseline] + [self._new(self._random(0), 0, "random") for _ in range(pop - 1)]
        self.state = "generation 1"
        if not self._evaluate(gen0, seeds):
            return self.finish()
        for g in range(1, gens):
            ranked = sorted((c for c in self.cands if c["score"] is not None), key=lambda c: -c["score"])
            elite = ranked[:elite_n]
            kids = []
            while len(kids) < pop:
                r = self.rng.random()
                if r < 0.55:
                    kids.append(self._new(self._mutate(self.rng.choice(elite), g), g, "mutation"))
                elif r < 0.85 and len(elite) > 1:
                    a, b = self.rng.sample(elite, 2)
                    kids.append(self._new(self._mutate({"settings": self._cross(a, b)}, g + 2), g, "crossover"))
                else:
                    kids.append(self._new(self._random(g), g, "random"))
            self.state = f"generation {g + 1}"
            self._save()
            if not self._evaluate(kids, seeds):
                return self.finish()
        return self.finish()

    def finish(self):
        """Re-test the finalists and the baseline on fresh seeds and write the report."""
        sp = self.spec
        ranked = sorted((c for c in self.cands if c["score"] is not None and c["settings"]), key=lambda c: -c["score"])
        final = ranked[:int(sp.get("finalists", 5))]
        baseline = self.cands[0]
        fresh = [int(sp.get("seed0", 1)) + 10000 + k for k in range(int(sp.get("validate_seeds", 6)))]
        for c in [baseline] + final:
            c["vruns"] = []
        self._vfull = []
        self.state = "validating on fresh seeds"
        if final and not self.cancel():
            self.cancel = lambda: False                              # validation always completes once started
            self._evaluate([baseline] + final, fresh, "vruns")
        for c in final:
            d, p = batch.welch([objective(x, self.w) for x in baseline["vruns"]], [objective(x, self.w) for x in c["vruns"]])
            c["vdiff"], c["vp"] = d, p
        self.leader = sorted(final, key=lambda c: -(c.get("vscore") or -1e9))
        self.state = "done"
        self._save()
        self._report(baseline, fresh)
        self.progress(self, "done")
        return self

    def _save(self):
        with open(os.path.join(self.out, "explore.json"), "w", encoding="utf-8") as f:
            json.dump({"spec": {k: v for k, v in self.spec.items() if k != "scenario"}, "keys": self.keys, "weights": self.w,
                       "candidates": self.cands, "leader": [c["id"] for c in self.leader], "state": self.state}, f, ensure_ascii=False)

    def _report(self, baseline, fresh):
        """The full batch report of the validation runs: baseline vs the finalists, on the fresh seeds."""
        if not self.leader or not self._vfull:
            return
        from . import report
        names = {f"c{baseline['id']}": "baseline (game)"}
        variants = [{"name": "baseline (game)", "settings": {}}]
        for i, c in enumerate(self.leader):
            names[f"c{c['id']}"] = f"#{i + 1} c{c['id']}"
            variants.append({"name": names[f"c{c['id']}"], "settings": c["settings"]})
        for r in self._vfull:
            r["variant"] = names.get(r["variant"], r["variant"])
        spec = dict(self.spec, variants=variants, sweep=None, seeds=len(fresh), seed0=fresh[0])
        summary = batch.summarize(variants, self._vfull, spec)
        summary["workers"] = self.n
        os.makedirs(os.path.join(self.out, "report"), exist_ok=True)
        with open(os.path.join(self.out, "report", "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False)
        report.write(summary, self._vfull, spec, os.path.join(self.out, "report", "report.html"))
        self.report_dir = os.path.join(self.out, "report")

    def best(self):
        return self.leader[0] if self.leader else (max((c for c in self.cands if c["score"] is not None), key=lambda c: c["score"], default=None))
