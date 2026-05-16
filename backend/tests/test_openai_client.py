from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.llm import LLMTextDelta, LLMToolCallEvent
from backend.openai_client import (
    build_response_params,
    build_text_format,
    stream_event_from_response_event,
    tool_call_from_response_event,
)
from backend.tutorial_schema import tutorial_plan_response_schema


class OpenAIClientSchemaTests(unittest.TestCase):
    def test_json_schema_format_adds_openai_strict_object_constraints(self) -> None:
        text_format = build_text_format(
            "application/json",
            tutorial_plan_response_schema(),
        )
        schema = text_format["schema"]

        self.assertEqual(text_format["type"], "json_schema")
        assert_openai_strict_objects(schema)

    def test_json_schema_format_does_not_mutate_input_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "summary": {"type": "string"},
            },
        }

        text_format = build_text_format("application/json", schema)

        self.assertNotIn("additionalProperties", schema)
        self.assertNotIn("required", schema)
        self.assertEqual(
            text_format["schema"],
            {
                "type": "object",
                "properties": {
                    "goal": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["goal", "summary"],
                "additionalProperties": False,
            },
        )

    def test_response_params_can_include_tutorial_tools_and_search(self) -> None:
        params = build_response_params(
            reasoning_effort="medium",
            verbosity="medium",
            enable_search_grounding=True,
            response_mime_type=None,
            response_schema=None,
            tools=[{"type": "function", "name": "tutorial_click"}],
        )

        self.assertEqual(
            params["tools"],
            [
                {"type": "function", "name": "tutorial_click"},
                {"type": "web_search"},
            ],
        )

    def test_tool_call_from_response_output_item_done_event(self) -> None:
        event = SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="function_call",
                name="tutorial_click",
                arguments='{"human_text":"Click New.","agent_description":"New button."}',
            ),
        )

        call = tool_call_from_response_event(event)

        self.assertIsNotNone(call)
        self.assertEqual(call.name, "tutorial_click")
        self.assertIn("Click New", call.arguments)

    def test_stream_event_from_response_text_delta(self) -> None:
        event = SimpleNamespace(type="response.output_text.delta", delta="Thinking...")

        stream_event = stream_event_from_response_event(event)

        self.assertIsInstance(stream_event, LLMTextDelta)
        self.assertEqual(stream_event.text, "Thinking...")

    def test_stream_event_from_response_native_tool_call(self) -> None:
        event = SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="function_call",
                name="tutorial_confirm",
                arguments='{"human_text":"Confirm the screen looks correct."}',
            ),
        )

        stream_event = stream_event_from_response_event(event)

        self.assertIsInstance(stream_event, LLMToolCallEvent)
        self.assertEqual(stream_event.tool_call.name, "tutorial_confirm")


def assert_openai_strict_objects(value: object) -> None:
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            property_names = list(properties.keys())
            assert value.get("required") == property_names
            assert value.get("additionalProperties") is False

        if value.get("type") == "object":
            assert value.get("additionalProperties") is False

        for child in value.values():
            assert_openai_strict_objects(child)

    if isinstance(value, list):
        for item in value:
            assert_openai_strict_objects(item)


if __name__ == "__main__":
    unittest.main()
