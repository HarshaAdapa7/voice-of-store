"""Application state: data, classifier and predicted rows loaded once at start-up, read-only afterwards."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pandas as pd

from .. import config as C
from ..analysis import build_report
from ..brief import build_region_week, severity_rank, trend_arrow, when_text
from ..classify import FeedbackClassifier
from ..io import Data, load_data, load_incidents
from ..pipeline import prepare_rows
from ..report import time_split_validation, wilson
from ..report_page import render_report
from ..routing import SAFETY_TYPES, action_window, next_step, verification_status
from ..stores import StoreResolver
from ..text import clean_input, redact

MAX_MEMOS = 4096


class AppState:
    """Data, classifier and predicted rows loaded once at start-up and read-only afterwards."""

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
        self.store_name = dict(zip(d.stores["store_id"], d.stores["store_name"], strict=False))
        self.store_region = dict(zip(d.stores["store_id"], d.stores["region"], strict=False))
        self.types = d.taxonomy.reset_index()[["issue_type_id", "issue_type", "owner_function", "policy_severity_floor"]]
        self._lock = threading.Lock()
        self._index_rows()
        self._brief_cache: dict = {}
        self._memos: dict = {}
        self._validation: dict | None = None
        self._submission_dir = Path(submission_dir)
        self._data_dir = Path(data_dir)
        self._report: dict | None = None
        self._default_data = self.data
        self._default_rows = self.rows
        self._default_flags = self.flags
        self._default_weeks = list(self.weeks)
        self._default_test_weeks = list(self.test_weeks)
        self.is_custom = False
        self.custom_name = ""

    def _index_rows(self) -> None:
        """Build the lookups once so each request is a dictionary read, not a scan of 40,000 rows."""
        r = self.rows
        self._by_id = r.set_index("feedback_id")[["channel", "text"]]
        issues = r[~r["itype"].isin(C.NON_ISSUE) & r["store"].notna()]
        self._counts = issues.groupby(["store", "itype", "week"]).size()
        self._chain = issues.groupby(["itype", "week"]).size()
        region = r["store"].map(self.store_region)
        self._region_week_rows = r[region.notna()].groupby([region[region.notna()], r["week"]]).size()
        act = r[(r["actionable"] == 1) & ~r["itype"].isin(C.NON_ISSUE) & r["store"].notna()]
        self._store_week_actionable = act.groupby(["store", "week"]).size()

    def _memo(self, kind: str, key: tuple, build) -> Any:
        """Bounded read-through cache for results that depend only on allow-listed arguments (read-only data)."""
        k = (kind, *key)
        with self._lock:
            if k in self._memos:
                return self._memos[k]
        value = build()
        with self._lock:
            if len(self._memos) >= MAX_MEMOS:
                self._memos.clear()
            self._memos[k] = value
        return value

    def warm(self) -> None:
        """Compute every brief of the test weeks in the background so the first click is instant."""
        for week in self.test_weeks:
            for region in self.regions:
                self.brief(region, week)
        self.report()

    # ---- queries (all arguments are validated by the caller against these allow-lists) ----
    def meta(self) -> dict:
        """Allow-lists and labels the UI needs."""
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
            dataset=self.dataset_info(),
        )

    def brief(self, region: str, week: str) -> list[dict]:
        """Cached top issues for a region and week."""
        key = (region, week)
        with self._lock:
            if key not in self._brief_cache:
                entries = build_region_week(self.rows, self.flags, self.data.stores, self.data.taxonomy, region, week)
                for e in entries:
                    e.pop("key", None)
                self._brief_cache[key] = entries
            return self._brief_cache[key]

    def week_rows(self, region: str, week: str) -> int:
        """Number of records for a region and week."""
        return int(self._region_week_rows.get((region, week), 0))

    def flags_for(self, week: str) -> list[dict]:
        """Cached flags for a week with evidence, status, next step and what changed."""
        return self._memo("flags", (week,), lambda: self._flags_for(week))

    def _flags_for(self, week: str) -> list[dict]:
        out = []
        by_id = self._by_id
        for f in self.flags[self.flags["as_of_week_start"] == week].itertuples():
            ids = f.evidence_feedback_ids.split(";")
            ev = [
                dict(channel=str(by_id.loc[i, "channel"]), text=redact(str(by_id.loc[i, "text"])[:240]))
                for i in ids
                if i in by_id.index
            ]
            owner = str(self.data.taxonomy.loc[f.issue_type_id, "owner_function"])
            out.append(
                dict(
                    owner_window=action_window("high", f.issue_type_id, True),
                    next_step=next_step(f.issue_type_id, owner, True),
                    status=verification_status(f.issue_type_id, self._evidence_tier(ev)),
                    change=self._change(f.store_id, f.issue_type_id, week),
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

    @staticmethod
    def _evidence_tier(evidence: list[dict]) -> str:
        """Independent means different wording in at least two channels, or three different texts; copies do not count."""
        texts = {e["text"] for e in evidence}
        channels = {e["channel"] for e in evidence}
        return "CORROBORATED" if (len(channels) >= 2 and len(texts) >= 2) or len(texts) >= 3 else "UNVERIFIED"

    def _change(self, store_id: str, issue_type: str, week: str) -> dict:
        """What changed, where and how quickly, from the same counts the detector used (all values are as of `week`)."""
        counts = self._counts.get((store_id, issue_type), pd.Series(dtype=int))
        chain = self._chain.get(issue_type, pd.Series(dtype=int))
        i = self.weeks.index(week)
        prior = self.weeks[max(0, i - 8) : i]
        history = [int(counts.get(w, 0)) for w in prior]
        base = sum(history) / len(history) if history else 0.0
        now = int(counts.get(week, 0))
        chain_now = int(chain.get(week, 0))
        chain_base = sum(int(chain.get(w, 0)) for w in prior) / len(prior) if prior else 0.0
        r = self.rows
        mine = r[(r["store"] == store_id) & (r["itype"] == issue_type) & (r["week"] == week)]["created_at"]
        first, last = (mine.min(), mine.max()) if len(mine) else (None, None)
        span = max(1, int((last - first).days) + 1) if first is not None else 0
        local = chain_now <= 1.5 * max(chain_base, 1.0)
        text = (
            f"{now} reports this week against a usual {base:.1f} a week over the previous {len(prior)} weeks "
            f"(last weeks: {', '.join(map(str, history[-4:])) or 'none'}). First report {when_text(first)}, latest {when_text(last)}: "
            f"{now} in {span} day(s). Chain-wide the issue is {chain_now} reports against a usual {chain_base:.0f}, "
            f"so this is {'local to this store' if local else 'also rising across the chain'}."
        )
        return dict(
            this_week=now,
            usual_per_week=round(base, 1),
            recent_weeks=history[-4:],
            first_report=when_text(first) if first is not None else None,
            latest_report=when_text(last) if last is not None else None,
            days_span=span,
            chain_this_week=chain_now,
            chain_usual=round(chain_base, 1),
            local_only=bool(local),
            summary=text,
        )

    def series(self, store_id: str, issue_type: str) -> dict:
        """Weekly counts for one store and issue type next to the chain total."""
        counts = self._counts.get((store_id, issue_type), pd.Series(dtype=int))
        chain = self._chain.get(issue_type, pd.Series(dtype=int))
        flagged = self.flags[(self.flags["store_id"] == store_id) & (self.flags["issue_type_id"] == issue_type)][
            "as_of_week_start"
        ].tolist()
        return dict(
            weeks=self.weeks,
            store_counts=[int(counts.get(w, 0)) for w in self.weeks],
            chain_counts=[int(chain.get(w, 0)) for w in self.weeks],
            flagged_weeks=flagged,
        )

    def store_ids_in_text(self, text: str) -> list[str]:
        """Stores whose locality the text names (same rule as the scorer), longest names first."""
        return self.resolver.names_in_text(text)

    def issue_catalogue(self) -> list[dict]:
        """Actionable issue types with owner and description."""
        return [
            dict(
                id=r.issue_type_id,
                name=r.issue_type,
                owner=r.owner_function,
                floor=r.policy_severity_floor,
                description=str(r.description),
            )
            for r in self.data.taxonomy.reset_index().itertuples()
            if r.issue_type_id not in C.NON_ISSUE
        ]

    def store_overview(self, store_id: str, week: str) -> dict:
        """Cached status of one store for a week."""
        return self._memo("store", (store_id, week), lambda: self._store_overview(store_id, week))

    def _store_overview(self, store_id: str, week: str) -> dict:
        """Everything the store page and the assistant show for one store and week."""
        prev = str((pd.Timestamp(week) - pd.Timedelta(days=7)).date())
        r = self.rows
        cur = r[(r["store"] == store_id) & (r["week"] == week) & (r["actionable"] == 1) & ~r["itype"].isin(C.NON_ISSUE)]
        before = r[(r["store"] == store_id) & (r["week"] == prev) & (r["actionable"] == 1) & ~r["itype"].isin(C.NON_ISSUE)]
        before_counts = before.groupby("itype").size()
        tax = self.data.taxonomy
        top = []
        for itype, g in cur.groupby("itype"):
            sev = C.SEVERITIES[severity_rank(itype, g["severity"])]
            n_prev = int(before_counts.get(itype, 0))
            top.append(
                dict(
                    issue_type=itype,
                    issue=str(tax.loc[itype, "issue_type"]),
                    owner=str(tax.loc[itype, "owner_function"]),
                    severity=sev,
                    count=len(g),
                    previous=n_prev,
                    trend=trend_arrow(len(g), n_prev),
                    next_step=next_step(itype, str(tax.loc[itype, "owner_function"]), False),
                    safety=itype in SAFETY_TYPES,
                    quotes=[redact(t[:200]) for t in g.sort_values("conf", ascending=False)["text"].drop_duplicates().head(2)],
                )
            )
        top.sort(key=lambda t: (-C.SEV_RANK[t["severity"]], -t["count"], t["issue_type"]))
        history = self.flags[self.flags["store_id"] == store_id].sort_values("as_of_week_start")
        series = [int(self._store_week_actionable.get((store_id, w), 0)) for w in self.weeks]
        return dict(
            store_id=store_id,
            name=self.store_name[store_id],
            region=self.store_region[store_id],
            week=week,
            reports_this_week=len(cur),
            reports_previous_week=len(before),
            top=top[:5],
            weeks=self.weeks,
            weekly_reports=series,
            flags_this_week=[f for f in self.flags_for(week) if f["store_id"] == store_id],
            flag_history=[
                dict(week=f.as_of_week_start, issue=str(tax.loc[f.issue_type_id, "issue_type"])) for f in history.itertuples()
            ],
        )

    def classify(self, text: str, channel: str) -> dict:
        """Classify one comment with the live model and explain it with key terms."""
        text = clean_input(text, 2000)
        df = pd.DataFrame([dict(feedback_id="input", channel=channel, text=text, store_id=None)])
        store = self.resolver.resolve(None, text)
        pred_frame, proba, why = self.clf.analyse(df, pd.Series([store], index=df.index, dtype=object))
        pred = pred_frame.iloc[0]
        itype = str(pred["issue_type_id"])
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
        """The precision statement, read from out/validation.json or computed once."""
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

    def report(self) -> dict:
        """The evaluation report: read from out/report.json when `main.py briefs` wrote it, otherwise computed once."""
        path = self._submission_dir.parent / "out" / "report.json"
        with self._lock:
            if self._report is None:
                if path.exists():
                    self._report = json.loads(path.read_text(encoding="utf-8"))
        if self._report is None:
            computed = build_report(
                self.data, self.resolver, self.rows, self.flags, self.validation(), load_incidents(self._data_dir)
            )
            with self._lock:
                self._report = computed
        return self._report

    def report_html(self) -> str:
        """The evaluation report page."""
        return render_report(self.report())

    def dataset_info(self) -> dict:
        fb = self.data.feedback
        min_date = str(fb["created_at"].min()) if not fb.empty else ""
        max_date = str(fb["created_at"].max()) if not fb.empty else ""
        return {
            "is_custom": self.is_custom,
            "name": self.custom_name if self.is_custom else "Default (Original Pack)",
            "row_count": len(fb),
            "date_min": min_date[:10] if min_date else "",
            "date_max": max_date[:10] if max_date else "",
            "stores_active": int(self.rows["store"].dropna().nunique()) if "store" in self.rows.columns else 0,
            "weeks_count": len(self.weeks),
        }

    def load_custom_dataset(self, feedback_df: pd.DataFrame, name: str = "Uploaded Dataset") -> dict:
        """Hot-swap the active dataset to the uploaded feedback records."""
        with self._lock:
            fb = feedback_df.copy()
            fb["created_at"] = pd.to_datetime(fb["created_at"])
            fb["feedback_id"] = fb["feedback_id"].astype(str)
            fb["channel"] = fb["channel"].astype(str)
            fb["store_id"] = fb["store_id"].astype(str)
            fb["text"] = fb["text"].astype(str)

            from ..io import week_start_of
            fb_weeks = sorted(week_start_of(fb["created_at"]).unique())
            if not fb_weeks:
                raise ValueError("Uploaded dataset has no valid dates.")

            cal_rows = [{"week_index": i, "week_start": w, "labelled_period": "test"} for i, w in enumerate(fb_weeks, 1)]
            cal_df = pd.DataFrame(cal_rows)

            custom_data = Data(
                feedback=fb,
                labels=self._default_data.labels,
                stores=self._default_data.stores,
                taxonomy=self._default_data.taxonomy,
                calendar=cal_df,
            )

            end = fb["created_at"].max() + pd.Timedelta(seconds=1)
            new_rows = prepare_rows(custom_data, end, self.resolver, clf=self.clf)

            from ..pipeline import emit_flags
            try:
                new_flags = emit_flags(new_rows, custom_data, self.resolver, fb_weeks)
            except Exception:
                new_flags = pd.DataFrame(columns=C.FLAG_COLS)

            if "confidence" in new_flags.columns and not new_flags.empty:
                new_flags["confidence"] = new_flags["confidence"].astype(float)

            self.data = custom_data
            self.rows = new_rows
            self.flags = new_flags
            self.weeks = fb_weeks
            self.test_weeks = fb_weeks
            self.is_custom = True
            self.custom_name = name
            self._brief_cache.clear()
            self._memos.clear()
            self._index_rows()

            return self.dataset_info()

    def reset_to_default(self) -> dict:
        """Restore the default original dataset."""
        with self._lock:
            self.data = self._default_data
            self.rows = self._default_rows
            self.flags = self._default_flags
            self.weeks = list(self._default_weeks)
            self.test_weeks = list(self._default_test_weeks)
            self.is_custom = False
            self.custom_name = ""
            self._brief_cache.clear()
            self._memos.clear()
            self._index_rows()
            return self.dataset_info()
