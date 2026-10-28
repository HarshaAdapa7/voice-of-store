"""Edge cases: empty, invalid, boundary and missing inputs (guideline rule 6)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from voice_of_store import config as C
from voice_of_store.brief import _severity_rank, _tier, _trend, build_region_week, render_html
from voice_of_store.classify import FeedbackClassifier, NotEnoughLabels
from voice_of_store.detect import expected_counts, run_statistic, weekly_counts
from voice_of_store.evidence import belongs
from voice_of_store.io import DataError, load_data, monday_of, week_start_of
from voice_of_store.routing import action_window
from voice_of_store.stores import StoreResolver
from voice_of_store.text import clean_input, normalise

ROOT = Path(__file__).resolve().parents[2]


# ---- io -------------------------------------------------------------------------------------------------------------
def _write_pack(folder: Path, **overrides: str) -> None:
    files = {
        "feedback.csv": "feedback_id,channel,created_at,store_id,rating,text\nF1,in_app,2026-03-30T08:00:00,S1,5,hello\n",
        "feedback_labels_train.csv": "feedback_id,issue_type_id,severity,actionable\nF1,NI01,low,0\n",
        "store_master.csv": "store_id,store_name,region,avg_weekly_footfall\nS1,Saffron Market Kothrud,West,1000\n",
        "issue_taxonomy.csv": "issue_type_id,issue_type,owner_function,policy_severity_floor\nNI01,Praise,None,low\n",
        "week_calendar.csv": "week_index,week_start,week_end,labelled_period\n1,2026-03-30,2026-04-05,train\n",
    }
    files.update(overrides)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")


def test_load_data_accepts_minimal_valid_pack(tmp_path):
    _write_pack(tmp_path)
    d = load_data(tmp_path)
    assert len(d.feedback) == 1 and d.taxonomy.index.tolist() == ["NI01"]


@pytest.mark.parametrize(
    "name,content,fragment",
    [
        ("feedback.csv", "feedback_id,channel\nF1,in_app\n", "missing columns"),
        ("feedback.csv", "feedback_id,channel,created_at,store_id,text\nF1,in_app,not-a-date,S1,hi\n", "unreadable timestamps"),
        (
            "feedback.csv",
            "feedback_id,channel,created_at,store_id,text\nF1,in_app,2026-03-30T08:00:00,S1,a\nF1,in_app,2026-03-30T09:00:00,S1,b\n",
            "duplicate",
        ),
        ("feedback_labels_train.csv", "feedback_id,issue_type_id,severity,actionable\nF1,IT99,low,0\n", "unknown issue types"),
        ("feedback_labels_train.csv", "feedback_id,issue_type_id,severity,actionable\nF1,NI01,low,2\n", "actionable"),
        ("store_master.csv", "store_id,store_name\nS1,x\n", "missing columns"),
        ("week_calendar.csv", "", "cannot parse"),
    ],
)
def test_load_data_rejects_bad_files_with_clear_message(tmp_path, name, content, fragment):
    _write_pack(tmp_path, **{name: content})
    with pytest.raises(DataError, match=fragment):
        load_data(tmp_path)


def test_load_data_missing_file_names_the_file(tmp_path):
    _write_pack(tmp_path)
    (tmp_path / "store_master.csv").unlink()
    with pytest.raises(DataError, match="store_master.csv"):
        load_data(tmp_path)


def test_dates_and_weeks_at_boundaries():
    assert monday_of("2026-03-30") == pd.Timestamp("2026-03-30")  # a Monday maps to itself
    assert monday_of("2026-04-05") == pd.Timestamp("2026-03-30")  # the Sunday maps to the Monday before
    assert monday_of("2026-04-06") == pd.Timestamp("2026-04-06")
    for bad in ("garbage", "", None):
        with pytest.raises(DataError):
            monday_of(bad)
    ts = pd.Series(pd.to_datetime(["2026-04-05T23:59:59", "2026-04-06T00:00:00"]))
    assert week_start_of(ts).tolist() == ["2026-03-30", "2026-04-06"]  # Sunday 23:59:59 stays, Monday 00:00 moves on


# ---- text and stores ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["", "   ", "😡😡", "ñandú ¿qué?", "x" * 10000, "\x00\x07", "தமிழ் text", None])
def test_text_helpers_never_crash(raw):
    assert isinstance(normalise(raw), str)
    assert len(clean_input(raw, 50)) <= 50


def test_resolver_edge_cases():
    stores = pd.DataFrame({"store_id": ["A", "B"], "store_name": ["Saffron Market Salt Lake", "Saffron Hyper Salt Lake City"]})
    r = StoreResolver(stores)
    assert r.resolve(None, "") is None
    assert r.resolve("ZZZ", "no place") is None  # recorded id not in the master is not trusted
    assert r.resolve(None, "queue at SALT LAKE CITY today") == "B"  # the longer locality wins, as the scorer's rule needs
    assert r.resolve(float("nan"), "salt lake") == "A"


def test_evidence_rule_matches_the_scorer_for_missing_store():
    loc = {"A": "kothrud"}
    assert belongs("A", "any", "A", loc) and not belongs("B", "kothrud", "A", loc)
    assert belongs(None, "Long queue KOTHRUD", "A", loc) and not belongs(None, "long queue", "A", loc)
    assert belongs("", "kothrud", "A", loc)


# ---- detector -------------------------------------------------------------------------------------------------------
def test_detector_all_zero_and_too_short_histories():
    zeros = np.zeros((4, 3, 10))
    assert run_statistic(zeros, np.full(4, 100.0))["flag"].sum() == 0
    short = np.ones((4, 3, 2))  # fewer weeks than the minimum baseline
    assert run_statistic(short, np.full(4, 100.0))["flag"].sum() == 0
    assert np.isfinite(expected_counts(np.ones((4, 3, 6)), np.full(4, 100.0), 5, dict(history=14, prior=6.0))).all()


def test_detector_ignores_one_off_blips_and_needs_two_reports():
    c = np.zeros((6, 2, 14))
    c[:, :, :] = 0.4
    c[1, 0, 10] = 1  # a single extra report
    assert run_statistic(np.round(c), np.full(6, 1000.0))["flag"][1, 0].sum() == 0


def test_chain_wide_spike_is_not_a_store_flag():
    rng = np.random.default_rng(2)
    c = rng.poisson(0.5, size=(40, 1, 16)).astype(float)
    c[:, 0, 12] += 2  # every store rises together (festival, outage)
    r = run_statistic(c, np.full(40, 1000.0), tie_rank=np.arange(40))
    assert r["flag"][:, 0, 12].sum() <= 3  # capped and, with the chain factor, rare


def test_weekly_counts_ignores_unknown_ids():
    rows = pd.DataFrame({"store": ["S1", "S9", "S1"], "itype": ["IT01", "IT01", "IT77"], "week": ["w1", "w1", "w1"]})
    out = weekly_counts(rows, ["S1"], ["IT01"], ["w1"])
    assert out.sum() == 1


# ---- classifier -----------------------------------------------------------------------------------------------------
def test_classifier_needs_labels_and_handles_odd_text(data_dir):
    d = load_data(data_dir)
    with pytest.raises(NotEnoughLabels):
        FeedbackClassifier(d.taxonomy).fit(d.feedback, d.labels.iloc[0:0])
    res = StoreResolver(d.stores)
    clf = FeedbackClassifier(d.taxonomy).fit(d.feedback, d.labels)
    odd = pd.DataFrame(
        {
            "feedback_id": list("abcd"),
            "channel": ["in_app", "call_centre_ticket", "online_review", "staff_shift_note"],
            "text": ["", "😡😡😡", "x" * 3000, "[inaudible]"],
            "store_id": [None] * 4,
        }
    )
    p = clf.predict(odd, res.resolve_frame(odd))
    assert len(p) == 4 and p["issue_type_id"].isin(C.ISSUE_TYPES).all() and p["severity"].isin(C.SEVERITIES).all()
    assert p["type_confidence"].between(0, 1).all()
    assert (p["actionable"] == 0).all()  # no store and no clear issue: never actionable


# ---- brief and routing ----------------------------------------------------------------------------------------------
def test_trend_boundaries():
    assert _trend(5, 4) == "→" and _trend(5, 3) == "↑" and _trend(3, 5) == "↓" and _trend(0, 0) == "→"
    assert _trend(20, 18) == "→"  # +2 but under 25%: noise
    assert _trend(10, 8) == "↑"  # exactly +25% and +2 counts as a rise


def test_tier_and_severity_rules():
    one = pd.DataFrame({"store": ["S1"], "channel": ["in_app"], "text": ["a"]})
    assert _tier(one) == "UNVERIFIED"
    two = pd.DataFrame({"store": ["S1", "S1"], "channel": ["in_app", "staff_shift_note"], "text": ["a", "b"]})
    assert _tier(two) == "CORROBORATED"
    three_stores = pd.DataFrame({"store": ["S1", "S2", "S3"], "channel": ["in_app"] * 3, "text": ["a", "b", "c"]})
    assert _tier(three_stores) == "POSSIBLE SYSTEMIC"
    sev = pd.Series(["low"] * 9 + ["critical"])
    assert _severity_rank("IT10", sev) == C.SEV_RANK["critical"]  # safety type: worst report counts
    assert _severity_rank("IT14", sev) == C.SEV_RANK["low"]  # others: one outlier does not decide


def test_action_window_policy():
    assert action_window("critical", "IT14", False) == "same day"
    assert action_window("low", "IT10", False) == "same day"  # safety types are same-day by policy
    assert action_window("low", "IT14", True) == "within 48 hours"
    assert action_window("low", "IT14", False) == "weekly cycle"


def test_empty_week_renders_and_escapes():
    page = render_html("South", "2026-08-03", [], 0)
    assert "No actionable issues this week." in page and "<script" not in page
    nasty = render_html("<img src=x onerror=alert(1)>", "2026-08-03", [], 0)
    assert "<img" not in nasty


def test_brief_for_empty_inputs():
    rows = pd.DataFrame(
        {
            c: pd.Series(dtype=object)
            for c in ("store", "itype", "severity", "actionable", "week", "text", "channel", "conf", "created_at", "feedback_id")
        }
    )
    stores = pd.DataFrame({"store_id": ["S1"], "store_name": ["Saffron Market A"], "region": ["West"]})
    tax = pd.DataFrame({"issue_type": ["x"], "owner_function": ["Store Ops"]}, index=["IT01"])
    flags = pd.DataFrame(columns=C.FLAG_COLS)
    assert build_region_week(rows, flags, stores, tax, "West", "2026-08-03") == []


# ---- command line ---------------------------------------------------------------------------------------------------
def test_detector_cli_reports_problems_without_traceback(tmp_path):
    cmd = [sys.executable, str(ROOT / "FULL_CODE" / "detect.py"), "--out", str(tmp_path / "o.csv")]
    r = subprocess.run(
        [*cmd, "--feedback", str(tmp_path / "absent.csv"), "--as-of", "2026-05-11"], capture_output=True, text=True
    )
    assert r.returncode != 0 and "error:" in r.stderr and "Traceback" not in r.stderr
    _write_pack(tmp_path)
    r = subprocess.run(
        [*cmd, "--feedback", str(tmp_path / "feedback.csv"), "--as-of", "not-a-date"], capture_output=True, text=True
    )
    assert r.returncode != 0 and "error:" in r.stderr and "Traceback" not in r.stderr


def test_detector_cli_with_too_few_labels_explains_itself(tmp_path):
    _write_pack(tmp_path)  # one labelled row: far below the minimum
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "FULL_CODE" / "detect.py"),
            "--feedback",
            str(tmp_path / "feedback.csv"),
            "--as-of",
            "2026-03-31",
            "--out",
            str(tmp_path / "flags.csv"),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "labelled rows" in r.stderr and "Traceback" not in r.stderr


def test_main_dispatcher_lists_commands():
    r = subprocess.run([sys.executable, str(ROOT / "FULL_CODE" / "main.py")], capture_output=True, text=True)
    assert r.returncode == 0 and "submission" in r.stdout and "serve" in r.stdout
    assert subprocess.run([sys.executable, str(ROOT / "FULL_CODE" / "main.py"), "bogus"], capture_output=True).returncode == 2
