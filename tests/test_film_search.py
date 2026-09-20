"""Unit + acceptance tests (stdlib unittest). Fixture supports need_providers (historical blocker fix)."""
import json
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import film_search as engine
import providers as prov

CATALOG = prov.load_local()

# need_providers-capable fixture (regression for historical CineAgent blocker)
NEED_PROVIDERS_FIXTURE = [
    {"id": "a", "title": "Alpha Test", "year": 2020, "type": "movie", "genres": ["Drama"], "moods": ["melancholic"],
     "themes": ["family"], "country": "France", "country_code": "FR", "age": "Tous publics", "cast": ["Jane Doe"],
     "director": "John Smith", "synopsis": "A quiet test drama.", "rating": 8.0, "popularity": 30,
     "providers": ["Netflix"], "sources": ["local"]},
    {"id": "b", "title": "Beta Test", "year": 2021, "type": "series", "genres": ["Comedy"], "moods": ["uplifting"],
     "themes": ["friendship"], "country": "USA", "country_code": "US", "age": "12+", "cast": ["John Roe"],
     "director": "Jane Roe", "synopsis": "A loud test comedy.", "rating": 7.0, "popularity": 80,
     "providers": ["MUBI"], "sources": ["local"]},
]

ACCEPTANCE = [
    "youth teen drama coming of age at school",
    "startup business entrepreneur tech silicon valley",
    "crime thriller heist tension investigation",
    "melancholic slow reflective sadness loneliness",
    "underrated hidden gems overlooked pepites",
    "similar to Breaking Bad",
    "similar to The Social Network",
    "similar to Parasite",
    "French drama 2010s",
    "sci-fi mind-bending time travel",
    "comedie feel-good famille",
    "melancholic drama without horror, sans violence",
]


class TestFTS(unittest.TestCase):
    def test_fts_mem_ranks(self):
        ranks = prov.fts_mem_ranks("startup entrepreneur technology", CATALOG)
        self.assertTrue(len(ranks) >= 2, f"fts too narrow: {ranks}")
        ids = set(ranks)
        self.assertTrue("silicon-valley-2014" in ids or "social-network-2010" in ids)
        # empty/garbage query => fail-soft
        self.assertEqual(prov.fts_mem_ranks("", CATALOG), {})
        self.assertEqual(prov.fts_mem_ranks("zxqw", CATALOG), {})

    def test_fts_stats(self):
        info = prov.build_fts_stats(CATALOG)
        self.assertEqual(info["fts"], "sqlite-fts5-memory")
        self.assertGreaterEqual(info["count"], 60)
        self.assertGreaterEqual(info["warmup_hits"], 2)


class TestSemantic(unittest.TestCase):
    def test_genre_mood_theme(self):
        p = engine.parse_query("startup business entrepreneur tech")
        self.assertIn("business", p["genres"])
        self.assertIn("startup", p["themes"])
        p2 = engine.parse_query("melancholic slow reflective")
        self.assertIn("melancholic", p2["moods"])
        p3 = engine.parse_query("youth teen drama school")
        self.assertIn("coming-of-age", p3["genres"])
        self.assertIn("teen", p3["themes"])

    def test_similar_negation(self):
        p = engine.parse_query("similar to Parasite")
        self.assertTrue(p["similar_to"])
        p2 = engine.parse_query("melancholic drama without horror")
        self.assertIn("horror", p2["excluded_genres"] or p2["excluded"])
        p3 = engine.parse_query("crime thriller sans horreur")
        self.assertTrue(p3["excluded"])

    def test_year_country_age(self):
        p = engine.parse_query("French drama 2010s")
        self.assertIn("FR", p["countries"])
        self.assertEqual((p["year_min"], p["year_max"]), (2010, 2019))
        p2 = engine.parse_query("family feel-good kids")
        self.assertEqual(p2["age"], "family")


class TestRanking(unittest.TestCase):
    def test_search_returns_ranked_with_reasons(self):
        res = engine.search(CATALOG, "startup business entrepreneur", filters={}, exposure={}, top_n=8)
        self.assertGreaterEqual(len(res), 3)
        for r in res:
            self.assertIn("ranking_reason", r)
            self.assertTrue(r["ranking_reason"])
            self.assertIn("poster", r)
            self.assertTrue(r["poster"])
            self.assertIn("synopsis", r)
            self.assertTrue(r["synopsis"])
            self.assertIn("cast", r)

    def test_dedupe(self):
        dup = CATALOG + [dict(CATALOG[0])]
        res = engine.search(dup, "teen drama", filters={}, exposure={}, top_n=12)
        keys = [engine.norm_title_key(r["title"], r["year"]) for r in res]
        self.assertEqual(len(keys), len(set(keys)))

    def test_hard_exclusion(self):
        res = engine.search(CATALOG, "crime thriller", filters={}, exposure={}, top_n=12)
        # inject horror exclusion via query
        res2 = engine.search(CATALOG, "crime thriller without horror sans horreur", filters={}, exposure={}, top_n=12)
        for r in res2:
            self.assertNotIn("horror", [g.lower() for g in r.get("genres", [])])

    def test_need_providers_fixture(self):
        # historical blocker: fixture must accept need_providers
        res = engine.search(NEED_PROVIDERS_FIXTURE, "test drama", filters={"need_providers": ["Netflix"]}, exposure={}, top_n=5)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["id"], "a")
        res2 = engine.search(NEED_PROVIDERS_FIXTURE, "test", filters={"need_providers": ["MUBI"]}, exposure={}, top_n=5)
        self.assertEqual(res2[0]["id"], "b")
        res3 = engine.search(CATALOG, "drama", filters={"need_providers": ["Netflix"]}, exposure={}, top_n=8)
        for r in res3:
            self.assertIn("netflix", [p.lower() for p in r.get("providers", [])])

    def test_similar_second_hop(self):
        res = engine.search(CATALOG, "similar to Breaking Bad", filters={}, exposure={}, top_n=8)
        self.assertGreaterEqual(len(res), 3)
        titles = [r["title"] for r in res]
        # neighbors should include crime series
        self.assertTrue(any(t in titles for t in ["True Detective", "Dark", "Money Heist", "Breaking Bad", "Se7en"]))

    def test_underrated(self):
        res = engine.search(CATALOG, "underrated hidden gems", filters={}, exposure={}, top_n=8)
        self.assertGreaterEqual(len(res), 3)
        pops = [r["popularity"] for r in res]
        self.assertLess(sum(pops) / len(pops), 65)

    def test_antirepeat(self):
        first = engine.search(CATALOG, "teen drama", filters={}, exposure={}, top_n=6)
        exp = {first[0]["id"]: 3.0}
        second = engine.search(CATALOG, "teen drama", filters={}, exposure=exp, top_n=6)
        self.assertGreaterEqual(len(second), 3)
        # penalized item should drop or carry penalty reason
        ids2 = [r["id"] for r in second]
        if first[0]["id"] in ids2:
            r = [x for x in second if x["id"] == first[0]["id"]][0]
            self.assertIn("anti-repeat", r["ranking_reason"])

    def test_filters(self):
        res = engine.search(CATALOG, "drama", filters={"country_code": "FR", "year_min": 2010, "year_max": 2019}, exposure={}, top_n=10)
        for r in res:
            self.assertEqual(r["country_code"], "FR")
            self.assertTrue(2010 <= r["year"] <= 2019)


