from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable, Iterator
from json import dumps, loads
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocketDisconnect

from backend.conversations import ConversationRepository, InMemoryConversationRepository
from backend.images import read_uploaded_images
from backend.llm import MultimodalLLM
from backend.llm_provider import LLMProvider, LLMProviderConfigurationError
from backend.web_ground import web_ground_producer_from_environment
from backend.tutorial_guide import (
    TutorialGuide,
    TutorialPlanRequest,
    TutorialStreamRequest,
)
from backend.tutorial_schema import TutorialPlan, TutorialPlanValidationError
from backend.tutorial_session_events import (
    CreateTutorialSessionResponse,
    ErrorEvent,
    ServerSessionEvent,
    SessionReadyEvent,
    StepStartedEvent,
    TutorialSessionResponse,
    UserCompletionResponseEvent,
    UserConfirmationEvent,
    UserMessageEvent,
    UserScreenEvent,
    UserStepAnnotationEvent,
    client_session_event_adapter,
)
from backend.session_event_log import SessionEventLog
from backend.tutorial_session_store import TutorialSessionError, TutorialSessionStore

logger = logging.getLogger(__name__)


_RESERVED_LOG_RECORD_KEYS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {"message", "asctime"}


class ExtraFieldsFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_LOG_RECORD_KEYS and not key.startswith("_")
        }
        if not extras:
            return base
        formatted_extras = " ".join(f"{key}={value!r}" for key, value in extras.items())
        return f"{base} | {formatted_extras}"


