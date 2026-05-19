#!/usr/bin/env python3
"""
experiments_v2/scripts/04_run_hyper_sweep.py
=============================================
Phase 4c — contract-hyperparameter sensitivity sweep.

One-at-a-time sweep over four contract knobs around the default
settings, with the headline M3 mechanism:
    alpha_scale       (credit schedule scale)        : 0.5, 1.0, 2.0, 4.0
    window_scale      (deferral window scale)        : 0.5, 1.0, 2.0
    t4_envelope_scale (T4 replica envelope scale)    : 1.0, 2.0
    short_job_s       (short-job exclusion, seconds) : 1, 60, 300

Cells: 12 hyperparam settings × 6 countries × 1 MW (10 MW) × 8 seeds = 576.

Wraps v1's replay_hyperparameter_sweep.run_one_cell (which already
implements the per-knob scaling) and adds the v2 per-cell JSON
cache + manifest writer for resumability and provenance.

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

DEFAULT_COUNTRIES = ["SE", "CH", "FR", "IT", "DE", "PL"]
DEFAULT_MW = 10
DEFAULT_SEEDS = 8

# 12 hyperparameter settings: each tuple is one cell config (others at default).
HYPER_GRID = [
    # (label, alpha_scale, window_scale, t4_envelope_scale, short_job_s)
    ("alpha_0.5",  0.5, 1.0, 1.0, 60),
    ("alpha_1.0",  1.0, 1.0, 1.0, 60),  # the default reference
    ("alpha_2.0",  2.0, 1.0, 1.0, 60),
    ("alpha_4.0",  4.0, 1.0, 1.0, 60),
    ("window_0.5", 1.0, 0.5, 1.0, 60),
    ("window_2.0", 1.0, 2.0, 1.0, 60),
    ("t4env_2.0",  1.0, 1.0, 2.0, 60),
    ("short_1",    1.0, 1.0, 1.0, 1),
    ("short_300",  1.0, 1.0, 1.0, 300),
    ("window_5.0", 1.0, 5.0, 1.0, 60),
    ("alpha_8.0",  8.0, 1.0, 1.0, 60),
    ("short_3600", 1.0, 1.0, 1.0, 3600),
]


def _resolve_cooling_params():
    if PUE_RAPS.exists():
        return load_pue_params(PUE_RAPS)
    return calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)


def _cell_id(c, label, mw, s):
    return f"{c}_{label}_{mw:03d}MW_seed{s}"


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
        if "cfe_canonical_pct" in r and "hyper_label" in r:
            return r
    except Exception:
        pass
    return None


def _run(c, label, alpha_scale, window_scale, t4_env, short_s, mw, seed,
         jobs_df, cooling_params):
    country_yaml = GRIDS_DIR / f"{c}.yaml"
    r = v1_hyper_cell(
        country_yaml, float(mw), int(seed), jobs_df, cooling_params,
        alpha_scale=alpha_scale, window_scale=window_scale,
        t4_envelope_scale=t4_env, short_job_s=short_s,
    )
    return {
        "country":  c, "mw": int(mw), "seed": int(seed),
        "hyper_label": label,
        "alpha_scale": float(alpha_scale),
        "window_scale": float(window_scale),
        "t4_envelope_scale": float(t4_env),
        "short_job_s": int(short_s),
        "energy_kwh":        float(r.get("energy_kwh", 0.0)),
        "ci_weighted_mean":  float(r.get("ci_weighted_mean", 0.0)),
        "cfe_canonical_pct": float(r.get("cfe_canonical_pct", 0.0)),
        "co2_g_facility":    float(r.get("co2_g_facility", 0.0)),
        "p95_slowdown":      float(r.get("p95_slowdown", 1.0)),
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

    countries = [c.strip() for c in args.countries.split(",")]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cells_dir = args.output_dir / "cells"
    cells_dir.mkdir(exist_ok=True)

    jobs_path = args.jobs or (JOBS_EXT if JOBS_EXT.exists() else JOBS_JAN)
    if not jobs_path.exists():
        print(f"ABORT: jobs trace not found at {jobs_path}", file=sys.stderr)
        return 2
    jobs_df = pd.read_parquet(jobs_path)
    if args.max_jobs is not None and len(jobs_df) > args.max_jobs:
        import numpy as _np
        rng = _np.random.default_rng(20260519)
        idx = rng.choice(len(jobs_df), size=args.max_jobs, replace=False)
        jobs_df = jobs_df.iloc[sorted(idx)].reset_index(drop=True)
        print(f"[04-hyper-sweep] sub-sampled to {len(jobs_df)} jobs")
    cooling_params = _resolve_cooling_params()

    cells = [
        (c, label, alpha_s, win_s, t4, short_s, args.mw, s)
        for c in countries
        for (label, alpha_s, win_s, t4, short_s) in HYPER_GRID
        for s in range(args.seeds)
    ]
    to_run = []
    rows: list[dict] = []
    for cell in cells:
        c, label, *_, s = cell
        cid = _cell_id(c, label, args.mw, s)
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
        for k, (cid, cell) in enumerate(to_run):
            row = _run(*cell, jobs_df, cooling_params)
            _persist(cells_dir / f"{cid}.json", row)
            rows.append(row); _tick()
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_run, *cell, jobs_df, cooling_params): (cid, cell)
                    for cid, cell in to_run}
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

    df = pd.DataFrame(rows).sort_values(
        ["country", "hyper_label", "seed"], kind="stable")
    csv_path = args.output_dir / "hyper_sweep.csv"
    df.to_csv(csv_path, index=False, float_format="%.4f")
    print(f"[04-hyper-sweep] wrote {csv_path}")

    metric_cols = ["energy_kwh", "ci_weighted_mean", "cfe_canonical_pct",
                   "co2_g_facility", "p95_slowdown"]
    summary = df.groupby(["hyper_label"], as_index=False)[metric_cols].mean()
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
        "hyper_grid": [list(t) for t in HYPER_GRID],
        "seeds": args.seeds,
        "wall_seconds": int(time.time() - t0),
    }, indent=2, default=str))
    print(f"[04-hyper-sweep] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
