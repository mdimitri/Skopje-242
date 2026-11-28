"""Per-tile cache of the candidate road builder: a road tile or reviewed window whose inputs and builder code are
unchanged is loaded instead of compiled, so a local map edit rebuilds only the tiles around it.

The key is made from what the job reads, with graph node and edge numbers replaced by OSM ids (an edit elsewhere renumbers
them); the stored signal records refer to the job's own edge list and are translated back on load.  build_world's stage
runner names the cache folder in SK242_ROAD_CACHE."""
import hashlib
import io
import os
import pickle
import zlib

import numpy as np
import shapely

from stages import _CanonPickler

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = ("roads_candidate.py", "roads_designer.py", "road_cache.py", "junction_net.py", "terrain.py", "geo.py", "subdivide.py", "roadvault/road_candidate.py",
        "roadvault/road_inference.py", "roadvault/mesh.py", "roadvault/run_candidate.py", "roadvault/traffic_furniture.py",
        "roadvault/partizanski_glavinov.json", "../src/roadwidth.py")
_ONCE = {}                                              # per worker: hashes of what every key shares


def _hash(*things):
    buf = io.BytesIO()
    pickler = _CanonPickler(buf, protocol=pickle.HIGHEST_PROTOCOL)
    pickler.fast = True                                   # no memo: equal data gives equal bytes however it is shared
    for t in things:
        pickler.dump(t)
    return hashlib.sha1(buf.getbuffer()).hexdigest()


def _once(name, make):
    if name not in _ONCE:
        _ONCE[name] = make()
    return _ONCE[name]


def _file(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return "-"


def _edge(source, edge):
    out = dict(edge)
    out["road"] = source.road_ids[edge["road"]]
    for end in ("a", "b"):
        n = edge[end]
        out[end] = (n[0], source.road_ids[edge["road"]], n[2]) if isinstance(n, tuple) else source.node_ids.get(n, n)
    return out


def key(job, G, size, margin):
    source, edges = G["source"], G["edges"]
    code = _once("code", lambda: _hash([_file(os.path.join(HERE, p)) for p in CODE], shapely.__version__, shapely.geos_version, np.__version__))
    sub = [edges[i] for i in _used(job, edges)]
    bridges = sorted({source.road_ids[edges[i]["road"]] for i in job[2] if edges[i]["bridge"]})    # OSM ways drawn by their decks
    parts = [code, size, margin, job[0], [_edge(source, e) for e in sub], bridges,
             [source.tags.get(source.road_ids[e["road"]]) for e in sub]]
    flat = [e for e in sub if e.get("flat")]
    if flat and G["T"] is not None:                       # bridge mouths are laid on their deck over the ground
        parts.append(_once("terrain", lambda: _hash(np.asarray(G["T"].g).tobytes())))
        parts.append([G["decks"][e["road"]].pack() for e in flat if G["decks"] and e["road"] in G["decks"]])
    sites = [(s["kind"], s["origin"], s["radius"]) for s in source.sites]
    if job[0] == "site":
        files = _once("files", lambda: [_file(os.path.join(str(source.osm), n)) for n in ("roads.json", "areas.json", "restrictions.json")])
        return _hash(parts, sites[job[1]], files)
    (tx, ty), skip = job[1], job[3]
    reach = size / 2 + margin
    found = sorted(source.index.query(shapely.box(tx - reach, ty - reach, tx + reach, ty + reach), predicate="intersects"))
    features = []
    for i in found:
        kind, data, shape = source.features[i]
        extra = source.originals.get(data["id"]) if kind == "road" else None
        features.append((kind, data, extra, shapely.to_wkb(shape)))
    relations = _once("relations", lambda: _hash(source.relations))
    return _hash(parts, (tx, ty), skip, sites, features, relations)


def _used(job, edges):
    """The job's graph edges whose shape the candidate builder reads (build_tile, _graph_records, drape_feet): one-way
    carriageways, which signals bind to, and grounded bridge tails.  The asphalt itself comes from the OSM ways, so a
    two-way street cut at another place (a new worn path joining it) does not change the tile."""
    return [i for i in job[2] if edges[i]["drive"] and not edges[i]["bridge"] and (edges[i]["ow"] or edges[i].get("flat"))]


def _nodes(controls, edge_of, node_of):
    """The signal records with every edge number passed through edge_of and every graph node through node_of."""
    out = dict(controls)

    def node(n):
        return ("candidate", node_of(n[1])) if isinstance(n, tuple) and n[:1] == ("candidate",) and n[1] != "glavinov" else n
    out["signals"] = [(node(r[0]), edge_of(r[1]), r[2], edge_of(r[3]), *r[4:]) for r in controls.get("signals", ())]
    out["heads"] = [(node(r[0]), None if r[1] is None else edge_of(r[1]), *r[2:]) for r in controls.get("heads", ())]
    out["crossings"] = [(*r[:7], node(r[7])) for r in controls.get("crossings", ())]
    return out


def load(folder, k, job, G):
    """The cached result of the job, or None."""
    try:
        with open(os.path.join(folder, k), "rb") as f:
            result = pickle.loads(zlib.decompress(f.read()))
    except (OSError, ValueError, zlib.error, pickle.UnpicklingError, EOFError):
        return None
    if result is None:
        return None
    edges = G["edges"]
    idx = _used(job, edges)
    controls = _nodes(result[1], lambda p: idx[p], lambda end: edges[idx[end[0]]][end[1]])
    return (result[0], controls, *result[2:])


def save(folder, k, job, G, result):
    edges = G["edges"]
    idx = _used(job, edges)
    position = {e: p for p, e in enumerate(idx)}
    ends = {}
    for p, i in enumerate(idx):
        for end in ("b", "a"):
            ends.setdefault(edges[i][end], (p, end))
    try:
        controls = _nodes(result[1], lambda e: position[e], lambda n: ends[n])
    except KeyError:                                      # a record outside the job's edges: do not cache this one
        return
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, f"{k}.{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        f.write(zlib.compress(pickle.dumps((result[0], controls, *result[2:]), protocol=pickle.HIGHEST_PROTOCOL), 1))
    os.replace(tmp, os.path.join(folder, k))


def prune(folder, used):
    """Drop the entries this build did not use."""
    try:
        for name in os.listdir(folder):
            if name not in used:
                os.remove(os.path.join(folder, name))
    except OSError:
        pass
