#!/usr/bin/env python3
"""
scripts/multicountry/replay_country_sweep.py
============================================
Multi-country × multi-MW × mechanism sweep that produces the headline
PECS-paper Finding 5 (f-SLA CFE-lift across European grids) and the
WHPC-paper PUE-aware controller comparison (Finding A1).

Sweep dimensions
----------------
  country    : SE, FR, CH, IT, DE, PL  (CI from low to high)
  mw_scale   : 1, 10, 50               (MW of IT power)
  layer      : `fsla`     → mechanism ∈ {none, M0, M1, M2, M3}, scheduler = EASY-FCFS
               `pue`      → mechanism ∈ {none, GridPilot-PUE},
                            scheduler = the PUE-aware variant
               (each layer's CSV row carries the same headline columns)
  seed       : N Monte-Carlo seeds (default 8)

Output (under ``--output-dir``):

  country_sweep.csv        one row per (country, mw, layer, mechanism, seed)
  COUNTRY_SUMMARY.json     mean per (country, mw, layer, mechanism) with CIs
  RUN_MANIFEST.json        git SHA + command line + wall time
  cells/<cell-id>.json     per-cell checkpoint (resumption); disable with
                           ``--no-cell-cache`` if you do not want partial-run
                           recovery.  A killed sweep can be resumed by simply
                           re-running the same command --- existing cell files
                           are re-read instead of recomputed.

Headline columns per row:

  cfe_pct, cfe_lift_pp_vs_none,
  co2_tonnes_y (annualised), co2_avoided_tonnes_y,
  delta_facility_pp (== 0 in the `fsla` layer; populated in `pue`),
  jain_fairness, p95_slowdown

The CFE-lift question the paper asks is: *given a fixed-tier set and a
fixed cluster size, how does f-SLA's CFE lift differ across CI grids?*
The same CSV also lets the WHPC paper answer: *how does the PUE-aware
control lift facility-CO2 reduction across CI grids?*

A literature-anchored stub is provided in
``seed_country_sweep_stub.py`` for editor-pass paper rebuilds.

Example
-------
::

    PYTHONPATH=src python scripts/multicountry/replay_country_sweep.py \\
        --jobs    data/traces/m100_real_jobs.parquet \\
        --grids   configs/grids/SE.yaml,configs/grids/FR.yaml,...,configs/grids/PL.yaml \\
        --mw      1,10,50 \\
        --seeds   8 --workers 4 \\
        --output-dir data/m100/country_sweep/
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
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "m100"))

from scheduler.scheduler_pue_aware import (  # noqa: E402
    replay_proact_opt_pue, replay_fcfs_pue,
)
from scheduler.fsla import sample_prior, assign_tiers, T_RIGID  # noqa: E402
from scheduler.fsla_mechanisms import build_mechanism, AntiGamingMechanism  # noqa: E402
from scheduler.ai_baseline import AIBaselinePredictor  # noqa: E402
from scheduler.swf import jain_fairness, per_user_utility  # noqa: E402
from cooling.cooling_pue_model import calibrate_to_design_pue  # noqa: E402

from inject_fsla_prior import (  # noqa: E402
    load_jobs, load_ci, load_t_amb, align_jobs_to_ci,
)

NODE_POWER_KW = 1.5  # M100-class GPU node


def _nodes_for_mw(mw: float, node_power_kw: float = NODE_POWER_KW) -> int:
    """Cluster node-count for the requested IT-power scale."""
    return max(1, int(round(mw * 1000.0 / node_power_kw)))


def _cfe_pct(result: dict) -> float:
    """Per-country-normalised CFE: energy-weighted average of
    (1 - CI_norm(t)) where CI_norm is the grid's own [min, max].

    NOTE: this metric saturates around 50 % for a blind FCFS
    dispatcher on a 24 h diurnal cycle and has limited discriminative
    power across grids.  ``_cfe_abs_pct`` below is the absolute
    counterpart (energy fraction under a fixed CI threshold) that we
    additionally emit so that downstream figures can choose the more
    informative metric.
    """
    e = float(result.get("energy_kwh", 0.0))
    g = float(result.get("green_kwh", 0.0))
    if e <= 0:
        return 0.0
    return float(np.clip(100.0 * g / e, 0.0, 100.0))


# Absolute CI threshold (g CO2eq / kWh) below which an hour counts as
# "clean".  150 g/kWh sits between the EU 2030 grid-average target
# (~150) and the cleanest European grids' present-day mean (~30).
# Hours below this threshold are a tiny fraction in Poland (CI 612)
# and most hours in Sweden (CI 11), so the absolute metric carries
# strong cross-grid signal.
CFE_ABS_THRESHOLD_G = 150.0


def _cfe_abs_pct(result: dict, ci_df: pd.DataFrame) -> float:
    """Absolute CFE: percentage of completed-job energy that ran
    while grid CI was below CFE_ABS_THRESHOLD_G.

    This is the metric a Scope-2 disclosure would actually report.
    It does not saturate, it ranks grids by their true cleanliness,
    and it has strictly more dynamic range than ``_cfe_pct``.
    """
    completed = result.get("completed", [])
    if not completed:
        return 0.0
    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_vals = ci.values.astype(float)
    ci_ts = np.array([t.timestamp() for t in pd.to_datetime(ci.index)])
    # Approximate per-job CI by the grid CI at the job's start time.
    clean_kwh = 0.0
    total_kwh = 0.0
    for j in completed:
        start = j.get("start")
        if start is None:
            continue
        idx = int(np.clip(np.searchsorted(ci_ts, start, side="right") - 1,
                          0, len(ci_vals) - 1))
        ci_here = float(ci_vals[idx])
        e_job = (float(j.get("nodes", 1))
                 * float(j.get("runtime", 0.0))
                 / 3600.0)   # nodes-hours, proxy for kWh at unit power
        total_kwh += e_job
        if ci_here <= CFE_ABS_THRESHOLD_G:
            clean_kwh += e_job
    if total_kwh <= 0:
        return 0.0
    return float(np.clip(100.0 * clean_kwh / total_kwh, 0.0, 100.0))


def _ci_weighted_mean_g(result: dict, ci_df: pd.DataFrame) -> float:
    """Energy-weighted average grid CI (g CO2eq/kWh) experienced by
    the completed jobs.

    This is the *effective* mean grid CI the cluster ran on.  Unlike
    the normalised CFE it ranks grids by their true cleanliness (SE
    ~11, PL ~612), and unlike the absolute-threshold CFE it has
    continuous dynamic range so even small lifts register.  The
    f-SLA lift is reported as ``baseline_ci - fsla_ci`` --- a
    positive number means the contract shifted compute toward
    cleaner hours.
    """
    completed = result.get("completed", [])
    if not completed:
        return 0.0
    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_vals = ci.values.astype(float)
    ci_ts = np.array([t.timestamp() for t in pd.to_datetime(ci.index)])
    num = 0.0
    den = 0.0
    for j in completed:
        start = j.get("start")
        if start is None:
            continue
        idx = int(np.clip(np.searchsorted(ci_ts, start, side="right") - 1,
                          0, len(ci_vals) - 1))
        ci_here = float(ci_vals[idx])
        e_job = (float(j.get("nodes", 1))
                 * float(j.get("runtime", 0.0))
                 / 3600.0)
        num += ci_here * e_job
        den += e_job
    if den <= 0:
        return 0.0
    return float(num / den)


def _attach_user_column(jobs_df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Synthetic Zipf-ian user attribution; matches the policy-matrix driver."""
    if "user" in jobs_df.columns:
        return jobs_df
    user_idx = rng.zipf(1.2, size=len(jobs_df))
    user_idx = np.clip(user_idx, 1, 50)
    return jobs_df.assign(user=[f"u{idx:03d}" for idx in user_idx])


