#!/usr/bin/env python3
"""
scripts/multicountry/replay_spatial_sweep.py
=============================================
Spatial-routing sweep for the C2 paper.

Extends the existing multi-country sweep (``replay_country_sweep.py``)
with a per-cell *destination grid* dimension: a T5-eligible job carries
a non-empty ``spatial_clause`` (the set of grids it may run on), and
the dispatcher routes each such job to whichever grid in the clause
is cleanest at dispatch time, charging the inter-site data-egress
emissions against the IT-side savings.

Sweep dimensions
----------------
  home_grid    : SE, FR, CH, IT, DE, PL
  mw_scale     : 1, 10, 50
  mechanism    : none, M0..M3, M-Spatial   (the new C2 mechanism)
  egress_regime: low (0.5x table), mid (1.0x), high (2.0x)
  seed         : 8 Monte-Carlo seeds

Output (under ``--output-dir``):
  spatial_sweep.csv               one row per (home_grid, mw,
                                  mechanism, egress_regime, seed)
  SPATIAL_SUMMARY.csv             mean per cell with CIs
  RUN_MANIFEST.json               git SHA + command line + wall time
  cells/<cell-id>.json            per-cell checkpoint (resumption)

This is the v0.1 shell: the dispatcher integration is partial (it
computes the *routing decision* per cell using the cleanest-grid
selector, but does not yet feed back into a multi-grid f-SLA replay).
The C2 paper's P1 phase upgrades this driver to invoke the existing
``replay_proact_opt_pue`` per destination grid and aggregate.
"""
from __future__ import annotations

import argparse
import json
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "m100"))

from scheduler.spatial_routing import (  # noqa: E402
    SpatialClause, pick_cleanest_grid,
    assign_t5_spatial_eligibility,
)
from scheduler.egress_cost import (  # noqa: E402
    load_egress_emissions, egress_emissions_g_co2,
)
from scheduler.fsla import T_SPATIAL  # noqa: E402

# Sibling import: the country-sweep driver already exposes load_ci /
# load_jobs and the per-country CI table loader.
from inject_fsla_prior import load_jobs, load_ci  # noqa: E402


GRID_CODES = ("SE", "CH", "FR", "IT", "DE", "PL")


