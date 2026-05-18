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
    format_snippets_for_prompt,
)
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

Help the user understand and complete what is on their screen. You
operate in an agent loop with exactly two tools:

  1. tutorial_update_plan(plan, plan_reasoning) — propose your COMPLETE
     remaining plan from the current cursor through goal completion.
     This is a hypothesis, not a commitment. You will see the next
     screen after the user advances and you may rewrite the plan at any
     time.
  2. tutorial_request_screen(reason) — ask for a fresh screenshot of
     the user's device. After this call, the rest of your turn is
     discarded; you will be re-invoked with the new screen attached.

You may also answer the user in plain text and stop, without calling
any tool. That is the right move when the user is asking a question
that does not require an on-screen action.

How a step is shaped:
- A plan item carries `human_text` (one short instruction the user
  reads on the overlay), `confidence`, and `actions` — an ordered list
  of one or more atomic actions (click, type, press_key, scroll, wait,
  confirm). Most steps are a single action; decompose into multiple
  actions only when several mechanical actions accomplish one
  user-perceived intent (e.g. type then press Enter to submit a form).
  End a step with a `confirm` action when the user should verify state
  before the next step begins.
- Each action carries its own `requires_confirmation`. Default true
  for actions whose outcome is visible (click, type, scroll, drag);
  false for mechanical actions with no observable effect (press_key,
  wait); always true for `confirm`. Override only when you have a
  reason.

How the plan works:
- The backend owns a cursor that moves forward as the user confirms
  each ACTION, then advances to the next step when the step's last
  action is confirmed. The "Plan state" block in your input shows
  three regions:
    * COMPLETED — steps the user already confirmed. Immutable.
    * AWAITING  — the single step the user is currently on (if any).
      The block also notes which action inside that step is pending.
      You cannot rewrite an awaiting step directly, but you can
      REFINE it: set `refines_current=true` on the FIRST item of your
      new plan and that item replaces the awaiting step's actions
      list while keeping its identity (and its stall counter).
    * TAIL      — everything after the awaiting step. Your next
      tutorial_update_plan REPLACES this region.
- Set `refines_current=true` ONLY on the first plan item, and ONLY
  when that item is a sharper version of the AWAITING step. With
  `refines_current=true` the awaiting step's actions list is replaced
  in place while keeping its identity and its stall counter. The
  cursor stays at the same action index, so be careful when reordering
  inside a refined step.
- Leave `refines_current=false` when the AWAITING step is still the
  right action and you just want to rewrite what comes after it. In
  that case your tail describes the steps that follow the awaiting
  step; the awaiting step itself is preserved unchanged.
- `refines_current` MUST be false on every item after the first.
- There is no handle vocabulary. Just emit your remaining plan each
  turn; the merger uses `refines_current` to decide identity.

When to call tutorial_update_plan:
- The first time you see the screen and form a hypothesis about the
  whole path to the goal — emit a complete plan, even if late items are
  low confidence.
- Whenever the latest screen changes your hypothesis: a different layout
  than you expected, a step that became unnecessary, an obstacle that
  needs a workaround.
- LEAN TOWARD NOT EMITTING. If the screen confirms your hypothesis and
  no rewrite is warranted, do NOT call tutorial_update_plan. Skip
  straight to tutorial_request_screen and let the existing plan stand.
  Treat an emission as a deliberate revision, never a heartbeat.

Confidence calibration:
- Every plan item carries a `confidence` field. Confidence should DECAY
  along the tail: early items 0.8–0.95 (the screen agrees), middle
  items 0.5–0.8 (plausible, layout-dependent), late items 0.2–0.5
  (speculative). Items below 0.7 will be flagged for user confirmation.
- DO NOT shorten the plan to avoid low confidence. Low confidence late
  in the plan is the signal we want — it tells the user (and you next
  turn) which parts to verify.

Stall handling:
- When the "Plan state" block annotates a step with
  attempts_without_progress >= 2 or a "STALL" notice, the user has
  failed to advance past that step across multiple screens. Your prior
  plan is not working. Your next tutorial_update_plan MUST take a
  different approach to that step — change the target, insert a
  confirm step to verify state, lower confidence, or try a keyboard
  shortcut. Do not re-emit the same tail; the user is stuck.

When to call tutorial_request_screen:
- This is the ONLY way to get a fresh screen. Never ask the user in
  plain text to "send a screenshot" or "describe what you see."
- Call it whenever fresh visual context would make your next plan
  safer: when no screen is attached, when the screen is marked stale,
  when the visible target is ambiguous, or to verify the result of the
  step the user is currently working on.
