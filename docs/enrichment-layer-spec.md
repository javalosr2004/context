# enrichment-layer — Implementation Spec

A spec for a coding agent to build `enrichment-layer`, the first container of a web/video tutorial enrichment system. Build phases in order; each phase is independently testable. Do not skip ahead. Where a decision is marked **LOCKED** it is not open for reinterpretation; where marked **OPEN** it must be surfaced to the human before the dependent phase begins.

---

## 1. Purpose and scope

`enrichment-layer` takes a raw user request describing a goal in some software application, generates web search queries, executes them against Brave Search, fetches and classifies the returned pages, extracts structured tutorial content, and persists everything — raw and parsed — as an auditable dataset partitioned by `(app_id, goal)`.

The dataset is the product. Every search, every page, every classification decision is stored so the human can later sift the corpus, identify which query phrasings surface good tutorials, and refine. Build the capture solidly; do not build quality ranking.

**In scope for this build:** the web enrichment pipeline end to end, in a single container.

**Explicitly out of scope:** the video enrichment layer (YouTube transcript mining, `ActionVideoParser`, mouse-coordinate extraction). It is a separate future build. The only concession to it here is a `source_type` field in the schema so its records share this schema later without a migration.

**Anti-goals:** do not split into multiple containers now; do not build quality scoring or ranking now; do not build a UI.

---

## 2. Architecture

A single container, `enrichment-layer`, running a FastAPI service. All work happens in-process except headless-browser rendering, which sits behind a clean interface so it can be extracted into its own container later as a mechanical change.

Pipeline, end to end:

```
raw request
  → QueryGenerator         produces QueryPlan {application, goal, queries[]}
  → ApplicationResolver    fuzzy-matches plan.application → app_id (or NULL)
  → web_search_tool        fans queries to Brave, concurrent
  → BraveClient            per-query results, cached by normalized query
  → dedup by URL (per search; cross-search dedup is implicit via content_hash)
  → Fetcher                cheap httpx GET per URL  → raw HTML
  → JsClassifier           scores HTML, decides render/no-render
  → Renderer               (only if escalated) Playwright re-fetch → rendered HTML
  → Preprocessor           trafilatura extraction + structural features → parsed record
  → Storage                blobs to filesystem, metadata to SQLite index
  → JSON export
```

Three components sit behind interfaces so the implementation can be swapped without touching the pipeline: `QueryGenerator`, `BraveClient`, `Renderer`. Each ships with a fake. The fakes exist as much for testing as for swapping — they let the whole pipeline run in tests with no network and no API spend.

---

## 3. Repository layout

```
enrichment-layer/
  pyproject.toml
  Dockerfile
  docker-compose.yml
  alembic.ini
  .env.example
  README.md
  src/enrichment/
    __init__.py
    config.py            settings via pydantic-settings, all env-driven
    app.py               FastAPI app, routes, lifespan
    models.py            Pydantic domain models (QueryPlan, etc.)
    db/
      __init__.py
      schema.py          SQLAlchemy table definitions
      engine.py          engine + session factory, WAL pragma
      migrations/        Alembic
    storage/
      __init__.py
      blobs.py           content-addressed blob store (filesystem)
      index.py           index DB read/write operations
    query/
      __init__.py
      base.py            QueryGenerator interface
      openai_gen.py      OpenAIQueryGenerator
      fake.py            FakeQueryGenerator
      prompt.py          QUERY_GEN_PROMPT
    apps/
      __init__.py
      resolver.py        ApplicationResolver — fuzzy match plan.application → app_id
      seed.py            initial applications/aliases seed data
    search/
      __init__.py
      base.py            BraveClient interface
      brave.py           real Brave client
      fake.py            FakeBraveClient
      cache.py           search-response cache
    fetch/
      __init__.py
      fetcher.py         cheap httpx GET
      classifier.py      JsClassifier — layered JS-detection
      renderer_base.py   Renderer interface
      playwright_renderer.py
      fake_renderer.py
      domain_cache.py    per-domain render verdict cache
    preprocess/
      __init__.py
      extract.py         trafilatura main-content extraction
      features.py        BeautifulSoup structural feature capture
    pipeline.py          orchestration: wires the stages
    export.py            JSON export of a run
    tools.py             web_search_tool definition (agent-facing)
  tests/
    conftest.py
    fixtures/            saved HTML pages, saved Brave responses
    ...
```

