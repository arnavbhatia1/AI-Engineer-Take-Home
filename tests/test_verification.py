"""Unit tests for the verification engine.

These are pure-logic tests - no network, no API key. They pin down the rules
that matter most for compliance: the exact Government-Warning check and the
fuzzy-but-safe field matching.

Run:  python -m pytest -q     (or)     python -m unittest -q
"""
from __future__ import annotations

import unittest

from src.config import CANONICAL_GOVERNMENT_WARNING
from src.models import ApplicationData, LabelExtraction, OverallStatus, Status
from src.verification import (
    aggregate,
    check_government_warning,
    match_abv,
    match_net_contents,
    match_text,
    verify_label,
)
from src.extraction import MockProvider


def _extraction(**overrides) -> LabelExtraction:
    base = dict(
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        producer_name_address="Bottled by Old Tom Distillery, Bardstown, KY",
        government_warning_text=CANONICAL_GOVERNMENT_WARNING,
        government_warning_heading_uppercase=True,
    )
    base.update(overrides)
    return LabelExtraction(**base)


class TestTextMatching(unittest.TestCase):
    def test_exact_match_passes(self):
        r = match_text("Brand", "OLD TOM DISTILLERY", "OLD TOM DISTILLERY")
        self.assertEqual(r.status, Status.PASS)

    def test_case_and_punctuation_insensitive(self):
        # Dave's example: STONE'S THROW vs Stone's Throw is obviously the same.
        r = match_text("Brand", "Stone's Throw", "STONE'S THROW")
        self.assertEqual(r.status, Status.PASS)

    def test_close_typo_flagged_for_review(self):
        r = match_text("Brand", "Copper Ridge Reserve", "Coppr Ridge Reserve")
        self.assertEqual(r.status, Status.REVIEW)

    def test_different_brand_fails(self):
        r = match_text("Brand", "Old Tom Distillery", "Silver Creek Vodka")
        self.assertEqual(r.status, Status.FAIL)

    def test_missing_field_fails(self):
        r = match_text("Brand", "Old Tom Distillery", None)
        self.assertEqual(r.status, Status.FAIL)


class TestABV(unittest.TestCase):
    def test_matching_abv_passes(self):
        r = match_abv("ABV", "45% Alc./Vol. (90 Proof)", "45% Alc./Vol. (90 Proof)")
        self.assertEqual(r.status, Status.PASS)

    def test_percent_only_vs_full_string(self):
        r = match_abv("ABV", "45%", "45% Alc./Vol. (90 Proof)")
        self.assertEqual(r.status, Status.PASS)

    def test_mismatch_fails(self):
        r = match_abv("ABV", "45% Alc./Vol. (90 Proof)", "40% Alc./Vol. (80 Proof)")
        self.assertEqual(r.status, Status.FAIL)

    def test_inconsistent_proof_flagged(self):
        # 45% but labelled 80 proof (should be 90) -> internal inconsistency.
        r = match_abv("ABV", "45%", "45% Alc./Vol. (80 Proof)")
        self.assertEqual(r.status, Status.REVIEW)


class TestNetContents(unittest.TestCase):
    def test_unit_normalisation_passes(self):
        r = match_net_contents("Net", "750 mL", "750ML")
        self.assertEqual(r.status, Status.PASS)

    def test_quantity_mismatch_fails(self):
        r = match_net_contents("Net", "750 mL", "1000 mL")
        self.assertEqual(r.status, Status.FAIL)


class TestGovernmentWarning(unittest.TestCase):
    def test_correct_warning_passes(self):
        r = check_government_warning(_extraction())
        self.assertEqual(r.status, Status.PASS)

    def test_missing_warning_fails(self):
        r = check_government_warning(
            _extraction(government_warning_text=None, government_warning_heading_uppercase=None)
        )
        self.assertEqual(r.status, Status.FAIL)
        self.assertIn("mandatory", r.detail.lower())

    def test_title_case_heading_fails(self):
        # Jenny's real catch: "Government Warning" in title case must be rejected.
        title = CANONICAL_GOVERNMENT_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
        r = check_government_warning(
            _extraction(government_warning_text=title, government_warning_heading_uppercase=False)
        )
        self.assertEqual(r.status, Status.FAIL)
        self.assertIn("capital", r.detail.lower())

    def test_altered_wording_fails(self):
        altered = CANONICAL_GOVERNMENT_WARNING.replace(
            "may cause health problems", "is bad for you"
        )
        r = check_government_warning(_extraction(government_warning_text=altered))
        self.assertEqual(r.status, Status.FAIL)
        self.assertIn("wording", r.detail.lower())


