# 🥃 TTB Label Verifier

An AI-powered tool that checks whether an alcohol beverage label matches its
COLA application, including the mandatory Government Health Warning (present,
worded exactly as regulation requires, and in all caps).

It reads a label image with a vision model, applies deterministic and
auditable compliance rules, and returns a clear **APPROVED / REJECTED /
NEEDS REVIEW** verdict. It handles one label at a time or hundreds in a batch.

> **🔗 Live app:** https://arnav-bhatia-department-of-treasury-take-home.streamlit.app/

---

## What it checks

Each label is verified field by field against the application:

| Check | Rule |
| --- | --- |
| **Brand name** | Case- and punctuation-insensitive match. `STONE'S THROW` equals `Stone's Throw`. Near-misses are flagged for **human review**, not auto-failed. |
| **Class / type** | Same fuzzy, human-in-the-loop matching. |
| **Alcohol content** | Numeric comparison (`45%` equals `45% Alc./Vol. (90 Proof)`). Also sanity-checks that proof is about twice the ABV. |
| **Net contents** | Quantity plus unit, with unit normalisation (`750 mL` equals `750ML`). |
| **Government Warning** | **Strict.** Must be present, **word-for-word** per 27 CFR 16.21, with the `GOVERNMENT WARNING:` heading in **all capitals**. Title-case, altered wording, or a missing statement all fail. |

The verdict rolls up simply: any **FAIL** means **REJECTED**; otherwise any
**REVIEW** means **NEEDS REVIEW**; otherwise **APPROVED**.

---

## Try it in 30 seconds

The app ships with **six sample labels** that exercise every path. They work
fully even in demo mode (no API key):

| Sample | What's special | Expected verdict |
| --- | --- | --- |
| Old Tom Distillery | Clean, everything matches | ✅ APPROVED |
| Stone's Throw Gin | Label says `STONE'S THROW`, application says `Stone's Throw` | ✅ APPROVED (judgment) |
| Silver Creek Vodka | Warning heading is title-case `Government Warning:` | ❌ REJECTED |
| Copper Ridge Rye | Label shows 40% but the application says 45% | ❌ REJECTED |
| Harbor Light Rum | No Government Warning at all | ❌ REJECTED |
| Golden Gate Brandy | Warning creatively reworded; the result shows a **word-level diff** of exactly what changed | ❌ REJECTED |

Open the live app, go to the **Single label** tab, pick a sample, and press
**Verify label**. Or open the **Batch** tab and press **Run the 6 bundled
samples**.

---

## Run locally

Requires Python 3.10+.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) enable live AI reading of your own uploads
cp .env.example .env    # then edit .env and add your ANTHROPIC_API_KEY
#   on Windows PowerShell:  copy .env.example .env

# 3. Run
streamlit run app.py
```

The app opens at `http://localhost:8501`.

- **No API key?** The app runs in demo mode: the six bundled samples work
  fully, and your own uploads show a demo-mode note.
- **With an API key** (in `.env`, your shell, or `.streamlit/secrets.toml`)
  it reads any label you upload with the live vision model. Get a key at
  <https://console.anthropic.com/>.

### Run the tests

Pure-logic tests, no network or key required:

```bash
python -m unittest discover -s tests -v
```

The suite includes an integration test that runs the full bundled-samples
batch end to end. CI (`.github/workflows/ci.yml`) runs it all on every push
and pull request, then boots a real Streamlit server and confirms it comes up
healthy, the same way Streamlit Community Cloud runs the app.

### Regenerate the sample labels

```bash
python samples/generate_samples.py
```

---

## Deployment

The live app above runs on **Streamlit Community Cloud** (free tier). To
deploy your own copy:

1. Push this repo to GitHub.
2. Go to <https://share.streamlit.io>, sign in with GitHub, and click
   **Create app**.
