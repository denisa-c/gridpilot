#!/usr/bin/env python3
"""
experiments_v2/scripts/test_fsla_scheduler.py
=============================================
Smoke test for ``schedulers.fsla_carbon_aware``.

Constructs a tiny 6-hour CI series with a clear clean valley at hour 3,
submits five deferrable jobs at hour 0, and verifies that the dispatcher
places them at the cleanest hour available — not at the earliest hour
(which would be the FCFS behaviour) and not at the end of the window
(which was the v1 dispatcher's pathology).

Run:
    PYTHONPATH=gridpilot/experiments_v2/src \\
        python3 gridpilot/experiments_v2/scripts/test_fsla_scheduler.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "gridpilot" / "experiments_v2" / "src"))

from schedulers import fcfs, fsla_carbon_aware, run_metrics  # noqa: E402


def _scenario(use_cfe_column: bool):
    """Build a 6-hour CI series with a clear valley at hour 3 plus
    five 1-hour deferrable jobs submitted at hour 0.  When
    ``use_cfe_column`` is True the parquet also carries a
    ``carbon_free_fraction`` column (1.0 at the valley, 0.05 elsewhere)
    so the scheduler exercises the argmax-CFE path; when False, it
    falls back to argmin-CI.
    """
    anchor = datetime(2025, 1, 15, tzinfo=timezone.utc)
    idx = pd.date_range(start=anchor, periods=6, freq="h", tz="UTC")
    ci_vals  = [500.0, 500.0, 500.0, 100.0, 500.0, 500.0]
    cfe_vals = [0.05,  0.05,  0.05,  0.95,  0.05,  0.05]
    cols = {"carbon_intensity_gCO2eq_per_kWh": ci_vals}
    if use_cfe_column:
        cols["carbon_free_fraction"] = cfe_vals
    ci = pd.DataFrame(cols, index=idx)
    pue = pd.Series(1.0, index=idx, name="pue")
    submit_epoch = anchor.timestamp()
    jobs = pd.DataFrame({
        "submit_time_epoch": [submit_epoch] * 5,
        "run_time":          [3600.0] * 5,
        "num_nodes_alloc":   [1] * 5,
        "d_max_hours":       [5] * 5,
        "workload_class":    ["elastic_ai"] * 5,
    })
    sim_end = (anchor + timedelta(hours=6)).timestamp()
    return anchor, ci, pue, jobs, sim_end


def _run_scenario(label: str, use_cfe_column: bool) -> bool:
    anchor, ci, pue, jobs, sim_end = _scenario(use_cfe_column)
    s_fcfs = fcfs.run(jobs, total_nodes=10, ci_df=ci, pue_curve=pue,
                       sim_end_epoch=sim_end)
    s_fsla = fsla_carbon_aware.run(jobs, total_nodes=10, ci_df=ci,
                                     pue_curve=pue, sim_end_epoch=sim_end)
    m_fcfs = run_metrics(s_fcfs, ci, pue_curve=pue)
    m_fsla = run_metrics(s_fsla, ci, pue_curve=pue)

    print(f"\n=== {label} ===")
    print(f"FCFS  : CI = {m_fcfs['ci_weighted_mean']:6.1f}   "
          f"CFE = {m_fcfs['cfe_canonical_pct']:5.1f}%")
    print(f"f-SLA : CI = {m_fsla['ci_weighted_mean']:6.1f}   "
          f"CFE = {m_fsla['cfe_canonical_pct']:5.1f}%")
    print(f"Δ CFE = "
          f"{m_fsla['cfe_canonical_pct'] - m_fcfs['cfe_canonical_pct']:+5.1f} pp")
    print("f-SLA placements (hour, CI):", [
        (int((j.start_epoch - anchor.timestamp()) // 3600),
         float(ci.iloc[int((j.start_epoch - anchor.timestamp()) // 3600), 0]))
        for j in s_fsla.completed_within_window
    ])
    return (m_fsla["cfe_canonical_pct"]
            > m_fcfs["cfe_canonical_pct"] + 5.0)


def main() -> int:
    ok_ci  = _run_scenario("argmin-CI path (no carbon_free_fraction column)",
                            use_cfe_column=False)
    ok_cfe = _run_scenario("argmax-CFE path (carbon_free_fraction column present)",
                            use_cfe_column=True)
    if ok_ci and ok_cfe:
        print("\nPASS: f-SLA found the clean valley in both modes.")
        return 0
    print("\nFAIL: f-SLA did not improve CFE in one or both modes.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
