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
    "You verify whether a screenshot shows the expected state for the "
    "next step of a tutorial. Answer strictly in JSON with two fields: "
    "verdict ('yes' if the screen is plausibly the right starting state "
    "for the instruction, 'no' only if it clearly is not — wrong app, "
    "wrong window, or missing required UI) and reason (one short "
    "sentence). Do not include any text outside the JSON object."
)


@dataclass(frozen=True)
class VerifierVerdict:
    ok: bool
    reason: str


def build_request(instruction: str, screen: UploadedImage) -> LLMRequest:
    user_text = (
        f"Expected instruction: {instruction}\n\n"
        "Is the attached screenshot a plausible starting state for this "
        'instruction? Respond with JSON: {"verdict": "yes"|"no", '
        '"reason": "..."}'
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
    reason = str(payload.get("reason", "")).strip() or "no reason given"
    if verdict == "no":
        return VerifierVerdict(ok=False, reason=reason)
    return VerifierVerdict(ok=True, reason=reason)


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
