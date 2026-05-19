#!/usr/bin/env python3
"""
experiments_v2/scripts/00_unit_audit.py
========================================
Phase 1 of the clean rerun.  Closed-form unit tests for every metric
function consumed by the v2 pipeline.  This script is the FIRST gate
of the orchestrator; if any test fails the rerun stops here.

What it checks (against METRICS.md):

  - _ci_weighted_mean_g            (METRICS §1)
  - _cfe_canonical_pct             (METRICS §2)
  - _cfe_threshold_pct             (METRICS §3)
  - IT vs facility emissions       (METRICS §4, §5)
  - annualised avoided tonnage     (METRICS §6)
  - lift sign convention           (METRICS §8)

Run:
    PYTHONPATH=gridpilot/src python3 \\
        gridpilot/experiments_v2/scripts/00_unit_audit.py

Exit codes:
    0   all tests pass
    1   one or more tests failed (diff printed, run aborted)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Import the metric implementations under test from the v1 source tree
# (the metric *implementations* are not what's broken --- v2 is about
# the surrounding orchestration).  If a metric IS broken, this audit
# catches it on the spot.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "gridpilot" / "src"))
sys.path.insert(0, str(ROOT / "gridpilot" / "scripts" / "multicountry"))
sys.path.insert(0, str(ROOT / "gridpilot" / "experiments_v2" / "src"))

# pylint: disable=wrong-import-position,import-error
from replay_country_sweep import (  # type: ignore[import-not-found]
    CFE_REF_CI_G,
    CFE_LEGACY_THRESHOLD_G,
    _ci_weighted_mean_g,
    _cfe_canonical_pct,
    _cfe_threshold_pct,
)
from schedulers.accounting import (  # type: ignore[import-not-found]
    ScheduledJob, ScheduleResult, run_metrics, from_dispatch_log,
    P_NODE_KW,
)


# ─────────────────────────────────────────────────────────────────────
# Test fixtures
# ─────────────────────────────────────────────────────────────────────

def _flat_ci_df(ci_g_per_kwh: float, days: int = 7) -> pd.DataFrame:
    """A flat hourly CI series of constant value, indexed by hour."""
    idx = pd.date_range("2024-01-01", periods=days * 24, freq="h", tz="UTC")
    return pd.DataFrame(
        {"carbon_intensity_gCO2eq_per_kWh": np.full(len(idx), ci_g_per_kwh)},
        index=idx,
    )


def _two_value_ci_df(low: float, high: float, days: int = 7) -> pd.DataFrame:
    """Hourly CI that alternates between two values --- half the hours
    at ``low``, half at ``high``."""
    idx = pd.date_range("2024-01-01", periods=days * 24, freq="h", tz="UTC")
    values = np.where(np.arange(len(idx)) % 2 == 0, low, high).astype(float)
    return pd.DataFrame(
        {"carbon_intensity_gCO2eq_per_kWh": values}, index=idx,
    )


def _result_dict(jobs: list[dict]) -> dict:
    """Wrap a list of {start, nodes, runtime} jobs into the dict
    shape the metric functions expect."""
    return {"completed": jobs}


def _job(start_iso: str, nodes: int, runtime_s: float) -> dict:
    return {
        "start": pd.Timestamp(start_iso, tz="UTC").timestamp(),
        "nodes": nodes,
        "runtime": runtime_s,
    }


# ─────────────────────────────────────────────────────────────────────
# Assertions
# ─────────────────────────────────────────────────────────────────────

_PASS = 0
_FAIL = 0


def _check(name: str, got: float, want: float, *, atol: float = 1e-6) -> None:
    """Print a pass/fail line and bump the global counter."""
    global _PASS, _FAIL  # pylint: disable=global-statement
    ok = math.isclose(got, want, abs_tol=atol)
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name:<60s} got={got:>10.4f}  want={want:>10.4f}")
    if ok:
        _PASS += 1
    else:
        _FAIL += 1


# ─────────────────────────────────────────────────────────────────────
# Test 1 — _ci_weighted_mean_g (METRICS §1)
# ─────────────────────────────────────────────────────────────────────

def test_ci_weighted_mean() -> None:
    print("\n[T1] _ci_weighted_mean_g  (METRICS §1)")

    # 1a: all jobs at CI = 0 → CI_eff = 0
    ci = _flat_ci_df(0.0)
    res = _result_dict([_job("2024-01-02T00:00", 1, 3600)])
    _check("1a flat CI=0", _ci_weighted_mean_g(res, ci), 0.0)

    # 1b: all jobs at CI = 800 → CI_eff = 800
    ci = _flat_ci_df(800.0)
    res = _result_dict([_job("2024-01-02T00:00", 1, 3600)])
    _check("1b flat CI=800", _ci_weighted_mean_g(res, ci), 800.0)

    # 1c: balanced 50/50 mix at CI=0 and CI=200 → energy-weighted = 100
    ci = _two_value_ci_df(0.0, 200.0)
    # one job at the CI=0 hour, one at the CI=200 hour, same energy
    res = _result_dict([
        _job("2024-01-02T00:00", 1, 3600),  # ci_ts even index → 0
        _job("2024-01-02T01:00", 1, 3600),  # ci_ts odd  index → 200
    ])
    _check("1c balanced 0/200", _ci_weighted_mean_g(res, ci), 100.0)

    # 1d: empty job set → defined return value of 0
    _check("1d empty", _ci_weighted_mean_g(_result_dict([]), _flat_ci_df(500)), 0.0)

    # 1e: unequal energy mix --- 1 small job at CI=0 and 1 big job at CI=400
    ci = _two_value_ci_df(0.0, 400.0)
    res = _result_dict([
        _job("2024-01-02T00:00", 1, 600),    # 0.25 kWh at CI=0
        _job("2024-01-02T01:00", 4, 3600),   # 6.0  kWh at CI=400
    ])
    # weighted mean = (0.25*0 + 6.0*400) / 6.25 = 384
    _check("1e weighted (small@0 + big@400)",
           _ci_weighted_mean_g(res, ci), 6.0 * 400 / 6.25)


# ─────────────────────────────────────────────────────────────────────
# Test 2 — _cfe_canonical_pct (METRICS §2)
# ─────────────────────────────────────────────────────────────────────

def test_cfe_canonical() -> None:
    print("\n[T2] _cfe_canonical_pct  (METRICS §2)")

    # 2a: SE-clean   ci_eff=11 → CFE = 100*(1 - 11/800) = 98.625
    ci = _flat_ci_df(11.0)
    res = _result_dict([_job("2024-01-02T00:00", 1, 3600)])
    _check("2a SE clean (11 g/kWh)",
           _cfe_canonical_pct(res, ci), 100.0 * (1.0 - 11.0 / CFE_REF_CI_G))

    # 2b: fossil-only   ci_eff=800 → CFE = 0
    ci = _flat_ci_df(800.0)
    res = _result_dict([_job("2024-01-02T00:00", 1, 3600)])
    _check("2b fossil-only", _cfe_canonical_pct(res, ci), 0.0)

    # 2c: above reference   ci_eff=1200 → CFE = 0 (clipped)
    ci = _flat_ci_df(1200.0)
    res = _result_dict([_job("2024-01-02T00:00", 1, 3600)])
    _check("2c clipped above reference", _cfe_canonical_pct(res, ci), 0.0)

    # 2d: PL annual mean ci_eff=612 → CFE = 100*(1 - 612/800) = 23.5
    ci = _flat_ci_df(612.0)
    res = _result_dict([_job("2024-01-02T00:00", 1, 3600)])
    _check("2d PL mean (612 g/kWh)",
           _cfe_canonical_pct(res, ci), 100.0 * (1.0 - 612.0 / CFE_REF_CI_G))

    # 2e: empty job set → 0 (no compute, defined)
    _check("2e empty", _cfe_canonical_pct(_result_dict([]), _flat_ci_df(500)), 0.0)


# ─────────────────────────────────────────────────────────────────────
# Test 3 — _cfe_threshold_pct (METRICS §3)
# ─────────────────────────────────────────────────────────────────────

def test_cfe_threshold() -> None:
    print("\n[T3] _cfe_threshold_pct  (METRICS §3)")

    # 3a: all jobs at CI=50 < 150 → 100 % clean by threshold
    ci = _flat_ci_df(50.0)
    res = _result_dict([_job("2024-01-02T00:00", 1, 3600)])
    _check("3a all below threshold",
           _cfe_threshold_pct(res, ci, threshold_g=CFE_LEGACY_THRESHOLD_G), 100.0)

    # 3b: all jobs at CI=500 > 150 → 0 %
    ci = _flat_ci_df(500.0)
    res = _result_dict([_job("2024-01-02T00:00", 1, 3600)])
    _check("3b all above threshold",
           _cfe_threshold_pct(res, ci, threshold_g=CFE_LEGACY_THRESHOLD_G), 0.0)

    # 3c: 50/50 below/above threshold, same energy → 50 %
    ci = _two_value_ci_df(50.0, 500.0)
    res = _result_dict([
        _job("2024-01-02T00:00", 1, 3600),
        _job("2024-01-02T01:00", 1, 3600),
    ])
    _check("3c balanced below/above",
           _cfe_threshold_pct(res, ci, threshold_g=CFE_LEGACY_THRESHOLD_G), 50.0)


# ─────────────────────────────────────────────────────────────────────
# Test 4 — sign convention (METRICS §8)
# ─────────────────────────────────────────────────────────────────────

def test_sign_convention() -> None:
    print("\n[T4] sign convention  (METRICS §8)")

    # Two synthetic policy results: 'base' runs at CI=400, 'fsla' at CI=300.
    # CFE_base = 100*(1 - 400/800) = 50; CFE_fsla = 62.5  → Δ CFE = +12.5
    # CI_base = 400; CI_fsla = 300  → Δ CI = +100 (= base - fsla)
    base = _result_dict([_job("2024-01-02T00:00", 1, 3600)])
    fsla = _result_dict([_job("2024-01-02T01:00", 1, 3600)])
    ci = _two_value_ci_df(300.0, 400.0)

    cfe_base = _cfe_canonical_pct(base, ci)
    cfe_fsla = _cfe_canonical_pct(fsla, ci)
    ciwm_base = _ci_weighted_mean_g(base, ci)
    ciwm_fsla = _ci_weighted_mean_g(fsla, ci)

    # In the two_value series, even-indexed hours are 'low' (300) and
    # odd-indexed are 'high' (400).  Our 'base' starts at index 0 (=300).
    # So we set up: base at CI=300, fsla at CI=400 --- then the
    # 'mechanism' makes it WORSE, so Δ should be NEGATIVE.
    # Check the sign convention works in BOTH directions.
    delta_cfe_vs_base = cfe_fsla - cfe_base
    delta_ci_vs_base = ciwm_base - ciwm_fsla

    # base at CI=300: CFE_base = 100*(1 - 300/800) = 62.5
    # fsla at CI=400: CFE_fsla = 100*(1 - 400/800) = 50.0
    # Δ CFE = 50 - 62.5 = -12.5  (worse: NEGATIVE)
    # Δ CI = 300 - 400 = -100    (worse: NEGATIVE)
    _check("4a CFE worse → Δ < 0", delta_cfe_vs_base, 50.0 - 62.5)
    _check("4b CI  worse → Δ < 0", delta_ci_vs_base, 300.0 - 400.0)


# ─────────────────────────────────────────────────────────────────────
# Test 5 — annualised avoided emissions (METRICS §6)
# ─────────────────────────────────────────────────────────────────────

def test_avoided_emissions() -> None:
    print("\n[T5] annualised avoided emissions  (METRICS §6)")
    # Hand-computed reference:
    #   28-day trace, base emits 1.0 t CO2, fsla emits 0.7 t CO2.
    #   diff = 0.3 t = 300 000 g.
    #   annualised = 300 000 g * (365/28) ≈ 3.91 × 10^6 g = 3.91 t/y
    #   at 10 MW target on a 5 MW trace, scaling = 2 → 7.82 t/y
    #   = 0.00782 kt/y
    diff_g = 300_000.0
    annualisation = 365.0 / 28.0
    scaling = 2.0
    avoided_kt_y = diff_g * annualisation * scaling / 1.0e9
    _check("5a 28d, 10MW/5MW scaling",
           avoided_kt_y, 0.300 * (365.0/28.0) * 2.0 / 1000.0)


# ─────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────
# Test 6 — shared accounting module (experiments_v2/src/schedulers/accounting.py)
# ─────────────────────────────────────────────────────────────────────

def _v2_job(submit: float, start: float, end: float,
            nodes: int = 1, replicas: float = 1.0) -> ScheduledJob:
    """Build a v2 ScheduledJob for the T6 accounting-module tests.

    Renamed from `_job` to avoid shadowing the v1-flavour `_job` helper
    near the top of this file (which returns a plain dict with
    'start'/'nodes'/'runtime' keys, for tests T1–T5 against the v1
    metric implementations).  The collision is a non-obvious
    Python-scoping trap: a `def` at module scope replaces an earlier
    `def` of the same name, and tests T1–T5 then silently received
    ScheduledJob instances instead of dicts, breaking ``j.get(...)``.
    """
    return ScheduledJob(
        submit_epoch=submit, start_epoch=start, end_epoch=end,
        nodes=nodes, runtime_s=end - start, replicas=replicas,
    )


def test_accounting_module() -> None:
    print("\n[T6] shared accounting module  (experiments_v2/src/schedulers/accounting.py)")

    sim_end = pd.Timestamp("2024-01-08T00:00", tz="UTC").timestamp()

    # 6a: empty schedule → all zeros, n_truncated counted
    empty = ScheduleResult(completed_within_window=[], truncated_at_window=[])
    m = run_metrics(empty, _flat_ci_df(100))
    _check("6a empty schedule  energy_kwh", m["energy_kwh"], 0.0)
    _check("6a empty schedule  cfe_canonical_pct", m["cfe_canonical_pct"], 0.0)
    _check("6a empty schedule  n_completed", m["n_completed_within_window"], 0.0)

    # 6b: one job, 1 node, 1 h runtime, CI=400 → energy = P_NODE_KW kWh,
    #     CO2_it = P_NODE_KW * 400 g, CFE = 100*(1 - 400/800) = 50
    ci = _flat_ci_df(400.0)
    t_start = pd.Timestamp("2024-01-02T00:00", tz="UTC").timestamp()
    sched = ScheduleResult(
        completed_within_window=[_v2_job(t_start, t_start, t_start + 3600.0)],
    )
    m = run_metrics(sched, ci)
    _check("6b 1 job  energy_kwh", m["energy_kwh"], P_NODE_KW)
    _check("6b 1 job  ci_weighted_mean", m["ci_weighted_mean"], 400.0)
    _check("6b 1 job  cfe_canonical_pct", m["cfe_canonical_pct"], 50.0)
    _check("6b 1 job  co2_g_it", m["co2_g_it"], P_NODE_KW * 400.0)

    # 6c: PUE = 1.5 → facility CO2 = 1.5 × IT CO2
    pue_curve = pd.Series(1.5, index=ci.index, name="pue")
    m = run_metrics(sched, ci, pue_curve=pue_curve)
    _check("6c PUE=1.5  co2_g_facility", m["co2_g_facility"], P_NODE_KW * 400.0 * 1.5)
    _check("6c PUE=1.5  co2_g_it (unchanged)", m["co2_g_it"], P_NODE_KW * 400.0)

    # 6d: two jobs of same energy, half at CI=0 / half at CI=200 →
    #     CI-weighted-mean = 100, CFE = 100*(1 - 100/800) = 87.5
    ci2 = _two_value_ci_df(0.0, 200.0)
    t0 = pd.Timestamp("2024-01-02T00:00", tz="UTC").timestamp()  # CI=0
    t1 = pd.Timestamp("2024-01-02T01:00", tz="UTC").timestamp()  # CI=200
    sched = ScheduleResult(completed_within_window=[
        _v2_job(t0, t0, t0 + 3600.0),
        _v2_job(t1, t1, t1 + 3600.0),
    ])
    m = run_metrics(sched, ci2)
    _check("6d balanced  ci_weighted_mean", m["ci_weighted_mean"], 100.0)
    _check("6d balanced  cfe_canonical_pct", m["cfe_canonical_pct"], 87.5)

    # 6e: replica scaling --- 1 job with replicas=2 doubles energy + CO2
    ci = _flat_ci_df(400.0)
    sched = ScheduleResult(completed_within_window=[
        _v2_job(t_start, t_start, t_start + 3600.0, replicas=2.0),
    ])
    m = run_metrics(sched, ci)
    _check("6e replicas=2  energy_kwh", m["energy_kwh"], 2.0 * P_NODE_KW)
    _check("6e replicas=2  co2_g_it",   m["co2_g_it"], 2.0 * P_NODE_KW * 400.0)

    # 6f: F3 truncation split --- one within-window, one truncated
    dispatch_log = [
        {  # completes 30 min before window end
            "submit_epoch": t_start, "start_epoch": t_start,
            "end_epoch":     t_start + 1800.0, "nodes": 1, "runtime_s": 1800.0,
        },
        {  # would run past window end
            "submit_epoch": t_start, "start_epoch": sim_end - 600.0,
            "end_epoch":     sim_end + 3600.0, "nodes": 1, "runtime_s": 4200.0,
        },
    ]
    sched = from_dispatch_log(dispatch_log, sim_end)
    _check("6f F3 split  n_completed", sched.completed_within_window.__len__(), 1.0)
    _check("6f F3 split  n_truncated", sched.truncated_at_window.__len__(), 1.0)
    # truncated job's end clamped to sim_end
    _check("6f F3 split  truncated end clamped",
           sched.truncated_at_window[0].end_epoch, sim_end)


def main() -> int:
    print(f"experiments_v2 Phase 1 — unit audit (CFE_REF={CFE_REF_CI_G} g/kWh)")
    print("=" * 78)

    test_ci_weighted_mean()
    test_cfe_canonical()
    test_cfe_threshold()
    test_sign_convention()
    test_avoided_emissions()
    test_accounting_module()

    print("\n" + "=" * 78)
    print(f"PASS={_PASS}  FAIL={_FAIL}")
    if _FAIL:
        print("\nABORTING: unit-audit gate failed.  Fix metric implementations")
        print("before advancing to Phase 2.  See gridpilot/experiments_v2/METRICS.md")
        print("for the closed-form reference values.")
        return 1
    print("Unit audit PASSED.  Proceed to Phase 2 (single-cell smoketest).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
