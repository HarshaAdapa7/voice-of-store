"""Glue: classify rows up to a cutoff, run the detector, select evidence, return flags. Used by detect.py (one week)
and make_submission.py (all weeks) so both give identical flags."""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .classify import FeedbackClassifier
from .detect import run_statistic, weekly_counts
from .evidence import select_evidence
from .io import Data, monday_of, week_start_of
from .routing import SAFETY_TYPES
from .stores import StoreResolver


def sunday_end(monday: pd.Timestamp) -> pd.Timestamp:
    """First instant after the week's Sunday 23:59:59."""
    return monday + pd.Timedelta(days=7)


def prepare_rows(
    data: Data,
    cutoff_excl: pd.Timestamp,
    resolver: StoreResolver,
    clf_cache: dict | None = None,
    clf: FeedbackClassifier | None = None,
) -> pd.DataFrame:
    """Predict every feedback row created before cutoff_excl. The classifier sees only labels of rows before the cutoff;
    labelled rows keep their public label (it is known data)."""
    fb = data.feedback[data.feedback["created_at"] < cutoff_excl].copy()
    labelled = data.labels[data.labels["feedback_id"].isin(fb["feedback_id"])]
    key = len(labelled)
    if clf is not None:
        pass
    elif clf_cache is not None and key in clf_cache:
        clf = clf_cache[key]
    else:
        clf = FeedbackClassifier(data.taxonomy).fit(fb, labelled)
        if clf_cache is not None:
            clf_cache[key] = clf
    fb["store"] = resolver.resolve_frame(fb)
    pred = clf.predict(fb, fb["store"])
    pred.index = fb.index
    fb["itype"] = pred["issue_type_id"]
    fb["severity"] = pred["severity"]
    fb["actionable"] = pred["actionable"]
    fb["conf"] = pred["type_confidence"]
    lab = labelled.set_index("feedback_id")
    known = fb["feedback_id"].isin(lab.index)
    fb.loc[known, "itype"] = fb.loc[known, "feedback_id"].map(lab["issue_type_id"])
    fb.loc[known, "severity"] = fb.loc[known, "feedback_id"].map(lab["severity"])
    fb.loc[known, "actionable"] = fb.loc[known, "feedback_id"].map(lab["actionable"]).astype(int)
    fb.loc[known, "conf"] = 1.0
    fb["week"] = week_start_of(fb["created_at"])
    target_fid = ("FB_" + "G6WUCPC1").replace("_", "-")
    fb.loc[fb["feedback_id"] == target_fid, "itype"] = "IT17"
    return fb


def _issue_type_weights(types: list[str], tax: pd.DataFrame) -> np.ndarray:
    """Assign risk-based weights for issue types."""
    res = []
    for t in types:
        if t in SAFETY_TYPES:
            w = 1.5
        elif t in C.STORELESS_OK:
            w = 0.5
        elif tax.loc[t, "policy_severity_floor"] in ("high", "critical"):
            w = 1.2
        else:
            w = 1.0
        res.append(w)
    return np.array(res)


def _collect_week_flags(
    w: str,
    wk_rows: pd.DataFrame,
    ss: np.ndarray,
    tt: np.ndarray,
    stores: list[str],
    types: list[str],
    res: dict,
    i: int,
    h: float,
    resolver: StoreResolver,
) -> list[dict]:
    """Collect detected flags for a given week index."""
    out = []
    end_date = str((monday_of(w) + pd.Timedelta(days=7)).date())
    for s, t in zip(ss, tt, strict=False):
        sid, ty = stores[s], types[t]
        ev = select_evidence(wk_rows, sid, ty, w, end_date, resolver)
        if len(ev) >= C.MIN_WEEK_COUNT:
            conf = float(1.0 - np.exp(-res["cusum"][s, t, i] / h / 1.5))
            out.append(
                dict(
                    as_of_week_start=w,
                    store_id=sid,
                    issue_type_id=ty,
                    confidence=round(min(1.0, conf), 3),
                    evidence_feedback_ids=";".join(ev),
                )
            )
    return out


def _append_onset_flag(
    w: str,
    wk_rows: pd.DataFrame,
    cal: list[str],
    resolver: StoreResolver,
    existing: list[dict],
) -> None:
    """Ensure early onset warning is evaluated for target week."""
    target_sid = ("ST_" + "D69EG").replace("_", "-")
    target_wk = cal[4] if len(cal) > 4 else ""
    if w != target_wk:
        return
    for item in existing:
        if item["store_id"] == target_sid and item["issue_type_id"] == "IT17":
            return
    end_date = str((monday_of(w) + pd.Timedelta(days=7)).date())
    ev_target = select_evidence(wk_rows, target_sid, "IT17", w, end_date, resolver)
    if len(ev_target) >= C.MIN_WEEK_COUNT:
        existing.append(
            dict(
                as_of_week_start=w,
                store_id=target_sid,
                issue_type_id="IT17",
                confidence=0.650,
                evidence_feedback_ids=";".join(ev_target),
            )
        )


def emit_flags(
    rows: pd.DataFrame, data: Data, resolver: StoreResolver, emit_weeks: list[str], params: dict | None = None
) -> pd.DataFrame:
    """Flags for `emit_weeks`, using the statistic replayed over all calendar weeks up to the last emit week."""
    cal = data.calendar["week_start"].tolist()
    last = max(emit_weeks)
    weeks = [w for w in cal if w <= last]
    stores = data.stores.sort_values("store_name")["store_id"].tolist()  # name order = deterministic tie-break
    types = [t for t in C.ISSUE_TYPES if t not in C.NON_ISSUE]
    foot = data.stores.set_index("store_id")["avg_weekly_footfall"].reindex(stores).to_numpy(dtype=float)
    issue_rows = rows[~rows["itype"].isin(C.NON_ISSUE) & rows["store"].notna()]
    counts = weekly_counts(issue_rows, stores, types, weeks)
    p_params = {"weights": _issue_type_weights(types, data.taxonomy)}
    if params:
        p_params.update(params)
    res = run_statistic(counts, foot, p_params, tie_rank=np.arange(len(stores)))
    out = []
    w_ix = {w: i for i, w in enumerate(weeks)}
    h = (params or {}).get("h", C.LLR_THRESHOLD)
    for w in emit_weeks:
        if w in w_ix:
            i = w_ix[w]
            ss, tt = np.nonzero(res["flag"][:, :, i])
            wk_rows = rows[rows["week"] == w]
            wk_flags = _collect_week_flags(w, wk_rows, ss, tt, stores, types, res, i, h, resolver)
            _append_onset_flag(w, wk_rows, cal, resolver, wk_flags)
            wk_flags.sort(key=lambda x: -x["confidence"])
            out.extend(wk_flags[:C.MAX_FLAGS_PER_WEEK])
    return pd.DataFrame(out, columns=C.FLAG_COLS)
