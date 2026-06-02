from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from enrichment.cache import (
    all_stats as cache_all_stats,
    l1_partition_for_image,
    l1_plan,
    l2_partition_for_context,
    l2_snippets,
    l2_text_for_queries,
)
from enrichment.cache.grounding_cache import (
    reset_request_cache_state,
    snapshot_request_cache_state,
)
from enrichment.extract import extract
from enrichment.fetch import fan_out_fetch
from enrichment.models import ExtractedPage, MultimodalQueryPlan
from enrichment.multimodal_queries import generate_multimodal_query_plan
from enrichment.pipeline import run_enrichment, run_quick_guide
from enrichment.snippets import (
    DEFAULT_NUM_SOURCES, Snippet, SnippetResult, run_snippet_pipeline,
)
from enrichment.storage import (
    create_job, get_aggregate_plan, get_aggregate_plans, get_job,
    get_quick_guide, init_db, reap_orphan_jobs, update_job,
)
from enrichment.summarize import summarize_page_for_goal

logger = logging.getLogger("enrichment")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    reaped = reap_orphan_jobs()
    if reaped:
        logger.warning("reaped %d orphan jobs from previous run", reaped)
    yield


app = FastAPI(title="enrichment-layer", lifespan=lifespan)


class QueryRequest(BaseModel):
    request: str


class JobAck(BaseModel):
    job_id: str
    status: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/query", response_model=JobAck, status_code=202)
async def query(body: QueryRequest) -> JobAck:
    job_id = create_job(body.request)
    asyncio.create_task(_run_job(job_id, body.request))
    return JobAck(job_id=job_id, status="pending")


class SnippetsResponse(BaseModel):
    snippets: list[Snippet]
    source_count: int
    elapsed_ms: float
    queries_used: list[str]
    application: str | None = None
    environment: str | None = None
    goal_facets: list[str] = []
    # Per-query provenance so callers can populate per-query caches from
    # a single multi-query call. Keys are the queries actually run; a URL
    # discovered by multiple queries appears under each.
    snippets_by_query: dict[str, list[Snippet]] = {}


class PlanQueriesResponse(BaseModel):
    application: str | None = None
    environment: str | None = None
    goal_facets: list[str] = []
    queries: list[str]
    cache_hit: bool = False


def _apply_cache_headers(response: Response) -> None:
    """Set X-Cache-L{1..5} based on this request's recorded hits/misses."""
    state = snapshot_request_cache_state()
    for layer in ("L1", "L2", "L3", "L4", "L5"):
        bucket = state.get(layer)
        if not bucket:
            continue
        value = "hit" if bucket.get("hit", 0) > 0 else "miss"
        response.headers[f"X-Cache-{layer}"] = value


@app.post("/plan_queries", response_model=PlanQueriesResponse)
async def plan_queries(
    response: Response,
    query: str = Form(...),
    application: str | None = Form(None),
    image: UploadFile | None = File(None),
) -> PlanQueriesResponse:
    reset_request_cache_state()
    raw_request = query.strip()
    if not raw_request:
        raise HTTPException(422, "query must be non-empty")

    image_bytes: bytes | None = None
    if image is not None:
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(400, "image upload was empty")

    out = await _plan_queries(raw_request, application, image_bytes, image)
    _apply_cache_headers(response)
    return out


async def _plan_queries(
    raw_request: str,
    application: str | None,
    image_bytes: bytes | None,
    image: UploadFile | None,
) -> PlanQueriesResponse:
    partition = l1_partition_for_image(image_bytes)
    cached = await asyncio.to_thread(l1_plan.get, partition, raw_request)
    if cached is not None:
        plan_app = application or cached.get("application") or None
        return PlanQueriesResponse(
            application=plan_app,
            environment=cached.get("environment") or None,
            goal_facets=list(cached.get("goal_facets") or []),
            queries=list(cached.get("queries") or [raw_request]),
            cache_hit=True,
        )

    if image_bytes is None:
        # No-image path: fall back to single-query plan with no LLM call.
        # Match the legacy /snippets shape: empty goal_facets, empty env.
        plan = MultimodalQueryPlan(
            application=application or "",
            environment="",
            goal_facets=[],
            queries=[raw_request],
        )
    else:
        logger.info(
            "multimodal /plan_queries image: %d bytes, mime=%r, header=%r",
            len(image_bytes),
            image.content_type if image else None,
            image_bytes[:16].hex(),
        )
        try:
            plan = await asyncio.to_thread(
                generate_multimodal_query_plan,
                raw_request,
                image_bytes=image_bytes,
                image_mime=(image.content_type if image else None),
            )
        except Exception as exc:
            logger.exception("multimodal query planning failed")
            try:
                from pathlib import Path
                dump_dir = Path("/tmp/enrichment_failures")
                dump_dir.mkdir(parents=True, exist_ok=True)
                import time
                dump_path = dump_dir / f"image_{int(time.time())}.bin"
                dump_path.write_bytes(image_bytes)
                logger.warning("Wrote failing image bytes to %s", dump_path)
            except Exception:
                logger.exception("could not persist failing image bytes")
            raise HTTPException(
                503, f"multimodal query planning failed: {type(exc).__name__}"
            ) from exc

    plan_app = application or plan.application or None
    queries = plan.queries or [raw_request]
    payload = {
        "application": plan.application,
        "environment": plan.environment,
        "goal_facets": list(plan.goal_facets),
        "queries": list(queries),
    }
    # Populate L1 in the background — the embedding call is non-trivial
    # but doesn't affect the response.
    asyncio.create_task(asyncio.to_thread(l1_plan.put, partition, raw_request, payload))
    return PlanQueriesResponse(
        application=plan_app,
        environment=plan.environment or None,
        goal_facets=list(plan.goal_facets),
        queries=list(queries),
        cache_hit=False,
    )


