"""Acceptance tests named after the requirements (see REQUIREMENTS_TRACEABILITY.md). They run on the real pack data and the
shipped submission, and skip when the pack data is not present."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from voice_of_store import config as C
from voice_of_store.brief import TOP_N, build_region_week, render_html
from voice_of_store.dedup import summarise
from voice_of_store.io import load_data
from voice_of_store.pipeline import prepare_rows
from voice_of_store.routing import ESCALATION_RULE, SAFETY_TYPES
from voice_of_store.stores import StoreResolver

ROOT = Path(__file__).resolve().parents[2]
DATA, SUB = ROOT / "data", ROOT / "submission"
pytestmark = pytest.mark.skipif(not (DATA / "feedback.csv").exists(), reason="pack data not present")
SEVERITIES = {"low", "medium", "high", "critical"}


@pytest.fixture(scope="module")
def world():
    data = load_data(DATA)
    resolver = StoreResolver(data.stores)
    rows = prepare_rows(data, data.feedback["created_at"].max() + pd.Timedelta(seconds=1), resolver)
    flags = pd.read_csv(SUB / "R5_emerging_flags.csv", dtype=str)
    return data, rows, flags


@pytest.fixture(scope="module")
def latest_briefs(world):
    data, rows, flags = world
    week = data.calendar["week_start"].iloc[-1]
    return week, {
        r: build_region_week(rows, flags, data.stores, data.taxonomy, r, week) for r in sorted(data.stores["region"].unique())
    }


def test_pack_every_row_is_predicted_once_with_valid_values(world):
    data, _, _ = world
    pred = pd.read_csv(SUB / "R5_predictions.csv", dtype=str)
    assert set(pred["feedback_id"]) == set(data.feedback["feedback_id"]) and not pred["feedback_id"].duplicated().any()
    assert pred["issue_type_id"].isin(data.taxonomy.index).all() and pred["severity"].isin(SEVERITIES).all()
    assert pred["actionable"].isin(["0", "1"]).all()


def test_pack_flags_cite_two_existing_ids_within_the_budget(world):
    data, _, flags = world
    ids = set(data.feedback["feedback_id"])
    cited = flags["evidence_feedback_ids"].str.split(";")
    assert (cited.map(len) >= 2).all() and cited.map(lambda c: set(c) <= ids).all()
    assert len(flags) / len(data.calendar) <= 3
    assert not flags.duplicated(["as_of_week_start", "store_id", "issue_type_id"]).any()


def test_pack_detector_command_shape():
    assert (
        SUB / "detector_cmd.txt"
    ).read_text().strip() == "python FULL_CODE/detect.py --feedback {feedback} --as-of {asof} --out {out}"


def test_d1_brief_per_region_has_top5_with_quotes_stores_and_trend(latest_briefs):
    _, briefs = latest_briefs
    assert len(briefs) == 5
    for region, entries in briefs.items():
        top = [e for e in entries if not e["beyond_top5"]]
        assert 1 <= len(top) <= TOP_N, region
        for e in entries:
            assert e["quotes"] and e["stores"] and e["trend"] in {"↑", "↓", "→"}, (region, e["issue"])


def test_d2_every_issue_has_owner_severity_and_the_rule_is_stated(world, latest_briefs):
    data, _, _ = world
    week, briefs = latest_briefs
    owners = set(data.taxonomy["owner_function"])
    for region, entries in briefs.items():
        for e in entries:
            assert e["owner"] in owners and e["severity"] in SEVERITIES
        assert ESCALATION_RULE in render_html(region, week, entries, 1).replace("&#x27;", "'").replace("&amp;", "&")


def test_fr07_policy_floor_and_safety_types_are_high_on_every_predicted_row(world):
    data, _, _ = world
    pred = pd.read_csv(SUB / "R5_predictions.csv", dtype=str)
    floor = data.taxonomy["policy_severity_floor"].map({"low": 0, "medium": 1, "high": 2})
    rank = pred["severity"].map({"low": 0, "medium": 1, "high": 2, "critical": 3})
    assert (rank >= pred["issue_type_id"].map(floor)).all()
    assert (rank[pred["issue_type_id"].isin(SAFETY_TYPES)] >= 2).all()


def test_fr07_safety_types_are_never_dropped_from_a_brief(world):
    data, rows, flags = world
    for week in data.calendar["week_start"].tail(4):
        for region in data.stores["region"].unique():
            entries = build_region_week(rows, flags, data.stores, data.taxonomy, region, week)
            ids = set(data.stores[data.stores["region"] == region]["store_id"])
            cur = rows[(rows["week"] == week) & (rows["actionable"] == 1) & rows["store"].isin(ids)]
            present = {e["issue_type"] for e in entries}
            assert set(cur["itype"][cur["itype"].isin(SAFETY_TYPES)]) <= present, (region, week)


def test_fr08_and_fr09_each_issue_carries_evidence_status_and_next_step(latest_briefs):
    _, briefs = latest_briefs
    for entries in briefs.values():
        for e in entries:
            assert e["count"] >= 1 and e["by_channel"] and e["first_seen"] and 0 <= e["confidence"] <= 1
            assert e["tier"] in {"UNVERIFIED", "CORROBORATED", "POSSIBLE SYSTEMIC"} and e["status"] and e["next_step"]
            assert e["dedup"]["incidents"] <= e["dedup"]["reports"]


def test_fr10_store_size_is_used_and_the_limit_is_disclosed(world, latest_briefs):
    data, _, _ = world
    assert "avg_weekly_footfall" in data.stores.columns
    week, briefs = latest_briefs
    region, entries = next((r, e) for r, e in briefs.items() if e)
    page = render_html(region, week, entries, 1)
    assert "10,000" in page and "approximate" in page and "UNVERIFIED" in page


def test_fr11_small_rising_issues_are_flagged_outside_the_top_five(world):
    data, rows, flags = world
    low_volume = 0
    for f in flags.itertuples():
        top = {
            e["issue_type"]
            for region in [data.stores.set_index("store_id").loc[f.store_id, "region"]]
            for e in build_region_week(rows, flags, data.stores, data.taxonomy, region, f.as_of_week_start)[:TOP_N]
        }
        low_volume += f.issue_type_id not in top
    assert low_volume >= 1, "at least one flag should concern an issue that is not in its region's top five"


def test_stretch_deduplication_collapses_reports_into_incidents(world):
    _, rows, _ = world
    act = rows[(rows["actionable"] == 1) & ~rows["itype"].isin(C.NON_ISSUE) & rows["store"].notna()]
    s = summarise(act)
    assert 0 < s["incidents"] < s["reports"]
