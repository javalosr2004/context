from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from backend.holo_client import (
    HoloLocalizer,
    VisualLocalizerOutput,
    build_localization_prompt,
    build_user_content,
)


class FakeChatCompletions:
    def __init__(self) -> None:
        self.request = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.request = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"x1":200,"y1":600,"x2":300,"y2":900}'
                    )
                )
            ]
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.completions = FakeChatCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class HoloClientTests(unittest.TestCase):
    def test_visual_localizer_output_requires_non_empty_bbox(self) -> None:
        output = VisualLocalizerOutput(x1=100, y1=200, x2=300, y2=400)

        self.assertEqual(output.x1, 100)
        self.assertEqual(output.y1, 200)
        self.assertEqual(output.x2, 300)
        self.assertEqual(output.y2, 400)

    def test_visual_localizer_output_rejects_inverted_bbox(self) -> None:
        with self.assertRaises(ValidationError):
            VisualLocalizerOutput(x1=300, y1=200, x2=100, y2=400)

    def test_build_user_content_adds_reference_image_after_screenshot(self) -> None:
        content = build_user_content(
            screenshot_data_uri="data:image/png;base64,screen",
            reference_image_data_uri="data:image/png;base64,reference",
            prompt="Find it.",
        )

        self.assertEqual(
            content,
            [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,screen"},
                },
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,reference"},
                },
                {"type": "text", "text": "Find it."},
            ],
        )

    def test_build_user_content_omits_reference_image_when_absent(self) -> None:
        content = build_user_content(
            screenshot_data_uri="data:image/png;base64,screen",
            reference_image_data_uri=None,
            prompt="Find it.",
        )

        self.assertEqual(
            content,
            [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,screen"},
                },
                {"type": "text", "text": "Find it."},
            ],
        )

    def test_build_localization_prompt_names_reference_image_and_target_bbox_image(self) -> None:
        prompt = build_localization_prompt(
            target="Submit",
            schema={"type": "object"},
            has_reference_image=True,
        )

        self.assertIn(
            "current GUI image (image 1) and reference image (image 2)",
            prompt,
        )
        self.assertIn("tight bounding box around that element on image 1", prompt)
        self.assertIn("0 is the top/left edge", prompt)
        self.assertIn("1000 is the bottom/right edge", prompt)
        self.assertIn("Submit", prompt)

    def test_locate_uses_openai_compatible_chat_completion(self) -> None:
        client = FakeOpenAIClient()
        localizer = HoloLocalizer(client=client, model_name="holo-test")

        bbox = localizer.locate(
            screenshot_data_uri="data:image/png;base64,screen",
            reference_image_data_uri=None,
            target="Submit",
        )

        self.assertEqual(bbox.x1, 200)
        self.assertEqual(bbox.y1, 600)
        self.assertEqual(bbox.x2, 300)
        self.assertEqual(bbox.y2, 900)
        request = client.completions.request
        self.assertEqual(request["model"], "holo-test")
        self.assertEqual(request["temperature"], 0.0)
        self.assertEqual(request["messages"][0]["role"], "user")
        self.assertEqual(
            request["extra_body"]["chat_template_kwargs"],
            {"enable_thinking": False},
        )
        self.assertEqual(
            request["extra_body"]["structured_outputs"]["json"]["title"],
            "VisualLocalizerOutput",
        )


if __name__ == "__main__":
    unittest.main()
