#!/usr/bin/env python3
"""Render the weekly one-page brief per region (HTML) plus the validation and precision statement.

    python FULL_CODE/make_briefs.py [--data data] [--submission submission] [--out out] [--from-week-index 14]

Briefs go to out/briefs/<week>/<region>.html with an index at out/briefs/index.html; validation numbers go to
out/validation.md and out/validation.json. Briefs cover the unlabelled-test half by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_of_store.briefing import run  # noqa: E402
from voice_of_store.io import DataError  # noqa: E402
from voice_of_store.logs import setup_logging  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--submission", default="submission")
    ap.add_argument("--out", default="out")
    ap.add_argument("--from-week-index", type=int, default=14)
    a = ap.parse_args()
    setup_logging()
    try:
        run(Path(a.data), Path(a.submission), Path(a.out), a.from_week_index)
    except (DataError, FileNotFoundError) as exc:
        raise SystemExit(f"error: {exc}") from None


if __name__ == "__main__":
    main()
