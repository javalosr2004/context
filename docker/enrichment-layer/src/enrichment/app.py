from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from enrichment.pipeline import run_enrichment, run_quick_guide
from enrichment.storage import (
    create_job, get_aggregate_plan, get_aggregate_plans, get_job,
    get_quick_guide, init_db, reap_orphan_jobs, update_job,
)

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
