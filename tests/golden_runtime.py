"""Golden journey against a running server. Writes data/golden.json. Stdlib only."""
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("FILM_SEARCH_PORT", "43140"))
ROOT = f"http://127.0.0.1:{PORT}"


def get(path, params=None):
    url = ROOT + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        ct = r.headers.get("Content-Type", "")
        body = r.read()
    if "json" in ct:
        return json.loads(body.decode("utf-8"))
    return body


def post(path, obj):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(ROOT + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ev = {}
    ev["health"] = get("/api/health")
    assert ev["health"].get("ok"), "health not ok"
    s1 = get("/api/search", {"q": "startup business entrepreneur tech", "limit": 8, "live": 0})
    ev["search_startup"] = {"count": s1["count"], "top3": [(r["title"], r["year"]) for r in s1["results"][:3]]}
    assert s1["count"] >= 3, "startup narrow"
    for r in s1["results"]:
        assert r.get("poster") and r.get("synopsis") and r.get("ranking_reason") and r.get("cast") is not None
    keys = [(r["title"], r["year"]) for r in s1["results"]]
    assert len(keys) == len(set(keys)), "duplicates in search"
    s2 = get("/api/search", {"q": "melancholic drama", "providers": "Netflix", "limit": 8, "live": 0})
    ev["search_providers"] = {"count": s2["count"], "top3": [(r["title"], r["year"]) for r in s2["results"][:3]]}
    assert s2["count"] >= 1
    for r in s2["results"]:
        assert "netflix" in [p.lower() for p in r.get("providers", [])], f"need_providers leak: {r['title']}"
    s3 = get("/api/similar", {"title": "Parasite", "limit": 6})
    ev["similar"] = {"count": s3["count"], "titles": [(r["title"], r["year"]) for r in s3["results"]]}
    assert s3["count"] >= 3
    first_id = s1["results"][0]["id"]
    ev["favorited"] = post("/api/favorites", {"id": first_id, "action": "add"})
    assert ev["favorited"].get("favorited") is True
    ev["feedback"] = post("/api/feedback", {"id": first_id, "value": 1})
    det = get("/api/detail", {"id": first_id})
    ev["detail"] = {"title": det["title"], "similar_n": len(det.get("similar", []))}
    assert det.get("synopsis") and det.get("poster")
    ev["history"] = get("/api/history", {"limit": 5})
    assert len(ev["history"].get("history", [])) >= 3, "history missing"
    ev["favorites"] = get("/api/favorites")
    assert any(f["id"] == first_id for f in ev["favorites"].get("favorites", [])), "favorite missing"
    ev["import"] = post("/api/import", {"text": "The Godfather,1972\nParasite,2019"})
    assert ev["import"].get("count", 0) >= 1
    # UI served?
    html = get("/")
    assert b"Film Search" in html, "UI missing"
    ev["ui_ok"] = True
    with open(os.path.join(BASE, "data", "golden.json"), "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1)
    print("GOLDEN_OK " + json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != "results"}) for k, v in ev.items()}, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