class TestAggregate(unittest.TestCase):
    def test_all_pass_is_approved(self):
        results = [type("R", (), {"status": Status.PASS})() for _ in range(3)]
        self.assertEqual(aggregate(results), OverallStatus.APPROVED)

    def test_any_fail_is_rejected(self):
        results = [
            type("R", (), {"status": Status.PASS})(),
            type("R", (), {"status": Status.FAIL})(),
        ]
        self.assertEqual(aggregate(results), OverallStatus.REJECTED)

    def test_review_without_fail_needs_review(self):
        results = [
            type("R", (), {"status": Status.PASS})(),
            type("R", (), {"status": Status.REVIEW})(),
        ]
        self.assertEqual(aggregate(results), OverallStatus.NEEDS_REVIEW)


class TestEndToEndWithMock(unittest.TestCase):
    """Full verify_label() path using the offline MockProvider + sample data."""

    def setUp(self):
        self.provider = MockProvider()

    def _verify(self, hint: str, app: ApplicationData):
        return verify_label(app, b"ignored-in-mock", "image/png", self.provider, hint=hint)

    def test_clean_label_approved(self):
        app = ApplicationData(
            brand_name="OLD TOM DISTILLERY",
            class_type="Kentucky Straight Bourbon Whiskey",
            alcohol_content="45% Alc./Vol. (90 Proof)",
            net_contents="750 mL",
        )
        report = self._verify("old_tom_bourbon.png", app)
        self.assertEqual(report.overall, OverallStatus.APPROVED)

    def test_fuzzy_brand_approved(self):
        app = ApplicationData(
            brand_name="Stone's Throw",
            class_type="London Dry Gin",
            alcohol_content="40% Alc./Vol. (80 Proof)",
            net_contents="750 mL",
        )
        report = self._verify("stones_throw_gin.png", app)
        self.assertEqual(report.overall, OverallStatus.APPROVED)

    def test_title_case_warning_rejected(self):
        app = ApplicationData(
            brand_name="Silver Creek Vodka",
            class_type="Vodka",
            alcohol_content="40% Alc./Vol. (80 Proof)",
            net_contents="750 mL",
        )
        report = self._verify("title_case_warning.png", app)
        self.assertEqual(report.overall, OverallStatus.REJECTED)

    def test_wrong_abv_rejected(self):
        app = ApplicationData(
            brand_name="Copper Ridge Reserve",
            class_type="Straight Rye Whiskey",
            alcohol_content="45% Alc./Vol. (90 Proof)",
            net_contents="750 mL",
        )
        report = self._verify("wrong_abv.png", app)
        self.assertEqual(report.overall, OverallStatus.REJECTED)

    def test_missing_warning_rejected(self):
        app = ApplicationData(
            brand_name="Harbor Light Spiced Rum",
            class_type="Spiced Rum",
            alcohol_content="35% Alc./Vol. (70 Proof)",
            net_contents="750 mL",
        )
        report = self._verify("missing_warning.png", app)
        self.assertEqual(report.overall, OverallStatus.REJECTED)

    def test_altered_warning_rejected_with_wording_detail(self):
        # Reworded warning (heading still in caps): only the wording check trips.
        app = ApplicationData(
            brand_name="Golden Gate Brandy",
            class_type="California Brandy",
            alcohol_content="40% Alc./Vol. (80 Proof)",
            net_contents="750 mL",
        )
        report = self._verify("altered_warning.png", app)
        self.assertEqual(report.overall, OverallStatus.REJECTED)
        gw = next(r for r in report.field_results if r.field == "Government Warning")
        self.assertEqual(gw.status, Status.FAIL)
        self.assertIn("wording", gw.detail.lower())
        self.assertNotIn("capital", gw.detail.lower())  # caps were fine here


if __name__ == "__main__":
    unittest.main()
