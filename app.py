"""TTB Label Verifier — Streamlit UI.

Design goals, straight from the stakeholder interviews:
  - Clean and obvious. Big verdicts, plain language, no hunting for buttons.
  - Fast. We surface the wall-clock time so the 5-second target is visible.
  - Batch-capable. Peak season means hundreds of labels at once.

This file is the *only* place Streamlit is imported; all verification logic
lives in `src/` so it stays testable and reusable.
"""
from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from src.batch import BatchItem, run_batch
from src.config import DEFAULT_MODEL
from src.extraction import get_provider
from src.models import ApplicationData, OverallStatus, Status, VerificationReport
from src.verification import verify_label

SAMPLES_DIR = Path(__file__).parent / "samples"

# Friendly label -> (filename, one-line expectation) for the sample picker.
SAMPLE_LABELS = {
    "Old Tom Distillery — clean label": "old_tom_bourbon.png",
    "Stone's Throw Gin — case/punctuation differs": "stones_throw_gin.png",
    "Silver Creek Vodka — title-case warning": "title_case_warning.png",
    "Copper Ridge Rye — ABV mismatch": "wrong_abv.png",
    "Harbor Light Rum — missing warning": "missing_warning.png",
}

# ---------------------------------------------------------------------------
# Config & styling
# ---------------------------------------------------------------------------

st.set_page_config(page_title="TTB Label Verifier", page_icon="🥃", layout="wide")

