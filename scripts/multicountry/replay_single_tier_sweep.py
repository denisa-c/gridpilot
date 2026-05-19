#!/usr/bin/env python3
"""
scripts/multicountry/replay_single_tier_sweep.py
==================================================
Per-tier contribution sweep for the PECS paper.

The main multi-country sweep (replay_country_sweep.py) draws a
DISTRIBUTION of tiers per job using the M0..M3 mechanism plug-ins.
That conflates the lift attributable to each tier.  This driver
isolates per-tier contribution: for each tier k in {0,1,2,3,4,5} we
force every job to tier k and replay the M100 trace against the six
European grids.

Output (under ``--output-dir``):

  tier_sweep.csv          one row per (country, mw, tier, seed) with
                          cfe_pct_mean, cfe_lift_pp_mean (vs T0),
                          ci_weighted_mean, p95_slowdown, jain_fairness
  TIER_SUMMARY.csv        mean per (country, mw, tier) with CIs
  RUN_MANIFEST.json       provenance

Sweep dimensions: 6 grids x 3 MW x 6 tiers x 8 seeds = 864 cells.
At ~9 s/cell with 4 workers, wall time is ~32 minutes.

Usage from the workspace root (one level above gridpilot/):

    PYTHONPATH=gridpilot/src python3 \\
        gridpilot/scripts/multicountry/replay_single_tier_sweep.py \\
        --jobs gridpilot/data/traces/m100_real_jobs.parquet \\
        --output-dir gridpilot/data/m100/tier_sweep/ \\
        --force

See docs/TIER_AND_HYPER_SWEEPS.md for the protocol and EXPERIMENTS_REMOTE.md
for the canonical remote-run sequence.
"""
from __future__ import annotations

import argparse
import json
import platform
import socket
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "m100"))

from scheduler.fsla import (  # noqa: E402
    TIER_NAMES, TIER_WINDOW_H, TIER_SLOWMAX, TIER_CREDIT_H,
    T_RIGID, T_ELASTIC, T_SPATIAL,
    T3_FIXED_CHECKPOINT_BONUS, T4_REPLICA_MIN, T4_REPLICA_MAX,
)
from scheduler.scheduler_pue_aware import replay_proact_opt_pue  # noqa: E402
from inject_fsla_prior import load_jobs, load_ci, load_pue_params  # noqa: E402
from replay_country_sweep import (  # noqa: E402
    NODE_POWER_KW, _nodes_for_mw, _scale_trace_to_cluster,
    _cfe_pct, _cfe_abs_pct, _ci_weighted_mean_g,
    align_jobs_to_ci, _attach_user_column,
)

GRID_CODES = ("SE", "CH", "FR", "IT", "DE", "PL")