3. Select the repo and branch, and set **Main file path** to `app.py`.
4. Under **Advanced settings → Secrets**, paste:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-your-key-here"
   # Optional: a faster model tier for the quickest results
   # LABEL_MODEL = "claude-sonnet-5"
   ```
5. Click **Deploy**. A public URL is ready in about two minutes.

The key lives in Streamlit's encrypted secrets and is never in the repo.
Without a key the deployed app still fully demonstrates the pass/fail logic
on the six bundled samples in demo mode.

> **Cost note:** each label reading is one small vision API call, a few cents
> at most.

<details>
<summary>Alternative host: Hugging Face Spaces</summary>

Create a new **Streamlit** Space, push these files, and add
`ANTHROPIC_API_KEY` under **Settings → Variables and secrets**. Same `app.py`
entry point.
</details>

---

## Approach

One principle drives the design: **the model reads, the code decides.**

1. **Read.** The label image goes to Claude vision in a single forced tool
   call that returns strict structured JSON (`src/extraction.py`). The model
   is told to transcribe the label *verbatim* and never to correct or
   normalise what it sees.
2. **Decide.** Deterministic, unit-tested Python rules compare the reading to
   the application (`src/verification.py`). All pass/fail judgment lives
   here, in auditable code, never in the model prompt.
3. **Report.** Each field gets a PASS / FAIL / REVIEW result with a
   plain-language explanation, rolled up into the overall verdict.

Why this split matters:

- **The vision model does what it's uniquely good at:** reading text off
  imperfect artwork (glare, skew, odd fonts) and returning it verbatim.
- **The compliance rules stay deterministic and auditable.** The
  Government Warning check enforces the exact wording and the all-caps
  heading in code (32 tests, no network needed), and produces a word-level
  diff when the wording drifts.
- **Fuzzy where it should be, strict where it must be.** Brand and type
  matching tolerates case and punctuation and escalates close calls to a
  human, because "STONE'S THROW" on a label is obviously the same brand as
  "Stone's Throw" on an application. The warning statement, by contrast, is
  compared word for word because the regulation requires it.

**Speed.** Extraction is a single API round-trip with no extended thinking
and minimal output, sized to stay under the 5-second turnaround that makes a
tool like this usable in practice. Oversized uploads such as raw phone photos
are downscaled client-side first (`src/imaging.py`): beyond ~1568px the model
gains nothing, larger files only add upload time and cost, and anything past
the API's 5 MB image cap would fail outright. The measured time is shown on
every result. The model is configurable via `LABEL_MODEL`; the default is the
most capable tier, and a faster tier (`claude-sonnet-5` or `claude-haiku-4-5`)
trades a little accuracy for lower latency.

**Explainability.** When the warning wording drifts from the mandate, the
result shows a word-level diff: the mandated text with the required words
highlighted, and the label's text with the substituted words struck through.
The reviewer sees exactly what to cite in the rejection, not just that it
failed.

**Batch.** Peak season brings hundreds of applications at once. Batch mode
fans the work across a thread pool, streams live progress, and produces a
downloadable CSV report.

**UX.** Built for a review team with a wide range of tech comfort: one
screen, large colour-coded verdicts, plain-language explanations for every
finding, and sample data one click away.

---

## Tools used

- **[Streamlit](https://streamlit.io)**: the UI and free hosting. The fastest
  path to a clean, deployable internal tool.
- **[Claude](https://www.anthropic.com/claude) vision** (Anthropic API):
  reads the label. A single forced tool call returns strict structured JSON,
  which keeps latency low and parsing trivial.
- **[Pydantic](https://docs.pydantic.dev)**: validates the model's structured
  output.
- **[Pillow](https://python-pillow.org)**: image downscaling, plus generating
  the synthetic sample labels (offline, no external image services).
- **[pandas](https://pandas.pydata.org)**: CSV handling for batch mode.
- **Python standard library**: `difflib` for fuzzy matching and diffs,
  `concurrent.futures` for batch parallelism. No heavyweight ML dependencies.

---

## Assumptions and trade-offs

- **Cloud API vs. a locked-down agency network.** Government networks often
  block outbound traffic to ML endpoints. This prototype uses a cloud vision
  API because that is what makes a free, publicly testable deployment
  possible. The extraction layer (`ExtractionProvider` in
  `src/extraction.py`) is a deliberate seam: a real on-prem deployment would
  drop in a self-hosted or Azure-tenant vision model behind the same
  interface without touching the verification engine.
- **Bold is not verified.** The regulation also requires the warning heading
  to be bold. Boldness is not reliably recoverable from an image via text
  extraction, so this build verifies presence, wording, and capitalisation
  (which are reliable) and documents bold as a known limitation.
- **Application data is trusted input.** The tool verifies label against
  application; it assumes the application values themselves are correct.
- **Batch throughput is bounded by API rate limits.** Concurrency is capped
  (`BATCH_MAX_WORKERS`, default 6). A true 300-at-once peak-season run would
  use the Message Batches API or a queue; that is the documented next step,
  not built here.
- **Demo mode covers the samples only.** Without an API key, only the six
  bundled labels have canned readings (used for the offline demo and tests).
  Real uploads need a key.
- **No storage or PII handling.** Nothing is stored; images are held in
  memory only for the duration of a request. A production version would need
  document-retention and PII controls.
- **Not integrated with COLA.** Standalone proof-of-concept by design.

---

## Project structure

```
.
├── app.py                      # Streamlit UI (the only file that imports Streamlit)
├── src/
│   ├── config.py               # TTB constants, thresholds, model selection
│   ├── models.py               # ApplicationData, LabelExtraction, report types
│   ├── extraction.py           # vision providers: Claude + offline demo/mock
│   ├── imaging.py              # client-side downscale (speed + API size cap)
│   ├── verification.py         # the compliance engine (all pass/fail rules)
│   └── batch.py                # concurrent batch runner
├── samples/
│   ├── generate_samples.py     # renders the 6 sample labels with Pillow
│   ├── applications.csv        # matching application data
│   └── *.png                   # the 6 committed sample images
├── tests/                      # 32 unit + integration tests, no network needed
├── .github/workflows/ci.yml    # CI: tests + real-server boot check on every push/PR
├── docs/ASSIGNMENT.md          # the original take-home brief, preserved
├── requirements.txt
└── .streamlit/                 # theme + secrets template
```

---

## License

Prototype built for evaluation purposes.
