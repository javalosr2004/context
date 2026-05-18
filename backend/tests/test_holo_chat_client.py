from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.holo_chat_client import (
    HoloChatClient,
    build_extra_body,
    build_messages,
    build_user_content,
)
from backend.images import UploadedImage
from backend.llm import LLMRequest


def make_request(
    *,
    user_text: str = "hi",
    images: list[UploadedImage] | None = None,
    response_mime_type: str | None = None,
    response_schema: dict | None = None,
    temperature: float | None = None,
) -> LLMRequest:
    return LLMRequest(
        system_prompt="sys",
        user_text=user_text,
        images=images or [],
        response_mime_type=response_mime_type,
        response_schema=response_schema,
        temperature=temperature,
    )


class BuildMessagesTests(unittest.TestCase):
    def test_system_and_user_messages(self) -> None:
        messages = build_messages(make_request(user_text="howdy"))
        self.assertEqual(messages[0], {"role": "system", "content": "sys"})
        self.assertEqual(messages[1]["role"], "user")
        # Single text content when there are no images.
        self.assertEqual(messages[1]["content"], [{"type": "text", "text": "howdy"}])

    def test_image_content_uses_data_uri(self) -> None:
        image = UploadedImage(data=b"\x89PNG", mime_type="image/png", filename="x.png")
        content = build_user_content("describe", [image])
        self.assertEqual(content[0]["type"], "image_url")
        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(content[1], {"type": "text", "text": "describe"})


class BuildExtraBodyTests(unittest.TestCase):
    def test_disables_thinking_by_default(self) -> None:
        extra = build_extra_body(response_mime_type=None, response_schema=None)
        self.assertEqual(extra["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("structured_outputs", extra)
        self.assertNotIn("response_format", extra)

    def test_passes_json_schema_when_provided(self) -> None:
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        extra = build_extra_body(
            response_mime_type="application/json",
            response_schema=schema,
        )
        self.assertEqual(extra["structured_outputs"], {"json": schema})

    def test_falls_back_to_json_object_when_schema_missing(self) -> None:
        extra = build_extra_body(
            response_mime_type="application/json",
            response_schema=None,
        )
        self.assertEqual(extra["response_format"], {"type": "json_object"})


class CompleteTextTests(unittest.TestCase):
    def test_calls_chat_completions_with_messages_and_extra_body(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))]
        )
        client = HoloChatClient(
            api_key="key",
            model="holo3-35b-a3b",
            base_url="https://h/",
            client=fake_client,
        )

        result = client.complete_text(make_request(user_text="ping"))

        self.assertEqual(result, "hello")
        fake_client.chat.completions.create.assert_called_once()
        kwargs = fake_client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "holo3-35b-a3b")
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertEqual(kwargs["messages"][0]["role"], "system")
        self.assertEqual(
            kwargs["extra_body"]["chat_template_kwargs"], {"enable_thinking": False}
        )

    def test_returns_empty_string_when_content_missing(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        )
        client = HoloChatClient(
            api_key="k", model="m", base_url="https://h/", client=fake_client
        )
        self.assertEqual(client.complete_text(make_request()), "")


if __name__ == "__main__":
    unittest.main()
