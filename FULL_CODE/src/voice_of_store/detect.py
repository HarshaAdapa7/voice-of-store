"""Emerging-issue detector: per (store, issue type) weekly counts, exposure-normalised, Gamma-Poisson shrunk toward
the chain rate, with a sequential log-likelihood-ratio (CUSUM-style) statistic. Causal by construction: the statistic
for week w reads only weeks <= w."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config as C


def weekly_counts(rows: pd.DataFrame, stores: list[str], types: list[str], weeks: list[str]) -> np.ndarray:
    """rows needs columns store, itype, week. Returns an int array [store, type, week]."""
    s_ix = {s: i for i, s in enumerate(stores)}
    t_ix = {t: i for i, t in enumerate(types)}
    w_ix = {w: i for i, w in enumerate(weeks)}
    out = np.zeros((len(stores), len(types), len(weeks)), dtype=float)
    sub = rows[rows["store"].isin(s_ix) & rows["itype"].isin(t_ix) & rows["week"].isin(w_ix)]
    g = sub.groupby(["store", "itype", "week"]).size()
    for (s, t, w), n in g.items():
        out[s_ix[s], t_ix[t], w_ix[w]] = n
    return out


def _default_params() -> dict:
    return dict(
        history=C.HISTORY_WEEKS,
        prior=C.PRIOR_STRENGTH,
        mult=C.ALT_MULTIPLIER,
        h=C.LLR_THRESHOLD,
        min_n=C.MIN_WEEK_COUNT,
        min_base=C.MIN_BASE_WEEKS,
        cooldown=C.COOLDOWN_WEEKS,
        cap=C.MAX_FLAGS_PER_WEEK,
    )


def expected_counts(counts: np.ndarray, e: np.ndarray, w: int, p: dict) -> np.ndarray:
    """Expected reports per (store, type) in week `w` if nothing unusual happens, from weeks before `w` only.

    chain rate per footfall x store/type multiplier (Gamma-Poisson shrinkage toward 1) x chain-wide factor. The factor
    uses every other store (leave-one-out), so a chain-wide spike is not blamed on one store and an incident at one
    store does not inflate its own baseline."""
    lo = max(0, w - p["history"])
    chain = counts.sum(axis=0)  # [T, W]
    e_tot = e.sum()
    hist_chain = chain[:, lo:w].sum(axis=1) / (e_tot * (w - lo))  # [T] chain rate per footfall
    hist_n = counts[:, :, lo:w].sum(axis=2)  # [S, T]
    hist_exp = e[:, None] * hist_chain[None, :] * (w - lo)
    ratio = (hist_n + p["prior"]) / (hist_exp + p["prior"])
    cur_chain_loo = (chain[:, w][None, :] - counts[:, :, w]) / np.maximum(e_tot - e, 1e-9)[:, None]
    factor = np.maximum(1.0, cur_chain_loo / np.maximum(hist_chain[None, :], 1e-12))
    return np.maximum(e[:, None] * hist_chain[None, :] * ratio * factor, 1e-4)


def _cap_flags(fire: np.ndarray, state: np.ndarray, cap: int, tie_rank: np.ndarray | None) -> np.ndarray:
    """Keep at most `cap` flags: highest statistic first, ties broken by store order then type."""
    if fire.sum() <= cap:
        return fire
    ss, tt = np.nonzero(fire)
    tie = tie_rank[ss] if tie_rank is not None else ss
    order = np.lexsort((tt, tie, -state[ss, tt]))[:cap]
    kept = np.zeros_like(fire)
    kept[ss[order], tt[order]] = True
    return kept


def run_statistic(
    counts: np.ndarray, exposure: np.ndarray, params: dict | None = None, tie_rank: np.ndarray | None = None
) -> dict:
    """Run the detector over every week in `counts`.

    counts   [S, T, W] reports per store, type and week
    exposure [S] relative store size (average weekly footfall)
    tie_rank [S] order used to break ties between equal scores (store name order), lower first
    Returns dict with arrays expected, llr, cusum, flag (all [S, T, W]).
    """
    p = _default_params()
    if params:
        p.update(params)
    n_s, n_t, n_w = counts.shape
    expected, llr, cusum = (np.zeros_like(counts) for _ in range(3))
    flag = np.zeros(counts.shape, dtype=bool)
    state = np.zeros((n_s, n_t))
    last_flag = np.full((n_s, n_t), -(10**6))
    ln_m = math.log(p["mult"])
    for w in range(p["min_base"], n_w):
        mu = expected_counts(counts, exposure.astype(float), w, p)
        n = counts[:, :, w]
        step = n * ln_m - (p["mult"] - 1.0) * mu  # log-likelihood ratio: rate x mult versus baseline
        state = np.maximum(0.0, state + step)  # CUSUM: evidence accumulates, never below zero
        expected[:, :, w], llr[:, :, w], cusum[:, :, w] = mu, step, state
        eff = state * p["weights"][None, :] if "weights" in p and p["weights"] is not None else state
        fire = (eff >= p["h"]) & (n >= p["min_n"]) & ((w - last_flag) > p["cooldown"])
        fire = _cap_flags(fire, eff, p["cap"], tie_rank)
        flag[:, :, w] = fire
        state = np.where(fire, 0.0, state)
        last_flag = np.where(fire, w, last_flag)
    return dict(expected=expected, llr=llr, cusum=cusum, flag=flag)
