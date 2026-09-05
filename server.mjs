import http from "node:http";
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadFilms, searchFilms, posterSVG, dedupeFilms, detectConflicts, diagnoseQuery } from "./search.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const PUB = path.join(here, "public");
const HIST = path.join(here, "data", "history.json");

function loadHistory() {
  try {
    if (!existsSync(HIST)) return [];
    return JSON.parse(readFileSync(HIST, "utf8"));
  } catch { return []; }
}
function appendHistory(entry) {
  const h = loadHistory();
  h.unshift({ ...entry, ts: new Date().toISOString() });
  const trimmed = h.slice(0, 100);
  mkdirSync(path.dirname(HIST), { recursive: true });
  writeFileSync(HIST, JSON.stringify(trimmed, null, 2));
  return trimmed;
}

function send(res, code, body, type = "application/json") {
  res.writeHead(code, { "content-type": type + "; charset=utf-8", "access-control-allow-origin": "*" });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, "http://127.0.0.1");
  if (u.pathname === "/api/health") {
    try {
      const films = loadFilms();
      const conflicts = detectConflicts(films);
      return send(res, 200, JSON.stringify({ ok: true, service: "film-search", version: "4.0.0", count: films.length, deduped: dedupeFilms(films).length, conflicts: conflicts.length, boundary: "metadata/search/discovery only — no streaming/download" }));
    } catch (e) { return send(res, 500, JSON.stringify({ ok: false, error: String(e).slice(0, 300) })); }
  }
  if (u.pathname === "/api/search") {
    const q = u.searchParams.get("q") || "";
    const filters = {};
    for (const k of ["genre", "country", "year", "yearFrom", "yearTo", "ageTarget", "ageMax"]) {
      const v = u.searchParams.get(k);
      if (v) filters[k] = v;
    }
    try {
      const results = searchFilms(q, filters);
      const diag = results.diagnostics || diagnoseQuery(q, results, dedupeFilms(loadFilms()), null);
      appendHistory({ q, filters, hits: results.length });
      return send(res, 200, JSON.stringify({
        query: q, filters, count: results.length,
        diagnostics: { unknown: !!diag.unknown, ambiguous: !!diag.ambiguous, notes: diag.notes || [], dedupedCount: diag.dedupedCount ?? 0, yearPref: !!diag.yearPref, similarAnchor: diag.similarAnchor || null },
        results: results.slice(0, 40).map((r) => ({
          id: r.film.id, title: r.film.title, alternateTitle: r.film.alternateTitle ?? null,
          year: r.film.year, country: r.film.country, countries: r.film.countries || [r.film.country],
          genres: r.film.genres, themes: r.film.themes, keywords: r.film.keywords || [], moods: r.film.moods,
          ageTarget: r.film.ageTarget, ageMin: r.film.ageMin,
          synopsis: r.film.synopsis, cast: r.film.cast, director: r.film.director, runtimeMin: r.film.runtimeMin,
          rating: r.film.rating, ratingSource: r.film.ratingSource || "unknown — surface uncertainty",
          sources: r.film.sources, provenance: r.film.provenance || { origin: "curated-local", sources: r.film.sources || [] },
          poster: r.poster, posterMissing: !!r.posterMissing,
          score: r.score, reasons: r.reasons, uncertainty: r.uncertainty || []
        }))
      }));
    } catch (e) { return send(res, 500, JSON.stringify({ ok: false, error: "search failed", detail: String(e).slice(0, 300) })); }
  }
  if (u.pathname === "/api/film") {
    const id = u.searchParams.get("id");
    const f = loadFilms().find((x) => x.id === id);
    if (!f) return send(res, 404, JSON.stringify({ ok: false, error: "unknown title id", hint: "try /api/search?q=teen drama" }));
    const uncertainty = [];
    if (f.posterHue == null) uncertainty.push("missing poster: placeholder shown");
    if (!f.ratingSource) uncertainty.push("rating provenance missing");
    return send(res, 200, JSON.stringify({ ...f, poster: posterSVG(f, 320), posterMissing: f.posterHue == null, uncertainty }));
  }
  if (u.pathname === "/api/diagnostics" && req.method === "GET") {
    try {
      const films = loadFilms();
      const conflicts = detectConflicts(films);
      const countries = [...new Set(films.map((f) => f.country))];
      const genres = [...new Set(films.flatMap((f) => f.genres || []))];
      return send(res, 200, JSON.stringify({ ok: true, count: films.length, deduped: dedupeFilms(films).length, countries, genres, conflicts, provenance: "curated-local + TMDB/OMDb/Wikidata snapshots; live via /api/live (Wikipedia, keyless)" }));
    } catch (e) { return send(res, 500, JSON.stringify({ ok: false, error: String(e).slice(0, 300) })); }
  }
  if (u.pathname === "/api/live" && req.method === "GET") {
    // Live public metadata smoke: Wikipedia REST summary (keyless, legitimate). Never fabricates.
    const title = (u.searchParams.get("title") || u.searchParams.get("q") || "").trim();
    if (!title) return send(res, 400, JSON.stringify({ ok: false, error: "missing ?title=", provider: "wikipedia" }));
    const wikiTitle = title.replace(/\s+/g, "_");
    // Also resolve local match for cross-check (no fabrication)
    const local = loadFilms().find((f) => f.title.toLowerCase() === title.toLowerCase() || String(f.alternateTitle || "").toLowerCase() === title.toLowerCase()) || null;
    try {
      const ctl = new AbortController();
      const t = setTimeout(() => ctl.abort(), 8000);
      const r = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(wikiTitle)}`, { signal: ctl.signal, headers: { "user-agent": "film-search/4.0 (metadata-smoke)" } });
      clearTimeout(t);
      if (!r.ok) {
        return send(res, 200, JSON.stringify({ ok: false, provider: "wikipedia", providerDown: r.status >= 500, status: r.status, title, local: local ? { id: local.id, title: local.title, year: local.year } : null, note: r.status === 404 ? `unknown title on Wikipedia: "${title}"` : `provider returned ${r.status} — surface uncertainty, local catalogue still available` }));
      }
      const j = await r.json();
      return send(res, 200, JSON.stringify({
        ok: true, provider: "wikipedia", provenance: j.content_urls?.desktop?.page || `https://en.wikipedia.org/wiki/${encodeURIComponent(wikiTitle)}`,
        title: j.title || title, extract: (j.extract || "").slice(0, 600), thumbnail: j.thumbnail?.source || null,
        local: local ? { id: local.id, title: local.title, year: local.year, ratingSource: local.ratingSource } : null,
        note: "Live public metadata (Wikipedia). Local curated record is authoritative for ranking; live is cross-check only."
      }));
    } catch (e) {
      return send(res, 200, JSON.stringify({ ok: false, provider: "wikipedia", providerDown: true, title, local: local ? { id: local.id, title: local.title, year: local.year } : null, error: String(e).slice(0, 300), note: "provider down — surface uncertainty, local catalogue still available" }));
    }
  }
  if (u.pathname === "/api/history" && req.method === "GET") return send(res, 200, JSON.stringify(loadHistory()));
  if (u.pathname === "/api/save" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      try {
        const j = JSON.parse(body || "{}");
        const saved = appendHistory({ q: "SAVE:" + (j.id || j.title || "?"), filters: {}, hits: 1, saved: j });
        return send(res, 200, JSON.stringify({ ok: true, history: saved.slice(0, 5) }));
      } catch { return send(res, 400, JSON.stringify({ ok: false })); }
    });
    return;
  }
  // static
  let p = u.pathname === "/" ? "/index.html" : u.pathname;
  const fp = path.join(PUB, decodeURIComponent(p).replace(/^\//, ""));
  if (!fp.startsWith(PUB) || !existsSync(fp)) return send(res, 404, "not found", "text/plain");
  const ext = path.extname(fp);
  const type = ext === ".html" ? "text/html" : ext === ".js" ? "text/javascript" : ext === ".css" ? "text/css" : "application/octet-stream";
  return send(res, 200, readFileSync(fp), type);
});

const cliPort = process.argv.includes("--port") ? Number(process.argv[process.argv.indexOf("--port") + 1]) : null;
const port = Number(cliPort || process.env.FILM_SEARCH_PORT || process.env.PORT || 8791);
const fallbackPort = Number(process.env.FILM_SEARCH_FALLBACK_PORT || 18091);
function boot(p, isFallback = false) {
  server.listen(p, "127.0.0.1", () => console.log(`film-search listening http://127.0.0.1:${p}/ films=${loadFilms().length} deduped=${dedupeFilms(loadFilms()).length}${isFallback ? " (fallback: primary 8791 EACCES-blocked)" : ""}`));
}
server.on("error", (e) => {
  if ((e.code === "EACCES" || e.code === "EADDRINUSE") && port !== fallbackPort) {
    console.error(`film-search port ${port} unavailable (${e.code}); retrying fallback ${fallbackPort}`);
    setTimeout(() => boot(fallbackPort, true), 300);
  } else { console.error("film-search listen failed", e.code || e.message); process.exit(1); }
});
boot(port);
