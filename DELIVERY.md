# Film Search — FINAL DELIVERY (FILM_SEARCH_GREEN)

## Provenance (scope discipline)

- Exhaustive 2026-09-02 recovery (`CINEAGENT_RECOVERY_SUMMARY.md`) proved **0 code
  sources** for CineAgent/CineAgent One/Semantic V4 across 3948 surfaces, 347 git
  repos, 1.3M zip entries, 118 GitHub repos — verdict `RECOVERY_ONLY` (20-cap spec)
  + `REBUILD_REQUIRED`. No writer owned the scope (no leases, no worktrees).
- This product is the authorized green-field rebuild (`family_cineagent_new`),
  implementing the 20 recovered caps + the operator's final acceptance, at the
  canonical taxonomy slot `F:\_dev-apps\10-PRODUCTS\film-search` (ONE_PRODUCT=ONE_REPO).
- Historical `need_providers` fixture blocker: fixed green-field — the test fixture
  natively supports `need_providers` (regression test `test_need_providers_fixture`).

## FINAL FLAGS

```
HEAD=0cd7802dd55164bdb5aabbf3dbb0189a82d1f3a4
SOURCES=local-catalog(62)+tvmaze-public+tmdb-optional-key
SEMANTIC_QUERY=FR/EN genres+moods+themes+year-range+country+age+type+rating+similar-to+negation+underrated+people
RANKING=multi-pass(lexical/semantic/second-hop/people/FTS5)+RRF(k=60)+MMR(λ=0.72)+quality-prior+liked-taste+explainable-reason
DEDUP=title|year-normalized cross-source merge (local first, poster/synopsis/sources merged)
POSTERS=tvmaze/tmdb-live-http else deterministic-SVG-dataURI (always present, UI onerror fallback)
METADATA=title/year/type/genres/moods/themes/country/age/cast/director/synopsis/rating/popularity/runtime/providers
FILTERS=genre/mood/type/country/year-min-max/min-rating/age/providers(need_providers)+explicit-country/year-from-query
HISTORY=jsonl-append + exposure-memory anti-repeat (penalty + dislike x2), restart-persistent
UI=single-file ui.html (search+filters+cards+reasons+detail-modal+similar+favorites+history+letterboxd-import)
TESTS=19-unittest-OK (semantic/ranking/dedupe/exclusion/need-providers/similar/underrated/antirepeat/filters/fts/acceptance-breadth/sources-cache/hermetic-live)
BUILD=OK (py_compile x7 + FTS5-memory warmup 30 hits + 19 tests, receipt data/build.json)
BENCHMARK=OK (15 queries, 0 hard-violations, 0 dups, irrelevant<=0.35, breadth>=30, TVMaze live smoke reachable, receipt data/benchmark.json)
RUNTIME=RUNTIME_PROOF_OK http://127.0.0.1:43147 (health/search-youth/providers-hardfilter/similar/detail/favorite/feedback/history/import/UI-compare-sources) + RESTART_PERSIST_OK (receipt data/runtime_proof.json)
FILM_SEARCH_GREEN=true
```

## Acceptance (12 queries, engine, ALL_ACCEPTANCE_OK, 47 uniques)

| # | Famille | Requête | n | Top3 |
|---|---|---|---|---|
| 1 | youth/teen drama | youth teen drama coming of age at school | 8 | Perks of Being a Wallflower, Lady Bird, Mid90s |
| 2 | startup/business | startup business entrepreneur tech silicon valley ambition | 8 | Silicon Valley, Social Network, Halt and Catch Fire |
| 3 | crime/thriller | crime thriller heist tension investigation | 8 | Money Heist, Se7en, Breaking Bad |
| 4 | melancholic | melancholic slow reflective sadness loneliness | 8 | Lost in Translation, Columbus, Manchester by the Sea |
| 5 | underrated | underrated hidden gems overlooked pepites méconnus | 8 | Halt and Catch Fire, Coherence, Eighth Grade |
| 6 | similar-title | similar to Breaking Bad | 8 | Godfather, Se7en, Dark (+anchor) |
| 7 | similar-title | similar to The Social Network | 8 | Big Short, Halt and Catch Fire (+anchor) |
| 8 | similar-title | similar to Parasite | 8 | Breaking Bad, Dark, Money Heist (+anchor) |
| 9 | country+year | French drama 2010s | 7 | Intouchables, Grave, Les Misérables |
| 10 | breadth | sci-fi mind-bending time travel | 8 | Dark, Dune Part Two, Interstellar |
| 11 | FR + public | comedie feel-good famille | 8 | Intouchables, Coco, Amelie |
| 12 | negation | melancholic drama without horror, sans violence | 8 | Broadchurch, Her, Perks of Being a Wallflower |

Contraintes vérifiées : pas de doublons intra-requête, poster+synopsis+cast+ranking_reason
sur chaque résultat, `need_providers=Netflix` sans fuite, anti-repeat pénalisé,
`france 2010s` 100% FR.

## Lancement / vérification

```bat
run.bat
:: http://127.0.0.1:43140  (FILM_SEARCH_PORT pour changer)
C:\Python314\python.exe -u -m unittest tests.test_film_search
C:\Python314\python.exe -u -c "import run_acceptance as ra; ra.main()"
```

## Notes d'environnement

- Host sous forte charge multi-sessions : les commits sqlite **fichier** calent de
  façon intermittente ici → FTS5 tourne sur `sqlite :memory:` (capacité réelle,
  prouvée `sqlite 3.50.4`, warmup 30 hits) et la persistance est en JSON atomique
  (`store.py`). Aucune dépendance externe, aucun build lourd.
- Live TVMaze prouvé joignable (200) et exercé par `/api/similar` en golden ;
  TMDB actif si `TMDB_API_KEY` défini, sinon skip propre.