---

## 4. Data model

### 4.1 Blob store — filesystem, content-addressed

Heavy data never goes in the database. Hash raw bytes with SHA-256, store the blob once under its hash, reference it by hash from the index. Hashing dedupes for free: the same tutorial reached by three queries is one blob with three query edges.

```
data/
  runs/{run_id}/meta.json            application, goal, raw_request, queries,
                                     model name, prompt, raw completion, timestamps
  searches/{query_hash}.json         raw Brave response (also the cache)
  pages/{content_hash}.html          raw HTML (pre-render)
  pages/{content_hash}.rendered.html rendered HTML (only if escalated)
  parsed/{content_hash}.json         structured extraction + features
```

`query_hash` = SHA-256 of the normalized query string (lowercased, collapsed whitespace, trimmed). `content_hash` = SHA-256 of the raw HTML bytes. `run_id` = UUID generated in Python.

### 4.2 Index DB — SQLite now, Postgres later

**LOCKED:** SQLite to start, accessed exclusively through SQLAlchemy with Postgres-portability discipline. Do not write raw `sqlite3` SQL. Do not use `AUTOINCREMENT` rowids as durable keys — generate UUIDs in Python. Do not use SQLite-only SQL (`INSERT OR REPLACE`, `strftime`); use SQLAlchemy's `upsert` construct and pass real `datetime` objects. Declare strict column types (`TEXT`, `INTEGER`, `TIMESTAMP`, `JSON`, `FLOAT`). Manage schema with Alembic from the first commit so the Postgres schema is generated for free later. Enable WAL mode (`PRAGMA journal_mode=WAL`) on connect.

Tables:

**`applications`** — canonical software-application registry. Seeded manually; grows as new apps are promoted from unresolved runs.
`app_id` (UUID, PK), `canonical_name` (TEXT, unique, e.g. `"Figma"`), `aliases` (JSON, list of normalized alias strings, e.g. `["figma", "figma desktop", "figma web"]`), `created_at` (TIMESTAMP).

**`runs`** — one row per request.
`run_id` (UUID, PK), `raw_request` (TEXT), `application` (TEXT, raw LLM output preserved for audit), `application_confidence` (FLOAT, from the LLM), `app_id` (UUID, FK → `applications.app_id`, nullable — NULL means no fuzzy match above threshold), `app_match_score` (FLOAT, nullable — the fuzzy score that produced the match, or the best below-threshold score when NULL), `goal` (TEXT), `source_type` (TEXT, `'web'` for this build), `model_name` (TEXT), `created_at` (TIMESTAMP), `status` (TEXT).

**`searches`** — one row per query executed within a run.
`search_id` (UUID, PK), `run_id` (FK), `query_text` (TEXT), `query_hash` (TEXT), `cache_hit` (BOOLEAN), `result_count` (INTEGER), `executed_at` (TIMESTAMP).

**`pages`** — one row per unique page (by `content_hash`). Pages are shared across searches and runs. `url` here is a representative URL (whichever arrived first); authoritative per-search URLs live on `search_pages` via the originating Brave result.
`content_hash` (TEXT, PK), `url` (TEXT), `domain` (TEXT), `http_status` (INTEGER), `fetched_at` (TIMESTAMP), `fetch_ms` (INTEGER), `render_decision` (TEXT: `'none'` | `'rendered'`), `render_signal` (TEXT: which classifier signal triggered escalation, null if none), `js_score` (FLOAT), `rendered` (BOOLEAN).

