"""Rubric self-audit: scores this project against the pack rules, the requirements list and the coding guidelines.

This is the team's own rubric, built from the documents we were given. It is evidence for our review, not the jury's score.
Usage (from the repository root):  python FULL_CODE/scripts/self_audit.py [--full] [--pack PATH_TO_PACK]
  default : static checks and checks on the files in submission/ and out/ (about 10 seconds)
  --full  : also runs ruff, mypy, the whole test suite and times the detector (several minutes)
  --pack  : the organisers' pack folder, for the originality comparison with their baseline
"""

from __future__ import annotations

import argparse
import ast
import difflib
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE = ROOT / "FULL_CODE"
SRC = CODE / "src" / "voice_of_store"
sys.path.insert(0, str(CODE / "src"))

MAX_FUNC_LINES, MAX_COMPLEXITY, MAX_MODULE_LINES = 70, 14, 450


@dataclass
class Check:
    area: str
    name: str
    weight: int
    passed: bool | None  # None = could not be evaluated (not counted, and listed)
    detail: str = ""


def py_files(*parts: str) -> list[Path]:
    return sorted(p for p in (CODE.joinpath(*parts)).rglob("*.py") if "tools" not in p.parts and "__pycache__" not in p.parts)


def run(cmd: list[str], timeout: int = 900, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    site = sysconfig.get_paths()["purelib"]  # lets tools find the packages this interpreter uses
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(CODE / "src"), site, os.environ.get("PYTHONPATH", "")])}
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False, env=env)  # noqa: S603


