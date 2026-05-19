#!/usr/bin/env python3
"""
experiments_v2/scripts/04_run_hyper_sweep.py
=============================================
Phase 4c — contract-hyperparameter sensitivity sweep.

One-at-a-time sweep over four contract knobs around DEFAULTS:
    alpha_scale       : 0.5, 1.0, 2.0, 4.0
    window_scale      : 0.5, 1.0, 2.0
    t4_envelope_scale : 1.0, 2.0
    short_job_s       : 1, 60, 300

Total cells: |countries| × Σ|values per hyper| × |seeds|.
With 6 countries × 12 hyper-values × 8 seeds = 576 (default).

Wraps v1's replay_hyperparameter_sweep.run_one_cell with the
correct 8-positional-arg signature (the previous v2 wrapper had
a wrong arg order — fixed in this version).

Outputs:
  data/hyper_sweep/cells/<cell_id>.json
  data/hyper_sweep/hyper_sweep.csv
  data/hyper_sweep/HYPER_SUMMARY.csv
  data/hyper_sweep/RUN_MANIFEST.json
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from tqdm import tqdm
    HAVE_TQDM = True
except ImportError:
    HAVE_TQDM = False

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "gridpilot" / "src"))
sys.path.insert(0, str(ROOT / "gridpilot" / "scripts" / "multicountry"))
sys.path.insert(0, str(ROOT / "gridpilot" / "scripts" / "m100"))
sys.path.insert(0, str(ROOT / "gridpilot" / "experiments_v2" / "src"))

# pylint: disable=wrong-import-position,import-error
from replay_hyperparameter_sweep import (  # type: ignore[import-not-found]
    run_one_cell as v1_hyper_cell,
    SWEEP, DEFAULTS, NODE_POWER_KW,
)
from inject_fsla_prior import load_pue_params  # type: ignore[import-not-found]
from cooling.cooling_pue_model import (        # type: ignore[import-not-found]
    calibrate_to_design_pue,
)

GRIDPILOT = ROOT / "gridpilot"
GRIDS_DIR = GRIDPILOT / "configs" / "grids"
PUE_RAPS  = GRIDPILOT / "raps" / "config" / "marconi100.yaml"
JOBS_EXT  = GRIDPILOT / "data" / "traces" / "m100_real_jobs_extended.parquet"
JOBS_JAN  = GRIDPILOT / "data" / "traces" / "m100_real_jobs.parquet"

# Canonical-CFE reference (Kamatar 2025; Google 24/7).  Used to
# compute cfe_canonical_pct from v1's ci_weighted_mean field (v1
# doesn't emit cfe_canonical_pct directly).
CFE_REF_CI_G = 800.0

DEFAULT_COUNTRIES = ["SE", "CH", "FR", "IT", "DE", "PL"]
DEFAULT_MW = 10
DEFAULT_SEEDS = 8

# Build the (hyper, value) sweep list once at module load.  This is
# v1's SWEEP dict flattened: each entry is a (hyper_name, value) pair.
HYPER_VALUE_PAIRS: list[tuple[str, float]] = [
    (h, v) for h, values in SWEEP.items() for v in values
]


def _resolve_cooling_params():
    if PUE_RAPS.exists():
        return load_pue_params(PUE_RAPS)
    return calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)


def _scheduler_kwargs_base() -> dict:
    """v1's run_one_cell expects node_power_kw + time_step in the
    base kwargs.  Match v1's main()."""
    return dict(node_power_kw=NODE_POWER_KW, time_step=3600)


def _cell_id(c, hyper, value, s):
    return f"{c}_{hyper}_{value}_seed{s}"


def _persist(cp, row):
    cp.parent.mkdir(parents=True, exist_ok=True)
    tmp = cp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row, default=str))
    tmp.replace(cp)


def _load_cached(cp):
    if not cp.exists():
        return None
    try:
        r = json.loads(cp.read_text())
        if {"country", "hyper", "value", "seed", "cfe_canonical_pct"}.issubset(r):
            return r
    except Exception:
        pass
    return None


