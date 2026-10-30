"""Validate extracted candidate records against store master and format schema."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

import pandas as pd

from ...io import FEEDBACK_COLS
from ...stores import StoreResolver

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}")
VALID_CHANNELS = {"online_review", "in_app", "staff_shift_note", "call_centre_ticket"}


@dataclass
class ValidatedRecord:
    """A candidate feedback record validated against store schema."""

    feedback_id: str
    channel: str
    created_at: str
    store_id: str
    store_name: str
    region: str
    text: str
    source_reference: str
    status: str  # "valid", "review_store", "review_date"
    notes: str


class IngestionValidator:
    """Validates and aligns candidate feedback records with store directory."""

    def __init__(self, stores_df: pd.DataFrame, resolver: StoreResolver | None = None) -> None:
        """Initialize validator with stores directory."""
        """Initialize validator with stores directory."""
        self.stores_df = stores_df.copy()
        self.resolver = resolver or StoreResolver(stores_df)
        self._store_by_id = {
            row["store_id"]: (row.get("store_name", ""), row.get("region", "")) for _, row in self.stores_df.iterrows()
        }

    def resolve_store_mention(self, mention: str | None, text_content: str) -> tuple[str, str, str]:
        """Returns (store_id, store_name, region). Empty strings if unresolvable."""
        # 1. If explicit store ID like STR-012
        if mention:
            m_upper = mention.upper().strip()
            if m_upper in self._store_by_id:
                s_name, region = self._store_by_id[m_upper]
                return m_upper, s_name, region

        # 2. Try resolving via store mention text
        query = f"{mention or ''} {text_content}"
        dummy_df = pd.DataFrame([{"store_id": "", "text": query}])
        resolved = self.resolver.resolve_frame(dummy_df)
        res_id = resolved.iloc[0]
        if res_id and res_id in self._store_by_id:
            s_name, region = self._store_by_id[res_id]
            return res_id, s_name, region

        return "", "", ""

    def validate_candidate_records(
        self,
        raw_records: list[dict],
        start_id: int = 1,
        fallback_date: str | None = None,
    ) -> tuple[list[ValidatedRecord], dict[str, int]]:
        fb_date = fallback_date or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        validated: list[ValidatedRecord] = []
        stats = {"total": len(raw_records), "valid": 0, "review_store": 0, "review_date": 0}

        for idx, rec in enumerate(raw_records, start_id):
            fb_id = f"FB-UPL-{idx:04d}"
            channel = rec.get("channel", "online_review")
            if channel not in VALID_CHANNELS:
                channel = "online_review"

            raw_date = rec.get("created_at")
            status = "valid"
            notes = []

            if raw_date and _DATE_PATTERN.match(str(raw_date).strip()):
                created_at = str(raw_date).strip()
                if len(created_at) == 10:
                    created_at += " 12:00:00"
            else:
                created_at = fb_date
                status = "review_date"
                notes.append("Date inferred/fallback")
                stats["review_date"] += 1

            store_id, store_name, region = self.resolve_store_mention(rec.get("store_mention"), rec.get("text", ""))
            if not store_id:
                if status == "valid":
                    status = "review_store"
                notes.append("Store could not be identified")
                stats["review_store"] += 1

            if status == "valid":
                stats["valid"] += 1

            text = str(rec.get("text", "")).strip()
            src_ref = str(rec.get("source_reference", f"Item {idx}"))

            validated.append(
                ValidatedRecord(
                    feedback_id=fb_id,
                    channel=channel,
                    created_at=created_at,
                    store_id=store_id,
                    store_name=store_name,
                    region=region,
                    text=text,
                    source_reference=src_ref,
                    status=status,
                    notes="; ".join(notes) if notes else "Verified",
                )
            )

        return validated, stats

    @staticmethod
    def to_feedback_dataframe(records: list[dict]) -> pd.DataFrame:
        """Convert a list of approved record dicts into a validated feedback DataFrame."""
        clean_rows = []
        for r in records:
            clean_rows.append(
                {
                    "feedback_id": r.get("feedback_id", ""),
                    "channel": r.get("channel", "online_review"),
                    "created_at": r.get("created_at", ""),
                    "store_id": r.get("store_id", ""),
                    "text": r.get("text", ""),
                }
            )
        df = pd.DataFrame(clean_rows, columns=FEEDBACK_COLS)
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
        # Drop rows where created_at or text is empty
        df = df.dropna(subset=["created_at", "text"])
        df["created_at"] = df["created_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
        return df
