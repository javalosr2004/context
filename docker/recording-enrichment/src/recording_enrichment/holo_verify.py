"""Optional verification: re-localize a description and compare to recorded cursor."""
from __future__ import annotations

import logging
import math
import os
from typing import Optional, Protocol

import httpx


logger = logging.getLogger(__name__)


class GroundingClient(Protocol):
    def locate(self, frame_jpeg: bytes, target_phrase: str) -> Optional[tuple[int, int]]: ...


class HoloGroundingClient:
    """Wraps the existing gui-grounding service. Stateless."""

    def __init__(self, base_url: Optional[str] = None, timeout_s: float = 10.0):
        self._base_url = base_url or os.environ.get("GROUNDING_URL", "http://gui-grounding:8080")
        self._timeout_s = timeout_s

    def locate(self, frame_jpeg: bytes, target_phrase: str) -> Optional[tuple[int, int]]:
        files = {"image": ("frame.jpg", frame_jpeg, "image/jpeg")}
        data = {"target_phrase": target_phrase}
        try:
            r = httpx.post(
                f"{self._base_url}/predict",
                files=files,
                data=data,
                timeout=self._timeout_s,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            logger.warning("grounding_call_failed err=%s", e)
            return None
        point = payload.get("point_pixel")
        if not point or len(point) != 2:
            return None
        return int(point[0]), int(point[1])


class VerifySettings:
    def __init__(self) -> None:
        self.enabled = os.environ.get("ENRICH_VERIFY_ENABLED", "0") == "1"
        self.max_distance_px = float(os.environ.get("ENRICH_VERIFY_MAX_DISTANCE_PX", "30"))


def euclidean(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def verify_against_cursor(
    *,
    client: GroundingClient,
    frame_jpeg: bytes,
    target_phrase: str,
    cursor: tuple[int, int],
    max_distance_px: float,
) -> tuple[Optional[bool], Optional[float]]:
    """Return (verified, distance_px). verified=None means probe failed."""
    point = client.locate(frame_jpeg, target_phrase)
    if point is None:
        return None, None
    d = euclidean(point, cursor)
    return d <= max_distance_px, d