def _ci_at_each_grid_now(
    ci_tables: dict[str, pd.DataFrame],
    t_now: pd.Timestamp,
) -> dict[str, float]:
    """Sample the per-grid CI at one wall-clock instant.  Used by the
    cleanest-grid selector; the actual time-aligned per-job CI is the
    job of the downstream dispatcher.  Defaults to the column-mean
    when ``t_now`` is outside the table's index.
    """
    out: dict[str, float] = {}
    for code, df in ci_tables.items():
        if df is None or df.empty:
            continue
        col = "carbon_intensity_gCO2eq_per_kWh"
        if t_now in df.index:
            out[code] = float(df.loc[t_now, col])
        else:
            out[code] = float(df[col].mean())
    return out


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="replay_spatial_sweep",
                                  allow_abbrev=False)
    # Resolve config defaults against the gridpilot/ root (ROOT) so the
    # driver runs from either the workspace root or the gridpilot/
    # directory.  The other m100 drivers get away with relative paths
    # because run_all_experiments.sh does ``cd gridpilot/`` first; this
    # one is also invoked standalone for the C2 paper.
    p.add_argument("--jobs", type=Path, required=True)
    p.add_argument("--grids-dir", type=Path,
                    default=ROOT / "configs" / "grids")
    p.add_argument("--grids", type=str, default=",".join(GRID_CODES),
                    help="Comma-separated grid codes to include "
                         "(default: all six bundled grids).")
    p.add_argument("--egress-yaml", type=Path,
                    default=ROOT / "configs" / "network" / "egress_emissions.yaml")
    p.add_argument("--mw", type=str, default="1,10,50")
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--seed-base", type=int, default=20260517)
    p.add_argument("--egress-regimes", type=str, default="0.5,1.0,2.0",
                    help="Comma-separated multipliers applied to the "
                         "loaded egress-emissions table; the C2 H2 "
                         "egress-threshold sweep uses these.")
    p.add_argument("--t5-fraction", type=float, default=0.10,
                    help="Fraction of jobs marked T5-eligible.")
    p.add_argument("--transfer-size-gb", type=float, default=10.0,
                    help="Per-job data state in GB charged on transfer.")
    p.add_argument("--output-dir", type=Path,
                    default=Path("data/m100/spatial_sweep"))
    p.add_argument("--force", action="store_true")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args(argv)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def main(argv=None) -> int:
    args = parse_args(argv)
    t0 = time.time()
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    sweep_csv = out_dir / "spatial_sweep.csv"
    if sweep_csv.exists() and not args.force:
        print(f"ERROR: {sweep_csv} already exists. Use --force.",
              file=sys.stderr)
        return 2

    grid_codes = [g.strip().upper() for g in args.grids.split(",") if g.strip()]
    mws = [float(s) for s in args.mw.split(",") if s.strip()]
    seeds = [args.seed_base + k for k in range(args.seeds)]
    egress_regimes = [float(s) for s in args.egress_regimes.split(",")
                       if s.strip()]

    # Per-grid CI tables ---------------------------------------------
    ci_tables: dict[str, pd.DataFrame] = {}
    for code in grid_codes:
        yaml_path = args.grids_dir / f"{code}.yaml"
        if yaml_path.exists():
            ci_tables[code] = load_ci(yaml_path)
        else:
            print(f"[spatial-sweep] WARN: missing {yaml_path}; skipping {code}",
                  file=sys.stderr)

    # Egress-emissions table ----------------------------------------
    egress_table_base = load_egress_emissions(args.egress_yaml)
    if not args.quiet:
        print(f"[spatial-sweep] loaded {len(egress_table_base)} egress pairs "
              f"from {args.egress_yaml}", flush=True)

    jobs_df = load_jobs(args.jobs)
    if not args.quiet:
        print(f"[spatial-sweep] {len(grid_codes)} grids x {len(mws)} MW x "
              f"{len(egress_regimes)} egress regimes x {len(seeds)} seeds",
              flush=True)

    # Anchor "now" at the trace's median submit time.  This is a v0.1
    # simplification: the full sweep evaluates the cleanest-grid
    # selector hour-by-hour using each job's actual dispatch time.
    submit_col = "submit_time_epoch"
    t_now = pd.Timestamp(
        float(jobs_df[submit_col].median()), unit="s",
    ) if submit_col in jobs_df.columns else pd.Timestamp.now()

    rows: list[dict] = []
    for home in grid_codes:
        for mw in mws:
            for regime in egress_regimes:
                # Scale the egress table per regime
                egress_table = {k: v * regime
                                 for k, v in egress_table_base.items()}
                for s in seeds:
                    rng = np.random.default_rng(s)
                    # Mark T5-eligible jobs and assign per-job spatial
                    # clauses (default: all six grids minus the home).
                    jobs_t5 = assign_t5_spatial_eligibility(
                        jobs_df, rng, fraction=args.t5_fraction,
                        default_clause=tuple(grid_codes),
                    )
                    # For each T5-eligible job, pick its cleanest
                    # destination grid using the egress-aware selector.
                    ci_now = _ci_at_each_grid_now(ci_tables, t_now)
                    if not ci_now:
                        continue
                    dest_counts: dict[str, int] = {g: 0 for g in grid_codes}
                    egress_total_g = 0.0
                    for _, row in jobs_t5[jobs_t5["is_spatial_eligible"]].iterrows():
                        clause_codes = tuple(
                            c for c in str(row["spatial_clause"]).split(",")
                            if c
                        )
                        if not clause_codes:
                            continue
                        clause = SpatialClause(
                            acceptable_grids=clause_codes,
                            transfer_size_gb=args.transfer_size_gb,
                            home_grid=home,
                        )
                        dest, ci_dest = pick_cleanest_grid(
                            clause, ci_now, egress_emissions=egress_table,
                        )
                        dest_counts[dest] = dest_counts.get(dest, 0) + 1
                        egress_total_g += egress_emissions_g_co2(
                            egress_table, home, dest, args.transfer_size_gb,
                        )
                    rows.append({
                        "home_grid": home,
                        "mw": mw,
                        "egress_regime": regime,
                        "seed": s,
                        "n_t5_jobs": int(jobs_t5["is_spatial_eligible"].sum()),
                        **{f"dest_{g}": int(c) for g, c in dest_counts.items()},
                        "egress_total_g_co2": float(egress_total_g),
                    })

    summary = pd.DataFrame(rows)
    summary.to_csv(sweep_csv, index=False, float_format="%.4f")
    (out_dir / "RUN_MANIFEST.json").write_text(json.dumps({
        "git_sha": _git_sha(),
        "command_line": " ".join(sys.argv),
        "args": {k: str(v) for k, v in vars(args).items()},
        "python_version": sys.version,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "wall_time_s": round(time.time() - t0, 1),
        "n_cells": len(rows),
    }, indent=2))
    if not args.quiet:
        print(f"[spatial-sweep] wrote {sweep_csv} ({len(rows)} cells, "
              f"{time.time()-t0:.1f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
