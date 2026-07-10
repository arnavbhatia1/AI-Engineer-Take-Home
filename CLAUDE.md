# CLAUDE.md — TTB Label Verifier

AI-powered alcohol-label compliance checker. Reads a label image with Claude
vision, then applies deterministic compliance rules and returns an
APPROVED/REJECTED/NEEDS-REVIEW verdict. Streamlit UI, deployable free on
Streamlit Community Cloud.

## Tech stack
- Python 3.10+
- Streamlit (UI + hosting)
- Anthropic Claude vision API (label reading, via a single forced tool call)
- Pydantic (structured-output validation), Pillow (sample generation), pandas (batch CSV)
- Standard lib: `difflib` (fuzzy/diff), `concurrent.futures` (batch)

## Commands
- Install: `pip install -r requirements.txt`
- Run: `streamlit run app.py`
- Test: `python -m unittest discover -s tests -v`
- Regenerate samples: `python samples/generate_samples.py`
- Deploy: push to GitHub → share.streamlit.io → main file `app.py` → add `ANTHROPIC_API_KEY` in Secrets

## Configuration (env vars / Streamlit secrets)
- `ANTHROPIC_API_KEY` — required for live reading; absent ⇒ offline demo mode
- `LABEL_MODEL` — vision model, default `claude-opus-4-8` (use `claude-sonnet-5`/`claude-haiku-4-5` for lower latency)
- `BATCH_MAX_WORKERS` — batch concurrency, default 6

## Architecture — "the model reads, the code decides"
- `src/extraction.py` — vision provider seam. `ClaudeProvider` (live) and
  `MockProvider` (offline demo + tests). New backends (e.g. on-prem model for
  the firewall constraint) drop in here without touching verification.
- `src/verification.py` — the compliance engine. Deterministic, unit-tested
  field matchers + the strict Government-Warning check. All pass/fail logic lives
  here, never in the model prompt.
- `src/models.py` — `ApplicationData`, `LabelExtraction` (Pydantic), report types.
- `src/config.py` — TTB constants (canonical warning text), thresholds, model.
- `src/batch.py` — concurrent batch runner.
- `app.py` — the ONLY file that imports Streamlit; keep UI logic out of `src/`.

## Conventions
- `src/` stays UI-agnostic (no Streamlit imports) so it's testable headless.
- The canonical Government Warning (27 CFR 16.21) is the single source of truth
  in `config.py` — compliance rules compare against it, never re-typed inline.
- Extraction is verbatim: the model must not normalise/correct label text; the
  engine owns all normalisation and judgment.
- Sample PNGs are committed so the deployed app needs no fonts at runtime;
  regenerate via the script if sample content changes.
- Every behavioral change updates the tests and this file in the same commit.

## Deliverables (take-home)
- Source: this repo. Docs: `README.md` (setup/run/deploy/approach/assumptions),
  original brief preserved at `docs/ASSIGNMENT.md`.
- Deployed URL goes at the top of `README.md` after deploy.
