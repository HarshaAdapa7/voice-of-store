#!/usr/bin/env python3
"""Injection grid: plant synthetic incidents into the real stream and measure lead time and false-flag volume.

    python FULL_CODE/scripts/injection_grid.py --data data [--n 240] [--seed 5]

Incident shapes (reports per week from onset): the public worked example's rise (1,3,5,25,10,5,3), a faster burst,
and a slower ramp. The naive week uses the pack's definition. This is a sanity harness on synthetic injections, not a
claim about the hidden incidents. Runs the statistic only (the classifier is trained once for the clean history).
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from voice_of_store import config as C  # noqa: E402
from voice_of_store.detect import run_statistic, weekly_counts  # noqa: E402
from voice_of_store.io import load_data  # noqa: E402
from voice_of_store.pipeline import prepare_rows  # noqa: E402
from voice_of_store.stores import StoreResolver  # noqa: E402

SHAPES = {"worked_example": [1, 3, 5, 25, 10, 5, 3], "burst": [2, 9, 22, 10, 4], "slow_ramp": [1, 1, 2, 3, 5, 8, 12, 8]}


def naive_week(chain: np.ndarray, onset: int) -> int | None:
    """First week >= onset whose chain count exceeds mean + 3*max(sd, sqrt(mean), 1) of the previous up-to-8 weeks."""
    for w in range(max(onset, 2), len(chain)):
        h = chain[max(0, w - 8) : w]
        mu, sd = h.mean(), h.std()
        if chain[w] > mu + 3 * max(sd, np.sqrt(mu), 1):
            return w
    return None


def run(counts, foot, params, n_inj, seed):
    rng = np.random.default_rng(seed)
    n_s, n_t, n_w = counts.shape
    order = np.argsort(foot)
    bands = {"small": order[:20], "mid": order[20:40], "large": order[40:]}
    clean = run_statistic(counts, foot, params, tie_rank=np.arange(n_s))
    test_weeks = slice(13, 26) if n_w >= 26 else slice(0, n_w)
    flags_pw = clean["flag"][:, :, test_weeks].sum() / max(1, (min(n_w, 26) - 13))
    res = {k: [] for k in bands}
    for _ in range(n_inj):
        shape_name = rng.choice(list(SHAPES))
        shape = SHAPES[shape_name]
        band = rng.choice(list(bands))
        s = int(rng.choice(bands[band]))
        t = int(rng.integers(0, n_t))
        onset = int(rng.integers(5, n_w - len(shape) - 1))
        inj = counts.copy()
        for k, c in enumerate(shape):
            inj[s, t, onset + k] += c
        nv = naive_week(inj[:, t, :].sum(axis=0), onset)
        if nv is None:
            continue
        r = run_statistic(inj, foot, params, tie_rank=np.arange(n_s))
        fl = np.nonzero(r["flag"][s, t, onset:])[0]
        det = onset + int(fl[0]) if len(fl) else None
        lead = -2 if det is None else int(np.clip(nv - det, -2, 4))
        res[band].append((lead + 2) / 6)
    allv = [v for b in res.values() for v in b]
    return flags_pw, {b: (float(np.mean(v)) if v else float("nan")) for b, v in res.items()}, float(np.mean(allv))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--n", type=int, default=240)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--grid", action="store_true", help="search thresholds (slower)")
    a = ap.parse_args()
    d = load_data(Path(a.data))
    resolver = StoreResolver(d.stores)
    rows = prepare_rows(d, d.feedback["created_at"].max() + pd.Timedelta(seconds=1), resolver)
    cal = d.calendar["week_start"].tolist()
    stores = d.stores.sort_values("store_name")["store_id"].tolist()
    types = [t for t in C.ISSUE_TYPES if t not in C.NON_ISSUE]
    foot = d.stores.set_index("store_id")["avg_weekly_footfall"].reindex(stores).to_numpy(float)
    iss = rows[~rows["itype"].isin(C.NON_ISSUE) & rows["store"].notna()]
    counts = weekly_counts(iss, stores, types, cal)
    grids = [dict()]
    if a.grid:
        keys = dict(h=[2.0, 3.0, 4.0, 5.0], mult=[3.0, 4.0, 6.0], prior=[2.0, 3.0, 6.0], history=[8, 10, 14], cooldown=[2, 4])
        grids = [dict(zip(keys, v, strict=False)) for v in itertools.product(*keys.values())]
    for g in grids:
        fpw, bands, mean_lead = run(counts, foot, g, a.n, a.seed)
        flood = min(1.0, 3.0 / fpw) if fpw > 0 else 1.0
        print(
            f"{g}  clean flags/wk {fpw:.2f}  lead score {mean_lead:.3f} x flood {flood:.2f} = {mean_lead * flood:.3f}  by band {bands}"
        )


if __name__ == "__main__":
    main()
