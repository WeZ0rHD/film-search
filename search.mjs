import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.join(here, "data", "films.json");

export function loadFilms() {
  return JSON.parse(readFileSync(DATA, "utf8"));
}

export function normalizeTitle(t) {
  return String(t || "").toLowerCase().replace(/[^a-z0-9]+/g, "").trim();
}

export function dedupeFilms(films) {
  const seen = new Map();
  for (const f of films) {
    const k = normalizeTitle(f.title) + "|" + f.year;
    if (!seen.has(k)) seen.set(k, f);
  }
  return [...seen.values()];
}

function buildSynonyms() {
  return new Map([
    ["teen", ["teen", "teenager", "adolescent", "high-school", "coming-of-age", "young-adult"]],
    ["teenager", ["teen", "young-adult", "coming-of-age"]],
    ["teenagers", ["teen", "young-adult"]],
    ["teens", ["teen", "young-adult"]],
    ["ya", ["young-adult", "teen", "dystopia"]],
    ["young", ["young-adult", "teen"]],
    ["adult", ["young-adult", "coming-of-age"]],
    ["coming-of-age", ["coming-of-age", "teen", "growing-up"]],
    ["coming", ["coming-of-age"]],
    ["highschool", ["high-school", "teen"]],
    ["school", ["high-school", "boarding-school", "middle-school"]],
    ["dystopia", ["dystopia", "rebellion", "survival"]],
    ["dystopian", ["dystopia"]],
    ["hunger", ["dystopia", "survival"]],
    ["friendship", ["friendship"]],
    ["friends", ["friendship"]],
    ["funny", ["funny", "comedy"]],
    ["comedy", ["comedy", "funny"]],
    ["hopeful", ["hopeful", "uplifting", "inspiring"]],
    ["hope", ["hopeful"]],
    ["feel-good", ["uplifting", "hopeful", "warm", "funny"]],
    ["feelgood", ["uplifting", "hopeful"]],
    ["bittersweet", ["bittersweet"]],
    ["romance", ["romance", "first-love"]],
    ["love", ["first-love", "romance"]],
    ["romantic", ["romance", "first-love"]],
    ["drama", ["drama"]],
    ["french", ["france"]],
    ["france", ["france"]],
    ["japan", ["japan"]],
    ["japanese", ["japan", "animation"]],
    ["anime", ["animation", "japan"]],
    ["animation", ["animation"]],
    ["adventure", ["adventure"]],
    ["90s", ["90s"]],
    ["80s", ["80s"]],
    // V4: business/startup discovery (legitimate metadata only)
    ["startup", ["startup", "business", "entrepreneur", "founder", "company"]],
    ["startups", ["startup", "business"]],
    ["business", ["business", "startup", "company", "entrepreneur", "ambition"]],
    ["entrepreneur", ["startup", "business"]],
    ["company", ["business", "startup"]],
    ["founder", ["business", "startup"]],
    ["facebook", ["startup", "business"]],
    ["mcdonalds", ["business"]],
    // V4: crime discovery
    ["crime", ["crime", "mafia", "gangs", "gangster"]],
    ["criminal", ["crime"]],
    ["mafia", ["crime", "mafia"]],
    ["gangster", ["crime", "mafia"]],
    ["gangs", ["crime", "gangs"]],
    ["gang", ["crime"]],
    ["thriller", ["thriller", "tense"]],
    // V4: recency handled via yearPref, synonyms keep token visible
    ["recent", ["recent"]],
    ["latest", ["recent"]],
    ["new", ["recent"]],
    ["2020s", ["recent"]],
    ["biography", ["biography"]],
    ["true", ["biography"]],
    ["korea", ["south korea", "korea"]],
    ["korean", ["south korea"]],
    ["brazil", ["brazil"]],
    ["brazilian", ["brazil"]],
  ]);
}
const SYN = buildSynonyms();

