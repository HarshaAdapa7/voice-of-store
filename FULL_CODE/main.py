#!/usr/bin/env python3
"""Single entry point for every task. Run from the project root:

    python FULL_CODE/main.py submission     # regenerate submission/ (predictions, flags, detector_cmd.txt)
    python FULL_CODE/main.py briefs         # weekly regional briefs + validation files in out/
    python FULL_CODE/main.py serve          # the web demo
    python FULL_CODE/main.py detect --feedback F --as-of YYYY-MM-DD --out O    # one week of the detector
    python FULL_CODE/main.py check          # package and rules check before zipping
    python FULL_CODE/main.py grid           # synthetic-incident sanity harness
    python FULL_CODE/main.py db             # Supabase database status, schema and sync

Each command accepts --help. The detector stays a separate script because submission/detector_cmd.txt calls it directly.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMANDS = {
    "submission": HERE / "make_submission.py",
    "briefs": HERE / "make_briefs.py",
    "serve": HERE / "serve.py",
    "detect": HERE / "detect.py",
    "check": HERE / "scripts" / "package_check.py",
    "grid": HERE / "scripts" / "injection_grid.py",
    "db": HERE / "scripts" / "supabase_sync.py",
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 0 if not argv or argv[0] in ("-h", "--help") else 2
    script = COMMANDS[argv[0]]
    sys.argv = [str(script), *argv[1:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
