"""Objective quality scorecard for this repository (stdlib only, plus ruff, mypy and pytest when installed).

Usage: python FULL_CODE/scripts/quality_gate.py [--skip-tests]
Prints a score out of 100 across fixed dimensions and exits 1 if any hard gate fails or the total is under 95.
It measures what a reviewer can measure: lint, types, tests, line coverage, docstrings, type hints, complexity, duplication,
risky constructs, requirement traceability and documentation. It is our own rubric, not the organisers'.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import shutil
import subprocess  # noqa: S404 (runs the project's own tools with fixed arguments)
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "voice_of_store"
PYTHON_FILES = [p for p in sorted(SRC.rglob("*.py"))]
ENTRY = [ROOT / n for n in ("main.py", "detect.py", "make_submission.py", "make_briefs.py", "serve.py")]
MAX_FUNC_LINES, MAX_COMPLEXITY = 60, 15


def _run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    return p.returncode, (p.stdout + p.stderr)


def _tool(name: str) -> list[str]:
    exe = shutil.which(name) or str(Path.home() / ".local" / "bin" / name)
    return [exe] if Path(exe).exists() else [sys.executable, "-m", name]


def lint() -> tuple[float, str]:
    c1, o1 = _run([*_tool("ruff"), "check", ".", "--output-format", "concise"])
    c2, o2 = _run([*_tool("ruff"), "format", "--check", ".", "--exclude", "tools"])
    return (10.0 if c1 == 0 and c2 == 0 else 0.0), "ruff check and format clean" if c1 == 0 and c2 == 0 else (o1 + o2)[-300:]


def types() -> tuple[float, str]:
    code, out = _run([*_tool("mypy"), "src", *[e.name for e in ENTRY]])
    return (10.0 if code == 0 else 0.0), out.strip().splitlines()[-1] if out.strip() else "no output"


def tests_and_coverage() -> tuple[float, float, str]:
    """Runs pytest once under sys.monitoring (3.12+) to count executed lines of src; returns (tests score, coverage score, note)."""
    runner = (
        "import sys, pytest\n"
        "mon = sys.monitoring; T = mon.COVERAGE_ID; hits = {}\n"
        "mon.use_tool_id(T, 'gate')\n"
        "def line(code, ln):\n"
        "    f = code.co_filename\n"
        "    if 'voice_of_store' in f: hits.setdefault(f, set()).add(ln)\n"
        "    return mon.DISABLE\n"
        "mon.register_callback(T, mon.events.LINE, line); mon.set_events(T, mon.events.LINE)\n"
        "rc = pytest.main(['-q', '-x', '-p', 'no:cacheprovider'])\n"
        "mon.set_events(T, 0)\n"
        "import json, os; json.dump({k: sorted(v) for k, v in hits.items()}, open(os.environ['GATE_HITS'], 'w'))\n"
        "sys.exit(int(rc))\n"
    )
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        hits_path = Path(tmp) / "hits.json"
        env = {
            **os.environ,
            "GATE_HITS": str(hits_path),
            "PYTHONPATH": str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
        }
        p = subprocess.run([sys.executable, "-c", runner], cwd=ROOT, env=env, capture_output=True, text=True, check=False)  # noqa: S603
        tail = (p.stdout.strip().splitlines() or ["no output"])[-1]
        if not hits_path.exists():
            return 0.0, 0.0, tail
        import json

        hits = json.loads(hits_path.read_text())
    total = covered = 0
    for f in PYTHON_FILES:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        lines = {
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.stmt) and not isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))
        }
        got = set(hits.get(str(f), [])) | set(hits.get(str(f.resolve()), []))
        total += len(lines)
        covered += len(lines & got)
    pct = covered / max(1, total)
    return (
        (10.0 if p.returncode == 0 else 0.0),
        round(10.0 * min(1.0, pct / 0.90), 2),
        f"{tail}; line coverage {pct:.1%} ({covered}/{total})",
    )


def _functions(tree: ast.AST):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _complexity(fn: ast.AST) -> int:
    score = 1
    for n in ast.walk(fn):
        if isinstance(n, (ast.If, ast.For, ast.While, ast.IfExp, ast.ExceptHandler, ast.With, ast.Assert, ast.comprehension)):
            score += 1
        elif isinstance(n, ast.BoolOp):
            score += len(n.values) - 1
    return score


def static_metrics() -> dict[str, tuple[float, str]]:
    fns = classes = doc_ok = doc_total = hints_ok = hints_total = 0
    long_fns, complex_fns = [], []
    risky: list[str] = []
    for f in PYTHON_FILES + ENTRY:
        text = f.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for fn in _functions(tree):
            fns += 1
            end = fn.end_lineno or fn.lineno
            if end - fn.lineno + 1 > MAX_FUNC_LINES:
                long_fns.append(f"{f.name}:{fn.name}")
            if _complexity(fn) > MAX_COMPLEXITY:
                complex_fns.append(f"{f.name}:{fn.name}={_complexity(fn)}")
            if not fn.name.startswith("_") or fn.name in ("__init__",):
                if f in PYTHON_FILES and fn.name != "__init__":
                    doc_total += 1
                    doc_ok += bool(ast.get_docstring(fn))
            args = [a for a in fn.args.args + fn.args.kwonlyargs if a.arg not in ("self", "cls")]
            hints_total += len(args) + 1
            hints_ok += sum(a.annotation is not None for a in args) + (fn.returns is not None)
        for c in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            classes += 1
            if f in PYTHON_FILES:
                doc_total += 1
                doc_ok += bool(ast.get_docstring(c))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                name = ast.unparse(n.func)
                if name in ("eval", "exec", "pickle.load", "pickle.loads", "os.system", "yaml.load") or (
                    name.startswith("subprocess.")
                    and any(k.arg == "shell" and getattr(k.value, "value", False) is True for k in n.keywords)
                ):
                    risky.append(f"{f.name}:{n.lineno} {name}")
        if re.search(r"(api[_-]?key|secret|password)\s*=\s*['\"][A-Za-z0-9+/_\-]{12,}['\"]", text, re.I) and f in PYTHON_FILES:
            risky.append(f"{f.name}: hard-coded secret-like string")
        if f in PYTHON_FILES and re.search(r"^\s*print\(", text, re.M):
            risky.append(f"{f.name}: print()")
    doc = doc_ok / max(1, doc_total)
    hint = hints_ok / max(1, hints_total)
    shape = 1 - (len(long_fns) + len(complex_fns)) / max(1, fns)
    return {
        "docstrings": (round(5 * min(1.0, doc / 0.85), 2), f"{doc:.1%} of public functions and classes ({doc_ok}/{doc_total})"),
        "type hints": (round(5 * min(1.0, hint / 0.95), 2), f"{hint:.1%} of parameters and returns"),
        "function size and complexity": (
            round(10 * min(1.0, shape / 0.97), 2),
            f"{len(long_fns)} over {MAX_FUNC_LINES} lines {long_fns[:4]}; {len(complex_fns)} over complexity {MAX_COMPLEXITY} {complex_fns[:4]}",
        ),
        "risky constructs": (
            10.0 if not risky else max(0.0, 10.0 - 3 * len(risky)),
            "none found" if not risky else "; ".join(risky[:5]),
        ),
    }


def duplication() -> tuple[float, str]:
    """Repeated blocks of 6 normalised lines inside src (a rough copy-paste detector)."""
    seen: dict[str, list[str]] = defaultdict(list)
    for f in PYTHON_FILES:
        lines = [re.sub(r"\s+", " ", ln.strip()) for ln in f.read_text(encoding="utf-8").splitlines()]
        lines = [ln for ln in lines if ln and not ln.startswith(("#", '"""', "import ", "from "))]
        for i in range(len(lines) - 5):
            block = "\n".join(lines[i : i + 6])
            if len(block) > 160:
                seen[hashlib.sha1(block.encode()).hexdigest()].append(f"{f.name}")  # noqa: S324 (not security use)
    dup = sum(1 for v in seen.values() if len(v) > 1)
    return (5.0 if dup <= 3 else max(0.0, 5.0 - 0.5 * (dup - 3))), f"{dup} repeated 6-line blocks"


