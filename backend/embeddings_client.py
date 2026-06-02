"""Text embeddings for in-session semantic comparisons.

Two consumers:

  * Stable ``logical_id`` across replans. When the planner mints a fresh
    ``step_id`` for what is logically the same step we tried last replan,
    embedding similarity on a canonical step fingerprint lets us reuse
    the prior ``logical_id`` so loop counters survive identity churn.

  * Pre-verifier screen shortcut. The planner can emit
    ``expected_screen_summary`` per step; after the verifier reports its
    ``screen_summary`` we cosine-compare and, if they match, we can
    promote the verdict without depending on the model's classification
    head.

Fail-open everywhere: any error returns no embedding (and callers treat
that as "skip the comparison"), so a flaky embeddings endpoint never
locks the user out of the tutorial.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Protocol

from openai import OpenAI

from backend.tutorial_schema import TutorialStep


logger = logging.getLogger(__name__)


DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
LOGICAL_ID_SIMILARITY_THRESHOLD = 0.85
EXPECTED_SCREEN_SIMILARITY_THRESHOLD = 0.85


class EmbeddingsClient(Protocol):
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input string. May return ``[]`` on failure;
        callers must tolerate a length-zero result."""
        ...


class NullEmbeddingsClient:
    """Drop-in client that disables embedding-based features.

    Returns an empty list, which every caller treats as "no signal."
    Used when no embeddings provider is configured or in tests that
    don't exercise the semantic paths.
    """

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return []


class OpenAIEmbeddingsClient:
    def __init__(self, api_key: str, model: str = DEFAULT_EMBEDDING_MODEL) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        started_at = time.perf_counter()
        try:
            response = self._client.embeddings.create(model=self._model, input=texts)
        except Exception:
            logger.exception(
                "[embeddings] call failed",
                extra={"model": self._model, "count": len(texts)},
            )
            return []
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "[embeddings] batch",
            extra={
                "model": self._model,
                "count": len(texts),
                "elapsed_ms": elapsed_ms,
            },
        )
        return [list(item.embedding) for item in response.data]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def step_fingerprint(step: TutorialStep) -> str:
    """Canonical text fed to the embedder for ``logical_id`` resolution.

    Includes the instruction and, for each action, its kind and any
    target label/description. Two steps with the same fingerprint refer
    to the same logical UI gesture even if the planner reworded them
    slightly across replans.
    """
    parts: list[str] = [step.instruction.strip()]
    for action in step.actions:
        parts.append(action.type)
        target = action.target
        if target is not None:
            if target.label:
                parts.append(target.label.strip())
            elif target.description:
                parts.append(target.description.strip())
    return " | ".join(part for part in parts if part)
