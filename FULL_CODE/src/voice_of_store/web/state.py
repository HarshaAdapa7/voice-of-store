"""Application state: data, classifier and predicted rows loaded once at start-up, read-only afterwards."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pandas as pd

from .. import config as C
from ..brief import build_region_week
from ..classify import FeedbackClassifier
from ..io import Data, load_data
from ..pipeline import prepare_rows
from ..report import time_split_validation, wilson
from ..stores import StoreResolver
from ..text import clean_input, redact


class AppState:
    def __init__(self, data_dir: Path, submission_dir: Path):
        self.data: Data = load_data(Path(data_dir))
        self.resolver = StoreResolver(self.data.stores)
        d = self.data
        fb = d.feedback.copy()
        fb["store"] = self.resolver.resolve_frame(fb)
        self.clf = FeedbackClassifier(d.taxonomy).fit(fb, d.labels)
        end = d.feedback["created_at"].max() + pd.Timedelta(seconds=1)
        self.rows = prepare_rows(d, end, self.resolver, clf=self.clf)
        flags = pd.read_csv(Path(submission_dir) / "R5_emerging_flags.csv", dtype=str)
        flags["confidence"] = flags["confidence"].astype(float)
        self.flags = flags
        self.weeks = d.calendar["week_start"].tolist()
        self.test_weeks = d.calendar[d.calendar["labelled_period"] == "test"]["week_start"].tolist()
        self.regions = sorted(d.stores["region"].unique())
        self.store_name = dict(zip(d.stores["store_id"], d.stores["store_name"]))
        self.store_region = dict(zip(d.stores["store_id"], d.stores["region"]))
        self.types = d.taxonomy.reset_index()[["issue_type_id", "issue_type", "owner_function", "policy_severity_floor"]]
        self._lock = threading.Lock()
        self._brief_cache: dict = {}
        self._validation: dict | None = None
        self._submission_dir = Path(submission_dir)

    # ---- queries (all arguments are validated by the caller against these allow-lists) ----
    def meta(self) -> dict:
        return dict(
            regions=self.regions,
            weeks=self.weeks,
            test_weeks=self.test_weeks,
            issue_types=[
                dict(id=r.issue_type_id, name=r.issue_type, owner=r.owner_function, floor=r.policy_severity_floor)
                for r in self.types.itertuples()
            ],
            channels=sorted(self.data.feedback["channel"].unique()),
            stores=[dict(id=s, name=n, region=self.store_region[s]) for s, n in self.store_name.items()],
        )

    def brief(self, region: str, week: str) -> list[dict]:
        key = (region, week)
        with self._lock:
            if key not in self._brief_cache:
                entries = build_region_week(self.rows, self.flags, self.data.stores, self.data.taxonomy, region, week)
                for e in entries:
                    e.pop("key", None)
                self._brief_cache[key] = entries
            return self._brief_cache[key]

    def week_rows(self, region: str, week: str) -> int:
        ids = set(self.data.stores[self.data.stores["region"] == region]["store_id"])
        r = self.rows
        return int(((r["week"] == week) & r["store"].isin(ids)).sum())

    def flags_for(self, week: str) -> list[dict]:
        out = []
        by_id = self.rows.set_index("feedback_id")
        for f in self.flags[self.flags["as_of_week_start"] == week].itertuples():
            ids = f.evidence_feedback_ids.split(";")
            ev = [
                dict(channel=str(by_id.loc[i, "channel"]), text=redact(str(by_id.loc[i, "text"])[:240]))
                for i in ids
                if i in by_id.index
            ]
            out.append(
                dict(
                    store_id=f.store_id,
                    store=self.store_name.get(f.store_id, f.store_id),
                    region=self.store_region.get(f.store_id),
                    issue_type=f.issue_type_id,
                    issue=str(self.data.taxonomy.loc[f.issue_type_id, "issue_type"]),
                    owner=str(self.data.taxonomy.loc[f.issue_type_id, "owner_function"]),
                    confidence=round(float(f.confidence), 3),
                    evidence=ev,
                )
            )
        return out

    def series(self, store_id: str, issue_type: str) -> dict:
        r = self.rows
        sub = r[(r["store"] == store_id) & (r["itype"] == issue_type)]
        counts = sub.groupby("week").size()
        chain = r[(r["itype"] == issue_type) & r["store"].notna()].groupby("week").size()
        flagged = self.flags[(self.flags["store_id"] == store_id) & (self.flags["issue_type_id"] == issue_type)][
            "as_of_week_start"
        ].tolist()
        return dict(
            weeks=self.weeks,
            store_counts=[int(counts.get(w, 0)) for w in self.weeks],
            chain_counts=[int(chain.get(w, 0)) for w in self.weeks],
            flagged_weeks=flagged,
        )

    def classify(self, text: str, channel: str) -> dict:
        text = clean_input(text, 2000)
        df = pd.DataFrame([dict(feedback_id="input", channel=channel, text=text, store_id=None)])
        store = self.resolver.resolve(None, text)
        pred = self.clf.predict(df, pd.Series([store], index=df.index, dtype=object)).iloc[0]
        proba = self.clf.proba(df).iloc[0].sort_values(ascending=False).head(3)
        itype = str(pred["issue_type_id"])
        why = self.clf.explain(df)
        return dict(
            issue_type=itype,
            issue=str(self.data.taxonomy.loc[itype, "issue_type"]),
            owner=str(self.data.taxonomy.loc[itype, "owner_function"]),
            severity=str(pred["severity"]),
            actionable=int(pred["actionable"]),
            confidence=round(float(pred["type_confidence"]), 3),
            store_named=self.store_name.get(store) if store else None,
            alternatives=[dict(issue_type=str(k), score=round(float(v), 3)) for k, v in proba.items()],
            key_terms=[dict(term=t, weight=round(w, 3)) for t, w in why],
            note=(
                "Not actionable without a store unless it is an order/app/payment/refund/loyalty issue."
                if int(pred["actionable"]) == 0 and itype not in C.NON_ISSUE
                else ""
            ),
        )

    def validation(self) -> dict:
        path = self._submission_dir.parent / "out" / "validation.json"
        with self._lock:
            if self._validation is None:
                if path.exists():
                    self._validation = json.loads(path.read_text(encoding="utf-8"))
                else:
                    v = time_split_validation(self.data, self.resolver)
                    k1 = round(v["precision_actionable"] * v["n_pred_actionable"])
                    k2 = round(v["precision_actionable_high"] * v["n_pred_actionable_high"])
                    v["ci_actionable"] = wilson(k1, v["n_pred_actionable"])
                    v["ci_actionable_high"] = wilson(k2, v["n_pred_actionable_high"])
                    self._validation = v
            return self._validation
