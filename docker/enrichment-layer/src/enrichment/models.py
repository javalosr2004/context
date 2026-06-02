from __future__ import annotations

from pydantic import BaseModel, Field


class QueryPlan(BaseModel):
    application: str
    goal: str
    queries: list[str] = Field(default_factory=list)


class MultimodalQueryPlan(BaseModel):
    """Plan emitted by the multimodal /snippets path.

    ``environment`` captures what the screenshot showed (OS, app, region)
    so downstream consumers can debug why queries look the way they do.
    ``goal_facets`` decomposes the raw request into varying interpretations
    of the user's intent; ``queries`` flattens 1-2 queries per facet so
    the aggregator sees coverage across angles, not a single phrasing.
    """
    application: str
    environment: str = ""
    goal_facets: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    query: str
    url: str
    title: str = ""
    snippet: str = ""
    rank: int = 0


class ExtractedPage(BaseModel):
    url: str
    content_hash: str
    http_status: int
    title: str = ""
    text: str = ""
    text_length: int = 0
    ordered_list_items: int = 0
    imperative_verb_density: float = 0.0
    image_count: int = 0
    application_term_present: bool = False
    goal_term_present: bool = False


class RunResult(BaseModel):
    run_id: str
    plan: QueryPlan
    hit_count: int
    page_count: int
    parsed_plan_count: int = 0
    aggregate_step_count: int = 0
    aggregate_plan_count: int = 0
