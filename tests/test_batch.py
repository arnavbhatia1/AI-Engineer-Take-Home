"""Batch runner tests using the offline MockProvider."""
from __future__ import annotations

import unittest

from src.batch import BatchItem, run_batch
from src.extraction import MockProvider
from src.models import ApplicationData, OverallStatus


class TestBatch(unittest.TestCase):
    def test_batch_preserves_order_and_verdicts(self):
        items = [
            BatchItem(
                "old_tom_bourbon.png",
                ApplicationData(
                    brand_name="OLD TOM DISTILLERY",
                    class_type="Kentucky Straight Bourbon Whiskey",
                    alcohol_content="45% Alc./Vol. (90 Proof)",
                    net_contents="750 mL",
                ),
                b"x",
            ),
            BatchItem(
                "wrong_abv.png",
                ApplicationData(
                    brand_name="Copper Ridge Reserve",
                    class_type="Straight Rye Whiskey",
                    alcohol_content="45% Alc./Vol. (90 Proof)",
                    net_contents="750 mL",
                ),
                b"x",
            ),
        ]
        progress = []
        results = run_batch(items, MockProvider(), max_workers=2,
                            on_progress=lambda d, t: progress.append((d, t)))

        self.assertEqual([r.name for r in results], ["old_tom_bourbon.png", "wrong_abv.png"])
        self.assertEqual(results[0].report.overall, OverallStatus.APPROVED)
        self.assertEqual(results[1].report.overall, OverallStatus.REJECTED)
        self.assertEqual(progress[-1], (2, 2))

    def test_missing_image_is_error(self):
        items = [BatchItem("no_image.png", ApplicationData(brand_name="X"), None)]
        results = run_batch(items, MockProvider())
        self.assertEqual(results[0].report.overall, OverallStatus.ERROR)


if __name__ == "__main__":
    unittest.main()
