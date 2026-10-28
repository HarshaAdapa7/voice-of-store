#!/usr/bin/env python3
"""Regenerate submission/ from the data folder: predictions for every row, flags week by week, detector_cmd.txt.

    python FULL_CODE/make_submission.py [--data data] [--out submission]

Flags are produced one as-of week at a time with exactly the logic of FULL_CODE/detect.py (each week sees only rows
created up to its Sunday).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd  # noqa: E402

from voice_of_store import config as C  # noqa: E402
from voice_of_store.io import load_data, monday_of, validate_flags, validate_predictions  # noqa: E402
from voice_of_store.pipeline import emit_flags, prepare_rows, sunday_end  # noqa: E402
from voice_of_store.stores import StoreResolver  # noqa: E402

DETECTOR_CMD = "python FULL_CODE/detect.py --feedback {feedback} --as-of {asof} --out {out}\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="submission")
    a = ap.parse_args()
    data = load_data(Path(a.data))
    resolver = StoreResolver(data.stores)
    out = Path(a.out)
    out.mkdir(exist_ok=True)

    # 1. predictions for every row: classifier trained on all public labels (labelled rows keep their public label)
    end = data.feedback["created_at"].max() + pd.Timedelta(seconds=1)
    rows = prepare_rows(data, end, resolver)
    pred = rows.rename(columns={"itype": "issue_type_id"})[C.PRED_COLS].copy()
    errs = validate_predictions(pred, data.feedback["feedback_id"])
    if errs:
        raise SystemExit(f"invalid predictions: {errs}")
    pred.to_csv(out / "R5_predictions.csv", index=False)

    # 2. flags: one as-of week at a time, each week classified with only the data available then
    cache: dict = {}
    frames = []
    for w in data.calendar["week_start"].tolist():
        wk_rows = prepare_rows(data, sunday_end(monday_of(w)), resolver, cache)
        frames.append(emit_flags(wk_rows, data, resolver, [w]))
    flags = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=C.FLAG_COLS)
    errs = validate_flags(flags)
    if errs:
        raise SystemExit(f"invalid flags: {errs}")
    flags.to_csv(out / "R5_emerging_flags.csv", index=False)
    (out / "detector_cmd.txt").write_text(DETECTOR_CMD, encoding="utf-8")
    print(f"wrote {len(pred)} predictions and {len(flags)} flags to {out}/")


if __name__ == "__main__":
    main()