def _step_tools_enabled_from_env() -> bool:
    """Read the STEP_TOOLS_ENABLED A/B flag. Defaults to True (capped-head
    is now the default mode); set the env var to a falsy value to opt
    back into the full-plan emission mode."""
    raw = os.environ.get("STEP_TOOLS_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        ExtraFieldsFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("backend").setLevel(level)


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Context Backend")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/conversations/stream")
    async def stream_conversation(
        conversation_id: Annotated[str, Form()],
        text: Annotated[str, Form()],
        images: Annotated[list[UploadFile] | None, File()] = None,
        conversations: ConversationRepository = Depends(
            get_conversation_repository),
        tutorial_guide: TutorialGuide = Depends(get_tutorial_guide),
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
        request = TutorialStreamRequest(
            conversation_id=conversation.id,
            text=text,
            images=uploaded_images,
        )

        return StreamingResponse(
            stream_as_server_sent_events(
                tutorial_guide.stream_tutorial(request)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/tutorials/plan")
    async def create_tutorial_plan(
        conversation_id: Annotated[str, Form()],
        text: Annotated[str, Form()],
        images: Annotated[list[UploadFile] | None, File()] = None,
        conversations: ConversationRepository = Depends(
            get_conversation_repository),
        tutorial_guide: TutorialGuide = Depends(get_tutorial_guide),
    ) -> TutorialPlan:
        conversation = conversations.get_conversation(conversation_id)
        logger.info(
            "Creating tutorial plan",
            extra={
                "conversation_id": conversation.id,
                "image_count": len(images or []),
            },
        )

        uploaded_images = await read_uploaded_images(images or [])
        request = TutorialPlanRequest(
            conversation_id=conversation.id,
            text=text,
            images=uploaded_images,
        )

        try:
            return tutorial_guide.create_plan(request)
        except TutorialPlanValidationError as error:
            logger.exception(
                "Tutorial plan validation failed",
                extra={"conversation_id": conversation.id},
            )
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/tutorial-sessions")
    def create_tutorial_session(
        sessions: TutorialSessionStore = Depends(get_tutorial_session_store),
    ) -> CreateTutorialSessionResponse:
        return sessions.create_session()

    @app.get("/tutorial-sessions/{session_id}")
    def get_tutorial_session(
        session_id: str,
        sessions: TutorialSessionStore = Depends(get_tutorial_session_store),
    ) -> TutorialSessionResponse:
        try:
            return sessions.get_session(session_id)
        except TutorialSessionError as error:
            raise HTTPException(status_code=404, detail=error.message) from error

    @app.websocket("/tutorial-sessions/{session_id}/socket")
    async def tutorial_session_socket(
        websocket: WebSocket,
        session_id: str,
        sessions: TutorialSessionStore = Depends(get_tutorial_session_store),
    ) -> None:
        await websocket.accept()
        try:
            sessions.get_session(session_id)
        except TutorialSessionError as error:
            await send_server_event(
                websocket,
                ErrorEvent(code=error.code, message=error.message),
            )
            await websocket.close(code=1008)
            return

        send_lock = asyncio.Lock()
        event_log = SessionEventLog(session_id)

        async def emit(event: ServerSessionEvent) -> None:
            event_log.write("server", event)
            async with send_lock:
                await send_server_event(websocket, event)

        try:
            session = sessions.attach(session_id, emit)
        except TutorialSessionError as error:
            await send_server_event(
                websocket,
                ErrorEvent(code=error.code, message=error.message),
            )
            await websocket.close(code=1008)
            return

        await emit(SessionReadyEvent(session_id=session_id))

        try:
            while True:
                try:
                    raw_event = await receive_websocket_json(websocket)
                    event = client_session_event_adapter.validate_python(raw_event)
                except WebSocketDisconnect:
                    raise
                except ValidationError as error:
                    await emit(
                        ErrorEvent(
                            code="invalid_event",
                            message=error.errors()[0]["msg"],
                        )
                    )
                    continue
                except ValueError as error:
                    await emit(ErrorEvent(code="invalid_event", message=str(error)))
                    continue

                event_log.write("client", event)

                try:
                    await dispatch_client_event(session, event)
                except Exception as error:  # noqa: BLE001 — surface unhandled errors to client
                    logger.exception(
                        "Tutorial session event failed",
                        extra={
                            "session_id": session_id,
                            "error_type": type(error).__name__,
                        },
                    )
                    await emit(
                        ErrorEvent(
                            code="session_event_failed",
                            message=f"{type(error).__name__}: {error}",
                        )
                    )
        except WebSocketDisconnect:
            logger.info(
                "Tutorial session socket disconnected",
                extra={"session_id": session_id},
            )
        finally:
            await sessions.detach(session_id)

    return app


async def dispatch_client_event(session, event) -> None:  # type: ignore[no-untyped-def]
    if isinstance(event, UserMessageEvent):
        await session.handle_user_message(event.text, event.uploaded_images)
        return
    if isinstance(event, UserScreenEvent):
        await session.handle_user_screen(event.request_id, event.screen)
        return
    if isinstance(event, StepStartedEvent):
        await session.handle_step_started(event.step_id, event.action_index)
        return
    if isinstance(event, UserConfirmationEvent):
        await session.handle_user_confirmation(
            event.step_id,
            event.action_index,
            event.confirmed,
            event.note,
            screen=event.screen,
        )
        return
    if isinstance(event, UserCompletionResponseEvent):
        await session.handle_user_completion_response(
            event.confirmed,
            event.note,
        )
        return
    if isinstance(event, UserStepAnnotationEvent):
        # Eval annotations don't drive session state — they're persisted by
        # the event log sink and extracted into fixtures offline.
        return


def get_conversation_repository() -> ConversationRepository:
    return InMemoryConversationRepository()


def get_multimodal_llm() -> MultimodalLLM:
    try:
        return LLMProvider.from_environment().create_multimodal_llm()
    except LLMProviderConfigurationError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


def get_fast_multimodal_llm() -> MultimodalLLM:
    try:
        return LLMProvider.from_environment().create_fast_llm()
    except LLMProviderConfigurationError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


def get_verifier_llm() -> MultimodalLLM:
    try:
        return LLMProvider.from_environment().create_verifier_llm()
    except LLMProviderConfigurationError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


def get_tutorial_guide(
    llm: MultimodalLLM = Depends(get_multimodal_llm),
) -> TutorialGuide:
    return TutorialGuide(llm)


def get_tutorial_session_store(
    connection: HTTPConnection,
    llm: MultimodalLLM = Depends(get_multimodal_llm),
    fast_llm: MultimodalLLM = Depends(get_fast_multimodal_llm),
    verifier_llm: MultimodalLLM = Depends(get_verifier_llm),
) -> TutorialSessionStore:
    store = getattr(connection.app.state, "tutorial_session_store", None)
    if store is None:
        store = TutorialSessionStore(
            llm,
            fast_llm=fast_llm,
            verifier_llm=verifier_llm,
            web_ground=web_ground_producer_from_environment(),
            step_tools_enabled=_step_tools_enabled_from_env(),
        )
        connection.app.state.tutorial_session_store = store
    return store


async def receive_websocket_json(websocket: WebSocket) -> object:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))

    text = message.get("text")
    if text is not None:
        return loads(text)

    data = message.get("bytes")
    if data is not None:
        return loads(data.decode("utf-8"))

    raise ValueError("Expected a text or binary JSON WebSocket message.")


async def send_server_event(websocket: WebSocket, event: ServerSessionEvent) -> None:
    await websocket.send_json(event.model_dump(mode="json"))


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
                yield format_sse_event("token", {"text": token})

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
        yield format_sse_event("done", {})
    except Exception:
        logger.exception(
            "LLM stream failed",
            extra={"total_ms": round(elapsed_ms_since(started_at), 2)},
        )
        yield format_sse_event("error", {"message": "stream_failed"})


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