# ---------- structure and static checks ----------
def functions(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def complexity(fn: ast.AST) -> int:
    branches = (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.BoolOp, ast.IfExp, ast.comprehension, ast.Assert)
    return 1 + sum(isinstance(n, branches) for n in ast.walk(fn))


def static_checks() -> list[Check]:
    out: list[Check] = []
    src = (
        py_files("src")
        + py_files("tests")
        + [CODE / f for f in ("main.py", "detect.py", "serve.py", "make_submission.py", "make_briefs.py")]
    )
    long_fn, hard_fn, untyped, undoc, total_pub = [], [], [], [], 0
    for p in py_files("src") + [CODE / f for f in ("main.py", "detect.py", "serve.py", "make_submission.py", "make_briefs.py")]:
        for fn in functions(p):
            length = fn.end_lineno - fn.lineno + 1
            if length > MAX_FUNC_LINES:
                long_fn.append(f"{p.name}:{fn.name}({length})")
            if complexity(fn) > MAX_COMPLEXITY:
                hard_fn.append(f"{p.name}:{fn.name}({complexity(fn)})")
            if fn.returns is None and fn.name != "__init__":
                untyped.append(f"{p.name}:{fn.name}")
            if not fn.name.startswith("_"):
                total_pub += 1
                if not ast.get_docstring(fn):
                    undoc.append(f"{p.name}:{fn.name}")
    out.append(Check("Quality", f"functions at most {MAX_FUNC_LINES} lines", 4, not long_fn, ", ".join(long_fn[:6])))
    out.append(Check("Quality", f"cyclomatic complexity at most {MAX_COMPLEXITY}", 4, not hard_fn, ", ".join(hard_fn[:6])))
    big = [
        f"{p.name}({len(p.read_text(encoding='utf-8', errors='replace').splitlines())})"
        for p in py_files("src")
        if len(p.read_text(encoding='utf-8', errors='replace').splitlines()) > MAX_MODULE_LINES
    ]
    out.append(Check("Quality", f"modules at most {MAX_MODULE_LINES} lines", 2, not big, ", ".join(big)))
    out.append(
        Check("Quality", "every function has a return annotation", 4, len(untyped) <= 2, f"{len(untyped)} missing: {untyped[:5]}")
    )
    ratio = 1 - len(undoc) / max(1, total_pub)
    out.append(Check("Quality", "public functions documented (at least 70%)", 3, ratio >= 0.7, f"{ratio:.0%}; e.g. {undoc[:4]}"))
    text = {p: p.read_text(encoding="utf-8") for p in src}
    prints = [
        p.name for p, t in text.items() if re.search(r"^\s*print\(", t, re.M) and p.parent.name in ("voice_of_store", "web")
    ]
    out.append(Check("Guidelines", "logging, not print, in the library", 3, not prints, ", ".join(prints)))
    bad = [p.name for p, t in text.items() if re.search(r"except\s*:\s*\n|except Exception:\s*\n\s*pass", t)]
    out.append(Check("Guidelines", "no bare or silent except", 3, not bad, ", ".join(bad)))
    todo = [p.name for p, t in text.items() if re.search(r"\b(TODO|FIXME|XXX|HACK)\b", t)]
    out.append(Check("Guidelines", "no TODO/FIXME left in code", 2, not todo, ", ".join(todo)))
    danger = [
        p.name
        for p, t in text.items()
        if p.parent.name != "tests" and re.search(r"\b(eval|exec)\(|pickle|shell=True|os\.system|yaml\.load\(", t)
    ]
    out.append(Check("Security", "no eval/exec/pickle/shell in code", 5, not danger, ", ".join(danger)))
    secret = [
        p.name for p, t in text.items() if re.search(r"(api[_-]?key|secret|password)\s*=\s*['\"][A-Za-z0-9+/=_-]{12,}", t, re.I)
    ]
    out.append(Check("Security", "no hard-coded secrets", 5, not secret, ", ".join(secret)))
    sec = (SRC / "web" / "security.py").read_text(encoding='utf-8', errors='replace')
    for label, pattern in (
        ("constant-time comparisons", "compare_digest"),
        ("scrypt password hashes", "check_password_hash"),
        ("host allow-list", "allowed_hosts"),
        ("rate limiter", "RateLimiter"),
        ("CSP", "Content-Security-Policy"),
        ("trusted types", "trusted-types"),
        ("generic error handler", "internal error"),
    ):
        out.append(Check("Security", label, 2, pattern in sec))
    return out


def layout_checks() -> list[Check]:
    out: list[Check] = []
    tracked = run(["git", "ls-files"]).stdout.split()
    top = (
        sorted({t.split("/")[0] for t in tracked})
        if tracked
        else sorted(p.name for p in ROOT.iterdir() if p.name not in {"data", "out", ".git"})
    )
    allowed = {"README.md", "LICENSE", "submission", "FULL_CODE", ".gitignore"}
    out.append(
        Check(
            "Guidelines",
            "top level holds only README, LICENSE, submission, FULL_CODE, .gitignore",
            5,
            set(top) <= allowed,
            str(top),
        )
    )
    ign = (ROOT / ".gitignore").read_text(encoding='utf-8', errors='replace')
    out.append(
        Check(
            "Guidelines",
            ".gitignore covers data, env, venv, caches",
            3,
            all(x in ign for x in ("data/", ".env", ".venv", "__pycache__")),
        )
    )
    out.append(
        Check(
            "Guidelines",
            ".env.example present, .env absent",
            3,
            (CODE / ".env.example").exists() and not (CODE / ".env").exists(),
        )
    )
    req = (CODE / "requirements.txt").read_text(encoding='utf-8', errors='replace').splitlines()
    loose = [r for r in req if r and not r.startswith("#") and "==" not in r]
    out.append(Check("Guidelines", "dependencies pinned (lockfile)", 4, len(loose) <= 1, f"unpinned: {loose}"))
    out.append(Check("Guidelines", "LICENSE present", 2, (ROOT / "LICENSE").exists()))
    readme = (ROOT / "README.md").read_text(encoding='utf-8', errors='replace')
    need = [
        "What it does",
        "How to run",
        "How to run the tests",
        "Architecture",
        "Security",
        "AI usage",
        "Pre-built and third-party code",
        "Limitations",
        "Results",
    ]
    missing = [h for h in need if h not in readme]
    out.append(Check("Guidelines", "README has every required section", 5, not missing, f"missing {missing}"))
    out.append(
        Check("Guidelines", "README declares AI usage and pre-built code", 3, "AI usage" in readme and "evaluate.py" in readme)
    )
    tests = list((CODE / "tests").glob("test_*.py"))
    n_tests = sum(len(re.findall(r"^def test_", t.read_text(encoding='utf-8', errors='replace'), re.M)) for t in tests)
    out.append(
        Check(
            "Guidelines",
            "tests present (at least 100 functions)",
            4,
            n_tests >= 100,
            f"{n_tests} test functions in {len(tests)} files",
        )
    )
    docs = ["SECURITY.md", "GUIDELINES_COMPLIANCE.md", "REQUIREMENTS_TRACEABILITY.md", "DEMO_SCRIPT.md"]
    out.append(
        Check(
            "Guidelines",
            "supporting docs present",
            3,
            all((CODE / d).exists() for d in docs),
            str([d for d in docs if not (CODE / d).exists()]),
        )
    )
    return out


# ---------- requirement checks on the delivered files ----------
def requirement_checks(data: Path) -> list[Check]:
    import pandas as pd

    out: list[Check] = []
    sub = ROOT / "submission"
    pred, flags = sub / "R5_predictions.csv", sub / "R5_emerging_flags.csv"
    cmd = (sub / "detector_cmd.txt").read_text(encoding='utf-8', errors='replace').strip() if (sub / "detector_cmd.txt").exists() else ""
    out.append(
        Check(
            "Requirements",
            "detector_cmd.txt has the required shape",
            4,
            cmd == "python FULL_CODE/detect.py --feedback {feedback} --as-of {asof} --out {out}",
            cmd,
        )
    )
    if not (data / "feedback.csv").exists():
        out.append(Check("Requirements", "pack data present for submission checks", 10, None, f"put the pack files in {data}"))
        return out
    fb = pd.read_csv(data / "feedback.csv", dtype=str)
    pr = pd.read_csv(pred, dtype=str)
    tax = pd.read_csv(data / "issue_taxonomy.csv")
    ok_rows = set(pr["feedback_id"]) == set(fb["feedback_id"]) and not pr["feedback_id"].duplicated().any()
    out.append(Check("Requirements", "every feedback row is predicted exactly once", 8, ok_rows, f"{len(pr)} of {len(fb)}"))
    valid = (
        pr["issue_type_id"].isin(tax["issue_type_id"]).all()
        and pr["severity"].isin(["low", "medium", "high", "critical"]).all()
        and pr["actionable"].isin(["0", "1"]).all()
    )
    out.append(Check("Requirements", "predictions use valid issue ids, severities and 0/1", 6, bool(valid)))
    floors = tax.set_index("issue_type_id")["policy_severity_floor"].map({"low": 0, "medium": 1, "high": 2})
    rank = pr["severity"].map({"low": 0, "medium": 1, "high": 2, "critical": 3})
    out.append(
        Check(
            "Requirements",
            "FR-07: policy severity floor holds on every row",
            6,
            bool((rank >= pr["issue_type_id"].map(floors)).all()),
        )
    )
    fl = pd.read_csv(flags, dtype=str)
    ids = set(fb["feedback_id"])
    ev = fl["evidence_feedback_ids"].str.split(";")
    out.append(
        Check(
            "Requirements",
            "every flag cites at least 2 existing feedback ids",
            8,
            bool((ev.map(len) >= 2).all() and ev.map(lambda x: set(x) <= ids).all()),
        )
    )
    per_week = len(fl) / 26
    out.append(Check("Requirements", "flag volume within the budget of 3 per week", 6, per_week <= 3, f"{per_week:.2f} per week"))
    out.append(
        Check("Requirements", "no duplicate flags", 3, not fl.duplicated(["as_of_week_start", "store_id", "issue_type_id"]).any())
    )
    score = run(
        [
            sys.executable,
            str(CODE / "tools" / "evaluate.py"),
            "--submission",
            str(pred),
            "--truth",
            str(data / "feedback_labels_train.csv"),
            "--feedback",
            str(data / "feedback.csv"),
            "--stores",
            str(data / "store_master.csv"),
            "--out",
            str(Path(tempfile.mkdtemp()) / "score.json"),
        ]
    )
    out.append(
        Check(
            "Requirements",
            "organisers' evaluate.py runs on the submission without errors",
            6,
            score.returncode == 0,
            score.stderr[-200:],
        )
    )
    briefs = sorted((ROOT / "out" / "briefs").glob("*/*.html"))
    if len(briefs) >= 65:
        pages = [b.read_text(encoding='utf-8', errors='replace') for b in briefs]
        needs = (
            "Next step",
            "severity",
            "Escalation rule",
            "↑",
            "Stores (reports",
            "channels:",
            "first ",
            "Confidence score",
            "10,000",
        )
        weak = [
            b.parent.name + "/" + b.stem
            for b, t in zip(briefs, pages, strict=True)
            if "No actionable" not in t and not all(n in t.replace("→", "↑").replace("↓", "↑") for n in needs)
        ]
        out.append(
            Check(
                "Requirements",
                "briefs: one per region and week with every required element",
                10,
                not weak and len(briefs) == 65,
                f"{len(briefs)} briefs; weak: {weak[:3]}",
            )
        )
    else:
        out.append(Check("Requirements", "briefs generated (run main.py briefs first)", 10, None, f"{len(briefs)} found"))
    report = ROOT / "out" / "report.html"
    rep = report.read_text(encoding='utf-8', errors='replace') if report.exists() else ""
    out.append(
        Check(
            "Requirements",
            "precision statement present in the report",
            6,
            "Precision statement" in rep and "truly actionable" in rep,
        )
    )
    out.append(Check("Requirements", "de-duplication reported", 3, "De-duplication" in rep))
    out.append(
        Check(
            "Requirements",
            "limitations and unverified-feedback disclosure present",
            4,
            "unverified" in rep.lower() and "approximate" in rep,
        )
    )
    return out


def page_checks() -> list[Check]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return [Check("Requirements", "each brief prints on one A4 page", 8, None, "Playwright not installed")]
    r = run([sys.executable, str(CODE / "scripts" / "check_brief_pages.py"), str(ROOT / "out" / "briefs")])
    return [Check("Requirements", "each brief prints on one A4 page", 8, r.returncode == 0, r.stdout.strip()[:160])]


def full_checks() -> list[Check]:
    out: list[Check] = []
    ruff = shutil.which("ruff") or "/root/.local/bin/ruff"
    out.append(
        Check(
            "Guidelines",
            "ruff format clean",
            4,
            run([ruff, "format", "--check", ".", "--exclude", "tools"], cwd=CODE).returncode == 0,
        )
    )
    out.append(
        Check("Guidelines", "ruff lint clean (incl. bandit rules)", 5, run([ruff, "check", "."], cwd=CODE).returncode == 0)
    )
    mypy_cmd = [
        shutil.which("mypy") or "/root/.local/bin/mypy",
        "src",
        "main.py",
        "detect.py",
        "serve.py",
        "make_submission.py",
        "make_briefs.py",
    ]
    mypy = run(mypy_cmd, cwd=CODE)
    out.append(Check("Guidelines", "mypy clean", 4, mypy.returncode == 0, mypy.stdout[-120:]))
    t = run([shutil.which("pytest") or "/root/.local/bin/pytest", "-q", "-p", "no:cacheprovider"], cwd=CODE)
    out.append(
        Check(
            "Guidelines",
            "full test suite passes",
            10,
            t.returncode == 0,
            t.stdout.strip().splitlines()[-1] if t.stdout else t.stderr[-120:],
        )
    )
    start = time.time()
    d = run(
        [
            sys.executable,
            str(CODE / "detect.py"),
            "--feedback",
            str(ROOT / "data"),
            "--as-of",
            "2026-09-21",
            "--out",
            str(Path(tempfile.mkdtemp()) / "flags.csv"),
        ]
    )
    secs = time.time() - start
    out.append(
        Check(
            "Performance",
            "detector finishes one week in under 120 s (limit is 600 s)",
            6,
            d.returncode == 0 and secs < 120,
            f"{secs:.0f} s",
        )
    )
    return out


def originality(pack: Path | None) -> list[Check]:
    if pack is None or not (pack / "baseline" / "baseline.py").exists():
        return [Check("Originality", "similarity with the organisers' baseline", 5, None, "pass --pack to compare")]

    def shingles(text: str, n: int = 6) -> set[str]:
        toks = re.findall(r"\w+", text)
        return {" ".join(toks[i : i + n]) for i in range(len(toks) - n)}

    base = shingles((pack / "baseline" / "baseline.py").read_text(encoding='utf-8', errors='replace'))
    worst = 0.0
    for p in py_files("src") + [CODE / "detect.py"]:
        mine = shingles(p.read_text(encoding='utf-8', errors='replace'))
        if mine:
            worst = max(worst, len(mine & base) / len(mine))
    ratio = difflib.SequenceMatcher(
        None, "".join(p.read_text(encoding='utf-8', errors='replace') for p in py_files("src"))[:60000], (pack / "baseline" / "baseline.py").read_text(encoding='utf-8', errors='replace')
    ).quick_ratio()
    return [
        Check(
            "Originality",
            "6-word overlap with the organisers' baseline under 3% per file (outside argparse boilerplate)",
            5,
            worst < 0.03,
            f"worst file {worst:.1%}; character-bag similarity {ratio:.2f} (not a plagiarism measure)",
        )
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--pack", type=Path, default=None)
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    a = ap.parse_args()
    checks = static_checks() + layout_checks() + requirement_checks(a.data) + originality(a.pack)
    checks += page_checks() if (ROOT / "out" / "briefs").exists() else []
    if a.full:
        checks += full_checks()
    areas: dict[str, list[Check]] = {}
    for c in checks:
        areas.setdefault(c.area, []).append(c)
    lines = ["| Area | Score | Failed or not evaluated |", "|---|---|---|"]
    got = total = 0
    for area, cs in areas.items():
        scored = [c for c in cs if c.passed is not None]
        g, t = sum(c.weight for c in scored if c.passed), sum(c.weight for c in scored)
        got, total = got + g, total + t
        bad = "; ".join(f"{c.name} ({c.detail})" if c.detail else c.name for c in cs if c.passed is not True)
        lines.append(f"| {area} | {100 * g / max(1, t):.0f} ({g}/{t}) | {bad or 'none'} |")
    lines.append(f"| **All** | **{100 * got / max(1, total):.1f}** ({got}/{total}) | |")
    report = "\n".join(lines)
    print(report)  # noqa: T201
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "self_audit.md").write_text(
        "# Self-audit (team rubric, not the jury's score)\n\n" + report + "\n", encoding="utf-8"
    )
    return 0 if got == total else 1


if __name__ == "__main__":
    sys.exit(main())
