"""In-memory store for tutorial sessions.

Tracks reserved session IDs allocated by the HTTP create endpoint and
the live ``TutorialSession`` instance (if any) bound to an active
WebSocket. A session ID lives in ``_reserved`` from creation until a
WebSocket connects, at which point it moves to ``_live``. When the
WebSocket disconnects the live session is removed.
"""

from __future__ import annotations

from typing import Callable, Literal
from uuid import uuid4

from backend.embeddings_client import EmbeddingsClient, NullEmbeddingsClient
from backend.llm import MultimodalLLM
from backend.llm_recording import LLMCallSink
from backend.tutorial_session import EventSink, TutorialSession
from backend.web_ground import NullWebGroundProducer, WebGroundProducer
from backend.tutorial_session_events import (
    CreateTutorialSessionResponse,
    TutorialSessionResponse,
)


SESSION_NOT_FOUND = "session_not_found"


class TutorialSessionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TutorialSessionStore:
    def __init__(
        self,
        llm: MultimodalLLM,
        session_id_factory: Callable[[], str] | None = None,
        web_ground: WebGroundProducer | None = None,
        fast_llm: MultimodalLLM | None = None,
        verifier_llm: MultimodalLLM | None = None,
        embeddings_client: EmbeddingsClient | None = None,
        step_tools_enabled: bool = True,
        grounding_strategy: Literal["parallel", "planner"] = "parallel",
    ) -> None:
        self._llm = llm
        self._fast_llm = fast_llm or llm
        self._verifier_llm = verifier_llm or self._fast_llm
        self._embeddings_client = embeddings_client or NullEmbeddingsClient()
        self._session_id_factory = session_id_factory or (lambda: str(uuid4()))
        self._web_ground = web_ground or NullWebGroundProducer()
        self._step_tools_enabled = step_tools_enabled
        self._grounding_strategy = grounding_strategy
        self._reserved: set[str] = set()
        self._live: dict[str, TutorialSession] = {}

    def create_session(self) -> CreateTutorialSessionResponse:
        session_id = self._session_id_factory()
        self._reserved.add(session_id)
        return CreateTutorialSessionResponse(session_id=session_id, status="created")

    def get_session(self, session_id: str) -> TutorialSessionResponse:
        live = self._live.get(session_id)
        if live is not None:
            return response_from_live(live)
        if session_id in self._reserved:
            return TutorialSessionResponse(session_id=session_id, status="created")
        raise TutorialSessionError(
            SESSION_NOT_FOUND,
            f"Tutorial session does not exist: {session_id}",
        )

    def attach(
        self,
        session_id: str,
        emit: EventSink,
        llm_call_sink: LLMCallSink | None = None,
    ) -> TutorialSession:
        if session_id not in self._reserved and session_id not in self._live:
            raise TutorialSessionError(
                SESSION_NOT_FOUND,
                f"Tutorial session does not exist: {session_id}",
            )
        self._reserved.discard(session_id)
        session = TutorialSession(
            session_id=session_id,
            llm=self._llm,
            fast_llm=self._fast_llm,
            verifier_llm=self._verifier_llm,
            embeddings_client=self._embeddings_client,
            emit=emit,
            web_ground=self._web_ground,
            step_tools_mode=(
                "capped_head" if self._step_tools_enabled else "full_plan"
            ),
            grounding_strategy=self._grounding_strategy,
            llm_call_sink=llm_call_sink,
        )
        self._live[session_id] = session
        return session

    async def detach(self, session_id: str) -> None:
        session = self._live.pop(session_id, None)
        if session is None:
            return
        await session.shutdown()


def response_from_live(session: TutorialSession) -> TutorialSessionResponse:
    return TutorialSessionResponse(
        session_id=session.session_id,
        status=session.status,
        goal=session.goal,
        current_step_id=session.awaiting_step_id,
        completed_step_ids=list(session.completed_step_ids),
        pending_question=None,
        current_plan=session.current_plan(),
        last_error=None,
    )