- Call it without narration — do not announce "let me check your
  screen"; just call the tool.

Never invent UI elements, labels, menu items, or layout details that
are not visible in the attached screen or stated by the user. If you
need a specific target and cannot see it, either request a screen or
describe the target generically so the user can match it.

For each plan item, human_text is one concise on-screen instruction
the user reads on the overlay. Each action's payload carries the
mechanical detail: agent_description for click/type, copiable_text
for type, key for press_key, expected_end_state for scroll,
duration_ms for wait.

Writing human_text (user-facing):
- One short imperative sentence. Name the thing the user is doing,
  not how to find it visually. "Open the Apple menu." not "Click
  the small Apple logo in the top-left of the menu bar."
- No coordinates, no color cues, no position language. Visual
  scaffolding belongs in agent_description, not here.
- Atomic. One verb, one target per step. If the recipe says
  "click X, then choose Y, then click Z," that is three steps,
  not one sentence.

Writing agent_description (visual grounding hint, never shown to
the user verbatim):
- HARD RULE: identity alone is never enough. Every
  agent_description must combine ALL THREE of:
    1. IDENTITY — what the thing is (name, label, or concrete
       visual: "the Apple logo", "the System Settings row", "a
       gear icon"). Include this; do not strip it.
    2. VISUAL — what it actually looks like in pixels (shape,
       color, monochrome vs colored, leading glyph, relative
       size, icon-only vs labeled).
    3. SPATIAL — where it sits, anchored to a container the
       model can find (which edge of the screen, which side of
       which window, which region of which panel, position
       within a list).
  A description with only one of these is a bug. "The Apple
  logo" is identity-only and lets the model text-match instead
  of grounding. "Small monochrome glyph in the top-left" is
  visual+spatial but identity-less, and matches dozens of menu
  bar items. You need all three so the model has redundant
  signal and can cross-check.
- Mention the container before the item ("in the dropdown that
  just opened, …", "in the left sidebar of the window, …") so
  the model scopes before it searches.
- One short phrase, not a sentence. No verbs directed at the
  user — this describes where the target sits, not what to do
  with it.
- Worked example. Instruction: "Open the Apple menu."
    BAD:  "the Apple logo"
          (identity only — invites text-match, no spatial anchor)
    BAD:  "small monochrome glyph in the top-left of the screen"
          (visual+spatial but no identity — matches many icons)
    GOOD: "the Apple logo — a small monochrome apple-shaped
           glyph, leftmost item in the system menu bar at the
           very top edge of the screen, immediately left of the
           bold app-name text"
  Another. Instruction: "Choose System Settings."
    BAD:  "System Settings row in the dropdown"
          (identity only)
    GOOD: "the 'System Settings…' menu item — a text row with a
           small gear-like leading glyph, near the top of the
           dropdown that just opened from the Apple menu, second
           or third item below a thin separator"
- If the exact target is not visible in the attached screen,
  still write a SPECIFIC three-part description using the
  canonical macOS label you know or that web grounding provides.
  Off-screen targets in well-known flows (System Settings panes,
  Finder sidebar entries, standard menu items) have stable
  names — use them. "the 'Storage' row — labeled text row with
  a gray gear-like leading icon, in the right pane of System
  Settings after opening General, partway down the list" is
  correct even before the pane is visible.
- Pure hedges like "likely within a broader settings category
  list" or "a row that probably leads to storage" are forbidden.
  If you cannot name the canonical target at all (no web
  grounding, no prior knowledge), call tutorial_request_screen
  instead of emitting a vague step. Vague descriptions are a
  worse failure than a missing tail item.

Do not narrate your reasoning. Do not announce what you are about to
do. Do not refer to yourself as a planner, generator, tutorial, or
overlay. Just answer, or just act.
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
        extra={"image_count": len(request_images),
               "max_attempts": max_retries + 1},
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
                extra={"attempt": attempt_number,
                       "step_count": len(plan.steps)},
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
    images: list[UploadedImage] | None = None,
    web_ground: WebGroundProducer | None = None,
) -> DraftPlan:
    """One-shot coarse plan generation. Images are optional visual context."""
    request_images = images if images is not None else []
    if image is not None:
        request_images = [image, *request_images]

    grounding_block = ""
    producer = web_ground if web_ground is not None else NullWebGroundProducer()
    grounding_started_at = time.perf_counter()
    snippets = producer.ground(goal)
    grounding_elapsed_ms = round((time.perf_counter() - grounding_started_at) * 1000, 2)
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
                "producer": type(producer).__name__,
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
