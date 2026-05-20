from __future__ import annotations

import json

from recording_enrichment.holo_describe import (
    DESCRIPTION_JSON_SCHEMA,
    Description,
    PROMPT_VERSION,
    build_messages,
    build_system_prompt,
)


def test_system_prompt_embeds_goal():
    p = build_system_prompt("Reply to Sarah about Q3 hiring")
    assert "Reply to Sarah about Q3 hiring" in p
    assert "Do NOT include the goal in" in p


def test_messages_carry_both_crops_as_data_uris():
    msgs = build_messages("g", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1")
    assert msgs[0]["role"] == "system"
    parts = msgs[1]["content"]
    image_parts = [p for p in parts if p["type"] == "image_url"]
    assert len(image_parts) == 2
    assert image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # Order matters: target first, context second.
    assert "Target crop" in parts[0]["text"]
    assert "Context crop" in parts[2]["text"]


def test_prompt_version_is_pinned():
    assert PROMPT_VERSION == "describe-v2"


def test_description_round_trips_json():
    raw = {"target_phrase": "the 'Reply' button", "kind": "button", "visible_text": "Reply"}
    d = Description.model_validate(raw)
    assert d.target_phrase == raw["target_phrase"]
    assert d.kind == "button"
    assert json.loads(d.model_dump_json())["kind"] == "button"


def test_schema_constrains_kind():
    enum = DESCRIPTION_JSON_SCHEMA["properties"]["kind"]["enum"]
    assert "button" in enum
    assert "rocketship" not in enum
