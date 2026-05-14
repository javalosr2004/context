from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass

from backend.images import UploadedImage
from backend.llm import LLMRequest, MultimodalLLM
from backend.tutorial_schema import (
    TutorialPlan,
    TutorialPlanValidationError,
    parse_tutorial_plan,
    tutorial_plan_response_schema,
)


logger = logging.getLogger(__name__)


TUTORIAL_CREATOR_SYSTEM_PROMPT = (
    "Your task is to be an agentic tutorial creator. You will create verbose "
    "tutorials that describe what action to perform - click, hover, scroll. "
    "When useful, look for tutorials, official documentation, or other helpful "
    "current information with Google Search. Prefer concrete, step-by-step "
    "instructions over generic advice. If the screen or user intent is unclear, "
    "state the uncertainty and ask for confirmation before continuing."
)

TUTORIAL_PLAN_SYSTEM_PROMPT = """
You are a tutorial planner for a macOS overlay teaching system.
Do not assume application context; design the tutorial to work with the
attached screen context and the user's request. Follow the provided response
schema exactly. Keep each instruction short and readable for a human overlay.
Use semantic targets, not coordinates, unless coordinates were provided.
Use confirmation when confidence is low, the target is ambiguous, or the
screen may not match the expected state.
""".strip()

MAX_TUTORIAL_PLAN_RETRIES = 2


@dataclass(frozen=True)
class TutorialStreamRequest:
    conversation_id: str
    text: str
    images: list[UploadedImage]


@dataclass(frozen=True)
class TutorialPlanRequest:
    conversation_id: str
    text: str
    images: list[UploadedImage]


class TutorialGuide:
    def __init__(self, llm: MultimodalLLM) -> None:
        self._llm = llm

    def create_plan(self, request: TutorialPlanRequest) -> TutorialPlan:
        return generate_tutorial_plan(
            llm=self._llm,
            prompt=build_tutorial_plan_user_prompt(request.text),
            images=request.images,
        )

    def stream_tutorial(self, request: TutorialStreamRequest) -> Iterator[str]:
        return self._llm.stream_text(
            LLMRequest(
                system_prompt=TUTORIAL_CREATOR_SYSTEM_PROMPT,
                user_text=request.text,
                images=request.images,
                enable_search_grounding=True,
            )
        )


def generate_tutorial_plan(
    llm: MultimodalLLM,
    prompt: str,
    images: list[UploadedImage] | None = None,
    max_retries: int = MAX_TUTORIAL_PLAN_RETRIES,
) -> TutorialPlan:
    last_text = ""
    error_text = ""
    last_error: TutorialPlanValidationError | None = None
    request_images = images or []

    for attempt in range(max_retries + 1):
        raw_plan = llm.complete_text(
            LLMRequest(
                system_prompt=TUTORIAL_PLAN_SYSTEM_PROMPT,
                user_text=plan_generation_prompt(
                    prompt=prompt,
                    attempt=attempt,
                    error_text=error_text,
                    last_text=last_text,
                ),
                images=request_images,
                enable_search_grounding=False,
                response_mime_type="application/json",
                response_schema=tutorial_plan_response_schema(),
                temperature=0,
            )
        )
        last_text = raw_plan

        try:
            return parse_tutorial_plan(raw_plan)
        except TutorialPlanValidationError as error:
            last_error = error
            error_text = format_validation_error(error)
            logger.warning(
                "Tutorial plan validation failed",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": max_retries + 1,
                    "error": error_text,
                },
            )

    raise TutorialPlanValidationError(
        "Could not generate valid TutorialPlan"
    ) from last_error


def plan_generation_prompt(
    prompt: str,
    attempt: int,
    error_text: str,
    last_text: str,
) -> str:
    if attempt == 0:
        return prompt

    return (
        "Fix the previous JSON so it validates against the provided response "
        "schema and tutorial action semantics.\n\n"
        f"Validation failed because:\n{error_text}\n\n"
        f"Previous output:\n{last_text}"
    )


def build_tutorial_plan_user_prompt(user_request: str) -> str:
    return (
        "Create a compact tutorial plan for this user request. "
        "Use the attached screen images as the current visual context.\n\n"
        f"User request: {user_request}"
    )


def format_validation_error(error: TutorialPlanValidationError) -> str:
    cause = error.__cause__
    return str(cause) if cause is not None else str(error)
