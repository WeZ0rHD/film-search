"""Film search HTTP server (stdlib only). Real runtime + restart persistence."""
import json
import os
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import film_search as engine
import providers as prov
import store

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
PORT = int(os.environ.get("FILM_SEARCH_PORT", "43140"))

LOCAL = prov.load_local()
BY_ID = {it["id"]: it for it in LOCAL}
LIVE_CACHE = {}
# Bound the in-process live cache: detail lookup falls back to disk-cached
# metadata (DISK_CACHE) when an id has been evicted (see /api/detail).
LIVE_CACHE_MAX = 400
# Stable-metadata disk cache for live enrichment (survives restart, TTL 7d).
# In-memory LIVE_CACHE stays authoritative for /api/detail in this process;
# disk cache lets offline/restared runs reuse last good live metadata.
DISK_CACHE = prov.load_live_cache()


def get_exposure():
    exp = store.get_exposure()
    return {k: float(v.get("cnt", 0.0)) if isinstance(v, dict) else float(v) for k, v in exp.items()}


def bump_exposure(ids):
    store.bump_exposure(ids)


def liked_signatures():
    favs = store.get_favorites()
    fb = store.get_feedback()
    liked_ids = set([f["id"] for f in favs] + [k for k, v in fb.items()
                                                   if isinstance(v, dict) and v.get("value", 0) > 0])
    genres, themes = set(), set()
    for lid in liked_ids:
        it = BY_ID.get(lid) or LIVE_CACHE.get(lid)
        if it:
            genres.update(x.lower() for x in it.get("genres", []))
            themes.update(x.lower() for x in it.get("themes", []))
    return genres, themes


def do_search(query, filters, limit=12, use_live=True):
    exposure = get_exposure()
    pool = list(LOCAL)
    live = []
    live_from = "none"
    if use_live and query and len(query.strip()) >= 2:
        key = re.sub(r"\s+", " ", query.lower()).strip()[:80]
        cached = DISK_CACHE.get(key)
        if cached and isinstance(cached, dict) and cached.get("items"):
            live = cached["items"]
            live_from = "disk-cache"
        else:
            try:
                live = prov.live_enrich(query)
            except Exception:
                live = []
            live_from = "live" if live else "live-empty"
            if live:
                try:
                    prov.save_live_cache(query, live)
                    DISK_CACHE[key] = {"ts": time.time(), "items": live}
                except Exception:
                    pass
    for it in live:
        LIVE_CACHE[it["id"]] = it
    while len(LIVE_CACHE) > LIVE_CACHE_MAX:
        LIVE_CACHE.pop(next(iter(LIVE_CACHE)))
    merged = pool + live
    # dedupe merged by title|year BEFORE search (keep local first, merge sources)
    seen = {}
    for it in merged:
        key = engine.norm_title_key(it.get("title", ""), it.get("year", ""))
        if key not in seen:
            seen[key] = dict(it)
            seen[key]["sources"] = list(it.get("sources", ["local"]))
            if not seen[key].get("source_url"):
                try:
                    seen[key]["source_url"] = prov.source_url_for(it)
                except Exception:
                    seen[key]["source_url"] = ""
        else:
            prev = seen[key]
            srcs = set(prev.get("sources", [])) | set(it.get("sources", []))
            prev["sources"] = sorted(srcs)
            if it.get("poster") and not prev.get("poster"):
                prev["poster"] = it["poster"]
            if it.get("source_url") and not prev.get("source_url"):
                prev["source_url"] = it["source_url"]
            if it.get("synopsis") and len(it.get("synopsis", "")) < len(prev.get("synopsis", "")):
                pass
            elif it.get("synopsis"):
                prev["synopsis"] = it["synopsis"]
    # FTS pre-filter signal: if query matches FTS titles, boost handled by engine lexical anyway
    results = engine.search(list(seen.values()), query, filters=filters, exposure=exposure, top_n=limit)
    # preference boost from favorites/feedback
    lg, lt = liked_signatures()
    if lg or lt:
        for r in results:
            g = set(x.lower() for x in r.get("genres", []))
            th = set(x.lower() for x in r.get("themes", []))
            bonus = 0.4 * len(g & lg) + 0.3 * len(th & lt)
            if bonus > 0:
                r["_score"] = round(r.get("_score", 0) + bonus, 3)
                r["ranking_reason"] = (r.get("ranking_reason", "") + f"; liked taste +{bonus:.1f}").strip("; ")
        results.sort(key=lambda r: -r.get("_score", 0))
    bump_exposure([r.get("id") for r in results[:6] if r.get("id")])
    # guarantee source_url on every result (legit links only, "" when none)
    for r in results:
        if not r.get("source_url"):
            try:
                r["source_url"] = prov.source_url_for(r)
            except Exception:
                r["source_url"] = ""
    # log history (JSONL, survives restart)
    store.log_search(query, filters, [r.get("id") for r in results])
    return results


