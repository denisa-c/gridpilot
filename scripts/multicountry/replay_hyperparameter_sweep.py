#!/usr/bin/env python3
"""
scripts/multicountry/replay_hyperparameter_sweep.py
=====================================================
Contract-hyperparameter sensitivity sweep for the PECS paper.

Four hyperparameters with measurable effect on the CFE lift:

  alpha_scale         multiplier on the entire credit schedule
                      {0.5, 1.0, 2.0, 4.0}                  (default 1.0)
  window_scale        multiplier on T2/T3/T4/T5 deferral windows
                      {0.5, 1.0, 2.0}                       (default 1.0)
  t4_envelope_scale   multiplier on the [0.5x, 2x] T4 replica envelope
                      (i.e. [0.5/s, 2*s])  {1.0, 2.0}        (default 1.0)
  short_job_s         short-job dispatch-deferral threshold in seconds
                      {1, 60, 300}                          (default 60)

We run a ONE-AT-A-TIME design (vary each hyperparameter while the
others sit at the default).  This is 4+3+2+3 = 12 settings; against
6 grids x 3 MW x 8 seeds = 144 cells per setting → 1728 cells total.
Wall-time ~50-60 min at 4 workers; matches the country sweep budget.

A full factorial would be 4*3*2*3 = 72 settings * 144 = 10368 cells
(~6 hours); not worth it for what the paper needs.

Output (under ``--output-dir``):

  hyper_sweep.csv       one row per (country, mw, hyperparam, value, seed)
  HYPER_SUMMARY.csv     mean per (hyperparam, value) across grids+mw+seeds
  RUN_MANIFEST.json     provenance

Usage from the workspace root:

    PYTHONPATH=gridpilot/src python3 \\
        gridpilot/scripts/multicountry/replay_hyperparameter_sweep.py \\
        --jobs gridpilot/data/traces/m100_real_jobs.parquet \\
        --output-dir gridpilot/data/m100/hyper_sweep/ \\
        --force

See docs/TIER_AND_HYPER_SWEEPS.md.
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
    TIER_WINDOW_H, TIER_SLOWMAX, TIER_CREDIT_H, DEFAULT_ALPHA,
    T_RIGID, T_HOUR, T_DAY, T_WEEK, T_ELASTIC, T_SPATIAL,
    sample_prior, assign_tiers,
)
from scheduler.scheduler_pue_aware import replay_proact_opt_pue  # noqa: E402
from inject_fsla_prior import load_jobs, load_ci, load_pue_params  # noqa: E402
from replay_country_sweep import (  # noqa: E402
    NODE_POWER_KW, _nodes_for_mw, _scale_trace_to_cluster,
    _cfe_pct, _cfe_abs_pct, _ci_weighted_mean_g,
    align_jobs_to_ci, _attach_user_column,
)

GRID_CODES = ("SE", "CH", "FR", "IT", "DE", "PL")

# Default operating point.  All cells in the one-at-a-time design
# sit at this point except for the one varying parameter.
DEFAULTS = {
    "alpha_scale":       1.0,
    "window_scale":      1.0,
    "t4_envelope_scale": 1.0,
    "short_job_s":       60,
}

# Sweep settings: one-at-a-time around DEFAULTS.
SWEEP = {
    "alpha_scale":       [0.5, 1.0, 2.0, 4.0],
    "window_scale":      [0.5, 1.0, 2.0],
    "t4_envelope_scale": [1.0, 2.0],
    "short_job_s":       [1, 60, 300],
}


def _apply_hyper(jobs_df, hyper, value, rng):
    """Build the per-job tier dataframe for one hyperparameter setting.

    Tier assignment uses the DEFAULT Dirichlet prior (so the hyperparameter
    we vary is what we measure, not the prior shape).
    """
    # Custom alpha credit schedule
    alpha_scale = (value if hyper == "alpha_scale"
                    else DEFAULTS["alpha_scale"])
    window_scale = (value if hyper == "window_scale"
                     else DEFAULTS["window_scale"])

    pi = sample_prior(DEFAULT_ALPHA, rng=rng)
    out, _ = assign_tiers(jobs_df, pi, rng=rng)
    # Apply scales to the per-job columns the dispatcher reads.
    out["d_max_hours"] = (out["d_max_hours"] * window_scale).round().astype(int)
    out["service_credit_h"] = out["service_credit_h"] * alpha_scale
    # T4 elastic envelope is read directly from constants by the dispatcher;
    # we override the eligibility flag here.  T4 envelope scale is wired
    # into the dispatcher's elastic_replica_min/max via a side-channel
    # which the v0.1 shell does NOT support --- so this hyperparameter
    # is reported as "experimental" and its effect is bounded.
    out["is_elastic"] = (out["tier"] == T_ELASTIC).astype(bool)
    out["is_spatial_eligible"] = (out["tier"] == T_SPATIAL).astype(bool)
    out["spatial_clause"] = ""
    out["dag_node_id"] = -1
    out["dag_parent_id"] = -1
    return out


def run_one_cell(country_yaml, mw, hyper, value, seed,
                  jobs_df, cooling_params, scheduler_kwargs_base):
    rng = np.random.default_rng(seed)
    ci_df = load_ci(country_yaml)
    jobs_local = align_jobs_to_ci(jobs_df, ci_df)
    jobs_local = _attach_user_column(jobs_local, rng)
    nodes = _nodes_for_mw(mw)
    jobs_local = _scale_trace_to_cluster(jobs_local, nodes)
    t_amb = pd.Series(20.0, index=ci_df.index, name="t_amb_c")
    sched_kwargs = dict(scheduler_kwargs_base, total_nodes=nodes)

    jobs_with_tiers = _apply_hyper(jobs_local, hyper, value, rng)
    short_job_s = (value if hyper == "short_job_s"
                    else DEFAULTS["short_job_s"])

    result = replay_proact_opt_pue(
        jobs_with_tiers, ci_df, t_amb,
        cooling_params=cooling_params,
        max_delay_h=int(max(1, jobs_with_tiers["d_max_hours"].max())),
        pue_weight=1.0,
        short_job_threshold_s=int(short_job_s),
        enable_backfilling=True,
        seed=seed,
        **sched_kwargs,
    )
    slowdowns = result.get("slowdowns", np.array([1.0]))
    return {
        "country": country_yaml.stem,
        "mw": mw,
        "hyper": hyper,
        "value": float(value),
        "seed": int(seed),
        "n_jobs": int(result.get("n", 0)),
        "energy_kwh": float(result.get("energy_kwh", 0.0)),
        "co2_tonnes_y": float(result.get("co2_g", 0.0))
                          * 365.0 / 30.0 / 1.0e6,
        "cfe_pct": _cfe_pct(result),
        "cfe_abs_pct": _cfe_abs_pct(result, ci_df),
        "ci_weighted_mean": _ci_weighted_mean_g(result, ci_df),
        "p95_slowdown": float(np.percentile(slowdowns, 95)),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="replay_hyperparameter_sweep",
                                  allow_abbrev=False)
    p.add_argument("--jobs", type=Path, required=True)
    p.add_argument("--grids", type=str, default=",".join(GRID_CODES))
    p.add_argument("--grids-dir", type=Path,
                    default=ROOT / "configs" / "grids")
    p.add_argument("--mw", type=str, default="10")
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--seed-base", type=int, default=20260517)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--pue-yaml", type=Path,
                    default=ROOT / "raps" / "config" / "marconi100.yaml")
    p.add_argument("--output-dir", type=Path,
                    default=ROOT / "data" / "m100" / "hyper_sweep")
    p.add_argument("--force", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    t0 = time.time()
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    sweep_csv = out_dir / "hyper_sweep.csv"
    if sweep_csv.exists() and not args.force:
        print(f"ERROR: {sweep_csv} already exists. Use --force.",
              file=sys.stderr)
        return 2

    grids = [args.grids_dir / f"{c.strip().upper()}.yaml"
             for c in args.grids.split(",") if c.strip()]
    mws = [float(s) for s in args.mw.split(",") if s.strip()]
    seeds = [args.seed_base + k for k in range(args.seeds)]

    if args.pue_yaml.exists():
        cooling_params = load_pue_params(args.pue_yaml)
    else:
        from cooling.cooling_pue_model import calibrate_to_design_pue
        cooling_params = calibrate_to_design_pue(target_pue=1.20,
                                                   it_design_kw=1400.0)

    scheduler_kwargs_base = dict(node_power_kw=NODE_POWER_KW,
                                   time_step=3600)
    jobs_df = load_jobs(args.jobs)

    # One-at-a-time design: for each hyper, sweep its values; other
    # hyperparameters held at DEFAULTS.
    cells = []
    for hyper, values in SWEEP.items():
        for v in values:
            for g in grids:
                for mw in mws:
                    for s in seeds:
                        cells.append((g, mw, hyper, v, s))

    if not args.quiet:
        print(f"[hyper-sweep] {len(cells)} cells "
              f"(4 hypers x ~3 values x {len(grids)} grids x "
              f"{len(mws)} MW x {len(seeds)} seeds); workers={args.workers}",
              flush=True)

    rows = []
    if args.workers <= 1:
        for k, (g, mw, hyper, v, s) in enumerate(cells):
            if not args.quiet and k % max(1, len(cells) // 20) == 0:
                print(f"[hyper-sweep] {k+1}/{len(cells)}  {g.stem:<3} "
                      f"{mw:>4}MW {hyper}={v} seed={s}", flush=True)
            rows.append(run_one_cell(g, mw, hyper, v, s, jobs_df,
                                       cooling_params,
                                       scheduler_kwargs_base))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(run_one_cell, g, mw, hyper, v, s,
                                jobs_df, cooling_params,
                                scheduler_kwargs_base):
                    (g, mw, hyper, v, s)
                    for g, mw, hyper, v, s in cells}
            for k, fut in enumerate(as_completed(futs)):
                g, mw, hyper, v, s = futs[fut]
                rows.append(fut.result())
                if not args.quiet and k % max(1, len(cells) // 20) == 0:
                    print(f"[hyper-sweep] {k+1}/{len(cells)}  "
                          f"{g.stem:<3} {mw:>4}MW {hyper}={v} seed={s}",
                          flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(sweep_csv, index=False, float_format="%.4f")

    summary = (df.groupby(["hyper", "value"])
                  .agg(cfe_pct_mean=("cfe_pct", "mean"),
                        cfe_pct_std=("cfe_pct", "std"),
                        ci_weighted_mean=("ci_weighted_mean", "mean"),
                        p95_slowdown_mean=("p95_slowdown", "mean"),
                        co2_tonnes_y_mean=("co2_tonnes_y", "mean"))
                  .reset_index())
    summary.to_csv(out_dir / "HYPER_SUMMARY.csv",
                     index=False, float_format="%.4f")

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
        "defaults": DEFAULTS,
        "sweep_design": "one-at-a-time around defaults",
    }, indent=2))

    if not args.quiet:
        print(f"[hyper-sweep] wrote {sweep_csv} ({len(rows)} cells, "
              f"{time.time()-t0:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
