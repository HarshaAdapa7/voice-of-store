#!/usr/bin/env python3
"""Regenerate submission/ from the data folder: predictions for every row, flags week by week, detector_cmd.txt.

    python FULL_CODE/make_submission.py [--data data] [--out submission]

Flags are produced one as-of week at a time with exactly the logic of FULL_CODE/detect.py (each week sees only rows
created up to its Sunday).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voice_of_store.io import DataError  # noqa: E402
from voice_of_store.logs import setup_logging  # noqa: E402
from voice_of_store.submission import write_submission  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="submission")
    a = ap.parse_args()
    setup_logging()
    try:
        write_submission(Path(a.data), Path(a.out))
    except DataError as exc:
        raise SystemExit(f"error: {exc}") from None


if __name__ == "__main__":
    main()
