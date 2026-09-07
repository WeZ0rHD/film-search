"""Providers: local catalog + SQLite FTS5 + TVMaze (public, no key) + TMDB (optional key).
Legitimate/public sources only. All live calls time out fast and fail soft offline.
"""
import json
import os
import re
import sqlite3
import html
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(BASE, "data", "catalog.json")
CATALOG_DB = os.path.join(BASE, "data", "film_catalog.sqlite")

TVMAZE_SEARCH = "https://api.tvmaze.com/search/shows?q={q}"
TVMAZE_CAST = "https://api.tvmaze.com/shows/{sid}/cast"


def load_local():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        items = json.load(f)
    for it in items:
        it.setdefault("sources", ["local"])
    return items


def build_catalog_db(items=None):
    items = items or load_local()
    tmp = CATALOG_DB + ".build"
    for stale in (tmp, tmp + "-journal", CATALOG_DB + "-journal"):
        try:
            if os.path.exists(stale):
                os.remove(stale)
        except OSError:
            pass
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except OSError:
        pass
    con = sqlite3.connect(tmp, timeout=5.0)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("PRAGMA synchronous=NORMAL")
        cur = con.cursor()
        cur.execute("CREATE TABLE catalog(id TEXT PRIMARY KEY, title TEXT, year INT, type TEXT, genres TEXT, moods TEXT, themes TEXT, country TEXT, cc TEXT, age TEXT, cast TEXT, director TEXT, synopsis TEXT, rating REAL, popularity REAL, providers TEXT, body TEXT)")
        fts_ok = True
        try:
            cur.execute("CREATE VIRTUAL TABLE catalog_fts USING fts5(title, body)")
        except sqlite3.OperationalError:
            fts_ok = False
        rows = []
        fts_rows = []
        for it in items:
            body = " ".join([it.get("title", ""), it.get("synopsis", ""), " ".join(it.get("genres", [])), " ".join(it.get("moods", [])), " ".join(it.get("themes", [])), " ".join(it.get("cast", [])), it.get("director", ""), it.get("country", "")])
            rows.append((
                it.get("id"), it.get("title"), int(it.get("year", 0)), it.get("type"), " ".join(it.get("genres", [])),
                " ".join(it.get("moods", [])), " ".join(it.get("themes", [])), it.get("country"), it.get("country_code"),
                it.get("age"), " ".join(it.get("cast", [])), it.get("director"), it.get("synopsis"),
                float(it.get("rating", 0)), float(it.get("popularity", 0)), " ".join(it.get("providers", [])), body))
            if fts_ok:
                fts_rows.append((it.get("title"), body))
        cur.executemany("INSERT OR REPLACE INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        if fts_ok:
            cur.executemany("INSERT INTO catalog_fts(title, body) VALUES (?,?)", fts_rows)
        con.commit()
    finally:
        con.close()
    # atomic swap: build tmp then replace (never leaves hot journal on canonical name)
    try:
        if os.path.exists(CATALOG_DB):
            os.remove(CATALOG_DB)
    except OSError:
        pass
    os.replace(tmp, CATALOG_DB)
    return {"db": CATALOG_DB, "fts": fts_ok, "count": len(items)}


def fts_search(query, limit=30):
    if not os.path.exists(CATALOG_DB):
        build_catalog_db()
    con = sqlite3.connect(CATALOG_DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    # sanitize FTS query: keep alnum words
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 2][:8]
    if not words:
        con.close()
        return []
    out = []
    try:
        q = " OR ".join(words)
        rows = cur.execute("SELECT title FROM catalog_fts WHERE catalog_fts MATCH ? LIMIT ?", (q, limit)).fetchall()
        titles = [r["title"] for r in rows]
        for t in titles:
            r = cur.execute("SELECT * FROM catalog WHERE title=?", (t,)).fetchone()
            if r:
                out.append(dict(r))
    except sqlite3.OperationalError:
        # fallback LIKE
        like = "%" + "%".join(words[:3]) + "%"
        rows = cur.execute("SELECT * FROM catalog WHERE body LIKE ? LIMIT ?", (like, limit)).fetchall()
        out = [dict(r) for r in rows]
    con.close()
    return out


def _http_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "film-search/1.0 (+local product)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    return html.unescape(s).strip()


def tvmaze_search(query, limit=10):
    """Public TVMaze API, no key. Returns series-mapped items. Fail-soft offline."""
    try:
        data = _http_json(TVMAZE_SEARCH.format(q=urllib.parse.quote(query[:80])), timeout=6)
    except Exception:
        return []
    out = []
    for entry in (data or [])[:limit]:
        sh = entry.get("show", {})
        title = sh.get("name") or ""
        premiered = sh.get("premiered") or ""
        try:
            year = int(premiered[:4]) if premiered else 0
        except ValueError:
            year = 0
        img = (sh.get("image") or {})
        rating = ((sh.get("rating") or {}).get("average")) or 0
        out.append({
            "id": f"tvmaze-{sh.get('id')}",
            "title": title,
            "year": year or 2000,
            "type": "series",
            "genres": sh.get("genres") or ["Drama"],
            "moods": [],
            "themes": [],
            "country": ((sh.get("network") or {}).get("country") or {}).get("name") or ((sh.get("webChannel") or {}).get("country") or {}).get("name") or "",
            "country_code": ((sh.get("network") or {}).get("country") or {}).get("code") or "",
            "age": "12+",
            "cast": [],
            "director": "",
            "synopsis": strip_html(sh.get("summary"))[:600],
            "rating": float(rating) if rating else 7.0,
            "popularity": 60.0,
            "runtime_min": sh.get("runtime") or 45,
            "providers": [],
            "poster": img.get("original") or img.get("medium") or "",
            "sources": ["tvmaze"],
            "language": sh.get("language") or "en",
        })
    return out


def tmdb_search(query, limit=10):
    """TMDB when TMDB_API_KEY env is set (legitimate, user key). Otherwise []."""
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        return []
    try:
        url = "https://api.themoviedb.org/3/search/multi?api_key=" + urllib.parse.quote(key) + "&query=" + urllib.parse.quote(query[:80]) + "&include_adult=false"
        data = _http_json(url, timeout=6)
    except Exception:
        return []
    out = []
    for r in (data.get("results") or [])[:limit]:
        mt = r.get("media_type", "")
        title = r.get("title") or r.get("name") or ""
        date = r.get("release_date") or r.get("first_air_date") or ""
        try:
            year = int(date[:4])
        except ValueError:
            year = 0
        poster = ("https://image.tmdb.org/t/p/w500" + r["poster_path"]) if r.get("poster_path") else ""
        out.append({
            "id": f"tmdb-{r.get('id')}",
            "title": title,
            "year": year or 2000,
            "type": "series" if mt == "tv" else "movie",
            "genres": [],
            "moods": [],
            "themes": [],
            "country": "",
            "country_code": "",
            "age": "12+",
            "cast": [],
            "director": "",
            "synopsis": (r.get("overview") or "")[:600],
            "rating": float(r.get("vote_average") or 0),
            "popularity": min(99.0, float(r.get("popularity") or 0)),
            "runtime_min": 0,
            "providers": [],
            "poster": poster,
            "sources": ["tmdb"],
            "language": r.get("original_language") or "",
        })
    return out


def live_enrich(query):
    """Combine live sources deduped by title|year. Never raises."""
    seen = {}
    for src in (tvmaze_search(query), tmdb_search(query)):
        for it in src:
            key = (re.sub(r"\s+", " ", (it.get("title") or "").lower()).strip(), it.get("year"))
            if key not in seen:
                seen[key] = it
    return list(seen.values())
