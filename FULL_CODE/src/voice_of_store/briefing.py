"""Weekly regional briefs (HTML) and the validation / precision statement files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from .analysis import build_report
from .brief import build_region_week, render_html
from .io import Data, load_data, load_incidents
from .pipeline import prepare_rows
from .report import time_split_validation, wilson
from .report_page import render_report
from .routing import ESCALATION_RULE
from .stores import StoreResolver

log = logging.getLogger(__name__)


def write_briefs(data: Data, rows: pd.DataFrame, flags: pd.DataFrame, out: Path, from_week_index: int) -> int:
    """One HTML page per region and week from `from_week_index`; returns how many pages were written."""
    out.mkdir(parents=True, exist_ok=True)
    weeks = data.calendar[data.calendar["week_index"] >= from_week_index]["week_start"].tolist()
    index = []
    for week in weeks:
        (out / week).mkdir(exist_ok=True)
        for region in sorted(data.stores["region"].unique()):
            entries = build_region_week(rows, flags, data.stores, data.taxonomy, region, week)
            ids = set(data.stores[data.stores["region"] == region]["store_id"])
            n_rows = int((rows["week"].eq(week) & rows["store"].isin(ids)).sum())
            (out / week / f"{region}.html").write_text(render_html(region, week, entries, n_rows), encoding="utf-8")
            index.append((week, region, len(entries)))
    links = "".join(f"<li>{w} · <a href='{w}/{r}.html'>{r}</a> ({n} issues)</li>" for w, r, n in index)
    (out / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Weekly briefs</title>"
        "<body style='font-family:system-ui;max-width:700px;margin:auto;padding:16px'>"
        f"<h1>Weekly regional briefs</h1><p><a href='../report.html'>Full evaluation report</a></p><ul>{links}</ul><p>{ESCALATION_RULE}</p></body>",
        encoding="utf-8",
    )
    return len(index)


def validation_text(v: dict) -> str:
    lo1, hi1 = v["ci_actionable"]
    lo2, hi2 = v["ci_actionable_high"]
    return (
        "# Validation and precision statement (time-split, out of sample)\n\n"
        f"Trained on labelled rows of weeks 1-9 ({v['n_train']} rows), tested on labelled rows of weeks 10-13 ({v['n_test']} rows).\n\n"
        f"- Issue macro-F1: {v['issue_macro_f1']:.3f}\n- Severity weighted-F1: {v['severity_weighted_f1']:.3f}\n"
        f"- Actionable F1: {v['actionable_f1']:.3f}\n- Classification score (0.5/0.25/0.25): {v['classification']:.3f}\n\n"
        f"Precision statement. Of {v['n_pred_actionable']} records marked actionable, {v['precision_actionable']:.1%} truly were "
        f"(95% interval {lo1:.1%}-{hi1:.1%}). Of {v['n_pred_actionable_high']} marked actionable and high/critical, "
        f"{v['precision_actionable_high']:.1%} were truly actionable (95% interval {lo2:.1%}-{hi2:.1%}).\n\n"
        "The labelled sample over-samples rare types, so these figures describe the sample, not the full stream.\n\n"
        f"{ESCALATION_RULE}\n"
    )


def write_validation(data: Data, resolver: StoreResolver, out: Path) -> dict:
    v = time_split_validation(data, resolver)
    v["ci_actionable"] = list(wilson(round(v["precision_actionable"] * v["n_pred_actionable"]), v["n_pred_actionable"]))
    v["ci_actionable_high"] = list(
        wilson(round(v["precision_actionable_high"] * v["n_pred_actionable_high"]), v["n_pred_actionable_high"])
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps(v), encoding="utf-8")
    (out / "validation.md").write_text(validation_text(v), encoding="utf-8")
    return v


def write_report(
    data: Data, resolver: StoreResolver, rows: pd.DataFrame, flags: pd.DataFrame, v: dict, data_dir: Path, out: Path
) -> dict:
    """The full evaluation report as JSON and as one self-contained HTML page."""
    rep = build_report(data, resolver, rows, flags, v, load_incidents(data_dir))
    (out / "report.json").write_text(json.dumps(rep), encoding="utf-8")
    (out / "report.html").write_text(render_report(rep), encoding="utf-8")
    return rep


def run(data_dir: Path, submission_dir: Path, out_dir: Path, from_week_index: int) -> int:
    data = load_data(data_dir)
    resolver = StoreResolver(data.stores)
    flags = pd.read_csv(submission_dir / "R5_emerging_flags.csv", dtype=str)
    rows = prepare_rows(data, data.feedback["created_at"].max() + pd.Timedelta(seconds=1), resolver)
    count = write_briefs(data, rows, flags, out_dir / "briefs", from_week_index)
    v = write_validation(data, resolver, out_dir)
    write_report(data, resolver, rows, flags, v, data_dir, out_dir)
    log.info("wrote %d briefs to %s and the validation and report files to %s", count, out_dir / "briefs", out_dir)
    return count
