from __future__ import annotations

import unittest

from backend.images import UploadedImage
from backend.instruction_verifier import (
    VERIFIER_SYSTEM_PROMPT,
    VerifierVerdict,
    build_request,
    classify_screen,
    parse_verdict,
)
from backend.llm import LLMRequest


def make_screen() -> UploadedImage:
    return UploadedImage(data=b"\x00", mime_type="image/png", filename="s")


class _StubLLM:
    def __init__(self, raw: str | None = None, raises: Exception | None = None) -> None:
        self.raw = raw
        self.raises = raises
        self.calls: list[LLMRequest] = []

    def complete_text(self, request: LLMRequest) -> str:
        self.calls.append(request)
        if self.raises is not None:
            raise self.raises
        assert self.raw is not None
        return self.raw

    def stream_text(self, request):  # pragma: no cover
        raise NotImplementedError

    def stream_tutorial_tool_calls(self, request):  # pragma: no cover
        raise NotImplementedError

    def stream_tutorial_events(self, request):  # pragma: no cover
        raise NotImplementedError


class ParseVerdictTests(unittest.TestCase):
    def test_yes_verdict(self) -> None:
        v = parse_verdict('{"verdict": "yes", "reason": "looks right"}')
        self.assertEqual(v, VerifierVerdict(ok=True, reason="looks right"))

    def test_no_verdict(self) -> None:
        v = parse_verdict('{"verdict": "no", "reason": "wrong app"}')
        self.assertEqual(v, VerifierVerdict(ok=False, reason="wrong app"))

    def test_unknown_verdict_fails_open(self) -> None:
        v = parse_verdict('{"verdict": "maybe", "reason": "shrug"}')
        self.assertTrue(v.ok)

    def test_unparseable_fails_open(self) -> None:
        v = parse_verdict("not json at all")
        self.assertTrue(v.ok)
        self.assertEqual(v.reason, "verifier_unparseable")

    def test_strips_code_fence(self) -> None:
        v = parse_verdict('```json\n{"verdict":"no","reason":"x"}\n```')
        self.assertEqual(v, VerifierVerdict(ok=False, reason="x"))

    def test_missing_reason_gets_default(self) -> None:
        v = parse_verdict('{"verdict": "no"}')
        self.assertEqual(v.reason, "no reason given")


class BuildRequestTests(unittest.TestCase):
    def test_request_uses_system_prompt_and_screen(self) -> None:
        req = build_request("Open Settings", make_screen())
        self.assertEqual(req.system_prompt, VERIFIER_SYSTEM_PROMPT)
        self.assertIn("Open Settings", req.user_text)
        self.assertEqual(len(req.images), 1)
        self.assertEqual(req.response_mime_type, "application/json")


class ClassifyScreenTests(unittest.TestCase):
    def test_returns_parsed_verdict(self) -> None:
        llm = _StubLLM(raw='{"verdict":"no","reason":"wrong window"}')
        v = classify_screen(llm, "Click Save", make_screen())
        self.assertEqual(v, VerifierVerdict(ok=False, reason="wrong window"))
        self.assertEqual(len(llm.calls), 1)

    def test_llm_error_fails_open(self) -> None:
        llm = _StubLLM(raises=RuntimeError("network died"))
        v = classify_screen(llm, "Click Save", make_screen())
        self.assertTrue(v.ok)
        self.assertEqual(v.reason, "verifier_error")


if __name__ == "__main__":
    unittest.main()
