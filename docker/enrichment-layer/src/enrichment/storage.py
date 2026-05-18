from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    JSON, Column, DateTime, Float, ForeignKey, Integer, String,
    create_engine, event,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from enrichment.aggregate import AggregatePlan
from enrichment.config import settings
from enrichment.fetch import FetchResult
from enrichment.models import ExtractedPage, QueryPlan, SearchHit
from enrichment.parse import EnrichedDraft

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"
    job_id = Column(String, primary_key=True)
    status = Column(String, nullable=False)  # pending|running|done|failed
    raw_request = Column(String, nullable=False)
    run_id = Column(String, ForeignKey("runs.run_id"), nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class Run(Base):
    __tablename__ = "runs"
    run_id = Column(String, primary_key=True)
    raw_request = Column(String, nullable=False)
    application = Column(String, nullable=False)
    goal = Column(String, nullable=False)
    source_type = Column(String, nullable=False, default="web")
    created_at = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="ok")


class Search(Base):
    __tablename__ = "searches"
    search_id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.run_id"), nullable=False)
    query_text = Column(String, nullable=False)
    result_count = Column(Integer, nullable=False, default=0)
    executed_at = Column(DateTime, nullable=False)


class Page(Base):
    __tablename__ = "pages"
    content_hash = Column(String, primary_key=True)
    url = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    http_status = Column(Integer, nullable=False)
    fetched_at = Column(DateTime, nullable=False)


class SearchPage(Base):
    __tablename__ = "search_pages"
    search_id = Column(String, ForeignKey("searches.search_id"), primary_key=True)
    content_hash = Column(String, ForeignKey("pages.content_hash"), primary_key=True)
    rank = Column(Integer, nullable=False, default=0)


class Plan(Base):
    __tablename__ = "plans"
    plan_id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey("runs.run_id"), nullable=False)
    content_hash = Column(String, ForeignKey("pages.content_hash"), nullable=False)
    goal = Column(String, nullable=False)
    step_count = Column(Integer, nullable=False, default=0)
    model_name = Column(String, nullable=False)
    plan_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)


class AggregatePlanRow(Base):
    __tablename__ = "aggregate_plans"
    run_id = Column(String, ForeignKey("runs.run_id"), primary_key=True)
    application = Column(String, nullable=False)
    goal = Column(String, nullable=False)
    step_count = Column(Integer, nullable=False)
    source_count = Column(Integer, nullable=False)
    model_name = Column(String, nullable=False)
    plan_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)


class Parsed(Base):
    __tablename__ = "parsed"
    content_hash = Column(String, ForeignKey("pages.content_hash"), primary_key=True)
    title = Column(String, nullable=False, default="")
    text_length = Column(Integer, nullable=False, default=0)
    ordered_list_items = Column(Integer, nullable=False, default=0)
    imperative_verb_density = Column(Float, nullable=False, default=0.0)
    image_count = Column(Integer, nullable=False, default=0)
    application_term_present = Column(Integer, nullable=False, default=0)
    goal_term_present = Column(Integer, nullable=False, default=0)
    features = Column(JSON, nullable=False)
    parsed_at = Column(DateTime, nullable=False)


_engine = None
_SessionLocal = None


