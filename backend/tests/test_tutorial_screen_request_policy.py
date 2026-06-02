from __future__ import annotations

import unittest

from backend.tutorial_guide import TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT
from backend.tutorial_session import HistoryEntry, render_history


class TutorialScreenRequestPolicyTests(unittest.TestCase):
    def test_tool_prompt_exposes_fresh_screen_tool(self) -> None:
        self.assertIn("tutorial_request_screen", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)
        self.assertIn("fresh screenshot", TUTORIAL_TOOL_STREAM_SYSTEM_PROMPT)

    def test_render_history_makes_missing_screen_state_explicit(self) -> None:
        text = render_history(
            goal="Help me use this app.",
            history=[HistoryEntry(role="user", content="Help me use this app.")],
            has_latest_screen=False,
        )

        self.assertIn("Loop state:", text)
        self.assertIn("latest_screen: not attached yet", text)

    def test_render_history_makes_attached_screen_state_explicit(self) -> None:
        text = render_history(
            goal="Help me use this app.",
            history=[HistoryEntry(role="user", content="Help me use this app.")],
            has_latest_screen=True,
        )

        self.assertIn("Loop state:", text)
        self.assertIn("latest_screen: attached to this request", text)


if __name__ == "__main__":
    unittest.main()
