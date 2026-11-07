"""Player profile for multiplayer: a stable id, the chosen username and lifetime stats (profile.json next to run.bat)."""
import json
import os
import re
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "profile.json")
STATS = ("games", "minutes", "kills", "deaths", "money", "score")


def clean(name):
    """Visible letters/digits/space/_-. only, at most 16 characters."""
    return re.sub(r"[^\w .\-]", "", name or "", flags=re.UNICODE).strip()[:16]


class Profile:
    def __init__(self, path=PATH):
        self.path = path
        self.uid, self.name, self.stats = uuid.uuid4().hex[:12], "", {k: 0 for k in STATS}
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.uid = str(d.get("uid", self.uid))[:12]
            self.name = clean(d.get("name", ""))
            for k in STATS:
                self.stats[k] = int(d.get("stats", {}).get(k, 0))
        except Exception:  # noqa: BLE001 - first start or unreadable file
            pass

    def save(self):
        try:
            with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"uid": self.uid, "name": self.name, "stats": self.stats}, f, indent=1, ensure_ascii=False)
            os.replace(self.path + ".tmp", self.path)
        except Exception:  # noqa: BLE001
            pass

    def add(self, **kw):
        for k, v in kw.items():
            if k in self.stats:
                self.stats[k] += int(v)
        self.save()
