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
    def test_on_track_verdict(self) -> None:
        v = parse_verdict(
            '{"screen_summary": "GitHub signup form", '
            '"verdict": "on_track", "evidence": "GitHub signup page visible"}'
        )
        self.assertEqual(v.verdict, "on_track")
        self.assertEqual(v.reason, "GitHub signup page visible")
        self.assertEqual(v.screen_summary, "GitHub signup form")
        self.assertTrue(v.ok)

    def test_screen_summary_optional_when_absent(self) -> None:
        v = parse_verdict('{"verdict": "on_track", "evidence": "fine"}')
        self.assertEqual(v.verdict, "on_track")
        self.assertEqual(v.screen_summary, "")

    def test_blocked_verdict(self) -> None:
        v = parse_verdict('{"verdict": "blocked", "evidence": "Colab dialog"}')
        self.assertEqual(v, VerifierVerdict(verdict="blocked", reason="Colab dialog"))
        self.assertFalse(v.ok)

    def test_diverged_verdict(self) -> None:
        v = parse_verdict(
            '{"verdict": "diverged", "evidence": "Already on signed-in dashboard"}'
        )
        self.assertEqual(
            v,
            VerifierVerdict(
                verdict="diverged", reason="Already on signed-in dashboard"
            ),
        )
        self.assertFalse(v.ok)

    def test_unsure_verdict_passes(self) -> None:
        v = parse_verdict('{"verdict": "unsure", "evidence": "shrug"}')
        self.assertEqual(v.verdict, "unsure")
        self.assertEqual(v.reason, "shrug")
        self.assertTrue(v.ok)

    def test_legacy_yes_maps_to_on_track(self) -> None:
        v = parse_verdict('{"verdict": "yes", "evidence": "ok"}')
        self.assertEqual(v.verdict, "on_track")
        self.assertTrue(v.ok)

    def test_legacy_no_maps_to_blocked(self) -> None:
        v = parse_verdict('{"verdict": "no", "evidence": "wrong app"}')
        self.assertEqual(v.verdict, "blocked")
        self.assertFalse(v.ok)

    def test_unknown_verdict_fails_open_to_unsure(self) -> None:
        v = parse_verdict('{"verdict": "maybe", "evidence": "shrug"}')
        self.assertEqual(v.verdict, "unsure")
        self.assertTrue(v.ok)

    def test_unparseable_fails_open(self) -> None:
        v = parse_verdict("not json at all")
        self.assertEqual(v.verdict, "unsure")
        self.assertTrue(v.ok)
        self.assertEqual(v.reason, "verifier_unparseable")

    def test_strips_code_fence(self) -> None:
        v = parse_verdict(
            '```json\n{"verdict":"blocked","evidence":"x"}\n```'
        )
        self.assertEqual(v, VerifierVerdict(verdict="blocked", reason="x"))

    def test_legacy_reason_field_accepted(self) -> None:
        v = parse_verdict('{"verdict": "blocked", "reason": "wrong window"}')
        self.assertEqual(
            v, VerifierVerdict(verdict="blocked", reason="wrong window")
        )

    def test_missing_evidence_gets_default(self) -> None:
        v = parse_verdict('{"verdict": "blocked"}')
        self.assertEqual(v.reason, "no evidence given")


class BuildRequestTests(unittest.TestCase):
    def test_request_uses_system_prompt_and_screen(self) -> None:
        req = build_request("Open Settings", make_screen())
        self.assertEqual(req.system_prompt, VERIFIER_SYSTEM_PROMPT)
        self.assertIn("Open Settings", req.user_text)
        self.assertEqual(len(req.images), 1)
        self.assertEqual(req.response_mime_type, "application/json")
        self.assertNotIn("Overall tutorial goal", req.user_text)

    def test_request_includes_goal_when_provided(self) -> None:
        req = build_request("Open Settings", make_screen(), goal="Create an account")
        self.assertIn("Overall tutorial goal: Create an account", req.user_text)

    def test_request_includes_previous_instruction(self) -> None:
        req = build_request(
            "Start creating a new account",
            make_screen(),
            previous_instruction="Sign out of GitHub",
        )
        self.assertIn(
            "Previous step the user just attempted: Sign out of GitHub",
            req.user_text,
        )

    def test_request_omits_previous_when_absent(self) -> None:
        req = build_request("Open Settings", make_screen())
        self.assertNotIn("Previous step", req.user_text)


class ClassifyScreenTests(unittest.TestCase):
    def test_returns_parsed_verdict(self) -> None:
        llm = _StubLLM(raw='{"verdict":"blocked","reason":"wrong window"}')
        v = classify_screen(llm, "Click Save", make_screen())
        self.assertEqual(
            v, VerifierVerdict(verdict="blocked", reason="wrong window")
        )
        self.assertEqual(len(llm.calls), 1)

    def test_passes_goal_through_to_request(self) -> None:
        llm = _StubLLM(raw='{"verdict":"on_track","evidence":"ok"}')
        classify_screen(llm, "Click Save", make_screen(), goal="Make a github acct")
        self.assertIn("Make a github acct", llm.calls[0].user_text)

    def test_llm_error_fails_open(self) -> None:
        llm = _StubLLM(raises=RuntimeError("network died"))
        v = classify_screen(llm, "Click Save", make_screen())
        self.assertTrue(v.ok)
        self.assertEqual(v.verdict, "unsure")
        self.assertEqual(v.reason, "verifier_error")


if __name__ == "__main__":
    unittest.main()