class TestAcceptance(unittest.TestCase):
    def test_all_queries_breadth(self):
        all_ids = set()
        per_query = {}
        for q in ACCEPTANCE:
            res = engine.search(CATALOG, q, filters={}, exposure={}, top_n=8)
            per_query[q] = len(res)
            self.assertGreaterEqual(len(res), 3, f"query too narrow: {q}")
            for r in res:
                all_ids.add(r["id"])
                self.assertTrue(r.get("poster"))
                self.assertTrue(r.get("synopsis"))
                self.assertTrue(r.get("ranking_reason"))
        self.assertGreaterEqual(len(ACCEPTANCE), 10)
        self.assertGreaterEqual(len(all_ids), 30, f"breadth too low: {len(all_ids)} unique")


class TestSourcesAndCache(unittest.TestCase):
    def test_source_url_legit_only(self):
        # local items: source_url "" or real TMDB link, never invented
        for it in CATALOG:
            url = prov.source_url_for(it)
            self.assertTrue(url == "" or url.startswith("https://www.themoviedb.org/"),
                            f"bad source_url {url} for {it.get('id')}")
        # tvmaze ids map to real TVMaze URLs
        self.assertEqual(prov.source_url_for({"id": "tvmaze-123", "type": "series"}),
                         "https://www.tvmaze.com/shows/123")
        self.assertEqual(prov.source_url_for({"id": "tmdb-456", "type": "movie"}),
                         "https://www.themoviedb.org/movie/456")

    def test_live_cache_roundtrip_failsoft(self):
        # save + load roundtrip in an ISOLATED tmp cache (never touches the
        # real data/live_cache.json).
        import tempfile
        tmpd = tempfile.TemporaryDirectory()
        try:
            orig = prov.LIVE_CACHE_PATH
            prov.LIVE_CACHE_PATH = os.path.join(tmpd.name, "live_cache.json")
            try:
                prov.save_live_cache("test-cache-roundtrip-xyz", [{"id": "x", "title": "X"}])
                data = prov.load_live_cache()
                self.assertIn("test-cache-roundtrip-xyz", data)
            finally:
                prov.LIVE_CACHE_PATH = orig
        finally:
            tmpd.cleanup()

    def test_tvmaze_failsoft_never_raises(self):
        # must return a list even offline (fail-soft), never raise.
        # Patched at the HTTP layer: no real network access in unit tests.
        orig = prov._http_json
        prov._http_json = lambda *a, **k: (_ for _ in ()).throw(OSError("offline-simulated"))
        try:
            res = prov.tvmaze_search("zxqw-heartstopper-unlikely-xyz", limit=3)
        finally:
            prov._http_json = orig
        self.assertIsInstance(res, list)

    def test_hard_violations_zero_on_gated_queries(self):
        gated = [
            ("French drama 2010s", {}, "FR", (2010, 2019)),
            ("teen drama", {"type": "series"}, None, None),
            ("drama", {"need_providers": ["Netflix"]}, None, None),
        ]
        for q, filters, cc, yrs in gated:
            res = engine.search(CATALOG, q, filters=filters, exposure={}, top_n=8)
            self.assertGreaterEqual(len(res), 2, f"too narrow: {q} {filters}")
            for r in res:
                if cc:
                    self.assertEqual(r.get("country_code"), cc, f"{q}: {r}")
                if yrs:
                    self.assertTrue(yrs[0] <= r["year"] <= yrs[1], f"{q}: {r}")
                if filters.get("type"):
                    self.assertEqual(r.get("type"), filters["type"])
                if filters.get("need_providers"):
                    have = set(p.lower() for p in r.get("providers", []))
                    self.assertTrue(have & {"netflix"})

    def test_no_duplicate_ids_in_results(self):
        for q in ["youth teen drama", "crime thriller", "sci-fi time travel", "teen drama"]:
            res = engine.search(CATALOG, q, filters={}, exposure={}, top_n=8)
            keys = [engine.norm_title_key(r["title"], r["year"]) for r in res]
            self.assertEqual(len(keys), len(set(keys)), f"duplicates for {q}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
