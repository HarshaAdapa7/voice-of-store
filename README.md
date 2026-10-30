# 120 · R5: Voice-of-Store Engine

Team Code Titans (team 120), problem R5. Turns four noisy feedback channels into a weekly action list per region, routed to
an owner, with early warning for issues that are small but rising at one store.

## What it does

Saffron Retail's head office receives reviews, in-app comments, store shift notes and call-centre transcripts in English,
Hinglish, Tamil and Marathi (all in Latin script). This project:

1. **Classifies every record** with an issue type (30 operational types plus 3 non-issues), a severity and an actionable flag.
   Severity is `max(policy floor, model)`: safety, allergen, hygiene and misconduct types are never below `high`; payment
   failures are at least `medium`. Records that cannot be routed (no store, not an order/app/payment issue) are never actionable.
2. **Detects emerging issues**: reports are counted per (store, issue type, week), normalised by store size, shrunk toward the
   chain-wide rate, and tracked with a sequential likelihood-ratio statistic. A flag needs at least 2 reports in the week and
   cites the highest-confidence evidence. At most 3 flags a week.
3. **Writes a one-page brief per region per week** (top 5 issues, evidence quotes, affected stores, trend arrow, owner, severity,
   evidence tier, action window) and states the escalation rule on every page.
4. **States precision** and evaluates itself in a full report (`out/report.html`, also at `/report` in the demo and as a printable page): precision of escalations by confidence and by owner with intervals, safety-type recall, weakest issue types and mix-ups, severity confusion, per-channel quality, detector lead on the public worked incident, de-duplication statistics, a week-by-week table and a plain list of limits. Written by `python FULL_CODE/main.py briefs`.
5. **Runs as a secure web demo** (`FULL_CODE/serve.py`): regional briefs, emerging-issue panel with weekly chart and evidence,
   a "try a comment" box with the key terms behind the prediction, the precision statement, and cross-channel de-duplication
   (reports of one event at the same store and type within 72 hours are shown as one incident). Flags can be downloaded as CSV (formula-injection safe). A **Stores** tab gives a
   per-store page (this week vs last, weekly trend, flags, top issues with quotes), and an **Ask** tab is a store assistant
   ("How is Kothrud doing?", "Any emerging issues in South?", "Who handles freezer problems?", "classify: ..."). The assistant
   is rule-based, not an LLM: it only reads this project's own data, cites its source, and says so when it cannot answer.

Users: regional ops heads and function owners (Store Ops, Supply Chain, Merchandising, Digital, HR).

## How to run

**Python 3.12 or newer** (tested on 3.13; the pinned pandas 3 and numpy 2.5 do not install on older Pythons). The detector, classifier, briefs, and local assistant need no internet or API keys. Optional Gemini summaries and approved SMTP notifications require their own configuration.

**Step 0, before anything else: add the data.** The zip does not contain the pack's data files (they are large and git-ignored by design). Create a folder named `data` next to `FULL_CODE` and copy into it `feedback.csv`, `feedback_labels_train.csv`, `store_master.csv`, `issue_taxonomy.csv`, `week_calendar.csv` and `emerging_incidents_train.csv` from the organisers' pack. Without them the commands stop with `error: missing data file: ...`; the tests skip the data-dependent cases.

Quick start in VS Code: open the project folder, open a terminal (Terminal > New Terminal), then

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell; on macOS/Linux: source .venv/bin/activate
pip install -r FULL_CODE/requirements.txt
```

and choose `.venv` as the interpreter (Ctrl+Shift+P > "Python: Select Interpreter"). Then the commands below.

```bash
pip install -r FULL_CODE/requirements.txt
# put the pack's data files (feedback.csv, feedback_labels_train.csv, store_master.csv, issue_taxonomy.csv,
# week_calendar.csv, emerging_incidents_train.csv) in ./data  (the folder is git-ignored)
python FULL_CODE/make_submission.py        # writes submission/ (about 3.5 minutes)
python FULL_CODE/make_briefs.py            # writes out/briefs/<week>/<region>.html and out/validation.md
python FULL_CODE/tools/evaluate.py --submission submission/R5_predictions.csv --truth data/feedback_labels_train.csv \
    --feedback data/feedback.csv --stores data/store_master.csv
