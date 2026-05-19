from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile
from PIL import Image


logger = logging.getLogger(__name__)


SUPPORTED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
}


@dataclass(frozen=True)
class UploadedImage:
    data: bytes
    mime_type: str
    filename: str


async def read_uploaded_images(files: list[UploadFile]) -> list[UploadedImage]:
    return await asyncio.gather(*(read_uploaded_image(file) for file in files))


async def read_uploaded_image(file: UploadFile) -> UploadedImage:
    mime_type = file.content_type or ""
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type: {mime_type or 'unknown'}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded images cannot be empty.")

    return UploadedImage(
        data=data,
        mime_type=mime_type,
        filename=file.filename or "image",
    )


def downscale_for_verifier(
    image: UploadedImage,
    max_edge: int = 1024,
    jpeg_quality: int = 70,
) -> UploadedImage:
    """Return a smaller JPEG variant suitable for the verifier LLM.

    Retina captures routinely exceed 200 KB and saturate vision-token budgets
    without improving a coarse "does the screen match this instruction"
    judgment. Downscale the long edge to `max_edge` and re-encode as JPEG.
    Falls back to the original on any decoder error so verification stays
    fail-open.
    """
    try:
        with Image.open(io.BytesIO(image.data)) as pil:
            pil.load()
            if pil.mode not in ("RGB", "L"):
                pil = pil.convert("RGB")
            width, height = pil.size
            long_edge = max(width, height)
            if long_edge > max_edge:
                scale = max_edge / long_edge
                pil = pil.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.LANCZOS,
                )
            buffer = io.BytesIO()
            pil.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
    except Exception:
        logger.exception("[images] downscale_for_verifier failed; using original")
        return image
    return UploadedImage(
        data=buffer.getvalue(),
        mime_type="image/jpeg",
        filename=f"{image.filename.rsplit('.', 1)[0]}.verifier.jpg",
    )
