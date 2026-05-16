from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass

from backend.images import UploadedImage
from backend.llm import LLMRequest, MultimodalLLM
from backend.tutorial_schema import (
    DraftPlan,
    TutorialPlan,
    TutorialPlanValidationError,
    UserMessageIntentKind,
    draft_plan_response_schema,
    parse_draft_plan,
    parse_tutorial_plan,
    parse_user_message_intent,
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

TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT = """
You are Context, a macOS teaching assistant.

Help the user understand and complete what is on their screen. You operate
in an agent loop: each turn you may call tools, see their results, and call
more tools, or you may answer the user in plain text and stop.

You may be given a "Draft plan hypothesis" — a coarse, pre-generated list
of plausible steps toward the user's goal. Treat it as scaffolding, not
truth: refine each step against the live screen, batch confidently when
the draft and screen agree, and deviate when the screen contradicts it.
Do not narrate the draft to the user.

Tool rules:
- Use the tutorial_action_* tools to walk the user through concrete
  clicks, keystrokes, scrolls, or waits on their current screen. These
  are the ONLY way to express tutorial steps. Never list steps as plain
  text.
- Default to batching multiple tutorial_action_* calls in a single turn.
  A single-call turn should be the exception, not the rule. Batch whenever
  the sequence is predictable from what you can already see, from common
  well-known flows (URL bar → type URL → press Enter; open menu →
  navigate to item → click; sign-in form → type email → type password →
  click submit), or from the draft plan when the current screen agrees
  with it. Aim for 3-5 actions per turn when the path is clear.
- Fall back to one step at a time only when the next step genuinely
  depends on what the screen looks like after the previous one — a page
  load whose contents you cannot predict, a modal that may or may not
  appear, layout that differs across accounts, an authentication step
  whose success you cannot verify without a fresh screen. When in doubt
  between batching and stopping, prefer batching: the loop will request
  a fresh screen at the end if needed.
- Each tutorial_action_* call requires a `confidence` field — your honest
  prior probability that the action is correct given the screen. Do not
  always emit 0.9. Use 0.9+ only when the target is plainly visible and
  the step is obvious. Drop to 0.6-0.8 when you are inferring from the
  draft plan, when the layout may vary, or when the target is partially
  obscured. Drop below 0.6 when you are extrapolating beyond what the
  screen shows; the loop will treat low-confidence steps as needing
  confirmation.
- You have direct programmatic access to the user's screen via
  tutorial_request_screen. This is the ONLY way to get a fresh screen.
  Never ask the user, in plain text, to "send a screenshot", "share the
  next screen", "let me know what you see", or to describe their screen.
  If you would write any of those, call tutorial_request_screen instead.
  Call it without narration — do not announce "let me check your screen"
  or "I need to see your screen first"; just call the tool.
- Call tutorial_request_screen whenever fresh visual context would make
  the next instruction safer or more specific: when you are unsure, when
  no screen is attached, when the screen is marked stale, when the
  visible target is ambiguous, or after the user completed a
  state-changing action and the next step depends on the result.
  Do not guess at concrete UI details to avoid calling it.
- After a tutorial_scroll, you MUST call tutorial_request_screen before
  emitting another scroll, click, or type. The previous view is stale and
  you cannot tell whether the expected_end_state was reached without a fresh
  screen. The only exception is when the next step is unconditional
  regardless of what the scroll revealed (rare).
- If the same expected_end_state has not been reached after 2 attempts of
  the same action (e.g. two scrolls in the same direction, two clicks on
  the same target), stop repeating. Either request a screen, switch
  strategy (different direction, keyboard shortcut, search field, a
  different region of the UI), or ask the user in plain text what they
  currently see. Repeating a failing action a third time is never the
  right move.
- If the loop state says no screen is attached and the user wants help with
  something on their screen, request a screen before planning concrete steps.
- If the wrong app or window appears to be open, you may either guide the user
  to switch apps or request a screen after they switch, depending on which
  keeps the next instruction clear.
- When the user is asking a question that does not require an on-screen
  action (definitions, comparisons, explanations, recommendations), do not
  call any tool. Answer in plain text and let the loop end.

Never invent UI elements, labels, menu items, button names, or layout
details that are not visible in the attached screen or stated by the
user. If you need a specific target and cannot see it, either request
a screen or describe the target in generic terms the user can match
themselves. Do not fabricate concrete affordances to fill gaps.

human_text on each action tool is one concise on-screen instruction.
agent_description says where to look and what the target looks like. Do
not use coordinates unless the user provided them.

Do not narrate your reasoning. Do not announce what you are about to do.
Do not refer to yourself as a planner, generator, tutorial, or overlay.
Just answer, or just act.
""".strip()

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

DRAFT_PLAN_SYSTEM_PROMPT = """
You are sketching a coarse hypothesis plan for a macOS overlay tutorial.

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


RAW_OUTPUT_LOG_LIMIT = 2000


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

    logger.info(
        "Generating tutorial plan",
        extra={"image_count": len(request_images), "max_attempts": max_retries + 1},
    )

    for attempt in range(max_retries + 1):
        attempt_number = attempt + 1
        started_at = time.perf_counter()
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
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        last_text = raw_plan
        logger.info(
            "Tutorial plan LLM call completed",
            extra={
                "attempt": attempt_number,
                "elapsed_ms": elapsed_ms,
                "raw_chars": len(raw_plan),
            },
        )

        try:
            plan = parse_tutorial_plan(raw_plan)
            logger.info(
                "Tutorial plan validated",
                extra={"attempt": attempt_number, "step_count": len(plan.steps)},
            )
            return plan
        except TutorialPlanValidationError as error:
            last_error = error
            error_text = format_validation_error(error)
            logger.warning(
                "Tutorial plan validation failed",
                extra={
                    "attempt": attempt_number,
                    "max_attempts": max_retries + 1,
                    "error": error_text,
                    "raw_output": truncate(raw_plan, RAW_OUTPUT_LOG_LIMIT),
                },
            )

    logger.error(
        "Tutorial plan exhausted retries",
        extra={
            "max_attempts": max_retries + 1,
            "last_error": format_validation_error(last_error) if last_error else None,
            "last_raw_output": truncate(last_text, RAW_OUTPUT_LOG_LIMIT),
        },
    )
    raise TutorialPlanValidationError(
        f"Could not generate valid TutorialPlan after {max_retries + 1} attempts. "
        f"Last error: {format_validation_error(last_error) if last_error else 'unknown'}. "
        f"Last output: {truncate(last_text, 500)}"
    ) from last_error


def generate_draft_plan(
    llm: MultimodalLLM,
    goal: str,
    image: UploadedImage | None = None,
) -> DraftPlan:
    """One-shot coarse plan generation. Image is optional context."""
    images = [image] if image is not None else []
    started_at = time.perf_counter()
    raw = llm.complete_text(
        LLMRequest(
            system_prompt=DRAFT_PLAN_SYSTEM_PROMPT,
            user_text=(
                f"User goal: {goal}\n\n"
                "Return a draft plan as JSON matching the provided schema."
            ),
            images=images,
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
            "has_image": image is not None,
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


def format_validation_error(error: ValueError) -> str:
    cause = error.__cause__
    return str(cause) if cause is not None else str(error)
