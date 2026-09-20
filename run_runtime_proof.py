"""Runtime proof: spawn server subprocess on proof port, run golden journey,
verify restart persistence, terminate owned subprocess. Writes data/runtime_proof.json.
Stdlib only. Bounded: fails fast, never hangs.
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("FILM_SEARCH_PROOF_PORT", "43147"))
ROOT = f"http://127.0.0.1:{PORT}"


def wait_health(proc, timeout_s=25):
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout_s:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early code={proc.returncode}")
        try:
            req = urllib.request.Request(ROOT + "/api/health", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = str(e)
            time.sleep(1.0)
    raise RuntimeError(f"server not healthy after {timeout_s}s: {last}")


def get(path, params=None):
    url = ROOT + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, obj):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(ROOT + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    env = dict(os.environ)
    env["FILM_SEARCH_PORT"] = str(PORT)
    proc = subprocess.Popen([sys.executable, "-u", os.path.join(BASE, "server.py")],
                             cwd=BASE, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    proof = {"port": PORT, "steps": [], "ok": False}
    try:
        health = wait_health(proc)
        assert health.get("ok") and health.get("local", 0) >= 60, f"bad health {health}"
        proof["steps"].append(f"health ok local={health['local']}")
        s1 = get("/api/search", {"q": "youth teen drama coming of age at school", "limit": 8, "live": 0})
        assert s1["count"] >= 5, "youth narrow"
        assert len({(r["title"], r["year"]) for r in s1["results"]}) == len(s1["results"]), "dups"
        for r in s1["results"]:
            assert r.get("poster") and r.get("synopsis") and r.get("ranking_reason"), f"meta {r.get('title')}"
            assert r.get("_sources"), f"sources missing {r.get('title')}"
        proof["steps"].append(f"youth n={s1['count']} top={[r['title'] for r in s1['results'][:3]]}")
        s2 = get("/api/search", {"q": "melancholic drama", "providers": "Netflix", "limit": 8, "live": 0})
        assert s2["count"] >= 1
        for r in s2["results"]:
            assert "netflix" in [p.lower() for p in r.get("providers", [])], f"leak {r['title']}"
        proof["steps"].append(f"providers n={s2['count']}")
        s3 = get("/api/similar", {"title": "Parasite", "limit": 6})
        assert s3["count"] >= 3
        proof["steps"].append(f"similar n={s3['count']}")
        fid = s1["results"][0]["id"]
        assert post("/api/favorites", {"id": fid, "action": "add"}).get("favorited") is True
        assert post("/api/feedback", {"id": fid, "value": 1}).get("ok") is True
        det = get("/api/detail", {"id": fid})
        assert det.get("synopsis") and det.get("poster") and len(det.get("similar", [])) >= 1
        proof["steps"].append(f"detail {det['title']} similar={len(det.get('similar', []))}")
        hist = get("/api/history", {"limit": 5})
        assert len(hist.get("history", [])) >= 3, "history missing"
        favs = get("/api/favorites")
        assert any(f["id"] == fid for f in favs.get("favorites", [])), "favorite missing"
        imp = post("/api/import", {"text": "The Godfather,1972\nParasite,2019"})
        assert imp.get("count", 0) >= 1
        req = urllib.request.Request(ROOT + "/", headers={"Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read()
        assert b"Film Search" in html and b"Comparer" in html and b"source" in html.lower(), "UI missing compare/sources"
        proof["steps"].append("ui ok (compare+sources)")
        # restart persistence: stop, restart, history+favorites must survive (JSON store)
        proc.terminate()
        proc.wait(timeout=15)
        proc2 = subprocess.Popen([sys.executable, "-u", os.path.join(BASE, "server.py")],
                                 cwd=BASE, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        proc = proc2
        h2 = wait_health(proc)
        assert h2.get("ok")
        hist2 = get("/api/history", {"limit": 5})
        favs2 = get("/api/favorites")
        assert len(hist2.get("history", [])) >= 3, "history not restart-persistent"
        assert any(f["id"] == fid for f in favs2.get("favorites", [])), "favorite not restart-persistent"
        proof["steps"].append("restart-persist ok")
        proof["ok"] = True
    except Exception as e:
        # Record the failure in the receipt instead of dying without one,
        # then let cleanup run and propagate the failure via exit code.
        proof["ok"] = False
        proof["error"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    with open(os.path.join(BASE, "data", "runtime_proof.json"), "w", encoding="utf-8") as f:
        json.dump(proof, f, ensure_ascii=False, indent=1)
    print("RUNTIME_PROOF_" + ("OK" if proof.get("ok") else "FAIL"))
    for s in proof["steps"]:
        print(" - " + s)
    return 0 if proof.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