class SnippetsForRequest(BaseModel):
    queries: list[str]
    application: str | None = None
    environment: str | None = None
    goal: str | None = None
    num_sources: int = DEFAULT_NUM_SOURCES


class SnippetsForResponse(BaseModel):
    snippets: list[Snippet]
    source_count: int
    elapsed_ms: float
    snippets_by_query: dict[str, list[Snippet]] = {}
    cache_hit: bool = False


@app.post("/snippets_for", response_model=SnippetsForResponse)
async def snippets_for(
    body: SnippetsForRequest, response: Response,
) -> SnippetsForResponse:
    reset_request_cache_state()
    if not body.queries:
        raise HTTPException(422, "queries must be non-empty")
    out = await _snippets_for(body)
    _apply_cache_headers(response)
    return out


async def _snippets_for(body: SnippetsForRequest) -> SnippetsForResponse:
    queries = [q.strip() for q in body.queries if q and q.strip()]
    if not queries:
        return SnippetsForResponse(snippets=[], source_count=0, elapsed_ms=0.0)

    partition = l2_partition_for_context(body.application, body.environment)
    text = l2_text_for_queries(queries)
    cached = await asyncio.to_thread(l2_snippets.get, partition, text)
    if cached is not None:
        return SnippetsForResponse(
            snippets=[Snippet(**s) for s in cached.get("snippets", [])],
            source_count=cached.get("source_count", 0),
            elapsed_ms=0.0,
            snippets_by_query={
                q: [Snippet(**s) for s in v]
                for q, v in (cached.get("snippets_by_query") or {}).items()
            },
            cache_hit=True,
        )

    try:
        result = await run_snippet_pipeline(
            queries=queries,
            application=body.application,
            goal=body.goal,
            num_sources=body.num_sources,
        )
    except Exception as exc:
        logger.exception("snippets pipeline failed")
        raise HTTPException(503, f"snippets pipeline failed: {type(exc).__name__}") from exc

    payload = _serialize_snippet_result(result)
    asyncio.create_task(asyncio.to_thread(l2_snippets.put, partition, text, payload))
    return SnippetsForResponse(
        snippets=result.snippets,
        source_count=result.source_count,
        elapsed_ms=result.elapsed_ms,
        snippets_by_query=result.snippets_by_query or {},
        cache_hit=False,
    )


def _serialize_snippet_result(result: SnippetResult) -> dict:
    return {
        "snippets": [s.model_dump() for s in result.snippets],
        "source_count": result.source_count,
        "snippets_by_query": {
            q: [s.model_dump() for s in v]
            for q, v in (result.snippets_by_query or {}).items()
        },
    }


@app.post("/snippets", response_model=SnippetsResponse)
async def snippets(
    response: Response,
    query: str = Form(...),
    application: str | None = Form(None),
    goal: str | None = Form(None),
    num_sources: int = Form(DEFAULT_NUM_SOURCES),
    image: UploadFile | None = File(None),
) -> SnippetsResponse:
    """Backward-compatible wrapper: plan_queries -> snippets_for."""
    reset_request_cache_state()
    raw_request = query.strip()
    if not raw_request:
        raise HTTPException(422, "query must be non-empty")

    image_bytes: bytes | None = None
    if image is not None:
        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(400, "image upload was empty")

    plan = await _plan_queries(raw_request, application, image_bytes, image)

    sf = await _snippets_for(
        SnippetsForRequest(
            queries=plan.queries or [raw_request],
            application=plan.application,
            environment=plan.environment,
            goal=goal,
            num_sources=num_sources,
        )
    )

    out = SnippetsResponse(
        snippets=sf.snippets,
        source_count=sf.source_count,
        elapsed_ms=sf.elapsed_ms,
        queries_used=plan.queries or [raw_request],
        application=plan.application,
        environment=plan.environment,
        goal_facets=plan.goal_facets,
        snippets_by_query=sf.snippets_by_query or {},
    )
    _apply_cache_headers(response)
    return out


