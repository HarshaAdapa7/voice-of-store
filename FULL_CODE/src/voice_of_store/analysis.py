"""Deeper evaluation behind the reports: where the classifier is weak, how precise escalation is at each confidence level,
how early the detector fires on the public worked example, how much de-duplication collapses, and data quality.

Everything here is computed from the public pack with the same code the product uses. Figures describe the public labelled
sample (which over-represents rare types), not the full stream, and the page that shows them says so.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from . import config as C
from .dedup import cluster_incidents
from .io import Data, week_start_of
from .pipeline import emit_flags
from .report import split_predictions, wilson
from .routing import SAFETY_TYPES
from .stores import StoreResolver


def _ci(k: int, n: int) -> list[float]:
    lo, hi = wilson(int(k), int(n))
    return [round(float(lo), 4), round(float(hi), 4)]


def classification_detail(te: pd.DataFrame, p: pd.DataFrame, taxonomy: pd.DataFrame) -> dict:
    """Per-type scores, the most frequent confusions, severity confusion and a per-channel view."""
    y, yp = te["issue_type_id"].to_numpy(), p["issue_type_id"].to_numpy()
    labels = sorted(set(y) | set(yp))
    pr, rc, f1, sup = precision_recall_fscore_support(y, yp, labels=labels, zero_division=0)
    per_type = [
        dict(
            id=t,
            name=str(taxonomy.loc[t, "issue_type"]),
            support=int(n),
            precision=round(float(a), 3),
            recall=round(float(b), 3),
            f1=round(float(c), 3),
        )
        for t, a, b, c, n in zip(labels, pr, rc, f1, sup, strict=True)
    ]
    wrong = pd.Series(list(zip(y, yp, strict=True)))
    wrong = wrong[[a != b for a, b in wrong]].value_counts().head(8)
    confusions = [dict(true=a, predicted=b, count=int(n)) for (a, b), n in wrong.items()]
    sev = C.SEVERITIES
    cm = confusion_matrix(te["severity"], p["severity"].to_numpy(), labels=sev)
    channels = []
    for ch, g in te.assign(pred=p["issue_type_id"].to_numpy(), pact=p["actionable"].to_numpy()).groupby("channel"):
        pa = g["pact"] == 1
        channels.append(
            dict(
                channel=str(ch),
                n=len(g),
                issue_accuracy=round(float((g["issue_type_id"] == g["pred"]).mean()), 3),
                actionable_precision=round(float((g.loc[pa, "actionable"] == 1).mean()), 3) if pa.any() else None,
            )
        )
    weakest = sorted((t for t in per_type if t["support"] >= 5), key=lambda t: t["f1"])[:5]
    return dict(
        per_type=per_type,
        weakest=weakest,
        confusions=confusions,
        severity_labels=sev,
        severity_confusion=cm.tolist(),
        channels=channels,
    )


def escalation_detail(te: pd.DataFrame, p: pd.DataFrame, taxonomy: pd.DataFrame) -> dict:
    """Precision of what the system escalates (actionable and high or critical), by owner and by confidence, plus recall
    of the safety types (the policy says these must not be missed)."""
    sev, act = p["severity"].to_numpy(), p["actionable"].to_numpy()
    esc = (act == 1) & np.isin(sev, ["high", "critical"])
    truth = te["actionable"].to_numpy() == 1
    conf = p["type_confidence"].to_numpy()
    by_conf = []
    for th in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7):
        keep = esc & (conf >= th)
        n, k = int(keep.sum()), int(truth[keep].sum())
        by_conf.append(dict(threshold=th, escalated=n, precision=round(k / n, 4) if n else None, ci=_ci(k, n) if n else None))
    owner = p["issue_type_id"].map(taxonomy["owner_function"]).to_numpy()
    by_owner = []
    for o in sorted(set(owner[esc])):
        keep = esc & (owner == o)
        n, k = int(keep.sum()), int(truth[keep].sum())
        by_owner.append(dict(owner=str(o), escalated=n, precision=round(k / n, 4), ci=_ci(k, n)))
    is_safety = te["issue_type_id"].isin(SAFETY_TYPES).to_numpy() & truth
    caught = is_safety & np.isin(p["issue_type_id"].to_numpy(), SAFETY_TYPES) & np.isin(sev, ["high", "critical"]) & (act == 1)
    n_s, k_s = int(is_safety.sum()), int(caught.sum())
    missed = is_safety & ~caught
    where = pd.Series(
        [
            ("another safety type, high or above" if (t in SAFETY_TYPES and sv in ("high", "critical")) else "a non-safety type")
            if a == 1
            else "not actionable"
            for t, sv, a in zip(p["issue_type_id"].to_numpy()[missed], sev[missed], act[missed], strict=True)
        ],
        dtype=object,
    ).value_counts()
    return dict(
        by_confidence=by_conf,
        by_owner=by_owner,
        safety_recall=dict(
            truly_safety=n_s,
            caught=k_s,
            recall=round(k_s / n_s, 4) if n_s else None,
            ci=_ci(k_s, n_s) if n_s else None,
            missed_as={str(k): int(v) for k, v in where.items()},
        ),
    )


def detection_example(data: Data, rows: pd.DataFrame, resolver: StoreResolver, inc: pd.DataFrame | None) -> dict:
    """Replay the detector over the whole calendar and read off the public worked incident(s): first flag at that store for
    that type, the pack's naive-detector week, and the lead in weeks. The statistic is sequential, so each week's flag uses
    only data up to that week. Flags elsewhere are counted so the volume cost of the lead is visible."""
    if inc is None or inc.empty:
        return dict(incidents=[], other_flags=0, weeks=0)
    cal = data.calendar["week_start"].tolist()
    flags = emit_flags(rows, data, resolver, cal)
    out = []
    for r in inc.itertuples():
        stores = str(r.store_ids).split(";")
        hit = flags[(flags["store_id"].isin(stores)) & (flags["issue_type_id"] == r.issue_type_id)].sort_values(
            "as_of_week_start"
        )
        first = hit["as_of_week_start"].iloc[0] if len(hit) else None
        lead = int((pd.Timestamp(r.naive_detect_week_start) - pd.Timestamp(first)).days // 7) if first else None
        out.append(
            dict(
                incident=str(r.incident_id),
                store=str(r.store_ids),
                issue_type=str(r.issue_type_id),
                onset=str(r.onset_week_start),
                naive_detection=str(r.naive_detect_week_start),
                our_first_flag=first,
                lead_weeks=lead,
                flagged_weeks=hit["as_of_week_start"].tolist(),
            )
        )
    matched = sum(len(o["flagged_weeks"]) for o in out)
    return dict(
        incidents=out,
        other_flags=int(len(flags) - matched),
        weeks=len(cal),
        flags_per_week=round(len(flags) / max(1, len(cal)), 2),
    )


def dedup_detail(rows: pd.DataFrame) -> dict:
    """How many reports collapse into incidents (72-hour gap rule, same store and type), by week and by channel mix."""
    r = rows[(rows["actionable"] == 1) & ~rows["itype"].isin(C.NON_ISSUE) & rows["store"].notna()]
    inc = cluster_incidents(r)
    m = r.merge(inc, on="feedback_id")
    per = m.groupby("incident").agg(n=("feedback_id", "size"), channels=("channel", "nunique"))
    return dict(
        reports=int(len(r)),
        incidents=int(len(per)),
        reports_per_incident=round(float(len(r) / max(1, len(per))), 2),
        multi_report_incidents=int((per["n"] >= 2).sum()),
        cross_channel_incidents=int((per["channels"] >= 2).sum()),
        four_channel_incidents=int((per["channels"] >= 4).sum()),
        note="Heuristic: same store and type within 72 hours of the previous report. There is no ground truth for duplicates.",
    )


def weekly_overview(data: Data, rows: pd.DataFrame, flags: pd.DataFrame) -> list[dict]:
    """One line per week: volume, actionable reports, incidents after de-duplication, safety-type reports and flags."""
    base = rows[rows["store"].notna() & ~rows["itype"].isin(C.NON_ISSUE)]
    act = base[base["actionable"] == 1]
    inc = cluster_incidents(act)
    inc_week = act.merge(inc, on="feedback_id").groupby("week")["incident"].nunique()
    out = []
    for w in data.calendar["week_start"]:
        wk = rows[rows["week"] == w]
        a = act[act["week"] == w]
        out.append(
            dict(
                week=w,
                records=int(len(wk)),
                actionable=int(len(a)),
                incidents=int(inc_week.get(w, 0)),
                safety_reports=int(a["itype"].isin(SAFETY_TYPES).sum()),
                flags=int((flags["as_of_week_start"] == w).sum()),
                labelled=bool(data.calendar.set_index("week_start").loc[w, "labelled_period"] != "test"),
            )
        )
    return out


def data_quality(data: Data, rows: pd.DataFrame) -> dict:
    fb = data.feedback
    wk = week_start_of(fb["created_at"])
    return dict(
        records=int(len(fb)),
        weeks=int(wk.nunique()),
        by_channel={str(k): int(v) for k, v in fb["channel"].value_counts().items()},
        store_resolved_share=round(float(rows["store"].notna().mean()), 4),
        labelled_rows=int(len(data.labels)),
        non_issue_share=round(float(rows["itype"].isin(C.NON_ISSUE).mean()), 4),
        stores=int(data.stores["store_id"].nunique()),
        safety_no_store=int((rows["itype"].isin(SAFETY_TYPES) & rows["store"].isna()).sum()),
        footfall_available=bool("avg_weekly_footfall" in data.stores.columns),
    )


def build_report(
    data: Data, resolver: StoreResolver, rows: pd.DataFrame, flags: pd.DataFrame, validation: dict, incidents: pd.DataFrame | None
) -> dict:
    te, p = split_predictions(data, resolver)
    return dict(
        validation=validation,
        classification=classification_detail(te, p, data.taxonomy),
        escalation=escalation_detail(te, p, data.taxonomy),
        detection=detection_example(data, rows, resolver, incidents),
        dedup=dedup_detail(rows),
        weeks=weekly_overview(data, rows, flags),
        quality=data_quality(data, rows),
    )
