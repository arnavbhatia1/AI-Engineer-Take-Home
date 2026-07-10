"""TTB Label Verifier: Streamlit UI.

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
    "Old Tom Distillery (clean label)": "old_tom_bourbon.png",
    "Stone's Throw Gin (case/punctuation differs)": "stones_throw_gin.png",
    "Silver Creek Vodka (title-case warning)": "title_case_warning.png",
    "Copper Ridge Rye (ABV mismatch)": "wrong_abv.png",
    "Harbor Light Rum (missing warning)": "missing_warning.png",
    "Golden Gate Brandy (reworded warning)": "altered_warning.png",
}

# ---------------------------------------------------------------------------
# Config & styling
# ---------------------------------------------------------------------------

st.set_page_config(page_title="TTB Label Verifier", page_icon="🥃", layout="wide")

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Public+Sans:ital,wght@0,400;0,500;0,600;0,700;0,800;1,400&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap');

      :root {
        --navy:#0f2a4a; --navy-deep:#0a1f38; --gold:#a67c1a; --gold-soft:#c9a94e;
        --parchment:#f4f1ea; --card:#ffffff; --line:#e4ddcf;
        --ink:#1b2430; --muted:#6d6a61;
        --green:#1e7a46; --green-bg:rgba(30,122,70,.10);
        --red:#b3261e;   --red-bg:rgba(179,38,30,.10);
        --amber:#9a6a00; --amber-bg:rgba(154,106,0,.10);
        --grey:#5f6b7a;  --grey-bg:rgba(95,107,122,.10);
      }

      /* base */
      .stApp { background: var(--parchment); color: var(--ink); }
      html, body, .stApp, button, input, textarea, select, .stApp p, .stApp label,
      [data-testid="stMarkdownContainer"],
      [data-testid="stMarkdownContainer"] span, [data-testid="stMarkdownContainer"] div {
        font-family:'Public Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }
      /* Never override Material icon fonts (expander chevrons, uploader icons, …) */
      [data-testid="stIconMaterial"], span[class*="material-symbols"], span[class*="material-icons"] {
        font-family:'Material Symbols Rounded','Material Symbols Outlined','Material Icons' !important;
      }
      h1,h2,h3,h4,.mast-title,.sec-title,.v-title {
        font-family:'Source Serif 4', Georgia, 'Times New Roman', serif !important;
        color: var(--navy); letter-spacing:.2px;
      }
      .block-container { max-width: 1180px; padding-top: 0.6rem; padding-bottom: 3rem; }
      [data-testid="stHeader"] { background: transparent; }

      /* federal utility strip + masthead */
      .gov-bar { background: var(--navy-deep); border-radius: 8px 8px 0 0; }
      .gov-bar-inner { padding:.42rem 1rem; display:flex; justify-content:space-between;
        align-items:center; gap:1rem; flex-wrap:wrap; font-size:.76rem; letter-spacing:.03em; }
      .gov-bar-inner span { color:#c7d0de; }
      .gov-bar .star { color: var(--gold-soft); }
      .masthead { background: var(--navy); border-radius:0 0 8px 8px; padding:1.15rem 1.3rem;
        display:flex; align-items:center; gap:1.1rem; border-top:3px solid var(--gold);
        box-shadow:0 10px 30px rgba(15,42,74,.18); }
      .masthead .crest { flex:0 0 auto; line-height:0; }
      .mast-text { flex:1 1 auto; }
      .mast-eyebrow { text-transform:uppercase; letter-spacing:.17em; font-size:.72rem;
        font-weight:700; color:var(--gold-soft); margin-bottom:.18rem; }
      .mast-title { font-size:1.95rem; font-weight:700; line-height:1.03; color:#fff !important; }
      .mast-sub { color:#c4cede; font-size:.95rem; margin-top:.3rem; }
      .mast-badge { flex:0 0 auto; align-self:flex-start; border:1px solid var(--gold-soft);
        color:var(--gold-soft); border-radius:999px; padding:.16rem .62rem; font-size:.66rem;
        font-weight:800; letter-spacing:.16em; text-transform:uppercase; }
      .lede { color:var(--muted); font-size:1.02rem; margin:1rem 0 .3rem; max-width:52rem; }

      /* section headers */
      .sec { margin:.5rem 0 .55rem; }
      .sec-eyebrow { text-transform:uppercase; letter-spacing:.14em; font-size:.72rem;
        font-weight:800; color:var(--gold); }
      .sec-title { font-size:1.3rem; font-weight:700; color:var(--navy); line-height:1.1;
        border-bottom:2px solid var(--line); padding-bottom:.36rem; }

      /* verdict */
      .verdict { display:flex; align-items:center; gap:.95rem; background:var(--card);
        border:1px solid var(--line); border-left:6px solid var(--grey); border-radius:10px;
        padding:1rem 1.15rem; margin:.4rem 0 1rem; box-shadow:0 2px 12px rgba(20,30,50,.06); }
      .v-icon { flex:0 0 auto; width:46px; height:46px; border-radius:50%; color:#fff;
        display:flex; align-items:center; justify-content:center; font-size:1.5rem; font-weight:800; }
      .v-eyebrow { text-transform:uppercase; letter-spacing:.15em; font-size:.7rem;
        font-weight:800; color:var(--muted); }
      .v-title { font-size:1.5rem; font-weight:700; line-height:1.05; }
      .v-sub { color:var(--muted); font-size:.96rem; margin-top:.1rem; }
      .v-approved{border-left-color:var(--green)} .v-approved .v-icon{background:var(--green)} .v-approved .v-title{color:var(--green)}
      .v-rejected{border-left-color:var(--red)}   .v-rejected .v-icon{background:var(--red)}   .v-rejected .v-title{color:var(--red)}
      .v-review{border-left-color:var(--amber)}    .v-review .v-icon{background:var(--amber)}    .v-review .v-title{color:var(--amber)}
      .v-error{border-left-color:var(--grey)}      .v-error .v-icon{background:var(--grey)}      .v-error .v-title{color:var(--grey)}

      /* field cards */
      .field-card { background:var(--card); border:1px solid var(--line); border-left:5px solid var(--grey);
        border-radius:8px; padding:.72rem .95rem; margin:.5rem 0; box-shadow:0 1px 4px rgba(20,30,50,.04); }
      .fc-pass{border-left-color:var(--green)} .fc-fail{border-left-color:var(--red)} .fc-review{border-left-color:var(--amber)}
      .fc-head { display:flex; align-items:center; gap:.55rem; }
      .fc-title { font-weight:700; font-size:1.05rem; color:var(--navy); }
      .fc-meta { color:var(--muted); font-size:.9rem; margin:.3rem 0 .18rem; }
      .fc-detail { font-size:.97rem; color:var(--ink); }
      .pill { display:inline-flex; align-items:center; gap:.34rem; font-weight:800; font-size:.68rem;
        letter-spacing:.06em; text-transform:uppercase; padding:.17rem .55rem; border-radius:999px; }
      .pill .dot { width:.5rem; height:.5rem; border-radius:50%; background:currentColor; }
      .pill-pass{color:var(--green);background:var(--green-bg)} .pill-fail{color:var(--red);background:var(--red-bg)}
      .pill-review{color:var(--amber);background:var(--amber-bg)}

      /* government-warning word diff */
      .gw-diff { background:#fbf9f4; border:1px dashed var(--line); border-radius:6px;
        padding:.6rem .8rem; margin:.15rem 0 .1rem; font-size:.9rem; line-height:1.75; }
      .gw-diff .gw-row { margin:.15rem 0; }
      .gw-diff .lbl { display:inline-block; font-weight:800; font-size:.64rem; letter-spacing:.09em;
        text-transform:uppercase; color:var(--muted); margin-right:.45rem; min-width:5.4rem; }
      .diff-miss { background:var(--green-bg); color:var(--green); font-weight:700;
        padding:0 .18rem; border-radius:3px; }
      .diff-extra { background:var(--red-bg); color:var(--red); font-weight:700;
        padding:0 .18rem; border-radius:3px; text-decoration:line-through; }

      /* buttons */
      .stButton>button, .stDownloadButton>button { border-radius:6px; font-weight:700;
        border:1px solid var(--navy); color:var(--navy); background:#fff; transition:all .12s ease; }
      .stButton>button:hover, .stDownloadButton>button:hover { background:#eef1f6; border-color:var(--navy-deep); color:var(--navy-deep); }
      .stButton>button[kind="primary"] { background:var(--navy); color:#fff; }
      .stButton>button[kind="primary"]:hover { background:var(--navy-deep); color:#fff; }

      /* tabs */
      [data-baseweb="tab-list"] { gap:.4rem; border-bottom:1px solid var(--line); }
      [data-baseweb="tab"] { font-weight:600; color:var(--muted); }
      [data-baseweb="tab"][aria-selected="true"] { color:var(--navy); }
      [data-baseweb="tab-highlight"] { background:var(--navy); height:3px; }

      /* inputs */
      .stTextInput div[data-baseweb="input"], [data-testid="stFileUploaderDropzone"] {
        border-radius:6px; border-color:var(--line); }
      .stTextInput div[data-baseweb="input"]:focus-within { border-color:var(--navy); box-shadow:0 0 0 1px var(--navy); }

      /* metrics, expander */
      [data-testid="stMetric"] { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:.55rem .85rem; }
      [data-testid="stMetricValue"] { color:var(--navy); font-weight:800; }
      [data-testid="stExpander"] { border:1px solid var(--line); border-radius:8px; background:var(--card); }
      [data-testid="stExpander"] summary { font-weight:600; color:var(--navy); }

      /* footer */
      .site-footer { margin-top:2.4rem; padding-top:1rem; border-top:1px solid var(--line);
        color:var(--muted); font-size:.82rem; text-align:center; line-height:1.6; }
      .site-footer b { color:var(--navy); }
    </style>
    """,
    unsafe_allow_html=True,
)

