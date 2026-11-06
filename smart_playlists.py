"""Smart playlists: a name, some rules ("artist is Mora", "listened to more than 10 times", "added in the last 30 days"…), an order and a
limit. They are worked out again every time they are looked at, from what the songs are, so they never go stale and nothing is copied.
Three come ready (`BUILTIN`); the user's own are kept in a small file of their own."""
import json
import math
import os
import random
import tempfile
import uuid

from apis.youtube import normalize

DAY = 86400
MAX_RULES = 12
MAX_LIMIT = 500
FIELDS = {"artist": "text", "album": "text", "title": "text", "liked": "bool",
          "duration_min": "number", "added_days": "number", "plays": "number", "last_played_days": "number"}
OPS = {"text": ("contains", "not_contains", "is"), "number": ("gt", "lt", "eq"), "bool": ("is",)}
SORTS = ("recent", "oldest", "plays", "title", "artist", "random")
KIND_RANK = {"album": 0, "playlist": 1, "track": 2, "liked": 3, "other": 4}

BUILTIN = [
    {"id": "recent", "name": "Recién añadidas", "match": "all", "rules": [{"field": "added_days", "op": "lt", "value": 30}], "sort": "recent", "limit": 50},
    {"id": "top", "name": "Más escuchadas", "match": "all", "rules": [{"field": "plays", "op": "gt", "value": 0}], "sort": "plays", "limit": 50},
    {"id": "forgotten", "name": "Olvidadas", "match": "all", "sort": "oldest", "limit": 50,
     "rules": [{"field": "added_days", "op": "gt", "value": 30}, {"field": "last_played_days", "op": "gt", "value": 90}]},
]


class SmartError(ValueError):
    """What the user wrote is not a smart playlist; the message says why, in Spanish, for the window."""


