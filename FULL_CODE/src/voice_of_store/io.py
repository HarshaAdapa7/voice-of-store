"""Reading data files (always from one folder) and validating inputs and outputs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .config import FLAG_COLS, ISSUE_TYPES, PRED_COLS, SEVERITIES

FEEDBACK_COLS = ["feedback_id", "channel", "created_at", "store_id", "text"]  # rating is optional: no code reads it
LABEL_COLS = ["feedback_id", "issue_type_id", "severity", "actionable"]
STORE_COLS = ["store_id", "store_name", "region", "avg_weekly_footfall"]
TAXONOMY_COLS = ["issue_type_id", "issue_type", "owner_function", "policy_severity_floor"]
CALENDAR_COLS = ["week_index", "week_start"]
log = logging.getLogger(__name__)
CHANNELS = {"online_review", "in_app", "staff_shift_note", "call_centre_ticket"}


class DataError(Exception):
    """An input file is missing or malformed. The message says which file and what to fix; it never quotes row content."""


@dataclass
class Data:
    feedback: pd.DataFrame
    labels: pd.DataFrame
    stores: pd.DataFrame
    taxonomy: pd.DataFrame
    calendar: pd.DataFrame


def _read(path: Path, **kwargs: object) -> pd.DataFrame:
    try:
        return pd.read_csv(path, **kwargs)  # type: ignore[call-overload]
    except FileNotFoundError:
        raise DataError(f"missing data file: {path.name} (expected in {path.parent})") from None
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise DataError(f"cannot parse {path.name}: {type(exc).__name__}") from None


def _need_columns(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise DataError(f"{name} is missing columns: {missing}")


def load_data(folder: Path, feedback_path: Path | None = None) -> Data:
    """Read every data file from `folder` (the folder that holds feedback.csv) and validate its shape."""
    folder = Path(folder)
    fb = _read(Path(feedback_path) if feedback_path else folder / "feedback.csv", dtype={"store_id": str, "feedback_id": str})
    _need_columns(fb, FEEDBACK_COLS, "feedback.csv")
    fb["text"] = fb["text"].fillna("").astype(str)
    fb["created_at"] = pd.to_datetime(fb["created_at"], errors="coerce")
    if fb["created_at"].isna().any() or fb["feedback_id"].isna().any() or fb["feedback_id"].duplicated().any():
        raise DataError("feedback.csv has unreadable timestamps, missing ids or duplicate feedback_id values")
    unknown = set(fb["channel"].dropna().unique()) - CHANNELS
    if unknown:  # the model copes with an unseen channel name, so warn instead of failing a live run
        log.warning("feedback.csv has channels the model was not trained on: %s", sorted(unknown))
    labels = _read(folder / "feedback_labels_train.csv", dtype=str)
    _need_columns(labels, LABEL_COLS, "feedback_labels_train.csv")
    labels["actionable"] = pd.to_numeric(labels["actionable"], errors="coerce")
    if labels["actionable"].isna().any() or not labels["actionable"].isin([0, 1]).all():
        raise DataError("feedback_labels_train.csv: actionable must be 0 or 1")
    labels["actionable"] = labels["actionable"].astype(int)
    if not labels["issue_type_id"].isin(ISSUE_TYPES).all() or not labels["severity"].isin(SEVERITIES).all():
        raise DataError("feedback_labels_train.csv has unknown issue types or severities")
    stores = _read(folder / "store_master.csv", dtype={"store_id": str})
    _need_columns(stores, STORE_COLS, "store_master.csv")
    tax = _read(folder / "issue_taxonomy.csv")
    _need_columns(tax, TAXONOMY_COLS, "issue_taxonomy.csv")
    cal = _read(folder / "week_calendar.csv")
    _need_columns(cal, CALENDAR_COLS, "week_calendar.csv")
    return Data(fb, labels, stores, tax.set_index("issue_type_id"), cal)


def week_start_of(ts: pd.Series) -> pd.Series:
    """Monday (as YYYY-MM-DD text) of the Monday-Sunday week containing each timestamp."""
    return ts.dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")


def monday_of(day: str) -> pd.Timestamp:
    """The Monday of the week containing `day` (any day of that week)."""
    try:
        d = pd.Timestamp(day)
    except (ValueError, TypeError):
        raise DataError(f"not a date: {str(day)[:20]!r} (use YYYY-MM-DD)") from None
    if pd.isna(d):
        raise DataError(f"not a date: {str(day)[:20]!r} (use YYYY-MM-DD)")
    d = d.normalize()
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


def load_incidents(folder: Path) -> pd.DataFrame | None:
    """The public worked-example incident file, used only by the reports. Never needed by the detector; None if absent."""
    path = Path(folder) / "emerging_incidents_train.csv"
    if not path.exists():
        return None
    inc = _read(path, dtype=str)
    need = ["incident_id", "store_ids", "issue_type_id", "onset_week_start", "naive_detect_week_start"]
    _need_columns(inc, need, "emerging_incidents_train.csv")
    return inc
