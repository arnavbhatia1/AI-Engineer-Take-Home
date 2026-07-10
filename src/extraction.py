"""Vision extraction providers.

`ExtractionProvider` is intentionally a tiny interface so the vision backend is
swappable. Today it's Claude via the Anthropic API; the same seam is where an
on-prem / self-hosted vision model would drop in to satisfy the firewall
constraint Marcus raised (see README "Assumptions & trade-offs").

`MockProvider` powers offline demo mode and deterministic tests — it returns
canned readings for the bundled sample labels so the whole pipeline (and UI)
works without an API key.
"""
from __future__ import annotations

import base64
from typing import Optional, Protocol

from .config import DEFAULT_MODEL, MAX_TOKENS
from .imaging import prepare_image
from .models import LabelExtraction

_SYSTEM_PROMPT = (
    "You are a meticulous TTB label-compliance assistant. You are shown a "
    "photograph or artwork of an alcohol beverage label. Read ONLY what is "
    "actually printed on the label and record it verbatim — do not correct, "
    "normalise, translate, or infer values that are not shown. "
    "Preserve the EXACT capitalization and punctuation of the government "
    "warning statement, because capitalization is compliance-relevant. "
    "If the image is skewed, blurry, glared, or otherwise hard to read, do "
    "your best and note the issue in legibility_notes. Use null for any field "
    "that is genuinely absent from the label."
)

# Tool schema mirrors LabelExtraction. Forcing this single tool guarantees a
# structured, parseable reading with one round trip (keeps latency low).
_LABEL_TOOL = {
    "name": "record_label_fields",
    "description": "Record the fields read from the alcohol beverage label image.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand_name": {"type": ["string", "null"], "description": "Brand name exactly as printed."},
            "class_type": {"type": ["string", "null"], "description": "Class/type designation as printed (e.g. 'Kentucky Straight Bourbon Whiskey')."},
            "alcohol_content": {"type": ["string", "null"], "description": "Alcohol content exactly as printed, e.g. '45% Alc./Vol. (90 Proof)'."},
            "net_contents": {"type": ["string", "null"], "description": "Net contents exactly as printed, e.g. '750 mL'."},
            "producer_name_address": {"type": ["string", "null"], "description": "Bottler/producer name and address as printed."},
            "country_of_origin": {"type": ["string", "null"], "description": "Country of origin, if shown."},
            "government_warning_text": {"type": ["string", "null"], "description": "The FULL government warning statement, verbatim, preserving exact capitalization and punctuation. null if none is present."},
            "government_warning_heading_uppercase": {"type": ["boolean", "null"], "description": "true if the 'GOVERNMENT WARNING:' heading appears in ALL CAPITAL letters; false if it uses any other capitalization; null if no warning is present."},
            "legibility_notes": {"type": ["string", "null"], "description": "Note any glare, blur, skew, or low-quality issues affecting the read; null if the image is clear."},
        },
        "required": [
            "brand_name", "class_type", "alcohol_content", "net_contents",
            "producer_name_address", "country_of_origin", "government_warning_text",
            "government_warning_heading_uppercase", "legibility_notes",
        ],
        "additionalProperties": False,
    },
}


class ExtractionProvider(Protocol):
    name: str
    is_demo: bool

    def extract(self, image_bytes: bytes, media_type: str, hint: Optional[str] = None) -> LabelExtraction:
        ...


class ClaudeProvider:
    """Reads labels with Claude vision via a single forced tool call."""

    is_demo = False

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        # Imported lazily so the package imports cleanly without the SDK
        # installed (e.g. for pure-logic unit tests).
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.name = model

    def extract(self, image_bytes: bytes, media_type: str, hint: Optional[str] = None) -> LabelExtraction:
        # Downscale oversized uploads: faster (5s target), cheaper, and keeps
        # big phone photos under the API's image size limit.
        image_bytes, media_type = prepare_image(image_bytes, media_type)
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        message = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            tools=[_LABEL_TOOL],
            tool_choice={"type": "tool", "name": "record_label_fields"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64},
                        },
                        {"type": "text", "text": "Read this alcohol beverage label and record its fields."},
                    ],
                }
            ],
        )
        tool_block = next((b for b in message.content if b.type == "tool_use"), None)
        if tool_block is None:
            raise RuntimeError("The model did not return a structured label reading.")
        return LabelExtraction(**tool_block.input)


