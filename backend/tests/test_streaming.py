from __future__ import annotations

import unittest
from json import loads

from backend.main import build_stream_metrics, elapsed_ms_since, stream_as_server_sent_events


class StreamingTests(unittest.TestCase):
    def test_stream_tokens_are_encoded_as_sse(self) -> None:
        events = list(stream_as_server_sent_events(iter(["hello", " world"])))

        self.assertEqual(events[0], 'event: token\ndata: {"text":"hello"}\n\n')
        self.assertEqual(events[1], 'event: token\ndata: {"text":" world"}\n\n')
        self.assertTrue(events[2].startswith("event: metrics\ndata: "))
        metrics = loads(events[2].split("data: ", 1)[1])
        self.assertEqual(metrics["token_count"], 2)
        self.assertIn("first_token_ms", metrics)
        self.assertIn("total_ms", metrics)
        self.assertEqual(events[3], "event: done\ndata: {}\n\n")

    def test_stream_tokens_are_json_encoded(self) -> None:
        events = list(stream_as_server_sent_events(iter(['hello\n"world"'])))

        self.assertEqual(
            events[0],
            'event: token\ndata: {"text":"hello\\n\\"world\\""}\n\n',
        )

    def test_elapsed_ms_since_uses_perf_counter_delta(self) -> None:
        self.assertEqual(elapsed_ms_since(1.0, now=lambda: 1.25), 250.0)

    def test_build_stream_metrics_rounds_latency_values(self) -> None:
        self.assertEqual(
            build_stream_metrics(
                first_token_ms=123.456,
                total_ms=987.654,
                token_count=3,
            ),
            {"first_token_ms": 123.46, "total_ms": 987.65, "token_count": 3},
        )


if __name__ == "__main__":
    unittest.main()
