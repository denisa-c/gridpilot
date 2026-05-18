#!/usr/bin/env python3
"""
scripts/m100/seed_policy_matrix_stub.py
=======================================
Emit a *stub* ``policy_matrix.csv`` for development and editor-pass
paper rebuilds.

The numbers are derived analytically from the headline M100 results
(GridPilot-PUE: 32.7 % IT-CO₂ reduction; declared-tier lift: 4.7 pp;
p95 baseline 13.3×, Jain 0.297) plus an empirically-motivated per-
mechanism shift drawn from the consensus literature:

  M0 → +0.0 pp (control)
  M1 → +0.3 pp (BlindTrust loses a small slice to audit cost)
  M2 → +0.0 pp (DAA collapses to posted price in full info)
  M3 → +1.1 pp (AI-baseline audit catches over-declaration, freeing
              dispatch into cleaner windows)

This stub lets the four figure scripts and the LaTeX build run
end-to-end with no replay. The real numbers are produced by
``scripts/m100/replay_policy_matrix.py`` and overwrite this stub.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

POLICIES   = ["FCFS", "EASY", "SAF", "RLBackfilling", "GridPilot-PUE"]
MECHANISMS = ["none", "M0", "M1", "M2", "M3"]

# Per-policy (CFE %, Δ_IT vs FCFS %, p95, Jain) — anchored to the
# numbers reported in Table 1 of the PECS paper.
POLICY_BASE = {
    "FCFS":          dict(cfe=18.0, dit=0.0,  p95=13.3, jain=0.297),
    "EASY":          dict(cfe=22.0, dit=6.4,  p95=14.5, jain=0.286),
    "SAF":           dict(cfe=24.0, dit=8.5,  p95=12.0, jain=0.310),
    "RLBackfilling": dict(cfe=26.5, dit=12.0, p95=11.8, jain=0.305),
    "GridPilot-PUE": dict(cfe=38.0, dit=32.7, p95=13.3, jain=0.299),
}
# Per-mechanism additive shift in Δ_IT (pp) — see module docstring.
MECH_SHIFT = {"none": 0.0, "M0": 0.0, "M1": 0.3, "M2": 0.0, "M3": 1.1}
# Per-mechanism NOM-IC violation rate (used by H2 test).
MECH_NOM_IC = {"none": 0.0, "M0": 0.12, "M1": 0.05, "M2": 0.0, "M3": 0.007}


def _gen_seed_cell(policy: str, mech: str, seed: int,
                    rng: np.random.Generator) -> dict:
    base = POLICY_BASE[policy]
    shift = MECH_SHIFT[mech]
    noise = float(rng.normal(0, 0.15))
    dit = base["dit"] + shift + noise
    cfe = base["cfe"] + 0.6 * shift + noise * 0.5
    p95 = base["p95"] + float(rng.normal(0, 0.2))
    jain = base["jain"] + float(rng.normal(0, 0.003))
    # Synthetic CO₂ from Δ_IT: baseline 1.0e9 gCO₂eq at FCFS+none
    baseline_co2 = 1.0e9
    co2_g_it = baseline_co2 * (1.0 - dit / 100.0)
    co2_g_facility = co2_g_it * (base["cfe"] / 100.0 + 1.0)  # fac > it
    energy_kwh = 3.0e6                                       # ≈ M100 month
    green_kwh = energy_kwh * cfe / 100.0
    # Synthetic SWF values: utilitarian roughly proportional to credit
    # accrual; Nash much smaller; α-fair interpolates.
    n_users = 50
    swf_base = max(0.1, 12.0 + shift)
    swf_util = swf_base * n_users + float(rng.normal(0, 0.5))
    swf_nash = (swf_base ** n_users) * np.exp(rng.normal(0, 0.1))
    swf_a05  = swf_base * np.sqrt(n_users)
    swf_a10  = np.log(max(swf_base, 1.01)) * n_users
    swf_a20  = -1.0 / max(swf_base, 0.1)
    return dict(
        policy=policy, mechanism=mech, seed=seed,
        n_jobs=1994,
        energy_kwh=energy_kwh,
        green_kwh=green_kwh,
        co2_g_it=co2_g_it,
        co2_g_facility=co2_g_facility,
        cfe_pct=cfe,
        p50_slowdown=max(1.0, p95 * 0.20),
        p95_slowdown=max(1.0, p95),
        p99_slowdown=max(1.0, p95 * 1.30),
        avg_pue=1.20,
        swf_utilitarian=swf_util,
        swf_nash=swf_nash,
        **{
            "swf_alpha_0.5": swf_a05,
            "swf_alpha_1.0": swf_a10,
            "swf_alpha_2.0": swf_a20,
        },
        jain_fairness=jain,
        n_users=n_users,
        audit_n_over_declared=int(rng.integers(0, 30)) if mech != "none" else 0,
        audit_n_under_declared=int(rng.integers(0, 30)) if mech != "none" else 0,
        audit_total_penalty=float(rng.uniform(0, 0.5)) if mech != "none" else 0.0,
        audit_nom_ic_violation_rate=MECH_NOM_IC[mech],
    )


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--seed-base", type=int, default=20260517)
    p.add_argument("--output-dir", type=Path,
                    default=Path("data/m100/policy_matrix"))
    args = p.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(args.seed_base)
    rows = []
    for pol in POLICIES:
        for mech in MECHANISMS:
            for k in range(args.seeds):
                rows.append(_gen_seed_cell(pol, mech, args.seed_base + k, rng))
    df = pd.DataFrame(rows)
    csv_path = args.output_dir / "policy_matrix.csv"
    df.to_csv(csv_path, index=False, float_format="%.4f")
    print(f"[stub] wrote {csv_path} ({len(df)} rows)")

    # Synthetic HYPOTHESIS_OUTCOMES.json mirroring what the real driver
    # would produce on these same numbers.
    outcomes = {
        "H1_declared_tier_lift": {
            "lifts_pct": {"M0": 0.0, "M1": 0.3, "M2": 0.0, "M3": 1.1},
            "passed": True,
        },
        "H2_nom_ic": {
            "m3_nom_ic_violation_rate": MECH_NOM_IC["M3"],
            "m0_nom_ic_violation_rate": MECH_NOM_IC["M0"],
            "passed": MECH_NOM_IC["M3"] < 0.01,
        },
        "H3_fairness": {
            "baseline_jain": POLICY_BASE["FCFS"]["jain"],
            "min_ratio": 0.97,
            "passed": True,
        },
        "H4_swf_dominance": {
            "swf_m2_alpha2": -0.07,
            "swf_m0_alpha2": -0.07,
            "passed": True,
        },
        "H5_latency_monotone": {
            "fcfs_p95": POLICY_BASE["FCFS"]["p95"],
            "gridpilot_m3_p95": POLICY_BASE["GridPilot-PUE"]["p95"],
            "max_clause": 4.0,
            "passed": True,
        },
        "_note": "STUB FILE — replace with output of replay_policy_matrix.py",
    }
    out_path = args.output_dir / "HYPOTHESIS_OUTCOMES.json"
    out_path.write_text(json.dumps(outcomes, indent=2))
    print(f"[stub] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
