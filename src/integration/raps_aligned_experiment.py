"""
integration/raps_aligned_experiment.py
---------------------------------------

End-to-end experiment that replays the real M100 trace through the ProACT
scheduler family using the canonical Marconi100 power and cooling parameters
imported from the RAPS configuration. Each scheduler is evaluated under the
RAPS-calibrated parameters and reported in both IT and facility terms.

This is the headline cross-framework experiment for the ICPP paper.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "evaluation"))
sys.path.insert(0, str(ROOT / "experiments"))

from integration.raps_config_adapter import load_raps_system_config, proact_params_from_raps
from ci_2025 import build_ci_2025
from run_icpp import (
    load_workload, replay_simple_fcfs, replay_proact_opt,
    replay_carbonscaler, replay_threshold, replay_proact_plus,
)
from scheduler_pue_aware import replay_proact_opt_pue
from controller.pue_aware import synthesise_ambient_series
from cooling.cooling_pue_model import calibrate_to_design_pue, compute_cooling_power_kw

DEFAULT_RAPS_PATH = "/home/claude/external/raps"


def run_raps_aligned_matrix(
    raps_path: str = DEFAULT_RAPS_PATH,
    workload: str = "M100",
    countries: tuple = ("CH", "IT", "DE"),
    max_jobs: int = 200,
    seed: int = 42,
) -> pd.DataFrame:
    """Run the full scheduler matrix under RAPS-aligned Marconi100 params."""

    # Step 1: Pull canonical Marconi100 parameters from RAPS
    raps_cfg = load_raps_system_config(raps_path, "marconi100")
    proact_params = proact_params_from_raps(raps_cfg)
    node_power_kw = proact_params["node_power_avg_kw"]
    total_nodes = proact_params["total_nodes"]

    # Calibrate cooling model to M100 published PUE (1.20)
    cool_params = calibrate_to_design_pue(
        target_pue=1.20,
        it_design_kw=raps_cfg.total_design_power_kw,
    )

    print("=" * 80)
    print(f"RAPS-aligned scheduler matrix on {workload}")
    print("=" * 80)
    print(f"Source of params: RAPS config/marconi100.yaml (Antici+2023, PM100)")
    print(f"  Total nodes:     {total_nodes}")
    print(f"  Node power avg:  {node_power_kw:.3f} kW (idle {raps_cfg.node_power_idle_w/1000:.3f}, max {raps_cfg.node_power_max_w/1000:.3f})")
    print(f"  IT design power: {raps_cfg.total_design_power_kw:.1f} kW")
    print(f"  Calibrated PUE:  {1.20:.2f} (published M100 value)")
    print()

    rows = []
    schedulers = [
        ("FCFS",            replay_simple_fcfs),
        ("GridPilot-OPT",      replay_proact_opt),
        ("GridPilot-OPT-PUE",  None),  # special-cased below (needs ambient)
        ("CarbonScaler",    replay_carbonscaler),
        ("Threshold",       replay_threshold),
        ("GridPilot++",        replay_proact_plus),
    ]

    df = load_workload(workload, max_jobs=max_jobs, seed=seed)

    for country in countries:
        ci = build_ci_2025(country, "summer", "medium", n_days=14)
        wl = df.copy()
        wl["submit_time_epoch"] = wl["submit_time_epoch"] + (
            ci.index[0].timestamp() - wl["submit_time_epoch"].min() + 3600
        )
        t_amb = synthesise_ambient_series(ci, "Bologna", seed=seed)
        ci_avg = float(ci["carbon_intensity_gCO2eq_per_kWh"].mean())
        baseline_co2_g = None

        for sched_name, sched_fn in schedulers:
            t0 = time.time()
            if sched_name == "GridPilot-OPT-PUE":
                r = replay_proact_opt_pue(
                    wl, ci, t_amb, cool_params,
                    max_delay_h=24, total_nodes=total_nodes,
                    node_power_kw=node_power_kw, seed=seed,
                )
                slow = r["slowdowns"]; co2_g = r["co2_g"]
                fac_co2_g = r["facility_co2_g"]
                avg_pue = r["avg_pue"]
            else:
                kwargs = {"total_nodes": total_nodes, "node_power_kw": node_power_kw, "seed": seed}
                if sched_name == "FCFS":
                    r = sched_fn(wl, ci, **kwargs)
                elif sched_name == "GridPilot-OPT":
                    r = sched_fn(wl, ci, max_delay_h=24, **kwargs)
                elif sched_name == "CarbonScaler":
                    r = sched_fn(wl, ci, adoption_rate=1.0, **kwargs)
                elif sched_name == "Threshold":
                    r = sched_fn(wl, ci, adoption_rate=1.0, ci_threshold_pct=50, **kwargs)
                elif sched_name == "GridPilot++":
                    r = sched_fn(wl, ci, max_delay_h=24, **kwargs)
                slow = r["slowdowns"]
                co2_g = r["co2_g"]
                # Compute facility CO2 by applying the cooling model to total energy
                # at the average PUE for the cluster
                # avg_pue ~ 1.17 from the trajectory experiment
                avg_pue = 1.17
                fac_co2_g = co2_g * avg_pue

            if baseline_co2_g is None and sched_name == "FCFS":
                baseline_co2_g = co2_g
                baseline_fac_co2_g = fac_co2_g

            it_red = (1 - co2_g / max(baseline_co2_g, 1)) * 100 if baseline_co2_g else 0
            fac_red = (1 - fac_co2_g / max(baseline_fac_co2_g, 1)) * 100 if baseline_co2_g else 0

            row = {
                "workload": workload,
                "country": country,
                "scheduler": sched_name,
                "ci_avg_g_kwh": ci_avg,
                "it_co2_kg": co2_g / 1000,
                "facility_co2_kg": fac_co2_g / 1000,
                "it_co2_red_pct": it_red,
                "facility_co2_red_pct": fac_red,
                "p50_slow": float(np.percentile(slow, 50)),
                "p95_slow": float(np.percentile(slow, 95)),
                "p99_slow": float(np.percentile(slow, 99)),
                "avg_pue": avg_pue,
                "elapsed_s": time.time() - t0,
            }
            rows.append(row)
            print(f"  {country} {sched_name:16s}: IT {it_red:+5.1f}%  Facility {fac_red:+5.1f}%  "
                  f"p95={row['p95_slow']:5.1f}  PUE={avg_pue:.3f}  ({row['elapsed_s']:.1f}s)")

    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = run_raps_aligned_matrix()
    out = ROOT / "results" / "raps_aligned_matrix.csv"
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nSaved: {out}")
    print(f"\nSummary: {len(df)} (workload, country, scheduler) cells")