def _scale_trace_to_cluster(jobs_df: pd.DataFrame, target_nodes: int,
                              ref_nodes: int = 980) -> pd.DataFrame:
    """Scale the M100 trace's per-job node counts so the busy-hour load
    matches the target cluster size proportionally.  This is the cheapest
    way to project the M100 workload onto a 1/10/50 MW cluster without
    re-instantiating a workload generator.
    """
    if ref_nodes <= 0:
        return jobs_df
    scale = target_nodes / ref_nodes
    out = jobs_df.copy()
    out["num_nodes_alloc"] = np.maximum(
        1, np.round(out["num_nodes_alloc"] * scale).astype(int)
    )
    return out


def _build_ai_predictor(jobs_df: pd.DataFrame, rng: np.random.Generator) -> AIBaselinePredictor:
    pi = sample_prior(rng=rng)
    historical, _ = assign_tiers(jobs_df, pi, rng=rng, length_conditioned=True)
    return AIBaselinePredictor(min_history=5).fit(historical)


# ─────────────────────────────────────────────────────────────────────
# Per-cell runner
# ─────────────────────────────────────────────────────────────────────
def run_one_cell(
    country_yaml: Path,
    mw: float,
    layer: str,            # "fsla" or "pue"
    mechanism: str,        # "none", "M0".."M3" for fsla; "none", "GridPilot-PUE" for pue
    seed: int,
    jobs_df: pd.DataFrame,
    cooling_params,
    scheduler_kwargs_base: dict,
) -> dict:
    rng = np.random.default_rng(seed)
    ci_df = load_ci(country_yaml)
    jobs_local = align_jobs_to_ci(jobs_df, ci_df)
    jobs_local = _attach_user_column(jobs_local, rng)
    nodes = _nodes_for_mw(mw)
    jobs_local = _scale_trace_to_cluster(jobs_local, nodes)
    t_amb = pd.Series(20.0, index=ci_df.index, name="t_amb_c")

    sched_kwargs = dict(scheduler_kwargs_base, total_nodes=nodes)

    # ── Tier assignment + replay
    if layer == "fsla":
        if mechanism == "none":
            jobs_with_tiers = jobs_local.copy()
            jobs_with_tiers["tier"] = T_RIGID
            jobs_with_tiers["d_max_hours"] = 0
            jobs_with_tiers["slowdown_max"] = 1.0
            jobs_with_tiers["service_credit_h"] = 0.0
            jobs_with_tiers["checkpoint_bonus"] = 0.0
        else:
            ai = _build_ai_predictor(jobs_local, rng)
            mech: AntiGamingMechanism = build_mechanism(mechanism)
            jobs_with_tiers = mech.assign_tiers(jobs_local, rng=rng, ai_predictor=ai)
        # C2 forward-compat schema columns: the spatial-routing and
        # workflow-DAG drivers expect these columns to exist; we add
        # them here as no-op defaults so PECS v1.0 replays still
        # produce identical CSV rows (the dispatcher ignores these
        # columns unless the C2-paper spatial / workflow drivers are
        # invoked).
        if "is_spatial_eligible" not in jobs_with_tiers.columns:
            jobs_with_tiers["is_spatial_eligible"] = False
        if "spatial_clause" not in jobs_with_tiers.columns:
            jobs_with_tiers["spatial_clause"] = ""
        if "dag_node_id" not in jobs_with_tiers.columns:
            jobs_with_tiers["dag_node_id"] = -1
        if "dag_parent_id" not in jobs_with_tiers.columns:
            jobs_with_tiers["dag_parent_id"] = -1

        # Mark Tier 4 (Elastic) jobs deterministically elastic so the
        # dispatcher scales their replicas with the CI signal.  This
        # is the CarbonScaler-style burst mechanism that Hanafy et al.
        # (2023) report as the highest-impact carbon-aware lever in
        # the literature.
        jobs_with_tiers["is_elastic"] = (
            jobs_with_tiers.get("tier", T_RIGID) == 4   # T_ELASTIC
        ).astype(bool)
        # EASY-FCFS replay with the CI-bias signal turned ON
        # (pue_weight=1.0) so the scheduler actually uses the f-SLA
        # tier windows for CI-aware deferral; lowering
        # short_job_threshold_s from the default 600 to 60 makes the
        # bulk of the M100 trace deferral-eligible (the PM100 dataset
        # is dominated by sub-10-minute jobs, which the default
        # exclusion silently disabled).  Both baseline and treatment
        # share the same scheduler config; the only thing that
        # differs across mechanisms is the per-job d_max_hours.
        result = replay_proact_opt_pue(
            jobs_with_tiers, ci_df, t_amb,
            cooling_params=cooling_params,
            max_delay_h=int(max(1, jobs_with_tiers["d_max_hours"].max())),
            pue_weight=1.0,
            short_job_threshold_s=60,
            enable_backfilling=True,
            seed=seed,
            **sched_kwargs,
        )
    elif layer == "pue":
        if mechanism == "none":
            # FCFS+PUE-accounted baseline (uses the PUE-aware *accounting*
            # but FCFS dispatch).  No deferral, no power capping.
            result = replay_fcfs_pue(
                jobs_local, ci_df, t_amb,
                cooling_params=cooling_params, seed=seed, **sched_kwargs,
            )
        elif mechanism == "GridPilot-PUE":
            jobs_with_tiers = jobs_local.copy()
            jobs_with_tiers["d_max_hours"] = 24
            result = replay_proact_opt_pue(
                jobs_with_tiers, ci_df, t_amb,
                cooling_params=cooling_params,
                max_delay_h=24, pue_weight=0.5,
                enable_backfilling=True, seed=seed, **sched_kwargs,
            )
        else:
            raise ValueError(f"layer 'pue' supports only none|GridPilot-PUE; got {mechanism}")
    else:
        raise ValueError(f"unknown layer {layer!r}; expected 'fsla' or 'pue'")

    # ── Aggregate metrics
    if "user" in jobs_local.columns:
        wait_by_user: dict[str, list[float]] = {}
        completed = result.get("completed", [])
        users = jobs_local["user"].astype(str).tolist()
        n_users = len(users)
        # Positional alignment between jobs_local and result["completed"]
        # (the dispatcher preserves submission order).  Use enumerate so
        # the lookup is O(N), NOT O(N^2) --- the previous .index(j) call
        # made the per-cell user-recovery quadratic in the trace size,
        # which on a 3 000-job M100 trace inflated each cell by ~9 M ops
        # and drove the 1 008-cell sweep into multi-hour wall times.
        for i, j in enumerate(completed):
            u = users[i] if i < n_users else "anonymous"
            wait_by_user.setdefault(u, []).append(
                max(0.0, (j.get("start", 0) - j.get("submit", 0)))
            )
        mean_inv_wait = [1.0 / max(np.mean(v), 1.0) for v in wait_by_user.values()] or [1.0]
    else:
        mean_inv_wait = [1.0]

    slowdowns = result.get("slowdowns", np.array([1.0]))
    sim_seconds = max(1.0, slowdowns.size and len(slowdowns) or 1)  # not used directly
    energy_kwh = float(result.get("energy_kwh", 0.0))
    co2_g_it = float(result.get("co2_g", 0.0))
    co2_g_fac = float(result.get("facility_co2_g", 0.0))
    # Annualise: the M100 trace is ~1 month; scale to 365 d.
    annualisation = 365.0 / 30.0
    co2_t_y = co2_g_it * annualisation / 1.0e6  # g → t

    return {
        "country": country_yaml.stem,
        "mw": mw,
        "nodes": int(_nodes_for_mw(mw)),
        "layer": layer,
        "mechanism": mechanism,
        "seed": seed,
        "n_jobs": int(result.get("n", 0)),
        "energy_kwh": energy_kwh,
        "co2_g_it": co2_g_it,
        "co2_g_facility": co2_g_fac,
        "co2_tonnes_y": co2_t_y,
        "cfe_pct":          _cfe_pct(result),
        "cfe_abs_pct":      _cfe_abs_pct(result, ci_df),
        "ci_weighted_mean": _ci_weighted_mean_g(result, ci_df),
        "p50_slowdown":     float(np.percentile(slowdowns, 50)),
        "p95_slowdown": float(np.percentile(slowdowns, 95)),
        "p99_slowdown": float(np.percentile(slowdowns, 99)),
        "avg_pue": float(result.get("avg_pue", 1.20)),
        "jain_fairness": jain_fairness(mean_inv_wait),
    }


