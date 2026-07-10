"""Data models shared across the app.

`LabelExtraction` is a Pydantic model because it is populated from the vision
model's structured tool output. Everything else is a plain dataclass - these
are internal value objects, not API payloads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Status(str, Enum):
    """Per-field verification result."""

    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"  # close enough to warrant a human look, not an auto-fail


class OverallStatus(str, Enum):
    """Roll-up verdict for a whole label."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS REVIEW"
    ERROR = "ERROR"  # extraction failed (bad image, no API access, etc.)


class LabelExtraction(BaseModel):
    """What the vision model actually read off the label artwork.

    Fields are verbatim (not normalised) so the verification engine - not the
    model - owns the pass/fail judgement. `government_warning_text` preserves
    exact capitalisation so we can enforce the all-caps heading rule.
    """

    brand_name: Optional[str] = Field(None, description="Brand name exactly as printed.")
    class_type: Optional[str] = Field(None, description="Class/type designation as printed.")
    alcohol_content: Optional[str] = Field(
        None, description="Alcohol content as printed, e.g. '45% Alc./Vol. (90 Proof)'."
    )
    net_contents: Optional[str] = Field(None, description="Net contents as printed.")
    producer_name_address: Optional[str] = Field(
        None, description="Bottler/producer name and address as printed."
    )
    country_of_origin: Optional[str] = Field(None, description="Country of origin, if shown.")
    government_warning_text: Optional[str] = Field(
        None, description="Full government warning verbatim, preserving capitalisation."
    )
    government_warning_heading_uppercase: Optional[bool] = Field(
        None, description="Whether the 'GOVERNMENT WARNING:' heading is in all caps."
    )
    legibility_notes: Optional[str] = Field(
        None, description="Any glare / blur / skew / low-quality issues affecting the read."
    )


@dataclass
class ApplicationData:
    """The 'expected' values from the COLA application being verified against."""

    brand_name: Optional[str] = None
    class_type: Optional[str] = None
    alcohol_content: Optional[str] = None
    net_contents: Optional[str] = None
    producer_name_address: Optional[str] = None
    country_of_origin: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ApplicationData":
        """Build from a dict, ignoring unknown/empty keys (e.g. CSV rows)."""
        def clean(v):
            if v is None:
                return None
            v = str(v).strip()
            return v or None

        return cls(
            brand_name=clean(d.get("brand_name")),
            class_type=clean(d.get("class_type")),
            alcohol_content=clean(d.get("alcohol_content")),
            net_contents=clean(d.get("net_contents")),
            producer_name_address=clean(d.get("producer_name_address")),
            country_of_origin=clean(d.get("country_of_origin")),
        )


@dataclass
class FieldResult:
    """One row of the verification report."""

    field: str
    expected: Optional[str]
    found: Optional[str]
    status: Status
    detail: str


@dataclass
class VerificationReport:
    """The full result for a single label."""

    overall: OverallStatus
    field_results: list[FieldResult] = field(default_factory=list)
    extraction: Optional[LabelExtraction] = None
    elapsed_seconds: float = 0.0
    model_used: str = ""
    demo_mode: bool = False
    error: Optional[str] = None

    @property
    def is_over_latency_target(self) -> bool:
        """True if we blew past the 5-second stakeholder target."""
        return self.elapsed_seconds > 5.0
