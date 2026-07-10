"""Tests for the image-preprocessing step (speed + API size-limit safety)."""
from __future__ import annotations

import unittest
from io import BytesIO

from PIL import Image

from src.imaging import MAX_EDGE, prepare_image


def _png_bytes(w: int, h: int) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), (200, 180, 140)).save(buf, "PNG")
    return buf.getvalue()


class TestPrepareImage(unittest.TestCase):
    def test_small_image_untouched(self):
        raw = _png_bytes(600, 800)
        out, mt = prepare_image(raw, "image/png")
        self.assertEqual(out, raw)
        self.assertEqual(mt, "image/png")

    def test_oversized_image_downscaled(self):
        raw = _png_bytes(4000, 3000)  # typical phone photo dimensions
        out, mt = prepare_image(raw, "image/png")
        self.assertEqual(mt, "image/jpeg")
        img = Image.open(BytesIO(out))
        self.assertLessEqual(max(img.size), MAX_EDGE)
        self.assertLess(len(out), len(raw))

    def test_aspect_ratio_preserved(self):
        raw = _png_bytes(4000, 2000)
        out, _ = prepare_image(raw, "image/png")
        img = Image.open(BytesIO(out))
        self.assertAlmostEqual(img.size[0] / img.size[1], 2.0, places=1)

    def test_non_image_bytes_passthrough(self):
        raw = b"definitely not an image"
        out, mt = prepare_image(raw, "image/png")
        self.assertEqual(out, raw)
        self.assertEqual(mt, "image/png")


if __name__ == "__main__":
    unittest.main()
