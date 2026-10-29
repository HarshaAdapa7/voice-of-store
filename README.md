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
4. **States precision**: out-of-sample, with intervals (`out/validation.md`).
5. **Runs as a secure web demo** (`FULL_CODE/serve.py`): regional briefs, emerging-issue panel with weekly chart and evidence,
   a "try a comment" box with the key terms behind the prediction, the precision statement, and cross-channel de-duplication
   (reports of one event at the same store and type within 72 hours are shown as one incident). Flags can be downloaded as CSV (formula-injection safe). A **Stores** tab gives a
   per-store page (this week vs last, weekly trend, flags, top issues with quotes), and an **Ask** tab is a store assistant
   ("How is Kothrud doing?", "Any emerging issues in South?", "Who handles freezer problems?", "classify: ..."). The assistant
   is rule-based, not an LLM: it only reads this project's own data, cites its source, and says so when it cannot answer.

Users: regional ops heads and function owners (Store Ops, Supply Chain, Merchandising, Digital, HR).

## How to run

Python 3.9 or newer (tested on 3.13). No internet and no API keys are needed at run time.

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

## Causal (as-of) statement

Each week's flags use only rows with `created_at` before the next Monday 00:00 (up to that week's Sunday 23:59:59). The
classifier for that week is trained only on public labels of rows inside that window. The detector replays earlier weeks
inside the same run to rebuild its state. No dates, week numbers, store ids or feedback ids are hard-coded; all data files are
read from the folder holding `--feedback`. Two tests check this: appending or removing later rows leaves a week's flags
unchanged, and a disguised copy (new ids, dates shifted by 7 weeks) gives the same flags after mapping the ids back.

## Security

The web demo is read-only over synthetic data plus two stateless POST endpoints (classify and the rule-based assistant, 300-character questions, own rate limit): no accounts, cookies, database, uploads
or outbound calls. Controls (each has a test in `tests/test_web.py`): strict Content-Security-Policy with no inline script,
DOM built with `textContent` only, escaped printable brief, host allow-list (DNS rebinding), origin and fetch-metadata checks plus
JSON-only POST (CSRF), allow-lists for every query value, fixed static-file table (no path traversal), body and text size
limits, per-client rate limits with bounded memory, optional login (salted scrypt hash, failed-login limiter) and constant-time API key, generic errors with request ids,
logs without feedback text, contact details masked before display, HSTS when behind HTTPS, no pickle anywhere, non-root
container, `ruff` with the bandit rules. Full table, configuration and the honest list of what it does **not** do (a single shared login, no TLS termination, no independent penetration test): `FULL_CODE/SECURITY.md`. With the server running, `python FULL_CODE/scripts/security_probe.py` fires 30 attacks at it (30/30 refused or neutralised in the build check). Before exposing it, run
`pip-audit -r FULL_CODE/requirements.txt` (needs internet) and put it behind a TLS-terminating reverse proxy.

## Results (what was measured, and what it means)

| Check | Result | Note |
|---|---|---|
| Time-split validation (train weeks 1-9, test labelled rows of weeks 10-13) | classification 0.914: issue macro-F1 0.899, severity weighted-F1 0.913, actionable F1 0.944 | Out of sample and forward in time; the best local proxy |
| Model choice (issue macro-F1, mean of three forward-in-time splits) | logistic regression 0.849, linear SVM 0.881, linear SVM with min_df=1 0.893 (chosen) | Same features and labels; the SVM won on every split. Its confidence is a softmax of margins: a ranking score, not a calibrated probability |
| Organisers' baseline (keyword rules, from the pack README) | classification about 0.58, lead 0.33 on the training truth | Our worked-example lead is 0.50 and our time-split classification 0.914; different protocols, so read as direction, not a like-for-like gap |
| Precision statement (time-split) | Marked actionable: 95.2% truly (95% interval 93.1%-96.7%); marked actionable and high/critical: 97.0% (92.6%-98.8%) | Sample over-represents rare types; not the full-stream rate |
| Worked example (IT17, ST-D69EG) | first valid flag 2026-05-11, naive detector 2026-05-18: lead +1 week | One incident only; none of the three hidden ones are known |
| Flag volume on the test half | 24 flags in 13 weeks (1.85 a week), budget is 3 | Planted incidents will add a few |
| Synthetic injection grid (120 plants, three shapes) | mean lead score about 0.49 (about one week earlier than the naive rule) | Synthetic shapes, not a forecast |
| `evaluate.py` on the training truth | 0.80 primary | **Inflated**: submission rows that have a public label carry that label, so classification scores 1.0 on them. Use the time-split row, not this one, to judge the classifier |

## AI usage

- **In the app (detector, classifier, web demo):** no LLM, no external AI API, no downloaded model. The classifier is a scikit-learn linear SVM trained at
  run time from the public labels; nothing is pickled.
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
- Not tested on Python 3.9 specifically (code avoids newer syntax); tested on 3.13 only. The synthetic data means privacy
  rules (DPDP) are design discipline here, not a live obligation.
- Next steps: a reporter-level key for true corroboration, store-level seasonality, an encoder comparison, analyst feedback loop.
