"""Integrity test for the bundled sample set.

Mirrors the app's "Run the bundled samples" batch end to end, without the
Streamlit runtime: reads samples/applications.csv, loads each committed PNG,
runs the concurrent batch with the offline provider, and asserts the expected
verdict mix. Catches a missing image, a CSV/sample mismatch, or a rule
regression in one shot. This is the CI smoke test.
"""
from __future__ import annotations

import csv
import unittest
from pathlib import Path

from src.batch import BatchItem, run_batch
from src.extraction import MOCK_EXTRACTIONS, MockProvider
from src.models import ApplicationData, OverallStatus

SAMPLES_DIR = Path(__file__).parent.parent / "samples"

EXPECTED_VERDICTS = {
    "old_tom_bourbon.png": OverallStatus.APPROVED,
    "stones_throw_gin.png": OverallStatus.APPROVED,
    "title_case_warning.png": OverallStatus.REJECTED,
    "wrong_abv.png": OverallStatus.REJECTED,
    "missing_warning.png": OverallStatus.REJECTED,
    "altered_warning.png": OverallStatus.REJECTED,
}


class TestSampleSet(unittest.TestCase):
    def _rows(self) -> list[dict]:
        with open(SAMPLES_DIR / "applications.csv", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_csv_images_and_mocks_are_consistent(self):
        rows = self._rows()
        csv_files = {r["image_file"] for r in rows}
        self.assertEqual(csv_files, set(EXPECTED_VERDICTS), "CSV rows out of sync")
        self.assertEqual(set(MOCK_EXTRACTIONS), set(EXPECTED_VERDICTS), "mock readings out of sync")
        for fn in EXPECTED_VERDICTS:
            self.assertTrue((SAMPLES_DIR / fn).is_file(), f"missing committed image: {fn}")

    def test_full_batch_produces_expected_verdicts(self):
        items = [
            BatchItem(
                name=row["image_file"],
                application=ApplicationData.from_dict(row),
                image_bytes=(SAMPLES_DIR / row["image_file"]).read_bytes(),
            )
            for row in self._rows()
        ]
        results = run_batch(items, MockProvider())

        verdicts = {r.name: r.report.overall for r in results}
        self.assertEqual(verdicts, EXPECTED_VERDICTS)

        counts = [r.report.overall for r in results]
        self.assertEqual(counts.count(OverallStatus.APPROVED), 2)
        self.assertEqual(counts.count(OverallStatus.REJECTED), 4)


if __name__ == "__main__":
    unittest.main()
