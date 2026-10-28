"""Build the three submission files: predictions for every row, flags week by week, and the detector command."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from . import config as C
from .classify import FeedbackClassifier
from .io import Data, DataError, load_data, monday_of, validate_flags, validate_predictions
from .pipeline import emit_flags, prepare_rows, sunday_end
from .stores import StoreResolver

log = logging.getLogger(__name__)
DETECTOR_CMD = "python FULL_CODE/detect.py --feedback {feedback} --as-of {asof} --out {out}\n"


def build_predictions(data: Data, resolver: StoreResolver) -> pd.DataFrame:
    """Classifier trained on all public labels; labelled rows keep their public label."""
    end = data.feedback["created_at"].max() + pd.Timedelta(seconds=1)
    rows = prepare_rows(data, end, resolver)
    return rows.rename(columns={"itype": "issue_type_id"})[C.PRED_COLS].copy()


def build_flags(data: Data, resolver: StoreResolver) -> pd.DataFrame:
    """One as-of week at a time, each week classified with only the data available then."""
    cache: dict[int, FeedbackClassifier] = {}
    frames = []
    for week in data.calendar["week_start"].tolist():
        rows = prepare_rows(data, sunday_end(monday_of(week)), resolver, cache)
        frames.append(emit_flags(rows, data, resolver, [week]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=C.FLAG_COLS)


def write_submission(data_dir: Path, out_dir: Path) -> tuple[int, int]:
    data = load_data(data_dir)
    resolver = StoreResolver(data.stores)
    pred = build_predictions(data, resolver)
    errs = validate_predictions(pred, data.feedback["feedback_id"])
    if errs:
        raise DataError(f"invalid predictions: {errs}")
    flags = build_flags(data, resolver)
    errs = validate_flags(flags)
    if errs:
        raise DataError(f"invalid flags: {errs}")
    out_dir.mkdir(parents=True, exist_ok=True)
    pred.to_csv(out_dir / "R5_predictions.csv", index=False)
    flags.to_csv(out_dir / "R5_emerging_flags.csv", index=False)
    (out_dir / "detector_cmd.txt").write_text(DETECTOR_CMD, encoding="utf-8")
    log.info("wrote %d predictions and %d flags to %s", len(pred), len(flags), out_dir)
    return len(pred), len(flags)