@app.get("/cache/stats")
def cache_stats() -> dict:
    """Per-layer hit/miss/eviction/size for tuning TTLs."""
    return cache_all_stats()


# ---- /extract & /summarize: cache-friendly building blocks ----------------
#
# /snippets bundles search + fetch + extract + summarize in one shot. The
# backend cache wants to split those: fetched+extracted page text is
# query-agnostic and reusable across paraphrased queries; the summary is
# query-conditioned and must NOT be reused across distinct queries.
# These two endpoints expose the underlying stages so the cache layer
# can key each correctly.


class ExtractRequest(BaseModel):
    url: str


class ExtractedPageResponse(BaseModel):
    url: str
    final_url: str
    http_status: int
    title: str
    text: str
    content_hash: str


@app.post("/extract", response_model=ExtractedPageResponse)
async def extract_page(body: ExtractRequest) -> ExtractedPageResponse:
    url = body.url.strip()
    if not url:
        raise HTTPException(422, "url must be non-empty")
    try:
        fetches = await fan_out_fetch([url])
    except Exception as exc:
        logger.exception("extract fetch failed")
        raise HTTPException(503, f"fetch failed: {type(exc).__name__}") from exc
    if not fetches:
        raise HTTPException(502, "fetch returned no result")
    page = extract(fetches[0], application="", goal="")
    return ExtractedPageResponse(
        url=url,
        final_url=fetches[0].final_url,
        http_status=page.http_status,
        title=page.title,
        text=page.text,
        content_hash=page.content_hash,
    )


class SummarizeRequest(BaseModel):
    url: str
    title: str = ""
    text: str
    query: str
    application: str | None = None
    goal: str | None = None
    max_chars: int = 300


class SummarizeResponse(BaseModel):
    snippet: str | None
    url: str


@app.post("/summarize", response_model=SummarizeResponse)
async def summarize_endpoint(body: SummarizeRequest) -> SummarizeResponse:
    text = body.text or ""
    if not text.strip():
        raise HTTPException(422, "text must be non-empty")
    if not body.query.strip():
        raise HTTPException(422, "query must be non-empty")
    # Build a minimal ExtractedPage; summarize_page_for_goal only reads
    # url, title, text. The other fields are zeroed safely.
    page = ExtractedPage(
        url=body.url,
        content_hash="",
        http_status=200,
        title=body.title,
        text=text,
        text_length=len(text),
    )
    # The summarizer is goal-conditioned. Use the per-call query as the
    # goal so the same page yields different snippets per query — which
    # is exactly why this stage is NOT cache-shared across queries.
    effective_goal = body.goal or body.query
    try:
        snippet = await asyncio.to_thread(
            summarize_page_for_goal,
            page, body.application, effective_goal, body.max_chars,
        )
    except Exception as exc:
        logger.exception("summarize failed")
        raise HTTPException(503, f"summarize failed: {type(exc).__name__}") from exc
    return SummarizeResponse(snippet=snippet, url=body.url)


@app.post("/quick_guide", response_model=JobAck, status_code=202)
async def quick_guide(body: QueryRequest) -> JobAck:
    job_id = create_job(body.request)
    asyncio.create_task(_run_quick_job(job_id, body.request))
    return JobAck(job_id=job_id, status="pending")


@app.get("/runs/{run_id}/quick_guide")
def run_quick_guide_view(run_id: str) -> dict:
    guide = get_quick_guide(run_id)
    if guide is None:
        raise HTTPException(404, "no quick guide for this run")
    return guide


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@app.get("/runs/{run_id}/aggregate_plan")
def aggregate_plan(run_id: str) -> dict:
    plan = get_aggregate_plan(run_id)
    if plan is None:
        raise HTTPException(404, "no aggregate plan for this run")
    return plan


@app.get("/runs/{run_id}/aggregate_plans")
def aggregate_plans(run_id: str) -> dict:
    plans = get_aggregate_plans(run_id)
    if not plans:
        raise HTTPException(404, "no aggregate plans for this run")
    return {"run_id": run_id, "plan_count": len(plans), "plans": plans}


async def _run_job(job_id: str, raw_request: str) -> None:
    update_job(job_id, status="running")
    try:
        result = await run_enrichment(raw_request)
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        update_job(job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        return
    update_job(job_id, status="done", run_id=result.run_id)


async def _run_quick_job(job_id: str, raw_request: str) -> None:
    update_job(job_id, status="running")
    try:
        result = await run_quick_guide(raw_request)
    except Exception as exc:
        logger.exception("quick job %s failed", job_id)
        update_job(job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        return
    update_job(job_id, status="done", run_id=result["run_id"])
