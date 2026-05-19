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
    "next step of a tutorial. You must ground every verdict in specific "
    "visual evidence — name the exact UI element, quote the exact text, "
    "or describe the exact region you observed. Do NOT accept the screen "
    "just because it looks like the right page or app; that is not "
    "evidence. If you cannot point to concrete evidence, answer 'unsure' "
    "or 'no'.\n\n"
    "Answer strictly in JSON with two fields: verdict (one of 'yes', "
    "'no', 'unsure') and evidence (one short sentence quoting or naming "
    "the specific element you observed, or describing what is missing). "
    "Do not include any text outside the JSON object."
)


@dataclass(frozen=True)
class VerifierVerdict:
    ok: bool
    reason: str


def build_request(instruction: str, screen: UploadedImage) -> LLMRequest:
    user_text = (
        f"Expected state after the previous action: {instruction}\n\n"
        "Look at the screenshot and find SPECIFIC visual evidence that "
        "this state has been reached — a labeled button, a status badge, "
        "a page title, a URL bar, a confirmation message. Quote or name "
        "the exact element. If you can only say 'looks like the right "
        "page' without pointing to a concrete element, the correct "
        "verdict is 'unsure', not 'yes'.\n\n"
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
        # No concrete evidence → treat as rejection so we replan rather
        # than rubber-stamp. The replan note carries the evidence string
        # so the planner sees what was missing.
        return VerifierVerdict(ok=False, reason=f"unsure: {evidence}")
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
