"""The evaluation report: structure on real data, honest wording, and safe rendering of hostile strings."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from voice_of_store.report_page import render_report

XSS = "<script>alert(1)</script>"


def _minimal() -> dict:
    ci = [0.9, 0.99]
    return dict(
        validation=dict(
            classification=0.9,
            n_train=10,
            n_test=5,
            n_pred_actionable=100,
            precision_actionable=0.95,
            n_pred_actionable_high=50,
            precision_actionable_high=0.97,
            ci_actionable=ci,
            ci_actionable_high=ci,
        ),
        escalation=dict(
            by_confidence=[dict(threshold=0.0, escalated=50, precision=0.97, ci=ci)],
            by_owner=[dict(owner=XSS, escalated=5, precision=1.0, ci=ci)],
            safety_recall=dict(truly_safety=10, caught=9, recall=0.9, ci=ci, missed_as={XSS: 1}),
        ),
        classification=dict(
            per_type=[],
            weakest=[dict(id="IT01", name=XSS, support=9, precision=0.5, recall=0.5, f1=0.5)],
            confusions=[dict(true="IT01", predicted="IT02", count=3)],
            severity_labels=["low", "medium", "high", "critical"],
            severity_confusion=[[1, 0, 0, 0]] * 4,
            channels=[dict(channel=XSS, n=4, issue_accuracy=0.9, actionable_precision=None)],
        ),
        detection=dict(
            incidents=[
                dict(
                    incident=XSS,
                    store="ST-1",
                    issue_type="IT17",
                    onset="2026-04-27",
                    naive_detection="2026-05-18",
                    our_first_flag=None,
                    lead_weeks=None,
                    flagged_weeks=[],
                )
            ],
            other_flags=3,
            weeks=26,
            flags_per_week=1.2,
        ),
        dedup=dict(
            reports=10,
            incidents=8,
            reports_per_incident=1.25,
            multi_report_incidents=2,
            cross_channel_incidents=1,
            four_channel_incidents=0,
            note=XSS,
        ),
        weeks=[dict(week="2026-04-06", records=10, actionable=5, incidents=4, safety_reports=1, flags=1, labelled=True)],
        quality=dict(
            records=100,
            weeks=26,
            by_channel={},
            store_resolved_share=0.8,
            labelled_rows=30,
            non_issue_share=0.2,
            stores=3,
            safety_no_store=2,
            footfall_available=True,
        ),
    )


def test_report_page_escapes_every_value_and_has_no_script():
    page = render_report(_minimal())
    assert "<script" not in page.lower() and "&lt;script&gt;" in page
    assert "onerror" not in page and "javascript:" not in page.lower()


def test_report_states_limits_and_does_not_overclaim():
    page = render_report(_minimal())
    for phrase in ("Feedback is unverified", "not a calibrated probability", "Only 30", "approximate", "not scored"):
        assert phrase in page
    assert "never" in page and "n/a" in page  # missing values are shown as such, not as zero


def test_report_survives_missing_incident_file():
    rep = copy.deepcopy(_minimal())
    rep["detection"] = dict(incidents=[], other_flags=0, weeks=0)
    assert "No worked-example incident file" in render_report(rep)


@pytest.fixture(scope="module")
def real_report():
    import pandas as pd

    from voice_of_store.analysis import build_report
    from voice_of_store.io import load_data, load_incidents
    from voice_of_store.pipeline import prepare_rows
    from voice_of_store.report import time_split_validation, wilson
    from voice_of_store.stores import StoreResolver

    root = Path(__file__).resolve().parents[2]
    if not (root / "data" / "feedback.csv").exists():
        pytest.skip("pack data not present")
    data = load_data(root / "data")
    res = StoreResolver(data.stores)
    rows = prepare_rows(data, data.feedback["created_at"].max() + pd.Timedelta(seconds=1), res)
    flags = pd.read_csv(root / "submission" / "R5_emerging_flags.csv", dtype=str)
    v = time_split_validation(data, res)
    v["ci_actionable"] = list(wilson(round(v["precision_actionable"] * v["n_pred_actionable"]), v["n_pred_actionable"]))
    v["ci_actionable_high"] = list(
        wilson(round(v["precision_actionable_high"] * v["n_pred_actionable_high"]), v["n_pred_actionable_high"])
    )
    return build_report(data, res, rows, flags, v, load_incidents(root / "data"))


def test_real_report_is_consistent(real_report):
    r = real_report
    conf = r["escalation"]["by_confidence"]
    assert [c["escalated"] for c in conf] == sorted(
        (c["escalated"] for c in conf), reverse=True
    )  # stricter threshold, fewer escalations
    assert conf[0]["escalated"] == r["validation"]["n_pred_actionable_high"]
    assert abs(conf[0]["precision"] - r["validation"]["precision_actionable_high"]) < 1e-3
    sr = r["escalation"]["safety_recall"]
    assert sr["caught"] + sum(sr["missed_as"].values()) == sr["truly_safety"]
    assert sum(sum(row) for row in r["classification"]["severity_confusion"]) == r["validation"]["n_test"]
    assert r["dedup"]["incidents"] <= r["dedup"]["reports"]
    assert len(r["weeks"]) == r["detection"]["weeks"] == 26
    d = r["detection"]["incidents"][0]
    assert d["incident"] == "EX-1" and d["lead_weeks"] is not None and d["lead_weeks"] >= 0


def test_real_report_renders(real_report):
    page = render_report(real_report)
    assert "Precision statement" in page and "Safety recall" in page and "<script" not in page
