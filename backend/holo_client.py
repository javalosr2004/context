from __future__ import annotations

import logging
import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field


DEFAULT_HOLO_BASE_URL = "https://api.hcompany.ai/v1/"
DEFAULT_HOLO_MODEL = "holo3-35b-a3b"

logger = logging.getLogger(__name__)


class VisualLocalizerOutput(BaseModel):
    x: int = Field(ge=0, le=1000, description="X coordinate as integer in [0, 1000]")
    y: int = Field(ge=0, le=1000, description="Y coordinate as integer in [0, 1000]")
    found: bool = Field(
        default=True,
        description="True if a matching UI element was found on the screen.",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model confidence that the returned point is correct.",
    )


class HoloLocalizer:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.model_name = model_name or os.environ.get("HOLO_MODEL", DEFAULT_HOLO_MODEL)
        self.client = client or OpenAI(
            base_url=base_url or os.environ.get("HAI_BASE_URL", DEFAULT_HOLO_BASE_URL),
            api_key=api_key or os.environ.get("HAI_API_KEY"),
        )

    def locate(
        self,
        *,
        screenshot_data_uri: str,
        target: str,
        reference_image_data_uri: str | None = None,
    ) -> VisualLocalizerOutput:
        schema = VisualLocalizerOutput.model_json_schema()
        prompt = build_localization_prompt(
            target=target,
            schema=schema,
            has_reference_image=reference_image_data_uri is not None,
        )
        content = build_user_content(
            screenshot_data_uri=screenshot_data_uri,
            prompt=prompt,
            reference_image_data_uri=reference_image_data_uri,
        )

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": content}],
            extra_body={
                "structured_outputs": {"json": schema},
                "chat_template_kwargs": {"enable_thinking": False},
            },
            temperature=0.0,
        )
        raw_content = response.choices[0].message.content
        if os.environ.get("LOG_HOLO_RAW_OUTPUT", "0") == "1":
            logger.info(
                "Holo raw output",
                extra={"model": self.model_name, "content": raw_content},
            )
        return VisualLocalizerOutput.model_validate_json(raw_content)


def build_localization_prompt(
    *,
    target: str,
    schema: dict[str, Any],
    has_reference_image: bool,
) -> str:
    reference_guidance = ""
    visual_context = "the GUI image"
    if has_reference_image:
        visual_context = "the current GUI image (image 1) and reference image (image 2)"
        reference_guidance = (
            " * Image 2 is the reference crop for the target. Treat its visual "
            "appearance as the primary matching signal, then use the text target "
            "only to disambiguate similar elements.\n"
            " * Return a point on image 1 only if you find the same UI element "
            "or a visually equivalent instance of it. Do not choose a merely "
            "related nearby element.\n"
        )

    return (
        f"Localize an element on {visual_context} according to the provided target "
        "and output a click position on image 1.\n"
        f"{reference_guidance}"
        " * If you find a matching element, set found=true and report your "
        "confidence (0.0-1.0) that the (x, y) is correct.\n"
        " * Use confidence >= 0.9 only when the exact target is visible and "
        "unambiguous. If there are multiple plausible matches, partial matches, "
        "or a reference image that does not clearly appear in image 1, confidence "
        "must be below 0.7.\n"
        " * If no element on image 1 matches the target, set found=false with "
        "confidence below 0.5; x and y must still be within [0, 1000] but will "
        "be treated as untrusted placeholders.\n"
        f" * You must output a valid JSON following the format: {schema}\n"
        f" Your target is:\n{target}"
    )


def build_user_content(
    *,
    screenshot_data_uri: str,
    prompt: str,
    reference_image_data_uri: str | None,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": screenshot_data_uri}}
    ]
    if reference_image_data_uri is not None:
        content.append(
            {"type": "image_url", "image_url": {"url": reference_image_data_uri}}
        )
    content.append({"type": "text", "text": prompt})
    return content
