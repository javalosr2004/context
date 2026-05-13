from __future__ import annotations

import unittest
from collections.abc import Iterator

from backend.llm import LLMRequest
from backend.tutorial_guide import (
    TUTORIAL_CREATOR_SYSTEM_PROMPT,
    TutorialGuide,
    TutorialStreamRequest,
)


class FakeLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def stream_text(self, request: LLMRequest) -> Iterator[str]:
        self.requests.append(request)
        return iter(["first", " second"])


class TutorialGuideTests(unittest.TestCase):
    def test_stream_tutorial_maps_domain_request_to_llm_request(self) -> None:
        llm = FakeLLM()
        guide = TutorialGuide(llm)

        tokens = list(
            guide.stream_tutorial(
                TutorialStreamRequest(
                    conversation_id="conversation-1",
                    text="Show me how to create a repo.",
                    images=[],
                )
            )
        )

        self.assertEqual(tokens, ["first", " second"])
        self.assertEqual(len(llm.requests), 1)
        self.assertEqual(llm.requests[0].system_prompt, TUTORIAL_CREATOR_SYSTEM_PROMPT)
        self.assertEqual(llm.requests[0].user_text, "Show me how to create a repo.")
        self.assertEqual(llm.requests[0].images, [])
        self.assertTrue(llm.requests[0].enable_search_grounding)


if __name__ == "__main__":
    unittest.main()
