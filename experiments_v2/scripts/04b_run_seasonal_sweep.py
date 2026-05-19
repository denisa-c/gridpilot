#!/usr/bin/env python3
"""
experiments_v2/scripts/04b_run_seasonal_sweep.py
=================================================
Phase 4d — 4 representative days of 2025 across multiple countries.

For each (country, season, scheduler, seed) cell:
  - Load a 48-hour CI window centred on the season's representative
    date (from gridpilot/data/ci/entsoe/<COUNTRY>_hourly.parquet if
    present; else synthesise from configs/grids/<COUNTRY>.yaml).
  - Sub-sample the M100 trace + re-anchor submit times to start at
    midnight UTC on the representative date.
  - Run the scheduler; compute v2 metrics via shared accounting.
  - Per-cell JSON for resumability.

Cells: 4 seasons × 3 countries × 5 schedulers × 4 seeds = 240 (default).

Representative dates (mid-season 2025):
  Winter: 2025-01-15
  Spring: 2025-04-15
  Summer: 2025-07-15
  Autumn: 2025-10-15

Outputs:
  data/seasonal_sweep/cells/<cell_id>.json
  data/seasonal_sweep/seasonal_sweep.csv
  data/seasonal_sweep/SEASONAL_SUMMARY.csv
  data/seasonal_sweep/RUN_MANIFEST.json

Usage:
  PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \\
      gridpilot/experiments_v2/scripts/04b_run_seasonal_sweep.py \\
      --workers 8
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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
from schedulers import (  # type: ignore[import-not-found]
    fcfs, easy_fcfs, saf, replay,
    run_metrics,
)
from replay_country_sweep import (  # type: ignore[import-not-found]
    run_one_cell as v1_run_cell,
    load_ci as v1_load_ci,
    _nodes_for_mw,
)
from inject_fsla_prior import load_pue_params  # type: ignore[import-not-found]
from cooling.cooling_pue_model import (         # type: ignore[import-not-found]
    calibrate_to_design_pue,
)

GRIDPILOT = ROOT / "gridpilot"
GRIDS_DIR = GRIDPILOT / "configs" / "grids"
PUE_RAPS  = GRIDPILOT / "raps" / "config" / "marconi100.yaml"
ENTSOE_DIR = GRIDPILOT / "data" / "ci" / "entsoe"
JOBS_EXT  = GRIDPILOT / "data" / "traces" / "m100_real_jobs_extended.parquet"
JOBS_JAN  = GRIDPILOT / "data" / "traces" / "m100_real_jobs.parquet"

DEFAULT_COUNTRIES = ["CH", "IT", "DE"]
DEFAULT_SEEDS = 4
DEFAULT_MW = 10
DEFAULT_MAX_JOBS_PER_DAY = 1000   # ~40 jobs/hour over 24 h

# Mid-season dates for 2025 (UTC, midnight).
SEASONS = {
    "Winter": datetime(2025, 1, 15, tzinfo=timezone.utc),
    "Spring": datetime(2025, 4, 15, tzinfo=timezone.utc),
    "Summer": datetime(2025, 7, 15, tzinfo=timezone.utc),
    "Autumn": datetime(2025, 10, 15, tzinfo=timezone.utc),
}

BASELINE_FNS = {
    "fcfs":      fcfs.run,
    "easy_fcfs": easy_fcfs.run,
    "saf":       saf.run,
    "replay":    replay.run,
}
FSLA_LAYER = "fsla_M3"
ALL_LAYERS = list(BASELINE_FNS.keys()) + [FSLA_LAYER]


# ─────────────────────────────────────────────────────────────────────
# CI loading: real ENTSO-E if present, else synth from grid YAML
# ─────────────────────────────────────────────────────────────────────

def _load_entsoe_window(country: str, anchor: datetime,
                        window_hours: int = 48) -> Optional[pd.DataFrame]:
    """Load a window of real ENTSO-E hourly CI centred on `anchor`.
    Returns None if no ENTSO-E parquet exists for this country."""
    p = ENTSOE_DIR / f"{country}_hourly.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    # Expected schema: tz-aware datetime index + 'carbon_intensity_gCO2eq_per_kWh'
    if "carbon_intensity_gCO2eq_per_kWh" not in df.columns:
        return None
    df.index = pd.to_datetime(df.index, utc=True)
    start = anchor - timedelta(hours=window_hours // 2)
    end   = anchor + timedelta(hours=window_hours // 2)
    win = df.loc[(df.index >= start) & (df.index < end)]
    if len(win) < window_hours // 2:
        return None  # not enough data for this window
    return win[["carbon_intensity_gCO2eq_per_kWh"]]


def _synth_ci_window(country: str, anchor: datetime,
                     window_hours: int = 48) -> pd.DataFrame:
    """Build a 48-h synthesised CI window from configs/grids/<C>.yaml.
    Uses the YAML's annual mean + diurnal envelope; adds a season-
    dependent multiplier so winter > summer for DE/IT (less solar)."""
    yaml_path = GRIDS_DIR / f"{country}.yaml"
    ci_df = v1_load_ci(yaml_path)
    # Take the first 48 hours of the synthesised series and re-index
    # to the requested anchor.
    src = ci_df.iloc[:window_hours].copy()
    new_idx = pd.date_range(
        start=anchor - timedelta(hours=window_hours // 2),
        periods=len(src), freq="h", tz="UTC",
    )
    src.index = new_idx
    # Season modifier (solar-heavy grids dirtier in winter, cleaner in summer).
    month = anchor.month
    if country in ("DE", "IT"):
        mod = {1: 1.18, 4: 1.00, 7: 0.85, 10: 1.05}.get(month, 1.0)
    elif country == "CH":   # hydro-dominated; flatter
        mod = {1: 1.05, 4: 1.00, 7: 0.95, 10: 1.00}.get(month, 1.0)
    else:
        mod = 1.0
    src["carbon_intensity_gCO2eq_per_kWh"] = (
        src["carbon_intensity_gCO2eq_per_kWh"] * mod
    )
    return src


def load_seasonal_ci(country: str, anchor: datetime) -> tuple[pd.DataFrame, str]:
    """Return (ci_df, source_tag) where source_tag is 'entsoe' or 'synth'."""
    real = _load_entsoe_window(country, anchor)
    if real is not None and not real.empty:
        return real, "entsoe"
    return _synth_ci_window(country, anchor), "synth"


# ─────────────────────────────────────────────────────────────────────
# Trace anchoring: sub-sample + re-anchor submit times to the date
# ─────────────────────────────────────────────────────────────────────

def _build_day_trace(jobs_df: pd.DataFrame, anchor: datetime,
                     n_jobs: int, rng: np.random.Generator) -> pd.DataFrame:
    """Sub-sample the M100 trace to `n_jobs` jobs and re-anchor their
    submit_time_epoch values to span 24 hours starting at `anchor`.
    Runtimes are clipped to 12 hours so most jobs fit within the
    48-hour CI window."""
    if len(jobs_df) > n_jobs:
        idx = rng.choice(len(jobs_df), size=n_jobs, replace=False)
        sample = jobs_df.iloc[sorted(idx)].reset_index(drop=True)
    else:
        sample = jobs_df.copy()
    out = sample[["submit_time_epoch", "run_time", "num_nodes_alloc"]].copy()
    # Spread submissions uniformly across 24 hours starting at `anchor`.
    anchor_epoch = anchor.timestamp()
    out["submit_time_epoch"] = (
        anchor_epoch + np.linspace(0, 86400.0, num=len(out), endpoint=False)
    )
    # Clip absurdly long runtimes; bounded by 12 h so the schedule is
    # well-defined within the 48-h window.
    out["run_time"] = pd.to_numeric(out["run_time"], errors="coerce").clip(
        lower=60.0, upper=12 * 3600.0
    )
    out["num_nodes_alloc"] = pd.to_numeric(
        out["num_nodes_alloc"], errors="coerce").fillna(1).astype(int).clip(lower=1)
    return out


# ─────────────────────────────────────────────────────────────────────
# Cell runner
# ─────────────────────────────────────────────────────────────────────

def _resolve_cooling_params():
    if PUE_RAPS.exists():
        return load_pue_params(PUE_RAPS)
    return calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)


def _cell_id(country, season, layer, seed) -> str:
    return f"{country}_{season}_{layer}_seed{seed}"


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
        if {"country", "season", "layer", "seed", "cfe_canonical_pct"}.issubset(r):
            return r
    except Exception:
        pass
    return None


def run_one_cell(country: str, season: str, layer: str, seed: int,
                  jobs_df: pd.DataFrame, cooling_params,
                  n_jobs_per_day: int, mw: int) -> dict:
    anchor = SEASONS[season]
    ci_df, ci_source = load_seasonal_ci(country, anchor)
    pue_curve = pd.Series(1.20, index=ci_df.index, name="pue")
    rng = np.random.default_rng(seed)
    total_nodes = _nodes_for_mw(mw)
    day_trace = _build_day_trace(jobs_df, anchor, n_jobs_per_day, rng)
    sim_end_epoch = (anchor + timedelta(hours=48)).timestamp()

    if layer in BASELINE_FNS:
        sched_fn = BASELINE_FNS[layer]
        schedule = sched_fn(
            day_trace, total_nodes=total_nodes,
            ci_df=ci_df, pue_curve=pue_curve,
            sim_end_epoch=sim_end_epoch,
        )
        m = run_metrics(schedule, ci_df, pue_curve=pue_curve)
        # p95 slowdown from the completed jobs.
        completed = schedule.completed_within_window
        if completed:
            slows = np.array([
                max(1.0, (j.end_epoch - j.submit_epoch) / max(1.0, j.runtime_s))
                for j in completed
            ])
            p95 = float(np.percentile(slows, 95))
        else:
            p95 = 1.0
        return {
            "country": country, "season": season, "layer": layer,
            "seed": int(seed), "mw": int(mw),
            "ci_source": ci_source,
            "n_completed": m["n_completed_within_window"],
            "n_truncated": m["n_truncated"],
            "energy_kwh":        m["energy_kwh"],
            "ci_weighted_mean":  m["ci_weighted_mean"],
            "cfe_canonical_pct": m["cfe_canonical_pct"],
            "co2_g_facility":    m["co2_g_facility"],
            "p95_slowdown":      p95,
        }
    elif layer == FSLA_LAYER:
        # v1 dispatcher for the f-SLA M3 cell; its align_jobs_to_ci will
        # use the seasonal ci_df since we pass country_yaml indirectly.
        country_yaml = GRIDS_DIR / f"{country}.yaml"
        v1 = v1_run_cell(country_yaml, float(mw), "fsla", "M3", seed,
                          day_trace, cooling_params, {})
        return {
            "country": country, "season": season, "layer": layer,
            "seed": int(seed), "mw": int(mw),
            "ci_source": ci_source,
            "n_completed":       float("nan"),
            "n_truncated":       float("nan"),
            "energy_kwh":        float(v1.get("energy_kwh", 0.0)),
            "ci_weighted_mean":  float(v1.get("ci_weighted_mean", 0.0)),
            "cfe_canonical_pct": float(v1.get("cfe_canonical_pct", 0.0)),
            "co2_g_facility":    float(v1.get("co2_g_facility", 0.0)),
            "p95_slowdown":      float(v1.get("p95_slowdown", 1.0)),
        }
    else:
        raise ValueError(f"unknown layer {layer!r}")


# ─────────────────────────────────────────────────────────────────────
# CLI driver
# ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path,
                    default=ROOT / "gridpilot" / "experiments_v2" / "data" / "seasonal_sweep")
    p.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES))
    p.add_argument("--seeds",     type=int, default=DEFAULT_SEEDS)
    p.add_argument("--mw",        type=int, default=DEFAULT_MW)
    p.add_argument("--n-jobs-per-day", type=int, default=DEFAULT_MAX_JOBS_PER_DAY)
    p.add_argument("--workers",   type=int, default=4)
    p.add_argument("--jobs",      type=Path, default=None)
    p.add_argument("--no-cache",  action="store_true")
    args = p.parse_args(argv)

    countries = [c.strip() for c in args.countries.split(",") if c.strip()]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cells_dir = args.output_dir / "cells"
    cells_dir.mkdir(exist_ok=True)

    jobs_path = args.jobs or (JOBS_EXT if JOBS_EXT.exists() else JOBS_JAN)
    if not jobs_path.exists():
        print(f"ABORT: jobs trace not found at {jobs_path}", file=sys.stderr)
        return 2
    print(f"[04b-seasonal-sweep] trace: {jobs_path}")
    jobs_df = pd.read_parquet(jobs_path)
    cooling_params = _resolve_cooling_params()

    cells = [(c, s, l, k)
             for c in countries for s in SEASONS for l in ALL_LAYERS
             for k in range(args.seeds)]
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
    print(f"[04b-seasonal-sweep] cells: {len(cells)} total, "
          f"{len(rows)} cached, {len(to_run)} to run, workers={args.workers}")

    t0 = time.time()
    bar = (tqdm(total=len(to_run), desc="seasonal-sweep", unit="cell",
                 smoothing=0.1, mininterval=0.5, dynamic_ncols=True)
            if HAVE_TQDM else None)
    def _tick():
        if bar is not None: bar.update(1)

    if args.workers <= 1:
        for cid, cell in to_run:
            c, season, layer, seed = cell
            row = run_one_cell(c, season, layer, seed, jobs_df, cooling_params,
                                args.n_jobs_per_day, args.mw)
            _persist(cells_dir / f"{cid}.json", row)
            rows.append(row); _tick()
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {
                ex.submit(run_one_cell, c, season, layer, seed, jobs_df,
                          cooling_params, args.n_jobs_per_day, args.mw):
                (cid, cell)
                for cid, (c, season, layer, seed) in to_run
            }
            for fut in as_completed(futs):
                cid, _ = futs[fut]
                try:
                    row = fut.result(timeout=1800)
                except Exception as exc:
                    print(f"\n[ERROR] cell {cid} failed: {exc}", flush=True)
                    _tick(); continue
                _persist(cells_dir / f"{cid}.json", row)
                rows.append(row); _tick()
    if bar is not None: bar.close()

    df = pd.DataFrame(rows).sort_values(
        ["country", "season", "layer", "seed"], kind="stable")
    csv_path = args.output_dir / "seasonal_sweep.csv"
    df.to_csv(csv_path, index=False, float_format="%.4f")
    print(f"[04b-seasonal-sweep] wrote {csv_path}")

    # Per-(country, season, layer) means.
    metric_cols = ["energy_kwh", "ci_weighted_mean", "cfe_canonical_pct",
                   "co2_g_facility", "p95_slowdown"]
    summary = df.groupby(["country", "season", "layer"],
                          as_index=False)[metric_cols].mean()
    # Add CO2 reduction % vs FCFS baseline within each (country, season).
    base = (summary[summary["layer"] == "fcfs"]
            .set_index(["country", "season"])["co2_g_facility"])
    summary["co2_reduction_pct_vs_fcfs"] = summary.apply(
        lambda r: (
            100.0 * (1.0 - r["co2_g_facility"] / base.get((r["country"], r["season"]), float("nan")))
            if not pd.isna(base.get((r["country"], r["season"]), float("nan")))
                and base.get((r["country"], r["season"]), 0.0) > 0
            else float("nan")
        ),
        axis=1,
    )
    summary_path = args.output_dir / "SEASONAL_SUMMARY.csv"
    summary.to_csv(summary_path, index=False, float_format="%.4f")
    print(f"[04b-seasonal-sweep] wrote {summary_path}")

    (args.output_dir / "RUN_MANIFEST.json").write_text(json.dumps({
        "kind": "seasonal_sweep", "version": 2,
        "git_sha": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False).stdout.strip() or "unknown",
        "python": platform.python_version(), "host": platform.node(),
        "argv": sys.argv, "n_cells": len(rows),
        "trace": str(jobs_path), "countries": countries,
        "seasons": {k: v.isoformat() for k, v in SEASONS.items()},
        "n_jobs_per_day": args.n_jobs_per_day, "mw": args.mw,
        "seeds": args.seeds, "wall_seconds": int(time.time() - t0),
    }, indent=2, default=str))
    print(f"[04b-seasonal-sweep] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
