"""Film search HTTP server (stdlib only). Real runtime + restart persistence."""
import json
import os
import re
import sqlite3
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import film_search as engine
import providers as prov

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
APP_DB = os.path.join(DATA, "film_app.sqlite")
PORT = int(os.environ.get("FILM_SEARCH_PORT", "43140"))

LOCAL = prov.load_local()
BY_ID = {it["id"]: it for it in LOCAL}
LIVE_CACHE = {}


def db():
    os.makedirs(DATA, exist_ok=True)
    con = sqlite3.connect(APP_DB, timeout=10.0)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    con.execute("CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, query TEXT, filters TEXT, result_ids TEXT, cnt INT)")
    con.execute("CREATE TABLE IF NOT EXISTS favorites(id TEXT PRIMARY KEY, title TEXT, year INT, poster TEXT, added_ts REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY, value INT, ts REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS exposure(item_id TEXT PRIMARY KEY, cnt REAL, last_ts REAL)")
    con.commit()
    return con


def get_exposure():
    con = db()
    try:
        rows = con.execute("SELECT item_id, cnt FROM exposure").fetchall()
        return {r["item_id"]: float(r["cnt"]) for r in rows}
    finally:
        con.close()


def bump_exposure(ids):
    con = db()
    try:
        now = time.time()
        for i in ids:
            row = con.execute("SELECT cnt FROM exposure WHERE item_id=?", (i,)).fetchone()
            if row:
                con.execute("UPDATE exposure SET cnt=cnt+1, last_ts=? WHERE item_id=?", (now, i))
            else:
                con.execute("INSERT INTO exposure(item_id, cnt, last_ts) VALUES (?,?,?)", (i, 1.0, now))
        con.commit()
    finally:
        con.close()


