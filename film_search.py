"""Agentic film search core engine (stdlib only).
Implements recovered CineAgent caps green-field:
multi-pass retrieval, RRF fusion, semantic concepts, hard exclusions,
concept negation, role-aware people, MMR diversity, anti-repeat/exposure,
second-hop discovery, explainable ranking, dedupe, need_providers support.
"""
import re
import math
import unicodedata
from collections import defaultdict

RRF_K = 60
MMR_LAMBDA = 0.72

STOPWORDS = set("""to of the and for with without sans avec dans des les une un est son sa ses sur par pour
plus pas que qui a an de la le en du au aux film films movie movies serie series tv show shows
similar similaire semblable like comme meilleur best top good bon bonne grand gros petit quel quelle quels
find trouver trouve cherche chercher looking want veux voir watch something quelque chose please stp svp
donne donner recommande recommend recommendation recommendations idee idea this that ces cette celui celle
qui quoi dont donc mais ou est sont ete etait avoir faire fait entre vers chez sous sans sous tout tous
toute avec comme dans elle il ils elle nous vous leur leurs mon ton son notre votre will would could should""".split())

GENRE_SYNONYMS = {
    "drama": ["drama", "drame", "dramatique"],
    "comedy": ["comedy", "comedie", "comédie", "funny", "drole", "drôle", "feel-good", "feelgood"],
    "crime": ["crime", "criminel", "policier", "polar", "gangster", "mafia", "heist", "casse", "braquage"],
    "thriller": ["thriller", "suspense", "tension", "tendu", "haletant", "espion"],
    "sci-fi": ["sci-fi", "scifi", "science-fiction", "science fiction", "sf", "space", "espace", "futur", "dystopia", "dystopie", "mind-bending", "time-travel", "voyage temporel"],
    "romance": ["romance", "romantique", "love", "amour", "sentimental"],
    "coming-of-age": ["coming-of-age", "coming of age", "teen", "ado", "adolescent", "youth", "jeunesse", "jeune", "lycee", "lycée", "high-school", "college", "initiation", "growing up"],
    "business": ["business", "startup", "entrepreneur", "entrepreneuriat", "tech", "silicon", "finance", "argent", "money", "bourse", "entreprise", "bureau", "office", "work"],
    "biography": ["biography", "biopic", "true story", "histoire vraie", "biographie"],
    "mystery": ["mystery", "mystere", "mystère", "enquete", "enquête", "investigation", "detective", "détective"],
    "action": ["action"],
    "fantasy": ["fantasy", "fantastique", "merveilleux"],
    "animation": ["animation", "anime", "cartoon", "dessin anime", "dessin animé"],
    "family": ["family", "famille", "familial", "kids", "enfants", "jeune public"],
    "documentary": ["documentary", "documentaire", "docu"],
    "horror": ["horror", "horreur", "effrayant", "peur", "epouvante"],
}

MOOD_SYNONYMS = {
    "melancholic": ["melancholic", "melancolique", "mélancolique", "melancholy", "melancolie", "mélancolie", "sad", "triste", "tristesse", "lonely", "solitude", "spleen", "nostalgic", "nostalgie", "blue"],
    "feel-good": ["feel-good", "feelgood", "feel good", "uplifting", "réconfortant", "reconfortant", "joyeux", "happy", "good mood", "bienveillant"],
    "tense": ["tense", "tendu", "tension", "suspense", "stressant", "anxious", "anxieux", "haletant", "palpitant"],
    "reflective": ["reflective", "reflexif", "contemplatif", "contemplative", "meditatif", "méditatif", "pensive", "pensif", "slow", "lent", "calme", "quiet", "doux"],
    "uplifting": ["uplifting", "hopeful", "espoir", "optimiste", "inspirant", "lumineux"],
    "dark": ["dark", "sombre", "noir", "noire", "bleak", "glauque"],
    "gritty": ["gritty", "rugueux", "brut", "cru", "realiste", "réaliste"],
    "dreamy": ["dreamy", "onirique", "reveur", "rêveur", "poetique", "poétique"],
    "nostalgic": ["nostalgic", "nostalgique", "nostalgie", "retro", "rétro", "80s", "90s"],
    "hopeful": ["hopeful", "espoir", "porteur d'espoir"],
    "slow": ["slow", "lent", "lenteur", "contemplatif"],
}

