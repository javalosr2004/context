"""Web grounding via the enrichment-layer /snippets endpoint.

Drop-in replacement for ``TavilyWebGroundProducer``. Trades a small extra
latency budget (per-page summarization on cleaned text) for grounding
that actually reflects page bodies rather than meta descriptions.

When a screenshot is available, callers should use
:meth:`EnrichmentSnippetsProducer.ground_multimodal`. The enrichment
layer then runs a multimodal query planner that identifies the visible
environment, decomposes the request into varying sub-goals, and emits a
multi-query search whose results are aggregated into a single snippet
set.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from backend.images import UploadedImage
from backend.web_ground import DEFAULT_MAX_RESULTS, WebGroundSnippet


logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 8.0
MULTIMODAL_TIMEOUT_SECONDS = 25.0


@dataclass(frozen=True)
class MultimodalGroundResult:
    snippets: list[WebGroundSnippet]
    queries_used: list[str]
    application: str | None
    environment: str | None
    goal_facets: list[str]


class EnrichmentSnippetsProducer:
    def __init__(
        self,
        base_url: str,
        *,
        num_sources: int = 5,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        multimodal_timeout_seconds: float = MULTIMODAL_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("EnrichmentSnippetsProducer requires a non-empty base_url")
        self._endpoint = base_url.rstrip("/") + "/snippets"
        self._num_sources = num_sources
        self._timeout = timeout_seconds
        self._multimodal_timeout = multimodal_timeout_seconds
        self._client = client

    def ground(
        self, query: str, *, max_results: int = DEFAULT_MAX_RESULTS
    ) -> list[WebGroundSnippet]:
        query = query.strip()
        if not query:
            return []

        data = {
            "query": query,
            "num_sources": str(
                min(self._num_sources, max_results) if max_results else self._num_sources
            ),
        }

        logger.info(
            "[enrichment] ground start",
            extra={"mode": "text", "query_chars": len(query)},
        )
        started_at = time.perf_counter()
        try:
            response = self._post_form(data=data, files=None, timeout=self._timeout)
        except httpx.HTTPError as error:
            logger.warning(
                "Enrichment grounding request failed",
                extra={
                    "error": str(error),
                    "query_chars": len(query),
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            return []

        body = self._parse_response_body(response)
        if body is None:
            logger.info(
                "[enrichment] ground end",
                extra={
                    "mode": "text",
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "status_code": response.status_code,
                    "snippet_count": 0,
                },
            )
            return []
        snippets = parse_enrichment_results(body)
        logger.info(
            "[enrichment] ground end",
            extra={
                "mode": "text",
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "status_code": response.status_code,
                "snippet_count": len(snippets),
            },
        )
        return snippets

    def ground_multimodal(
        self,
        request_text: str,
        image: UploadedImage,
        *,
        max_results: int = DEFAULT_MAX_RESULTS,
    ) -> MultimodalGroundResult:
        request_text = request_text.strip()
        empty = MultimodalGroundResult(
            snippets=[], queries_used=[], application=None,
            environment=None, goal_facets=[],
        )
        if not request_text:
            return empty

        data = {
            "query": request_text,
            "num_sources": str(
                min(self._num_sources, max_results) if max_results else self._num_sources
            ),
        }
        files = {"image": (image.filename or "screen.png", image.data, image.mime_type)}

        logger.info(
            "[enrichment] ground start",
            extra={
                "mode": "multimodal",
                "request_chars": len(request_text),
                "image_bytes": len(image.data),
            },
        )
        started_at = time.perf_counter()
        try:
            response = self._post_form(
                data=data, files=files, timeout=self._multimodal_timeout
            )
        except httpx.HTTPError as error:
            logger.warning(
                "Enrichment multimodal grounding request failed",
                extra={
                    "error": str(error),
                    "request_chars": len(request_text),
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            return empty

        body = self._parse_response_body(response)
        if body is None:
            logger.info(
                "[enrichment] ground end",
                extra={
                    "mode": "multimodal",
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "status_code": response.status_code,
                    "snippet_count": 0,
                },
            )
            return empty
        snippets = parse_enrichment_results(body)
        logger.info(
            "[enrichment] ground end",
            extra={
                "mode": "multimodal",
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "status_code": response.status_code,
                "snippet_count": len(snippets),
            },
        )
        return MultimodalGroundResult(
            snippets=snippets,
            queries_used=_as_str_list(body.get("queries_used")),
            application=_as_optional_str(body.get("application")),
            environment=_as_optional_str(body.get("environment")),
            goal_facets=_as_str_list(body.get("goal_facets")),
        )

    def _post_form(
        self,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]] | None,
        timeout: float,
    ) -> httpx.Response:
        if self._client is not None:
            return self._client.post(
                self._endpoint, data=data, files=files, timeout=timeout
            )
        return httpx.post(
            self._endpoint, data=data, files=files, timeout=timeout
        )

    def _parse_response_body(self, response: httpx.Response) -> dict | None:
        if response.status_code >= 400:
            logger.warning(
                "Enrichment grounding non-2xx",
                extra={"status_code": response.status_code, "body": response.text[:300]},
            )
            return None
        try:
            body = response.json()
        except ValueError:
            logger.warning("Enrichment grounding returned non-JSON body")
            return None
        if not isinstance(body, dict):
            return None
        return body


def parse_enrichment_results(body: object) -> list[WebGroundSnippet]:
    if not isinstance(body, dict):
        return []
    raw = body.get("snippets")
    if not isinstance(raw, list):
        return []
    snippets: list[WebGroundSnippet] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = _as_str(item.get("title"))
        url = _as_str(item.get("url"))
        content = _as_str(item.get("content"))
        if not url and not content:
            continue
        snippets.append(WebGroundSnippet(title=title, url=url, content=content))
    return snippets


def _as_str(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _as_optional_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]