**`search_pages`** — edge table linking searches to pages (many-to-many).
`search_id` (FK), `content_hash` (FK), `rank` (INTEGER, position in Brave results). Composite PK `(search_id, content_hash)`.

**`parsed`** — one row per page that produced an extraction.
`content_hash` (TEXT, PK/FK), `extracted_ok` (BOOLEAN), `text_length` (INTEGER), `ordered_list_items` (INTEGER), `imperative_verb_density` (FLOAT), `screenshot_count` (INTEGER), `application_term_present` (BOOLEAN), `goal_term_present` (BOOLEAN), `features` (JSON, full structural feature blob), `parsed_at` (TIMESTAMP).

**`domain_render_cache`** — learned render verdicts keyed by domain.
`domain` (TEXT, PK), `verdict` (TEXT: `'server'` | `'client'`), `confidence` (FLOAT), `sample_count` (INTEGER), `manually_seeded` (BOOLEAN), `updated_at` (TIMESTAMP).

---

## 5. Component contracts

### 5.1 QueryGenerator — `query/`

**LOCKED:** in-process, not a separate service. It is one stateless async call. Behind an interface so the model provider can change.

```python
class QueryGenerator(ABC):
    @abstractmethod
    async def generate(self, raw_request: str) -> QueryPlan: ...
```

`QueryPlan` is a Pydantic model: `application: str`, `application_confidence: float`, `goal: str`, `queries: list[str]`, `raw_request: str`. It is both the validation boundary and — for the OpenAI implementation — the response schema.

`OpenAIQueryGenerator` uses the OpenAI **Responses API** (`client.responses.parse` with `text_format=QueryPlan`), the actively-developed surface. Requirements:
- Verify exact SDK argument names (`responses.parse`, `text_format`) against current OpenAI Python docs at build time; the SDK revises.
- Handle refusals: a refusal does not conform to the schema and is exposed on a separate `refusal` field. Check for it before assuming a parsed plan exists. On refusal, raise `QueryGenerationRefused`.
- Enforce semantics in code, not via schema: cap `queries` at `MAX_QUERIES` (config, default 5) — JSON Schema `maxItems` is not reliably enforced by structured outputs. All schema fields must be required; express optionality as a union with `null`, not omission.
- Set `raw_request` on the returned plan from the input argument; do not trust the model to echo it.

`FakeQueryGenerator` returns a fixed `QueryPlan` from a lookup or a default. No network.

**Auditability:** persist the system prompt, model name, and raw completion into `runs/{run_id}/meta.json`. The query generator is part of the dataset — "the LLM picked weak queries" is a diagnosable failure only if the exact prompt and response are on disk.

### 5.2 ApplicationResolver — `apps/`

**LOCKED:** runs after `QueryGenerator`, before search. Resolves `plan.application` (raw LLM string) to a canonical `app_id` so the corpus partitions cleanly. Without this, "Figma" / "figma" / "Figma Desktop" fragment the dataset and silently defeat the refinement loop.

```python
@dataclass(frozen=True)
class AppResolution:
    app_id: UUID | None
    score: float          # fuzzy match score (0–100); best candidate even when None
    matched_name: str | None

class ApplicationResolver:
    def __init__(self, session_factory, threshold: float = 90.0): ...
    def resolve(self, raw_application: str) -> AppResolution: ...
```

Algorithm:
1. Normalize input: lowercase, strip, collapse internal whitespace.
2. Exact match against `canonical_name` (normalized) and every entry in `aliases` across all rows in `applications`. Exact hit → score 100, return immediately.
3. Otherwise fuzzy match with `rapidfuzz.process.extractOne` over the union of canonical names and aliases, using `WRatio`. Threshold default 90 (config-driven).
4. Below threshold → return `AppResolution(app_id=None, score=best, matched_name=best_candidate)`. The raw LLM string is still preserved on `runs.application`; `runs.app_match_score` records the best score so the human review queue can sort by "almost-matched."

