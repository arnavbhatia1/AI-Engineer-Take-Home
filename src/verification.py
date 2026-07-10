"""The verification engine.

Design principle: the vision model *reads* the label; this module *decides*.
Keeping the judgement in deterministic, testable code (rather than asking the
model "does this pass?") gives us:
  - an exact, auditable Government-Warning check (Jenny's requirement),
  - fuzzy-but-explainable matching for brand/type (Dave's requirement),
  - unit-testable rules with no network dependency.
"""
from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from typing import Optional

from .config import (
    ABV_TOLERANCE,
    CANONICAL_GOVERNMENT_WARNING,
    TEXT_REVIEW_THRESHOLD,
    WARNING_WORDING_THRESHOLD,
)
from .models import (
    ApplicationData,
    FieldResult,
    LabelExtraction,
    OverallStatus,
    Status,
    VerificationReport,
)

# --- normalisation helpers -------------------------------------------------


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _norm_text(s: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace.

    Makes "STONE'S THROW" and "Stone's Throw" compare equal.
    """
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return _collapse_ws(s)


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# --- field matchers --------------------------------------------------------


def match_text(field: str, expected: str, found: Optional[str]) -> FieldResult:
    """Fuzzy text match for brand name / class-type / producer / country."""
    if not found or not found.strip():
        return FieldResult(field, expected, found, Status.FAIL, "Not found on the label.")

    e, f = _norm_text(expected), _norm_text(found)
    if e == f:
        return FieldResult(
            field, expected, found, Status.PASS,
            "Matches the application (ignoring case and punctuation).",
        )

    r = _ratio(e, f)
    if r >= TEXT_REVIEW_THRESHOLD:
        return FieldResult(
            field, expected, found, Status.REVIEW,
            f"Close but not identical ({r:.0%} similar) — suggest a human check.",
        )
    return FieldResult(
        field, expected, found, Status.FAIL,
        "Does not match the application.",
    )


def _parse_percent(s: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    return float(m.group(1)) if m else None


def _parse_proof(s: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*proof", s, re.I)
    return float(m.group(1)) if m else None


def _parse_abv(s: str) -> Optional[float]:
    """Pull an ABV value from free text. Prefers a percentage, then derives
    from proof, then falls back to a bare number."""
    pct = _parse_percent(s)
    if pct is not None:
        return pct
    proof = _parse_proof(s)
    if proof is not None:
        return proof / 2.0
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def match_abv(field: str, expected: str, found: Optional[str]) -> FieldResult:
    if not found or not found.strip():
        return FieldResult(field, expected, found, Status.FAIL, "Not found on the label.")

    e, f = _parse_abv(expected), _parse_abv(found)
    if e is None or f is None:
        return FieldResult(
            field, expected, found, Status.REVIEW,
            "Could not read a numeric alcohol value — suggest a human check.",
        )

    if abs(e - f) > ABV_TOLERANCE:
        return FieldResult(
            field, expected, found, Status.FAIL,
            f"Label shows {f:g}% but the application states {e:g}%.",
        )

    # Values agree — sanity-check proof vs ABV on the label itself (proof = 2×ABV).
    pct = _parse_percent(found)
    proof = _parse_proof(found)
    if pct is not None and proof is not None and abs(proof - 2 * pct) > 0.2:
        return FieldResult(
            field, expected, found, Status.REVIEW,
            f"ABV matches, but the label's proof ({proof:g}) is inconsistent with "
            f"its stated {pct:g}% (proof should be ~{2 * pct:g}).",
        )
    return FieldResult(field, expected, found, Status.PASS, f"{f:g}% matches the application.")


_QTY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ml|milliliters?|millilitres?|l|liters?|litres?|fl\.?\s*oz|oz)",
    re.I,
)
_UNIT_CANON = {
    "ml": "ml", "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "oz": "oz", "floz": "oz", "fl oz": "oz", "fl. oz": "oz",
}


def _parse_qty(s: str) -> Optional[tuple[float, str]]:
    m = _QTY_RE.search(s)
    if not m:
        return None
    num = float(m.group(1))
    unit = re.sub(r"[.\s]", "", m.group(2).lower())
    unit = {"floz": "oz"}.get(unit, unit)
    unit = _UNIT_CANON.get(unit, unit)
    return num, unit


def match_net_contents(field: str, expected: str, found: Optional[str]) -> FieldResult:
    if not found or not found.strip():
        return FieldResult(field, expected, found, Status.FAIL, "Not found on the label.")

    e, f = _parse_qty(expected), _parse_qty(found)
    if e is None or f is None:
        # Fall back to plain text comparison.
        return match_text(field, expected, found)
    if e == f:
        return FieldResult(field, expected, found, Status.PASS, "Matches the application.")
    if abs(e[0] - f[0]) < 1e-6 and e[1] != f[1]:
        return FieldResult(
            field, expected, found, Status.REVIEW,
            f"Same quantity but different unit ({f[1]} vs {e[1]}) — suggest a human check.",
        )
    return FieldResult(
        field, expected, found, Status.FAIL,
        f"Label shows {f[0]:g} {f[1]} but the application states {e[0]:g} {e[1]}.",
    )


# --- government warning (the strict check) ---------------------------------


def _canon_warning(s: str) -> str:
    """Whitespace-normalise for wording comparison. Case is compared separately."""
    return _collapse_ws(s.lower())


def _word_diff(expected: str, found: str, limit: int = 3) -> str:
    """Human-readable summary of how the found warning diverges from the mandate."""
    exp_words = expected.split()
    fnd_words = found.split()
    sm = SequenceMatcher(None, [w.lower() for w in exp_words], [w.lower() for w in fnd_words])
    notes: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            notes.append(f'changed "{" ".join(exp_words[i1:i2])}" → "{" ".join(fnd_words[j1:j2])}"')
        elif tag == "delete":
            notes.append(f'missing "{" ".join(exp_words[i1:i2])}"')
        elif tag == "insert":
            notes.append(f'added "{" ".join(fnd_words[j1:j2])}"')
        if len(notes) >= limit:
            notes.append("…")
            break
    return "Differences: " + "; ".join(notes) if notes else ""


def check_government_warning(extraction: LabelExtraction) -> FieldResult:
    """Enforce the mandatory Government Health Warning.

    Three independent checks, all of which must pass:
      1. Present at all.
      2. Heading "GOVERNMENT WARNING:" is in ALL CAPS (Jenny's title-case catch).
      3. Wording matches the mandated text verbatim.
    """
    field = "Government Warning"
    canonical = CANONICAL_GOVERNMENT_WARNING
    text = extraction.government_warning_text

    if not text or not text.strip():
        return FieldResult(
            field, canonical, None, Status.FAIL,
            "No Government Warning statement found. This statement is mandatory on "
            "all alcohol beverage labels.",
        )

    problems: list[str] = []

    # (2) Heading capitalisation. Cross-check the model's boolean against a
    # case-sensitive substring test on the verbatim text.
    heading_caps = "GOVERNMENT WARNING" in text
    heading_any = re.search(r"government\s+warning", text, re.I) is not None
    if extraction.government_warning_heading_uppercase is False:
        heading_caps = False
    if not heading_caps:
        if heading_any:
            problems.append(
                'The "GOVERNMENT WARNING:" heading is not in all capital letters — '
                "it must appear in capitals (found different capitalization)."
            )
        else:
            problems.append('The required "GOVERNMENT WARNING:" heading is missing.')

    # (3) Wording.
    r = _ratio(_canon_warning(canonical), _canon_warning(text))
    if r < WARNING_WORDING_THRESHOLD:
        diff = _word_diff(canonical, text)
        msg = f"The warning wording does not match the mandated text ({r:.0%} similar)."
        if diff:
            msg += " " + diff
        problems.append(msg)

    if problems:
        return FieldResult(field, canonical, text, Status.FAIL, " ".join(problems))

    return FieldResult(
        field, canonical, text, Status.PASS,
        "Present, correctly capitalized, and matches the mandated wording word-for-word.",
    )


# --- orchestration ---------------------------------------------------------


def build_field_results(app: ApplicationData, extraction: LabelExtraction) -> list[FieldResult]:
    """Compare each supplied application field, plus the always-mandatory warning."""
    results: list[FieldResult] = []

    if app.brand_name:
        results.append(match_text("Brand Name", app.brand_name, extraction.brand_name))
    if app.class_type:
        results.append(match_text("Class / Type", app.class_type, extraction.class_type))
    if app.alcohol_content:
        results.append(match_abv("Alcohol Content", app.alcohol_content, extraction.alcohol_content))
    if app.net_contents:
        results.append(
            match_net_contents("Net Contents", app.net_contents, extraction.net_contents)
        )
    if app.producer_name_address:
        results.append(
            match_text("Producer / Bottler", app.producer_name_address, extraction.producer_name_address)
        )
    if app.country_of_origin:
        results.append(
            match_text("Country of Origin", app.country_of_origin, extraction.country_of_origin)
        )

    # The Government Warning is mandatory regardless of what the application lists.
    results.append(check_government_warning(extraction))
    return results


def aggregate(results: list[FieldResult]) -> OverallStatus:
    statuses = {r.status for r in results}
    if Status.FAIL in statuses:
        return OverallStatus.REJECTED
    if Status.REVIEW in statuses:
        return OverallStatus.NEEDS_REVIEW
    return OverallStatus.APPROVED


def verify_label(
    application: ApplicationData,
    image_bytes: bytes,
    media_type: str,
    provider,
    hint: Optional[str] = None,
) -> VerificationReport:
    """End-to-end: read the label with `provider`, then apply the rules.

    `provider` is any object exposing `.extract(image_bytes, media_type, hint)`,
    `.name` and `.is_demo`. Timing wraps the whole thing so we can surface the
    5-second latency target in the UI.
    """
    start = time.perf_counter()
    try:
        extraction = provider.extract(image_bytes, media_type, hint)
    except Exception as exc:  # noqa: BLE001 — surface any provider error to the UI
        return VerificationReport(
            overall=OverallStatus.ERROR,
            elapsed_seconds=time.perf_counter() - start,
            model_used=getattr(provider, "name", ""),
            demo_mode=getattr(provider, "is_demo", False),
            error=str(exc),
        )

    results = build_field_results(application, extraction)
    return VerificationReport(
        overall=aggregate(results),
        field_results=results,
        extraction=extraction,
        elapsed_seconds=time.perf_counter() - start,
        model_used=getattr(provider, "name", ""),
        demo_mode=getattr(provider, "is_demo", False),
    )
