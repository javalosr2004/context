"""Single-shot screen-vs-instruction classifier for tutorial verification.

When the user advances to a new instruction (the parent of [actions]),
the session asks a fast multimodal LLM to classify the current screen
relative to that instruction:

    on_track  — screen is a plausible starting state; proceed.
    blocked   — a concrete element (modal, error, sign-in wall, an
                in-flight picker/confirmation from a different flow)
                prevents attempting the instruction; replan. Also: the
                previous step's intended effect did not occur (e.g. user
                clicked Sign Out but is still in the sign-out picker).
    diverged  — screen is a coherent app state, but not the one this
                instruction assumes; the user is somewhere else in the
                flow (often already past it). Replan.
    unsure    — verifier can't tell. Fail-open: proceed.

The model is forced to first describe the dominant visible UI in one
phrase ("screen_summary") before picking a verdict — this disciplines
the judgment by making the model commit to what it actually sees before
classifying.

Fail-open: any error or unparseable response yields `unsure` so a flaky
verifier never locks the user out of the tutorial.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Literal

from backend.images import UploadedImage
from backend.llm import LLMRequest, MultimodalLLM


logger = logging.getLogger(__name__)


Verdict = Literal["on_track", "blocked", "diverged", "unsure"]
_VALID_VERDICTS: frozenset[str] = frozenset(
    {"on_track", "blocked", "diverged", "unsure"}
)


VERIFIER_SYSTEM_PROMPT = (
    "You classify whether the user's screen matches the next tutorial "
    "instruction. You MUST answer in two steps, both in the JSON "
    "response:\n\n"
    "  1. screen_summary — a short phrase (<= 12 words) naming the "
    "dominant visible UI on screen. Examples: 'GitHub sign-out account "
    "picker', 'Signed-in GitHub dashboard', 'Empty new tab page', "
    "'GitHub signup form with email field focused'. Be concrete about "
    "what is in front of the user RIGHT NOW — don't summarize what "
    "they could navigate to.\n"
    "  2. verdict — one of:\n"
    "      on_track  — from the screen you just summarized, the user "
    "can begin the instruction's first action right now, possibly after "
    "one obvious click on something visible. If reaching the "
    "instruction would require completing a different flow first "
    "(finishing a sign-out, dismissing an account picker, resolving a "
    "confirmation dialog, navigating through unrelated pages), that is "
    "NOT on_track.\n"
    "      blocked   — a specific UI element occupies the screen and "
    "must be resolved before the instruction can be attempted. "
    "Examples: a modal/error dialog, a sign-in wall, an OS permission "
    "prompt, a picker / confirmation / wizard step belonging to a "
    "DIFFERENT flow, or visible evidence the previous step did not "
    "complete (e.g. the previous step was 'Sign out' but the screen "
    "still shows the sign-out picker). Name the element.\n"
    "      diverged  — the screen is a coherent app state, but it is "
    "NOT where this instruction assumes the user is. Common cases: the "
    "user has already completed this step (and likely later ones) — "
    "e.g. the instruction says 'sign up' but the screen shows a "
    "signed-in dashboard. Name what you see vs. what the instruction "
    "assumes.\n"
    "      unsure    — you cannot confidently pick one of the above.\n\n"
    "If a previous step is provided, FIRST check whether its intended "
    "effect is visible. If the previous step was 'Sign out' but the "
    "screen still shows the sign-out picker, the prior step did not "
    "complete — that is blocked. Do NOT default to on_track just "
    "because the right app is visible and no error is shown.\n\n"
    'Respond strictly as JSON: {"screen_summary": "...", "verdict": '
    '"on_track"|"blocked"|"diverged"|"unsure", "evidence": "one short '
    'sentence"}. No text outside the JSON.'
)


@dataclass(frozen=True)
class VerifierVerdict:
    verdict: Verdict
    reason: str
    screen_summary: str = ""

    @property
    def ok(self) -> bool:
        """True when the gate should let the walk proceed without replan."""
        return self.verdict in ("on_track", "unsure")


def build_request(
    instruction: str,
    screen: UploadedImage,
    goal: str | None = None,
    previous_instruction: str | None = None,
) -> LLMRequest:
    goal_line = f"Overall tutorial goal: {goal}\n" if goal else ""
    prev_line = (
        f"Previous step the user just attempted: {previous_instruction}\n"
        if previous_instruction
        else ""
    )
    user_text = (
        f"{goal_line}"
        f"{prev_line}"
        f"Next instruction the user will attempt: {instruction}\n\n"
        "Answer in two steps. First, in screen_summary, name the "
        "dominant visible UI on the screen in <= 12 words — be "
        "concrete about what's in front of the user right now. Then "
        "pick a verdict.\n\n"
        "Test for on_track: from the screen you just summarized, can "
        "the user begin the next instruction's first action right now "
        "(possibly after one obvious click on something visible)? If "
        "they must first finish some other flow (sign-out, picker, "
        "confirmation, wizard step), it is blocked. If the previous "
        "step's effect isn't visible on screen, it is also blocked. If "
        "the screen contradicts where this instruction assumes the "
        "user is (already past it, wrong section), it is diverged.\n\n"
        'Respond with JSON: {"screen_summary": "...", "verdict": '
        '"on_track"|"blocked"|"diverged"|"unsure", "evidence": "..."}'
    )
    return LLMRequest(
        system_prompt=VERIFIER_SYSTEM_PROMPT,
        user_text=user_text,
        images=[screen],
        temperature=0,
        response_mime_type="application/json",
    )


def _normalize_verdict(raw: str) -> Verdict | None:
    """Map raw verdict strings (incl. legacy yes/no) to the new enum."""
    v = raw.strip().lower()
    if v in _VALID_VERDICTS:
        return v  # type: ignore[return-value]
    # Backward-compat for the old yes/no/unsure prompt.
    if v == "yes":
        return "on_track"
    if v == "no":
        return "blocked"
    return None


def parse_verdict(raw: str) -> VerifierVerdict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return VerifierVerdict(verdict="unsure", reason="verifier_unparseable")
    if not isinstance(payload, dict):
        return VerifierVerdict(verdict="unsure", reason="verifier_unparseable")
    verdict = _normalize_verdict(str(payload.get("verdict", "")))
    evidence = (
        str(payload.get("evidence", "")).strip()
        or str(payload.get("reason", "")).strip()
        or "no evidence given"
    )
    screen_summary = str(payload.get("screen_summary", "")).strip()
    if verdict is None:
        # Unknown label: fail-open as unsure so the walk continues.
        return VerifierVerdict(
            verdict="unsure", reason=evidence, screen_summary=screen_summary
        )
    return VerifierVerdict(
        verdict=verdict, reason=evidence, screen_summary=screen_summary
    )


def classify_screen(
    llm: MultimodalLLM,
    instruction: str,
    screen: UploadedImage,
    goal: str | None = None,
    previous_instruction: str | None = None,
) -> VerifierVerdict:
    """Sync, single-shot classification. Caller should run in a thread."""
    started_at = time.perf_counter()
    try:
        raw = llm.complete_text(
            build_request(instruction, screen, goal, previous_instruction)
        )
    except Exception:
        logger.exception(
            "[verifier] llm call failed",
            extra={"elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2)},
        )
        return VerifierVerdict(verdict="unsure", reason="verifier_error")
    llm_elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.info(
        "[verifier] llm_call",
        extra={
            "elapsed_ms": llm_elapsed_ms,
            "raw_chars": len(raw),
        },
    )
    verdict = parse_verdict(raw)
    logger.info(
        "[verifier] raw_response",
        extra={
            "instruction": instruction[:120],
            "previous_instruction": (previous_instruction or "")[:120],
            "raw_chars": len(raw),
            "raw_preview": raw.strip()[:200],
            "verdict": verdict.verdict,
            "screen_summary": verdict.screen_summary,
            "parsed_ok": verdict.ok,
            "parsed_reason": verdict.reason,
        },
    )
    return verdict