# --- Offline demo provider -------------------------------------------------
#
# Canned readings for the bundled sample labels. Because we generate those
# labels ourselves (samples/generate_samples.py), we know exactly what a
# correct vision read looks like. This lets graders exercise the full pass/fail
# logic on the deployed app even with no API key configured.

_GOOD_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)
_TITLECASE_WARNING = _GOOD_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")

MOCK_EXTRACTIONS: dict[str, LabelExtraction] = {
    "old_tom_bourbon.png": LabelExtraction(
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        producer_name_address="Bottled by Old Tom Distillery, Bardstown, KY",
        country_of_origin=None,
        government_warning_text=_GOOD_WARNING,
        government_warning_heading_uppercase=True,
        legibility_notes=None,
    ),
    "stones_throw_gin.png": LabelExtraction(
        brand_name="STONE'S THROW",
        class_type="London Dry Gin",
        alcohol_content="40% Alc./Vol. (80 Proof)",
        net_contents="750 mL",
        producer_name_address="Distilled & Bottled by Stone's Throw Spirits, Portland, OR",
        country_of_origin=None,
        government_warning_text=_GOOD_WARNING,
        government_warning_heading_uppercase=True,
        legibility_notes=None,
    ),
    "title_case_warning.png": LabelExtraction(
        brand_name="SILVER CREEK VODKA",
        class_type="Vodka",
        alcohol_content="40% Alc./Vol. (80 Proof)",
        net_contents="750 mL",
        producer_name_address="Produced by Silver Creek Distilling Co., Austin, TX",
        country_of_origin=None,
        government_warning_text=_TITLECASE_WARNING,
        government_warning_heading_uppercase=False,
        legibility_notes=None,
    ),
    "wrong_abv.png": LabelExtraction(
        brand_name="COPPER RIDGE RESERVE",
        class_type="Straight Rye Whiskey",
        alcohol_content="40% Alc./Vol. (80 Proof)",
        net_contents="750 mL",
        producer_name_address="Bottled by Copper Ridge Distillers, Louisville, KY",
        country_of_origin=None,
        government_warning_text=_GOOD_WARNING,
        government_warning_heading_uppercase=True,
        legibility_notes=None,
    ),
    "missing_warning.png": LabelExtraction(
        brand_name="HARBOR LIGHT SPICED RUM",
        class_type="Spiced Rum",
        alcohol_content="35% Alc./Vol. (70 Proof)",
        net_contents="750 mL",
        producer_name_address="Bottled by Harbor Light Rum Co., Key West, FL",
        country_of_origin=None,
        government_warning_text=None,
        government_warning_heading_uppercase=None,
        legibility_notes=None,
    ),
    "altered_warning.png": LabelExtraction(
        brand_name="GOLDEN GATE BRANDY",
        class_type="California Brandy",
        alcohol_content="40% Alc./Vol. (80 Proof)",
        net_contents="750 mL",
        producer_name_address="Distilled by Golden Gate Cellars, San Francisco, CA",
        country_of_origin=None,
        government_warning_text=_GOOD_WARNING.replace(
            "because of the risk of birth defects", "because of the risk of harm to the baby"
        ).replace("may cause health problems", "can cause health issues"),
        government_warning_heading_uppercase=True,
        legibility_notes=None,
    ),
}


class MockProvider:
    """Offline provider used when no API key is configured, and in tests."""

    is_demo = True
    name = "demo (offline sample data)"

    def extract(self, image_bytes: bytes, media_type: str, hint: Optional[str] = None) -> LabelExtraction:
        key = (hint or "").strip().lower()
        for filename, extraction in MOCK_EXTRACTIONS.items():
            if key.endswith(filename):
                return extraction.model_copy(deep=True)
        # Unknown image in demo mode — we can't actually read it offline.
        return LabelExtraction(
            legibility_notes=(
                "Demo mode: this offline build only has canned readings for the "
                "bundled sample labels. Configure an ANTHROPIC_API_KEY to analyse "
                "your own uploads with the live vision model."
            )
        )


def get_provider(api_key: Optional[str], model: str = DEFAULT_MODEL) -> ExtractionProvider:
    """Return a live provider if a key is available, else the offline demo one."""
    if api_key:
        return ClaudeProvider(api_key=api_key, model=model)
    return MockProvider()