def _enable_wal(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def _get_session():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
        event.listen(_engine, "connect", _enable_wal)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _SessionLocal()


def init_db() -> None:
    global _engine
    if _engine is None:
        _get_session().close()
    Base.metadata.create_all(_engine)


# ---------- jobs ----------

def create_job(raw_request: str) -> str:
    init_db()
    job_id = str(uuid4())
    now = _now()
    with _get_session() as session:
        session.add(Job(
            job_id=job_id,
            status="pending",
            raw_request=raw_request,
            created_at=now,
            updated_at=now,
        ))
        session.commit()
    return job_id


def update_job(
    job_id: str,
    *,
    status: str,
    run_id: str | None = None,
    error: str | None = None,
) -> None:
    with _get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = status
        if run_id is not None:
            job.run_id = run_id
        if error is not None:
            job.error = error
        job.updated_at = _now()
        session.commit()


def get_job(job_id: str) -> dict | None:
    with _get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            return None
        return {
            "job_id": job.job_id,
            "status": job.status,
            "raw_request": job.raw_request,
            "run_id": job.run_id,
            "error": job.error,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        }


def get_aggregate_plan(run_id: str) -> dict | None:
    with _get_session() as session:
        row = session.get(AggregatePlanRow, run_id)
        return row.plan_json if row else None


def reap_orphan_jobs() -> int:
    """Mark any pending/running jobs as failed; called on startup."""
    init_db()
    count = 0
    with _get_session() as session:
        from sqlalchemy import select
        for job in session.execute(select(Job).where(Job.status.in_(["pending", "running"]))).scalars():
            job.status = "failed"
            job.error = "server restarted before completion"
            job.updated_at = _now()
            count += 1
        session.commit()
    return count


def reset_engine_for_tests() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _domain(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc


# ---------- blob layout ----------

def _blob_root() -> Path:
    return settings.data_dir


def _write_blob(rel: str, data: bytes | str) -> Path:
    path = _blob_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data)
    else:
        path.write_bytes(data)
    return path


def save_run(
    raw_request: str,
    plan: QueryPlan,
    hits_by_query: dict[str, list[SearchHit]],
    fetches: list[FetchResult],
    extractions: list[ExtractedPage],
    drafts: list[EnrichedDraft],
    aggregate: AggregatePlan | None,
) -> str:
    init_db()
    run_id = str(uuid4())
    now = _now()

    # meta blob
    _write_blob(
        f"runs/{run_id}/meta.json",
        json.dumps(
            {
                "run_id": run_id,
                "raw_request": raw_request,
                "application": plan.application,
                "goal": plan.goal,
                "queries": plan.queries,
                "created_at": now.isoformat(),
            },
            indent=2,
        ),
    )

    # page blobs (raw html + parsed json)
    for f in fetches:
        _write_blob(f"pages/{f.content_hash}.html", f.html)
    for e in extractions:
        _write_blob(f"parsed/{e.content_hash}.json", e.model_dump_json(indent=2))
    for d in drafts:
        _write_blob(f"plans/{d.source_content_hash}.json", d.model_dump_json(indent=2))
    if aggregate is not None:
        _write_blob(
            f"runs/{run_id}/aggregate_plan.json",
            aggregate.model_dump_json(indent=2),
        )

    with _get_session() as session:
        session.add(Run(
            run_id=run_id,
            raw_request=raw_request,
            application=plan.application,
            goal=plan.goal,
            created_at=now,
        ))

        # pages (upsert-ish: insert if missing)
        for f in fetches:
            existing = session.get(Page, f.content_hash)
            if existing is None:
                session.add(Page(
                    content_hash=f.content_hash,
                    url=f.final_url,
                    domain=_domain(f.final_url),
                    http_status=f.http_status,
                    fetched_at=now,
                ))

        # searches + edges
        hash_by_url = {f.final_url: f.content_hash for f in fetches}
        hash_by_url.update({f.url: f.content_hash for f in fetches})
        for query, hits in hits_by_query.items():
            search_id = str(uuid4())
            session.add(Search(
                search_id=search_id,
                run_id=run_id,
                query_text=query,
                result_count=len(hits),
                executed_at=now,
            ))
            for hit in hits:
                ch = hash_by_url.get(hit.url)
                if ch is None:
                    continue
                session.add(SearchPage(search_id=search_id, content_hash=ch, rank=hit.rank))

        # parsed rows
        for e in extractions:
            if session.get(Parsed, e.content_hash) is not None:
                continue
            session.add(Parsed(
                content_hash=e.content_hash,
                title=e.title,
                text_length=e.text_length,
                ordered_list_items=e.ordered_list_items,
                imperative_verb_density=e.imperative_verb_density,
                image_count=e.image_count,
                application_term_present=int(e.application_term_present),
                goal_term_present=int(e.goal_term_present),
                features=e.model_dump(),
                parsed_at=now,
            ))

        # aggregate plan
        if aggregate is not None:
            session.add(AggregatePlanRow(
                run_id=run_id,
                application=aggregate.application,
                goal=aggregate.goal,
                step_count=len(aggregate.steps),
                source_count=aggregate.source_count,
                model_name=aggregate.model_name,
                plan_json=aggregate.model_dump(),
                created_at=now,
            ))

        # draft plans
        for d in drafts:
            session.add(Plan(
                plan_id=str(uuid4()),
                run_id=run_id,
                content_hash=d.source_content_hash,
                goal=d.plan.goal,
                step_count=len(d.plan.steps),
                model_name=d.model_name,
                plan_json=d.model_dump(),
                created_at=now,
            ))

        session.commit()

    return run_id
