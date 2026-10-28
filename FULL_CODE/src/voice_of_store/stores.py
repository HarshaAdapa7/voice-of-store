"""Store resolver. Uses the same locality rule the scorer uses for evidence check (b)."""

from __future__ import annotations

import pandas as pd


def locality(store_name: str) -> str:
    """Part of the store name after 'Saffron Hyper/Market/Express' (lower-case)."""
    parts = str(store_name).split(" ", 2)
    return (parts[2] if len(parts) > 2 else parts[-1]).lower()


class StoreResolver:
    def __init__(self, stores: pd.DataFrame):
        self.locality = {r.store_id: locality(r.store_name) for r in stores.itertuples()}
        # longest locality first so "Salt Lake City" wins over "Salt Lake"
        self._ordered = sorted(self.locality.items(), key=lambda kv: -len(kv[1]))
        self.valid = set(self.locality)

    def names_in_text(self, text: str) -> list[str]:
        low = str(text).lower()
        return [sid for sid, loc in self._ordered if loc and loc in low]

    def resolve(self, store_id: object, text: str) -> str | None:
        """Recorded store if it is valid; otherwise the single store whose locality the text names."""
        if isinstance(store_id, str) and store_id in self.valid:
            return store_id
        hits = self.names_in_text(text)
        # "Salt Lake City" also contains "Salt Lake": when one locality is part of a longer named one, the longer one is meant
        hits = [
            h
            for h in hits
            if not any(self.locality[h] != self.locality[o] and self.locality[h] in self.locality[o] for o in hits)
        ]
        return hits[0] if len(hits) == 1 else None

    def resolve_frame(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series([self.resolve(s, t) for s, t in zip(df["store_id"], df["text"])], index=df.index, dtype=object)