# Masthead: federal utility strip + a stylised crest (NOT an official seal) and
# wordmark. Everything is explicitly labelled a prototype.
st.markdown(
    '<div class="gov-bar"><div class="gov-bar-inner">'
    '<span><span class="star">★</span>&nbsp; Proof-of-concept demonstration</span>'
    '<span>Alcohol &amp; Tobacco Tax and Trade Bureau &nbsp;·&nbsp; U.S. Department of the Treasury</span>'
    "</div></div>"
    '<div class="masthead">'
    '<div class="crest">'
    '<svg width="62" height="62" viewBox="0 0 100 100" role="img" aria-label="emblem">'
    '<circle cx="50" cy="50" r="47" fill="#0a1f38" stroke="#a67c1a" stroke-width="3"/>'
    '<circle cx="50" cy="50" r="39" fill="none" stroke="#c9a94e" stroke-width="1" opacity=".55"/>'
    '<path d="M50,26 L55.6,42.3 L72.8,42.6 L59,52.9 L64.1,69.4 L50,59.5 L35.9,69.4 L41,52.9 L27.2,42.6 L44.4,42.3 Z" fill="#c9a94e"/>'
    "</svg>"
    "</div>"
    '<div class="mast-text">'
    '<div class="mast-eyebrow">TTB Label Compliance</div>'
    '<div class="mast-title">Label Verification Console</div>'
    '<div class="mast-sub">AI-assisted review of alcohol beverage labels against COLA applications</div>'
    "</div>"
    '<div class="mast-badge">Prototype</div>'
    "</div>"
    '<p class="lede">Confirm a label&#39;s artwork matches its application: brand name, '
    "alcohol content, net contents, and the mandatory Government Health Warning. Results in seconds.</p>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Provider / key resolution
# ---------------------------------------------------------------------------


def _secret(name: str):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:  # noqa: BLE001 - no secrets file locally is fine
        pass
    return os.getenv(name)


API_KEY = _secret("ANTHROPIC_API_KEY")
MODEL = _secret("LABEL_MODEL") or DEFAULT_MODEL

if API_KEY:
    st.caption(f"🟢 Live AI reading enabled · model **{MODEL}**")
else:
    st.warning(
        "**Demo mode**: no `ANTHROPIC_API_KEY` configured. The bundled sample "
        "labels work fully (offline canned readings); add an API key to analyse your "
        "own uploads with the live vision model.",
        icon="🔌",
    )


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

_STATUS_PILL = {
    Status.PASS: '<span class="pill pill-pass"><span class="dot"></span>Pass</span>',
    Status.FAIL: '<span class="pill pill-fail"><span class="dot"></span>Fail</span>',
    Status.REVIEW: '<span class="pill pill-review"><span class="dot"></span>Review</span>',
}
_FC_CLASS = {Status.PASS: "fc-pass", Status.FAIL: "fc-fail", Status.REVIEW: "fc-review"}


def section_header(title: str, eyebrow: str = "") -> None:
    eb = f'<div class="sec-eyebrow">{eyebrow}</div>' if eyebrow else ""
    st.markdown(f'<div class="sec">{eb}<div class="sec-title">{title}</div></div>', unsafe_allow_html=True)


def render_verdict(report: VerificationReport) -> None:
    mapping = {
        OverallStatus.APPROVED: ("v-approved", "✓", "Approved", "Label matches the application."),
        OverallStatus.REJECTED: ("v-rejected", "✕", "Rejected", "One or more required checks failed."),
        OverallStatus.NEEDS_REVIEW: ("v-review", "!", "Needs review", "A compliance agent should take a look."),
        OverallStatus.ERROR: ("v-error", "–", "Could not analyse", "The label could not be read."),
    }
    cls, icon, title, sub = mapping[report.overall]
    st.markdown(
        f'<div class="verdict {cls}">'
        f'<div class="v-icon">{icon}</div>'
        f'<div><div class="v-eyebrow">Verdict</div>'
        f'<div class="v-title">{title}</div>'
        f'<div class="v-sub">{sub}</div></div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    if report.error:
        st.error(report.error)
        return

    latency_flag = "  ·  ⏱ over the 5s target" if report.is_over_latency_target else ""
    demo_flag = "  ·  demo data" if report.demo_mode else ""
    st.caption(f"Analysed in **{report.elapsed_seconds:.1f}s**{latency_flag}{demo_flag}")


def _warning_diff_html(expected: str, found: str) -> str:
    """Side-by-side word-level diff of the mandated warning vs the label's.

    Words the label is missing/changed are highlighted on the "Mandated" line;
    words the label wrongly added/changed are struck through on the "On label"
    line. Comparison is case-insensitive (capitalisation issues are reported
    separately by the engine).
    """
    from difflib import SequenceMatcher

    e_words, f_words = expected.split(), found.split()
    sm = SequenceMatcher(None, [w.lower() for w in e_words], [w.lower() for w in f_words])

    exp_parts: list[str] = []
    fnd_parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        exp_chunk = " ".join(_esc(w) for w in e_words[i1:i2])
        fnd_chunk = " ".join(_esc(w) for w in f_words[j1:j2])
        if tag == "equal":
            exp_parts.append(exp_chunk)
            fnd_parts.append(fnd_chunk)
        else:  # replace / delete / insert
            if exp_chunk:
                exp_parts.append(f'<span class="diff-miss">{exp_chunk}</span>')
            if fnd_chunk:
                fnd_parts.append(f'<span class="diff-extra">{fnd_chunk}</span>')

    return (
        '<div class="gw-diff">'
        f'<div class="gw-row"><span class="lbl">Mandated</span>{" ".join(exp_parts)}</div>'
        f'<div class="gw-row"><span class="lbl">On label</span>{" ".join(fnd_parts)}</div>'
        "</div>"
    )


def render_fields(report: VerificationReport) -> None:
    for r in report.field_results:
        pill = _STATUS_PILL.get(r.status, "")
        meta_bits = []
        if r.expected and r.field != "Government Warning":
            meta_bits.append(f"Application: <b>{_esc(r.expected)}</b>")
        if r.found and r.field != "Government Warning":
            meta_bits.append(f"On label: <b>{_esc(r.found)}</b>")
        meta = "<div class='fc-meta'>" + " &nbsp;·&nbsp; ".join(meta_bits) + "</div>" if meta_bits else ""

        # For a failed Government Warning with wording drift, show a word-level
        # diff so the agent sees exactly what changed, not just that it did.
        diff = ""
        if (
            r.field == "Government Warning"
            and r.status == Status.FAIL
            and r.expected
            and r.found
            and r.expected.lower().split() != r.found.lower().split()
        ):
            diff = _warning_diff_html(r.expected, r.found)

        # Single-line HTML on purpose: a blank line inside the block (e.g. when
        # `meta` is empty) would terminate the HTML block and make Streamlit's
        # Markdown parser render the rest as a literal code block.
        st.markdown(
            f'<div class="field-card {_FC_CLASS.get(r.status, "")}">'
            f'<div class="fc-head">{pill}<span class="fc-title">{_esc(r.field)}</span></div>'
            f"{meta}"
            f'<div class="fc-detail">{_esc(r.detail)}</div>'
            f"{diff}"
            f"</div>",
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
        section_header("The label", "Step 1")

        choice = st.selectbox(
            "Start from a sample (optional)",
            ["(Upload my own)", *SAMPLE_LABELS.keys()],
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

        section_header("The application", "Step 2")
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
        section_header("Result", "Verdict")
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
    section_header("Verify many labels at once", "Batch")
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
        if st.button(f"▶  Run the {len(SAMPLE_LABELS)} bundled samples", width="stretch"):
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
            help="CSV + the sample label images, so you can test the 'bring your own' flow.",
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
                    "Issues": issues or ("none" if not r.report.error else r.report.error),
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
            with st.expander(f"{r.name}: {r.report.overall.value}"):
                render_verdict(r.report)
                render_fields(r.report)
                render_extraction(r.report)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="site-footer">'
    "<b>TTB Label Verification Console</b> · standalone proof-of-concept · "
    "Not an official government system · Images are processed in-memory and not stored.<br>"
    "Government Health Warning reference: 27 CFR § 16.21."
    "</div>",
    unsafe_allow_html=True,
)
