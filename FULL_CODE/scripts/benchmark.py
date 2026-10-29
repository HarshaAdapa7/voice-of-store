"""Measure start-up time and per-request latency of the web app (in process, no network). Run from the repository root:
python FULL_CODE/scripts/benchmark.py [--data data] [--submission submission]"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voice_of_store.web.security import SecurityConfig  # noqa: E402
from voice_of_store.web.server import create_app  # noqa: E402
from voice_of_store.web.state import AppState  # noqa: E402


def timed(call, n: int = 200) -> tuple[float, float]:
    """Median and 95th percentile of `n` calls, in milliseconds."""
    ms = []
    for _ in range(n):
        t = time.perf_counter()
        call()
        ms.append((time.perf_counter() - t) * 1000)
    ms.sort()
    return statistics.median(ms), ms[int(0.95 * (n - 1))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="data")
    ap.add_argument("--submission", default="submission")
    a = ap.parse_args()
    t0 = time.perf_counter()
    state = AppState(Path(a.data), Path(a.submission))
    print(f"start-up (load, train, classify {len(state.rows):,} rows): {time.perf_counter() - t0:.1f} s")  # noqa: T201
    t0 = time.perf_counter()
    state.warm()
    print(f"warm-up (all briefs and the report): {time.perf_counter() - t0:.1f} s")  # noqa: T201
    cfg = SecurityConfig(rate_per_minute=10**9, classify_per_minute=10**9, assistant_per_minute=10**9)
    client = create_app(state, cfg).test_client()
    week, region, store = state.test_weeks[-1], state.regions[0], next(iter(state.store_name))
    calls = {
        "GET /api/brief": lambda: client.get("/api/brief", query_string={"region": region, "week": week}),
        "GET /api/flags": lambda: client.get("/api/flags", query_string={"week": week}),
        "GET /api/store": lambda: client.get("/api/store", query_string={"store_id": store, "week": week}),
        "GET /report": lambda: client.get("/report"),
        "POST /api/assistant": lambda: client.post("/api/assistant", json={"message": "How is Kothrud doing?"}),
        "POST /api/classify": lambda: client.post(
            "/api/classify", json={"text": "freezer not cooling at Kothrud", "channel": "in_app"}
        ),
    }
    for name, call in calls.items():
        p50, p95 = timed(call)
        print(f"{name:22s} median {p50:6.1f} ms   p95 {p95:6.1f} ms")  # noqa: T201


if __name__ == "__main__":
    main()