def _compute_deltas(headline: pd.DataFrame) -> pd.DataFrame:
    """Add ``cfe_lift_pp_vs_none``, ``co2_avoided_tonnes_y``, and
    ``delta_facility_pp`` columns by joining each row against its
    (country, mw, layer, mechanism='none') baseline.
    """
    base = (
        headline.query("mechanism == 'none'")
            .groupby(["country", "mw", "layer"])
            .agg(base_cfe=("cfe_pct", "mean"),
                  base_cfe_abs=("cfe_abs_pct", "mean"),
                  base_ciwm=("ci_weighted_mean", "mean"),
                  base_co2_t=("co2_tonnes_y", "mean"),
                  base_co2_fac=("co2_g_facility", "mean"))
            .reset_index()
    )
    out = headline.merge(base, on=["country", "mw", "layer"], how="left")
    out["cfe_lift_pp_vs_none"]     = out["cfe_pct"]     - out["base_cfe"]
    out["cfe_abs_lift_pp_vs_none"] = out["cfe_abs_pct"] - out["base_cfe_abs"]
    # CI-weighted mean lift: baseline_ci - fsla_ci  (positive means
    # the contract shifted compute toward cleaner hours, in g/kWh).
    out["ci_weighted_lift_g"]      = out["base_ciwm"]   - out["ci_weighted_mean"]
    out["co2_avoided_tonnes_y"]    = out["base_co2_t"]  - out["co2_tonnes_y"]
    out["delta_facility_pp"] = (
        (out["base_co2_fac"] - out["co2_g_facility"]) / out["base_co2_fac"].replace(0, np.nan)
    ) * 100.0
    out["delta_facility_pp"] = out["delta_facility_pp"].fillna(0.0)
    return out.drop(columns=["base_cfe", "base_cfe_abs", "base_ciwm",
                              "base_co2_t", "base_co2_fac"])


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────
def parse_args(argv=None):
    # allow_abbrev=False so that '--pue' is NOT silently expanded to
    # '--pue-yaml' or '--pue-mechanisms' (the two flags share a prefix).
    p = argparse.ArgumentParser(prog="replay_country_sweep",
                                  allow_abbrev=False)
    p.add_argument("--jobs", type=Path, required=True)
    p.add_argument("--grids", type=str,
                    default="configs/grids/SE.yaml,configs/grids/FR.yaml,"
                            "configs/grids/CH.yaml,configs/grids/IT.yaml,"
                            "configs/grids/DE.yaml,configs/grids/PL.yaml")
    p.add_argument("--mw", type=str, default="1,10,50")
    # f-SLA mechanism plug-ins for the contract-side replay
    p.add_argument("--fsla-mechanisms", "--mechanisms", dest="fsla_mechanisms",
                    type=str, default="none,M0,M1,M2,M3",
                    help="comma-separated list of f-SLA mechanisms (default: none,M0,M1,M2,M3)")
    # GridPilot-PUE comparators for the controller-side replay
    p.add_argument("--pue-mechanisms", dest="pue_mechanisms",
                    type=str, default="none,GridPilot-PUE",
                    help="comma-separated list of PUE-layer mechanisms (default: none,GridPilot-PUE)")
    # Cooling-model anchor file
    p.add_argument("--pue", "--pue-yaml", dest="pue_yaml", type=Path,
                    default=Path("raps/config/marconi100.yaml"),
                    help="path to the RAPS cooling-model YAML (default: raps/config/marconi100.yaml)")
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--seed-base", type=int, default=20260517)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--output-dir", type=Path,
                    default=Path("data/m100/country_sweep"))
    p.add_argument("--time-step", type=int, default=3600)
    p.add_argument("--node-power-kw", type=float, default=NODE_POWER_KW)
    p.add_argument("--force", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument(
        "--no-cell-cache", action="store_true",
        help="Disable per-cell JSON checkpointing (default: cells are "
             "checkpointed under <output-dir>/cells/ so a killed run can "
             "resume without re-doing finished cells).",
    )
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
    headline_csv = out_dir / "country_sweep.csv"
    if headline_csv.exists() and not args.force:
        print(f"ERROR: {headline_csv} already exists. Use --force.", file=sys.stderr)
        return 2

    grids = [Path(p.strip()) for p in args.grids.split(",") if p.strip()]
    mws = [float(s) for s in args.mw.split(",") if s.strip()]
    fsla_mechs = [m.strip() for m in args.fsla_mechanisms.split(",") if m.strip()]
    pue_mechs  = [m.strip() for m in args.pue_mechanisms.split(",") if m.strip()]
    seeds = [args.seed_base + k for k in range(args.seeds)]

    jobs_df = load_jobs(args.jobs)
    # PUE cooling params (used for facility-CO2 accounting in both layers)
    if args.pue_yaml.exists():
        # Re-use inject_fsla_prior's loader to keep the calibration path
        # consistent with the §3 reproducibility commands.
        from inject_fsla_prior import load_pue_params
        cooling_params = load_pue_params(args.pue_yaml)
    else:
        cooling_params = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)

    scheduler_kwargs_base = dict(
        node_power_kw=args.node_power_kw,
        time_step=args.time_step,
    )

    cells = []
    for grid in grids:
        for mw in mws:
            for s in seeds:
                for m in fsla_mechs:
                    cells.append((grid, mw, "fsla", m, s))
                for m in pue_mechs:
                    cells.append((grid, mw, "pue", m, s))

    if not args.quiet:
        print(f"[country-sweep] {len(grids)} grids × {len(mws)} MW × "
              f"({len(fsla_mechs)} fsla + {len(pue_mechs)} pue) × {len(seeds)} seeds "
              f"= {len(cells)} cells; workers={args.workers}", flush=True)

    # Per-cell checkpoint directory.  Each completed cell writes its
    # row to <output-dir>/cells/<cell-id>.json so a killed sweep can
    # resume by skipping the cell files that already exist.  Set
    # --no-cell-cache to disable.
    cells_dir = out_dir / "cells"
    if not args.no_cell_cache:
        cells_dir.mkdir(parents=True, exist_ok=True)

    def _cell_id(g: Path, mw: float, layer: str, mech: str, s: int) -> str:
        # Stable, filesystem-safe id; matches the (country, mw, layer,
        # mechanism, seed) tuple that uniquely identifies a sweep row.
        return f"{g.stem}_{int(mw):03d}MW_{layer}_{mech}_{s}"

    def _cell_path(cid: str) -> Path:
        return cells_dir / f"{cid}.json"

    # Build the work list, partitioning into already-done and to-do.
    # A cached row must contain every column the downstream aggregator
    # (``_compute_deltas`` + ``COUNTRY_SUMMARY`` build) reads off it ---
    # otherwise a stale cell file from an older schema would silently
    # poison the final CSV.  Files that fail either the JSON parse or
    # the schema check are deleted and re-computed.
    REQUIRED_KEYS = {
        "country", "mw", "layer", "mechanism", "seed",
        "cfe_pct", "co2_g_facility", "co2_tonnes_y",
    }
    to_run = []
    cached_rows: list[dict] = []
    for cell in cells:
        g, mw, layer, mech, s = cell
        cid = _cell_id(g, mw, layer, mech, s)
        cp = _cell_path(cid)
        if (not args.no_cell_cache) and cp.exists():
            try:
                row = json.loads(cp.read_text())
                if not REQUIRED_KEYS.issubset(row):
                    raise ValueError("schema mismatch")
                cached_rows.append(row)
                continue
            except Exception:
                # Corrupt or stale-schema checkpoint; re-run this cell.
                cp.unlink(missing_ok=True)
        to_run.append((cid, cell))

    if not args.quiet and cached_rows:
        print(f"[country-sweep] resuming: {len(cached_rows)} cells from "
              f"{cells_dir} already on disk; {len(to_run)} to run",
              flush=True)

    def _json_default(o):
        # numpy scalars are not JSON-serialisable by default --- cast to
        # native Python primitives.  Without this, json.dumps fails on
        # e.g. numpy.float64 returned by .mean() / .percentile().
        if isinstance(o, np.generic):
            return o.item()
        raise TypeError(f"not JSON-serialisable: {type(o).__name__}")

    def _persist(cid: str, row: dict) -> None:
        if args.no_cell_cache:
            return
        try:
            # Write to a sibling .tmp and rename, so a kill mid-write
            # never leaves a half-written JSON the resume path will trip on.
            tmp = _cell_path(cid).with_suffix(".json.tmp")
            tmp.write_text(json.dumps(row, default=_json_default))
            tmp.replace(_cell_path(cid))
        except Exception as exc:
            print(f"[country-sweep] WARN: failed to checkpoint {cid}: {exc}",
                  flush=True)

    rows: list[dict] = list(cached_rows)
    total = len(cells)
    if args.workers <= 1:
        for k, (cid, cell) in enumerate(to_run):
            g, mw, layer, mech, s = cell
            if not args.quiet:
                print(f"[country-sweep] {len(rows)+1}/{total}  {g.stem:<3} {mw:>4}MW "
                      f"{layer:<4} {mech:<14} seed={s}", flush=True)
            row = run_one_cell(g, mw, layer, mech, s, jobs_df,
                               cooling_params, scheduler_kwargs_base)
            _persist(cid, row)
            rows.append(row)
    else:
        # NOTE: submit ``run_one_cell`` directly (NOT a nested closure)
        # because ProcessPoolExecutor on macOS uses the ``spawn`` start
        # method, which can only pickle module-level callables.  A
        # local closure such as ``_exec`` triggers
        #   PicklingError: Can't pickle local object 'main.<locals>._exec'
        # at submit time.
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {}
            for cid, (g, mw, layer, mech, s) in to_run:
                fut = ex.submit(run_one_cell, g, mw, layer, mech, s,
                                jobs_df, cooling_params, scheduler_kwargs_base)
                futs[fut] = (cid, (g, mw, layer, mech, s))
            for k, fut in enumerate(as_completed(futs)):
                cid, (g, mw, layer, mech, s) = futs[fut]
                row = fut.result()
                _persist(cid, row)
                rows.append(row)
                if not args.quiet and (k % max(1, len(to_run) // 20) == 0
                                       or len(rows) == total):
                    print(f"[country-sweep] {len(rows)}/{total}  {g.stem:<3} "
                          f"{mw:>4}MW {layer:<4} {mech:<14} seed={s}",
                          flush=True)

    headline = _compute_deltas(pd.DataFrame(rows))
    headline.to_csv(headline_csv, index=False, float_format="%.4f")
    if not args.quiet:
        print(f"[country-sweep] wrote {headline_csv}", flush=True)

    # Summary JSON: mean per (country, mw, layer, mechanism)
    summary = (
        headline
            .groupby(["country", "mw", "layer", "mechanism"])
            .agg(cfe_pct_mean=("cfe_pct", "mean"),
                  cfe_lift_pp_mean=("cfe_lift_pp_vs_none", "mean"),
                  cfe_abs_pct_mean=("cfe_abs_pct", "mean"),
                  cfe_abs_lift_pp_mean=("cfe_abs_lift_pp_vs_none", "mean"),
                  ci_weighted_mean_g=("ci_weighted_mean", "mean"),
                  ci_weighted_lift_g_mean=("ci_weighted_lift_g", "mean"),
                  co2_avoided_t_y_mean=("co2_avoided_tonnes_y", "mean"),
                  delta_facility_pp_mean=("delta_facility_pp", "mean"),
                  jain_mean=("jain_fairness", "mean"),
                  p95_mean=("p95_slowdown", "mean"))
            .reset_index()
    )
    summary.to_csv(out_dir / "COUNTRY_SUMMARY.csv", index=False, float_format="%.4f")

    manifest = {
        "git_sha": _git_sha(),
        "command_line": " ".join(sys.argv),
        "args": {k: str(v) for k, v in vars(args).items()},
        "python_version": sys.version,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "wall_time_s": time.time() - t0,
    }
    (out_dir / "RUN_MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    if not args.quiet:
        print(f"[country-sweep] total wall time {time.time()-t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
