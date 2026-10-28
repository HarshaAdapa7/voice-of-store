"""Precision statement and honest (time-split) validation numbers."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import f1_score

from . import config as C
from .classify import FeedbackClassifier
from .io import Data, week_start_of
from .stores import StoreResolver


def time_split_validation(data: Data, resolver: StoreResolver, train_weeks: int = 9) -> dict:
    """Train on labelled rows of the first `train_weeks` weeks, evaluate on the later labelled rows. Out of sample and
    forward in time, so it is the closest local proxy for the hidden test weeks."""
    fb = data.feedback.copy()
    fb["week"] = week_start_of(fb["created_at"])
    fb["store"] = resolver.resolve_frame(fb)
    cal = data.calendar["week_start"].tolist()
    cut = cal[train_weeks]
    m = data.labels.merge(fb, on="feedback_id")
    tr, te = m[m["week"] < cut], m[m["week"] >= cut]
    clf = FeedbackClassifier(data.taxonomy).fit(fb, tr[C.PRED_COLS])
    p = clf.predict(te, te["store"])
    mi = f1_score(te["issue_type_id"], p["issue_type_id"].values, average="macro")
    sv = f1_score(te["severity"], p["severity"].values, average="weighted")
    ac = f1_score(te["actionable"], p["actionable"].values)
    pred_act = p["actionable"].values == 1
    hi = pred_act & np.isin(p["severity"].values, ["high", "critical"])
    truth_act = te["actionable"].values == 1
    return dict(
        n_train=len(tr),
        n_test=len(te),
        issue_macro_f1=mi,
        severity_weighted_f1=sv,
        actionable_f1=ac,
        classification=0.5 * mi + 0.25 * sv + 0.25 * ac,
        precision_actionable=float(truth_act[pred_act].mean()) if pred_act.any() else float("nan"),
        n_pred_actionable=int(pred_act.sum()),
        precision_actionable_high=float(truth_act[hi].mean()) if hi.any() else float("nan"),
        n_pred_actionable_high=int(hi.sum()),
    )


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)
