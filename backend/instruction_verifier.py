"""Single-shot screen-vs-instruction classifier for tutorial verification.

When the user advances to a new instruction (the parent of [actions]),
the session asks a fast multimodal LLM to classify the current screen
relative to that instruction:

    on_track  — screen is a plausible starting state; proceed.
    blocked   — a concrete element (modal, error, sign-in wall) prevents
                attempting the instruction; replan.
    diverged  — screen is a coherent app state, but not the one this
                instruction assumes; the user is somewhere else in the
                flow (often already past it). Replan.
    unsure    — verifier can't tell. Fail-open: proceed.

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
    "instruction. Choose exactly one verdict:\n\n"
    "  on_track  — from THIS exact screen, the user can plausibly "
    "attempt the instruction's first action, possibly after one obvious "
    "click on a visible target. If reaching the instruction would "
    "require completing a different flow first (finishing a sign-out, "
    "dismissing an account picker, resolving a confirmation dialog, "
    "navigating through unrelated pages), that is NOT on_track.\n"
    "  blocked   — a specific UI element occupies the screen and must "
    "be resolved before the instruction can be attempted. Examples: a "
    "modal/error dialog, a sign-in wall, an OS permission prompt, a "
    "picker / confirmation / wizard step belonging to a different flow, "
    "or visible evidence the previous step failed. Name the element.\n"
    "  diverged  — the screen shows a coherent app state, but it is NOT "
    "where this instruction assumes the user is. Common cases: the user "
    "has already completed this step (and likely later ones) — e.g. the "
    "instruction says 'sign up' but the screen shows a signed-in "
    "dashboard; the user is in a different app or a different section "
    "of the flow than the instruction expects. Name what you see vs. "
    "what the instruction assumes.\n"
    "  unsure    — you cannot confidently pick one of the above.\n\n"
    "Do NOT default to on_track just because the right app/site is "
    "visible and no error is shown. Ask: can the user, RIGHT NOW from "
    "this screen, begin the instruction? If they must first finish some "
    "other flow, the verdict is blocked or diverged. Respond strictly "
    'as JSON: {"verdict": "on_track"|"blocked"|"diverged"|"unsure", '
    '"evidence": "one short sentence"}. No text outside the JSON.'
)


@dataclass(frozen=True)
class VerifierVerdict:
    verdict: Verdict
    reason: str

    @property
    def ok(self) -> bool:
        """True when the gate should let the walk proceed without replan."""
        return self.verdict in ("on_track", "unsure")


def build_request(
    instruction: str,
    screen: UploadedImage,
    goal: str | None = None,
) -> LLMRequest:
    goal_line = (
        f"Overall tutorial goal: {goal}\n\n" if goal else ""
    )
    user_text = (
        f"{goal_line}"
        f"Next instruction the user will attempt: {instruction}\n\n"
        "Classify the screen as on_track, blocked, diverged, or unsure. "
        "Test: from this exact screen, can the user begin the "
        "instruction's first action right now (possibly after one "
        "obvious click on something visible)? If yes → on_track. If a "
        "specific UI element occupies the screen and must be resolved "
        "first — modal, error, sign-in wall, OS prompt, or a picker / "
        "confirmation / wizard step from a DIFFERENT flow (e.g. a "
        "sign-out picker when the instruction is to sign up) — that is "
        "blocked; name the element. If the screen is a coherent state "
        "that contradicts where this instruction assumes the user is "
        "(e.g. instruction says 'sign up' but the screen is a "
        "signed-in dashboard, or the user is past this step) → "
        "diverged.\n\n"
        'Respond with JSON: {"verdict": "on_track"|"blocked"|"diverged"'
        '|"unsure", "evidence": "..."}'
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
    if verdict is None:
        # Unknown label: fail-open as unsure so the walk continues.
        return VerifierVerdict(verdict="unsure", reason=evidence)
    return VerifierVerdict(verdict=verdict, reason=evidence)


def classify_screen(
    llm: MultimodalLLM,
    instruction: str,
    screen: UploadedImage,
    goal: str | None = None,
) -> VerifierVerdict:
    """Sync, single-shot classification. Caller should run in a thread."""
    started_at = time.perf_counter()
    try:
        raw = llm.complete_text(build_request(instruction, screen, goal))
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
            "raw_chars": len(raw),
            "raw_preview": raw.strip()[:200],
            "verdict": verdict.verdict,
            "parsed_ok": verdict.ok,
            "parsed_reason": verdict.reason,
        },
    )
    return verdict
