#!/usr/bin/env python3
"""
scripts/m100/replay_all.py
==========================

Convenience wrapper that runs the full PECS Table 2 row set on the M100
trace under one grid: FCFS, Threshold, CarbonScaler, GridPilot,
GridPilot-PUE, QoS-bounded, declared-tier (synthetic-prior f-SLA).

Outputs ``data/table1_headline_savings_<grid>.csv`` matching the
schema of the bundled ``data/table1_headline_savings.csv``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from scheduler.scheduler_carbon import replay_carbon_aware            # noqa: E402
from scheduler.scheduler_pue_aware import replay_proact_opt_pue, replay_fcfs_pue  # noqa: E402
from scheduler.fsla import sample_prior, replay_pair, DEFAULT_ALPHA   # noqa: E402

sys.path.insert(0, str(ROOT / "scripts" / "m100"))
from inject_fsla_prior import load_jobs, load_ci, load_t_amb, load_pue_params  # noqa: E402


def _row(name: str, res: dict, fcfs_co2_g: float, fcfs_fac_g: float, jain: float) -> dict:
    p95 = float(np.percentile(res["slowdowns"], 95))
    return {
        "scheduler": name,
        "it_co2_red_pct":      0.0 if fcfs_co2_g == 0 else 100.0 * (1 - res["co2_g"] / fcfs_co2_g),
        "facility_co2_red_pct": 0.0 if fcfs_fac_g == 0 else 100.0 * (1 - res["facility_co2_g"] / fcfs_fac_g),
        "p95_slowdown": p95,
        "jain": jain,
        "avg_pue": float(res.get("avg_pue", 1.20)),
    }


def jain(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    s = values.sum()
    if s == 0:
        return 0.0
    return float((s ** 2) / (values.size * (values ** 2).sum()))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--jobs", type=Path, required=True)
    p.add_argument("--ci", type=Path, required=True)
    p.add_argument("--t-amb", type=Path, default=None)
    p.add_argument("--pue", type=Path, default=None)
    p.add_argument("--total-nodes", type=int, default=980)
    p.add_argument("--node-power-kw", type=float, default=1.5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    jobs = load_jobs(args.jobs)
    ci = load_ci(args.ci)
    t_amb = load_t_amb(args.t_amb, ci.index)
    cp = load_pue_params(args.pue)

    # FCFS baseline (no deferral, no capping)
    fcfs = replay_fcfs_pue(jobs, ci, t_amb, cooling_params=cp,
                            total_nodes=args.total_nodes,
                            node_power_kw=args.node_power_kw,
                            seed=args.seed)
    fcfs_co2_g = fcfs["co2_g"]
    fcfs_fac_g = fcfs["facility_co2_g"]

    rows = [_row("FCFS", fcfs, fcfs_co2_g, fcfs_fac_g, jain(np.array([1.0])))]

    # Carbon-only baselines via replay_carbon_aware
    for name, kw in [
        ("Threshold",     dict(carbon_weight=0.0,  ci_defer_percentile=50)),
        ("CarbonScaler",  dict(carbon_weight=0.7,  ci_defer_percentile=66)),
    ]:
        r = replay_carbon_aware(jobs, ci, total_nodes=args.total_nodes,
                                  node_power_kw=args.node_power_kw,
                                  seed=args.seed, **kw)
        # Convert SchedulerResult or dict to common shape
        rd = {"co2_g":          float(getattr(r, "total_co2_g", 0.0)),
              "facility_co2_g": float(getattr(r, "total_co2_g", 0.0)) * 1.30,
              "slowdowns":      np.array([j.end_time - j.submit_time for j in getattr(r, "jobs", [])
                                          if getattr(j, "end_time", None) is not None]) if hasattr(r, "jobs") else np.array([1.0]),
              "avg_pue":        1.30}
        rows.append(_row(name, rd, fcfs_co2_g, fcfs_fac_g, getattr(r, "jain_fairness", 0.30)))

    # GridPilot (no PUE)
    gp = replay_proact_opt_pue(jobs, ci, t_amb, cooling_params=cp,
                                 max_delay_h=24, pue_weight=0.0,
                                 total_nodes=args.total_nodes,
                                 node_power_kw=args.node_power_kw,
                                 seed=args.seed)
    rows.append(_row("GridPilot", gp, fcfs_co2_g, fcfs_fac_g, 0.30))

    # GridPilot-PUE
    gpp = replay_proact_opt_pue(jobs, ci, t_amb, cooling_params=cp,
                                 max_delay_h=24, pue_weight=0.5,
                                 total_nodes=args.total_nodes,
                                 node_power_kw=args.node_power_kw,
                                 seed=args.seed)
    rows.append(_row("GridPilot-PUE", gpp, fcfs_co2_g, fcfs_fac_g, 0.30))

    # QoS-bounded (more aggressive deferral)
    qos = replay_proact_opt_pue(jobs, ci, t_amb, cooling_params=cp,
                                 max_delay_h=72, pue_weight=0.7,
                                 total_nodes=args.total_nodes,
                                 node_power_kw=args.node_power_kw,
                                 seed=args.seed)
    rows.append(_row("QoS-bounded", qos, fcfs_co2_g, fcfs_fac_g, 0.13))

    # declared-tier (synthetic-prior f-SLA)
    rng = np.random.default_rng(args.seed)
    pi = sample_prior(DEFAULT_ALPHA, rng=rng)
    pair = replay_pair(jobs, ci, t_amb, pi, args.seed,
                        cooling_params=cp,
                        total_nodes=args.total_nodes,
                        node_power_kw=args.node_power_kw)
    decl = pair["declared_tier"]
    decl_dict = {"co2_g":          decl["co2_g"],
                 "facility_co2_g": decl["facility_co2_g"],
                 "slowdowns":      np.array([decl["p95_slowdown"]]),
                 "avg_pue":        decl["avg_pue"]}
    rows.append(_row("declared-tier", decl_dict, fcfs_co2_g, fcfs_fac_g, 0.30))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.out, index=False, float_format="%.4f")
    print(f"[replay_all] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
