# Enrichment-Layer Cache Migration Plan

Move all hot-path grounding caches from the backend into the
enrichment-layer service so cache keys live in the same process as
the values they protect.

## Motivation

The current cache (`backend/cached_enrichment_client.py`,
`backend/grounding_cache.py`) is structurally dead on the live session
path:

- `ground_multimodal` cannot check the cache before the upstream call,
  because the cache key (the refined query list, the resolved app/OS)
  is produced *by* the multimodal planner call itself.
- The cache only writes; nothing in `tutorial_session` ever calls the
  single-query `ground(query)` path that would read those writes.
- No URL-level cache exists on the backend, because the backend never
  sees URLs — they are an internal artifact of the enrichment-layer
  fetch stage.

Result: every `/snippets` call pays the full ~20s cost, even when the
same goal is repeated in the same app on the same OS.

## End-state architecture

```
backend  ──HTTP──>  enrichment-layer
                      ├── /snippets (hot path, caches at every stage)
                      ├── /plan_queries  (split — see Phase 2)
                      └── /snippets_for  (split — see Phase 2)
```

The enrichment-layer owns all grounding caches. The backend's
`cached_enrichment_client.py` collapses into a thin HTTP client.
`grounding_cache.py` stays on the backend only for its non-grounding
callers (verifier reconciliation, `logical_id` assignment).

## Cache layers

Four caches, layered from cheap to expensive. Each is read on the way
down and populated on the way up. A hit at any layer short-circuits
the layers below it.

| Layer | Key | Value | Cost saved on hit | TTL |
|---|---|---|---|---|
| L1 — multimodal plan | `sha256(goal \| app_hint \| os_hint \| image_perceptual_hash)` | `{app, os, queries, goal_facets}` | ~3–5s LLM + image upload | 7 days |
| L2 — final snippets | `sha256(sorted(queries) \| app \| os)` | `list[Snippet]` | ~15–18s (all of L3 + L4) | 24h |
| L3 — search hits | `sha256(query)` | `list[SearchHit]` | ~0.3–1s Brave call | 24h |
| L4 — fetch + extract | `url` | `ExtractedPage` | ~0.5–2s HTTP + trafilatura | 7 days |
| L5 — page summary | `sha256(content_hash \| goal \| app)` | `snippet_text` | ~1–3s gpt-4o-mini call | 30 days |

Notes:

- L4 keys by URL, not `content_hash`, because we don't know the hash
  until we fetch. Internally, after fetching, dedup by `content_hash`
  so identical content under different URLs shares L5 entries.
- L5's long TTL is safe: it's `(page_content, goal)`-pure; if the page
  changes, `content_hash` changes and we get a new key naturally.
- L1 uses a perceptual hash (not SHA of bytes) so trivial screenshot
  differences (cursor moved, clock ticked) still hit. Reuse the same
  image-hash util the verifier downscaler uses.

## Storage backend

All layers use **in-memory storage for now**, behind a generic
abstraction so swapping in Redis, SQLite, or anything else is a
one-file change.

```python
# enrichment-layer/src/enrichment/cache/storage.py

class StorageProvider(Protocol[K, V]):
    def get(self, key: K) -> V | None: ...
    def put(self, key: K, value: V, *, ttl_seconds: float | None) -> None: ...
    def delete(self, key: K) -> None: ...
    def stats(self) -> StorageStats: ...

class InMemoryStorage(StorageProvider[K, V]):
    """TTL + max-size LRU eviction. Process-local. Thread-safe."""
```

Module-scope singletons per layer, each parameterized with its own
`StorageProvider` instance and key/value types. Cache logic
(key normalization, paraphrase matching, negative caching) lives
in a layer-specific wrapper, not in the storage itself — the
storage knows nothing about embeddings or TTLs by domain.

No persistence in this iteration. Cold start drops all caches.
This is fine for the MVP — Phase 4 observability will tell us if
warm-cache lifetime matters enough to add persistence.

## Negative caching

L2 and L3 should record "known empty" results with a shorter TTL
(~1h) to prevent retrying obviously-bad query plans. Mirror the
shape of the existing `NegativeQueryCache` on the backend.

## Paraphrase matching (built in from Phase 1)

L1 (multimodal plan) and L2 (final snippets) use **embedding-based
similarity lookup** for keys. "Ship to Cloud Run" and "Deploy to
Cloud Run" hit the same entry.

- New `enrichment-layer/src/enrichment/embeddings.py`. Small wrapper
  around `openai.embeddings` (dep already present). Pure function:
  `embed(text: str) -> list[float]`. Batched where possible.
- The wrapper cache stores embeddings alongside values. Lookup is:
  1. Embed the incoming key.
  2. Cosine over stored embeddings in the same partition.
  3. Return the value if max similarity ≥ 0.92, else miss.
- Cosine threshold and partition key live in
  `cache/grounding_cache.py`, not in `StorageProvider`. Storage is
  domain-agnostic.
- L3 (search hits), L4 (fetch+extract), L5 (page summary) stay on
  exact-string / URL / content-hash keys. They're already
  deterministic — no paraphrase variance to absorb.

The embedding lookup adds ~50–150ms per cache check (one OpenAI
embeddings call, batched across concurrent requests where the
event loop allows). Acceptable: a hit still saves 15–25s.

## Phases

Each phase is independently shippable and measurable.

### Phase 1 — Storage abstraction + deterministic caches inside `/snippets`

Smallest shippable slice. No new endpoints. No backend changes.

