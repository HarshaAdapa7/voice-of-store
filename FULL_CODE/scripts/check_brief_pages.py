"""Print every generated brief to A4 in headless Chromium and report how many pages each takes (the brief must be one page).

Needs Playwright (development only, not in requirements.txt). Usage: python FULL_CODE/scripts/check_brief_pages.py [out/briefs]
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path


def count_pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def main() -> int:
    from playwright.sync_api import sync_playwright

    root = Path(sys.argv[1] if len(sys.argv) > 1 else "out/briefs").resolve()
    files = sorted(root.glob("*/*.html"))
    if not files:
        print(f"no briefs under {root}")  # noqa: T201
        return 2
    pages: Counter = Counter()
    over: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for f in files:
            page.goto(f.as_uri())
            n = count_pages(page.pdf(format="A4", prefer_css_page_size=True, print_background=True))
            pages[n] += 1
            if n > 1:
                over.append(f"{f.parent.name}/{f.stem}: {n} pages")
        browser.close()
    print(f"{len(files)} briefs; pages per brief: {dict(pages)}")  # noqa: T201
    for line in over[:10]:
        print("  over one page:", line)  # noqa: T201
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