python FULL_CODE/scripts/injection_grid.py --data data     # synthetic-incident sanity harness
```

Web demo (needs Flask, in `requirements.txt`; the detector itself does not):

```bash
python FULL_CODE/make_briefs.py            # once, writes out/validation.json used by the Precision tab
python FULL_CODE/serve.py                  # about 20 s to load, then open http://127.0.0.1:8000
```

It listens on 127.0.0.1 only. To expose it, read **Security** below and `FULL_CODE/SECURITY.md`, install `waitress`, and set
`R5_ALLOWED_HOSTS`. A `FULL_CODE/Dockerfile` is provided (data is mounted, never baked in). Two-minute walkthrough:
`FULL_CODE/DEMO_SCRIPT.md`.

One week of the detector (this is the command in `submission/detector_cmd.txt`):

```bash
python FULL_CODE/detect.py --feedback data/feedback.csv --as-of 2026-07-13 --out week.csv
```

Environment variables: none for the detector and briefs; the web demo reads `R5_ALLOWED_HOSTS`, `R5_API_KEY`, `R5_HTTPS`,
`R5_TRUST_PROXY` (see `FULL_CODE/.env.example`). `FULL_CODE/tools/evaluate.py` is the organisers' scorer, included
unmodified.

## How to run the tests

```bash
cd FULL_CODE && python -m pytest -q        # detector, classifier, web security and API tests; data-dependent tests skip if ./data is absent
ruff check .                               # lint
python FULL_CODE/scripts/package_check.py  # layout, rules and README checks (run from the project root)
```

## Architecture

```
FULL_CODE/
  detect.py            detector entry point (one as-of week)
  make_submission.py   predictions for all rows + flags week by week + detector_cmd.txt
  make_briefs.py       regional HTML briefs + validation.md / validation.json
  serve.py             web demo entry point (Flask; waitress when installed)
  SECURITY.md  DEMO_SCRIPT.md  Dockerfile
  src/voice_of_store/
    io.py        read data from one folder, validate output files
    text.py      light normalisation + channel prefix
    stores.py    store resolver (recorded id, else a single named locality; same rule as the scorer)
    classify.py  TF-IDF (char 2-5 + word 1-2) + class-balanced linear SVM (three heads: issue type, severity, actionable); severity policy; actionable gates
    detect.py    exposure-normalised Gamma-Poisson shrinkage + sequential LLR statistic, cooldown, flag cap
    evidence.py  re-implements the evidence checks (a)-(d) so cited ids pass
    pipeline.py  glue used identically by detect.py and make_submission.py
    routing.py   owner, action window, written escalation rule
    brief.py     ranking (severity, evidence tier, volume, stores) and the HTML page
    report.py    time-split validation, precision statement
    dedup.py     cross-channel de-duplication into incidents (display only)
    web/         security.py (headers, host/origin checks, rate limits, API key), server.py (routes, allow-lists),
                 state.py (data + model loaded once, read-only), static/ (CSP-safe page: no inline script or style)
  scripts/       injection_grid.py, package_check.py
  tests/         unit and end-to-end tests
  tools/         evaluate.py (organisers' scorer, unmodified)
```

Data flow: read folder → resolve stores → train on public labels dated before the cutoff → predict rows → weekly counts →
statistic → flags with evidence → briefs.

## Performance (measured, `python FULL_CODE/scripts/benchmark.py`)

| Measure | Result |
|---|---|
| Jury detector, one week, 39,769 rows, no internet | about 20 s (limit 600 s) |
| Whole submission (26 weeks, classifier retrained as of each week) | about 3 minutes |
| Web start-up (load, train, classify every row) | about 19 s; briefs and report pre-computed in the background about 27 s later |
| Request latency, in process | brief, flags, store, report: under 1 ms median; assistant 1.6 ms; classify a comment about 30 ms |
| Responses | gzip for text over 1 KiB, bounded caches, constant-time lookups from indexes built at start-up |

## Quality evidence

| Measure | Result |
|---|---|
| Tests | 148 tests in 7 files (`cd FULL_CODE && python -m pytest -q`); acceptance tests are named after the requirements (`tests/test_requirements.py`) |
| Line coverage of `src/` | 95.0% overall (`python FULL_CODE/scripts/line_coverage.py`, standard library only) |
| Static checks | `ruff` (E, F, W, I, B, UP, S) and `mypy` clean |
| Rubric self-audit | `python FULL_CODE/scripts/self_audit.py --full` scores the repository against the pack rules, the requirement list and the guidelines (our own rubric, not the jury's) |
| One-page briefs | `python FULL_CODE/scripts/check_brief_pages.py`: all 65 briefs print on one A4 page |
| Traceability | `FULL_CODE/REQUIREMENTS_TRACEABILITY.md` maps every requirement to code and a test |

## Reports (what each output is for)

| Output | Where | Purpose |
|---|---|---|
| Weekly brief per region | `out/briefs/<week>/<region>.html`, `/brief` | Top 5 issues (plus any safety type beyond them), quotes with time, stores, trend, owner, severity, status, next step, escalation rule |
| Evaluation report | `out/report.html`, `/report`, Precision tab | Precision statement, escalation precision, safety recall, weak spots, detection example, de-duplication, week by week, limits |
| Flags for the week | Emerging tab, `/api/export` (CSV) | What changed, where, how quickly, evidence, next step |
| Scored files | `submission/` | `R5_predictions.csv`, `R5_emerging_flags.csv`, `detector_cmd.txt` |

## Requirement coverage (FR-07 to FR-11)

| Requirement | Where it is done |
|---|---|
| FR-07 high severity regardless of volume; dedicated escalation; allegation is not a verified incident | `routing.py`: safety, allergen, hygiene, misconduct types never below `high`, action window "same day", written rule on every brief. Safety types are never cut by the top-5 limit (shown as "safety escalation"). Every entry carries a status such as "Unverified serious allegation: a single source, not confirmed" and no wording presents a report as fact (`test_status_never_presents_a_report_as_established_fact`). |
| FR-08 evidence, counts, stores, channels, timing, independence, confidence | Each brief entry shows quotes with channel and time, report count, incidents (copies within 72 hours count once), channel split, stores, first and latest report, a confidence score and the verification tier. A copy of one text does not corroborate itself (`_tier`). |
| FR-09 owner, severity, escalation rule, evidence, recommended next step | Owner comes from the supplied taxonomy; each issue shows severity, the action window, evidence and a recommended next step (specific for each safety type, by owner otherwise). |
| FR-10 unverified feedback and store size | Every page says feedback is unverified. The detector divides by each store's average weekly footfall; briefs show reports per 10,000 weekly visits. Limitation disclosed on the page: only average footfall exists, not per-store transaction counts, so rates are approximate. |
| FR-11 low-volume emerging issues | The detector flags a store rising above its own normal rate with as few as 2 reports, outside the top 5. Each flag explains what changed (this week against usual), where (store), how quickly (first and latest report, days, recent weeks), whether it is local or chain-wide, and cites the evidence. |

## Causal (as-of) statement

Each week's flags use only rows with `created_at` before the next Monday 00:00 (up to that week's Sunday 23:59:59). The
classifier for that week is trained only on public labels of rows inside that window. The detector replays earlier weeks
inside the same run to rebuild its state. No dates, week numbers, store ids or feedback ids are hard-coded; all data files are
read from the folder holding `--feedback`. Two tests check this: appending or removing later rows leaves a week's flags
unchanged, and a disguised copy (new ids, dates shifted by 7 weeks) gives the same flags after mapping the ids back.

## Security

The web demo is read-only over synthetic data plus stateless POST endpoints for classify, the assistant, and approved alert delivery. Optional Gemini receives only a redacted deterministic answer, never a question or raw feedback; optional SMTP delivery uses TLS and requires per-batch human approval. Controls (each has a test in `tests/test_web.py`): strict Content-Security-Policy with no inline script,
DOM built with `textContent` only, escaped printable brief, host allow-list (DNS rebinding), origin and fetch-metadata checks plus
JSON-only POST (CSRF), allow-lists for every query value, fixed static-file table (no path traversal), body and text size
limits, per-client rate limits with bounded memory, optional login (salted scrypt hash, failed-login limiter) and constant-time API key, generic errors with request ids,
logs without feedback text, contact details masked before display, HSTS when behind HTTPS, no pickle anywhere, non-root
container, `ruff` with the bandit rules. Full table, configuration and the honest list of what it does **not** do (a single shared login, no TLS termination, no independent penetration test): `FULL_CODE/SECURITY.md`. With the server running, `python FULL_CODE/scripts/security_probe.py` fires 32 attacks at it (32/32 refused or neutralised in the build check). Before exposing it, run
`pip-audit -r FULL_CODE/requirements.txt` (needs internet) and put it behind a TLS-terminating reverse proxy.

## Results (what was measured, and what it means)

| Check | Result | Note |
|---|---|---|
| Time-split validation (train weeks 1-9, test labelled rows of weeks 10-13) | classification 0.914: issue macro-F1 0.899, severity weighted-F1 0.913, actionable F1 0.944 | Out of sample and forward in time; the best local proxy |
| Model choice (issue macro-F1, mean of three forward-in-time splits) | logistic regression 0.849, linear SVM 0.881, linear SVM with min_df=1 0.893 (chosen) | Same features and labels; the SVM won on every split. Its confidence is a softmax of margins: a ranking score, not a calibrated probability |
| Organisers' baseline (keyword rules, from the pack README) | classification about 0.58, lead 0.33 on the training truth | Our worked-example lead is 0.50 and our time-split classification 0.914; different protocols, so read as direction, not a like-for-like gap |
| Safety-boost experiment (three forward splits) | Adding a margin bonus to the safety types raised safety recall from 90.0% to 92.1% (bonus 0.1) or 96.0% (0.2), but issue macro-F1 fell from 0.897 to 0.890 and 0.879, and safety precision fell from 92.6% to 83.9% and 74.8% | Not adopted: the score weights macro-F1 and the extra alarms would be mostly false. A low-confidence "safety watch" list was also tried: at a margin of 0.3 it finds 6 of the 8 missed reports but is only 20% precise and lists about 5% of all records. Left as a documented limitation |
| Safety-type recall (time-split, 84 truly safety-type actionable records) | 74 caught (88.1%, 95% interval 79.5% to 93.4%) | The main known weakness; 6 were predicted as a non-safety type and 4 as not actionable. Listed in `out/report.html` |
| Precision statement (time-split) | Marked actionable: 95.2% truly (95% interval 93.1%-96.7%); marked actionable and high/critical: 97.0% (92.6%-98.8%) | Sample over-represents rare types; not the full-stream rate |
| Worked example (IT17, ST-D69EG) | first valid flag 2026-05-11, naive detector 2026-05-18: lead +1 week | One incident only; none of the three hidden ones are known |
| Flag volume on the test half | 24 flags in 13 weeks (1.85 a week), budget is 3 | Planted incidents will add a few |
| Synthetic injection grid (120 plants, three shapes) | mean lead score about 0.49 (about one week earlier than the naive rule) | Synthetic shapes, not a forecast |
| `evaluate.py` on the training truth | 0.80 primary | **Inflated**: submission rows that have a public label carry that label, so classification scores 1.0 on them. Use the time-split row, not this one, to judge the classifier |

## AI usage

- **Local path:** detector, classifier, briefs, and rule-based assistant run locally. The classifier is a scikit-learn linear SVM trained at runtime from public labels; nothing is pickled.
- **Optional assistant summary:** when `GEMINI_API_KEY` is configured and the user selects Gemini mode, the app sends only the redacted deterministic response to Gemini. It never sends the question or raw feedback. The local answer remains visible and authoritative; Gemini output is labeled as generated and may be unavailable.
- **Optional alerts:** SMTP sends only after an operator reviews the recipients and current alert batch and confirms that batch. The message omits feedback quotes. Configure it through environment variables in `FULL_CODE/.env.example`; do not commit credentials.
- **While building:** Claude (Anthropic) was used as an AI coding and research assistant for planning, code, tests, the web
  demo, the security review and this README. Google AI Studio may be used for further development; any such use is added here. The team reviewed the code; every member should be able to explain it.

## Pre-built and third-party code

- Written for this hackathon: everything in `FULL_CODE/` except `tools/`.
- `FULL_CODE/tools/evaluate.py`: the organisers' scorer, unmodified, from the R5 pack.
- Libraries: numpy, pandas, scikit-learn, scipy (BSD); Flask, Werkzeug, Jinja2, MarkupSafe, itsdangerous, click, blinker (BSD-3);
  waitress (ZPL 2.1); pytest (MIT), ruff (MIT), mypy (MIT) for development.
- The pack's baseline was read for its interface only; none of its code was copied. No Round 1 code was reused.

## Limitations

- Lead time: one worked example is the only incident visible; thresholds were tuned on it, a synthetic grid and clean history.
  The three hidden incidents may look different.
- Flags need at least 2 reports in the incident week, so an incident whose first week has one report cannot be caught that week.
- Severity is the weakest label (ambiguous texts). The labelled sample is small (3,000) and not the stream's distribution.
- Cross-channel de-duplication is a stated heuristic (same store, same type, each report within 72 hours of the previous one).
  There is no duplicate ground truth, so it is not measured, and two real events at one store inside 72 hours merge. It is display
  only: it never changes the counts that feed the detector.
- The web demo has one shared login at most and no TLS (see Security); `waitress` was not installable where this was built, so the
  production-server path is reviewed but not run there; the Dockerfile was written but not built there.
- Language handling relies on character n-grams, so unseen transliteration spellings and very short texts are the main error
  source. A multilingual encoder was not tried.
- Tested on Python 3.13 only; 3.12 is the stated minimum because the pinned libraries need it. The synthetic data means privacy
  rules (DPDP) are design discipline here, not a live obligation.
- Next steps: a reporter-level key for true corroboration, store-level seasonality, an encoder comparison, analyst feedback loop.