def run_one_cell(country_yaml, mw, tier, seed, jobs_df,
                  cooling_params, scheduler_kwargs_base):
    """Forced-tier replay: every job assigned tier ``tier``.

    Returns a dict suitable for direct row insertion into the
    aggregate CSV.
    """
    rng = np.random.default_rng(seed)
    ci_df = load_ci(country_yaml)
    jobs_local = align_jobs_to_ci(jobs_df, ci_df)
    jobs_local = _attach_user_column(jobs_local, rng)
    nodes = _nodes_for_mw(mw)
    jobs_local = _scale_trace_to_cluster(jobs_local, nodes)
    t_amb = pd.Series(20.0, index=ci_df.index, name="t_amb_c")
    sched_kwargs = dict(scheduler_kwargs_base, total_nodes=nodes)

    # Force every job to the chosen tier.
    jobs_with_tiers = jobs_local.copy()
    jobs_with_tiers["tier"] = int(tier)
    jobs_with_tiers["d_max_hours"] = int(TIER_WINDOW_H[tier])
    jobs_with_tiers["slowdown_max"] = float(TIER_SLOWMAX[tier])
    jobs_with_tiers["service_credit_h"] = float(TIER_CREDIT_H[tier])
    jobs_with_tiers["checkpoint_bonus"] = (
        T3_FIXED_CHECKPOINT_BONUS if int(tier) == 3 else 0.0
    )
    # T4 elastic eligibility flag --- the dispatcher reads this column
    # for replica scaling.  Same convention as replay_country_sweep.py.
    jobs_with_tiers["is_elastic"] = (int(tier) == T_ELASTIC)
    jobs_with_tiers["is_spatial_eligible"] = (int(tier) == T_SPATIAL)
    jobs_with_tiers["spatial_clause"] = ""
    jobs_with_tiers["dag_node_id"] = -1
    jobs_with_tiers["dag_parent_id"] = -1

    result = replay_proact_opt_pue(
        jobs_with_tiers, ci_df, t_amb,
        cooling_params=cooling_params,
        max_delay_h=int(max(1, int(TIER_WINDOW_H[tier]))),
        pue_weight=1.0,
        short_job_threshold_s=60,
        enable_backfilling=True,
        seed=seed,
        **sched_kwargs,
    )
    slowdowns = result.get("slowdowns", np.array([1.0]))
    return {
        "country": country_yaml.stem,
        "mw": mw,
        "tier": int(tier),
        "tier_name": TIER_NAMES[int(tier)],
        "seed": int(seed),
        "n_jobs": int(result.get("n", 0)),
        "energy_kwh": float(result.get("energy_kwh", 0.0)),
        "co2_g_it": float(result.get("co2_g", 0.0)),
        "co2_g_facility": float(result.get("facility_co2_g", 0.0)),
        "co2_tonnes_y": float(result.get("co2_g", 0.0))
                          * 365.0 / 30.0 / 1.0e6,
        "cfe_pct": _cfe_pct(result),
        "cfe_abs_pct": _cfe_abs_pct(result, ci_df),
        "ci_weighted_mean": _ci_weighted_mean_g(result, ci_df),
        "p50_slowdown": float(np.percentile(slowdowns, 50)),
        "p95_slowdown": float(np.percentile(slowdowns, 95)),
        "p99_slowdown": float(np.percentile(slowdowns, 99)),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="replay_single_tier_sweep",
                                  allow_abbrev=False)
    p.add_argument("--jobs", type=Path, required=True)
    p.add_argument("--grids", type=str, default=",".join(GRID_CODES),
                    help="comma-separated grid codes")
    p.add_argument("--grids-dir", type=Path,
                    default=ROOT / "configs" / "grids")
    p.add_argument("--mw", type=str, default="1,10,50")
    p.add_argument("--tiers", type=str, default="0,1,2,3,4,5",
                    help="comma-separated tier indices to sweep")
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--seed-base", type=int, default=20260517)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--pue-yaml", type=Path,
                    default=ROOT / "raps" / "config" / "marconi100.yaml")
    p.add_argument("--output-dir", type=Path,
                    default=ROOT / "data" / "m100" / "tier_sweep")
    p.add_argument("--force", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    t0 = time.time()
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    sweep_csv = out_dir / "tier_sweep.csv"
    if sweep_csv.exists() and not args.force:
        print(f"ERROR: {sweep_csv} already exists. Use --force.",
              file=sys.stderr)
        return 2

    grids = [args.grids_dir / f"{c.strip().upper()}.yaml"
             for c in args.grids.split(",") if c.strip()]
    mws = [float(s) for s in args.mw.split(",") if s.strip()]
    tiers = [int(t) for t in args.tiers.split(",") if t.strip()]
    seeds = [args.seed_base + k for k in range(args.seeds)]

    # PUE cooling params
    if args.pue_yaml.exists():
        cooling_params = load_pue_params(args.pue_yaml)
    else:
        from cooling.cooling_pue_model import calibrate_to_design_pue
        cooling_params = calibrate_to_design_pue(target_pue=1.20,
                                                   it_design_kw=1400.0)

    scheduler_kwargs_base = dict(node_power_kw=NODE_POWER_KW,
                                   time_step=3600)
    jobs_df = load_jobs(args.jobs)

    cells = [(g, mw, tier, s) for g in grids for mw in mws
              for tier in tiers for s in seeds]
    if not args.quiet:
        print(f"[tier-sweep] {len(grids)} grids x {len(mws)} MW x "
              f"{len(tiers)} tiers x {len(seeds)} seeds = "
              f"{len(cells)} cells; workers={args.workers}",
              flush=True)

    rows = []
    if args.workers <= 1:
        for k, (g, mw, tier, s) in enumerate(cells):
            if not args.quiet and k % max(1, len(cells) // 20) == 0:
                print(f"[tier-sweep] {k+1}/{len(cells)}  {g.stem:<3} "
                      f"{mw:>4}MW T{tier} seed={s}", flush=True)
            rows.append(run_one_cell(g, mw, tier, s, jobs_df,
                                       cooling_params,
                                       scheduler_kwargs_base))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(run_one_cell, g, mw, tier, s, jobs_df,
                                cooling_params, scheduler_kwargs_base):
                    (g, mw, tier, s) for g, mw, tier, s in cells}
            for k, fut in enumerate(as_completed(futs)):
                g, mw, tier, s = futs[fut]
                rows.append(fut.result())
                if not args.quiet and k % max(1, len(cells) // 20) == 0:
                    print(f"[tier-sweep] {k+1}/{len(cells)}  "
                          f"{g.stem:<3} {mw:>4}MW T{tier} seed={s}",
                          flush=True)

    # ── Aggregate
    df = pd.DataFrame(rows)
    # Lift vs the same (country, mw) baseline at tier=0 (rigid)
    base = (df.query("tier == 0")
              .groupby(["country", "mw"])["cfe_pct"]
              .mean().reset_index().rename(columns={"cfe_pct": "base_cfe"}))
    df = df.merge(base, on=["country", "mw"], how="left")
    df["cfe_lift_pp_vs_t0"] = df["cfe_pct"] - df["base_cfe"]
    df = df.drop(columns=["base_cfe"])
    df.to_csv(sweep_csv, index=False, float_format="%.4f")

    # Summary: mean per (country, mw, tier)
    summary = (df.groupby(["country", "mw", "tier", "tier_name"])
                  .agg(cfe_pct_mean=("cfe_pct", "mean"),
                        cfe_lift_pp_mean=("cfe_lift_pp_vs_t0", "mean"),
                        ci_weighted_mean=("ci_weighted_mean", "mean"),
                        p95_slowdown_mean=("p95_slowdown", "mean"),
                        co2_tonnes_y_mean=("co2_tonnes_y", "mean"))
                  .reset_index())
    summary.to_csv(out_dir / "TIER_SUMMARY.csv",
                     index=False, float_format="%.4f")

    # RUN_MANIFEST: provenance marker (signals "real run" to extractor)
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    (out_dir / "RUN_MANIFEST.json").write_text(json.dumps({
        "git_sha": git_sha,
        "command_line": " ".join(sys.argv),
        "args": {k: str(v) for k, v in vars(args).items()},
        "python_version": sys.version,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "wall_time_s": round(time.time() - t0, 1),
        "n_cells": len(rows),
    }, indent=2))

    if not args.quiet:
        print(f"[tier-sweep] wrote {sweep_csv} ({len(rows)} cells, "
              f"{time.time()-t0:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