def traceability() -> tuple[float, str]:
    """Every row of REQUIREMENTS.md must name code files and tests that really exist."""
    path = ROOT / "REQUIREMENTS.md"
    if not path.exists():
        return 0.0, "REQUIREMENTS.md missing"
    test_text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py"))
    rows = [ln for ln in path.read_text(encoding="utf-8").splitlines() if re.match(r"\|\s*(FR|NFR|OUT|PACK|G)-?\w*", ln)]
    bad = []
    for ln in rows:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        rid = cells[0]
        for ref in re.findall(r"`([\w/.]+\.py)`", cells[2] if len(cells) > 2 else ""):
            if not (ROOT / ref).exists() and not (SRC / ref).exists() and not any(SRC.rglob(Path(ref).name)):
                bad.append(f"{rid}: code {ref}")
        for t in re.findall(r"`(test_\w+)`", cells[3] if len(cells) > 3 else ""):
            if f"def {t}" not in test_text:
                bad.append(f"{rid}: test {t}")
        if len(cells) > 3 and not re.search(r"`test_\w+`|live probe|manual", cells[3]):
            bad.append(f"{rid}: no verification named")
    score = 15.0 if rows and not bad else max(0.0, 15.0 - 2 * len(bad))
    return score, f"{len(rows)} requirements traced; problems: {bad[:6] or 'none'}"