st.markdown(
    """
    <style>
      html, body, [class*="css"] { font-size: 16.5px; }
      .big-title { font-size: 2.0rem; font-weight: 800; margin-bottom: 0.1rem; }
      .subtitle { color: #6b7280; font-size: 1.05rem; margin-top: 0; }
      .verdict {
          border-radius: 12px; padding: 1.1rem 1.3rem; margin: 0.6rem 0 1rem 0;
          font-size: 1.5rem; font-weight: 800; display: flex; align-items: center;
          gap: 0.6rem; border: 2px solid transparent;
      }
      .v-approved { background: rgba(22,163,74,.12); color: #16a34a; border-color: rgba(22,163,74,.5); }
      .v-rejected { background: rgba(220,38,38,.12); color: #dc2626; border-color: rgba(220,38,38,.5); }
      .v-review   { background: rgba(217,119,6,.12); color: #d97706; border-color: rgba(217,119,6,.5); }
      .v-error    { background: rgba(107,114,128,.14); color: #6b7280; border-color: rgba(107,114,128,.5); }
      .field-card {
          border-left: 6px solid #9ca3af; background: rgba(148,163,184,.08);
          border-radius: 8px; padding: 0.6rem 0.9rem; margin: 0.45rem 0;
      }
      .fc-pass   { border-left-color: #16a34a; }
      .fc-fail   { border-left-color: #dc2626; }
      .fc-review { border-left-color: #d97706; }
      .fc-title { font-weight: 700; font-size: 1.05rem; }
      .fc-meta  { color: #6b7280; font-size: 0.92rem; margin: 0.15rem 0; }
      .chip { font-weight: 800; font-size: 0.8rem; padding: 0.1rem 0.5rem;
              border-radius: 999px; margin-right: 0.4rem; }
      .chip-pass   { background: rgba(22,163,74,.18); color: #16a34a; }
      .chip-fail   { background: rgba(220,38,38,.18); color: #dc2626; }
      .chip-review { background: rgba(217,119,6,.18); color: #d97706; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="big-title">🥃 TTB Label Verifier</div>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">Check that a label\'s artwork matches its application — '
    "brand, alcohol content, net contents, and the mandatory Government Warning.</p>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Provider / key resolution
# ---------------------------------------------------------------------------


def _secret(name: str):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:  # noqa: BLE001 — no secrets file locally is fine
        pass
    return os.getenv(name)


API_KEY = _secret("ANTHROPIC_API_KEY")
MODEL = _secret("LABEL_MODEL") or DEFAULT_MODEL

if API_KEY:
    st.caption(f"🟢 Live AI reading enabled · model **{MODEL}**")
else:
    st.warning(
        "**Demo mode** — no `ANTHROPIC_API_KEY` configured. The five bundled sample "
        "labels work fully (offline canned readings); add an API key to analyse your "
        "own uploads with the live vision model.",
        icon="🔌",
    )


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

_STATUS_CHIP = {
    Status.PASS: '<span class="chip chip-pass">PASS</span>',
    Status.FAIL: '<span class="chip chip-fail">FAIL</span>',
    Status.REVIEW: '<span class="chip chip-review">REVIEW</span>',
}
_FC_CLASS = {Status.PASS: "fc-pass", Status.FAIL: "fc-fail", Status.REVIEW: "fc-review"}


def render_verdict(report: VerificationReport) -> None:
    mapping = {
        OverallStatus.APPROVED: ("v-approved", "✅", "APPROVED — label matches the application"),
        OverallStatus.REJECTED: ("v-rejected", "❌", "REJECTED — one or more checks failed"),
        OverallStatus.NEEDS_REVIEW: ("v-review", "⚠️", "NEEDS REVIEW — a human should take a look"),
        OverallStatus.ERROR: ("v-error", "🛑", "COULD NOT ANALYSE"),
    }
    cls, icon, text = mapping[report.overall]
    st.markdown(f'<div class="verdict {cls}">{icon}&nbsp;{text}</div>', unsafe_allow_html=True)

    if report.error:
        st.error(report.error)
        return

    latency_flag = "  ·  ⏱️ over the 5s target" if report.is_over_latency_target else ""
    demo_flag = "  ·  demo data" if report.demo_mode else ""
    st.caption(f"Analysed in **{report.elapsed_seconds:.1f}s**{latency_flag}{demo_flag}")


def render_fields(report: VerificationReport) -> None:
    for r in report.field_results:
        chip = _STATUS_CHIP.get(r.status, "")
        meta_bits = []
        if r.expected and r.field != "Government Warning":
            meta_bits.append(f"Application: <b>{_esc(r.expected)}</b>")
        if r.found and r.field != "Government Warning":
            meta_bits.append(f"On label: <b>{_esc(r.found)}</b>")
        meta = "<div class='fc-meta'>" + " &nbsp;·&nbsp; ".join(meta_bits) + "</div>" if meta_bits else ""
        st.markdown(
            f"""<div class="field-card {_FC_CLASS.get(r.status, '')}">
                <div class="fc-title">{chip}{_esc(r.field)}</div>
                {meta}
                <div>{_esc(r.detail)}</div>
            </div>""",
            unsafe_allow_html=True,
        )


def _esc(s) -> str:
    if s is None:
        return ""
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def render_extraction(report: VerificationReport) -> None:
    if not report.extraction:
        return
    ex = report.extraction
    with st.expander("🔎 What the AI read from the label"):
        data = {
            "Brand name": ex.brand_name,
            "Class / type": ex.class_type,
            "Alcohol content": ex.alcohol_content,
            "Net contents": ex.net_contents,
            "Producer / bottler": ex.producer_name_address,
            "Country of origin": ex.country_of_origin,
            "Government warning (verbatim)": ex.government_warning_text,
        }
        for k, v in data.items():
            st.markdown(f"**{k}:** {v if v else '_(not found)_'}")
        if ex.legibility_notes:
            st.info(f"Image-quality note: {ex.legibility_notes}", icon="🖼️")


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------


@st.cache_data
def _load_applications() -> dict[str, dict]:
    df = pd.read_csv(SAMPLES_DIR / "applications.csv").fillna("")
    return {row["image_file"]: row.to_dict() for _, row in df.iterrows()}


@st.cache_data
def _load_sample_image(filename: str) -> bytes:
    return (SAMPLES_DIR / filename).read_bytes()


@st.cache_data
def _build_sample_zip() -> bytes:
    """Bundle the sample CSV + images so graders can test batch upload."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("applications.csv", (SAMPLES_DIR / "applications.csv").read_text())
        for fn in SAMPLE_LABELS.values():
            zf.write(SAMPLES_DIR / fn, arcname=fn)
    return buf.getvalue()


APPLICATIONS = _load_applications()


def _media_type(name: str, declared: str | None = None) -> str:
    if declared and declared.startswith("image/"):
        return declared
    ext = Path(name).suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }.get(ext, "image/png")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_single, tab_batch = st.tabs(["🔍  Single label", "📚  Batch"])


