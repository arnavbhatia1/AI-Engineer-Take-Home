# 🥃 TTB Label Verifier

An AI-powered tool that checks whether an alcohol beverage **label's artwork
matches its COLA application** — and that the mandatory **Government Health
Warning** is present, correctly worded, and in all caps.

Built as a standalone proof-of-concept for the TTB Label Compliance take-home.
It reads a label image with a vision model, then applies deterministic,
auditable compliance rules and returns a clear **APPROVED / REJECTED / NEEDS
REVIEW** verdict — for one label or hundreds at a time.

> **🔗 Live app:** _paste your Streamlit URL here after deploying (see [Deploy](#deploy-free-in-5-minutes))._

---

## What it checks

For each label it verifies, field by field, against the application:

| Check | Rule |
| --- | --- |
| **Brand name** | Case- and punctuation-insensitive match. `STONE'S THROW` == `Stone's Throw`. Near-misses are flagged for **human review**, not auto-failed. |
| **Class / type** | Same fuzzy, human-in-the-loop matching. |
| **Alcohol content** | Numeric comparison (`45%` == `45% Alc./Vol. (90 Proof)`). Also sanity-checks that proof ≈ 2 × ABV. |
| **Net contents** | Quantity + unit, with unit normalisation (`750 mL` == `750ML`). |
| **Government Warning** | **Strict.** Must be present, **word-for-word** per 27 CFR 16.21, with the `GOVERNMENT WARNING:` heading in **all capitals**. Title-case, altered wording, or a missing statement all fail. |

The verdict rolls up as: any **FAIL → REJECTED**, otherwise any **REVIEW →
NEEDS REVIEW**, otherwise **APPROVED**.

---

## Try it in 30 seconds

The app ships with **five sample labels** that exercise every path. In **demo
mode** (no API key needed) they work fully offline:

| Sample | What's special | Expected verdict |
| --- | --- | --- |
| Old Tom Distillery | Clean, everything matches | ✅ APPROVED |
| Stone's Throw Gin | Label `STONE'S THROW` vs application `Stone's Throw` | ✅ APPROVED (judgment) |
| Silver Creek Vodka | Warning heading is title-case `Government Warning:` | ❌ REJECTED |
| Copper Ridge Rye | Label shows 40% but application says 45% | ❌ REJECTED |
| Harbor Light Rum | No Government Warning at all | ❌ REJECTED |

Open the deployed app → **Single label** tab → pick a sample → **Verify**.
Or the **Batch** tab → **Run the 5 bundled samples**.

---

## Run locally

Requires Python 3.10+.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) enable live AI reading of your own uploads
cp .env.example .env          # then edit .env and add your ANTHROPIC_API_KEY
#   ...or on Windows PowerShell:  copy .env.example .env

# 3. Run
streamlit run app.py
```

The app opens at `http://localhost:8501`.

- **No API key?** It runs in **demo mode** — the five bundled samples work
  fully; your own uploads show a "demo mode" note.
- **With an API key** (in `.env`, your shell, or `.streamlit/secrets.toml`)
  it reads any label you upload with the live vision model.

Get a key at <https://console.anthropic.com/>.

### Run the tests

Pure-logic tests — no network, no key required:

```bash
python -m unittest discover -s tests -v
```

### Regenerate the sample labels

```bash
python samples/generate_samples.py
```

---

## Deploy free in 5 minutes

**Streamlit Community Cloud** is the simplest free host for this app.

1. **Push this repo to GitHub** (public or private).
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. Click **Create app** → **Deploy a public app from GitHub**.
4. Select your repo/branch and set **Main file path** to `app.py`.
5. Click **Advanced settings → Secrets** and paste:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-your-key-here"
   # Optional, for the fastest turnaround toward the 5s target:
   # LABEL_MODEL = "claude-sonnet-5"
   ```
6. Click **Deploy**. In ~2 minutes you'll get a public URL like
   `https://your-app.streamlit.app` — paste it at the top of this README.

That's it. Graders open the URL and test live; the key stays in Streamlit's
encrypted secrets and is never in the repo.

> **Cost note:** each label reading is one small vision API call (a few cents
> at most). If you'd rather not attach a key, the deployed app still fully
> demonstrates the pass/fail logic on the five bundled samples in demo mode.

<details>
<summary>Alternative: Hugging Face Spaces</summary>

Create a new **Streamlit** Space, push these files, and add `ANTHROPIC_API_KEY`
under **Settings → Variables and secrets**. Same `app.py` entry point.
</details>

---

## Approach

**One principle drives the design: the model _reads_, the code _decides._**

```
        label image                      application data (COLA)
             │                                    │
             ▼                                    │
   ┌───────────────────┐                          │
   │ Vision extraction │  Claude vision + a single │
   │  (src/extraction) │  forced tool call → strict│
   └─────────┬─────────┘  structured JSON          │
             │  LabelExtraction (verbatim)         │
             ▼                                      ▼
        ┌──────────────────────────────────────────────┐
        │  Verification engine (src/verification.py)     │
        │  deterministic, unit-tested field rules +      │
        │  the exact Government-Warning check            │
        └───────────────────────┬────────────────────────┘
                                 ▼
                        VerificationReport
                  (APPROVED / REJECTED / NEEDS REVIEW)
```

Why split it this way:

- **The vision model does what it's uniquely good at** — reading text off
  imperfect artwork (glare, skew, odd fonts) and returning it *verbatim*. It is
  explicitly told **not** to normalise or "fix" anything.
- **The pass/fail judgment lives in plain Python** — so the rules are
  deterministic, auditable, and unit-tested (25 tests, no network). The
  Government-Warning check in particular is a real compliance rule, not a vibe:
  it enforces exact wording and the all-caps heading in code, and shows a
  word-level diff when the wording drifts.
- **Fuzzy where it should be, strict where it must be.** Brand/type matching
  tolerates case and punctuation and *escalates close calls to a human* (Dave's
  "STONE'S THROW is obviously the same thing" point). The warning statement is
  compared verbatim (Jenny's "it has to be exact" point).

**Speed.** Extraction is a single API round-trip that returns a small
structured record via a forced tool call — no extended thinking, minimal output
— to stay under the **5-second** target the stakeholders called out as
make-or-break. The measured time is shown on every result. The model is
configurable (`LABEL_MODEL`); the default is the most capable Opus tier, and a
faster tier (`claude-sonnet-5` / `claude-haiku-4-5`) trades a little accuracy
for lower latency if needed.

**Batch.** Peak-season importers submit hundreds at once (Janet's ask). Batch
mode fans the work across a small thread pool and streams live progress, then
offers a downloadable CSV report.

**UX.** Half the review team is 50+ and tech comfort varies. The UI is one
screen with big, colour-coded verdicts, plain-language explanations for every
finding, sample data one click away, and no hunting for buttons.

---

## Tools used

- **[Streamlit](https://streamlit.io)** — the UI and free hosting. Fastest path
  to a clean, deployable internal tool.
- **[Claude](https://www.anthropic.com/claude) vision** (Anthropic API) — reads
  the label. A single forced tool call returns strict structured JSON, which
  keeps latency low and parsing trivial.
- **[Pydantic](https://docs.pydantic.dev)** — validates the model's structured
  output.
- **[Pillow](https://python-pillow.org)** — generates the synthetic sample
  labels (offline, no external image services).
- **[pandas](https://pandas.pydata.org)** — CSV handling for batch mode.
- **Python standard library** — `difflib` for fuzzy/diff logic,
  `concurrent.futures` for batch parallelism. No heavyweight ML deps.

---

## Assumptions & trade-offs

Called out honestly, since the brief asks for them:

- **Cloud API vs. the agency firewall.** Marcus noted the network blocks many
  outbound domains, which sank the last vendor's ML endpoints. This prototype
  uses the cloud vision API because that's what makes a *free, publicly
  testable* deployment possible. The extraction layer
  (`src/extraction.py::ExtractionProvider`) is a deliberate seam: for a real
  on-prem deployment you'd drop in a self-hosted / Azure-tenant vision model
  behind the same interface **without touching the verification engine**. That
  separation is the point.
- **"Bold" is not verified.** The regulation also requires the warning to be
  **bold**. Boldness isn't reliably recoverable from an image via text
  extraction, so this build verifies presence, wording, and capitalisation
  (which *are* reliable) and treats bold as out of scope. It's flagged rather
  than silently ignored.
- **Application data is trusted input.** The tool verifies label-vs-application;
  it assumes the application values themselves are correct.
- **Batch throughput is bounded by API rate limits.** Concurrency is capped
  (`BATCH_MAX_WORKERS`, default 6) to stay safely under limits. A true
  300-at-once peak-season run would use the Message Batches API or a queue;
  that's noted as the next step, not built here.
- **Demo mode is sample-only.** With no API key, only the five bundled labels
  have canned readings (used for the offline demo and the tests). Real uploads
  need a key.
- **No storage / PII handling.** Per Marcus, nothing sensitive is stored — the
  app holds images in memory for the duration of a request only. A production
  version would need document-retention and PII controls.
- **Not integrated with COLA.** Standalone POC by design.

---

## Project structure

```
.
├── app.py                     # Streamlit UI (the only file that imports Streamlit)
├── src/
│   ├── config.py              # TTB constants, thresholds, model selection
│   ├── models.py              # ApplicationData, LabelExtraction, report types
│   ├── extraction.py          # vision providers: Claude + offline demo/mock
│   ├── verification.py        # the compliance engine (read-vs-decide lives here)
│   └── batch.py               # concurrent batch runner
├── samples/
│   ├── generate_samples.py    # renders the 5 sample labels with Pillow
│   ├── applications.csv        # matching application data
│   └── *.png                   # the 5 committed sample images
├── tests/                     # 25 unit + end-to-end (mock) tests, no network
├── docs/ASSIGNMENT.md         # the original take-home brief, preserved
├── requirements.txt
└── .streamlit/                # theme + secrets template
```

---

## License

Prototype for evaluation purposes.
