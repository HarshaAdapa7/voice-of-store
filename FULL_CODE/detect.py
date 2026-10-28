#!/usr/bin/env python3
"""Detector entry point (the command in submission/detector_cmd.txt).

    python FULL_CODE/detect.py --feedback <feedback.csv> --as-of YYYY-MM-DD --out <flags.csv>

Writes the flags for the Monday-Sunday week containing --as-of. Uses only rows created before the next Monday 00:00,
reads every data file from the folder that contains --feedback, trains the classifier at run time from the public
labels in that folder, needs no internet and no pre-built model file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_of_store.io import load_data, monday_of  # noqa: E402
from voice_of_store.pipeline import emit_flags, prepare_rows, sunday_end  # noqa: E402
from voice_of_store.stores import StoreResolver  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Voice-of-Store emerging-issue detector (one week, as-of)")
    ap.add_argument("--feedback", required=True, help="path to feedback.csv; other data files are read from its folder")
    ap.add_argument("--as-of", dest="as_of", required=True, help="YYYY-MM-DD, any day of the week to flag")
    ap.add_argument("--out", required=True, help="flags file to write")
    a = ap.parse_args()
    fb_path = Path(a.feedback).resolve()
    data = load_data(fb_path.parent, fb_path)
    monday = monday_of(a.as_of)
    resolver = StoreResolver(data.stores)
    rows = prepare_rows(data, sunday_end(monday), resolver)
    flags = emit_flags(rows, data, resolver, [monday.strftime("%Y-%m-%d")])
    flags.to_csv(a.out, index=False)
    print(f"as-of {monday.date()}: wrote {a.out} ({len(flags)} flags, {len(rows)} rows used)")


if __name__ == "__main__":
    main()
