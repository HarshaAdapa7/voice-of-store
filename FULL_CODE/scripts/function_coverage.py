"""Function-level coverage of src/ by the test suite, using the interpreter's own monitoring hook (Python 3.12+).

Prints `function coverage NN.N%` and lists the functions no test reached. It is a coarser measure than line coverage but
needs no extra package. Run from FULL_CODE: python scripts/function_coverage.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "src").resolve()
mon = sys.monitoring
TOOL = mon.COVERAGE_ID
seen: set[tuple[str, int]] = set()


def _on_start(code: object, _offset: int) -> object:
    if code.co_filename.startswith(str(SRC)):  # type: ignore[attr-defined]
        seen.add((code.co_filename, code.co_firstlineno))  # type: ignore[attr-defined]
    return mon.DISABLE


def main() -> int:
    sys.path.insert(0, str(SRC))
    mon.use_tool_id(TOOL, "r5-function-coverage")
    mon.register_callback(TOOL, mon.events.PY_START, _on_start)
    mon.set_events(TOOL, mon.events.PY_START)
    rc = pytest.main(["-q", "-p", "no:cacheprovider", str(ROOT / "tests")])
    mon.set_events(TOOL, 0)
    defined: dict[tuple[str, int], str] = {}
    for p in SRC.rglob("*.py"):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
                first = min([n.lineno, *(d.lineno for d in n.decorator_list)])
                defined[(str(p), n.lineno)] = f"{p.relative_to(SRC)}:{n.name}"
                defined[(str(p), first)] = f"{p.relative_to(SRC)}:{n.name}"
    names = {v for v in defined.values()}
    hit = {defined[k] for k in seen if k in defined}
    missed = sorted(names - hit)
    pct = 100 * len(hit) / max(1, len(names))
    print(f"function coverage {pct:.1f}% ({len(hit)}/{len(names)}); not reached: {missed}")
    return int(rc != 0)


if __name__ == "__main__":
    sys.exit(main())
