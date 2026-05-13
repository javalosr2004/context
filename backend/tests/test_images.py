from __future__ import annotations

import unittest

from backend.images import SUPPORTED_IMAGE_MIME_TYPES


class ImageValidationTests(unittest.TestCase):
    def test_expected_gemini_image_types_are_supported(self) -> None:
        self.assertIn("image/png", SUPPORTED_IMAGE_MIME_TYPES)
        self.assertIn("image/jpeg", SUPPORTED_IMAGE_MIME_TYPES)
        self.assertIn("image/webp", SUPPORTED_IMAGE_MIME_TYPES)
        self.assertIn("image/heic", SUPPORTED_IMAGE_MIME_TYPES)
        self.assertIn("image/heif", SUPPORTED_IMAGE_MIME_TYPES)


if __name__ == "__main__":
    unittest.main()
