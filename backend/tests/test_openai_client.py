from __future__ import annotations

import unittest
from collections.abc import Sequence
from types import SimpleNamespace

from backend.llm import (
    LLMRequest,
    LLMTextDelta,
    LLMToolCallArgsDelta,
    LLMToolCallEvent,
    LLMWebSearchCompleted,
    LLMWebSearchStarted,
)
from backend.openai_client import (
    OpenAIClient,
    build_response_params,
    build_text_format,
    stream_event_from_response_event,
    tool_call_from_response_event,
    web_search_event_from_response_event,
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


    def test_web_search_added_event_maps_to_started(self) -> None:
        event = SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(
                type="web_search_call",
                action=SimpleNamespace(query="set up Stripe webhook"),
            ),
        )

        stream_event = stream_event_from_response_event(event)

        self.assertIsInstance(stream_event, LLMWebSearchStarted)
        self.assertEqual(stream_event.query, "set up Stripe webhook")

    def test_web_search_done_event_maps_to_completed(self) -> None:
        event = SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(
                type="web_search_call",
                action=SimpleNamespace(query="set up Stripe webhook"),
            ),
        )

        stream_event = stream_event_from_response_event(event)

        self.assertIsInstance(stream_event, LLMWebSearchCompleted)
        self.assertEqual(stream_event.query, "set up Stripe webhook")
        # elapsed_ms is stamped by the stream loop, not the per-event helper.
        self.assertEqual(stream_event.elapsed_ms, 0.0)

    def test_web_search_helper_ignores_unrelated_output_items(self) -> None:
        function_call = SimpleNamespace(
            type="response.output_item.done",
            item=SimpleNamespace(type="function_call", name="x", arguments="{}"),
        )
        self.assertIsNone(web_search_event_from_response_event(function_call))

    def test_web_search_helper_returns_none_when_query_absent(self) -> None:
        event = SimpleNamespace(
            type="response.output_item.added",
            item=SimpleNamespace(type="web_search_call", action=None),
        )

        stream_event = web_search_event_from_response_event(event)

        self.assertIsInstance(stream_event, LLMWebSearchStarted)
        self.assertEqual(stream_event.query, "")


class _FakeResponses:
    def __init__(self, events: Sequence[object]) -> None:
        self._events = events

    def create(self, **kwargs: object) -> object:
        return iter(self._events)


class _FakeClient:
    def __init__(self, events: Sequence[object]) -> None:
        self.responses = _FakeResponses(events)


class OpenAIClientArgsDeltaStreamingTests(unittest.TestCase):
    def _client_with_events(self, events: Sequence[object]) -> OpenAIClient:
        client = OpenAIClient(api_key="test", model="gpt-test")
        client._client = _FakeClient(events)
        return client

    def _request(self) -> LLMRequest:
        return LLMRequest(system_prompt="sys", user_text="hi", images=[])

    def test_streams_update_plan_args_and_emits_final_tool_call(self) -> None:
        full_args = '{"plan_reasoning":"x","plan":[{"human_text":"Go."}]}'
        events = [
            SimpleNamespace(
                type="response.output_item.added",
                item=SimpleNamespace(
                    type="function_call", id="fc_1", name="tutorial_update_plan"
                ),
            ),
            SimpleNamespace(
                type="response.function_call_arguments.delta",
                item_id="fc_1",
                delta='{"plan_reasoning":"x","plan":[',
            ),
            SimpleNamespace(
                type="response.function_call_arguments.delta",
                item_id="fc_1",
                delta='{"human_text":"Go."}]}',
            ),
            SimpleNamespace(
                type="response.output_item.done",
                item=SimpleNamespace(
                    type="function_call",
                    name="tutorial_update_plan",
                    arguments=full_args,
                ),
            ),
        ]
        out = list(self._client_with_events(events).stream_tutorial_events(self._request()))

        arg_deltas = [e for e in out if isinstance(e, LLMToolCallArgsDelta)]
        tool_calls = [e for e in out if isinstance(e, LLMToolCallEvent)]
        self.assertEqual(len(arg_deltas), 2)
        self.assertTrue(all(d.name == "tutorial_update_plan" for d in arg_deltas))
        self.assertTrue(all(d.call_id == "fc_1" for d in arg_deltas))
        self.assertEqual("".join(d.delta for d in arg_deltas), full_args)
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0].tool_call.name, "tutorial_update_plan")

    def test_ignores_args_deltas_for_other_tools(self) -> None:
        events = [
            SimpleNamespace(
                type="response.output_item.added",
                item=SimpleNamespace(
                    type="function_call", id="fc_2", name="tutorial_request_screen"
                ),
            ),
            SimpleNamespace(
                type="response.function_call_arguments.delta",
                item_id="fc_2",
                delta='{"reason":"need a fresh screen"}',
            ),
            SimpleNamespace(
                type="response.output_item.done",
                item=SimpleNamespace(
                    type="function_call",
                    name="tutorial_request_screen",
                    arguments='{"reason":"need a fresh screen"}',
                ),
            ),
        ]
        out = list(self._client_with_events(events).stream_tutorial_events(self._request()))

        self.assertFalse(any(isinstance(e, LLMToolCallArgsDelta) for e in out))
        self.assertEqual(
            sum(isinstance(e, LLMToolCallEvent) for e in out), 1
        )

    def test_unknown_item_id_delta_is_dropped(self) -> None:
        # An args delta whose item_id was never announced (no name known)
        # must not be attributed to update_plan.
        events = [
            SimpleNamespace(
                type="response.function_call_arguments.delta",
                item_id="ghost",
                delta='{"plan":[',
            ),
        ]
        out = list(self._client_with_events(events).stream_tutorial_events(self._request()))
        self.assertEqual(out, [])


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
