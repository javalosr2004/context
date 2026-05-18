from __future__ import annotations

import unittest

from backend.web_ground import (
    NullWebGroundProducer,
    WebGroundSnippet,
    format_snippets_for_prompt,
    parse_tavily_results,
    web_ground_producer_from_environment,
)


class ParseTavilyResultsTests(unittest.TestCase):
    def test_returns_empty_for_non_dict(self):
        self.assertEqual(parse_tavily_results("not a dict"), [])

    def test_returns_empty_when_results_missing(self):
        self.assertEqual(parse_tavily_results({"query": "x"}), [])

    def test_skips_entries_with_no_url_and_no_content(self):
        body = {"results": [{"title": "Only title"}]}
        self.assertEqual(parse_tavily_results(body), [])

    def test_parses_well_formed_entries(self):
        body = {
            "results": [
                {
                    "title": "How to ship a macOS app",
                    "url": "https://example.com/ship",
                    "content": "Sign with Developer ID, then notarize.",
                },
                {"url": "https://example.com/x", "content": ""},
            ]
        }
        snippets = parse_tavily_results(body)
        self.assertEqual(len(snippets), 2)
        self.assertEqual(snippets[0].title, "How to ship a macOS app")
        self.assertEqual(snippets[0].url, "https://example.com/ship")
        self.assertIn("notarize", snippets[0].content)


class FormatSnippetsTests(unittest.TestCase):
    def test_empty_snippets_render_empty_string(self):
        self.assertEqual(format_snippets_for_prompt([]), "")

    def test_renders_numbered_block(self):
        snippets = [
            WebGroundSnippet(title="T", url="https://u", content="C"),
        ]
        rendered = format_snippets_for_prompt(snippets)
        self.assertIn("[1] T", rendered)
        self.assertIn("https://u", rendered)
        self.assertIn("C", rendered)


class FactoryTests(unittest.TestCase):
    def test_returns_null_when_no_api_key(self):
        producer = web_ground_producer_from_environment({})
        self.assertIsInstance(producer, NullWebGroundProducer)

    def test_returns_null_when_api_key_blank(self):
        producer = web_ground_producer_from_environment({"TAVILY_API_KEY": "  "})
        self.assertIsInstance(producer, NullWebGroundProducer)

    def test_returns_tavily_when_key_present(self):
        producer = web_ground_producer_from_environment({"TAVILY_API_KEY": "secret"})
        self.assertNotIsInstance(producer, NullWebGroundProducer)


if __name__ == "__main__":
    unittest.main()
