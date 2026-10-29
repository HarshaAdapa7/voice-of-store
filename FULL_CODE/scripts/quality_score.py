"""Self-audit: scores this project 0-100 against the guidelines and the requirement list with measurable checks.

Usage: python FULL_CODE/scripts/quality_score.py [--pack PATH_TO_ORGANISERS_PACK] [--quick]
Every check prints its measured value, its weight and the points earned, so a low score always says what to fix.
Checks that need a tool that is not installed (ruff, mypy) are reported as skipped and left out of the total.
`--quick` skips the test run. The organisers' pack folder, when given, is used for the originality comparison.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import shutil
import subprocess  # noqa: S404 (runs the project's own tools)
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # FULL_CODE
REPO = ROOT.parent
SRC = ROOT / "src"
PY_FILES = sorted([*SRC.rglob("*.py"), *(ROOT / "scripts").glob("*.py"), *ROOT.glob("*.py")])
FORBIDDEN = re.compile(
    r"\b(eval|exec|pickle|marshal|shelve)\b\s*[.(]|os\.system|shell\s*=\s*True|yaml\.load\(|verify\s*=\s*False"
)
SECRET = re.compile(r"(api[_-]?key|secret|passwd|password|token)\s*=\s*['\"][A-Za-z0-9/+_-]{12,}['\"]", re.I)


def run(cmd: list[str], cwd: Path = REPO) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603
    return p.returncode, (p.stdout + p.stderr)


def functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def docstring_share() -> tuple[float, str]:
    total = doc = 0
    for p in SRC.rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        total, doc = total + 1, doc + (ast.get_docstring(tree) is not None)  # module docstring
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and not n.name.startswith("_"):
                total, doc = total + 1, doc + (ast.get_docstring(n) is not None)
    return doc / total, f"{doc}/{total} public modules, classes and functions have a docstring"


def hint_share() -> tuple[float, str]:
    fns = [f for p in PY_FILES for f in functions(ast.parse(p.read_text(encoding="utf-8")))]
    ok = sum(f.returns is not None or f.name == "__init__" for f in fns)
    return ok / len(fns), f"{ok}/{len(fns)} functions have a return annotation"


def complexity() -> tuple[float, str]:
    worst, long_fns = (0, ""), []
    for p in SRC.rglob("*.py"):
        for f in functions(ast.parse(p.read_text(encoding="utf-8"))):
            branches = sum(
                isinstance(
                    x, ast.If | ast.For | ast.While | ast.Try | ast.BoolOp | ast.ExceptHandler | ast.comprehension | ast.IfExp
                )
                for x in ast.walk(f)
            )
            worst = max(worst, (1 + branches, f"{p.name}:{f.name}"))
            if (f.end_lineno or 0) - f.lineno + 1 > 60:
                long_fns.append(f"{p.name}:{f.name}")
    score = 1.0 - 0.15 * len(long_fns) - 0.05 * max(0, worst[0] - 12)
    return max(0.0, score), f"worst cyclomatic estimate {worst[0]} ({worst[1]}); functions over 60 lines: {long_fns or 'none'}"


def _norm_lines(p: Path) -> list[str]:
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s and not s.startswith(("#", '"""', "import ", "from ", ")", "]", "}")) and len(s) > 12:
            out.append(s)
    return out


def duplication() -> tuple[float, str]:
    seen: dict[str, tuple[str, int]] = {}
    dup = total = 0
    for p in SRC.rglob("*.py"):
        lines = _norm_lines(p)
        total += len(lines)
        for i in range(len(lines) - 5):
            h = hashlib.md5("\n".join(lines[i : i + 6]).encode(), usedforsecurity=False).hexdigest()
            if h in seen and seen[h][0] != f"{p}:{i // 6}":
                dup += 1
            seen.setdefault(h, (f"{p}:{i // 6}", i))
    share = dup / max(1, total)
    return max(0.0, 1.0 - share * 8), f"{share:.1%} of lines sit in a repeated 6-line block"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z_]\w*|\d+|[^\s\w]", re.sub(r"#.*", "", text))


def originality(pack: Path | None) -> tuple[float, str]:
    refs = [p for p in (pack.rglob("*.py") if pack else []) if p.name in ("baseline.py", "evaluate.py")]
    if not refs:
        return 1.0, "organisers' pack not given (--pack): not measured"
    ref = set()
    for p in refs:
        t = _tokens(p.read_text(encoding="utf-8"))
        ref |= {tuple(t[i : i + 12]) for i in range(len(t) - 11)}
    mine = [p for p in PY_FILES if "tools" not in p.parts]
    own = hit = 0
    for p in mine:
        t = _tokens(p.read_text(encoding="utf-8"))
        grams = [tuple(t[i : i + 12]) for i in range(len(t) - 11)]
        own, hit = own + len(grams), hit + sum(g in ref for g in grams)
    share = hit / max(1, own)
    return (
        max(0.0, 1.0 - share * 10),
        f"{share:.2%} of 12-token windows match the organisers' baseline.py or evaluate.py (tools/evaluate.py is declared and excluded)",
    )


