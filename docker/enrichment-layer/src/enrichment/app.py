from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from enrichment.models import RunResult
from enrichment.pipeline import run_enrichment
from enrichment.storage import init_db

app = FastAPI(title="enrichment-layer")


class QueryRequest(BaseModel):
    request: str


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/query", response_model=RunResult)
async def query(body: QueryRequest) -> RunResult:
    return await run_enrichment(body.request)
