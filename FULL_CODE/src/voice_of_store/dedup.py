"""Cross-channel de-duplication (stretch goal): collapse several reports of one real-world event into one incident.

Rule (there is no ground truth for duplicates, so this is a stated heuristic, not a measured result):
reports are the same incident when they share the resolved store and the predicted issue type and each report follows
the previous one by at most `gap_hours`. Time order is the only linkage, so one event told in different languages by
different channels is merged even when the wording differs. Counts that feed the detector are NOT changed by this.
"""
from __future__ import annotations

import pandas as pd

GAP_HOURS = 72


def cluster_incidents(rows: pd.DataFrame, gap_hours: int = GAP_HOURS) -> pd.DataFrame:
    """rows needs feedback_id, store, itype, created_at, channel. Returns a frame with one row per input row and a
    deterministic `incident` label like 'ST-X|IT10|0'."""
    if rows.empty:
        return pd.DataFrame(columns=["feedback_id", "incident"])
    r = rows.sort_values(["store", "itype", "created_at", "feedback_id"], kind="mergesort")
    new_group = (r["store"] != r["store"].shift()) | (r["itype"] != r["itype"].shift())
    gap = r["created_at"].diff() > pd.Timedelta(hours=gap_hours)
    seq = (new_group | gap).cumsum()
    first = r.groupby(seq)["created_at"].transform("min")
    r = r.assign(_seq=seq, _first=first)
    label = r["store"].astype(str) + "|" + r["itype"].astype(str) + "|" + r["_first"].dt.strftime("%Y%m%d%H%M")
    return pd.DataFrame({"feedback_id": r["feedback_id"].values, "incident": label.values})


def summarise(rows: pd.DataFrame, gap_hours: int = GAP_HOURS) -> dict:
    """Incident count, report count and how many incidents were seen in 2+ channels."""
    if rows.empty:
        return dict(reports=0, incidents=0, cross_channel=0)
    inc = cluster_incidents(rows, gap_hours)
    m = rows.merge(inc, on="feedback_id")
    g = m.groupby("incident")["channel"].nunique()
    return dict(reports=len(rows), incidents=int(len(g)), cross_channel=int((g >= 2).sum()))