class Handler(BaseHTTPRequestHandler):
    server_version = "film-search/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, (bytes, bytearray)) else (json.dumps(obj, ensure_ascii=False).encode("utf-8") if ctype == "application/json" else obj)
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "text" in ctype or "json" in ctype else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _num(raw, kind, default=None):
        """Parse an optional numeric query param. Returns (ok, value)."""
        if raw in (None, ""):
            return True, default
        try:
            return True, kind(raw)
        except (TypeError, ValueError):
            return False, default

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        qs = urllib.parse.parse_qs(u.query)
        g = lambda k, d="": qs.get(k, [d])[0]
        if path in ("/", "/index.html", "/ui.html"):
            with open(os.path.join(BASE, "ui.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if path == "/api/health":
            return self._send(200, {"ok": True, "local": len(LOCAL), "port": PORT, "tvmaze": "public",
                                    "tmdb": bool(os.environ.get("TMDB_API_KEY")),
                                    "fts": "sqlite-fts5-memory", "store": "json",
                                    "live_disk_cache": len(DISK_CACHE)})
        if path == "/api/search":
            filters = {}
            if g("genre"): filters["genre"] = g("genre")
            if g("type"): filters["type"] = g("type")
            if g("country_code"): filters["country_code"] = g("country_code")
            if g("age"): filters["age"] = g("age")
            if g("mood"): filters["mood"] = g("mood")
            ok, v = self._num(g("year_min"), int)
            if not ok:
                return self._send(400, {"error": "invalid year_min"})
            if v is not None:
                filters["year_min"] = v
            ok, v = self._num(g("year_max"), int)
            if not ok:
                return self._send(400, {"error": "invalid year_max"})
            if v is not None:
                filters["year_max"] = v
            ok, v = self._num(g("min_rating"), float)
            if not ok:
                return self._send(400, {"error": "invalid min_rating"})
            if v is not None:
                filters["min_rating"] = v
            if g("providers"):
                filters["need_providers"] = [p.strip() for p in g("providers").split(",") if p.strip()]
            ok, limit = self._num(g("limit", "12") or "12", int, 12)
            if not ok or limit < 1:
                return self._send(400, {"error": "invalid limit"})
            use_live = g("live", "1") != "0"
            results = do_search(g("q", ""), filters, limit=min(limit, 24), use_live=use_live)
            return self._send(200, {"query": g("q", ""), "filters": filters, "count": len(results), "results": results,
                                    "sources": {"local": len(LOCAL), "live_cached": len(LIVE_CACHE),
                                                "live_disk_cache": len(DISK_CACHE)}})
        if path == "/api/similar":
            title = g("title", "")
            ok, slim = self._num(g("limit", "12") or "12", int, 12)
            if not ok or slim < 1:
                return self._send(400, {"error": "invalid limit"})
            results = do_search(f"similar to {title}", {}, limit=min(slim, 24), use_live=True)
            # drop exact anchor if first
            return self._send(200, {"title": title, "count": len(results), "results": results})
        if path == "/api/detail":
            _id = g("id", "")
            it = BY_ID.get(_id) or LIVE_CACHE.get(_id)
            if not it:
                # evicted from the bounded in-process cache? fall back to
                # disk-cached live metadata before giving up.
                for entry in DISK_CACHE.values():
                    if not isinstance(entry, dict):
                        continue
                    for cand in (entry.get("items") or []):
                        if isinstance(cand, dict) and cand.get("id") == _id:
                            it = cand
                            break
                    if it:
                        break
            if not it:
                return self._send(404, {"error": "not found"})
            d = dict(it)
            d["poster"] = engine.poster_for(d)
            if not d.get("source_url"):
                try:
                    d["source_url"] = prov.source_url_for(d)
                except Exception:
                    d["source_url"] = ""
            # second hop neighbors
            neigh = engine.search(list(BY_ID.values()), f"similar to {d.get('title','')}", filters={}, exposure={}, top_n=6)
            d["similar"] = [{"id": n.get("id"), "title": n.get("title"), "year": n.get("year"), "poster": n.get("poster")} for n in neigh if n.get("id") != d.get("id")][:5]
            return self._send(200, d)
        if path == "/api/history":
            return self._send(200, {"history": store.get_history(int(g("limit", "20") or 20))})
        if path == "/api/favorites":
            return self._send(200, {"favorites": store.get_favorites()})
        return self._send(404, {"error": "unknown route"})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {}
        if u.path == "/api/favorites":
            _id = data.get("id", "")
            if not _id:
                return self._send(400, {"error": "id required"})
            action = data.get("action", "toggle")
            it = BY_ID.get(_id) or LIVE_CACHE.get(_id)
            if action == "remove" or (action == "toggle" and store.is_favorite(_id)):
                store.remove_favorite(_id)
                return self._send(200, {"favorited": False})
            title = data.get("title") or (it.get("title") if it else _id)
            year = data.get("year") or (it.get("year") if it else 0)
            poster = data.get("poster") or (engine.poster_for(it) if it else "")
            store.set_favorite(_id, title, year, poster)
            return self._send(200, {"favorited": True})
        if u.path == "/api/feedback":
            _id = data.get("id", "")
            if not _id:
                return self._send(400, {"error": "id required"})
            value = int(data.get("value", 1))
            store.set_feedback(_id, value)
            # dislike => stronger exposure penalty next time
            if value < 0:
                store.add_exposure(_id, 2.0)
            return self._send(200, {"ok": True})
        if u.path == "/api/import":
            text = data.get("text", "") or ""
            # Letterboxd CSV (Date,Name,Year,Letterboxd URI,Rating) or plain lines or URLs
            found = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                m = re.search(r"letterboxd\.com/.*/film/([^/]+)/?", line)
                slug = m.group(1).replace("-", " ") if m else None
                title, year = None, None
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) >= 3 and re.match(r"^\d{4}$", parts[1] if len(parts) > 1 else ""):
                    title, year = parts[0], parts[1]
                elif slug:
                    title = slug
                else:
                    mm = re.match(r"(.+?)\s*\((\d{4})\)", line)
                    if mm:
                        title, year = mm.group(1), mm.group(2)
                    else:
                        title = line
                # resolve locally
                res = engine.search(list(BY_ID.values()), title or "", filters={}, exposure={}, top_n=3)
                if res:
                    best = res[0]
                    found.append({"input": line, "matched_id": best["id"], "title": best["title"], "year": best["year"]})
            # auto-add matches to favorites
            for f in found:
                it = BY_ID.get(f["matched_id"])
                if it:
                    if not store.is_favorite(it["id"]):
                        store.set_favorite(it["id"], it["title"], it["year"], engine.poster_for(it))
            return self._send(200, {"matched": found, "count": len(found)})
        return self._send(404, {"error": "unknown route"})


def main():
    info = prov.build_fts_stats()
    print(f"film-search on http://127.0.0.1:{PORT} fts={info}", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    srv.serve_forever()


if __name__ == "__main__":
    main()
