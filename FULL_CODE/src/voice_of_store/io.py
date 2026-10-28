"""Reading data files (always from one folder) and validating output files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import FLAG_COLS, ISSUE_TYPES, PRED_COLS, SEVERITIES


@dataclass
class Data:
    feedback: pd.DataFrame
    labels: pd.DataFrame
    stores: pd.DataFrame
    taxonomy: pd.DataFrame
    calendar: pd.DataFrame


def load_data(folder: Path, feedback_path: Path | None = None) -> Data:
    """Read every data file from `folder` (the folder that holds feedback.csv)."""
    folder = Path(folder)
    fb_path = Path(feedback_path) if feedback_path else folder / "feedback.csv"
    fb = pd.read_csv(fb_path, dtype={"store_id": str, "feedback_id": str})
    fb["text"] = fb["text"].fillna("").astype(str)
    fb["created_at"] = pd.to_datetime(fb["created_at"])
    labels = pd.read_csv(folder / "feedback_labels_train.csv", dtype=str)
    labels["actionable"] = labels["actionable"].astype(int)
    stores = pd.read_csv(folder / "store_master.csv", dtype={"store_id": str})
    tax = pd.read_csv(folder / "issue_taxonomy.csv").set_index("issue_type_id")
    cal = pd.read_csv(folder / "week_calendar.csv")
    return Data(fb, labels, stores, tax, cal)


def week_start_of(ts: pd.Series) -> pd.Series:
    """Monday (as YYYY-MM-DD text) of the Monday-Sunday week containing each timestamp."""
    return ts.dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")


def monday_of(day: str) -> pd.Timestamp:
    d = pd.Timestamp(day).normalize()
    return d - pd.Timedelta(days=d.weekday())


def validate_predictions(pred: pd.DataFrame, feedback_ids: pd.Series) -> list[str]:
    """Return a list of problems (empty list = valid)."""
    errs: list[str] = []
    if list(pred.columns) != PRED_COLS:
        errs.append(f"columns must be {PRED_COLS}, got {list(pred.columns)}")
        return errs
    if pred["feedback_id"].duplicated().any():
        errs.append("duplicate feedback_id")
    if set(pred["feedback_id"]) != set(feedback_ids):
        errs.append("feedback_id set differs from feedback.csv")
    if not pred["issue_type_id"].isin(ISSUE_TYPES).all():
        errs.append("unknown issue_type_id")
    if not pred["severity"].isin(SEVERITIES).all():
        errs.append("unknown severity")
    if not pred["actionable"].isin([0, 1]).all():
        errs.append("actionable must be 0/1")
    return errs


def validate_flags(flags: pd.DataFrame) -> list[str]:
    errs: list[str] = []
    if list(flags.columns) != FLAG_COLS:
        errs.append(f"columns must be {FLAG_COLS}, got {list(flags.columns)}")
        return errs
    if flags.duplicated(["as_of_week_start", "store_id", "issue_type_id"]).any():
        errs.append("duplicate (week, store, type)")
    if len(flags) and not flags["confidence"].between(0, 1).all():
        errs.append("confidence must be in [0, 1]")
    if len(flags) and not flags["issue_type_id"].isin(ISSUE_TYPES).all():
        errs.append("unknown issue_type_id")
    return errs
