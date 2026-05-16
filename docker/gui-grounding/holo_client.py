from __future__ import annotations

import os

from openai import OpenAI
from pydantic import BaseModel, Field

from logging_config import configure_logging, log_event


class VisualLocalizerOutput(BaseModel):
    x: int = Field(ge=0, le=1000, description="X coordinate as integer in [0, 1000]")
    y: int = Field(ge=0, le=1000, description="Y coordinate as integer in [0, 1000]")


class HoloLocalizer:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
    ) -> None:
        self.model_name = model_name or os.environ.get("HOLO_MODEL", "holo3-35b-a3b")
        self.client = OpenAI(
            base_url=base_url or os.environ.get("HAI_BASE_URL", "https://api.hcompany.ai/v1/"),
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
            messages=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
            extra_body={
                "structured_outputs": {"json": schema},
                "chat_template_kwargs": {"enable_thinking": False},
            },
            temperature=0.0,
        )
        content = response.choices[0].message.content
        if os.environ.get("LOG_HOLO_RAW_OUTPUT", "0") == "1":
            log_event(
                configure_logging(),
                "holo_raw_output",
                model=self.model_name,
                content=content,
        )
        return VisualLocalizerOutput.model_validate_json(content)


def build_localization_prompt(
    *,
    target: str,
    schema: dict,
    has_reference_image: bool,
) -> str:
    visual_context = "the GUI image"
    if has_reference_image:
        visual_context = "the current GUI image (image 1) and reference image (image 2)"

    return (
        f"Localize an element on {visual_context} according to the provided target "
        "and output a click position on image 1.\n"
        f" * You must output a valid JSON following the format: {schema}\n"
        f" Your target is:\n{target}"
    )


def build_user_content(
    *,
    screenshot_data_uri: str,
    prompt: str,
    reference_image_data_uri: str | None,
) -> list[dict]:
    content = [{"type": "image_url", "image_url": {"url": screenshot_data_uri}}]
    if reference_image_data_uri is not None:
        content.append({"type": "image_url", "image_url": {"url": reference_image_data_uri}})
    content.append({"type": "text", "text": prompt})
    return content