- Add `enrichment-layer/src/enrichment/cache/` package:
  - `storage.py` — `StorageProvider[K, V]` Protocol +
    `InMemoryStorage` implementation (TTL + max-size LRU,
    thread-safe).
  - `embeddings.py` — small `openai.embeddings` wrapper.
  - `grounding_cache.py` — layer-specific wrappers (L3, L4, L5
    in this phase; L1, L2 added in Phase 2). Each wrapper owns
    its key shape, TTL, and (for L1/L2) the embedding threshold.
- Wire L3 inside `search.fan_out_search` (per-query, exact-string).
- Wire L4 inside `fetch.fan_out_fetch` (per-URL, exact-string).
- Wire L5 inside `snippets.run_snippet_pipeline` (per
  `(content_hash, goal, application)`).
- Add `[cache]` log lines on every hit, miss, and put. Include
  layer name, key preview, age, storage size.

**Acceptance:** a repeated `/snippets` call with the same goal +
screenshot completes in <8s (L5 hits skip 5 summarizer calls;
L4 hits skip ~20 fetches). Logs show `[cache] hit layer=L5` etc.

**Risk:** none. Strictly additive. Pure functions in / pure functions
out. If any cache layer throws, log and fall through.

### Phase 2 — Split `/snippets` into `/plan_queries` + `/snippets_for`

Enables L1 and L2.

- Extract the multimodal planner call from
  `app.py::snippets` into a new `POST /plan_queries`:
  - Input: `query` (raw goal), optional `image`, optional
    `application` hint.
  - Output: `{application, environment, goal_facets, queries}`.
- Extract the rest of the pipeline into a new
  `POST /snippets_for`:
  - Input: `queries: list[str]`, `application`, `goal`,
    `num_sources`.
  - Output: the existing `SnippetsResponse` shape minus the
    plan fields.
- Reimplement the existing `POST /snippets` as a thin wrapper
  that calls both internally. Backward-compatible — the backend
  doesn't need to change yet.
- Wire L1 inside `/plan_queries`: embedding-based lookup on the
  goal text, partitioned by perceptual hash of the screenshot
  (or `None` if no image). Cosine threshold 0.92.
- Wire L2 inside `/snippets_for`: embedding-based lookup on the
  sorted-and-joined query list, partitioned by `(app, os)`.
  Cosine threshold 0.92.

**Acceptance:** the wrapper `/snippets` still produces identical
output. Repeated calls now skip the multimodal planner on L1 hit
and the entire downstream pipeline on L2 hit.

**Risk:** small. The wrapper preserves backward compatibility, so
the backend can adopt the split lazily.

### Phase 3 — Backend cleanup

- Delete the multimodal-side population logic in
  `backend/cached_enrichment_client.py` — it's now dead.
- Keep `backend/grounding_cache.py` only for its non-grounding
  callers (verifier reconciliation at `tutorial_session.py:1203`,
  `logical_id` assignment at `tutorial_session.py:1539`). Rename
  to clarify scope (e.g. `embedding_match_cache.py`).
- Delete `backend/tests/test_cached_enrichment_client.py`
  multimodal cases. Keep coverage for the single-query path if
  any internal caller still uses it; otherwise delete the file.
- Update `backend/enrichment_client.py` to log the new
  enrichment-side cache headers (Phase 4) when present.

**Acceptance:** backend has no grounding-cache code path. All
cache logs originate from enrichment-layer.

### Phase 4 — Observability

- Add response headers from enrichment-layer indicating which
  layers hit/missed for this request:
  `X-Cache-L1: hit`, `X-Cache-L2: miss`, etc.
- Backend logs these in the existing
  `[enrichment] ground end` line so per-session traces show cache
  behavior without grepping two services' logs.
- Add `/cache/stats` endpoint on enrichment-layer returning
  per-layer hit count, miss count, evictions, and current size.
  Useful for tuning TTLs.

**Acceptance:** a single backend log line tells you the cache hit
profile of any grounding call. `/cache/stats` shows non-zero hits
after a demo replay.

## Non-goals for this migration

- Multi-process / Redis sharing. Single enrichment-layer process
  is fine for the MVP. The `Cache[K, V]` Protocol leaves the door
  open.
- Crawler / pre-warmed index. The cache only populates on demand
  from real user traffic.
- Replacing trafilatura / BeautifulSoup. Out of scope.
- Replacing Brave. Out of scope.

## Open questions

1. **Should L1's image hash use the downscaled-verifier image or
   the original?** Probably downscaled — same perceptual signal,
   smaller cache key, robust to minor differences. Need to confirm
   the downscaling util is reachable from enrichment-layer (it
   currently lives in backend; may need to lift it).

2. **Cache key for L5 includes `application`** — but what about
   `environment` (e.g. macOS version)? Likely irrelevant for
   page summaries; defer until we see a counter-example.

3. **What happens when `/plan_queries` is called without an
   image?** Current code falls back to `[raw_request]` as the
   single query. L1 should still cache this case keyed on goal
   alone — confirm the key shape handles `image_hash=None`.

4. **TTL sweep strategy.** Per-call expiration check on read is
   simplest; a background sweep is overkill at MVP scale. Revisit
   if cache size grows unbounded between user sessions.

## Success criteria

- Repeating "create emoji" in Slack twice: second call returns
  in <2s (vs ~24s today).
- Cold goal in known app/OS: L3 + L4 hits on overlap with prior
  unrelated goals (e.g. both surface the same Slack help page) —
  saves at least 1 summarizer call typically.
- `/cache/stats` shows non-zero hits within a single 10-minute
  demo session.
- No correctness regressions: snippets returned with cache hits
  are byte-identical to snippets returned without (verified by
  a comparison harness running both paths during Phase 1).
