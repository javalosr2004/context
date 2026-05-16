import pytest
from pydantic import ValidationError

from holo_client import (
    VisualLocalizerOutput,
    build_localization_prompt,
    build_user_content,
)


def test_visual_localizer_output_requires_non_empty_bbox():
    output = VisualLocalizerOutput(x1=100, y1=200, x2=300, y2=400)

    assert output.x1 == 100
    assert output.y1 == 200
    assert output.x2 == 300
    assert output.y2 == 400


def test_visual_localizer_output_rejects_inverted_bbox():
    with pytest.raises(ValidationError):
        VisualLocalizerOutput(x1=300, y1=200, x2=100, y2=400)


def test_visual_localizer_output_rejects_zero_height_bbox():
    with pytest.raises(ValidationError):
        VisualLocalizerOutput(x1=100, y1=200, x2=300, y2=200)


def test_build_user_content_adds_reference_image_after_screenshot():
    content = build_user_content(
        screenshot_data_uri="data:image/png;base64,screen",
        reference_image_data_uri="data:image/png;base64,reference",
        prompt="Find it.",
    )

    assert content == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,screen"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,reference"}},
        {"type": "text", "text": "Find it."},
    ]


def test_build_user_content_omits_reference_image_when_absent():
    content = build_user_content(
        screenshot_data_uri="data:image/png;base64,screen",
        reference_image_data_uri=None,
        prompt="Find it.",
    )

    assert content == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,screen"}},
        {"type": "text", "text": "Find it."},
    ]


def test_build_localization_prompt_names_reference_image_and_target_bbox_image():
    prompt = build_localization_prompt(
        target="Submit",
        schema={"type": "object"},
        has_reference_image=True,
    )

    assert "current GUI image (image 1) and reference image (image 2)" in prompt
    assert "tight bounding box around that element on image 1" in prompt
    assert "0 is the top/left edge" in prompt
    assert "1000 is the bottom/right edge" in prompt
    assert "y2 is the bottom edge" in prompt
    assert "y2 must be greater than y1" in prompt
    assert "Never set y2 equal to y1" in prompt
    assert "Submit" in prompt