# ----- Single label --------------------------------------------------------
with tab_single:
    left, right = st.columns([1, 1], gap="large")

    with left:
        st.subheader("Step 1 · The label")

        choice = st.selectbox(
            "Start from a sample (optional)",
            ["— Upload my own —", *SAMPLE_LABELS.keys()],
            help="Pick a sample to auto-fill everything, or upload your own label below.",
        )

        # When the sample choice changes, pre-fill the form fields.
        if choice != st.session_state.get("_last_choice"):
            st.session_state["_last_choice"] = choice
            if choice in SAMPLE_LABELS:
                fn = SAMPLE_LABELS[choice]
                app = APPLICATIONS.get(fn, {})
                st.session_state["f_brand"] = app.get("brand_name", "")
                st.session_state["f_class"] = app.get("class_type", "")
                st.session_state["f_abv"] = app.get("alcohol_content", "")
                st.session_state["f_net"] = app.get("net_contents", "")
                st.session_state["_sample_file"] = fn
            else:
                st.session_state["_sample_file"] = None

        uploaded = st.file_uploader(
            "…or upload a label image", type=["png", "jpg", "jpeg", "gif", "webp"]
        )

        # Resolve which image we're actually verifying.
        image_bytes: bytes | None = None
        image_name = ""
        media_type = "image/png"
        if uploaded is not None:
            image_bytes = uploaded.getvalue()
            image_name = uploaded.name
            media_type = _media_type(uploaded.name, uploaded.type)
        elif st.session_state.get("_sample_file"):
            fn = st.session_state["_sample_file"]
            image_bytes = _load_sample_image(fn)
            image_name = fn
            media_type = "image/png"

        if image_bytes:
            st.image(image_bytes, caption=image_name, width="stretch")

        st.subheader("Step 2 · The application")
        st.caption("What the COLA application says this label should contain.")
        brand = st.text_input("Brand name", key="f_brand")
        class_type = st.text_input("Class / type", key="f_class")
        c1, c2 = st.columns(2)
        with c1:
            abv = st.text_input("Alcohol content", key="f_abv", placeholder="45% Alc./Vol. (90 Proof)")
        with c2:
            net = st.text_input("Net contents", key="f_net", placeholder="750 mL")

        verify_clicked = st.button("✓  Verify label", type="primary", width="stretch")

    with right:
        st.subheader("Result")
        if verify_clicked:
            if not image_bytes:
                st.error("Please choose a sample or upload a label image first.")
            else:
                application = ApplicationData(
                    brand_name=brand or None,
                    class_type=class_type or None,
                    alcohol_content=abv or None,
                    net_contents=net or None,
                )
                provider = get_provider(API_KEY, MODEL)
                with st.spinner("Reading the label and checking compliance…"):
                    report = verify_label(application, image_bytes, media_type, provider, hint=image_name)
                st.session_state["_single_report"] = report

        report = st.session_state.get("_single_report")
        if report:
            render_verdict(report)
            render_fields(report)
            render_extraction(report)
        else:
            st.info("Choose a sample or upload a label, fill in the application, then press **Verify label**.")


