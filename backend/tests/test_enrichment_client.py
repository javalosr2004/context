from __future__ import annotations

import unittest

import httpx

from backend.enrichment_client import (
    EnrichmentSnippetsProducer,
    parse_enrichment_results,
)
from backend.web_ground import WebGroundSnippet


class _StubClient:
    def __init__(self, response: httpx.Response | Exception):
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json or {}))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _ok(body: dict) -> httpx.Response:
    req = httpx.Request("POST", "https://e/snippets")
    return httpx.Response(200, json=body, request=req)


def _err(status: int, text: str = "boom") -> httpx.Response:
    req = httpx.Request("POST", "https://e/snippets")
    return httpx.Response(status, text=text, request=req)


class ParseEnrichmentResultsTests(unittest.TestCase):
    def test_returns_empty_for_non_dict(self):
        self.assertEqual(parse_enrichment_results("nope"), [])

    def test_returns_empty_when_snippets_missing(self):
        self.assertEqual(parse_enrichment_results({"source_count": 0}), [])

    def test_skips_entries_with_no_url_and_no_content(self):
        body = {"snippets": [{"title": "x"}]}
        self.assertEqual(parse_enrichment_results(body), [])

    def test_parses_well_formed_entries(self):
        body = {
            "snippets": [
                {
                    "title": "Export PNG",
                    "url": "https://example.com/figma",
                    "content": "Open the export panel and click PNG.",
                }
            ]
        }
        out = parse_enrichment_results(body)
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], WebGroundSnippet)
        self.assertEqual(out[0].url, "https://example.com/figma")


class GroundTests(unittest.TestCase):
    def test_blank_query_short_circuits(self):
        stub = _StubClient(_ok({"snippets": []}))
        producer = EnrichmentSnippetsProducer("https://e", client=stub)
        self.assertEqual(producer.ground("  "), [])
        self.assertEqual(stub.calls, [])

    def test_happy_path_maps_to_snippets(self):
        stub = _StubClient(
            _ok({"snippets": [{"title": "T", "url": "https://u", "content": "C"}]})
        )
        producer = EnrichmentSnippetsProducer("https://e/", client=stub, num_sources=3)
        out = producer.ground("how to x", max_results=2)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].content, "C")
        # max_results clamps num_sources downward
        self.assertEqual(stub.calls[0][1]["num_sources"], 2)
        self.assertTrue(stub.calls[0][0].endswith("/snippets"))

    def test_returns_empty_on_http_error(self):
        stub = _StubClient(httpx.ConnectError("nope"))
        producer = EnrichmentSnippetsProducer("https://e", client=stub)
        self.assertEqual(producer.ground("x"), [])

    def test_returns_empty_on_5xx(self):
        stub = _StubClient(_err(503))
        producer = EnrichmentSnippetsProducer("https://e", client=stub)
        self.assertEqual(producer.ground("x"), [])

    def test_returns_empty_on_malformed_json(self):
        req = httpx.Request("POST", "https://e/snippets")
        stub = _StubClient(httpx.Response(200, content=b"not json", request=req))
        producer = EnrichmentSnippetsProducer("https://e", client=stub)
        self.assertEqual(producer.ground("x"), [])

    def test_requires_base_url(self):
        with self.assertRaises(ValueError):
            EnrichmentSnippetsProducer("")


if __name__ == "__main__":
    unittest.main()