def security() -> tuple[float, str]:
    bad = []
    for p in PY_FILES:
        if "tools" in p.parts or p.name == "quality_score.py":
            continue
        text = p.read_text(encoding="utf-8")
        bad += [f"{p.name}: {m.group(0)}" for m in FORBIDDEN.finditer(text)] + [
            f"{p.name}: secret-like string" for _ in SECRET.finditer(text)
        ]
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    unpinned = [ln for ln in reqs.splitlines() if ln and not ln.startswith("#") and "==" not in ln]
    env_ok = (ROOT / ".env.example").exists() and ".env" in (REPO / ".gitignore").read_text(encoding="utf-8")
    needed = [
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "Strict-Transport-Security",
        "compare_digest",
        "check_password_hash",
    ]
    sec_text = (SRC / "voice_of_store" / "web" / "security.py").read_text(encoding="utf-8")
    missing = [n for n in needed if n not in sec_text]
    penalty = 0.2 * len(bad) + 0.05 * len(unpinned) + (0 if env_ok else 0.2) + 0.1 * len(missing)
    return (
        max(0.0, 1.0 - penalty),
        f"forbidden or secret-like: {bad or 'none'}; unpinned: {unpinned or 'none'} (waitress is a minimum version by design); controls missing: {missing or 'none'}",
    )


def traceability() -> tuple[float, str]:
    path = ROOT / "TRACEABILITY.md"
    if not path.exists():
        return 0.0, "TRACEABILITY.md missing"
    text = path.read_text(encoding="utf-8")
    refs = set(re.findall(r"`((?:src|tests|scripts)/[\w/.-]+\.py)`", text))
    tests = set(re.findall(r"`(test_\w+)`", text))
    missing = [r for r in refs if not (ROOT / r).exists()]
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("*.py"))
    absent = [t for t in tests if f"def {t}" not in corpus]
    rows = len(re.findall(r"^\| (?:FR|OUT|NFR|PK|GL)-", text, re.M))
    ok = rows >= 25 and not missing and not absent
    return (
        1.0 if ok else 0.5 if rows else 0.0
    ), f"{rows} requirement rows; missing files: {missing or 'none'}; tests not found: {absent or 'none'}"


def layout() -> tuple[float, str]:
    code, out = run([sys.executable, str(ROOT / "scripts" / "package_check.py")])
    return (1.0 if code == 0 else 0.0), out.strip().splitlines()[-1] if out.strip() else "no output"


def readme() -> tuple[float, str]:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    need = [
        "What it does",
        "How to run",
        "How to run the tests",
        "Architecture",
        "Security",
        "AI usage",
        "Pre-built and third-party code",
        "Limitations",
        "Requirement coverage",
    ]
    missing = [h for h in need if f"## {h}" not in text]
    return 1.0 - len(missing) / len(need), f"sections missing: {missing or 'none'}"


def tool_check(name: str, cmd: list[str]) -> tuple[float | None, str]:
    exe = shutil.which(cmd[0]) or (
        str(Path.home() / ".local/bin" / cmd[0]) if (Path.home() / ".local/bin" / cmd[0]).exists() else None
    )
    if exe is None:
        return None, f"{name} not installed: skipped"
    code, out = run([exe, *cmd[1:]], ROOT)
    return (1.0 if code == 0 else 0.0), ("clean" if code == 0 else out.strip().splitlines()[-1][:120])


def tests(quick: bool) -> tuple[float | None, str]:
    if quick:
        return None, "skipped (--quick)"
    code, out = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], ROOT)
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    return (1.0 if code == 0 else 0.0), tail


def func_cov(quick: bool) -> tuple[float | None, str]:
    if quick:
        return None, "skipped (--quick)"
    code, out = run([sys.executable, str(ROOT / "scripts" / "function_coverage.py")], ROOT)
    m = re.search(r"function coverage ([\d.]+)%", out)
    return (float(m.group(1)) / 100 if m else 0.0), (m.group(0) if m else out.strip()[-120:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, default=None)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    checks = [
        ("Layout and submission rules (package_check)", 10, layout()),
        ("README has every required section", 4, readme()),
        ("Formatter clean (ruff format)", 4, tool_check("ruff format", ["ruff", "format", "--check", ".", "--exclude", "tools"])),
        ("Linter clean (ruff, security rules on)", 5, tool_check("ruff", ["ruff", "check", "."])),
        (
            "Type check (mypy)",
            6,
            tool_check("mypy", ["mypy", "src", "main.py", "detect.py", "make_submission.py", "make_briefs.py", "serve.py"]),
        ),
        ("All tests pass", 10, tests(a.quick)),
        ("Function coverage by tests", 9, func_cov(a.quick)),
        ("Docstring coverage", 8, docstring_share()),
        ("Type-hint coverage", 5, hint_share()),
        ("Complexity and function length", 6, complexity()),
        ("No copy-pasted blocks", 5, duplication()),
        ("Originality against the organisers' code", 6, originality(a.pack)),
        ("Security hygiene", 10, security()),
        ("Requirement traceability (TRACEABILITY.md)", 12, traceability()),
    ]
    earned = possible = 0.0
    print(f"{'Check':50} {'Weight':>6} {'Points':>7}  Detail")
    for name, w, (frac, detail) in checks:
        if frac is None:
            print(f"{name:50} {w:6} {'skip':>7}  {detail}")
            continue
        earned, possible = earned + w * frac, possible + w
        print(f"{name:50} {w:6} {w * frac:7.1f}  {detail}")
    score = 100 * earned / possible
    print(f"\nSELF-AUDIT SCORE: {score:.1f} / 100  ({earned:.1f} of {possible:.0f} points counted)")
    print("This is a self-measured proxy, not the organisers' or a reviewer's score.")
    return 0 if score >= 95 else 1


if __name__ == "__main__":
    sys.exit(main())