def liked_signatures():
    con = db()
    try:
        favs = con.execute("SELECT id FROM favorites").fetchall()
        fb = con.execute("SELECT id FROM feedback WHERE value>0").fetchall()
        liked_ids = set([r["id"] for r in favs] + [r["id"] for r in fb])
    finally:
        con.close()
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
    if use_live and query and len(query.strip()) >= 2:
        try:
            live = prov.live_enrich(query)
        except Exception:
            live = []
    for it in live:
        LIVE_CACHE[it["id"]] = it
    merged = pool + live
    # dedupe merged by title|year BEFORE search (keep local first, merge sources)
    seen = {}
    for it in merged:
        key = engine.norm_title_key(it.get("title", ""), it.get("year", ""))
        if key not in seen:
            seen[key] = dict(it)
            seen[key]["sources"] = list(it.get("sources", ["local"]))
        else:
            prev = seen[key]
            srcs = set(prev.get("sources", [])) | set(it.get("sources", []))
            prev["sources"] = sorted(srcs)
            if it.get("poster") and not prev.get("poster"):
                prev["poster"] = it["poster"]
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
    # log history
    con = db()
    try:
        con.execute("INSERT INTO history(ts, query, filters, result_ids, cnt) VALUES (?,?,?,?,?)",
                    (time.time(), query, json.dumps(filters, ensure_ascii=False), json.dumps([r.get("id") for r in results], ensure_ascii=False), len(results)))
        con.commit()
    finally:
        con.close()
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

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        qs = urllib.parse.parse_qs(u.query)
        g = lambda k, d="": qs.get(k, [d])[0]
        if path in ("/", "/index.html", "/ui.html"):
            with open(os.path.join(BASE, "ui.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if path == "/api/health":
            return self._send(200, {"ok": True, "local": len(LOCAL), "port": PORT, "tvmaze": "public", "tmdb": bool(os.environ.get("TMDB_API_KEY"))})
        if path == "/api/search":
            filters = {}
            if g("genre"): filters["genre"] = g("genre")
            if g("type"): filters["type"] = g("type")
            if g("country_code"): filters["country_code"] = g("country_code")
            if g("age"): filters["age"] = g("age")
            if g("mood"): filters["mood"] = g("mood")
            if g("year_min"): filters["year_min"] = int(g("year_min"))
            if g("year_max"): filters["year_max"] = int(g("year_max"))
            if g("min_rating"): filters["min_rating"] = float(g("min_rating"))
            if g("providers"):
                filters["need_providers"] = [p.strip() for p in g("providers").split(",") if p.strip()]
            limit = int(g("limit", "12") or 12)
            use_live = g("live", "1") != "0"
            results = do_search(g("q", ""), filters, limit=min(limit, 24), use_live=use_live)
            return self._send(200, {"query": g("q", ""), "filters": filters, "count": len(results), "results": results,
                                    "sources": {"local": len(LOCAL), "live_cached": len(LIVE_CACHE)}})
        if path == "/api/similar":
            title = g("title", "")
            results = do_search(f"similar to {title}", {}, limit=int(g("limit", "12") or 12), use_live=True)
            # drop exact anchor if first
            return self._send(200, {"title": title, "count": len(results), "results": results})
        if path == "/api/detail":
            _id = g("id", "")
            it = BY_ID.get(_id) or LIVE_CACHE.get(_id)
            if not it:
                return self._send(404, {"error": "not found"})
            d = dict(it)
            d["poster"] = engine.poster_for(d)
            # second hop neighbors
            neigh = engine.search(list(BY_ID.values()), f"similar to {d.get('title','')}", filters={}, exposure={}, top_n=6)
            d["similar"] = [{"id": n.get("id"), "title": n.get("title"), "year": n.get("year"), "poster": n.get("poster")} for n in neigh if n.get("id") != d.get("id")][:5]
            return self._send(200, d)
        if path == "/api/history":
            con = db()
            try:
                rows = con.execute("SELECT ts, query, cnt FROM history ORDER BY id DESC LIMIT ?", (int(g("limit", "20") or 20),)).fetchall()
                return self._send(200, {"history": [dict(r) for r in rows]})
            finally:
                con.close()
        if path == "/api/favorites":
            con = db()
            try:
                rows = con.execute("SELECT id, title, year, poster, added_ts FROM favorites ORDER BY added_ts DESC").fetchall()
                return self._send(200, {"favorites": [dict(r) for r in rows]})
            finally:
                con.close()
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
            action = data.get("action", "toggle")
            it = BY_ID.get(_id) or LIVE_CACHE.get(_id)
            con = db()
            try:
                exists = con.execute("SELECT id FROM favorites WHERE id=?", (_id,)).fetchone()
                if action == "remove" or (action == "toggle" and exists):
                    con.execute("DELETE FROM favorites WHERE id=?", (_id,))
                    con.commit()
                    return self._send(200, {"favorited": False})
                title = data.get("title") or (it.get("title") if it else _id)
                year = data.get("year") or (it.get("year") if it else 0)
                poster = data.get("poster") or (engine.poster_for(it) if it else "")
                con.execute("INSERT OR REPLACE INTO favorites(id,title,year,poster,added_ts) VALUES (?,?,?,?,?)", (_id, title, year, poster, time.time()))
                con.commit()
                return self._send(200, {"favorited": True})
            finally:
                con.close()
        if u.path == "/api/feedback":
            _id = data.get("id", "")
            value = int(data.get("value", 1))
            con = db()
            try:
                con.execute("INSERT OR REPLACE INTO feedback(id,value,ts) VALUES (?,?,?)", (_id, value, time.time()))
                # dislike => stronger exposure penalty next time
                if value < 0:
                    con.execute("INSERT INTO exposure(item_id,cnt,last_ts) VALUES (?,?,?) ON CONFLICT(item_id) DO UPDATE SET cnt=cnt+2", (_id, 2.0, time.time()))
                con.commit()
                return self._send(200, {"ok": True})
            finally:
                con.close()
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
            con = db()
            try:
                for f in found:
                    it = BY_ID.get(f["matched_id"])
                    if it:
                        con.execute("INSERT OR IGNORE INTO favorites(id,title,year,poster,added_ts) VALUES (?,?,?,?,?)",
                                    (it["id"], it["title"], it["year"], engine.poster_for(it), time.time()))
                con.commit()
            finally:
                con.close()
            return self._send(200, {"matched": found, "count": len(found)})
        return self._send(404, {"error": "unknown route"})


def main():
    prov.build_catalog_db()
    db()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"film-search on http://127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
