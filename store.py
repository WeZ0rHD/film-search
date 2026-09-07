"""JSON file persistence (atomic tmp+replace, thread-locked).
Chosen over sqlite files: this host intermittently stalls sqlite file commits
under load; small JSON docs with direct writes are proven reliable here.
Restart persistence: plain files under data/ survive restarts.
"""
import json
import os
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
_LOCK = threading.Lock()


def _path(name):
    os.makedirs(DATA, exist_ok=True)
    return os.path.join(DATA, name)


def load(name, default):
    p = _path(name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, obj):
    p = _path(name)
    tmp = p + ".tmp"
    with _LOCK:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
            os.replace(tmp, p)
        except OSError:
            # fallback: direct write (proven primitive on this host)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            with open(p, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)


# ---- history (append JSONL) ----
def log_search(query, filters, result_ids):
    with _LOCK:
        try:
            with open(_path("history.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "query": query, "filters": filters,
                                    "result_ids": result_ids, "cnt": len(result_ids)}, ensure_ascii=False) + "\n")
        except OSError:
            pass


def get_history(limit=20):
    rows = []
    try:
        with open(_path("history.jsonl"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows[-limit:][::-1]


# ---- favorites ----
def get_favorites():
    fav = load("favorites.json", {})
    return sorted(fav.values(), key=lambda x: -x.get("added_ts", 0))


def is_favorite(_id):
    return _id in load("favorites.json", {})


def set_favorite(_id, title, year, poster):
    fav = load("favorites.json", {})
    fav[_id] = {"id": _id, "title": title, "year": year, "poster": poster, "added_ts": time.time()}
    save("favorites.json", fav)


def remove_favorite(_id):
    fav = load("favorites.json", {})
    if _id in fav:
        del fav[_id]
        save("favorites.json", fav)


# ---- feedback ----
def get_feedback():
    return load("feedback.json", {})


def set_feedback(_id, value):
    fb = load("feedback.json", {})
    fb[_id] = {"value": int(value), "ts": time.time()}
    save("feedback.json", fb)


# ---- exposure (anti-repeat memory) ----
def get_exposure():
    return load("exposure.json", {})


def bump_exposure(ids):
    if not ids:
        return
    exp = load("exposure.json", {})
    now = time.time()
    for i in ids:
        e = exp.get(i, {"cnt": 0.0})
        e["cnt"] = float(e.get("cnt", 0.0)) + 1.0
        e["last_ts"] = now
        exp[i] = e
    save("exposure.json", exp)


def add_exposure(_id, amount):
    exp = load("exposure.json", {})
    e = exp.get(_id, {"cnt": 0.0})
    e["cnt"] = float(e.get("cnt", 0.0)) + float(amount)
    e["last_ts"] = time.time()
    exp[_id] = e
    save("exposure.json", exp)
