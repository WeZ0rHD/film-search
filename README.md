# Film Search — découverte agentique films/séries

Recherche en langage naturel (FR/EN) avec fusion multi-passes, ranking explicable,
déduplication, anti-répétition, découverte second-hop, filtres, historique, favoris,
import Letterboxd. Sources légitimes/publiques uniquement.

## Lancement

```bat
run.bat
:: ou
set FILM_SEARCH_PORT=43140 && python server.py
```

Ouvrir `http://127.0.0.1:43140`.

## Sources

- `data/catalog.json` — catalogue local curé (62 titres, métadonnées résumées de
  sources publiques). Toujours disponible, même hors-ligne.
- TVMaze `https://api.tvmaze.com` — public, sans clé (séries). Enrichissement live.
- TMDB `https://api.themoviedb.org/3` — optionnel, si `TMDB_API_KEY` est défini.
  Sans clé, le produit reste complet sur catalogue local + TVMaze.

## Moteur (`film_search.py`, stdlib uniquement)

- `parse_query` : genres, humeurs, thèmes, année/plage, pays, public, type,
  note min, `similar to X`, exclusions (`sans/not/without/sauf/no`), `underrated`.
- Passes : lexicale, sémantique, second-hop similar-title, personnes
  (cast/réalisateur). Fusion RRF (k=60).
- Diversité MMR (λ=0.72), mémoire d'exposition anti-repeat, filtres durs
  (dont `need_providers`), dédupe titre+année, raison de ranking par résultat.
- `poster_for` : image live si disponible, sinon placeholder SVG déterministe.
- `run_benchmark.py` : 15 requêtes curées (dont 2 jeunesse récente), mesure
  violations de contraintes dures, doublons, taux non-pertinent, smoke TVMaze
  live → `data/benchmark.json`.
- `run_runtime_proof.py` : preuve runtime réelle (health, youth, providers,
  similar, detail, favoris/feedback/historique/import, UI comparer+sources,
  restart-persist) → `data/runtime_proof.json`.

## Données / honnêteté

- Disponibilités catalogue (`providers`) : snapshot indicatif, **à vérifier** —
  jamais inventées comme temps réel. UI libellée en ce sens.
- `source_url` : liens légitimes uniquement (TVMaze/TMDB quand un ID existe,
  sinon vide). Pas de faux liens streaming/téléchargement.
- Cache live stable : `data/live_cache.json` (TTL 7 j, persistant restart),
  requêtes TVMaze/TMDB avec timeout court + fail-soft hors-ligne.

## API

- `GET /api/search?q=&genre=&mood=&type=&country_code=&age=&year_min=&year_max=&min_rating=&providers=&limit=&live=1`
- `GET /api/similar?title=`
- `GET /api/detail?id=`
- `GET /api/history` · `GET /api/favorites`
- `POST /api/favorites {id, action}` · `POST /api/feedback {id, value}`
- `POST /api/import {text}` — CSV Letterboxd ou lignes `Titre,Année`.
- `GET /api/health`

UI : cartes visuelles + filtres + **comparaison (max 3)** + favoris +
historique + import Letterboxd + **« pourquoi ce match »** + **liens sources**.
Pas de disponibilité streaming inventée.

Persistance JSON sous `data/` (`favorites.json`, `feedback.json`,
`exposure.json`, `history.jsonl`) — écritures atomiques (tmp+replace),
survit au restart. Catalogue FTS5 `sqlite3` **en mémoire**, reconstruit
via `providers.fts_mem_ranks` à chaque recherche (aucun fichier DB écrit).

## Vérification

```bat
python -u -m unittest tests.test_film_search
python -u -c "import run_acceptance as ra; ra.main()"
python -u run_benchmark.py
python -u run_runtime_proof.py
```

Voir `DELIVERY.md` pour les preuves finales (HEAD/SOURCES/.../FILM_SEARCH_GREEN).
