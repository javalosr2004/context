from __future__ import annotations

import unittest

from backend.openai_client import build_text_format
from backend.tutorial_schema import tutorial_planner_reply_response_schema


class OpenAIClientSchemaTests(unittest.TestCase):
    def test_json_schema_format_adds_openai_strict_object_constraints(self) -> None:
        text_format = build_text_format(
            "application/json",
            tutorial_planner_reply_response_schema(),
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
