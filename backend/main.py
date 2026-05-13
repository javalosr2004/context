from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterator
from json import dumps
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
    started_at = time.perf_counter()
    first_token_ms: float | None = None
    token_count = 0

    try:
        for token in tokens:
            if token:
                token_count += 1
                if first_token_ms is None:
                    first_token_ms = elapsed_ms_since(started_at)
                    logger.info(
                        "Received first stream token",
                        extra={"first_token_ms": round(first_token_ms, 2)},
                    )
                yield f"data: {token}\n\n"

        total_ms = elapsed_ms_since(started_at)
        metrics = build_stream_metrics(
            first_token_ms=first_token_ms,
            total_ms=total_ms,
            token_count=token_count,
        )
        logger.info(
            "Completed stream",
            extra=metrics,
        )
        yield format_sse_event("metrics", metrics)
        yield "event: done\ndata: {}\n\n"
    except Exception:
        logger.exception(
            "Gemini stream failed",
            extra={"total_ms": round(elapsed_ms_since(started_at), 2)},
        )
        yield 'event: error\ndata: {"message":"stream_failed"}\n\n'


def elapsed_ms_since(started_at: float, now: Callable[[], float] = time.perf_counter) -> float:
    return (now() - started_at) * 1000


def build_stream_metrics(
    first_token_ms: float | None,
    total_ms: float,
    token_count: int,
) -> dict[str, float | int | None]:
    return {
        "first_token_ms": round(first_token_ms, 2)
        if first_token_ms is not None
        else None,
        "total_ms": round(total_ms, 2),
        "token_count": token_count,
    }


def format_sse_event(event: str, data: object) -> str:
    return f"event: {event}\ndata: {dumps(data, separators=(',', ':'))}\n\n"


app = create_app()
