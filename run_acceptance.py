"""Acceptance runner: >=10 queries incl. youth/teen, startup, crime, melancholic, underrated, similar-titles."""
import os
import sys
import json

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import film_search as engine
import providers as prov

QUERIES = [
    ("youth/teen drama", "youth teen drama coming of age at school"),
    ("startup/business", "startup business entrepreneur tech silicon valley ambition"),
    ("crime/thriller", "crime thriller heist tension investigation"),
    ("melancholic", "melancholic slow reflective sadness loneliness"),
    ("underrated", "underrated hidden gems overlooked pepites méconnus"),
    ("similar Breaking Bad", "similar to Breaking Bad"),
    ("similar Social Network", "similar to The Social Network"),
    ("similar Parasite", "similar to Parasite"),
    ("france 2010s", "French drama 2010s"),
    ("sci-fi breadth", "sci-fi mind-bending time travel"),
    ("FR feel-good", "comedie feel-good famille"),
    ("negation", "melancholic drama without horror, sans violence"),
]

REQUIRED_LABELS = ["youth/teen drama", "startup/business", "crime/thriller", "melancholic", "underrated"]


def main():
    catalog = prov.load_local()
    print(f"catalog={len(catalog)}")
    all_ids = set()
    per_label = {}
    fails = []
    for label, q in QUERIES:
        res = engine.search(catalog, q, filters={}, exposure={}, top_n=8)
        per_label[label] = {"query": q, "count": len(res), "top3": [(r["title"], r["year"], r["_score"]) for r in res[:3]]}
        print(f"[{label}] n={len(res)} top3={per_label[label]['top3']}")
        for r in res:
            all_ids.add(r["id"])
            for field in ("poster", "synopsis", "cast", "ranking_reason", "rating", "year", "genres"):
                if field not in r or r[field] in (None, "", []):
                    fails.append(f"{label}: missing {field} in {r.get('title')}")
        keys = [engine.norm_title_key(r["title"], r["year"]) for r in res]
        if len(keys) != len(set(keys)):
            fails.append(f"{label}: duplicates inside results")
        if len(res) < 3:
            fails.append(f"{label}: too narrow ({len(res)})")
    for req in REQUIRED_LABELS:
        if req not in per_label or per_label[req]["count"] < 3:
            fails.append(f"required family missing/narrow: {req}")
    similar_ok = all(per_label[k]["count"] >= 3 for k in per_label if k.startswith("similar"))
    if not similar_ok:
        fails.append("similar-title queries too narrow")
    breadth = len(all_ids)
    print(f"unique_total={breadth}")
    if breadth < 30:
        fails.append(f"breadth too low: {breadth} < 30")
    # posters/metadata spot check
    posters = sum(1 for _ in all_ids)
    ok = not fails
    print("FAILURES:" if fails else "ALL_ACCEPTANCE_OK")
    for f in fails:
        print(" - " + f)
    out = {"queries": per_label, "unique_total": breadth, "failures": fails, "ok": ok, "n_queries": len(QUERIES)}
    with open(os.path.join(BASE, "data", "acceptance.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
