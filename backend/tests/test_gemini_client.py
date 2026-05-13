from __future__ import annotations

import unittest

from backend.gemini_client import (
    build_generate_content_config,
)
from backend.tutorial_guide import TUTORIAL_CREATOR_SYSTEM_PROMPT


class GeminiClientConfigTests(unittest.TestCase):
    def test_config_includes_tutorial_creator_system_prompt(self) -> None:
        config = build_generate_content_config(
            system_prompt=TUTORIAL_CREATOR_SYSTEM_PROMPT,
            enable_search_grounding=True,
        )

        self.assertEqual(config.system_instruction, TUTORIAL_CREATOR_SYSTEM_PROMPT)
        self.assertIn("click, hover, scroll", config.system_instruction)

    def test_config_enables_google_search_grounding(self) -> None:
        config = build_generate_content_config(
            system_prompt=TUTORIAL_CREATOR_SYSTEM_PROMPT,
            enable_search_grounding=True,
        )

        self.assertEqual(len(config.tools), 1)
        self.assertIsNotNone(config.tools[0].google_search)

    def test_config_can_disable_google_search_grounding(self) -> None:
        config = build_generate_content_config(
            system_prompt="Ground this screen without search.",
            enable_search_grounding=False,
        )

        self.assertEqual(config.tools, [])


if __name__ == "__main__":
    unittest.main()
