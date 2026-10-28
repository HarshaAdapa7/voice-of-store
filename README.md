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

Users: regional ops heads and function owners (Store Ops, Supply Chain, Merchandising, Digital, HR).

## How to run

Python 3.9 or newer (tested on 3.13). No internet and no API keys are needed at run time.

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

One week of the detector (this is the command in `submission/detector_cmd.txt`):

```bash
python FULL_CODE/detect.py --feedback data/feedback.csv --as-of 2026-07-13 --out week.csv
```

Environment variables: none (see `FULL_CODE/.env.example`). `FULL_CODE/tools/evaluate.py` is the organisers' scorer, included
unmodified.

## How to run the tests

```bash
cd FULL_CODE && python -m pytest -q        # 12 tests, about a minute; data-dependent tests skip if ./data is absent
ruff check .                               # lint
python FULL_CODE/scripts/package_check.py  # layout, rules and README checks (run from the project root)
```

## Architecture

```
FULL_CODE/
  detect.py            detector entry point (one as-of week)
  make_submission.py   predictions for all rows + flags week by week + detector_cmd.txt
  make_briefs.py       regional HTML briefs + validation.md
  src/voice_of_store/
    io.py        read data from one folder, validate output files
    text.py      light normalisation + channel prefix
    stores.py    store resolver (recorded id, else a single named locality; same rule as the scorer)
    classify.py  TF-IDF (char 2-5 + word 1-2) + class-balanced logistic regression; severity policy; actionable gates
    detect.py    exposure-normalised Gamma-Poisson shrinkage + sequential LLR statistic, cooldown, flag cap
    evidence.py  re-implements the evidence checks (a)-(d) so cited ids pass
    pipeline.py  glue used identically by detect.py and make_submission.py
    routing.py   owner, action window, written escalation rule
    brief.py     ranking (severity, evidence tier, volume, stores) and the HTML page
    report.py    time-split validation, precision statement
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

## Results (what was measured, and what it means)

| Check | Result | Note |
|---|---|---|
| Time-split validation (train weeks 1-9, test labelled rows of weeks 10-13) | classification 0.880: issue macro-F1 0.848, severity weighted-F1 0.891, actionable F1 0.935 | Out of sample and forward in time; the best local proxy |
| 5-fold cross-validation on the 3,000 labels | classification about 0.91 | Optimistic: random folds mix weeks |
| Precision statement (time-split) | Marked actionable: 95.0% truly (95% interval 92.8%-96.5%); marked actionable and high/critical: 95.3% (90.6%-97.7%) | Sample over-represents rare types; not the full-stream rate |
| Worked example (IT17, ST-D69EG) | first valid flag 2026-05-11, naive detector 2026-05-18: lead +1 week | One incident only; none of the three hidden ones are known |
| Flag volume on the test half | 24 flags in 13 weeks (1.85 a week), budget is 3 | Planted incidents will add a few |
| Synthetic injection grid (120 plants, three shapes) | mean lead score about 0.49 (about one week earlier than the naive rule) | Synthetic shapes, not a forecast |
| `evaluate.py` on the training truth | 0.80 primary | **Inflated**: submission rows that have a public label carry that label, so classification scores 1.0 on them. Use the time-split row, not this one, to judge the classifier |

## AI usage

- **In the app:** no LLM, no external AI API, no downloaded model. The classifier is scikit-learn logistic regression trained at
  run time from the public labels; nothing is pickled.
- **While building:** Claude (Anthropic) was used as an AI coding and research assistant for planning, code, tests and this
  README. The team reviewed the code; every member should be able to explain it.

## Pre-built and third-party code

- Written for this hackathon: everything in `FULL_CODE/` except `tools/`.
- `FULL_CODE/tools/evaluate.py`: the organisers' scorer, unmodified, from the R5 pack.
- Libraries: numpy, pandas, scikit-learn, scipy (BSD licences); pytest, ruff, mypy for development.
- The pack's baseline was read for its interface only; none of its code was copied. No Round 1 code was reused.

## Limitations

- Lead time: one worked example is the only incident visible; thresholds were tuned on it, a synthetic grid and clean history.
  The three hidden incidents may look different.
- Flags need at least 2 reports in the incident week, so an incident whose first week has one report cannot be caught that week.
- Severity is the weakest label (ambiguous texts). The labelled sample is small (3,000) and not the stream's distribution.
- Cross-channel de-duplication (the stretch goal) is not implemented; the briefs show how many channels report an issue.
- Language handling relies on character n-grams, so unseen transliteration spellings and very short texts are the main error
  source. A multilingual encoder was not tried.
- Not tested on Python 3.9 specifically (code avoids newer syntax); tested on 3.13 only. The synthetic data means privacy
  rules (DPDP) are design discipline here, not a live obligation.
- Next steps: a reporter-level key for true corroboration, store-level seasonality, an encoder comparison, analyst feedback loop.
