from __future__ import annotations

import unittest

import httpx

from backend.enrichment_client import (
    EnrichmentSnippetsProducer,
    parse_enrichment_results,
)
from backend.images import UploadedImage
from backend.web_ground import WebGroundSnippet


class _StubClient:
    def __init__(self, response: httpx.Response | Exception):
        self._response = response
        self.calls: list[dict] = []

    def post(self, url, data=None, files=None, timeout=None):
        self.calls.append(
            {"url": url, "data": dict(data or {}), "files": files, "timeout": timeout}
        )
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _ok(body: dict) -> httpx.Response:
    req = httpx.Request("POST", "https://e/snippets")
    return httpx.Response(200, json=body, request=req)


def _err(status: int, text: str = "boom") -> httpx.Response:
    req = httpx.Request("POST", "https://e/snippets")
    return httpx.Response(status, text=text, request=req)


def _image() -> UploadedImage:
    return UploadedImage(data=b"\x89PNG\r\nfake", mime_type="image/png", filename="s.png")


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
        self.assertEqual(stub.calls[0]["data"]["num_sources"], "2")
        self.assertTrue(stub.calls[0]["url"].endswith("/snippets"))
        # Plain ground() does not attach a file.
        self.assertIsNone(stub.calls[0]["files"])

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


class GroundMultimodalTests(unittest.TestCase):
    def test_blank_request_short_circuits(self):
        stub = _StubClient(_ok({"snippets": []}))
        producer = EnrichmentSnippetsProducer("https://e", client=stub)
        result = producer.ground_multimodal("  ", _image())
        self.assertEqual(result.snippets, [])
        self.assertEqual(result.queries_used, [])
        self.assertEqual(stub.calls, [])

    def test_uploads_image_and_returns_plan_metadata(self):
        body = {
            "snippets": [
                {"title": "Help", "url": "https://x", "content": "steps"},
            ],
            "queries_used": [
                "Figma help center export PNG",
                "how to batch export Figma frames",
            ],
            "application": "Figma",
            "environment": "macOS Sequoia, Figma desktop",
            "goal_facets": ["export selected frame as PNG", "batch export frames"],
        }
        stub = _StubClient(_ok(body))
        producer = EnrichmentSnippetsProducer("https://e/", client=stub, num_sources=4)
        result = producer.ground_multimodal("export this", _image())

        self.assertEqual(len(result.snippets), 1)
        self.assertEqual(result.application, "Figma")
        self.assertEqual(result.environment, "macOS Sequoia, Figma desktop")
        self.assertEqual(
            result.queries_used,
            [
                "Figma help center export PNG",
                "how to batch export Figma frames",
            ],
        )
        self.assertEqual(
            result.goal_facets,
            ["export selected frame as PNG", "batch export frames"],
        )
        call = stub.calls[0]
        self.assertTrue(call["url"].endswith("/snippets"))
        self.assertEqual(call["data"]["query"], "export this")
        self.assertIsNotNone(call["files"])
        self.assertEqual(call["files"]["image"][0], "s.png")
        self.assertEqual(call["files"]["image"][2], "image/png")

    def test_returns_empty_on_http_error(self):
        stub = _StubClient(httpx.ConnectError("nope"))
        producer = EnrichmentSnippetsProducer("https://e", client=stub)
        result = producer.ground_multimodal("x", _image())
        self.assertEqual(result.snippets, [])
        self.assertEqual(result.queries_used, [])

    def test_returns_empty_on_5xx(self):
        stub = _StubClient(_err(503))
        producer = EnrichmentSnippetsProducer("https://e", client=stub)
        result = producer.ground_multimodal("x", _image())
        self.assertEqual(result.snippets, [])


if __name__ == "__main__":
    unittest.main()