def clean(defn):
    """The definition with only what belongs in it, or SmartError."""
    if not isinstance(defn, dict):
        raise SmartError("Esa playlist inteligente no es válida.")
    name = defn.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise SmartError("Ponle un nombre de hasta 80 letras.")
    if defn.get("match") not in ("all", "any"):
        raise SmartError("Elige si deben cumplirse todas las reglas o cualquiera.")
    if defn.get("sort") not in SORTS:
        raise SmartError("Ese orden no existe.")
    limit = defn.get("limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= MAX_LIMIT:
        raise SmartError(f"El límite debe estar entre 0 (sin límite) y {MAX_LIMIT}.")
    rules = defn.get("rules")
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise SmartError(f"Una playlist inteligente admite hasta {MAX_RULES} reglas.")
    return {"name": name.strip(), "match": defn["match"], "rules": [_clean_rule(r) for r in rules], "sort": defn["sort"], "limit": limit}


def _clean_rule(rule):
    if not isinstance(rule, dict) or rule.get("field") not in FIELDS:
        raise SmartError("Una de las reglas no es válida.")
    field, kind = rule["field"], FIELDS[rule["field"]]
    if rule.get("op") not in OPS[kind]:
        raise SmartError("Una de las reglas tiene una condición que no corresponde a ese campo.")
    value = rule.get("value")
    if kind == "text":
        if not isinstance(value, str) or not normalize(value) or len(value.strip()) > 100:
            raise SmartError("Una de las reglas de texto está vacía.")
        value = value.strip()
    elif kind == "number":
        try:
            if isinstance(value, bool):
                raise ValueError
            value = float(value)
        except (TypeError, ValueError):
            raise SmartError("Una de las reglas necesita un número.") from None
        if not math.isfinite(value) or not 0 <= value <= 100000:
            raise SmartError("Una de las reglas tiene un número fuera de rango.")
    elif not isinstance(value, bool):
        raise SmartError("Una de las reglas necesita sí o no.")
    return {"field": field, "op": rule["op"], "value": value}


def _passes(rule, item, facts):
    field, op, value = rule["field"], rule["op"], rule["value"]
    if field in ("artist", "album", "title"):
        have, want = normalize(item.get(field)), normalize(value)
        return want in have if op == "contains" else want not in have if op == "not_contains" else have == want
    have = facts[field]
    if field == "liked":
        return have is value
    return have > value if op == "gt" else have < value if op == "lt" else have == value


def evaluate(defn, items, liked_ids, counts, now, rng=random):
    """The ids of the songs that fit, in the order asked. `counts` is {(artist, title): (listens, when last)} from the statistics."""
    picked, seen = [], {}
    for item in items:
        identity = (normalize(item.get("artist")), normalize(item.get("title")))
        if identity[0] and identity[1]:
            kept = seen.get(identity)
            if kept is not None:                                  # the same song as another file: keep the album copy
                if KIND_RANK.get(item.get("kind"), 4) < KIND_RANK.get(picked[kept][0].get("kind"), 4):
                    picked[kept] = (item, identity)
                continue
            seen[identity] = len(picked)
        picked.append((item, identity))
    rows = []
    for item, identity in picked:
        plays, last = counts.get(identity, (0, None))
        facts = {"liked": item["id"] in liked_ids, "duration_min": (item.get("duration") or 0) / 60,
                 "added_days": max(0, (now - (item.get("added") or now)) / DAY), "plays": plays,
                 "last_played_days": math.inf if last is None else max(0, (now - last) / DAY)}
        checks = [_passes(r, item, facts) for r in defn["rules"]]
        if not checks or (all(checks) if defn["match"] == "all" else any(checks)):
            rows.append((item, plays))
    sort = defn["sort"]
    if sort == "recent":
        rows.sort(key=lambda r: -(r[0].get("added") or 0))
    elif sort == "oldest":
        rows.sort(key=lambda r: r[0].get("added") or 0)
    elif sort == "plays":
        rows.sort(key=lambda r: (-r[1], -(r[0].get("added") or 0)))
    elif sort in ("title", "artist"):
        rows.sort(key=lambda r: (normalize(r[0].get(sort)), normalize(r[0].get("title"))))
    else:
        rng.shuffle(rows)
    ids = [r[0]["id"] for r in rows]
    return ids[:defn["limit"]] if defn["limit"] else ids


class SmartStore:
    def __init__(self, path):
        self.path = path
        self._lists, self._bad, self._locked = [], False, False
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            lists = data.get("lists") if isinstance(data, dict) else None
            if not isinstance(lists, list):
                raise ValueError
            for entry in lists:
                if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                    try:
                        self._lists.append({"id": entry["id"], **clean(entry)})
                    except SmartError:
                        continue      # one damaged list does not take the others with it
        except FileNotFoundError:
            pass
        except ValueError:
            self._bad = True          # kept aside as .bad the first time something is saved
        except OSError:
            self._locked = True       # exists but cannot be read now: do not write over it

    def all(self):
        return [dict(d, rules=[dict(r) for r in d["rules"]]) for d in self._lists]

    def save(self, defn, sid=None):
        """Creates (or, with `sid`, replaces) a smart playlist; answers its id."""
        fixed = clean(defn)
        if sid is not None and not any(d["id"] == sid for d in self._lists):
            raise SmartError("Esa playlist inteligente ya no existe.")
        before = list(self._lists)
        if sid is None:
            sid = uuid.uuid4().hex[:8]
            self._lists.append({"id": sid, **fixed})
        else:
            self._lists = [{"id": sid, **fixed} if d["id"] == sid else d for d in self._lists]
        try:
            self._write()
        except SmartError:
            self._lists = before
            raise
        return sid

    def delete(self, sid):
        if not any(d["id"] == sid for d in self._lists):
            return False
        before = list(self._lists)
        self._lists = [d for d in self._lists if d["id"] != sid]
        try:
            self._write()
        except SmartError:
            self._lists = before
            raise
        return True

    def _write(self):
        if self._locked:
            raise SmartError("No pude leer el archivo de tus playlists inteligentes, así que no lo cambio.")
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            if self._bad:
                os.replace(self.path, self.path + ".bad")
                self._bad = False
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"lists": self._lists}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            raise SmartError("No pude guardar la playlist inteligente.") from None
