import json
import tempfile
import unittest
from pathlib import Path

from cropper import (
    BBox,
    annotate_frame,
    bbox_from_ax_attributes,
    clamp_bbox_to_image,
    parse_events_jsonl,
    resolve_tutorial_source,
)


class BBoxParsingTests(unittest.TestCase):
    def test_prefers_current_snapshot_bbox(self) -> None:
        bbox = bbox_from_ax_attributes(
            {
                "current": {
                    "boundingBox": {"x": 10.2, "y": 20.6, "width": 30, "height": 40}
                },
                "parents": [
                    {"boundingBox": {"x": 1, "y": 2, "width": 3, "height": 4}}
                ],
            }
        )

        self.assertEqual(bbox, BBox(x=10, y=21, width=30, height=40))

    def test_supports_legacy_flat_bbox(self) -> None:
        bbox = bbox_from_ax_attributes(
            {
                "bbox_x": "10",
                "bbox_y": "20",
                "bbox_width": "30",
                "bbox_height": "40",
            }
        )

        self.assertEqual(bbox, BBox(x=10, y=20, width=30, height=40))

    def test_rejects_empty_bbox(self) -> None:
        bbox = bbox_from_ax_attributes(
            {
                "current": {
                    "boundingBox": {"x": 10, "y": 20, "width": 0, "height": 40}
                }
            }
        )

        self.assertIsNone(bbox)


class EventParsingTests(unittest.TestCase):
    def test_parse_events_keeps_event_type_for_pdf_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            events_path = Path(temp_dir) / "events.jsonl"
            rows = [
                {"eventType": "recording_start", "timeUtcMs": 1000, "x": 0, "y": 0},
                {
                    "eventType": "mousedown_left",
                    "timeUtcMs": 1250,
                    "axAttributes": {
                        "current": {
                            "boundingBox": {
                                "x": 10,
                                "y": 20,
                                "width": 30,
                                "height": 40,
                            }
                        }
                    },
                },
            ]
            events_path.write_text(
                "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
            )

            base_ms, sections = parse_events_jsonl(events_path)

        self.assertEqual(base_ms, 1000)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].event_type, "mousedown_left")
        self.assertEqual(sections[0].bbox, BBox(x=10, y=20, width=30, height=40))


class TutorialSourceTests(unittest.TestCase):
    def test_resolves_extracted_recording_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events_path = root / "events.jsonl"
            video_path = root / "recording.webm"
            events_path.write_text("", encoding="utf-8")
            video_path.write_bytes(b"not a real video")

            source = resolve_tutorial_source(root)

        self.assertEqual(Path(source.events_path).name, "events.jsonl")
        self.assertEqual(Path(source.video_path or "").name, "recording.webm")


class BBoxClampTests(unittest.TestCase):
    def test_clamps_bbox_to_image_bounds(self) -> None:
        bbox = clamp_bbox_to_image(BBox(x=-5, y=10, width=20, height=30), 100, 100)

        self.assertEqual(bbox, BBox(x=0, y=10, width=15, height=30))

    def test_rejects_non_overlapping_bbox(self) -> None:
        bbox = clamp_bbox_to_image(BBox(x=110, y=10, width=20, height=30), 100, 100)

        self.assertIsNone(bbox)


class AnnotationTests(unittest.TestCase):
    def test_annotation_dims_background_and_preserves_target(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "source.png"
            output_path = root / "annotated.png"
            Image.new("RGB", (80, 80), (200, 200, 200)).save(source_path)

            annotate_frame(source_path, BBox(x=30, y=30, width=20, height=20), output_path)

            with Image.open(output_path).convert("RGB") as annotated:
                background_pixel = annotated.getpixel((10, 10))
                target_pixel = annotated.getpixel((40, 40))

        self.assertLess(background_pixel[0], 120)
        self.assertEqual(target_pixel, (200, 200, 200))


if __name__ == "__main__":
    unittest.main()
