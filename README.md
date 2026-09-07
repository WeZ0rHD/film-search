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

## API

- `GET /api/search?q=&genre=&mood=&type=&country_code=&age=&year_min=&year_max=&min_rating=&providers=&limit=&live=1`
- `GET /api/similar?title=`
- `GET /api/detail?id=`
- `GET /api/history` · `GET /api/favorites`
- `POST /api/favorites {id, action}` · `POST /api/feedback {id, value}`
- `POST /api/import {text}` — CSV Letterboxd ou lignes `Titre,Année`.
- `GET /api/health`

Persistance SQLite `data/app.db` (historique, favoris, feedback, exposition) —
survit au restart (WAL). Catalogue FTS5 `data/catalog.db` reconstruit au boot.

## Vérification

```bat
C:\Python314\python.exe -u -m unittest tests.test_film_search
C:\Python314\python.exe -u -c "import run_acceptance as ra; ra.main()"
```

Voir `DELIVERY.md` pour les preuves finales (HEAD/SOURCES/.../FILM_SEARCH_GREEN).
