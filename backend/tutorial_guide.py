from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass

from backend.images import UploadedImage
from backend.llm import LLMRequest, MultimodalLLM
from backend.web_ground import (
    NullWebGroundProducer,
    WebGroundProducer,
    WebGroundSnippet,
    format_snippets_for_prompt,
)
from backend.tutorial_schema import (
    DraftPlan,
    TutorialPlan,
    TutorialPlanValidationError,
    UserMessageIntentKind,
    draft_plan_response_schema,
    parse_draft_plan,
    parse_search_query_refinement,
    parse_tutorial_plan,
    parse_user_message_intent,
    search_query_refinement_response_schema,
    tutorial_plan_response_schema,
    user_message_intent_response_schema,
)


logger = logging.getLogger(__name__)


TUTORIAL_CREATOR_SYSTEM_PROMPT = """
You are Context, a macOS teaching assistant.

Your job is to help the user understand and complete work on their screen. You
are not only a tutorial generator. Choose the response style that best helps:
- Conversational help: use when the user is asking what something means, why
  something happened, how to think about a task, or what options they have.
- Coaching help: use when the user wants support and the task benefits from a
  clear sequence, checks, examples, or decision points.
- Overlay tutorial: use when the user wants concrete screen actions such as click,
  type, press, wait, or scroll.

Make this choice internally. Never announce or describe the internal route to
the user.

For conversational help, be detailed enough to be genuinely useful. Explain the
reasoning, name tradeoffs, give concrete examples, and offer practical next
steps. Do not cut the conversation short after one shallow answer when the user
is still orienting. If a better answer needs missing context, ask one specific
question and explain why it matters.

For coaching help or overlay tutorials, prefer concrete instructions over
generic advice. When useful, look for tutorials, official documentation, or
other helpful current information with Google Search. If the screen or user
intent is unclear, state the uncertainty and ask for confirmation before
continuing.

Keep the tone patient, direct, and tool-aware. Surface available help such as
screen checks, confirmation prompts, examples, summaries, or next-step lists
when they would reduce user confusion. Do not pretend to see UI state that was
not provided.
""".strip()

TUTORIAL_PLAN_SYSTEM_PROMPT = """
You are a tutorial planner for a macOS overlay teaching system.
Do not assume application context; design the tutorial to work with the
attached screen context and the user's request. Follow the provided response
schema exactly. Keep each instruction short and readable for a human overlay.
Use semantic targets, not coordinates, unless coordinates were provided.
Use confirmation when confidence is low, the target is ambiguous, or the
screen may not match the expected state.
""".strip()

_CAPPED_HEAD_PLAN_RULE = (
    "Each tutorial_update_plan emits the next 1–5 steps you can see clearly "
    "from the current screen — not the whole plan. The backend re-invokes "
    "you once the user walks past your head."
)

_FULL_PLAN_RULE = (
    "Each tutorial_update_plan emits your complete remaining plan from "
    "the current cursor through the goal. Confidence can decay along the tail."
)

_WEB_SEARCH_BULLET = (
    "\n- web_search(query): search the web for anything you're unsure about — "
    "UI labels, factual claims, whether a feature exists."
)


def _build_tool_stream_prompt(*, capped_head: bool, planner_search: bool) -> str:
    plan_rule = _CAPPED_HEAD_PLAN_RULE if capped_head else _FULL_PLAN_RULE
    web_search = _WEB_SEARCH_BULLET if planner_search else ""
    return (
        "You are Context, a macOS teaching assistant. Help the user with "
        "whatever is on their screen — answer questions, walk them through "
        "a flow, or both.\n"
        "\n"
        "Tools:\n"
        "- tutorial_update_plan(plan, plan_reasoning): emit your remaining "
        "plan. Each step has human_text (one user-facing line), confidence "
        "(0–1), and actions (click, type, press_key, scroll, wait, "
        "user_choice). Use user_choice when the user must make a free "
        "choice. Set refines_current=true on the first item to sharpen the "
        "awaiting step in place; set abandon_awaiting=true to drop it.\n"
        "- tutorial_request_screen(reason): fetch a fresh screenshot.\n"
        "- tutorial_request_completion(reason): propose the goal is "
        "reached; the user decides.\n"
        "- tutorial_ask_user(reason, questions): ask 1–4 clarifying "
        "questions whenever it helps."
        f"{web_search}\n"
        "\n"
        f"{plan_rule} Replan when the screen disagrees. Answer in plain "
        "text when no action is needed. Be direct."
    )


TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT = _build_tool_stream_prompt(
    capped_head=False, planner_search=False
)


def tool_stream_system_prompt(
    *, capped_head: bool, planner_search: bool = False
) -> str:
    """Build the planner system prompt.

    ``capped_head=True`` swaps the plan-length rule to the 1–5-step head
    contract (STEP_TOOLS_ENABLED=on A/B). ``planner_search=True`` adds
    the web_search tool bullet (GROUNDING_STRATEGY=planner).
    """
    return _build_tool_stream_prompt(
        capped_head=capped_head, planner_search=planner_search
    )

