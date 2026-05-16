from __future__ import annotations

import logging
import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field, model_validator


DEFAULT_HOLO_BASE_URL = "https://api.hcompany.ai/v1/"
DEFAULT_HOLO_MODEL = "holo3-35b-a3b"

logger = logging.getLogger(__name__)


class VisualLocalizerOutput(BaseModel):
    x1: int = Field(ge=0, le=1000, description="Left edge as integer in [0, 1000]")
    y1: int = Field(ge=0, le=1000, description="Top edge as integer in [0, 1000]")
    x2: int = Field(ge=0, le=1000, description="Right edge as integer in [0, 1000]")
    y2: int = Field(ge=0, le=1000, description="Bottom edge as integer in [0, 1000]")

    @model_validator(mode="after")
    def validate_non_empty_box(self) -> "VisualLocalizerOutput":
        if self.x2 <= self.x1:
            raise ValueError("x2 must be greater than x1")
        if self.y2 <= self.y1:
            raise ValueError("y2 must be greater than y1")
        return self


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
    visual_context = "the GUI image"
    if has_reference_image:
        visual_context = "the current GUI image (image 1) and reference image (image 2)"

    return (
        f"Localize an element on {visual_context} according to the provided target "
        "and output the tight bounding box around that element on image 1.\n"
        "Use the same coordinate scale for every field: 0 is the top/left edge "
        "of image 1, and 1000 is the bottom/right edge of image 1.\n"
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
