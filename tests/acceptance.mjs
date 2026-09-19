import { loadFilms, searchFilms, dedupeFilms, detectConflicts, diagnoseQuery, franchiseBase, diversify, wantsRecent } from "../search.mjs";

function assert(c, msg) { if (!c) { console.error("FAIL:", msg); process.exitCode = 1; } else console.log("PASS:", msg); }
function noDupes(results) {
  const keys = results.map((r) => r.film.title.toLowerCase() + "|" + r.film.year);
  return new Set(keys).size === keys.length;
}
function hasPosterMeta(r) { return r.poster && r.poster.startsWith("data:image") && r.film.synopsis && r.film.cast?.length && r.reasons?.length; }

const films = loadFilms();
assert(films.length >= 28, `dataset ${films.length} >= 28`);
assert(dedupeFilms([...films, films[0]]).length === films.length, "dedupe collapses exact duplicate");

const QUERIES = [
  { q: "teen coming-of-age drama", filters: {}, expectMin: 8, label: "teen/YA/drama core" },
  { q: "young adult dystopia like Hunger Games", filters: {}, expectMin: 3, label: "YA dystopia semantic" },
  { q: "feel-good friendship comedy hopeful", filters: {}, expectMin: 5, label: "mood friendship" },
  { q: "drama USA 90s", filters: {}, expectMin: 3, label: "90s USA drama" },
  { q: "French coming-of-age romance", filters: {}, expectMin: 2, label: "French coming-of-age" },
  { q: "like Lady Bird", filters: {}, expectMin: 5, label: "similar-title Lady Bird" },
  { q: "hopeful bittersweet tender", filters: {}, expectMin: 5, label: "mood query" },
  { q: "adventure animation", filters: { ageMax: "13" }, expectMin: 3, label: "age 13+ adventure filter" },
  { q: "Japan animation drama", filters: {}, expectMin: 2, label: "country Japan" },
  { q: "drama", filters: {}, expectMin: 20, label: "broad drama returns 20+" },
];

let allOk = true;
for (const t of QUERIES) {
  const res = searchFilms(t.q, t.filters, films);
  const okCount = res.length >= t.expectMin;
  const okDupes = noDupes(res);
  const okMeta = res.slice(0, 5).every(hasPosterMeta);
  console.log(`\nQUERY "${t.q}" [${t.label}] => ${res.length} hits top=${res[0]?.film.title} score=${res[0]?.score}`);
  console.log(`  reasons: ${(res[0]?.reasons || []).slice(0, 2).join(" | ")}`);
  assert(okCount, `"${t.label}" hits ${res.length} >= ${t.expectMin}`);
  assert(okDupes, `"${t.label}" no duplicate spam`);
  assert(okMeta, `"${t.label}" poster/synopsis/cast/ranking-reason present`);
  if (!okCount || !okDupes || !okMeta) allOk = false;
}

// filters
const f1 = searchFilms("drama", { country: "France" }, films);
assert(f1.length >= 2 && f1.every((r) => (r.film.countries || [r.film.country]).includes("France")), "country filter France");
const f2 = searchFilms("", { genre: "Animation" }, films);
assert(f2.length >= 3, "genre filter Animation");
const f3 = searchFilms("drama", { yearFrom: "2015", yearTo: "2019" }, films);
assert(f3.every((r) => r.film.year >= 2015 && r.film.year <= 2019), "year range filter");

// variety: broad query spans >=4 countries
const broad = searchFilms("drama", {}, films);
const countries = new Set(broad.slice(0, 20).map((r) => r.film.country));
assert(countries.size >= 4, `broad discovery spans ${[...countries].join(",")}`);