USER_MESSAGE_INTENT_SYSTEM_PROMPT = """
You are a routing classifier inside a macOS tutorial system.

A session already has an active goal and (optionally) a draft plan. A new
user message just arrived. Decide whether the message is:

- "follow_up": it refines, clarifies, answers, confirms, or continues the
  active goal in any way — including adjustments ("with mustard"), answers
  to the agent's questions, requests to skip/redo a step, or general
  conversation about the same task.
- "new_goal": the user is switching to an unrelated task that has nothing
  to do with the active goal or the drafted steps.

Default to "follow_up" when unsure. Only return "new_goal" when the new
message clearly describes a different task. Return only the JSON object
matching the provided schema; no prose, no reasoning.
""".strip()

SEARCH_QUERY_REFINER_SYSTEM_PROMPT = """
You turn a vague user goal into one precise web search query, using the
attached screenshot for grounding.

Look at the screenshot first. Identify the OS and version (e.g. macOS
Sequoia), the active app, and any specific UI region visible. Combine
that context with the user's goal to produce a single search query that
would surface step-by-step instructions for the user's task on this
exact platform.

Rules:
- One query, roughly 5-12 words.
- Always name the OS or app when visible. Prefer specific labels over
  generic ones.
- No question marks, no quotes, no boilerplate ("how to", "tutorial on").
- If the screenshot is ambiguous or absent, still emit a query — fall
  back to the most likely platform implied by the goal.

Return only the JSON object matching the provided schema.
""".strip()

DRAFT_PLAN_SYSTEM_PROMPT = """
You are sketching a coarse hypothesis plan for a macOS overlay tutorial.

Set `goal` to a short imperative title — roughly 3-6 words — that names
the task in the user's domain ("Sign up for Figma", "Export a Notion
page as PDF"). Name the target app or surface when it is clear from the
user's request or the screen. Do not echo the user's full sentence,
preserve filler words, or end with punctuation.

Produce up to 20 short, human-readable instructions that map a plausible
path from the user's current context to their goal. This is a hypothesis,
not a contract — another agent will refine each step against the live
screen, batch confidently when the path is predictable, and deviate when
the screen contradicts the draft. Cover the full path, not just the first
step.

Each instruction is one short sentence written for the end user
("Open the Courses menu", "Type your search query", "Click Sign in").
Tag each with a kind hint. Use "verify" sparingly — only when a step
genuinely hinges on a state check.

Never invent specific UI labels, menu items, or button names that you have
no reason to expect. When unsure, describe the target generically. Do not
include reasoning, preambles, or commentary — only the structured plan.
""".strip()


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


RAW_OUTPUT_LOG_LIMIT = 2000


def generate_tutorial_plan(
    llm: MultimodalLLM,
    prompt: str,
    images: list[UploadedImage] | None = None,
) -> TutorialPlan:
    """Single-shot tutorial plan generation.

    The OpenAI client wires the response schema as a strict json_schema
    format (see ``backend.openai_client.build_text_format``), so the model
    cannot return shape-invalid JSON. Gemini's structured-output mode
    behaves the same way. A retry loop would only mask semantic bugs
    (bad enum values, missing required fields) that strict schema already
    catches at decode time — surface those instead of paying 2-3x latency.
    """
    request_images = images or []
    started_at = time.perf_counter()
    raw_plan = llm.complete_text(
        LLMRequest(
            system_prompt=TUTORIAL_PLAN_SYSTEM_PROMPT,
            user_text=prompt,
            images=request_images,
            enable_search_grounding=False,
            response_mime_type="application/json",
            response_schema=tutorial_plan_response_schema(),
            temperature=0,
        )
    )
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.info(
        "Tutorial plan LLM call completed",
        extra={"elapsed_ms": elapsed_ms, "raw_chars": len(raw_plan)},
    )

    try:
        plan = parse_tutorial_plan(raw_plan)
    except TutorialPlanValidationError as error:
        logger.error(
            "Tutorial plan validation failed",
            extra={
                "error": format_validation_error(error),
                "raw_output": truncate(raw_plan, RAW_OUTPUT_LOG_LIMIT),
            },
        )
        raise

    logger.info(
        "Tutorial plan validated",
        extra={"step_count": len(plan.steps)},
    )
    return plan


