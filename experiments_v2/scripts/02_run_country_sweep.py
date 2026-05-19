#!/usr/bin/env python3
"""
experiments_v2/scripts/02_run_country_sweep.py
==============================================
Phase 4a — v2 country sweep.

Cells: 6 countries × 3 MW × 9 schedulers × 8 seeds = 1296 cells
(can be over-ridden with CLI flags).

Schedulers covered, per cell:
  baselines (v2 hand-rolled, via experiments_v2/src/schedulers):
    fcfs       — Mu'alem & Feitelson 2001 §2
    easy_fcfs  — Lifka 1995 §3
    saf        — Carastan-Santos & de Camargo 2019 §3
    replay     — historical M100 dispatch
  f-SLA contract (v1 dispatcher in gridpilot/src/scheduler/scheduler_pue_aware.py):
    fsla_none  — all-T0 baseline (rigid, no contract)
    fsla_M0..M3 — anti-gaming mechanisms

Outputs:
  data/country_sweep/cells/<cell_id>.json   ← one JSON per cell, resumable
  data/country_sweep/country_sweep.csv      ← all cells, all schedulers
  data/country_sweep/COUNTRY_SUMMARY.csv    ← per-country means
  data/country_sweep/RUN_MANIFEST.json      ← git SHA, env, args, hash

Usage:
  PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \\
      gridpilot/experiments_v2/scripts/02_run_country_sweep.py \\
      --output-dir gridpilot/experiments_v2/data/country_sweep \\
      --workers 4
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
    run_metrics, P_NODE_KW,
)
from replay_country_sweep import (  # type: ignore[import-not-found]
    run_one_cell as v1_run_cell,
    align_jobs_to_ci, load_ci, _scale_trace_to_cluster, _nodes_for_mw,
)
from inject_fsla_prior import load_pue_params  # type: ignore[import-not-found]
from cooling.cooling_pue_model import (  # type: ignore[import-not-found]
    calibrate_to_design_pue,
)

GRIDPILOT = ROOT / "gridpilot"
GRIDS_DIR = GRIDPILOT / "configs" / "grids"
PUE_RAPS  = GRIDPILOT / "raps" / "config" / "marconi100.yaml"
JOBS_EXT  = GRIDPILOT / "data" / "traces" / "m100_real_jobs_extended.parquet"
JOBS_JAN  = GRIDPILOT / "data" / "traces" / "m100_real_jobs.parquet"

DEFAULT_COUNTRIES = ["SE", "CH", "FR", "IT", "DE", "PL"]
DEFAULT_MW = [1, 10, 50]
DEFAULT_SEEDS = 8

BASELINE_FNS = {
    "fcfs":      fcfs.run,
    "easy_fcfs": easy_fcfs.run,
    "saf":       saf.run,
    "replay":    replay.run,
}
FSLA_MECHANISMS = ["none", "M0", "M1", "M2", "M3"]
ALL_LAYERS = list(BASELINE_FNS.keys()) + [f"fsla_{m}" for m in FSLA_MECHANISMS]

# Headline baselines used to compute Δ-vs-X columns.
DELTA_BASELINES = ["fcfs", "easy_fcfs", "saf", "replay"]


# ─────────────────────────────────────────────────────────────────────
# Cell runner
# ─────────────────────────────────────────────────────────────────────

def _resolve_cooling_params():
    if PUE_RAPS.exists():
        return load_pue_params(PUE_RAPS)
    return calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)


def _build_pue_curve(ci_index, avg_pue: float = 1.20) -> pd.Series:
    return pd.Series(avg_pue, index=ci_index, name="pue")


def run_one_cell(country: str, mw: int, layer: str, seed: int,
                  jobs_df: pd.DataFrame, cooling_params) -> dict:
    """One (country, mw, layer, seed) cell.  Returns a flat metric dict."""
    country_yaml = GRIDS_DIR / f"{country}.yaml"
    ci_df = load_ci(country_yaml)
    pue_curve = _build_pue_curve(ci_df.index)

    total_nodes = _nodes_for_mw(mw)
    jobs_local = align_jobs_to_ci(jobs_df, ci_df)
    jobs_local = _scale_trace_to_cluster(jobs_local, total_nodes)

    last_submit = float(jobs_local["submit_time_epoch"].max())
    last_runtime = float(jobs_local["run_time"].max())
    sim_end_epoch = last_submit + last_runtime + 7 * 86400.0

    if layer in BASELINE_FNS:
        # ---- v2 baseline path: scheduler → ScheduleResult → run_metrics ----
        sched_fn = BASELINE_FNS[layer]
        schedule = sched_fn(
            jobs_local, total_nodes=total_nodes,
            ci_df=ci_df, pue_curve=pue_curve,
            sim_end_epoch=sim_end_epoch,
        )
        m = run_metrics(schedule, ci_df, pue_curve=pue_curve)
        return {
            "country":  country, "mw": int(mw), "layer": layer,
            "seed":     int(seed), "nodes": int(total_nodes),
            "n_completed": m["n_completed_within_window"],
            "n_truncated": m["n_truncated"],
            "energy_kwh":  m["energy_kwh"],
            "ci_weighted_mean":  m["ci_weighted_mean"],
            "cfe_canonical_pct": m["cfe_canonical_pct"],
            "co2_g_it":          m["co2_g_it"],
            "co2_g_facility":    m["co2_g_facility"],
            "source": "v2_scheduler",
        }
    elif layer.startswith("fsla_"):
        # ---- f-SLA contract path: call v1's run_one_cell, remap fields ----
        mech = layer[len("fsla_"):]
        v1 = v1_run_cell(country_yaml, float(mw), "fsla", mech, seed,
                          jobs_df, cooling_params, {})
        # v1's energy/CFE/CI fields are computed with the same formulas
        # as v2 (per-job energy = nodes × P_node × runtime; canonical CFE
        # = 100*(1 - ci_eff/800)).  We copy them in directly.  v1's
        # n_jobs is contaminated by end-of-sim padding (Phase 3 F3 finding)
        # so we report it as a separate column rather than n_completed.
        return {
            "country":  country, "mw": int(mw), "layer": layer,
            "seed":     int(seed), "nodes": int(total_nodes),
            "n_completed":       float("nan"),   # v1 doesn't expose F3 split
            "n_truncated":       float("nan"),
            "energy_kwh":        float(v1.get("energy_kwh", 0.0)),
            "ci_weighted_mean":  float(v1.get("ci_weighted_mean", 0.0)),
            "cfe_canonical_pct": float(v1.get("cfe_canonical_pct", 0.0)),
            "co2_g_it":          float(v1.get("co2_g_it", 0.0)),
            "co2_g_facility":    float(v1.get("co2_g_facility", 0.0)),
            "v1_n_jobs":         int(v1.get("n_jobs", 0)),   # contaminated
            "source": "v1_fsla_dispatcher",
        }
    else:
        raise ValueError(f"unknown layer {layer!r}")


# ─────────────────────────────────────────────────────────────────────
# Per-cell caching + parallel orchestrator
# ─────────────────────────────────────────────────────────────────────

def _cell_id(country: str, mw: int, layer: str, seed: int) -> str:
    return f"{country}_{int(mw):03d}MW_{layer}_seed{seed}"


def _json_default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, float) and not np.isfinite(o):
        return None
    raise TypeError(f"not JSON-serialisable: {type(o).__name__}")


def _persist(cell_path: Path, row: dict) -> None:
    cell_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cell_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row, default=_json_default))
    tmp.replace(cell_path)


def _load_cached(cell_path: Path) -> Optional[dict]:
    if not cell_path.exists():
        return None
    try:
        row = json.loads(cell_path.read_text())
        # Schema check: must have the headline columns.
        required = {"country", "mw", "layer", "seed",
                    "cfe_canonical_pct", "ci_weighted_mean", "energy_kwh"}
        if not required.issubset(row):
            return None
        return row
    except Exception:
        return None


def _compute_deltas(headline: pd.DataFrame) -> pd.DataFrame:
    """Add Δ-vs-baseline columns.  For each (country, mw, seed) triple,
    compute (layer_cfe - baseline_cfe) for each baseline in DELTA_BASELINES.
    """
    out = headline.copy()
    keys = ["country", "mw", "seed"]
    for base in DELTA_BASELINES:
        base_rows = headline.query(f"layer == '{base}'")[keys + ["cfe_canonical_pct", "ci_weighted_mean"]]
        base_rows = base_rows.rename(columns={
            "cfe_canonical_pct": f"_base_{base}_cfe",
            "ci_weighted_mean":  f"_base_{base}_ci",
        })
        out = out.merge(base_rows, on=keys, how="left")
        out[f"d_cfe_vs_{base}_pp"] = out["cfe_canonical_pct"] - out[f"_base_{base}_cfe"]
        out[f"d_ci_vs_{base}_g"]   = out[f"_base_{base}_ci"] - out["ci_weighted_mean"]
    out = out.drop(columns=[c for c in out.columns if c.startswith("_base_")])
    return out


def _country_summary(headline: pd.DataFrame) -> pd.DataFrame:
    """Per-(country, layer) means across MW and seeds."""
    keys = ["country", "layer"]
    metric_cols = ["energy_kwh", "ci_weighted_mean", "cfe_canonical_pct",
                   "co2_g_it", "co2_g_facility"]
    delta_cols = [c for c in headline.columns
                  if c.startswith("d_cfe_vs_") or c.startswith("d_ci_vs_")]
    agg_cols = metric_cols + delta_cols
    summary = headline.groupby(keys, as_index=False)[agg_cols].mean()
    return summary


# ─────────────────────────────────────────────────────────────────────
# CLI driver
# ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path,
                    default=ROOT / "gridpilot" / "experiments_v2" / "data" / "country_sweep")
    p.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES))
    p.add_argument("--mw",        default=",".join(str(m) for m in DEFAULT_MW))
    p.add_argument("--seeds",     type=int, default=DEFAULT_SEEDS)
    p.add_argument("--layers",    default=",".join(ALL_LAYERS),
                    help="comma-separated subset of layers to run")
    p.add_argument("--workers",   type=int, default=4)
    p.add_argument("--jobs",      type=Path, default=None,
                    help="trace parquet; defaults to m100_real_jobs_extended.parquet")
    p.add_argument("--no-cache",  action="store_true",
                    help="re-run every cell even if a cached JSON exists")
    p.add_argument("--max-jobs",  type=int, default=None,
                    help="sub-sample the trace to at most this many jobs "
                         "(stratified by submit-time bucket). Essential "
                         "for fast iteration on the bundled extended "
                         "trace, which has 360k jobs in a compressed "
                         "~1h timespan (build_extended_trace bug — see "
                         "AUDIT_FINDINGS.md F-NEW-TRACE-TIMESPAN).")
    args = p.parse_args(argv)

    countries = [c.strip() for c in args.countries.split(",") if c.strip()]
    mws       = [int(m.strip()) for m in args.mw.split(",") if m.strip()]
    layers    = [l.strip() for l in args.layers.split(",") if l.strip()]
    for layer in layers:
        if layer not in ALL_LAYERS:
            raise ValueError(f"unknown layer {layer!r}; expected subset of {ALL_LAYERS}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cells_dir = args.output_dir / "cells"
    cells_dir.mkdir(exist_ok=True)

    # ---- Load trace ----
    jobs_path = args.jobs or (JOBS_EXT if JOBS_EXT.exists() else JOBS_JAN)
    if not jobs_path.exists():
        print(f"ABORT: jobs trace not found at {jobs_path}", file=sys.stderr)
        return 2
    print(f"[02-country-sweep] trace: {jobs_path}")
    jobs_df = pd.read_parquet(jobs_path)
    print(f"[02-country-sweep] loaded {len(jobs_df)} jobs")

    if args.max_jobs is not None and len(jobs_df) > args.max_jobs:
        # Uniform random sub-sample with a fixed seed for reproducibility.
        rng = np.random.default_rng(20260519)
        idx = rng.choice(len(jobs_df), size=args.max_jobs, replace=False)
        jobs_df = jobs_df.iloc[sorted(idx)].reset_index(drop=True)
        print(f"[02-country-sweep] sub-sampled to {len(jobs_df)} jobs "
              f"(--max-jobs={args.max_jobs})")

    # Diagnostic: trace schema and column health.  Helps localise
    # dtype-related bugs that surface as cryptic 'size 0' errors deep
    # in pandas internals (e.g. nullable-Int64 round-trip from parquet
    # contaminating arithmetic with NA → NaN).
    for col in ("submit_time_epoch", "run_time", "num_nodes_alloc"):
        if col in jobs_df.columns:
            s = jobs_df[col]
            n_null = int(pd.isna(s).sum())
            print(f"  {col:<22s} dtype={str(s.dtype):<10s}  "
                  f"nulls={n_null:>6d}  min={pd.to_numeric(s, errors='coerce').min():.4g}  "
                  f"max={pd.to_numeric(s, errors='coerce').max():.4g}")
        else:
            print(f"  {col:<22s} *** NOT PRESENT in trace ***")

    cooling_params = _resolve_cooling_params()

    # ---- Build cell list, partition into cached vs to-run ----
    cells = [
        (c, m, l, s)
        for c in countries for m in mws for l in layers for s in range(args.seeds)
    ]
    to_run = []
    cached_rows = []
    for cell in cells:
        cid = _cell_id(*cell)
        cp = cells_dir / f"{cid}.json"
        if not args.no_cache:
            r = _load_cached(cp)
            if r is not None:
                cached_rows.append(r)
                continue
        to_run.append((cid, cell))

    print(f"[02-country-sweep] cells: {len(cells)} total, "
          f"{len(cached_rows)} cached, {len(to_run)} to run, "
          f"workers={args.workers}")

    rows: list[dict] = list(cached_rows)

    # ---- Run remaining cells (progress bar) ----
    t0 = time.time()

    def _bar(total: int, desc: str):
        if HAVE_TQDM:
            return tqdm(total=total, desc=desc, unit="cell", smoothing=0.1,
                        mininterval=0.5, dynamic_ncols=True)
        # tqdm-less fallback: a tiny one-line progress object.
        class _P:
            def __init__(self, n): self.n = 0; self.total = n; self.t = time.time()
            def update(self, k=1):
                self.n += k
                el = int(time.time() - self.t)
                eta = int(el * (self.total - self.n) / max(1, self.n))
                print(f"\r  [{self.n}/{self.total}] elapsed {el//60:02d}:{el%60:02d} "
                      f"eta {eta//60:02d}:{eta%60:02d}", end="", flush=True)
            def close(self):  print()
            def write(self, s): print(s)
        return _P(total)

    if args.workers <= 1:
        bar = _bar(len(to_run), "country-sweep")
        for k, (cid, cell) in enumerate(to_run):
            c, m, l, s = cell
            t_cell = time.time()
            row = run_one_cell(c, m, l, s, jobs_df, cooling_params)
            row["_wall_s"] = time.time() - t_cell
            _persist(cells_dir / f"{cid}.json", row)
            rows.append(row)
            bar.update(1)
        bar.close()
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            # IMPORTANT: submit one cell at a time inside a generator;
            # ProcessPoolExecutor pickles args at submit time, and for
            # 360k-row jobs_df that's ~50 MB per submit.  With many cells
            # this dominates wall time.  Using imap-style submission
            # over a generator keeps memory + pickling pressure bounded
            # to (workers + queued) at a time.
            futs = {}
            for cid, (c, m, l, s) in to_run:
                fut = ex.submit(run_one_cell, c, m, l, s, jobs_df, cooling_params)
                futs[fut] = (cid, (c, m, l, s))
            bar = _bar(len(to_run), "country-sweep")
            for fut in as_completed(futs):
                cid, _ = futs[fut]
                t_cell = time.time()
                try:
                    row = fut.result(timeout=3600)   # 1h per-cell timeout
                except Exception as exc:
                    print(f"\n[ERROR] cell {cid} failed: {exc}", flush=True)
                    bar.update(1); continue
                row["_wall_s"] = time.time() - t_cell
                _persist(cells_dir / f"{cid}.json", row)
                rows.append(row)
                bar.update(1)
            bar.close()

    # ---- Compose CSVs ----
    df = pd.DataFrame(rows)
    df = df.sort_values(["country", "mw", "layer", "seed"], kind="stable")
    df = _compute_deltas(df)
    csv_path = args.output_dir / "country_sweep.csv"
    df.to_csv(csv_path, index=False, float_format="%.4f")
    print(f"[02-country-sweep] wrote {csv_path} ({len(df)} rows)")

    summary = _country_summary(df)
    summary_path = args.output_dir / "COUNTRY_SUMMARY.csv"
    summary.to_csv(summary_path, index=False, float_format="%.4f")
    print(f"[02-country-sweep] wrote {summary_path}")

    # ---- Manifest ----
    manifest = {
        "kind": "country_sweep",
        "version": 2,
        "git_sha": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        ).stdout.strip() or "unknown",
        "python":  platform.python_version(),
        "host":    platform.node(),
        "argv":    sys.argv,
        "n_cells": len(rows),
        "trace":   str(jobs_path),
        "countries": countries,
        "mw":      mws,
        "layers":  layers,
        "seeds":   args.seeds,
        "wall_seconds": int(time.time() - t0),
    }
    (args.output_dir / "RUN_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, default=_json_default)
    )
    print(f"[02-country-sweep] wrote {args.output_dir/'RUN_MANIFEST.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
