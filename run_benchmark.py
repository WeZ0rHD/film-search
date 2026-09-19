"""Benchmark: curated diverse requests incl. recent youth/teen drama.
Measures hard-constraint violations, duplicate rate, irrelevant rate.
Local engine (offline-capable) + optional live TVMaze smoke. Writes data/benchmark.json.
"""
import os
import sys
import json
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import film_search as engine
import providers as prov

QUERIES = [
    {"label": "youth/teen drama", "query": "youth teen drama coming of age at school", "filters": {}, "min_n": 5},
    {"label": "recent youth/teen drama", "query": "recent teen drama high school 2020s heartfelt", "filters": {}, "min_n": 3},
    {"label": "recent youth heartwarming", "query": "heartwarming teen series friendship 2022", "filters": {"type": "series"}, "min_n": 3},
    {"label": "startup/business", "query": "startup business entrepreneur tech silicon valley ambition", "filters": {}, "min_n": 5},
    {"label": "crime/thriller", "query": "crime thriller heist tension investigation", "filters": {}, "min_n": 5},
    {"label": "melancholic", "query": "melancholic slow reflective sadness loneliness", "filters": {}, "min_n": 5},
    {"label": "underrated gems", "query": "underrated hidden gems overlooked", "filters": {}, "min_n": 3},
    {"label": "similar Breaking Bad", "query": "similar to Breaking Bad", "filters": {}, "min_n": 3},
    {"label": "similar Parasite", "query": "similar to Parasite", "filters": {}, "min_n": 3},
    {"label": "france 2010s hard", "query": "French drama 2010s", "filters": {}, "min_n": 3,
     "expect": {"country_code": "FR", "year_min": 2010, "year_max": 2019}},
    {"label": "sci-fi breadth", "query": "sci-fi mind-bending time travel", "filters": {}, "min_n": 5},
    {"label": "family feel-good", "query": "comedie feel-good famille", "filters": {"age": "family"}, "min_n": 3,
     "expect": {"age": "family"}},
    {"label": "negation no-horror", "query": "melancholic drama without horror, sans violence", "filters": {}, "min_n": 3,
     "expect": {"exclude_genre": "horror"}},
    {"label": "providers Netflix", "query": "drama", "filters": {"need_providers": ["Netflix"]}, "min_n": 2,
     "expect": {"need_providers": ["netflix"]}},
    {"label": "series only", "query": "teen drama", "filters": {"type": "series"}, "min_n": 3,
     "expect": {"type": "series"}},
]


def check_hard(it, parsed, filters, expect):
    """Return list of violation strings (empty = respects hard constraints)."""
    v = []
    f = dict(filters or {})
    if expect:
        for k, val in expect.items():
            if k == "country_code" and it.get("country_code") != val:
                v.append(f"country {it.get('country_code')} != {val}")
            if k == "year_min" and int(it.get("year", 0)) < int(val):
                v.append(f"year {it.get('year')} < min {val}")
            if k == "year_max" and int(it.get("year", 0)) > int(val):
                v.append(f"year {it.get('year')} > max {val}")
            if k == "type" and it.get("type") != val:
                v.append(f"type {it.get('type')} != {val}")
            if k == "exclude_genre" and val in [g.lower() for g in it.get("genres", [])]:
                v.append(f"excluded genre {val} present")
            if k == "need_providers":
                have = set(p.lower() for p in it.get("providers", []))
                if not (have & set(val)):
                    v.append(f"providers {it.get('providers')} lack {val}")
            if k == "age" and val == "family" and it.get("age") not in ("Tous publics", "10+"):
                v.append(f"age {it.get('age')} not family-safe")
    # explicit UI filters are hard too
    if f.get("country_code") and it.get("country_code") != f["country_code"]:
        v.append(f"filter country {it.get('country_code')} != {f['country_code']}")
    if f.get("type") and it.get("type") != f["type"]:
        v.append(f"filter type {it.get('type')} != {f['type']}")
    if f.get("year_min") is not None and int(it.get("year", 0)) < int(f["year_min"]):
        v.append(f"filter year_min violated {it.get('year')}")
    if f.get("year_max") is not None and int(it.get("year", 0)) > int(f["year_max"]):
        v.append(f"filter year_max violated {it.get('year')}")
    if f.get("need_providers"):
        have = set(p.lower() for p in it.get("providers", []))
        want = set(p.lower() for p in f["need_providers"])
        if not (have & want):
            v.append("filter need_providers violated")
    # parsed hard constraints enforced by engine: year range + explicit country
    if parsed.get("year_min") is not None and parsed.get("year_max") is not None:
        if not (parsed["year_min"] <= int(it.get("year", 0)) <= parsed["year_max"]):
            v.append(f"parsed year range violated {it.get('year')}")
    return v