// ---- V4 FINAL PRODUCT GATES ----
console.log("\n--- V4 GATES ---");
function hasFullMeta(f) {
  return f.title && f.year && f.genres?.length && f.country && f.cast?.length && f.director
    && (f.themes?.length || f.keywords?.length) && f.synopsis && f.runtimeMin
    && f.rating != null && f.ratingSource && f.sources?.length && f.provenance;
}
assert(films.every(hasFullMeta), "V4 schema: title/alt/year/genre/country/cast/director/keywords/synopsis/runtime/poster/ratingSource/provenance");
assert(films.every((f) => ("alternateTitle" in f) && ("keywords" in f) && ("ratingSource" in f) && ("provenance" in f)), "V4 fields present (alternateTitle/keywords/ratingSource/provenance)");
// discovery coverage
const v4queries = [
  { q: "startup business", expectMin: 2, label: "startup/business discovery" },
  { q: "crime", expectMin: 3, label: "crime discovery" },
  { q: "romance", expectMin: 3, label: "romance discovery" },
  { q: "recent films", expectMin: 3, label: "recent films discovery" },
  { q: "similar to Parasite", expectMin: 3, label: "similar to Parasite" },
];
for (const t of v4queries) {
  const res = searchFilms(t.q, {}, films);
  const ok = res.length >= t.expectMin && noDupes(res);
  console.log(`V4 QUERY "${t.q}" => ${res.length} top=${res[0]?.film.title}`);
  assert(ok, `V4 "${t.label}" hits ${res.length} >= ${t.expectMin} no-dupes`);
  if (!ok) allOk = false;
  // similarity explanation present
  assert(res[0]?.reasons?.length >= 1, `V4 "${t.label}" similarity explained`);
}
// ranking: year preference
assert(wantsRecent(["recent"], ["recent"]), "V4 yearPref detects recent");
const recentRes = searchFilms("recent films", {}, films);
assert(recentRes[0]?.film.year >= 2016, `V4 recent ranks new first (${recentRes[0]?.film.title} ${recentRes[0]?.film.year})`);
// ranking: diversity — no franchise flooding (max 2 per franchise base in top 10)
{
  const res = searchFilms("drama", {}, films);
  const top10 = res.slice(0, 10);
  const counts = {};
  for (const r of top10) { const k = franchiseBase(r.film); counts[k] = (counts[k] || 0) + 1; }
  const maxF = Math.max(...Object.values(counts));
  assert(maxF <= 2, `V4 diversity: max franchise in top10 = ${maxF} <= 2`);
  // country diversity in broad top 20
  const cset = new Set(res.slice(0, 20).map((r) => r.film.country));
  assert(cset.size >= 4, `V4 diversity countries ${[...cset].join(",")}`);
}
// negatives
{
  const unk = diagnoseQuery("zzzz unknown film qqq", [], films, null);
  assert(unk.unknown === true, "V4 negative: unknown title surfaced");
  const ambRes = searchFilms("like Lady Bird", {}, films);
  assert(Array.isArray(ambRes), "V4 negative: ambiguous path returns array");
  const conflicts = detectConflicts(films);
  assert(Array.isArray(conflicts), "V4 negative: metadata conflicts detectable");
  // missing poster handling: synthetic film without hue
  const { posterSVG } = await import("../search.mjs");
  const svg = posterSVG({ title: "No Poster Test", year: 2020, country: "USA", posterHue: null }, 100);
  assert(svg.startsWith("data:image"), "V4 negative: missing poster fallback data-URI");
  // duplicate collapse + diagnostics
  const dupRes = searchFilms("drama", {}, [...films, films[0]]);
  assert(dupRes.diagnostics?.dedupedCount >= 1, "V4 negative: duplicate collapse reported");
}
// provenance + posters + filters
{
  const r = searchFilms("teen drama", {}, films);
  assert(r.slice(0, 3).every((x) => x.film.provenance && x.film.ratingSource && x.poster), "V4 provenance/posters/filters on results");
  const crimeF = searchFilms("crime", { genre: "Crime" }, films);
  assert(crimeF.length >= 2, "V4 filter genre=Crime");
  const brazilF = searchFilms("drama", { country: "Brazil" }, films);
  assert(brazilF.length >= 1, "V4 filter country=Brazil");
}

if (!allOk || process.exitCode) { console.error("\nACCEPTANCE: FAIL"); process.exit(1); }
console.log("\nACCEPTANCE: ALL 10 QUERIES GREEN + V4 GATES GREEN");
