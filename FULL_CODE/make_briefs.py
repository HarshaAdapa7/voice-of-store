#!/usr/bin/env python3
"""Render the weekly one-page brief per region (HTML) plus the validation and precision statement.

    python FULL_CODE/make_briefs.py [--data data] [--submission submission] [--out out] [--from-week-index 14]

Briefs are written to out/briefs/<week>/<region>.html with an index at out/briefs/index.html; validation numbers go to
out/validation.md. Briefs cover the unlabelled-test half by default.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd  # noqa: E402

from voice_of_store.brief import build_region_week, render_html  # noqa: E402
from voice_of_store.io import load_data  # noqa: E402
from voice_of_store.pipeline import prepare_rows  # noqa: E402
from voice_of_store.report import time_split_validation, wilson  # noqa: E402
from voice_of_store.routing import ESCALATION_RULE  # noqa: E402
from voice_of_store.stores import StoreResolver  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--submission", default="submission")
    ap.add_argument("--out", default="out")
    ap.add_argument("--from-week-index", type=int, default=14)
    a = ap.parse_args()
    d = load_data(Path(a.data))
    resolver = StoreResolver(d.stores)
    flags = pd.read_csv(Path(a.submission) / "R5_emerging_flags.csv", dtype=str)
    rows = prepare_rows(d, d.feedback["created_at"].max() + pd.Timedelta(seconds=1), resolver)
    out = Path(a.out) / "briefs"
    out.mkdir(parents=True, exist_ok=True)
    weeks = d.calendar[d.calendar["week_index"] >= a.from_week_index]["week_start"].tolist()
    regions = sorted(d.stores["region"].unique())
    index = []
    for w in weeks:
        (out / w).mkdir(exist_ok=True)
        wk_rows = rows[rows["week"] == w]
        for reg in regions:
            entries = build_region_week(rows, flags, d.stores, d.taxonomy, reg, w)
            ids = set(d.stores[d.stores["region"] == reg]["store_id"])
            n = int(wk_rows["store"].isin(ids).sum())
            (out / w / f"{reg}.html").write_text(render_html(reg, w, entries, n), encoding="utf-8")
            index.append((w, reg, len(entries)))
    links = "".join(f"<li>{w} · <a href='{w}/{r}.html'>{r}</a> ({n} issues)</li>" for w, r, n in index)
    (out / "index.html").write_text(
        f"<!doctype html><meta charset='utf-8'><title>Weekly briefs</title><body style='font-family:system-ui;max-width:700px;margin:auto;padding:16px'>"
        f"<h1>Weekly regional briefs</h1><ul>{links}</ul><p>{ESCALATION_RULE}</p></body>", encoding="utf-8")

    v = time_split_validation(d, resolver)
    lo1, hi1 = wilson(round(v["precision_actionable"] * v["n_pred_actionable"]), v["n_pred_actionable"])
    lo2, hi2 = wilson(round(v["precision_actionable_high"] * v["n_pred_actionable_high"]), v["n_pred_actionable_high"])
    import json
    v["ci_actionable"], v["ci_actionable_high"] = [lo1, hi1], [lo2, hi2]
    (Path(a.out) / "validation.json").write_text(json.dumps(v), encoding="utf-8")
    (Path(a.out) / "validation.md").write_text(
        "# Validation and precision statement (time-split, out of sample)\n\n"
        f"Trained on labelled rows of weeks 1-9 ({v['n_train']} rows), tested on labelled rows of weeks 10-13 ({v['n_test']} rows).\n\n"
        f"- Issue macro-F1: {v['issue_macro_f1']:.3f}\n- Severity weighted-F1: {v['severity_weighted_f1']:.3f}\n"
        f"- Actionable F1: {v['actionable_f1']:.3f}\n- Classification score (0.5/0.25/0.25): {v['classification']:.3f}\n\n"
        f"Precision statement. Of {v['n_pred_actionable']} records marked actionable, {v['precision_actionable']:.1%} truly were "
        f"(95% interval {lo1:.1%}-{hi1:.1%}). Of {v['n_pred_actionable_high']} marked actionable and high/critical, "
        f"{v['precision_actionable_high']:.1%} were truly actionable (95% interval {lo2:.1%}-{hi2:.1%}).\n\n"
        "The labelled sample over-samples rare types, so these figures describe the sample, not the full stream.\n\n"
        f"{ESCALATION_RULE}\n", encoding="utf-8")
    print(f"wrote {len(index)} briefs to {out}/ and {Path(a.out) / 'validation.md'}")
    print((Path(a.out) / "validation.md").read_text())


if __name__ == "__main__":
    main()
