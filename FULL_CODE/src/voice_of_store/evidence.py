"""Evidence selection. Re-implements the scorer's checks (a) to (d) so every cited id is one the scorer will accept."""

from __future__ import annotations

import pandas as pd

from . import config as C
from .stores import StoreResolver


def belongs(row_store: object, row_text: str, store_id: str, loc: dict) -> bool:
    """Scorer rule (b): same store_id, or empty store_id and the text names the store's locality."""
    if isinstance(row_store, str) and row_store:
        return row_store == store_id
    return loc[store_id] in str(row_text).lower()


def select_evidence(
    week_rows: pd.DataFrame,
    store_id: str,
    itype: str,
    week_start: str,
    week_end_excl: str,
    resolver: StoreResolver,
    limit: int = C.EVIDENCE_MAX,
) -> list[str]:
    """Highest-confidence rows of this store, week and predicted type. week_rows has feedback_id, store_id, text,
    created_at, itype, conf."""
    r = week_rows
    in_week = (r["created_at"] >= pd.Timestamp(week_start)) & (r["created_at"] < pd.Timestamp(week_end_excl))
    ok = r[in_week & (r["itype"] == itype)]
    keep = [belongs(s, t, store_id, resolver.locality) for s, t in zip(ok["store_id"], ok["text"], strict=False)]
    ok = ok[keep].sort_values(["conf", "feedback_id"], ascending=[False, True], kind="mergesort")
    return ok["feedback_id"].drop_duplicates().head(limit).tolist()


def valid_evidence_count(
    ids: list[str],
    week_rows: pd.DataFrame,
    store_id: str,
    itype: str,
    week_start: str,
    week_end_excl: str,
    resolver: StoreResolver,
) -> int:
    """How many of the cited ids would pass the scorer's four checks for this store, week and type."""
    chosen = select_evidence(week_rows, store_id, itype, week_start, week_end_excl, resolver, limit=10**6)
    return len(set(ids) & set(chosen))
