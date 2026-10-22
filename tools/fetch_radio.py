"""Downloads freely licensed Macedonian music for the car radio from Wikimedia Commons.

    python tools/fetch_radio.py [--target 100] [--max-mb 12] [--list]

* finds audio files through the Commons API (category crawl + search), keeps only CC0 / CC BY / CC BY-SA / public domain
  (NC / ND / fair-use are rejected), reads the licence and author from the file's metadata;
* resumable: finished files are skipped, partial ones are re-fetched, the run can be killed and started again;
* writes assets/radio/ATTRIBUTION.md (title, author, licence, source URL for every track kept);
* never fails the game start: exits 0 even when offline.  If fewer than --target tracks exist it says so.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "radio")
API = ["https://commons.wikimedia.org/w/api.php"]
EXT = {"audio/ogg": ".ogg", "application/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
       "audio/flac": ".flac", "audio/x-flac": ".flac"}
SEED_CATS = ["Music of North Macedonia", "Macedonian music", "Macedonian folk music", "Folk music of North Macedonia",
             "Macedonian songs", "Songs in Macedonian", "Macedonian-language songs", "Macedonian pop music",
             "Audio files of North Macedonia", "Macedonian singers", "Macedonian musicians", "Macedonian dances", "Македонска музика", "Македонски пејачи", "Македонски музичари", "Македонски пејачки",
             "Macedonian female singers", "Macedonian male singers",
             "Music of the Republic of Macedonia", "Macedonian music by genre", "Sound of North Macedonia",
             "Eurovision Song Contest entries of North Macedonia", "Eurovision Song Contest entries of Macedonia"]
SEARCHES = ["Macedonian folk filetype:audio", "Macedonian song filetype:audio", "Macedonia folk music filetype:audio",
            "makedonska filetype:audio", "Skopje music filetype:audio", "oro Macedonian filetype:audio",
            "Macedonian pop filetype:audio", "Eurovision Macedonia filetype:audio", "македонска музика filetype:audio",
            "македонски пејач filetype:audio", "македонска песна filetype:audio", "македонска народна музика filetype:audio",
            "македонски пејачи filetype:audio", "македонски музичари filetype:audio", "пејачка македонија filetype:audio",
            "македонско оро filetype:audio", "Macedonian singer filetype:audio", "Macedonian musicians filetype:audio",
            "Macedonian traditional filetype:audio", "Ohrid song filetype:audio", "Tose Proeski filetype:audio"]
RELEVANT = re.compile(r"пејач|музичар|македон|macedon|makedon|македон|skopje|скопје|ohrid|bitola|oro\b|tose|proeski|kaliopi|vardar", re.I)
GOOD = re.compile(r"^(cc0|cc[- ]by(-sa)?\b|public domain|pd\b|pd-|attribution|cc[- ]zero)", re.I)
# songs only: no speeches, interviews, field recordings, sound effects, anthems read aloud ...
NOT_SONG = re.compile(r"speech|говор|interview|интервју|lecture|predavan|предавање|spoken|poem|poetry|поезија|reading|"
                      r"pronunciation|изговор|sound effect|sfx|ambien|field recording|noise|bird|ptic|bell|ѕвон|church|"
                      r"crowd|traffic|recording of|test tone|jingle|announcement|news|вести|radio show|podcast|"
                      r"wikipedia|spoken word|audiobook|anthem|химна|ringtone|alarm|siren", re.I)
SONG = re.compile(r"song|песна|pesna|pop|поп|music|музик|singer|пејач|band|бенд|album|албум|single|сингл|vocal|"
                  r"chorus|melod|hit\b|eurovision|евровизија|dance|track|cover|remix|ballad|rock|folk|oro|оро", re.I)
IA = "https://archive.org"
IA_QUERIES = [  # Internet Archive netlabels: whole CC pop songs (no NC / ND)
    'mediatype:audio AND (subject:(macedonian pop) OR subject:(balkan pop) OR subject:(makedonska) OR subject:(turbofolk))',
    'mediatype:audio AND collection:netlabels AND subject:(pop)',
    'mediatype:audio AND collection:netlabels AND subject:(synthpop OR electropop OR "indie pop" OR "dance pop")',
    'mediatype:audio AND collection:opensource_audio AND subject:(pop song)',
]
BAD = re.compile(r"\bnc\b|-nc|noncommercial|\bnd\b|-nd|fair use|non-free|copyrighted", re.I)


def say(m):
    print("[radio] " + m, flush=True)


def api(**kw):
    kw.update(format="json", formatversion="2")
    url = API[0] + "?" + urllib.parse.urlencode(kw)
    for attempt in range(5):
        try:
            return json.loads(net.fetch(url, "radio_api", first_byte=40, stall=20, limit=90))
        except net.Fail as f:
            if f.kind in ("offline", "reject"):
                raise
            time.sleep(min(30, f.retry_after or 3 * (attempt + 1)))
    raise net.Fail("net", "API unreachable")


def cat_files(cat, depth, seen_cats, found):
    if cat in seen_cats or len(seen_cats) > 200:
        return
    seen_cats.add(cat)
    cont = {}
    while True:
        try:
            d = api(action="query", list="categorymembers", cmtitle="Category:" + cat, cmtype="file|subcat", cmlimit="500", **cont)
        except net.Fail as f:
            if f.kind == "offline":
                raise
            return
        for m in d.get("query", {}).get("categorymembers", []):
            t = m["title"]
            if t.startswith("File:"):
                found.add(t)
            elif t.startswith("Category:") and depth > 0:
                cat_files(t[9:], depth - 1, seen_cats, found)
        if "continue" not in d:
            break
        cont = d["continue"]


def search_files(q, found):
    cont = {}
    for _ in range(4):
        d = api(action="query", list="search", srsearch=q, srnamespace="6", srlimit="100", **cont)
        for m in d.get("query", {}).get("search", []):
            found.add(m["title"])
        if "continue" not in d:
            break
        cont = d["continue"]


def artists():
    """Names from popular_singers.txt in the game folder ("1. Taylor Swift" per line)."""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "popular_singers.txt")
    try:
        lines = open(p, encoding="utf-8").read().splitlines()
    except OSError:
        return []
    return [n for n in (re.sub(r"^\s*\d+[.)]\s*", "", l).strip() for l in lines) if n]


def strip(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h or "")).strip()


def infos(titles):
    out = []
    for i in range(0, len(titles), 40):
        d = api(action="query", prop="imageinfo", titles="|".join(titles[i:i + 40]), iiprop="url|size|mime|extmetadata")
        for p in d.get("query", {}).get("pages", []):
            ii = (p.get("imageinfo") or [None])[0]
            if ii:
                out.append((p["title"], ii))
    return out


def judge(title, ii, via_cat, max_mb):
    mime = ii.get("mime", "")
    if mime not in EXT or ii.get("size", 0) > max_mb * 1e6 or ii.get("size", 0) < 20000:
        return None
    md = ii.get("extmetadata", {})
    lic = strip(md.get("LicenseShortName", {}).get("value", ""))
    if not lic or BAD.search(lic) or not GOOD.search(lic):
        return None
    desc = strip(md.get("ImageDescription", {}).get("value", "")) + " " + title
    cats = strip(md.get("Categories", {}).get("value", ""))
    artist = via_cat == "artist"
    if not via_cat and not RELEVANT.search(desc + " " + cats):
        return None
    if NOT_SONG.search(desc + " " + cats) or not (artist or SONG.search(desc + " " + cats)) or ii.get("size", 0) < 900000:
        return None                                                  # under ~1 MB is a jingle / effect, not a song
    return {"title": title[5:], "url": ii["url"], "page": ii.get("descriptionurl", ""), "mime": mime, "size": ii["size"],
            "license": lic, "author": strip(md.get("Artist", {}).get("value", "")) or "unknown",
            "credit": strip(md.get("Credit", {}).get("value", ""))[:160]}


def ia_tracks(max_mb):
    """Pop songs from Internet Archive items with a CC licence that allows reuse (no NC / ND)."""
    for q in IA_QUERIES:
        url = IA + "/advancedsearch.php?" + urllib.parse.urlencode(
            {"q": q, "fl[]": ["identifier", "licenseurl", "creator", "title"], "rows": "150", "output": "json"}, doseq=True)
        try:
            docs = json.loads(net.fetch(url, "radio_api", first_byte=40, stall=20, limit=90))["response"]["docs"]
        except (net.Fail, KeyError, ValueError) as f:
            say("Internet Archive search failed (%s)" % f)
            continue
        say("Internet Archive: %d albums for %s" % (len(docs), q[:60]))
        for d in docs:
            lic = d.get("licenseurl") or ""
            if "creativecommons.org" not in lic or re.search(r"-nc|-nd|/nc|/nd", lic):
                if "publicdomain" not in lic:
                    continue
            try:
                md = json.loads(net.fetch(IA + "/metadata/" + d["identifier"], "radio_api", first_byte=40, stall=20, limit=60))
            except (net.Fail, ValueError):
                continue
            n = 0
            for f in md.get("files", []):
                nm = f.get("name", "")
                if not nm.lower().endswith(".mp3") or "sample" in nm.lower():
                    continue
                try:
                    ln = float(f.get("length", 0) or 0)
                except ValueError:
                    ln = 0                              # "3:41" style: accept on size
                size = int(f.get("size", 0) or 0)
                if (ln and not 90 <= ln <= 420) or size < 1500000 or size > max_mb * 1e6:
                    continue
                if NOT_SONG.search(nm + " " + (f.get("title") or "")):
                    continue
                cre = d.get("creator") or "unknown"
                yield {"title": (f.get("title") or nm.rsplit(".", 1)[0])[:80] + ".mp3",
                       "url": IA + "/download/" + d["identifier"] + "/" + urllib.parse.quote(nm),
                       "page": IA + "/details/" + d["identifier"], "mime": "audio/mpeg", "size": size,
                       "license": lic.rstrip("/").split("/licenses/")[-1].replace("/", " ") or lic,
                       "author": (cre if isinstance(cre, str) else ", ".join(cre))[:80], "credit": "Internet Archive"}
                n += 1
                if n >= 3:                              # a few songs per album keeps the radio varied
                    break


def fname(t):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", t["title"].rsplit(".", 1)[0])[:70] + EXT[t["mime"]]


def write_attr(tracks):
    lines = ["# Radio tracks - licences and attribution", "",
             "All files come from Internet Archive or Wikimedia Commons and are CC0 / CC BY / CC BY-SA / public domain.",
             "Generated by tools/fetch_radio.py; %d tracks." % len(tracks), "",
             "| File | Title | Author | Licence | Source |", "|---|---|---|---|---|"]
    for t in sorted(tracks, key=lambda x: x["file"]):
        lines.append("| %s | %s | %s | %s | %s |" % (t["file"], t["title"].replace("|", "/"), t["author"][:80].replace("|", "/"),
                                                      t["license"], t["page"]))
    with open(os.path.join(OUT, "ATTRIBUTION.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(tracks, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--max-mb", type=float, default=12)
    ap.add_argument("--list", action="store_true", help="only list what would be downloaded")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    idx_path = os.path.join(OUT, "index.json")
    have = json.load(open(idx_path, encoding="utf-8")) if os.path.exists(idx_path) else []
    have = [t for t in have if os.path.exists(os.path.join(OUT, t["file"]))]
    for t in list(have):                                  # earlier rounds kept speeches / effects: drop them
        if t.get("credit") != "Internet Archive" and (NOT_SONG.search(t["title"] + " " + t.get("credit", ""))
                                                       or t.get("size", 0) < 900000):
            have.remove(t)
            try:
                os.remove(os.path.join(OUT, t["file"]))
            except OSError:
                pass
            say("removed (not a song): " + t["title"][:60])
    write_attr(have)
    if len(have) >= a.target and not a.list:
        say("%d radio tracks present - nothing to do" % len(have))
        return 0
    net.emit("radio", n=len(have), target=a.target, title="")
    # the slow part (searching Commons) is cached, and every good file is downloaded as soon as it is judged, so a
    # game that is closed early still keeps what it got and the next start continues instead of searching again
    cache = os.path.join(OUT, "candidates.json")
    done = list(have)
    have_f = {t["file"] for t in have}
    if not a.list:
        say("looking for CC-licensed pop songs on Internet Archive ...")
        try:
            for t in ia_tracks(a.max_mb):
                if len(done) >= a.target:
                    break
                t["file"] = fname(t)
                if t["file"] in have_f:
                    continue
                try:
                    body = net.fetch(t["url"], "radio_dl", first_byte=40, stall=20, limit=240)
                except net.Fail as f:
                    say("skip %s (%s)" % (t["title"], f))
                    continue
                dest = os.path.join(OUT, t["file"])
                with open(dest + ".part", "wb") as fh:
                    fh.write(body)
                os.replace(dest + ".part", dest)
                done.append(t)
                have_f.add(t["file"])
                write_attr(done)
                net.emit("radio", n=len(done), target=a.target, title=t["title"][:50])
                say("song %d/%d: %s - %s" % (len(done), a.target, t["author"][:30], t["title"][:50]))
        except net.Fail as f:
            say("Internet Archive unreachable (%s)" % f)
    if len(done) >= a.target:
        say("done: %d songs" % len(done))
        return 0
    try:
        try:
            st = json.load(open(cache, encoding="utf-8"))
            titles, via, pos = st["titles"], st["via"], st.get("pos", 0)
            if time.time() - st.get("t", 0) > 30 * 86400 or st.get("v") != 2:
                raise ValueError("old")
            say("continuing with %d cached candidates (%d checked)" % (len(titles), pos))
        except Exception:  # noqa: BLE001 - no cache yet: search
            found, via = set(), {}
            say("looking for Macedonian audio on Wikimedia Commons ...")
            for n in artists():                       # songs by the artists in popular_singers.txt first
                before = set(found)
                search_files('"%s" filemime:audio' % n, found)
                for t in found - before:
                    via[t] = "artist"
            say("%d audio files by listed artists" % len(found))
            seen = set()
            for c in SEED_CATS:
                before = set(found)
                cat_files(c, 3, seen, found)
                for t in found - before:
                    via.setdefault(t, True)
            for q in SEARCHES:
                search_files(q, found)
            titles, pos = sorted(found, key=lambda t: (via.get(t) != "artist", t)), 0
            json.dump({"titles": titles, "via": via, "pos": 0, "t": time.time(), "v": 2}, open(cache, "w", encoding="utf-8"))
            say("%d candidate files, checking licences and downloading ..." % len(titles))
        for i in range(pos, len(titles), 40):
            if len(done) >= max(a.target, 1) + 40:
                break
            for title, ii in infos(titles[i:i + 40]):
                t = judge(title, ii, via.get(title, False), a.max_mb)
                if not t:
                    continue
                t["file"] = fname(t)
                if t["file"] in have_f:
                    continue
                if a.list:
                    print("%-9s %-18s %s" % (t["license"][:9], t["author"][:18], t["title"]))
                    continue
                dest = os.path.join(OUT, t["file"])
                try:
                    body = net.fetch(t["url"], "radio_dl", first_byte=40, stall=20, limit=240)
                except net.Fail as f:
                    say("skip %s (%s)" % (t["title"], f))
                    if f.kind == "offline":
                        raise
                    continue
                with open(dest + ".part", "wb") as fh:
                    fh.write(body)
                os.replace(dest + ".part", dest)
                done.append(t)
                have_f.add(t["file"])
                write_attr(done)
                net.emit("radio", n=len(done), target=a.target, title=t["title"][:50])
                say("track %d/%d: %s" % (len(done), a.target, t["title"][:60]))
            json.dump({"titles": titles, "via": via, "pos": i + 40, "t": time.time()}, open(cache, "w", encoding="utf-8"))
    except net.Fail as f:
        say("cannot reach Wikimedia Commons (%s) - radio keeps %d tracks; run again when online" % (f, len(done)))
        return 0
    print()
    write_attr(done)
    if len(done) >= a.target:
        say("done: %d tracks" % len(done))
    else:
        say("only %d freely licensed tracks exist/were reachable (target %d) - not padded" % (len(done), a.target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
