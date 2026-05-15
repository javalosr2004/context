from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from backend.images import UploadedImage
from backend.llm import LLMRequest, LLMTextDelta, LLMToolCallEvent, MultimodalLLM
from backend.tutorial_schema import (
    PlannerConversation,
    PlannerReply,
    PlannerReady,
    TutorialPlan,
    TutorialPlannerReplyValidationError,
    TutorialPlanValidationError,
    TutorialStep,
    parse_tutorial_planner_reply,
    parse_tutorial_plan,
    tutorial_planner_reply_response_schema,
    tutorial_plan_response_schema,
)
from backend.tutorial_tools import (
    plan_from_steps,
    step_from_tool_call,
)


logger = logging.getLogger(__name__)

TutorialStepSink = Callable[[TutorialStep], None]
TutorialTextSink = Callable[[str], None]


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

TUTORIAL_SESSION_PLANNER_SYSTEM_PROMPT = """
You are Context, a macOS teaching assistant for an overlay system.
Return exactly one planner reply matching the provided response schema.

Decide internally whether the user needs runnable overlay steps or more
conversation. Never announce or describe the internal route to the user.

- If the user asks for explanation, strategy, clarification, options, or general
  help that is not yet a concrete screen action, return type "needs_context"
  with one specific user-facing question or prompt that keeps the conversation
  moving.
- If the current screen, user goal, or previous context is insufficient to
  produce concrete runnable tutorial steps, return type "needs_context" with one
  specific user-facing question. Do not invent generic tutorial steps.
- When the context is sufficient for visible screen work, return type "ready"
  with a valid TutorialPlan.

For "needs_context", make the question useful, not abrupt. Briefly anchor what
you understood and ask for the missing decision or context. For "ready", keep
each instruction short and readable for a human overlay.

Use semantic targets, not coordinates, unless coordinates were provided.
Use confirmation when confidence is low, the target is ambiguous, or the
screen may not match the expected state.
""".strip()

TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT = """
You are Context, a macOS teaching assistant.

Help the user understand and complete what is on their screen. Answer
clearly and directly. Explain, recommend, define, or compare when asked.
Ask one focused question when you need a specific piece of information you
cannot see.

The action tools exist for one thing: walking the user through a specific
click, keystroke, scroll, or wait on their current screen, right now. If
the user has not asked for that, do not call them.

When you do call an action tool, human_text is one concise on-screen
instruction. agent_description says where to look and what the target
looks like. Do not use coordinates unless the user provided them.

Do not narrate your reasoning. Do not announce what you are about to do.
Do not explain when or why you are or are not taking an action. Do not
refer to yourself as a planner, generator, tutorial, or overlay. Just
answer, or just act.
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


@dataclass(frozen=True)
class TutorialSessionPlanRequest:
    session_id: str
    goal: str
    messages: list[dict[str, str]]
    latest_screen: UploadedImage | None


class TutorialGuide:
    def __init__(self, llm: MultimodalLLM) -> None:
        self._llm = llm

    def create_plan(self, request: TutorialPlanRequest) -> TutorialPlan:
        return generate_tutorial_plan(
            llm=self._llm,
            prompt=build_tutorial_plan_user_prompt(request.text),
            images=request.images,
        )

    def create_session_planner_reply(
        self,
        request: TutorialSessionPlanRequest,
        on_streamed_step: TutorialStepSink | None = None,
        on_text_delta: TutorialTextSink | None = None,
    ) -> PlannerReply:
        streamed_reply = self.create_streamed_session_planner_reply(
            request,
            on_streamed_step=on_streamed_step,
            on_text_delta=on_text_delta,
        )
        if streamed_reply is not None:
            return streamed_reply

        return self.create_structured_session_planner_reply(request)

    def create_structured_session_planner_reply(
        self,
        request: TutorialSessionPlanRequest,
    ) -> PlannerReply:
        return generate_tutorial_planner_reply(
            llm=self._llm,
            prompt=build_tutorial_session_user_prompt(request),
            images=[request.latest_screen] if request.latest_screen is not None else [],
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

    def create_streamed_session_planner_reply(
        self,
        request: TutorialSessionPlanRequest,
        on_streamed_step: TutorialStepSink | None = None,
        on_text_delta: TutorialTextSink | None = None,
    ) -> PlannerReady | PlannerConversation | None:
        steps = []
        text_deltas = []
        for event in self._llm.stream_tutorial_events(
            LLMRequest(
                system_prompt=TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT,
                user_text=build_tutorial_session_user_prompt(request),
                images=[request.latest_screen]
                if request.latest_screen is not None
                else [],
                enable_search_grounding=False,
                temperature=0,
            )
        ):
            if isinstance(event, LLMTextDelta):
                if on_text_delta is not None:
                    on_text_delta(event.text)
                text_deltas.append(event.text)
                continue

            if isinstance(event, LLMToolCallEvent):
                step = step_from_tool_call(event.tool_call, len(steps))
                steps.append(step)
                if on_streamed_step is not None:
                    on_streamed_step(step)

        if not steps and any(text.strip() for text in text_deltas):
            logger.info(
                "Tutorial tool stream produced conversation text",
                extra={"session_id": request.session_id},
            )
            return PlannerConversation(
                type="conversation",
                message="".join(text_deltas).strip(),
            )

        if not steps:
            logger.info(
                "Tutorial tool stream produced no steps; falling back to planner reply",
                extra={"session_id": request.session_id},
            )
            return None

        logger.info(
            "Tutorial tool stream produced steps",
            extra={"session_id": request.session_id, "step_count": len(steps)},
        )
        return PlannerReady(type="ready", plan=plan_from_steps(request.goal, steps))


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


def generate_tutorial_planner_reply(
    llm: MultimodalLLM,
    prompt: str,
    images: list[UploadedImage] | None = None,
    max_retries: int = MAX_TUTORIAL_PLAN_RETRIES,
) -> PlannerReply:
    last_text = ""
    error_text = ""
    last_error: TutorialPlannerReplyValidationError | None = None
    request_images = images or []

    logger.info(
        "Generating tutorial planner reply",
        extra={"image_count": len(request_images), "max_attempts": max_retries + 1},
    )

    for attempt in range(max_retries + 1):
        attempt_number = attempt + 1
        started_at = time.perf_counter()
        raw_reply = llm.complete_text(
            LLMRequest(
                system_prompt=TUTORIAL_SESSION_PLANNER_SYSTEM_PROMPT,
                user_text=plan_generation_prompt(
                    prompt=prompt,
                    attempt=attempt,
                    error_text=error_text,
                    last_text=last_text,
                ),
                images=request_images,
                enable_search_grounding=False,
                response_mime_type="application/json",
                response_schema=tutorial_planner_reply_response_schema(),
                temperature=0,
            )
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        last_text = raw_reply
        logger.info(
            "Tutorial planner reply LLM call completed",
            extra={
                "attempt": attempt_number,
                "elapsed_ms": elapsed_ms,
                "raw_chars": len(raw_reply),
            },
        )

        try:
            reply = parse_tutorial_planner_reply(raw_reply)
            logger.info(
                "Tutorial planner reply validated",
                extra={"attempt": attempt_number, "reply_type": reply.type},
            )
            return reply
        except TutorialPlannerReplyValidationError as error:
            last_error = error
            error_text = format_validation_error(error)
            logger.warning(
                "Tutorial planner reply validation failed",
                extra={
                    "attempt": attempt_number,
                    "max_attempts": max_retries + 1,
                    "error": error_text,
                    "raw_output": truncate(raw_reply, RAW_OUTPUT_LOG_LIMIT),
                },
            )

    logger.error(
        "Tutorial planner reply exhausted retries",
        extra={
            "max_attempts": max_retries + 1,
            "last_error": format_validation_error(last_error) if last_error else None,
            "last_raw_output": truncate(last_text, RAW_OUTPUT_LOG_LIMIT),
        },
    )
    raise TutorialPlannerReplyValidationError(
        f"Could not generate valid tutorial planner reply after {max_retries + 1} "
        f"attempts. Last error: {format_validation_error(last_error) if last_error else 'unknown'}. "
        f"Last output: {truncate(last_text, 500)}"
    ) from last_error


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


def build_tutorial_session_user_prompt(request: TutorialSessionPlanRequest) -> str:
    return (
        "Plan the next tutorial steps from the current session state. "
        "Use the attached screen image as the latest visual context.\n\n"
        f"Session ID: {request.session_id}\n"
        f"Goal: {request.goal}\n\n"
        "Conversation context:\n"
        f"{format_session_messages(request.messages)}"
    )


def format_session_messages(messages: list[dict[str, str]]) -> str:
    if not messages:
        return "- <none>"

    lines = []
    for message in messages:
        role = message.get("role", "unknown")
        content = message.get("content", "")
        lines.append(f"- {role}: {content}")
    return "\n".join(lines)


def format_validation_error(error: ValueError) -> str:
    cause = error.__cause__
    return str(cause) if cause is not None else str(error)
