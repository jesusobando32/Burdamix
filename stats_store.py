"""Listening statistics. Every listen is one line appended to a file of its own (`[when, artist, title, album, seconds]`), so the file is
never rewritten and a crash cannot damage what was already there. Everything stays on this computer. A listen counts when the song was
heard for 30 seconds or half of it (the player decides that; here it is only recorded)."""
import json
import math
import os
import threading
import time
from datetime import date, datetime, timedelta

from apis.youtube import normalize

TOP = 10
MAX_SECONDS = 7200            # one listen longer than two hours is a mistake, not a song
PERIOD_DAYS = {"week": 7, "month": 30, "year": 365}
WEEKDAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


class Stats:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self._lock = threading.Lock()

    # --- the file ------------------------------------------------------------------------------------------------

    def record(self, artist, title, album, seconds, ts=None):
        """One more listen. False when the numbers make no sense or the file cannot be written."""
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 < seconds <= MAX_SECONDS:
            return False
        line = json.dumps([float(ts if ts is not None else self.clock()), self._text(artist), self._text(title), self._text(album), round(float(seconds), 1)],
                          ensure_ascii=False)
        try:
            with self._lock:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            return True
        except OSError:
            return False

    @staticmethod
    def _text(value):
        return value.strip()[:200] if isinstance(value, str) else ""

    def _events(self):
        events = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        ts, artist, title, album, seconds = json.loads(line)
                        events.append((float(ts), str(artist), str(title), str(album), float(seconds)))
                    except (ValueError, TypeError):
                        continue   # a half-written or foreign line: the rest still counts
        except OSError:
            pass
        return events

    # --- what the screens ask ----------------------------------------------------------------------------------------

    def counts(self):
        """{(artist, title): (listens, when it was last heard)} with both names normalised: what the smart playlists use."""
        found = {}
        for ts, artist, title, _, _ in self._events():
            key = (normalize(artist), normalize(title))
            if key[0] and key[1]:
                plays, last = found.get(key, (0, 0))
                found[key] = (plays + 1, max(last, ts))
        return found

    def summary(self, period="all"):
        now = self.clock()
        everything = self._events()
        days = PERIOD_DAYS.get(period)
        events = [e for e in everything if days is None or e[0] >= now - days * 86400]
        songs, artists, albums = {}, {}, {}
        for _, artist, title, album, seconds in events:
            a, t, al = normalize(artist), normalize(title), normalize(album)
            if a and t:
                s = songs.setdefault((a, t), {"artist": artist, "title": title, "album": album, "plays": 0, "seconds": 0.0})
                s["plays"] += 1; s["seconds"] += seconds; s["album"] = album or s["album"]
            if a:
                r = artists.setdefault(a, {"artist": artist, "plays": 0, "seconds": 0.0})
                r["plays"] += 1; r["seconds"] += seconds
            if a and al:
                b = albums.setdefault((a, al), {"artist": artist, "album": album, "plays": 0, "seconds": 0.0})
                b["plays"] += 1; b["seconds"] += seconds
        return {
            "period": period if days else "all",
            "plays": len(events),
            "seconds": round(sum(e[4] for e in events)),
            "songs": self._top(songs, "title"), "artists": self._top(artists, "artist"), "albums": self._top(albums, "album"),
            "series": self._series(events, period, now),
            "streak": self._streak({datetime.fromtimestamp(e[0]).date() for e in everything}, now),
        }

    @staticmethod
    def _top(table, name):
        ranked = sorted(table.values(), key=lambda r: (-r["plays"], -r["seconds"], r[name].lower()))[:TOP]
        return [{**r, "seconds": round(r["seconds"])} for r in ranked]

    @staticmethod
    def _streak(played_days, now):
        today = datetime.fromtimestamp(now).date()
        day = today if today in played_days else today - timedelta(days=1)
        count = 0
        while day in played_days:
            count += 1
            day -= timedelta(days=1)
        return count

    @staticmethod
    def _series(events, period, now):
        """The bars of the chart, oldest first: one per day (a week, a month) or per month (a year, everything), with the minutes heard."""
        today = datetime.fromtimestamp(now).date()
        if period in ("week", "month"):
            n = PERIOD_DAYS[period]
            slots = [today - timedelta(days=n - 1 - i) for i in range(n)]
            key = lambda d: d                                                      # noqa: E731
            bar = lambda d: {"date": d.isoformat(), "label": WEEKDAYS[d.weekday()] if period == "week" else str(d.day)}   # noqa: E731
        else:
            first = min((datetime.fromtimestamp(e[0]).date() for e in events), default=today)
            span = 12 if period == "year" else min(24, max(1, (today.year - first.year) * 12 + today.month - first.month + 1))
            slots = []
            y, m = today.year, today.month
            for _ in range(span):
                slots.append(date(y, m, 1))
                y, m = (y, m - 1) if m > 1 else (y - 1, 12)
            slots.reverse()
            if period == "all" and not events:
                return []
            key = lambda d: date(d.year, d.month, 1)                               # noqa: E731
            bar = lambda d: {"date": d.strftime("%Y-%m"), "label": MONTHS[d.month - 1]}   # noqa: E731
        minutes = {slot: 0.0 for slot in slots}
        for ts, _, _, _, seconds in events:
            slot = key(datetime.fromtimestamp(ts).date())
            if slot in minutes:
                minutes[slot] += seconds / 60
        return [{**bar(slot), "minutes": round(minutes[slot], 1)} for slot in slots]