Seed data lives in `apps/seed.py` (a small initial list of applications the system already supports) and is applied via an Alembic data migration. Promoting an unresolved run's `application` into the registry is a manual operation for now — a CLI command (`enrichment apps promote <run_id>`) creates a new `applications` row using the raw string as `canonical_name` and the run's normalized form as the first alias. No automatic promotion in this build.

**OPEN:** fuzzy threshold (90 is a starting guess; tune against the first batch of real runs).

### 5.3 BraveClient — `search/`

```python
class BraveClient(ABC):
    @abstractmethod
    async def search(self, query: str) -> BraveResult: ...
```

Real client: async `httpx` wrapper over the Brave Search API. **LOCKED:** Brave is 50 QPS, so no token-bucket rate limiter — a plain `asyncio.gather` over the query list bounded by an `asyncio.Semaphore` (config `BRAVE_CONCURRENCY`, default 10–20) to cap open sockets, not to throttle Brave.

**OPEN:** Brave's monthly request cap depends on plan tier and must be confirmed before fan-out is treated as free. Every run multiplies (~5 queries/run). Surface this to the human.

**Search-response cache** (`search/cache.py`): before billing a query, check for `searches/{query_hash}.json` on disk; on hit, load and skip the API call, set `cache_hit=True`. The LLM generates near-duplicate queries and identical queries recur across test runs — the cache protects the monthly cap. Dedup the LLM's query list (by `query_hash`) before dispatch.

`FakeBraveClient` returns saved responses from `tests/fixtures/`.

### 5.4 Fetcher — `fetch/fetcher.py`

Plain `httpx` GET per URL. Always runs first regardless of later render decision — the raw HTML is needed for the dataset and costs one request. Returns raw HTML bytes, HTTP status, timing, final URL. Reasonable timeout, a real User-Agent, capped redirects.

### 5.5 JsClassifier — `fetch/classifier.py`

**LOCKED:** runs after the cheap fetch, emits a `js_score` (higher = more likely to need rendering) and the name of the signal that drove the decision. The classifier asks one question only: **is this page a JavaScript SPA shell that needs rendering before extraction will work?** All signals serve that one decision. Layered, evaluated in this order:

1. **`<noscript>` "enable JavaScript" text** — explicit declaration the page is client-rendered. Strong escalate.
2. **Framework shell markers** — `<div id="root">` / `<div id="app">` with an otherwise empty body, `data-reactroot`, `ng-version`, `window.__NUXT__`. Strong SPA signal.
3. **Embedded server-rendered state** — `__NEXT_DATA__`, JSON-LD, hydration blobs. This is the *good* case: content already sits in the HTML as JSON; extract without rendering. Lowers the score.
4. **Content ratio** — extracted visible-text length over raw HTML length, combined with script-tag count. Low text + many scripts → client-rendered.
5. **Cheap structural probe** — a fast BeautifulSoup pass on the raw HTML asking whether the body contains any meaningful content elements at all (`<h1>`/`<h2>`/`<ol>`/`<p>` with non-trivial text). An empty body sitting under `<div id="root">` is the SPA tell. This is a lightweight presence check — *not* a quality extraction. Trafilatura is not used here; it runs later in the preprocessor on whichever HTML (raw or rendered) the pipeline ultimately commits to.

Below a configurable threshold the page is escalated to the `Renderer`. Log `js_score` and `render_signal` on the `pages` row for every page — missed escalations and wasted renders are both auditable, and that audit is the refinement loop.

**Domain cache** (`fetch/domain_cache.py`): before running the full classifier, check `domain_render_cache` for a known verdict for the page's domain; tutorial sources repeat heavily, so a known domain collapses a per-page guess into a table lookup. The table is updatable from classifier results and manually seedable. On a confident cached verdict, skip straight to render-or-not.

### 5.6 Renderer — `fetch/renderer_base.py`

```python
class Renderer(ABC):
    @abstractmethod
    async def render(self, url: str) -> str: ...
```

**LOCKED:** implementation uses **Playwright's Python API** — not Puppeteer, not pyppeteer (unmaintained). Use Playwright's official Docker image (browsers preinstalled) to avoid image bloat.

