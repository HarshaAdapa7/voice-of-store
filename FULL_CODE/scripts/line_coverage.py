"""Line coverage of src/ using the standard library only (sys.monitoring, Python 3.12+), for machines without coverage.py.

Usage: python FULL_CODE/scripts/line_coverage.py [pytest args]   (run from FULL_CODE; prints a table, exit 1 below 85 percent)
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import CodeType

HERE = Path(__file__).resolve().parents[1]
SRC = (HERE / "src" / "voice_of_store").resolve()
TARGET = 85.0
hit: dict[str, set[int]] = {}


def on_line(code: CodeType, line: int) -> object:
    if code.co_filename.startswith(str(SRC)):
        hit.setdefault(code.co_filename, set()).add(line)
        return None
    return sys.monitoring.DISABLE  # not our code: stop watching this line


def executable_lines(path: Path) -> set[int]:
    lines: set[int] = set()

    def walk(code: CodeType) -> None:
        lines.update(ln for _, _, ln in code.co_lines() if ln is not None)
        for const in code.co_consts:
            if isinstance(const, CodeType):
                walk(const)

    walk(compile(path.read_text(encoding="utf-8"), str(path), "exec"))
    return lines


def main() -> int:
    import pytest

    mon = sys.monitoring
    mon.use_tool_id(mon.COVERAGE_ID, "r5cov")
    mon.register_callback(mon.COVERAGE_ID, mon.events.LINE, on_line)
    mon.set_events(mon.COVERAGE_ID, mon.events.LINE)
    code = pytest.main(["-q", "-p", "no:cacheprovider", *sys.argv[1:]])
    mon.set_events(mon.COVERAGE_ID, 0)
    total = covered = 0
    rows = []
    for path in sorted(SRC.rglob("*.py")):
        want = executable_lines(path)
        got = hit.get(str(path), set()) & want
        total, covered = total + len(want), covered + len(got)
        rows.append((100 * len(got) / max(1, len(want)), str(path.relative_to(SRC)), len(want) - len(got)))
    for pct, name, missing in sorted(rows):
        print(f"{pct:5.1f}%  {name}  ({missing} lines not run)")  # noqa: T201
    overall = 100 * covered / max(1, total)
    print(f"overall line coverage {overall:.1f}% (target {TARGET:.0f}%)")  # noqa: T201
    return 0 if code == 0 and overall >= TARGET else 1


if __name__ == "__main__":
    sys.exit(main())
