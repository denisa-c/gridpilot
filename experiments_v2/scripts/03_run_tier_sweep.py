#!/usr/bin/env python3
"""
experiments_v2/scripts/03_run_tier_sweep.py
============================================
Phase 4b — per-tier contribution sweep.

For each (country, MW, tier_k, seed) cell: force every job in the
trace to tier k (T0..T5), run through v1's f-SLA dispatcher with
mechanism M3 (the headline anti-gaming mechanism), and report the
per-tier CFE lift and p95 slowdown.  This decomposes the headline
M3 lift across the six tier choices.

Cells: 6 countries × 3 MW × 6 tiers × 8 seeds = 864 (default).

Outputs:
  data/tier_sweep/cells/<cell_id>.json
  data/tier_sweep/tier_sweep.csv
  data/tier_sweep/TIER_SUMMARY.csv
  data/tier_sweep/RUN_MANIFEST.json

This script imports run_one_cell semantics from the v1 single-tier
sweep (scripts/multicountry/replay_single_tier_sweep.py) because
forcing every job to one tier requires bypassing the AI-baseline
predictor that v1's standard f-SLA replay uses.  v2's contribution
here is (a) the per-cell JSON cache for resumability and (b) the
shared accounting output schema so downstream figures (06) can
consume tier_sweep.csv and country_sweep.csv identically.

Usage:
  PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \\
      gridpilot/experiments_v2/scripts/03_run_tier_sweep.py
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "gridpilot" / "src"))
sys.path.insert(0, str(ROOT / "gridpilot" / "scripts" / "multicountry"))
sys.path.insert(0, str(ROOT / "gridpilot" / "scripts" / "m100"))
sys.path.insert(0, str(ROOT / "gridpilot" / "experiments_v2" / "src"))

# v1's single-tier sweep already implements the "force every job to
# tier k" semantics.  We import its run_one_cell and shim the v2 CSV
# schema on top.
# pylint: disable=wrong-import-position,import-error
from replay_single_tier_sweep import (  # type: ignore[import-not-found]
    run_one_cell as v1_tier_cell,
)
from replay_country_sweep import _nodes_for_mw  # type: ignore[import-not-found]
from inject_fsla_prior import load_pue_params   # type: ignore[import-not-found]
from cooling.cooling_pue_model import (         # type: ignore[import-not-found]
    calibrate_to_design_pue,
)

GRIDPILOT = ROOT / "gridpilot"
GRIDS_DIR = GRIDPILOT / "configs" / "grids"
PUE_RAPS  = GRIDPILOT / "raps" / "config" / "marconi100.yaml"
JOBS_EXT  = GRIDPILOT / "data" / "traces" / "m100_real_jobs_extended.parquet"
JOBS_JAN  = GRIDPILOT / "data" / "traces" / "m100_real_jobs.parquet"

DEFAULT_COUNTRIES = ["SE", "CH", "FR", "IT", "DE", "PL"]
DEFAULT_MW = [1, 10, 50]
DEFAULT_TIERS = [0, 1, 2, 3, 4, 5]
DEFAULT_SEEDS = 8


def _resolve_cooling_params():
    if PUE_RAPS.exists():
        return load_pue_params(PUE_RAPS)
    return calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)


def _cell_id(country: str, mw: int, tier: int, seed: int) -> str:
    return f"{country}_{mw:03d}MW_T{tier}_seed{seed}"


def _persist(cell_path: Path, row: dict) -> None:
    cell_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cell_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(row, default=str))
    tmp.replace(cell_path)


def _load_cached(cell_path: Path):
    if not cell_path.exists():
        return None
    try:
        row = json.loads(cell_path.read_text())
        if "cfe_canonical_pct" in row and "tier" in row:
            return row
    except Exception:
        pass
    return None


def _run(c, m, t, s, jobs_df, cooling_params):
    country_yaml = GRIDS_DIR / f"{c}.yaml"
    r = v1_tier_cell(country_yaml, float(m), int(t), int(s),
                     jobs_df, cooling_params, {})
    return {
        "country":  c, "mw": int(m), "tier": int(t),
        "seed":     int(s), "nodes": int(_nodes_for_mw(m)),
        "energy_kwh":        float(r.get("energy_kwh", 0.0)),
        "ci_weighted_mean":  float(r.get("ci_weighted_mean", 0.0)),
        "cfe_canonical_pct": float(r.get("cfe_canonical_pct", 0.0)),
        "co2_g_facility":    float(r.get("co2_g_facility", 0.0)),
        "p50_slowdown":      float(r.get("p50_slowdown", 1.0)),
        "p95_slowdown":      float(r.get("p95_slowdown", 1.0)),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path,
                    default=ROOT / "gridpilot" / "experiments_v2" / "data" / "tier_sweep")
    p.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES))
    p.add_argument("--mw",        default=",".join(str(m) for m in DEFAULT_MW))
    p.add_argument("--tiers",     default=",".join(str(t) for t in DEFAULT_TIERS))
    p.add_argument("--seeds",     type=int, default=DEFAULT_SEEDS)
    p.add_argument("--workers",   type=int, default=4)
    p.add_argument("--jobs",      type=Path, default=None)
    p.add_argument("--no-cache",  action="store_true")
    args = p.parse_args(argv)

    countries = [c.strip() for c in args.countries.split(",")]
    mws       = [int(m.strip()) for m in args.mw.split(",")]
    tiers     = [int(t.strip()) for t in args.tiers.split(",")]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cells_dir = args.output_dir / "cells"
    cells_dir.mkdir(exist_ok=True)

    jobs_path = args.jobs or (JOBS_EXT if JOBS_EXT.exists() else JOBS_JAN)
    if not jobs_path.exists():
        print(f"ABORT: jobs trace not found at {jobs_path}", file=sys.stderr)
        return 2
    print(f"[03-tier-sweep] trace: {jobs_path}")
    jobs_df = pd.read_parquet(jobs_path)
    cooling_params = _resolve_cooling_params()

    cells = [(c, m, t, s)
             for c in countries for m in mws for t in tiers for s in range(args.seeds)]
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
    print(f"[03-tier-sweep] cells: {len(cells)} total, "
          f"{len(rows)} cached, {len(to_run)} to run, "
          f"workers={args.workers}")

    t0 = time.time()
    if args.workers <= 1:
        for k, (cid, cell) in enumerate(to_run):
            row = _run(*cell, jobs_df, cooling_params)
            _persist(cells_dir / f"{cid}.json", row)
            rows.append(row)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_run, *cell, jobs_df, cooling_params): (cid, cell)
                    for cid, cell in to_run}
            for k, fut in enumerate(as_completed(futs)):
                cid, _ = futs[fut]
                row = fut.result()
                _persist(cells_dir / f"{cid}.json", row)
                rows.append(row)
                if (k + 1) % max(1, len(to_run) // 20) == 0:
                    el = int(time.time() - t0)
                    print(f"  [{k+1}/{len(to_run)}] {cid}  "
                          f"(elapsed {el//60:02d}:{el%60:02d})", flush=True)

    df = pd.DataFrame(rows).sort_values(
        ["country", "mw", "tier", "seed"], kind="stable")
    csv_path = args.output_dir / "tier_sweep.csv"
    df.to_csv(csv_path, index=False, float_format="%.4f")
    print(f"[03-tier-sweep] wrote {csv_path}")

    # Per-(country, tier) means with T0 reference subtracted for lift.
    metric_cols = ["energy_kwh", "ci_weighted_mean", "cfe_canonical_pct",
                   "co2_g_facility", "p95_slowdown"]
    summary = df.groupby(["country", "tier"], as_index=False)[metric_cols].mean()
    # CFE lift over the per-country T0 reference.
    t0_ref = summary.query("tier == 0").set_index("country")["cfe_canonical_pct"]
    summary["cfe_lift_pp"] = (
        summary["cfe_canonical_pct"] - summary["country"].map(t0_ref)
    )
    summary_path = args.output_dir / "TIER_SUMMARY.csv"
    summary.to_csv(summary_path, index=False, float_format="%.4f")
    print(f"[03-tier-sweep] wrote {summary_path}")

    (args.output_dir / "RUN_MANIFEST.json").write_text(json.dumps({
        "kind": "tier_sweep", "version": 2,
        "git_sha": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False).stdout.strip() or "unknown",
        "python": platform.python_version(), "host": platform.node(),
        "argv": sys.argv, "n_cells": len(rows),
        "trace": str(jobs_path), "countries": countries,
        "mw": mws, "tiers": tiers, "seeds": args.seeds,
        "wall_seconds": int(time.time() - t0),
    }, indent=2, default=str))
    print(f"[03-tier-sweep] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
