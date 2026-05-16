from __future__ import annotations

import base64
import io

from PIL import Image

from grounding import ImageSize


def read_image(data: bytes) -> tuple[ImageSize, str]:
    if not data:
        raise ValueError("Image upload was empty.")

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise ValueError(f"Could not decode image: {exc}") from exc

    mime_type = Image.MIME.get(image.format, "image/png")
    encoded = base64.b64encode(data).decode("ascii")
    return ImageSize(width=image.width, height=image.height), f"data:{mime_type};base64,{encoded}"