**LOCKED:** renders are heavy and overlapping — gate them with a *separate, small* `asyncio.Semaphore` (config `RENDER_CONCURRENCY`, default 3–5) so a wide fan-out does not spawn fifty Chromium contexts and exhaust the container. This is independent of `BRAVE_CONCURRENCY`: generous on cheap work, tight on rendering.

`FakeRenderer` returns saved rendered HTML from fixtures.

Keeping `Renderer` behind this interface is what makes extracting the browser into its own container later a mechanical change.

### 5.7 Preprocessor — `preprocess/`

`extract.py`: use **trafilatura** for main-content extraction on whichever HTML the pipeline committed to (raw if no render escalation, rendered otherwise) — built for pulling main content from arbitrary pages, strips boilerplate. This is the *only* place trafilatura runs; the classifier does not use it.

`features.py`: use **BeautifulSoup** for structural feature capture at parse time. Capture, do not score: ordered-list item count, density of imperative verbs (`click`, `select`, `drag`, `choose`, `open`, etc.), screenshot/image count, whether the `application` and `goal` terms appear in the text. Store these on the `parsed` row and the full blob in `parsed/{content_hash}.json`.

**LOCKED:** do not build quality ranking now. Captured features give a cheap, fully explainable v1 score immediately, and because raw HTML and features are all persisted, TF-IDF or an LLM-judge pass can run retrospectively over the accumulated corpus without re-scraping.

### 5.8 web_search_tool — `tools.py`

The agent-facing tool. Definition: the agent proposes multiple search queries; the tool dedups them, dispatches concurrently through `BraveClient`, and returns results. The agent proposes intent; the client decides actual concurrency. This is a thin wrapper over the search stage of the pipeline.

---

## 6. Build phases

Each phase ends with passing tests and is independently runnable. Do not begin a phase before the previous one is green.

**Phase 0 — scaffold.** `pyproject.toml`, repo layout, `config.py` (pydantic-settings, all values env-driven), FastAPI app with a `/health` endpoint, `Dockerfile` from the Playwright base image, `docker-compose.yml`, `.env.example`. Exit: container builds, `/health` returns 200.

**Phase 1 — storage.** SQLAlchemy table definitions (including `applications`), engine with WAL pragma, Alembic initialized with the initial migration, blob store (`storage/blobs.py`) and index operations (`storage/index.py`). Exit: migration applies, blobs round-trip by hash, index rows insert and query through SQLAlchemy only.

**Phase 2 — query generation.** `QueryGenerator` interface, `FakeQueryGenerator`, `OpenAIQueryGenerator` against the Responses API, `QUERY_GEN_PROMPT`, refusal handling, query cap. Exit: fake returns a valid `QueryPlan`; real generator parses a live response into `QueryPlan` and writes prompt + completion to `meta.json`.

**Phase 2.5 — application resolution.** `ApplicationResolver` with normalize → exact-match → rapidfuzz pipeline, initial seed data in `apps/seed.py`, Alembic data migration that loads the seed, `enrichment apps promote <run_id>` CLI command. Exit: a known application name resolves to its `app_id`; an alias resolves correctly; an unknown name returns `AppResolution(app_id=None, ...)` with the best score recorded; promotion CLI creates a new `applications` row from an unresolved run.

**Phase 3 — search.** `BraveClient` interface, `FakeBraveClient`, real Brave client with the concurrency semaphore, search-response cache, query dedup. Exit: fake returns fixture results; real client executes a query and caches it; a repeated query is a disk read with `cache_hit=True`.

**Phase 4 — fetch and classify.** `Fetcher`, `JsClassifier` with all five signals, `Renderer` interface, `PlaywrightRenderer`, `FakeRenderer`, `domain_render_cache`. Exit: cheap fetch returns HTML; classifier scores fixture pages correctly across all five signals; escalation invokes the renderer under the render semaphore; domain cache short-circuits a known domain.