THEME_SYNONYMS = {
    "youth": ["youth", "jeunesse", "jeune", "young"],
    "teen": ["teen", "teens", "teenager", "ado", "ados", "adolescent", "adolescence", "lyceen", "lycéen", "highschool", "high-school", "school", "ecole", "école"],
    "coming-of-age": ["coming-of-age", "coming of age", "initiation", "passage a l'age adulte", "growing up"],
    "startup": ["startup", "start-up", "entrepreneur", "entrepreneurship", "entrepreneuriat", "founder", "fondateur", "lever de fonds", "licorne"],
    "entrepreneurship": ["entrepreneurship", "entrepreneuriat"],
    "technology": ["technology", "technologie", "tech", "silicon valley", "internet", "ai", "ia", "informatique", "ordinateur", "code"],
    "money": ["money", "argent", "finance", "bourse", "crise", "bank", "banque"],
    "heist": ["heist", "casse", "braquage", "hold-up", "cambriolage", "vol"],
    "investigation": ["investigation", "enquete", "enquête", "detective", "police", "meurtre", "murder", "crime scene"],
    "family": ["family", "famille"],
    "love": ["love", "amour", "romance", "couple"],
    "loneliness": ["loneliness", "solitude", "seul", "isolement", "lonely"],
    "work": ["work", "travail", "bureau", "office", "entreprise", "job"],
    "ambition": ["ambition", "ambitieux", "success", "succes", "succès", "power", "pouvoir"],
    "friendship": ["friendship", "amitie", "amitié", "amis", "friends", "potes"],
    "identity": ["identity", "identite", "identité", "coming out", "genre", "soi"],
    "hidden-gem": ["underrated", "hidden", "gem", "gems", "overlooked", "meconnu", "méconnu", "pepite", "pépite", "peu connu", "confidentiel", "rare", "oublie", "oublié"],
    "underdog": ["underdog", "outsider", "opprimé"],
    "small-town": ["small-town", "small town", "petite ville", "province", "village"],
    "city": ["city", "ville", "urbain", "new york", "paris", "tokyo", "los angeles"],
    "time": ["time", "temps", "temporel", "voyage dans le temps"],
    "memory": ["memory", "memoire", "mémoire", "souvenir", "oubli"],
    "music": ["music", "musique", "concert", "chanson"],
    "redemption": ["redemption", "redemption", "pardon", "seconde chance"],
}

COUNTRY_SYNONYMS = {
    "FR": ["france", "french", "francais", "français", "française", "paris"],
    "US": ["usa", "us", "america", "americain", "américain", "americaine", "hollywood", "new york", "los angeles"],
    "GB": ["uk", "british", "britannique", "angleterre", "england", "london", "londres"],
    "KR": ["korea", "coree", "corée", "coreen", "coréen", "korean", "seoul", "séoul"],
    "JP": ["japan", "japon", "japonais", "tokyo"],
    "ES": ["spain", "espagne", "espagnol", "madrid", "barcelona"],
    "DE": ["germany", "allemagne", "allemand", "berlin"],
    "NO": ["norway", "norvege", "norvège", "norvegien", "oslo"],
    "NZ": ["new zealand", "nouvelle-zelande", "zelande"],
    "DK": ["denmark", "danemark", "danois"],
    "CA": ["canada", "canadien", "quebec", "québec", "montreal"],
    "BE": ["belgium", "belgique", "belge", "bruxelles"],
}

AGE_HINTS = {
    "family": ["family", "famille", "kids", "enfants", "jeune public", "tous publics", "all ages", "children"],
    "teen": ["teen", "ado", "adolescent", "youth", "jeunesse", "young adult", "ya"],
    "adult": ["adult", "adulte", "mature"],
}

