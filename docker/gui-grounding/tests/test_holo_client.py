from holo_client import build_localization_prompt, build_user_content


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


def test_build_localization_prompt_names_reference_image_and_click_target_image():
    prompt = build_localization_prompt(
        target="Submit",
        schema={"type": "object"},
        has_reference_image=True,
    )

    assert "current GUI image (image 1) and reference image (image 2)" in prompt
    assert "reference crop for the target" in prompt
    assert "primary matching signal" in prompt
    assert "confidence >= 0.9 only when the exact target is visible" in prompt
    assert "click position on image 1" in prompt
    assert "Submit" in prompt
