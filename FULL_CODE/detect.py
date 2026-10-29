#!/usr/bin/env python3
"""Detector entry point (the command in submission/detector_cmd.txt).

Called by the jury as the command stored in submission/detector_cmd.txt. It reports the Monday-to-Sunday week that holds
the given date, and only looks at feedback created before the following Monday 00:00. --feedback may be the CSV itself or
the folder holding it; every other data file is read from that same folder. The classifier is trained on the spot from
the public labels there, so no internet and no saved model file are needed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_of_store.classify import NotEnoughLabels  # noqa: E402
from voice_of_store.io import DataError, load_data, monday_of  # noqa: E402
from voice_of_store.logs import setup_logging  # noqa: E402
from voice_of_store.pipeline import emit_flags, prepare_rows, sunday_end  # noqa: E402
from voice_of_store.stores import StoreResolver  # noqa: E402

log = logging.getLogger("detect")


def build_parser() -> argparse.ArgumentParser:
    """The three options the jury's command line supplies."""
    ap = argparse.ArgumentParser(description="Voice-of-Store emerging-issue detector for a single week")
    ap.add_argument(
        "--feedback",
        required=True,
        help="path to feedback.csv, or to the folder that holds it; other data files are read from that folder",
    )
    ap.add_argument(
        "--as-of",
        dest="as_of",
        required=True,
        help="a date (YYYY-MM-DD) inside the week to report; the Monday-to-Sunday week that contains it is used",
    )
    ap.add_argument("--out", required=True, help="where to write the flags CSV")
    return ap


def main() -> None:
    """Parse the command line, run the detector for the requested week and write the flags file."""
    a = build_parser().parse_args()
    setup_logging()
    try:
        fb_path = Path(a.feedback).resolve()
        if fb_path.is_dir():  # the jury may pass the folder instead of the file
            fb_path = fb_path / "feedback.csv"
        data = load_data(fb_path.parent, fb_path)
        monday = monday_of(a.as_of)
        resolver = StoreResolver(data.stores)
        rows = prepare_rows(data, sunday_end(monday), resolver)
        flags = emit_flags(rows, data, resolver, [monday.strftime("%Y-%m-%d")])
    except (DataError, NotEnoughLabels) as exc:
        raise SystemExit(f"error: {exc}") from None
    flags.to_csv(a.out, index=False)
    log.info("as-of %s: wrote %s (%d flags, %d rows used)", monday.date(), a.out, len(flags), len(rows))


if __name__ == "__main__":
    main()