# ----- Batch ---------------------------------------------------------------
with tab_batch:
    st.subheader("Verify many labels at once")
    st.caption(
        "For peak season, when importers submit hundreds of applications. "
        "Labels are analysed in parallel and you can download a full report."
    )

    def _run_and_store(items: list[BatchItem]) -> None:
        provider = get_provider(API_KEY, MODEL)
        bar = st.progress(0.0, text="Starting…")

        def _prog(done: int, total: int) -> None:
            bar.progress(done / total, text=f"Analysed {done} of {total} labels…")

        results = run_batch(items, provider, on_progress=_prog)
        bar.empty()
        st.session_state["_batch_results"] = results

    b1, b2 = st.columns([1, 1])
    with b1:
        if st.button("▶  Run the 5 bundled samples", width="stretch"):
            items = [
                BatchItem(
                    name=fn,
                    application=ApplicationData.from_dict(APPLICATIONS[fn]),
                    image_bytes=_load_sample_image(fn),
                    media_type="image/png",
                )
                for fn in SAMPLE_LABELS.values()
            ]
            _run_and_store(items)
    with b2:
        st.download_button(
            "⬇  Download the sample batch (zip)",
            data=_build_sample_zip(),
            file_name="sample_batch.zip",
            help="CSV + the 5 label images, so you can test the 'bring your own' flow.",
            width="stretch",
        )

    st.divider()
    st.markdown("**Or bring your own:** upload a CSV plus the matching label images.")
    with st.expander("CSV format"):
        st.markdown(
            "One row per label. Required column **`image_file`** (must match an uploaded "
            "image's filename), plus any of: `brand_name`, `class_type`, "
            "`alcohol_content`, `net_contents`, `producer_name_address`, `country_of_origin`."
        )
        st.code(
            "image_file,brand_name,class_type,alcohol_content,net_contents\n"
            "acme_gin.png,Acme Gin,London Dry Gin,40% Alc./Vol. (80 Proof),750 mL",
            language="text",
        )

    csv_file = st.file_uploader("Applications CSV", type=["csv"], key="batch_csv")
    img_files = st.file_uploader(
        "Label images", type=["png", "jpg", "jpeg", "gif", "webp"],
        accept_multiple_files=True, key="batch_imgs",
    )

    if st.button("▶  Run batch", type="primary", width="stretch"):
        if not csv_file:
            st.error("Please upload an applications CSV.")
        else:
            df = pd.read_csv(csv_file).fillna("")
            if "image_file" not in df.columns:
                st.error("The CSV must have an `image_file` column.")
            else:
                images = {f.name: f for f in (img_files or [])}
                items = []
                for _, row in df.iterrows():
                    fn = str(row["image_file"]).strip()
                    f = images.get(fn)
                    items.append(
                        BatchItem(
                            name=fn,
                            application=ApplicationData.from_dict(row.to_dict()),
                            image_bytes=f.getvalue() if f else None,
                            media_type=_media_type(fn, f.type if f else None),
                        )
                    )
                if not items:
                    st.error("No rows found in the CSV.")
                else:
                    _run_and_store(items)

    # ----- Batch results -----
    results = st.session_state.get("_batch_results")
    if results:
        st.divider()
        counts = {"APPROVED": 0, "REJECTED": 0, "NEEDS REVIEW": 0, "ERROR": 0}
        for r in results:
            counts[r.report.overall.value] = counts.get(r.report.overall.value, 0) + 1

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total", len(results))
        m2.metric("✅ Approved", counts["APPROVED"])
        m3.metric("❌ Rejected", counts["REJECTED"])
        m4.metric("⚠️ Review", counts["NEEDS REVIEW"])
        m5.metric("🛑 Errors", counts["ERROR"])

        table_rows = []
        for r in results:
            issues = "; ".join(
                f"{fr.field}: {fr.detail}"
                for fr in r.report.field_results
                if fr.status in (Status.FAIL, Status.REVIEW)
            )
            table_rows.append(
                {
                    "Label": r.name,
                    "Verdict": r.report.overall.value,
                    "Time (s)": round(r.report.elapsed_seconds, 1),
                    "Issues": issues or ("—" if not r.report.error else r.report.error),
                }
            )
        table_df = pd.DataFrame(table_rows)
        st.dataframe(table_df, width="stretch", hide_index=True)

        st.download_button(
            "⬇  Download full report (CSV)",
            data=table_df.to_csv(index=False).encode("utf-8"),
            file_name="verification_report.csv",
            mime="text/csv",
        )

        for r in results:
            with st.expander(f"{r.name} — {r.report.overall.value}"):
                render_verdict(r.report)
                render_fields(r.report)
                render_extraction(r.report)
