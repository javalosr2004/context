"""Local copy of backend's DraftPlan / DraftStep.

Kept identical to backend.tutorial_schema.DraftPlan so an enriched page can be
fed straight into the tutorial agent loop. A drift test in tests/ ensures the
JSON schemas match.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DraftStepKind = Literal[
    "click",
    "type",
    "press_key",
    "scroll",
    "wait",
    "navigate",
    "verify",
    "other",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftStep(_Strict):
    instruction: str = Field(
        min_length=1,
        description="One short human-readable sentence for the user.",
    )
    kind: DraftStepKind = Field(
        description="Coarse action kind hint; refiner may override.",
    )


class DraftPlan(_Strict):
    """Coarse hypothesis plan generated up-front from the goal.

    Not executable on its own — the agent loop refines each step against
    the live screen before emitting a TutorialStep.
    """

    schema_version: Literal["draft_plan.v1"] = "draft_plan.v1"
    goal: str = Field(min_length=1)
    steps: list[DraftStep] = Field(min_length=1, max_length=20)
