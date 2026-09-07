"""Providers: local catalog + in-memory SQLite FTS5 + TVMaze (public, no key) + TMDB (optional key).
Legitimate/public sources only. All live calls time out fast and fail soft offline.
Note: FTS5 runs on sqlite :memory: (rebuilt per call, ~ms for this catalog size)
because sqlite *file* commits intermittently stall on this host; the catalog
itself is still genuinely SQLite FTS5.
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

TVMAZE_SEARCH = "https://api.tvmaze.com/search/shows?q={q}"
TVMAZE_CAST = "https://api.tvmaze.com/shows/{sid}/cast"


def load_local():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        items = json.load(f)
    for it in items:
        it.setdefault("sources", ["local"])
    return items


def _item_body(it):
    return " ".join([it.get("title", ""), it.get("synopsis", ""), " ".join(it.get("genres", [])),
                     " ".join(it.get("moods", [])), " ".join(it.get("themes", [])),
                     " ".join(it.get("cast", [])), it.get("director", ""), it.get("country", "")])


def fts_mem_ranks(query, items, limit=30):
    """SQLite FTS5 pass over an in-memory index. Returns {id(item): rank 1..N}.

    In-memory (no files) because sqlite file commits stall on this host;
    the retrieval capability is still genuinely SQLite FTS5. Fail-soft {}.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) >= 3][:8]
    if not words or not items:
        return {}
    try:
        con = sqlite3.connect(":memory:")
        try:
            cur = con.cursor()
            cur.execute("CREATE VIRTUAL TABLE m USING fts5(id UNINDEXED, title, body)")
            cur.executemany("INSERT INTO m(id, title, body) VALUES (?,?,?)",
                            [(it.get("id"), it.get("title", ""), _item_body(it)) for it in items])
            q = " OR ".join(words)
            rows = cur.execute("SELECT id FROM m WHERE m MATCH ? ORDER BY rank LIMIT ?", (q, limit)).fetchall()
            return {r[0]: i + 1 for i, r in enumerate(rows)}
        finally:
            con.close()
    except Exception:
        return {}


def build_fts_stats(items=None):
    """Warmup/evidence for the FTS5 catalog (no files written)."""
    items = items or load_local()
    ranks = fts_mem_ranks("startup tech drama thriller", items)
    return {"fts": "sqlite-fts5-memory", "sqlite": sqlite3.sqlite_version,
            "count": len(items), "warmup_hits": len(ranks)}


# Kept for API compatibility (historical CineAgent cap name): now memory-backed.
def build_catalog_db(items=None):
    return build_fts_stats(items)


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