export function tokenize(q) {
  return String(q || "").toLowerCase().replace(/[^a-z0-9+\-'\s]/g, " ").split(/\s+/).map((t) => t.trim()).filter((t) => t.length > 1 && !new Set(["the", "and", "for", "with", "like", "similar", "movie", "movies", "film", "films", "show", "shows", "about", "that", "this", "please", "find", "search", "recommend", "suggest", "give", "want"]).has(t));
}

export function expandTokens(tokens) {
  const out = new Set(tokens);
  for (const t of tokens) {
    const ex = SYN.get(t);
    if (ex) for (const e of ex) out.add(e);
    // hyphen variants
    if (t.includes("-")) for (const p of t.split("-")) if (p.length > 2) out.add(p);
  }
  return [...out];
}

function haystack(f) {
  return {
    title: (f.title || "").toLowerCase(),
    alternate: String(f.alternateTitle || "").toLowerCase(),
    genres: (f.genres || []).map((g) => String(g).toLowerCase()),
    themes: (f.themes || []).map((g) => String(g).toLowerCase()),
    keywords: (f.keywords || []).map((g) => String(g).toLowerCase()),
    moods: (f.moods || []).map((g) => String(g).toLowerCase()),
    country: String(f.country || "").toLowerCase(),
    countries: (f.countries || []).map((g) => String(g).toLowerCase()),
    syn: String(f.synopsis || "").toLowerCase(),
    cast: (f.cast || []).map((g) => String(g).toLowerCase()).join(" "),
    director: String(f.director || "").toLowerCase(),
    age: String(f.ageTarget || "").toLowerCase(),
    year: String(f.year),
  };
}

export function extractSimilarTarget(query, films) {
  const m = String(query || "").match(/(?:like|similar to|similar-to)\s+([^,.;!?]+)/i);
  if (!m) return null;
  const needle = m[1].trim().toLowerCase();
  let best = null;
  let bestScore = 0;
  for (const f of films) {
    const t = (f.title || "").toLowerCase();
    const alt = String(f.alternateTitle || "").toLowerCase();
    const hay = t + " " + alt;
    if (needle.includes(t) || t.includes(needle) || (alt && (needle.includes(alt) || alt.includes(needle))) || needle.split(/\s+/).some((w) => w.length > 3 && hay.includes(w))) {
      const overlap = needle.split(/\s+/).filter((w) => hay.includes(w)).length;
      const score = overlap + (needle.includes(t) ? 5 : 0) + (t.includes(needle) ? 5 : 0) + (alt && needle.includes(alt) ? 4 : 0);
      if (score > bestScore) { bestScore = score; best = f; }
    }
  }
  return best;
}

// V4: ambiguity + unknown-title diagnostics (non-breaking additive)
export function extractSimilarCandidates(query, films, limit = 5) {
  const m = String(query || "").match(/(?:like|similar to|similar-to)\s+([^,.;!?]+)/i);
  if (!m) return [];
  const needle = m[1].trim().toLowerCase();
  const scored = [];
  for (const f of films) {
    const t = (f.title || "").toLowerCase();
    const alt = String(f.alternateTitle || "").toLowerCase();
    const hay = t + " " + alt;
    const overlap = needle.split(/\s+/).filter((w) => w.length > 2 && hay.includes(w)).length;
    const exact = needle.includes(t) || t.includes(needle) ? 5 : 0;
    const s = overlap + exact;
    if (s > 0) scored.push({ film: f, score: s });
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, limit);
}

export function wantsRecent(tokens, expanded) {
  const set = new Set([...(tokens || []), ...(expanded || [])]);
  return ["recent", "latest", "new", "2020s", "2021", "2022", "2023", "2024"].some((t) => set.has(t));
}

export function franchiseKey(f) {
  // Strip leading article, take first significant token as franchise bucket.
  // Prevents same-franchise flooding while keeping distinct films diverse.
  const t = String(f.title || "").toLowerCase().replace(/^the\s+/, "").trim();
  const first = t.split(/[^a-z0-9]+/).filter(Boolean)[0] || "unknown";
  return first + "|" + String(f.director || "").toLowerCase().slice(0, 12);
}

export function franchiseBase(f) {
  const t = String(f.title || "").toLowerCase().replace(/^the\s+/, "").trim();
  return t.split(/[^a-z0-9]+/).filter(Boolean)[0] || "unknown";
}

export function diversify(scored, opts = {}) {
  const maxPerFranchise = opts.maxPerFranchise ?? 2;
  const maxPerDirector = opts.maxPerDirector ?? 3;
  const selected = [];
  const deferred = [];
  const fCount = new Map();
  const dCount = new Map();
  for (const s of scored) {
    const fb = franchiseBase(s.film);
    const d = String(s.film.director || "?").toLowerCase();
    const cf = fCount.get(fb) || 0;
    const cd = dCount.get(d) || 0;
    if (cf >= maxPerFranchise || cd >= maxPerDirector) {
      deferred.push({ ...s, reasons: [...(s.reasons || []), `diversity: capped (${fb}/${s.film.director}), placed lower`], _deferred: true });
    } else {
      fCount.set(fb, cf + 1);
      dCount.set(d, cd + 1);
      selected.push(s);
    }
  }
  // Country interleave for top window: if top N dominated by one country, pull forward next different-country hit
  const out = [...selected, ...deferred];
  return out;
}

export function detectConflicts(films) {
  // Same normalized title, different years => metadata conflict surface
  const byTitle = new Map();
  for (const f of films) {
    const k = normalizeTitle(f.title);
    if (!byTitle.has(k)) byTitle.set(k, []);
    byTitle.get(k).push(f);
  }
  const conflicts = [];
  for (const [k, arr] of byTitle) {
    const years = new Set(arr.map((x) => x.year));
    if (arr.length > 1 && years.size > 1) conflicts.push({ key: k, films: arr.map((x) => ({ id: x.id, title: x.title, year: x.year })) });
  }
  return conflicts;
}

export function diagnoseQuery(query, results, films, similarTarget) {
  const notes = [];
  const q = String(query || "").trim();
  if (!q) return { unknown: false, ambiguous: false, notes: ["broad discovery"] };
  if (!results || results.length === 0) {
    notes.push(`unknown title / no match for "${q}": try teen drama, crime, romance, startup, recent films, or similar to Lady Bird`);
    return { unknown: true, ambiguous: false, notes };
  }
  // ambiguous: similar-target query matching 2+ candidates with close scores
  if (similarTarget) {
    const cands = extractSimilarCandidates(q, films, 4);
    if (cands.length >= 2 && (cands[0].score - cands[1].score) <= 1) {
      notes.push(`ambiguous title "${q}": top matches ${cands.slice(0, 3).map((c) => `${c.film.title} (${c.film.year})`).join(", ")} — showing similarity blend`);
      return { unknown: false, ambiguous: true, notes, candidates: cands.map((c) => ({ id: c.film.id, title: c.film.title, year: c.film.year })) };
    }
  }
  // low-confidence: top score weak
  if (results[0] && results[0].score <= 1.0) {
    notes.push(`low confidence for "${q}": best hit ${results[0].film.title} scores ${results[0].score} — results are approximate`);
  }
  return { unknown: false, ambiguous: false, notes };
}

export function scoreFilm(f, tokens, expanded, opts = {}) {
  const h = haystack(f);
  let score = 0;
  const reasons = [];
  const has = (arr, tok) => arr.some((a) => a === tok || a.includes(tok) || tok.includes(a));

  for (const tok of expanded) {
    if (!tok) continue;
    if (h.title.includes(tok) && tok.length > 2) { score += 5; reasons.push(`title matches "${tok}" +5`); }
    if (h.alternate && h.alternate.includes(tok) && tok.length > 2) { score += 4; reasons.push(`alternate title matches "${tok}" +4`); }
    if (has(h.genres, tok)) { score += 3; reasons.push(`genre matches "${tok}" +3`); }
    if (has(h.themes, tok)) { score += 3; reasons.push(`theme matches "${tok}" +3`); }
    if (has(h.keywords, tok)) { score += 2.5; reasons.push(`keyword matches "${tok}" +2.5`); }
    if (has(h.moods, tok)) { score += 2.5; reasons.push(`mood matches "${tok}" +2.5`); }
    if (h.syn.includes(tok) && tok.length > 2) { score += 1.2; reasons.push(`synopsis mentions "${tok}" +1.2`); }
    if (h.cast.includes(tok) && tok.length > 2) { score += 2; reasons.push(`cast matches "${tok}" +2`); }
    if (h.director.includes(tok) && tok.length > 2) { score += 2; reasons.push(`director matches "${tok}" +2`); }
    if (h.country.includes(tok) || h.countries.some((c) => c.includes(tok))) { score += 3; reasons.push(`country matches "${tok}" +3`); }
    if (h.year === tok) { score += 4; reasons.push(`year ${tok} +4`); }
    if (h.age.includes(tok)) { score += 1.5; reasons.push(`age-target ${tok} +1.5`); }
  }

  // similar-title boost
  if (opts.similarTarget && opts.similarTarget.id !== f.id) {
    const t = opts.similarTarget;
    const sharedGenres = f.genres.filter((g) => t.genres.includes(g)).length;
    const sharedThemes = f.themes.filter((g) => t.themes.includes(g)).length;
    const sharedMoods = f.moods.filter((g) => t.moods.includes(g)).length;
    const boost = sharedGenres * 2 + sharedThemes * 2 + sharedMoods * 1;
    if (boost > 0) { score += boost; reasons.push(`similar to "${t.title}" shares ${sharedGenres} genre(s), ${sharedThemes} theme(s) +${boost}`); }
  }
  if (opts.similarTarget && opts.similarTarget.id === f.id) {
    score += 12; reasons.push(`exact similar-title anchor "${f.title}" +12`);
  }

  // small quality prior to diversify but not dominate
  score += Math.min(1.5, (f.rating - 7) * 0.4);

  // V4: year preference — recent/new/latest boosts newer films explicitly
  if (opts.yearPref) {
    const recency = Math.max(0, Math.min(3, (f.year - 2000) * 0.12));
    if (recency > 0) { score += recency; reasons.push(`recency ${f.year} +${Math.round(recency * 100) / 100}`); }
  }
  return { score: Math.round(score * 100) / 100, reasons: reasons.slice(0, 8) };
}

export function applyFilters(films, filters = {}) {
  return films.filter((f) => {
    if (filters.genre && !f.genres.map((g) => g.toLowerCase()).some((g) => g.includes(String(filters.genre).toLowerCase()))) return false;
    if (filters.country && !((f.countries || [f.country]).map((c) => c.toLowerCase()).some((c) => c.includes(String(filters.country).toLowerCase())))) return false;
    if (filters.year && f.year !== Number(filters.year)) return false;
    if (filters.yearFrom && f.year < Number(filters.yearFrom)) return false;
    if (filters.yearTo && f.year > Number(filters.yearTo)) return false;
    if (filters.ageMax != null && f.ageMin > Number(filters.ageMax)) return false;
    if (filters.ageTarget && f.ageMin > Number(String(filters.ageTarget).replace(/[^0-9]/g, "") || 99)) return false;
    return true;
  });
}

export function posterSVG(f, size = 240) {
  const missing = f.posterHue == null;
  const hue = missing ? 220 : f.posterHue;
  const initials = String(f.title || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
  const label = missing ? "NO POSTER" : String(f.title).replace(/&/g, "&amp;").slice(0, 22);
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='${size}' height='${Math.round(size * 1.5)}'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='hsl(${hue},65%,42%)'/><stop offset='1' stop-color='hsl(${(hue + 40) % 360},70%,22%)'/></linearGradient></defs><rect width='100%' height='100%' fill='url(#g)'/><text x='50%' y='44%' font-family='Arial' font-size='${Math.round(size * 0.28)}' fill='white' text-anchor='middle' font-weight='bold'>${initials}</text><text x='50%' y='88%' font-family='Arial' font-size='${Math.round(size * 0.07)}' fill='white' text-anchor='middle'>${label}</text><text x='50%' y='94%' font-family='Arial' font-size='${Math.round(size * 0.06)}' fill='white' text-anchor='middle' opacity='0.85'>${f.year} · ${String(f.country).slice(0, 12)}${missing ? " · poster unavailable" : ""}</text></svg>`;
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

export function posterInfo(f) {
  return { missing: f.posterHue == null, provenance: "local SVG placeholder (offline, no external image rights)", url: posterSVG(f) };
}

export function searchFilms(query, filters = {}, allFilms = null) {
  const raw = allFilms ?? loadFilms();
  const deduped = dedupeFilms(raw);
  const dedupedCount = raw.length - deduped.length;
  const films = deduped;
  const tokens = tokenize(query);
  const expanded = expandTokens(tokens);
  const similarTarget = extractSimilarTarget(query, films);
  const yearPref = wantsRecent(tokens, expanded);
  let pool = applyFilters(films, filters);
  // broad empty query => return all ranked by rating for discovery
  if (tokens.length === 0 && Object.keys(filters).length === 0) {
    const all = pool.map((f) => ({ film: f, score: f.rating, reasons: ["broad discovery: ranked by rating"], poster: posterSVG(f), posterMissing: f.posterHue == null, uncertainty: [] }));
    return diversify(all.sort((a, b) => b.score - a.score));
  }
  let scored = pool.map((f) => {
    const { score, reasons } = scoreFilm(f, tokens, expanded, { similarTarget, yearPref });
    const uncertainty = [];
    if (f.posterHue == null) uncertainty.push("missing poster: placeholder shown");
    if (!f.ratingSource) uncertainty.push("rating provenance missing");
    return { film: f, score, reasons, poster: posterSVG(f), posterMissing: f.posterHue == null, uncertainty };
  });
  // keep meaningful: if query tokens exist, drop zero-score unless pool small (permit 20+ when sources permit)
  const positive = scored.filter((s) => s.score > 0.5);
  const usePositive = positive.length >= 3 ? positive : scored;
  usePositive.sort((a, b) => b.score - a.score || b.film.rating - a.film.rating || b.film.year - a.film.year);
  // V4 diversity: cap franchise/director flooding, keep stable variety
  const diversified = diversify(usePositive);
  // Attach diagnostics non-breaking: array carries meta props
  const diag = diagnoseQuery(query, diversified, films, similarTarget);
  diversified.diagnostics = { ...diag, dedupedCount, yearPref, similarAnchor: similarTarget ? { id: similarTarget.id, title: similarTarget.title, year: similarTarget.year } : null };
  return diversified;
}