def refine_search_query(
    llm: MultimodalLLM,
    goal: str,
    image: UploadedImage | None,
) -> str:
    """Turn the raw user goal + screenshot into a grounded web search query.

    Uses a small multimodal call (intended for a fast model like nano) so
    the downstream web search runs against a query that names the visible
    OS/app rather than the user's ambiguous phrasing. Falls back to the
    original goal on any failure — refinement is a soft enhancement.
    """
    stripped = goal.strip()
    if not stripped:
        return ""
    request_images = [image] if image is not None else []
    started_at = time.perf_counter()
    try:
        raw = llm.complete_text(
            LLMRequest(
                system_prompt=SEARCH_QUERY_REFINER_SYSTEM_PROMPT,
                user_text=(
                    f"User goal: {stripped}\n\n"
                    "Return one grounded search query as JSON matching "
                    "the provided schema."
                ),
                images=request_images,
                enable_search_grounding=False,
                response_mime_type="application/json",
                response_schema=search_query_refinement_response_schema(),
                temperature=0,
            )
        )
        refined = parse_search_query_refinement(raw).query.strip()
    except Exception:
        logger.exception(
            "Search query refinement failed; falling back to raw goal",
            extra={"goal_chars": len(stripped)},
        )
        return stripped
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    if not refined:
        return stripped
    logger.info(
        "Search query refined",
        extra={
            "original": stripped,
            "refined": refined,
            "elapsed_ms": elapsed_ms,
            "had_image": image is not None,
        },
    )
    return refined


def generate_draft_plan(
    llm: MultimodalLLM,
    goal: str,
    image: UploadedImage | None = None,
    images: list[UploadedImage] | None = None,
    web_ground: WebGroundProducer | None = None,
    snippets: list[WebGroundSnippet] | None = None,
) -> DraftPlan:
    """One-shot coarse plan generation. Images are optional visual context.

    If ``snippets`` is provided, ``web_ground`` is ignored — the caller has
    already done the grounding fetch (e.g. to emit progress events around it).
    """
    request_images = images if images is not None else []
    if image is not None:
        request_images = [image, *request_images]

    grounding_block = ""
    if snippets is None:
        producer_name = type(
            web_ground if web_ground is not None else NullWebGroundProducer()
        ).__name__
        producer = web_ground if web_ground is not None else NullWebGroundProducer()
        grounding_started_at = time.perf_counter()
        snippets = producer.ground(goal)
        grounding_elapsed_ms = round((time.perf_counter() - grounding_started_at) * 1000, 2)
    else:
        producer_name = "caller"
        grounding_elapsed_ms = 0.0
    if snippets:
        grounding_block = format_snippets_for_prompt(snippets) + "\n\n"
        logger.info(
            "Draft plan grounded via web search",
            extra={
                "query": goal,
                "snippet_count": len(snippets),
                "elapsed_ms": grounding_elapsed_ms,
                "sources": [
                    {"title": s.title, "url": s.url} for s in snippets
                ],
            },
        )
    else:
        logger.info(
            "Draft plan grounding returned no snippets",
            extra={
                "query": goal,
                "elapsed_ms": grounding_elapsed_ms,
                "producer": producer_name,
            },
        )

    started_at = time.perf_counter()
    raw = llm.complete_text(
        LLMRequest(
            system_prompt=DRAFT_PLAN_SYSTEM_PROMPT,
            user_text=(
                f"User goal: {goal}\n\n"
                f"{grounding_block}"
                "Return a draft plan as JSON matching the provided schema."
            ),
            images=request_images,
            enable_search_grounding=False,
            response_mime_type="application/json",
            response_schema=draft_plan_response_schema(),
            temperature=0,
        )
    )
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    plan = parse_draft_plan(raw)
    logger.info(
        "Draft plan generated",
        extra={
            "elapsed_ms": elapsed_ms,
            "step_count": len(plan.steps),
            "image_count": len(request_images),
        },
    )
    return plan


def classify_user_message_intent(
    llm: MultimodalLLM,
    prior_goal: str,
    prior_draft: DraftPlan | None,
    new_message: str,
) -> UserMessageIntentKind:
    """Decide whether `new_message` is a follow-up or a new goal."""
    draft_block = _format_draft_for_classifier(prior_draft)
    started_at = time.perf_counter()
    raw = llm.complete_text(
        LLMRequest(
            system_prompt=USER_MESSAGE_INTENT_SYSTEM_PROMPT,
            user_text=(
                f"Active goal: {prior_goal}\n\n"
                f"{draft_block}"
                f"New user message: {new_message}\n\n"
                "Return the intent as JSON matching the provided schema."
            ),
            images=[],
            enable_search_grounding=False,
            response_mime_type="application/json",
            response_schema=user_message_intent_response_schema(),
            temperature=0,
        )
    )
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    intent = parse_user_message_intent(raw).intent
    logger.info(
        "User message intent classified",
        extra={
            "elapsed_ms": elapsed_ms,
            "intent": intent,
            "has_draft": prior_draft is not None,
        },
    )
    return intent


def _format_draft_for_classifier(draft: DraftPlan | None) -> str:
    if draft is None:
        return ""
    bullets = "\n".join(f"- {step.instruction}" for step in draft.steps)
    return f"Draft plan so far:\n{bullets}\n\n"


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [+{len(text) - limit} chars]"


def build_tutorial_plan_user_prompt(user_request: str) -> str:
    return (
        "Create a compact tutorial plan for this user request. "
        "Use the attached screen images as the current visual context.\n\n"
        f"User request: {user_request}"
    )


def format_validation_error(error: ValueError) -> str:
    cause = error.__cause__
    return str(cause) if cause is not None else str(error)