TYPE_HINTS = {
    "series": ["series", "serie", "série", "séries", "show", "tv", "saison", "season", "episode"],
    "movie": ["movie", "film", "movies", "films", "cinema", "cinéma", "long-metrage", "long métrage"],
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    s = (s or "").lower()
    s = strip_accents(s)
    s = re.sub(r"[’']", " ", s)
    s = re.sub(r"[^a-z0-9+ ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_title_key(title: str, year) -> str:
    return f"{norm(title)}|{year}"


def tokenize(q: str):
    return norm(q).split()


def find_hits(text_norm: str, synonyms: dict) -> list:
    hits = []
    for canon, variants in synonyms.items():
        for v in variants:
            vv = norm(v)
            if not vv:
                continue
            if " " in vv:
                if vv in text_norm:
                    hits.append(canon)
                    break
            else:
                if re.search(r"\b" + re.escape(vv) + r"s?\b", text_norm):
                    hits.append(canon)
                    break
    return sorted(set(hits))


def parse_query(q: str) -> dict:
    raw = q or ""
    t = norm(raw)
    parsed = {
        "raw": raw,
        "genres": find_hits(t, GENRE_SYNONYMS),
        "moods": find_hits(t, MOOD_SYNONYMS),
        "themes": find_hits(t, THEME_SYNONYMS),
        "countries": find_hits(t, COUNTRY_SYNONYMS),
        "similar_to": [],
        "excluded": [],
        "excluded_genres": [],
        "years": [],
        "year_min": None,
        "year_max": None,
        "age": None,
        "type": None,
        "min_rating": None,
        "underrated": False,
        "people": [],
    }
    # similar-to patterns FR+EN
    for pat in [r"similar to ([a-z0-9 \-':]+)", r"like ([a-z0-9 \-':]+)", r"comme ([a-z0-9 \-':]+)", r"semblable a ([a-z0-9 \-':]+)"]:
        for m in re.finditer(pat, norm(raw)):
            name = m.group(1).strip(" -")
            if len(name) >= 3 and name not in ("the same", "a film"):
                parsed["similar_to"].append(name)
    # negation: not X / sans X / without X / sauf X / no X
    for pat in [r"\bnot ([a-z\- ]+)", r"\bsans ([a-z\- ]+)", r"\bwithout ([a-z\- ]+)", r"\bsauf ([a-z\- ]+)", r"\bno ([a-z\- ]+)"]:
        for m in re.finditer(pat, t):
            chunk = m.group(1).strip()
            if chunk:
                parsed["excluded"].append(chunk)
    excl_text = " ".join(parsed["excluded"])
    if excl_text:
        parsed["excluded_genres"] = find_hits(excl_text, GENRE_SYNONYMS)
    # years
    for m in re.finditer(r"\b(19\d{2}|20\d{2})\b", t):
        parsed["years"].append(int(m.group(1)))
    if re.search(r"\b2010s\b|annees 2010|years 2010", t):
        parsed["year_min"], parsed["year_max"] = 2010, 2019
    elif re.search(r"\b2000s\b|annees 2000", t):
        parsed["year_min"], parsed["year_max"] = 2000, 2009
    elif re.search(r"\b90s\b|annees 90", t):
        parsed["year_min"], parsed["year_max"] = 1990, 1999
    m = re.search(r"after (\d{4})|apres (\d{4})|depuis (\d{4})", t)
    if m:
        y = next(g for g in m.groups() if g)
        parsed["year_min"] = int(y)
    m = re.search(r"before (\d{4})|avant (\d{4})", t)
    if m:
        y = next(g for g in m.groups() if g)
        parsed["year_max"] = int(y)
    if parsed["years"]:
        if parsed["year_min"] is None and parsed["year_max"] is None and len(parsed["years"]) == 1:
            parsed["year_min"] = parsed["year_max"] = parsed["years"][0]
    # age / type
    for canon, variants in AGE_HINTS.items():
        if any(re.search(r"\b" + re.escape(norm(v)) + r"\b", t) for v in variants if norm(v)):
            parsed["age"] = canon
            break
    for canon, variants in TYPE_HINTS.items():
        if any(re.search(r"\b" + re.escape(norm(v)) + r"\b", t) for v in variants if norm(v)):
            parsed["type"] = canon
            break
    m = re.search(r"(\d(?:[.,]\d)?)\s*/\s*10|note\s*(?:min|>|>=)?\s*(\d(?:[.,]\d)?)|rating\s*(?:>|>=)?\s*(\d(?:[.,]\d)?)", t)
    if m:
        for g in m.groups():
            if g:
                try:
                    parsed["min_rating"] = float(g.replace(",", "."))
                    break
                except ValueError:
                    pass
    if "hidden-gem" in parsed["themes"] or re.search(r"\bunderrated\b|\bhidden gems?\b|\bpepite", t):
        parsed["underrated"] = True
    # melancholic mood implies reflective+slow boost even if only sadness words
    return parsed


def item_text_blob(it: dict) -> str:
    parts = [it.get("title", ""), it.get("synopsis", ""), " ".join(it.get("genres", [])),
             " ".join(it.get("moods", [])), " ".join(it.get("themes", [])),
             " ".join(it.get("cast", [])), it.get("director", ""), it.get("country", "")]
    return norm(" ".join(parts))


def lexical_score(it: dict, tokens: list) -> tuple:
    blob = item_text_blob(it)
    title_n = norm(it.get("title", ""))
    score = 0.0
    reasons = []
    for tok in tokens:
        if len(tok) < 3:
            continue
        if tok in title_n:
            score += 3.0
        elif re.search(r"\b" + re.escape(tok) + r"\b", blob):
            score += 1.0
        elif tok in blob:
            score += 0.4
    if score > 0:
        reasons.append(f"lexical {score:.1f}")
    return score, reasons


def semantic_score(it: dict, parsed: dict) -> tuple:
    score = 0.0
    reasons = []
    g = set(x.lower() for x in it.get("genres", []))
    m = set(x.lower() for x in it.get("moods", []))
    th = set(x.lower() for x in it.get("themes", []))
    for want in parsed["genres"]:
        if want in g:
            score += 2.5
            reasons.append(f"genre {want} +2.5")
    for want in parsed["moods"]:
        if want in m:
            score += 2.0
            reasons.append(f"mood {want} +2.0")
    for want in parsed["themes"]:
        if want in th:
            score += 1.5
            reasons.append(f"theme {want} +1.5")
    for cc in parsed["countries"]:
        if it.get("country_code") == cc:
            score += 2.0
            reasons.append(f"country {cc} +2.0")
    if parsed["year_min"] is not None and parsed["year_max"] is not None:
        if parsed["year_min"] <= int(it.get("year", 0)) <= parsed["year_max"]:
            score += 1.5
            reasons.append(f"year {it.get('year')} in range +1.5")
    elif parsed["years"]:
        if int(it.get("year", 0)) in parsed["years"]:
            score += 1.5
            reasons.append("year exact +1.5")
    if parsed["type"] and it.get("type") == parsed["type"]:
        score += 1.0
        reasons.append(f"type {parsed['type']} +1.0")
    if parsed["age"] == "family" and it.get("age") == "Tous publics":
        score += 1.0
        reasons.append("family-friendly +1.0")
    if parsed["age"] == "teen" and any(x in th for x in ("youth", "teen", "coming-of-age")):
        score += 1.5
        reasons.append("teen audience +1.5")
    if parsed["min_rating"] is not None and float(it.get("rating", 0)) >= parsed["min_rating"]:
        score += 1.0
        reasons.append(f"rating>={parsed['min_rating']} +1.0")
    if parsed["underrated"]:
        pop = float(it.get("popularity", 50))
        rat = float(it.get("rating", 0))
        if pop < 55 and rat >= 7.0:
            score += 2.5
            reasons.append(f"underrated gem pop={pop:.0f} rating={rat} +2.5")
        elif pop < 70:
            score += 0.8
            reasons.append("lesser-known +0.8")
    return score, reasons


def people_score(it: dict, parsed: dict, tokens: list) -> tuple:
    names = [norm(c) for c in it.get("cast", [])] + [norm(it.get("director", ""))]
    blob = " ".join(names)
    score = 0.0
    reasons = []
    for tok in tokens:
        if len(tok) < 4:
            continue
        for nm in names:
            if tok in nm and nm:
                score += 2.0
                reasons.append(f"person match '{tok}' +2.0")
                break
    return score, reasons


def passes_for(items: list, parsed: dict, tokens: list):
    scored_a, scored_b, scored_d = [], [], []
    for it in items:
        s, _ = lexical_score(it, tokens)
        if s > 0:
            scored_a.append((s, it))
        s2, _ = semantic_score(it, parsed)
        if s2 > 0:
            scored_b.append((s2, it))
        s3, _ = people_score(it, parsed, tokens)
        if s3 > 0:
            scored_d.append((s3, it))
    scored_a.sort(key=lambda x: -x[0])
    scored_b.sort(key=lambda x: -x[0])
    scored_d.sort(key=lambda x: -x[0])
    rank_a = {id(it): i + 1 for i, (_, it) in enumerate(scored_a)}
    rank_b = {id(it): i + 1 for i, (_, it) in enumerate(scored_b)}
    rank_d = {id(it): i + 1 for i, (_, it) in enumerate(scored_d)}
    # pass C: similar-title second hop (rank + raw similarity strength)
    rank_c = {}
    sim_c = {}
    base_ids = set()
    if parsed["similar_to"]:
        for want in parsed["similar_to"]:
            wn = norm(want)
            best = None
            best_ov = 0
            for it in items:
                tn = norm(it.get("title", ""))
                if not tn:
                    continue
                # overlap of words
                ov = len(set(wn.split()) & set(tn.split()))
                if wn == tn:
                    ov += 10
                elif wn in tn or tn in wn:
                    ov += 5
                if ov > best_ov:
                    best_ov = ov
                    best = it
            if best is not None and best_ov > 0:
                base_ids.add(id(best))
                # neighbors share genres/themes/cast
                bg = set(x.lower() for x in best.get("genres", []))
                bt = set(x.lower() for x in best.get("themes", []))
                bc = set(norm(c) for c in best.get("cast", []))
                scored = []
                for it in items:
                    if it is best:
                        continue
                    g = set(x.lower() for x in it.get("genres", []))
                    th = set(x.lower() for x in it.get("themes", []))
                    c = set(norm(x) for x in it.get("cast", []))
                    sim = 3 * len(bg & g) + 2 * len(bt & th) + 4 * len(bc & c)
                    if sim > 0:
                        scored.append((sim, it))
                scored.sort(key=lambda x: -x[0])
                for i, (sim, it) in enumerate(scored):
                    # keep best rank across similar bases
                    r = i + 1
                    if id(it) not in rank_c or r < rank_c[id(it)]:
                        rank_c[id(it)] = r
                        sim_c[id(it)] = sim
    return rank_a, rank_b, rank_c, rank_d, base_ids, sim_c


def rrf_fuse(items: list, ranks_list: list) -> dict:
    fused = defaultdict(float)
    for ranks in ranks_list:
        for key, r in ranks.items():
            fused[key] += 1.0 / (RRF_K + r)
    return fused


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def item_signature(it: dict) -> set:
    return set(x.lower() for x in it.get("genres", [])) | set(x.lower() for x in it.get("themes", [])) | set(norm(c) for c in it.get("cast", [])[:3])


def mmr_rerank(candidates: list, top_n: int = 12) -> list:
    selected = []
    remaining = candidates[:]
    while remaining and len(selected) < top_n:
        best = None
        best_mmr = None
        for cand in remaining:
            sim_max = 0.0
            for sel in selected:
                sim_max = max(sim_max, jaccard(item_signature(cand["item"]), item_signature(sel["item"])))
            mmr = MMR_LAMBDA * cand["fused"] - (1 - MMR_LAMBDA) * sim_max * 2.0
            if best is None or mmr > best_mmr:
                best, best_mmr = cand, mmr
        selected.append(best)
        remaining.remove(best)
    return selected


def apply_hard_filters(items: list, parsed: dict, filters: dict) -> list:
    f = filters or {}
    out = []
    excl_genres = set(parsed.get("excluded_genres", []))
    excl_text = " ".join(parsed.get("excluded", []))
    for it in items:
        g = set(x.lower() for x in it.get("genres", []))
        if excl_genres & g:
            continue
        if excl_text and ("horror" in excl_text or "horreur" in excl_text) and "horror" in g:
            continue
        if f.get("genre") and f["genre"].lower() not in g:
            continue
        if f.get("type") and it.get("type") != f["type"]:
            continue
        if f.get("country_code") and it.get("country_code") != f["country_code"]:
            continue
        if f.get("year_min") is not None and int(it.get("year", 0)) < int(f["year_min"]):
            continue
        if f.get("year_max") is not None and int(it.get("year", 0)) > int(f["year_max"]):
            continue
        if f.get("min_rating") is not None and float(it.get("rating", 0)) < float(f["min_rating"]):
            continue
        if f.get("mood") and f["mood"].lower() not in set(x.lower() for x in it.get("moods", [])):
            continue
        # need_providers: item must be available on at least one requested provider
        need = f.get("need_providers") or f.get("providers") or []
        if need:
            have = set(p.lower() for p in it.get("providers", []))
            want = set(p.lower() for p in need)
            if not (have & want):
                continue
        # age filter: family wants Tous publics or 10+
        if f.get("age") == "family" and it.get("age") not in ("Tous publics", "10+"):
            # allow 12+ only if explicitly teen? no -> filter
            continue
        out.append(it)
    # parsed year range also acts as hard filter when explicit
    if parsed.get("year_min") is not None and parsed.get("year_max") is not None:
        out = [it for it in out if parsed["year_min"] <= int(it.get("year", 0)) <= parsed["year_max"]]
    # explicit country mention in query acts as hard filter (kept soft for similar-to breadth)
    if parsed.get("countries") and not parsed.get("similar_to") and not f.get("country_code"):
        want_cc = set(parsed["countries"])
        out = [it for it in out if it.get("country_code") in want_cc]
    if parsed.get("type"):
        # soft: keep but filtered above only if filters set; here enforce if query says series/movie
        pass
    return out


def dedupe_results(scored: list) -> list:
    seen = {}
    for entry in scored:
        it = entry["item"]
        key = norm_title_key(it.get("title", ""), it.get("year", ""))
        if key not in seen:
            seen[key] = entry
        else:
            # merge sources, keep best score, concatenate reasons
            prev = seen[key]
            if entry["score"] > prev["score"]:
                entry["reasons"] = sorted(set(prev["reasons"] + entry["reasons"]))
                entry["sources"] = sorted(set(prev.get("sources", []) + entry.get("sources", [])))
                seen[key] = entry
            else:
                prev["reasons"] = sorted(set(prev["reasons"] + entry["reasons"]))
                prev["sources"] = sorted(set(prev.get("sources", []) + entry.get("sources", [])))
    return list(seen.values())


def poster_for(it: dict) -> str:
    url = (it.get("poster") or "").strip()
    if url.startswith("http"):
        return url
    path = (it.get("poster_path") or "").strip()
    if path.startswith("http"):
        return path
    if path.startswith("/"):
        return "https://image.tmdb.org/t/p/w500" + path
    # deterministic SVG placeholder (clean, not slop)
    title = (it.get("title") or "?")[:22]
    year = it.get("year", "")
    hue = abs(hash(it.get("id", title))) % 360
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='500' height='750'>"
           f"<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
           f"<stop offset='0' stop-color='hsl({hue},32%,22%)'/>"
           f"<stop offset='1' stop-color='hsl({(hue+40)%360},30%,12%)'/></linearGradient></defs>"
           f"<rect width='500' height='750' fill='url(#g)'/>"
           f"<text x='36' y='380' font-family='Arial' font-size='40' fill='white'>{title}</text>"
           f"<text x='36' y='430' font-family='Arial' font-size='30' fill='#cccccc'>{year}</text></svg>")
    import base64
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def search(items: list, query: str, filters: dict = None, exposure: dict = None, top_n: int = 12) -> list:
    filters = filters or {}
    exposure = exposure or {}
    parsed = parse_query(query)
    tokens = [t for t in tokenize(query) if len(t) >= 3 and t not in STOPWORDS]
    # similar-to anchor words must not pollute lexical/people passes (second-hop decides)
    if parsed["similar_to"]:
        anchor_toks = set(tokenize(" ".join(parsed["similar_to"])))
        lex_tokens = [t for t in tokens if t not in anchor_toks]
    else:
        lex_tokens = tokens
    pool = apply_hard_filters(items, parsed, filters)
    if not pool:
        return []
    rank_a, rank_b, rank_c, rank_d, base_ids, sim_c = passes_for(pool, parsed, lex_tokens)
    fused = rrf_fuse(pool, [rank_a, rank_b, rank_c, rank_d])
    candidates = []
    by_id = {id(it): it for it in pool}
    for key, fscore in fused.items():
        it = by_id.get(key)
        if it is None:
            continue
        s_sem, r_sem = semantic_score(it, parsed)
        s_lex, r_lex = lexical_score(it, lex_tokens)
        s_ppl, r_ppl = people_score(it, parsed, lex_tokens)
        # quality prior: rating + popularity (dampened when underrated requested)
        rating = float(it.get("rating", 0))
        pop = float(it.get("popularity", 50))
        if parsed["underrated"]:
            quality = (rating - 6.5) * 0.35 + max(0.0, (55 - pop)) * 0.012
        else:
            quality = (rating - 6.5) * 0.22 + (pop / 100.0) * 0.35
        total = fscore * 6.0 + s_sem + s_lex * 0.7 + s_ppl + quality
        reasons = []
        reasons += r_sem + r_lex + r_ppl
        if fscore > 0:
            reasons.append(f"multi-pass RRF {fscore:.3f}")
        if quality > 0.2:
            reasons.append(f"quality rating {rating} pop {pop:.0f}")
        if id(it) in base_ids:
            reasons.append("exact similar-title anchor")
        # anti-repeat exposure penalty
        exp = float(exposure.get(it.get("id", ""), 0))
        if exp > 0:
            total -= min(2.5, exp * 0.8)
            reasons.append(f"seen penalty -{min(2.5, exp*0.8):.1f} (anti-repeat)")
        # similar boost weighted by second-hop similarity strength
        if parsed["similar_to"] and id(it) not in base_ids and key in rank_c:
            sim = float(sim_c.get(key, 0))
            boost = min(4.5, sim * 0.4)
            total += boost
            reasons.append(f"second-hop similar sim={sim:.0f} +{boost:.1f}")
        # anchor injection note (anchors appended below if missing from fusion)
        # empty query => catalog browse by quality
        if not tokens and not (parsed["genres"] or parsed["moods"] or parsed["themes"]):
            total = quality + rating * 0.1
            reasons = [f"browse quality {quality:.2f}"]
        candidates.append({"item": it, "score": total, "fused": fscore + total * 0.05, "reasons": reasons, "sources": list(it.get("sources", ["local"]))})
    # inject similar-title anchors so the reference is visible first
    have_ids = set(id(c["item"]) for c in candidates)
    for it in pool:
        if id(it) in base_ids and id(it) not in have_ids:
            rating = float(it.get("rating", 0))
            pop = float(it.get("popularity", 50))
            quality = (rating - 6.5) * 0.22 + (pop / 100.0) * 0.35
            candidates.append({"item": it, "score": 4.0 + quality, "fused": 1.0 / (RRF_K + 1) + 0.2,
                               "reasons": ["exact similar-title anchor", f"quality rating {rating} pop {pop:.0f}"],
                               "sources": list(it.get("sources", ["local"]))})
    # if nothing fused (e.g. filter-only browse), fallback to quality ranking
    if not candidates:
        for it in pool[:top_n * 3]:
            rating = float(it.get("rating", 0))
            candidates.append({"item": it, "score": rating, "fused": rating * 0.05, "reasons": ["filter browse"], "sources": ["local"]})
    candidates.sort(key=lambda c: -c["score"])
    candidates = dedupe_results(candidates)
    candidates.sort(key=lambda c: -c["score"])
    ranked = mmr_rerank(candidates, top_n=top_n)
    # attach poster + reason string
    out = []
    for c in ranked:
        it = dict(c["item"])
        it["poster"] = poster_for(it)
        it["ranking_reason"] = "; ".join(c["reasons"][:4]) if c["reasons"] else "browse"
        it["_score"] = round(c["score"], 3)
        it["_sources"] = c["sources"]
        out.append(it)
    return out
