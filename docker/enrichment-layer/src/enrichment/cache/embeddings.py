"""Tiny embeddings wrapper used by L1 + L2 paraphrase matching.

L3, L4, L5 are deterministic and never call this module. It exists in
Phase 1 only so the layered wrappers in ``grounding_cache.py`` can be
written once and Phase 2 just turns the lookup on.
"""
from __future__ import annotations

import logging
import math
from typing import Iterable

from openai import OpenAI

from enrichment.config import settings

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"


def embed(text: str) -> list[float] | None:
    """Embed a single string. Returns None on failure (caller should miss)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.embeddings.create(model=_EMBED_MODEL, input=text)
        return list(resp.data[0].embedding)
    except Exception as exc:
        logger.warning("[cache] embed failed: %s", exc)
        return None


def embed_batch(texts: Iterable[str]) -> list[list[float] | None]:
    items = [t.strip() for t in texts]
    nonempty = [(i, t) for i, t in enumerate(items) if t]
    out: list[list[float] | None] = [None] * len(items)
    if not nonempty:
        return out
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.embeddings.create(
            model=_EMBED_MODEL,
            input=[t for _, t in nonempty],
        )
        for (idx, _), datum in zip(nonempty, resp.data):
            out[idx] = list(datum.embedding)
    except Exception as exc:
        logger.warning("[cache] embed_batch failed: %s", exc)
    return out


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
