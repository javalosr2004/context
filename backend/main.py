from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from backend.conversations import ConversationRepository, InMemoryConversationRepository
from backend.gemini_client import GeminiClient, GeminiStreamRequest
from backend.images import UploadedImage, read_uploaded_images

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="Context Backend")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/conversations/stream")
    async def stream_conversation(
        conversation_id: Annotated[str, Form()],
        text: Annotated[str, Form()],
        images: Annotated[list[UploadFile] | None, File()] = None,
        conversations: ConversationRepository = Depends(get_conversation_repository),
        gemini: GeminiClient = Depends(get_gemini_client),
    ) -> StreamingResponse:
        conversation = conversations.get_conversation(conversation_id)
        logger.info(
            "Starting multimodal stream",
            extra={
                "conversation_id": conversation.id,
                "image_count": len(images or []),
            },
        )

        uploaded_images = await read_uploaded_images(images or [])
        request = GeminiStreamRequest(
            conversation_id=conversation.id,
            text=text,
            images=uploaded_images,
        )

        return StreamingResponse(
            stream_as_server_sent_events(gemini.stream_response(request)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def get_conversation_repository() -> ConversationRepository:
    return InMemoryConversationRepository()


def get_gemini_client() -> GeminiClient:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is required to stream Gemini responses.",
        )

    model = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    return GeminiClient(api_key=api_key, model=model)


def stream_as_server_sent_events(tokens: Iterator[str]) -> Iterator[str]:
    try:
        for token in tokens:
            if token:
                yield f"data: {token}\n\n"
        yield "event: done\ndata: {}\n\n"
    except Exception:
        logger.exception("Gemini stream failed")
        yield 'event: error\ndata: {"message":"stream_failed"}\n\n'


app = create_app()
