from __future__ import annotations

import unittest

from backend.main import stream_as_server_sent_events


class StreamingTests(unittest.TestCase):
    def test_stream_tokens_are_encoded_as_sse(self) -> None:
        events = list(stream_as_server_sent_events(iter(["hello", " world"])))

        self.assertEqual(events[0], "data: hello\n\n")
        self.assertEqual(events[1], "data:  world\n\n")
        self.assertEqual(events[2], "event: done\ndata: {}\n\n")


if __name__ == "__main__":
    unittest.main()
