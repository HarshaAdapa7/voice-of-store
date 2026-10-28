"""End-to-end checks on the real data folder (skipped when data/ is absent)."""

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from voice_of_store import config as C
from voice_of_store.evidence import belongs
from voice_of_store.io import load_data, monday_of
from voice_of_store.pipeline import emit_flags, prepare_rows, sunday_end
from voice_of_store.stores import StoreResolver

ROOT = Path(__file__).resolve().parents[2]
DETECT = ROOT / "FULL_CODE" / "detect.py"


def _flags(data, week, truncate=False):
    resolver = StoreResolver(data.stores)
    if truncate:
        data.feedback = data.feedback[data.feedback["created_at"] < sunday_end(monday_of(week))]
    rows = prepare_rows(data, sunday_end(monday_of(week)), resolver)
    return emit_flags(rows, data, resolver, [week]), rows, resolver


def test_future_rows_do_not_change_flags(data_dir):  # T30
    week = "2026-07-13"
    a, _, _ = _flags(load_data(data_dir), week)
    b, _, _ = _flags(load_data(data_dir), week, truncate=True)
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


def test_evidence_passes_scorer_rules(data_dir):  # T25/T26
    d = load_data(data_dir)
    week = "2026-05-11"
    flags, rows, resolver = _flags(d, week)
    assert len(flags) >= 1
    fb = d.feedback.set_index("feedback_id")
    end = sunday_end(monday_of(week))
    for f in flags.itertuples():
        ids = f.evidence_feedback_ids.split(";")
        assert len(ids) >= 2 and len(set(ids)) == len(ids)
        ok = 0
        for i in ids:
            r = fb.loc[i]
            same_week = monday_of(week) <= r["created_at"] < end
            lab = rows.set_index("feedback_id").loc[i, "itype"]
            ok += bool(
                belongs(r["store_id"] if isinstance(r["store_id"], str) else None, r["text"], f.store_id, resolver.locality)
                and same_week
                and lab == f.issue_type_id
            )
        assert ok >= 2


def _disguise(src: Path, dst: Path, shift_weeks: int):
    rng = np.random.default_rng(11)
    dst.mkdir()
    fb = pd.read_csv(src / "feedback.csv", dtype=str)
    st = pd.read_csv(src / "store_master.csv", dtype=str)
    lab = pd.read_csv(src / "feedback_labels_train.csv", dtype=str)
    cal = pd.read_csv(src / "week_calendar.csv")
    fid = {k: "FB-" + "".join(rng.choice(list("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"), 8)) for k in fb["feedback_id"]}
    sid = {k: "ST-" + "".join(rng.choice(list("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"), 5)) for k in st["store_id"]}
    delta = pd.Timedelta(weeks=shift_weeks)
    fb["created_at"] = (pd.to_datetime(fb["created_at"]) + delta).dt.strftime("%Y-%m-%dT%H:%M:%S")
    fb["feedback_id"] = fb["feedback_id"].map(fid)
    fb["store_id"] = fb["store_id"].map(sid)
    lab["feedback_id"] = lab["feedback_id"].map(fid)
    st["store_id"] = st["store_id"].map(sid)
    for c in ("week_start", "week_end"):
        cal[c] = (pd.to_datetime(cal[c]) + delta).dt.strftime("%Y-%m-%d")
    fb.to_csv(dst / "feedback.csv", index=False)
    lab.to_csv(dst / "feedback_labels_train.csv", index=False)
    st.to_csv(dst / "store_master.csv", index=False)
    cal.to_csv(dst / "week_calendar.csv", index=False)
    shutil.copy(src / "issue_taxonomy.csv", dst / "issue_taxonomy.csv")
    return fid, sid


def test_disguised_copy_gives_same_flags(data_dir, tmp_path):  # T31/T32
    week, shift = "2026-05-11", 7
    real = tmp_path / "real.csv"
    subprocess.run(
        [sys.executable, str(DETECT), "--feedback", str(data_dir / "feedback.csv"), "--as-of", week, "--out", str(real)],
        check=True,
        capture_output=True,
    )
    fid, sid = _disguise(data_dir, tmp_path / "disg", shift)
    new_week = str((pd.Timestamp(week) + pd.Timedelta(weeks=shift)).date())
    dis = tmp_path / "dis.csv"
    subprocess.run(
        [
            sys.executable,
            str(DETECT),
            "--feedback",
            str(tmp_path / "disg" / "feedback.csv"),
            "--as-of",
            new_week,
            "--out",
            str(dis),
        ],
        check=True,
        capture_output=True,
    )
    a, b = pd.read_csv(real), pd.read_csv(dis)
    assert len(a) == len(b)
    inv_f = {v: k for k, v in fid.items()}
    inv_s = {v: k for k, v in sid.items()}

    def key(df, mf, ms):
        return sorted(
            (ms(r.store_id), r.issue_type_id, tuple(sorted(mf(i) for i in r.evidence_feedback_ids.split(";"))))
            for r in df.itertuples()
        )

    assert key(a, lambda x: x, lambda x: x) == key(b, inv_f.get, inv_s.get)


def test_submission_files_if_present():  # T01/T02/T50 on the committed files
    sub = ROOT / "submission"
    if not (sub / "R5_predictions.csv").exists() or not (ROOT / "data" / "feedback.csv").exists():
        return
    from voice_of_store.io import validate_flags, validate_predictions

    fb = pd.read_csv(ROOT / "data" / "feedback.csv")
    assert validate_predictions(pd.read_csv(sub / "R5_predictions.csv"), fb["feedback_id"]) == []
    flags = pd.read_csv(sub / "R5_emerging_flags.csv")
    assert validate_flags(flags) == []
    cmd = (sub / "detector_cmd.txt").read_text().strip()
    assert cmd == "python FULL_CODE/detect.py --feedback {feedback} --as-of {asof} --out {out}"
    assert len(flags) / 13 <= C.MAX_FLAGS_PER_WEEK


def test_classifier_policy(data_dir):  # T10-T14: severity floor, non-issue low, IT27 at least medium, actionable gates
    d = load_data(data_dir)
    resolver = StoreResolver(d.stores)
    fb = d.feedback.copy()
    fb["store"] = resolver.resolve_frame(fb)
    from voice_of_store.classify import FeedbackClassifier

    clf = FeedbackClassifier(d.taxonomy).fit(fb, d.labels)
    sample = fb.sample(2000, random_state=1)
    p = clf.predict(sample, sample["store"])
    floor = p["issue_type_id"].map(d.taxonomy["policy_severity_floor"])
    assert (p["severity"].map(C.SEV_RANK) >= floor.map(C.SEV_RANK)).all()
    assert (p.loc[p["issue_type_id"].isin(C.NON_ISSUE), "severity"] == "low").all()
    assert (p.loc[p["issue_type_id"] == "IT27", "severity"].map(C.SEV_RANK) >= 1).all()
    assert (p.loc[p["issue_type_id"].isin(C.NON_ISSUE), "actionable"] == 0).all()
    no_store = sample["store"].isna().values & ~p["issue_type_id"].isin(C.STORELESS_OK).values
    assert (p.loc[no_store, "actionable"] == 0).all()