def is_irrelevant(it, parsed, tokens):
    """Heuristic: shares no signal with query -> possibly irrelevant.
    Skipped for similar-to and empty-concept queries (second-hop decides)."""
    if parsed.get("similar_to"):
        return False
    if not (parsed.get("genres") or parsed.get("moods") or parsed.get("themes")) and not tokens:
        return False
    g = set(x.lower() for x in it.get("genres", []))
    m = set(x.lower() for x in it.get("moods", []))
    th = set(x.lower() for x in it.get("themes", []))
    want = set(parsed.get("genres", [])) | set(parsed.get("moods", [])) | set(parsed.get("themes", []))
    have = g | m | th
    if want & have:
        return False
    blob = engine.item_text_blob(it)
    for t in tokens:
        if len(t) >= 4 and t in blob:
            return False
    return True


def main():
    t0 = time.time()
    catalog = prov.load_local()
    per_query = []
    all_ids = set()
    tot_results = 0
    tot_violations = 0
    tot_dup_keys = 0
    tot_irrelevant = 0
    tot_missing_meta = 0
    fails = []
    for q in QUERIES:
        query, filters = q["query"], q.get("filters", {})
        parsed = engine.parse_query(query)
        tokens = [t for t in engine.tokenize(query) if len(t) >= 3 and t not in engine.STOPWORDS]
        res = engine.search(catalog, query, filters=filters, exposure={}, top_n=8)
        keys = [engine.norm_title_key(r["title"], r["year"]) for r in res]
        dups = len(keys) - len(set(keys))
        viols, irrel, missing = [], 0, []
        for r in res:
            all_ids.add(r.get("id"))
            v = check_hard(r, parsed, filters, q.get("expect"))
            if v:
                viols.append({"title": r.get("title"), "violations": v})
            if is_irrelevant(r, parsed, tokens):
                irrel += 1
            for field in ("poster", "synopsis", "cast", "ranking_reason", "rating", "year", "genres"):
                if field not in r or r[field] in (None, "", []):
                    missing.append(f"{r.get('title')}: missing {field}")
        tot_results += len(res)
        tot_violations += len(viols)
        tot_dup_keys += dups
        tot_irrelevant += irrel
        tot_missing_meta += len(missing)
        row = {"label": q["label"], "query": query, "filters": filters, "n": len(res),
               "top3": [(r["title"], r["year"], r["_score"]) for r in res[:3]],
               "duplicates": dups, "violations": viols, "irrelevant": irrel,
               "missing_meta": missing[:4]}
        per_query.append(row)
        print(f"[{q['label']}] n={len(res)} dups={dups} viol={len(viols)} irrel={irrel} "
              f"top3={[t[0] for t in row['top3']]}")
        if len(res) < q.get("min_n", 3):
            fails.append(f"{q['label']}: too narrow n={len(res)} < {q.get('min_n')}")
        if dups:
            fails.append(f"{q['label']}: {dups} duplicates")
        if viols:
            fails.append(f"{q['label']}: {len(viols)} hard-constraint violations {viols[:2]}")
        if missing:
            fails.append(f"{q['label']}: {len(missing)} missing metadata")
    breadth = len(all_ids)
    print(f"unique_total={breadth} total_results={tot_results}")
    if breadth < 30:
        fails.append(f"breadth too low: {breadth} < 30")
    irr_rate = (tot_irrelevant / tot_results) if tot_results else 1.0
    print(f"irrelevant={tot_irrelevant}/{tot_results} rate={irr_rate:.2f}")
    if irr_rate > 0.35:
        fails.append(f"irrelevant rate too high: {irr_rate:.2f} > 0.35")
    if tot_violations:
        fails.append(f"total hard violations {tot_violations} > 0")
    # live smoke: TVMaze public, fail-soft but reported
    smoke = {"tvmaze_reachable": False, "results": 0, "cached_write": False, "note": ""}
    try:
        live = prov.tvmaze_search("Heartstopper", limit=5)
        smoke["tvmaze_reachable"] = True
        smoke["results"] = len(live)
        titles = [x.get("title", "") for x in live]
        smoke["titles"] = titles[:5]
        if not live:
            smoke["note"] = "reachable but 0 results (API changed or offline shape)"
        try:
            prov.save_live_cache("benchmark-smoke-heartstopper", live)
            smoke["cached_write"] = True
        except Exception as e:
            smoke["note"] = f"cache write failed: {e}"
        print(f"live smoke TVMaze Heartstopper: {titles}")
    except Exception as e:
        smoke["note"] = f"TVMaze unreachable: {e}"
        print(f"live smoke FAILED: {e}")
    ok = not fails
    print("FAILURES:" if fails else "BENCHMARK_OK")
    for f in fails:
        print(" - " + f)
    out = {"catalog_n": len(catalog), "n_queries": len(QUERIES), "queries": per_query,
           "unique_total": breadth, "total_results": tot_results,
           "hard_violations": tot_violations, "duplicates": tot_dup_keys,
           "irrelevant": tot_irrelevant, "irrelevant_rate": round(irr_rate, 3),
           "live_smoke": smoke, "failures": fails, "ok": ok,
           "seconds": round(time.time() - t0, 1)}
    with open(os.path.join(BASE, "data", "benchmark.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
