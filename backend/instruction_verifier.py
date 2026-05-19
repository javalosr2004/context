"""Single-shot screen-vs-instruction classifier for tutorial verification.

When the user advances to a new instruction (the parent of [actions]),
the session asks a fast multimodal LLM whether the current screen is a
plausible starting state for the instruction. A "no" verdict triggers
replan; a "yes" lets the user proceed.

Fail-open: any error or unparseable response returns a "yes" verdict so
a flaky verifier never locks the user out of the tutorial.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from backend.images import UploadedImage
from backend.llm import LLMRequest, MultimodalLLM


logger = logging.getLogger(__name__)


VERIFIER_SYSTEM_PROMPT = (
    "You are a safety check for a tutorial overlay. The user is about to "
    "attempt the next instruction. Your only job is to detect when the "
    "screen is CLEARLY INCONSISTENT with that instruction — for example: "
    "an unrelated application is in focus, an error dialog is blocking "
    "the UI, the user is on a sign-in wall when the instruction assumes "
    "they are signed in, or the previous step obviously failed. \n\n"
    "Default to 'yes'. Only answer 'no' when you can point to a SPECIFIC "
    "blocking element (name it or quote its text). If the screen merely "
    "lacks the exact element named in the instruction, that is NOT a "
    "blocker — the instruction's element may be one click or scroll "
    "away. Answer 'unsure' only when something looks off but you cannot "
    "name a concrete blocker.\n\n"
    "Respond strictly as JSON with two fields: verdict (one of 'yes', "
    "'no', 'unsure') and evidence (one short sentence naming the "
    "blocking element for 'no', or what looks plausible for 'yes'). "
    "Do not include any text outside the JSON object."
)


@dataclass(frozen=True)
class VerifierVerdict:
    ok: bool
    reason: str


def build_request(instruction: str, screen: UploadedImage) -> LLMRequest:
    user_text = (
        f"Next instruction the user will attempt: {instruction}\n\n"
        "Look at the screenshot. Is there a SPECIFIC blocker that makes "
        "this instruction impossible to attempt right now — wrong app in "
        "focus, modal error, sign-in wall, prior step visibly failed? "
        "Name the blocking element if so. Otherwise answer 'yes' — the "
        "target element doesn't need to be visible on screen; the user "
        "may need to click, scroll, or navigate to reach it.\n\n"
        'Respond with JSON: {"verdict": "yes"|"no"|"unsure", '
        '"evidence": "..."}'
    )
    return LLMRequest(
        system_prompt=VERIFIER_SYSTEM_PROMPT,
        user_text=user_text,
        images=[screen],
        temperature=0,
        response_mime_type="application/json",
    )


def parse_verdict(raw: str) -> VerifierVerdict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return VerifierVerdict(ok=True, reason="verifier_unparseable")
    if not isinstance(payload, dict):
        return VerifierVerdict(ok=True, reason="verifier_unparseable")
    verdict = str(payload.get("verdict", "")).strip().lower()
    evidence = (
        str(payload.get("evidence", "")).strip()
        or str(payload.get("reason", "")).strip()
        or "no evidence given"
    )
    if verdict == "no":
        return VerifierVerdict(ok=False, reason=evidence)
    if verdict == "unsure":
        # Pass through — a precondition gate shouldn't replan on doubt;
        # only a confident "no" (a named blocker) interrupts the walk.
        return VerifierVerdict(ok=True, reason=f"unsure: {evidence}")
    return VerifierVerdict(ok=True, reason=evidence)


def classify_screen(
    llm: MultimodalLLM,
    instruction: str,
    screen: UploadedImage,
) -> VerifierVerdict:
    """Sync, single-shot classification. Caller should run in a thread."""
    try:
        raw = llm.complete_text(build_request(instruction, screen))
    except Exception:
        logger.exception("[verifier] llm call failed")
        return VerifierVerdict(ok=True, reason="verifier_error")
    verdict = parse_verdict(raw)
    logger.info(
        "[verifier] raw_response",
        extra={
            "instruction": instruction[:120],
            "raw_chars": len(raw),
            "raw_preview": raw.strip()[:200],
            "parsed_ok": verdict.ok,
            "parsed_reason": verdict.reason,
        },
    )
    return verdict
