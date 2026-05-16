from __future__ import annotations

import os

from openai import OpenAI
from pydantic import BaseModel, Field


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

    def locate(self, *, screenshot_data_uri: str, target: str) -> VisualLocalizerOutput:
        schema = VisualLocalizerOutput.model_json_schema()
        prompt = (
            "Localize an element on the GUI image according to the provided target "
            "and output a click position.\n"
            f" * You must output a valid JSON following the format: {schema}\n"
            f" Your target is:\n{target}"
        )

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": screenshot_data_uri}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            extra_body={
                "structured_outputs": {"json": schema},
                "chat_template_kwargs": {"enable_thinking": False},
            },
            temperature=0.0,
        )
        content = response.choices[0].message.content
        return VisualLocalizerOutput.model_validate_json(content)
