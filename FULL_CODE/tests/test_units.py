import numpy as np
import pandas as pd

from voice_of_store import config as C
from voice_of_store.detect import run_statistic
from voice_of_store.io import validate_flags, validate_predictions
from voice_of_store.stores import StoreResolver, locality
from voice_of_store.text import normalise


def test_normalise_masks_ids_and_urls():  # T03/T04
    assert normalise("Call 9876543210 http://x.y/z  NOW") == "call num url now"
    assert normalise("") == ""


def test_locality_and_resolver():  # T05-T07
    stores = pd.DataFrame({"store_id": ["A", "B"], "store_name": ["Saffron Market Kothrud", "Saffron Hyper Salt Lake City"]})
    r = StoreResolver(stores)
    assert locality("Saffron Express Koramangala 4th Block") == "koramangala 4th block"
    assert r.resolve("A", "anything") == "A"
    assert r.resolve(None, "queue at KOTHRUD store") == "A"
    assert r.resolve(float("nan"), "no place named") is None
    assert r.resolve(None, "kothrud and salt lake city") is None  # ambiguous, not guessed


def test_validators():  # T01/T02
    ids = pd.Series(["a", "b"])
    good = pd.DataFrame({"feedback_id": ["a", "b"], "issue_type_id": ["IT01", "NI01"], "severity": ["low", "low"], "actionable": [1, 0]})
    assert validate_predictions(good, ids) == []
    bad = good.assign(severity=["urgent", "low"])
    assert validate_predictions(bad, ids)
    assert validate_flags(pd.DataFrame(columns=C.FLAG_COLS)) == []  # header-only is allowed
    dup = pd.DataFrame([["2026-01-05", "S", "IT01", 0.5, "x;y"]] * 2, columns=C.FLAG_COLS)
    assert validate_flags(dup)


def _quiet(n_s=6, n_t=2, n_w=20, rate=0.4, seed=1):
    rng = np.random.default_rng(seed)
    return rng.poisson(rate, size=(n_s, n_t, n_w)).astype(float)


def test_detector_catches_planted_rise_before_naive():  # T20-T22
    c = _quiet()
    for k, v in enumerate([1, 3, 5, 25, 10]):
        c[2, 0, 10 + k] += v
    r = run_statistic(c, np.full(6, 10000.0), tie_rank=np.arange(6))
    weeks = np.nonzero(r["flag"][2, 0])[0]
    assert len(weeks) and weeks[0] <= 12


def test_detector_quiet_stream_rarely_flags():  # T23
    c = _quiet(n_s=30, n_t=5, n_w=26, seed=3)
    r = run_statistic(c, np.full(30, 10000.0), tie_rank=np.arange(30))
    assert r["flag"].sum() / 26 <= 1.0


def test_detector_needs_two_reports_and_respects_cap():  # T24/T27
    c = np.zeros((10, 1, 12))
    c[:, 0, 8] = 1.0  # ten stores one report each: below min count, so no flag
    assert run_statistic(c, np.full(10, 1000.0))["flag"].sum() == 0
    c[:, 0, 9] = 40.0
    r = run_statistic(c, np.full(10, 1000.0), tie_rank=np.arange(10))
    assert r["flag"][:, :, 9].sum() <= C.MAX_FLAGS_PER_WEEK


def test_detector_is_causal():  # T30 (statistic level): changing future weeks never changes earlier output
    c = _quiet(seed=5)
    full = run_statistic(c, np.full(6, 5000.0), tie_rank=np.arange(6))
    c2 = c.copy()
    c2[:, :, 12:] = 50.0
    cut = run_statistic(c2, np.full(6, 5000.0), tie_rank=np.arange(6))
    assert np.array_equal(full["flag"][:, :, :12], cut["flag"][:, :, :12])
    assert np.allclose(full["cusum"][:, :, :12], cut["cusum"][:, :, :12])