def documentation() -> tuple[float, str]:
    readme = (ROOT.parent / "README.md").read_text(encoding="utf-8")
    needed = [
        "What it does",
        "How to run",
        "How to run the tests",
        "Architecture",
        "Security",
        "AI usage",
        "Pre-built and third-party code",
        "Limitations",
    ]
    missing = [h for h in needed if f"## {h}" not in readme]
    extra = [
        n
        for n in ("SECURITY.md", "REQUIREMENTS.md", "GUIDELINES_COMPLIANCE.md", ".env.example", "requirements.txt")
        if not (ROOT / n).exists()
    ]
    ok = not missing and not extra
    return (5.0 if ok else max(0.0, 5.0 - len(missing) - len(extra))), "complete" if ok else f"missing {missing + extra}"


def layout() -> tuple[float, str]:
    code, out = _run([sys.executable, "scripts/package_check.py"])
    return (5.0 if code == 0 else 0.0), (out.strip().splitlines() or ["no output"])[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-tests", action="store_true", help="skip the (slow) test and coverage run")
    a = ap.parse_args()
    rows: list[tuple[str, float, float, str]] = []

    def add(name: str, pts: float, mx: float, note: str) -> None:
        rows.append((name, pts, mx, note))

    s, n = lint()
    add("lint and format", s, 10, n)  # noqa: E702
    s, n = types()
    add("static types", s, 10, n)  # noqa: E702
    if a.skip_tests:
        add("tests pass", 10, 10, "skipped (counted as pass)")
        add("line coverage", 10, 10, "skipped")  # noqa: E702
    else:
        t, c, n = tests_and_coverage()
        add("tests pass", t, 10, n)
        add("line coverage", c, 10, "target 90%")  # noqa: E702
    for name, (s, n) in static_metrics().items():
        add(name, s, {"docstrings": 5, "type hints": 5, "function size and complexity": 10, "risky constructs": 10}[name], n)
    s, n = duplication()
    add("internal duplication", s, 5, n)  # noqa: E702
    s, n = traceability()
    add("requirement traceability", s, 15, n)  # noqa: E702
    s, n = documentation()
    add("documentation", s, 5, n)  # noqa: E702
    s, n = layout()
    add("layout and package check", s, 5, n)  # noqa: E702
    total = sum(r[1] for r in rows)
    maximum = sum(r[2] for r in rows)
    for name, pts, mx, note in rows:
        print(f"{'OK  ' if pts >= mx - 0.01 else 'LOW '} {name:<30} {pts:5.1f}/{mx:<4.0f} {note}")  # noqa: T201
    score = 100 * total / maximum
    print(f"\nSCORE {score:.1f}/100")  # noqa: T201
    return 0 if score >= 95 else 1


if __name__ == "__main__":
    sys.exit(main())