**Phase 5 — preprocess.** trafilatura extraction, BeautifulSoup feature capture. Exit: a fixture tutorial page yields a parsed record with all structural features populated.

**Phase 6 — pipeline and export.** `pipeline.py` wires every stage (including `ApplicationResolver` between Phase 2 and Phase 3); `export.py` emits a run's JSON, grouped by `app_id` (with unresolved runs in a separate bucket). The FastAPI endpoint accepts a raw request and runs the pipeline. Exit: a raw request runs end to end against fakes with zero network calls and produces a complete, correct run in the blob store and index, plus a JSON export.

**Phase 7 — agent tool.** `web_search_tool` definition wrapping the search stage. Exit: an agent can propose N queries and receive deduplicated, concurrently-fetched results.

---

## 7. Testing strategy

Every phase delivers tests. The full pipeline must be exercisable end to end with all three fakes — `FakeQueryGenerator`, `FakeBraveClient`, `FakeRenderer` — so no test spends API budget or depends on network or LLM nondeterminism. `tests/fixtures/` holds saved Brave responses and saved HTML pages (server-rendered, SPA-shell, and embedded-state cases) so the classifier and preprocessor are tested against real-world page shapes. `ApplicationResolver` is tested with a small in-memory `applications` table covering exact, alias, fuzzy-hit, and below-threshold cases. A small number of integration tests may hit live Brave and OpenAI, marked and excluded from the default run.

---

## 8. Dockerfile and compose

`Dockerfile`: start from the official Playwright Python image (browsers preinstalled), install the project, run FastAPI via uvicorn. `docker-compose.yml`: the `enrichment-layer` service, the `data/` directory mounted as a volume so the dataset survives container restarts, environment from `.env`. SQLite's database file lives in the mounted volume. Structure the compose file so a future `renderer` service can be added without restructuring.

---

## 9. Configuration (`.env`)

`BRAVE_API_KEY`, `BRAVE_CONCURRENCY` (default 15), `OPENAI_API_KEY`, `OPENAI_MODEL`, `MAX_QUERIES` (default 5), `RENDER_CONCURRENCY` (default 4), `JS_SCORE_THRESHOLD`, `APP_MATCH_THRESHOLD` (default 90), `DATA_DIR` (default `./data`), `DATABASE_URL` (default `sqlite:///data/index.db`). All consumed through `config.py`; nothing hardcoded.

---

## 10. Decisions index

**LOCKED:** single container with the browser behind an interface; SQLite via SQLAlchemy with Postgres discipline (UUID keys, strict types, Alembic, WAL, no SQLite-only SQL); content-addressed blob storage separated from the metadata index; QueryGenerator in-process behind an interface; OpenAI Responses API with `responses.parse`; refusal handling; query cap enforced in code; `ApplicationResolver` between query generation and search, with normalize → exact → rapidfuzz; raw LLM `application` string preserved on every run; manual promotion of unresolved runs into the `applications` registry; Brave at 50 QPS with a concurrency semaphore and no token bucket; search-response cache; five-signal layered JS classifier (the fifth signal is a cheap BeautifulSoup structural probe, not trafilatura) with per-page logging; trafilatura runs exactly once, in the preprocessor; domain render cache; Playwright (not pyppeteer) on the official image; separate small render semaphore; trafilatura for extraction, BeautifulSoup for features; structural feature capture with quality ranking deferred; `source_type` field for the future video layer.

**OPEN — surface to the human before the dependent phase:**
1. Brave monthly request cap for the active plan tier (blocks treating fan-out as unconstrained — relevant Phase 3).
2. Exact OpenAI Python SDK argument names for `responses.parse` / `text_format`, to be verified against current docs (relevant Phase 2).
3. `JS_SCORE_THRESHOLD` starting value and the per-signal weights — propose defaults, tune against fixtures (relevant Phase 4).
4. `APP_MATCH_THRESHOLD` starting value (default 90) — tune against the first batch of real runs once the seed list is populated (relevant Phase 2.5).
