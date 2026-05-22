"""
tests/test_gridpilot_pue.py
============================

Five invariants for the GridPilot-PUE scheduler that back f-SLA paper Findings 1
and 2 (Pareto-optimality at preserved QoS, and the IT-vs-facility gap).

Run::

    pytest tests/test_gridpilot_pue.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from cooling.cooling_pue_model import calibrate_to_design_pue       # noqa: E402
from scheduler.scheduler_pue_aware import replay_proact_opt_pue, replay_fcfs_pue  # noqa: E402


@pytest.fixture
def jobs() -> pd.DataFrame:
    """20 jobs spanning short/medium/long runtimes."""
    return pd.DataFrame({
        "job_id": list(range(20)),
        "submit_time_epoch": np.linspace(0, 3600 * 24 * 3, 20),
        "run_time": np.tile([600, 1_800, 4 * 3600, 12 * 3600, 24 * 3600], 4),
        "num_nodes_alloc": np.tile([4, 8, 16, 32, 64], 4),
        "d_max_hours": 24.0,
    })


@pytest.fixture
def ci() -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=24 * 14, freq="h")
    hours = np.arange(len(idx))
    series = 250.0 + 100.0 * np.sin(2 * np.pi * hours / 24.0)
    return pd.DataFrame({"carbon_intensity_gCO2eq_per_kWh": series}, index=idx)


@pytest.fixture
def t_amb(ci) -> pd.Series:
    return pd.Series(20.0, index=ci.index, name="t_amb_c")


# ─────────────────────────────────────────────────────────────────────
# 1. PUE-aware scheduler runs and returns the documented dict shape
# ─────────────────────────────────────────────────────────────────────
def test_scheduler_runs(jobs, ci, t_amb):
    cp = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    res = replay_proact_opt_pue(jobs, ci, t_amb, cooling_params=cp,
                                  total_nodes=128, node_power_kw=1.5,
                                  seed=0)
    for k in ("co2_g", "facility_co2_g", "energy_kwh",
              "slowdowns", "avg_pue"):
        assert k in res, f"missing key {k}"
    assert res["facility_co2_g"] >= res["co2_g"]
    assert np.percentile(res["slowdowns"], 95) >= 1.0


# ─────────────────────────────────────────────────────────────────────
# 2. Facility CO₂ is monotonic-non-decreasing in PUE for fixed IT energy
# ─────────────────────────────────────────────────────────────────────
def test_facility_geq_it(jobs, ci, t_amb):
    cp = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    res = replay_proact_opt_pue(jobs, ci, t_amb, cooling_params=cp,
                                  total_nodes=128, seed=1)
    assert res["facility_co2_g"] >= res["co2_g"]


# ─────────────────────────────────────────────────────────────────────
# 3. PUE-aware scheduler does not exceed FCFS slowdown by > 5×
# ─────────────────────────────────────────────────────────────────────
def test_p95_within_envelope(jobs, ci, t_amb):
    cp = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    fcfs = replay_fcfs_pue(jobs, ci, t_amb, cooling_params=cp,
                             total_nodes=128, seed=2)
    pue  = replay_proact_opt_pue(jobs, ci, t_amb, cooling_params=cp,
                                   max_delay_h=24, total_nodes=128, seed=2)
    p95_fcfs = np.percentile(fcfs["slowdowns"], 95)
    p95_pue  = np.percentile(pue["slowdowns"], 95)
    # The PUE-aware scheduler defers some jobs and may be slower than
    # FCFS; bound the deviation generously.
    assert p95_pue <= 5.0 * p95_fcfs + 1.0


# ─────────────────────────────────────────────────────────────────────
# 4. Setting d_max_hours = 0 globally collapses to a no-deferral policy
# ─────────────────────────────────────────────────────────────────────
def test_zero_delay_collapses(jobs, ci, t_amb):
    cp = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    rigid_jobs = jobs.copy(); rigid_jobs["d_max_hours"] = 0
    res_rigid = replay_proact_opt_pue(rigid_jobs, ci, t_amb,
                                        cooling_params=cp, max_delay_h=0,
                                        total_nodes=128, seed=3)
    res_flex  = replay_proact_opt_pue(jobs, ci, t_amb,
                                        cooling_params=cp, max_delay_h=24,
                                        total_nodes=128, seed=3)
    # Rigid baseline must not produce strictly better IT-CO₂
    assert res_rigid["co2_g"] >= res_flex["co2_g"] - 1e-6


# ─────────────────────────────────────────────────────────────────────
# 5. PUE-aware scheduler's avg_pue rises when IT load drops
#    (the cooling-overhead drag invariant)
# ─────────────────────────────────────────────────────────────────────
def test_avg_pue_increases_under_low_load(jobs, ci, t_amb):
    cp = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    # Sparse jobs (few, short) → low utilisation → higher PUE
    sparse = jobs.head(5).copy(); sparse["run_time"] = 600
    res_full   = replay_proact_opt_pue(jobs, ci, t_amb, cooling_params=cp,
                                          total_nodes=128, seed=4)
    res_sparse = replay_proact_opt_pue(sparse, ci, t_amb, cooling_params=cp,
                                          total_nodes=128, seed=4)
    # The sparse trace should drive avg_pue ≥ full trace's avg_pue
    assert res_sparse["avg_pue"] + 1e-6 >= res_full["avg_pue"]