def _run(c, hyper, value, seed, mw, jobs_df, cooling_params):
    """Call v1 with the correct 8-positional-arg signature, then
    augment the row with cfe_canonical_pct (which v1 doesn't emit)."""
    country_yaml = GRIDS_DIR / f"{c}.yaml"
    r = v1_hyper_cell(
        country_yaml, float(mw), str(hyper), float(value), int(seed),
        jobs_df, cooling_params, _scheduler_kwargs_base(),
    )
    # Derive canonical CFE from the energy-weighted mean CI v1 returns.
    ci_eff = float(r.get("ci_weighted_mean", 0.0))
    cfe_canonical = (
        max(0.0, min(100.0, 100.0 * (1.0 - ci_eff / CFE_REF_CI_G)))
        if ci_eff > 0 else 0.0
    )
    return {
        "country":  c, "mw": int(mw), "seed": int(seed),
        "hyper":    str(hyper),
        "value":    float(value),
        "energy_kwh":        float(r.get("energy_kwh", 0.0)),
        "ci_weighted_mean":  ci_eff,
        "cfe_canonical_pct": cfe_canonical,
        "cfe_pct":           float(r.get("cfe_pct", 0.0)),
        "cfe_abs_pct":       float(r.get("cfe_abs_pct", 0.0)),
        "p95_slowdown":      float(r.get("p95_slowdown", 1.0)),
        "n_jobs":            int(r.get("n_jobs", 0)),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path,
                    default=ROOT / "gridpilot" / "experiments_v2" / "data" / "hyper_sweep")
    p.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES))
    p.add_argument("--mw",        type=int, default=DEFAULT_MW)
    p.add_argument("--seeds",     type=int, default=DEFAULT_SEEDS)
    p.add_argument("--workers",   type=int, default=4)
    p.add_argument("--jobs",      type=Path, default=None)
    p.add_argument("--no-cache",  action="store_true")
    p.add_argument("--max-jobs",  type=int, default=None,
                    help="sub-sample the trace to at most this many jobs")
    args = p.parse_args(argv)

    countries = [c.strip() for c in args.countries.split(",") if c.strip()]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cells_dir = args.output_dir / "cells"
    cells_dir.mkdir(exist_ok=True)

    jobs_path = args.jobs or (JOBS_EXT if JOBS_EXT.exists() else JOBS_JAN)
    if not jobs_path.exists():
        print(f"ABORT: jobs trace not found at {jobs_path}", file=sys.stderr)
        return 2
    print(f"[04-hyper-sweep] trace: {jobs_path}")
    jobs_df = pd.read_parquet(jobs_path)
    print(f"[04-hyper-sweep] loaded {len(jobs_df)} jobs")

    if args.max_jobs is not None and len(jobs_df) > args.max_jobs:
        rng = np.random.default_rng(20260519)
        idx = rng.choice(len(jobs_df), size=args.max_jobs, replace=False)
        jobs_df = jobs_df.iloc[sorted(idx)].reset_index(drop=True)
        print(f"[04-hyper-sweep] sub-sampled to {len(jobs_df)} jobs")

    cooling_params = _resolve_cooling_params()

    cells = [
        (c, hyper, value, seed)
        for c in countries
        for (hyper, value) in HYPER_VALUE_PAIRS
        for seed in range(args.seeds)
    ]
    to_run = []
    rows: list[dict] = []
    for cell in cells:
        cid = _cell_id(*cell)
        cp = cells_dir / f"{cid}.json"
        if not args.no_cache:
            r = _load_cached(cp)
            if r is not None:
                rows.append(r)
                continue
        to_run.append((cid, cell))
    print(f"[04-hyper-sweep] cells: {len(cells)} total, "
          f"{len(rows)} cached, {len(to_run)} to run, "
          f"workers={args.workers}")

    t0 = time.time()
    bar = (tqdm(total=len(to_run), desc="hyper-sweep", unit="cell",
                 smoothing=0.1, mininterval=0.5, dynamic_ncols=True)
            if HAVE_TQDM else None)
    def _tick():
        if bar is not None: bar.update(1)

    if args.workers <= 1:
        for cid, cell in to_run:
            row = _run(*cell, args.mw, jobs_df, cooling_params)
            _persist(cells_dir / f"{cid}.json", row)
            rows.append(row); _tick()
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {
                ex.submit(_run, *cell, args.mw, jobs_df, cooling_params): (cid, cell)
                for cid, cell in to_run
            }
            for fut in as_completed(futs):
                cid, _ = futs[fut]
                try:
                    row = fut.result(timeout=3600)
                except Exception as exc:
                    print(f"\n[ERROR] cell {cid} failed: {exc}", flush=True)
                    _tick(); continue
                _persist(cells_dir / f"{cid}.json", row)
                rows.append(row); _tick()
    if bar is not None: bar.close()

    if not rows:
        print("[04-hyper-sweep] WARN: no rows produced; nothing to summarise.")
        return 3

    df = pd.DataFrame(rows).sort_values(
        ["country", "hyper", "value", "seed"], kind="stable")
    csv_path = args.output_dir / "hyper_sweep.csv"
    df.to_csv(csv_path, index=False, float_format="%.4f")
    print(f"[04-hyper-sweep] wrote {csv_path}")

    metric_cols = ["energy_kwh", "ci_weighted_mean", "cfe_canonical_pct",
                   "cfe_pct", "cfe_abs_pct", "p95_slowdown"]
    summary = df.groupby(["hyper", "value"],
                          as_index=False)[metric_cols].mean()
    # Add a default-reference column for delta-vs-default convenience.
    for h, default_v in DEFAULTS.items():
        ref = summary[(summary["hyper"] == h) & (summary["value"] == float(default_v))]
        if not ref.empty:
            ref_cfe = float(ref.iloc[0]["cfe_canonical_pct"])
            mask = summary["hyper"] == h
            summary.loc[mask, f"d_cfe_vs_default_pp"] = (
                summary.loc[mask, "cfe_canonical_pct"] - ref_cfe
            )
    summary_path = args.output_dir / "HYPER_SUMMARY.csv"
    summary.to_csv(summary_path, index=False, float_format="%.4f")
    print(f"[04-hyper-sweep] wrote {summary_path}")

    (args.output_dir / "RUN_MANIFEST.json").write_text(json.dumps({
        "kind": "hyper_sweep", "version": 2,
        "git_sha": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False).stdout.strip() or "unknown",
        "python": platform.python_version(), "host": platform.node(),
        "argv": sys.argv, "n_cells": len(rows),
        "trace": str(jobs_path), "countries": countries, "mw": args.mw,
        "hyper_sweep": {k: list(v) for k, v in SWEEP.items()},
        "defaults": DEFAULTS,
        "seeds": args.seeds,
        "wall_seconds": int(time.time() - t0),
    }, indent=2, default=str))
    print(f"[04-hyper-sweep] done in {int(time.time() - t0)} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
