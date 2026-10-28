#!/usr/bin/env python3
"""Pre-submission check of the project layout and rules. Run from the project root (or anywhere):

    python FULL_CODE/scripts/package_check.py [--root .]

Exit code 0 = every check passed. Checks that need the pack data skip with a note when data/ is absent.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_TOP = {"README.md", ".gitignore", "LICENSE", "submission", "FULL_CODE", ".git"}
FORBIDDEN_IMPORT = re.compile(r"^\s*(import|from)\s+(requests|urllib|http|socket|pickle|joblib|httpx|aiohttp)\b", re.M)
HARD_CODED = re.compile(r"\b20\d\d-\d\d-\d\d\b|\b(ST|FB)-[A-Z0-9]{5,8}\b")
SECRETS = re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}", re.I)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    root = Path(ap.parse_args().root).resolve()
    bad: list[str] = []

    top = {p.name for p in root.iterdir()}
    extra = top - ALLOWED_TOP
    if extra:
        bad.append(f"unexpected top-level items: {sorted(extra)}")
    for need in ("README.md", "submission", "FULL_CODE"):
        if need not in top:
            bad.append(f"missing top-level {need}")

    gi = (root / ".gitignore").read_text() if (root / ".gitignore").exists() else ""
    for pat in ("data/", "models/", ".env", ".venv/", "node_modules/"):
        if pat not in gi:
            bad.append(f".gitignore must list {pat}")
    if re.search(r"^\*\.(csv|jsonl)\s*$", gi, re.M):
        bad.append(".gitignore must not exclude csv/jsonl (submission files)")

    sub = root / "submission"
    for f in ("R5_predictions.csv", "R5_emerging_flags.csv", "detector_cmd.txt"):
        if not (sub / f).exists():
            bad.append(f"submission/{f} missing")
    cmd = sub / "detector_cmd.txt"
    if cmd.exists():
        line = cmd.read_text().strip()
        if line != "python FULL_CODE/detect.py --feedback {feedback} --as-of {asof} --out {out}":
            bad.append(f"detector_cmd.txt has unexpected line: {line}")
        if not (root / "FULL_CODE" / "detect.py").exists():
            bad.append("detector script FULL_CODE/detect.py missing")

    for name in ("pyproject.toml", "requirements.txt", ".env.example"):
        if not (root / "FULL_CODE" / name).exists():
            bad.append(f"FULL_CODE/{name} missing")

    for py in list((root / "FULL_CODE" / "src").rglob("*.py")) + [root / "FULL_CODE" / n for n in ("detect.py", "make_submission.py", "make_briefs.py")]:
        text = py.read_text()
        if FORBIDDEN_IMPORT.search(text):
            bad.append(f"network/pickle import in {py.relative_to(root)}")
        if HARD_CODED.search(text):
            bad.append(f"hard-coded date or id in {py.relative_to(root)}")
        if SECRETS.search(text):
            bad.append(f"possible secret in {py.relative_to(root)}")

    readme = (root / "README.md").read_text() if (root / "README.md").exists() else ""
    for h in ("What it does", "How to run", "How to run the tests", "Architecture", "AI usage", "Pre-built and third-party code", "Limitations", "Causal"):
        if h.lower() not in readme.lower():
            bad.append(f"README missing section: {h}")

    tracked = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True).stdout.split()
    for f in ("submission/R5_predictions.csv", "submission/R5_emerging_flags.csv", "submission/detector_cmd.txt"):
        if tracked and f not in tracked:
            bad.append(f"{f} is not committed")
    if any(t.startswith("data/") for t in tracked):
        bad.append("pack data/ is committed")

    if bad:
        print("PACKAGE CHECK FAILED")
        for b in bad:
            print(" -", b)
        return 1
    print("PACKAGE CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
