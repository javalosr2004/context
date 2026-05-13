from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile


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
