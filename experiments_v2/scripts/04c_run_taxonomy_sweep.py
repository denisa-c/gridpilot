#!/usr/bin/env python3
"""
experiments_v2/scripts/04c_run_taxonomy_sweep.py
=================================================
Phase 4e — taxonomy-classified f-SLA across 4 representative days × 6 countries.

The headline question: *"does the contract still help when the per-job
tier comes from a workload classifier (taxonomy) rather than a
synthetic Dirichlet prior?"*

For each (country, season, scheduler, seed) cell:
  - Pick the representative date for that season.
  - Load real ENTSO-E CI for that 48-h window (synth fallback).
  - Sub-sample the M100 trace to N jobs (default 1500) so the day's
    workload is realistic.
  - Classify every job via workload_taxonomy.classify_jobs() into one
    of {interactive, workflow_coupled, elastic_ai, batch_parallel,
    geo_shiftable, large_hpc}.  Each class maps to a tier per
    Fig. 1 of the paper.
  - Run scheduler:
      baselines: v2 fcfs / easy_fcfs / saf with the same workload
      treatment: fsla_carbon_aware (v2-native argmin-CI deferral)
  - Compute v2 metrics via shared accounting.
  - Also emit per-class breakdown columns so the figure can show
    which workload class contributes most to the lift.

Cells: 4 seasons × 6 countries × 4 schedulers × 4 seeds = 384.

Outputs:
  data/taxonomy_sweep/cells/<cell_id>.json
  data/taxonomy_sweep/taxonomy_sweep.csv
  data/taxonomy_sweep/TAXONOMY_SUMMARY.csv
  data/taxonomy_sweep/TAXONOMY_MIX.csv         (one row per class)
  data/taxonomy_sweep/RUN_MANIFEST.json
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
    fcfs, easy_fcfs, saf, fsla_carbon_aware,
    run_metrics,
)
from workload_taxonomy import (  # type: ignore[import-not-found]
    classify_jobs, assign_tiers_from_taxonomy,
    assign_tiers_dirichlet_per_class,
    summarise_taxonomy_mix,
    CLASS_ORDER, CLASS_TO_TIER,
)
from replay_country_sweep import (  # type: ignore[import-not-found]
    _nodes_for_mw,
)

GRIDPILOT  = ROOT / "gridpilot"
GRIDS_DIR  = GRIDPILOT / "configs" / "grids"
PUE_RAPS   = GRIDPILOT / "raps" / "config" / "marconi100.yaml"
ENTSOE_DIR = GRIDPILOT / "data" / "ci" / "entsoe"
JOBS_EXT   = GRIDPILOT / "data" / "traces" / "m100_real_jobs_extended.parquet"
JOBS_JAN   = GRIDPILOT / "data" / "traces" / "m100_real_jobs.parquet"

DEFAULT_COUNTRIES = ["SE", "CH", "FR", "IT", "DE", "PL"]
DEFAULT_SEEDS = 4
DEFAULT_MW = 10
DEFAULT_JOBS_PER_DAY = 1500
DEFAULT_DAYS_PER_WINDOW = 7        # week-long replays (v2 paper default)
CFE_REF_CI_G = 800.0

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
}
ALL_LAYERS = list(BASELINE_FNS.keys()) + ["fsla_taxonomy"]


# ─────────────────────────────────────────────────────────────────────
# CI loading (mirrors 04b)
# ─────────────────────────────────────────────────────────────────────

def _load_entsoe_window(country: str, anchor: datetime,
                        window_hours: int) -> Optional[pd.DataFrame]:
    """Slice a ``window_hours``-long CI + CFE series starting 24 h
    BEFORE the anchor and running forward.  Returns both columns
    (``carbon_intensity_gCO2eq_per_kWh`` and ``carbon_free_fraction``)
    when present in the parquet, so accounting + scheduler can use
    the canonical CFE-share formula directly.  Legacy parquets that
    carry only CI still load; the scheduler then falls back to its
    argmin-CI proxy.

    The asymmetric window (24 h pre-trace + the trace + 7 d T3 tail)
    keeps every candidate deferral hour inside the CI series so the
    scheduler's argmax can compare real values rather than the median
    pad."""
    p = ENTSOE_DIR / f"{country}_hourly.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if "carbon_intensity_gCO2eq_per_kWh" not in df.columns:
        return None
    if "timestamp" in df.columns:
        df = df.set_index("timestamp")
    df.index = pd.to_datetime(df.index, utc=True)
    start = anchor - timedelta(hours=24)
    end   = start + timedelta(hours=window_hours)
    win = df.loc[(df.index >= start) & (df.index < end)]
    if len(win) < window_hours // 2:
        return None
    keep = [c for c in ("carbon_intensity_gCO2eq_per_kWh",
                         "carbon_free_fraction") if c in win.columns]
    return win[keep]


def _synth_ci_window(country: str, anchor: datetime,
                     window_hours: int) -> pd.DataFrame:
    """Load v1's per-country synth and re-index to the requested window.
    v2.1: amplified diurnal + seasonal so the dispatcher has real
    structure to exploit when ENTSO-E is unavailable."""
    from replay_country_sweep import load_ci as v1_load_ci  # type: ignore[import-not-found]
    yaml_path = GRIDS_DIR / f"{country}.yaml"
    ci_df = v1_load_ci(yaml_path)
    if len(ci_df) < window_hours:
        n_tiles = (window_hours // len(ci_df)) + 1
        tiled = pd.concat([ci_df] * n_tiles, ignore_index=False)
    else:
        tiled = ci_df
    src = tiled.iloc[:window_hours].copy()
    # Asymmetric window: 24 h pre-trace + the trace itself + a T3 tail.
    # Matches _load_entsoe_window so synth and real CI cover the same
    # epoch range; the scheduler's argmin-CI deferral then has a defined
    # CI for every candidate hour.
    new_idx = pd.date_range(
        start=anchor - timedelta(hours=24),
        periods=len(src), freq="h", tz="UTC",
    )
    src.index = new_idx
    # Season modifier (matches 04b).
    month = anchor.month
    season_mod = {
        "DE": {1: 1.40, 4: 1.00, 7: 0.65, 10: 1.10},
        "IT": {1: 1.40, 4: 1.00, 7: 0.65, 10: 1.10},
        "FR": {1: 1.15, 4: 1.00, 7: 0.85, 10: 1.05},
        "PL": {1: 1.10, 4: 1.00, 7: 0.90, 10: 1.05},
        "CH": {1: 1.10, 4: 1.00, 7: 0.92, 10: 1.00},
        "SE": {1: 1.05, 4: 1.00, 7: 0.95, 10: 1.00},
    }.get(country, {1: 1.0, 4: 1.0, 7: 1.0, 10: 1.0})
    mod = season_mod.get(month, 1.0)
    src["carbon_intensity_gCO2eq_per_kWh"] = (
        src["carbon_intensity_gCO2eq_per_kWh"] * mod
    )
    # Amplified diurnal swing (real ENTSO-E shows 50–80 % swings).
    hours_since_anchor = np.arange(len(src))
    intraday_amp = {"SE": 0.05, "CH": 0.10, "FR": 0.15,
                    "IT": 0.30, "DE": 0.40, "PL": 0.20}.get(country, 0.25)
    intraday_factor = 1.0 + intraday_amp * np.sin(
        2 * np.pi * (hours_since_anchor - 6) / 24
    )
    src["carbon_intensity_gCO2eq_per_kWh"] = (
        src["carbon_intensity_gCO2eq_per_kWh"].values * intraday_factor
    )
    # Synthesise a matching carbon-free fraction column so accounting +
    # scheduler take the canonical CFE-share path on synth-fallback
    # cells too.  Proxy: max(0, 1 - CI / 800).  Real grids would carry
    # a generation-mix-derived column from the fetcher; this proxy
    # preserves ordering (cleaner hour <=> higher CFE) so the scheduler
    # picks the same hour either way.
    src["carbon_free_fraction"] = (
        (1.0 - src["carbon_intensity_gCO2eq_per_kWh"] / 800.0)
        .clip(lower=0.0, upper=1.0)
    )
    return src


def load_seasonal_ci(country: str, anchor: datetime, window_hours: int):
    real = _load_entsoe_window(country, anchor, window_hours)
    if real is not None and not real.empty:
        return real, "entsoe"
    return _synth_ci_window(country, anchor, window_hours), "synth"


# ─────────────────────────────────────────────────────────────────────
# Trace preparation
# ─────────────────────────────────────────────────────────────────────

def _build_window_trace(jobs_df: pd.DataFrame, anchor: datetime,
                         n_jobs_per_day: int, days: int,
                         rng: np.random.Generator,
                         *,
                         sampling: str = "energy_weighted",
                         ) -> pd.DataFrame:
    """Sub-sample ``(n_jobs_per_day * days)`` jobs and spread their
    submit times uniformly across the ``days``-day window starting at
    ``anchor``.  Runtimes preserved (clipped to 12 h) so the classifier
    sees real M100 distributions.

    sampling
    --------
    ``"uniform"`` — each job selected with equal probability.  This is
        the v2.0 default and is wrong for our purposes: the M100 trace
        has ~350 k jobs of which 97.7 % are sub-minute interactive but
        only 2 % of GPU·h.  A 10 500-job uniform sample picks ~5
        elastic_ai jobs (out of 167 in the population) — too few to
        get a stable per-class GPU·h estimate, so the headline lift
        becomes seed-dependent.

    ``"energy_weighted"`` — each job selected with probability
        proportional to ``num_nodes_alloc × run_time`` (≈ GPU·h).
        Sample is drawn *with replacement* so the per-class GPU·h
        distribution is an unbiased estimator of the population's
        — large elastic_ai / batch_parallel jobs may appear multiple
        times in the week, which is semantically equivalent to "this
        class arrives at higher rate", and each repeat gets a unique
        submit time via the np.linspace below so they don't collide
        on the cluster.  This is the v2.1 default and produces the
        order-of-magnitude lift the paper is after.
    """
    n_jobs = n_jobs_per_day * days
    if len(jobs_df) == 0:
        raise ValueError("empty jobs_df passed to _build_window_trace")
    # Coerce the two weighting columns BEFORE sampling so weights are
    # well-defined for every row (M100 sacct dumps occasionally carry
    # NaN runtimes or 0-node rows).
    rt = pd.to_numeric(jobs_df["run_time"], errors="coerce").fillna(60.0)
    rt = rt.clip(lower=60.0, upper=12 * 3600.0)
    nd = pd.to_numeric(jobs_df["num_nodes_alloc"],
                        errors="coerce").fillna(1.0).clip(lower=1.0)
    if sampling == "uniform" or len(jobs_df) <= n_jobs:
        if len(jobs_df) > n_jobs:
            idx = rng.choice(len(jobs_df), size=n_jobs, replace=False)
            sample = jobs_df.iloc[sorted(idx)].reset_index(drop=True)
        else:
            sample = jobs_df.copy()
    elif sampling == "energy_weighted":
        weights = (nd.values * rt.values).astype(float)
        # Guard against an all-zero weight vector (would NaN the p
        # argument); fall back to uniform if that ever happens.
        total = float(weights.sum())
        if total <= 0:
            idx = rng.choice(len(jobs_df), size=n_jobs, replace=False)
        else:
            p = weights / total
            # With replacement: gives an unbiased GPU.h distribution.
            # Per-job duplicates are semantically OK -- each gets a
            # unique submit time via the np.linspace below.
            idx = rng.choice(len(jobs_df), size=n_jobs, replace=True, p=p)
        sample = jobs_df.iloc[idx].reset_index(drop=True)
    else:
        raise ValueError(f"unknown sampling mode {sampling!r}")

    out = sample[["submit_time_epoch", "run_time", "num_nodes_alloc"]].copy()
    anchor_epoch = anchor.timestamp()
    window_s = days * 86400.0
    out["submit_time_epoch"] = (
        anchor_epoch + np.linspace(0, window_s, num=len(out), endpoint=False)
    )
    out["run_time"] = pd.to_numeric(out["run_time"], errors="coerce").clip(
        lower=60.0, upper=12 * 3600.0
    )
    out["num_nodes_alloc"] = pd.to_numeric(
        out["num_nodes_alloc"], errors="coerce"
    ).fillna(1).astype(int).clip(lower=1)
    return out


# ─────────────────────────────────────────────────────────────────────
# Cell runner
# ─────────────────────────────────────────────────────────────────────

def _cell_id(country, season, layer, seed):
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


def _per_class_breakdown_from_schedule(jobs_with_tiers: pd.DataFrame,
                                         schedule, ci_df: pd.DataFrame) -> dict:
    """Per-class energy / CI / CFE breakdown for the f-SLA treatment.

    Pairs each ``ScheduledJob`` in the within-window completed list with
    its workload_class via positional order (the v2 scheduler preserves
    the input row order, and the dispatch_log is keyed by submit-time
    sort, so we replay the same sort to recover the mapping).
    """
    out = {}
    if "workload_class" not in jobs_with_tiers.columns:
        return out
    completed = list(schedule.completed_within_window)
    if not completed:
        for cls in CLASS_ORDER:
            out[f"class_{cls}_energy_kwh"] = 0.0
            out[f"class_{cls}_ci_eff"] = 0.0
            out[f"class_{cls}_cfe_pct"] = 0.0
        return out
    # Pair by submit time: the v2 scheduler sorts by submit_time_epoch
    # internally, then emits dispatch_log in that order, but the
    # safest cross-reference is a {submit_epoch -> class} map — works
    # because _build_window_trace assigns strictly-unique submit times
    # via np.linspace.
    ci_series = ci_df["carbon_intensity_gCO2eq_per_kWh"]
    ci_vals = ci_series.to_numpy(dtype=float)
    ci_ts = np.array(
        [t.timestamp() for t in pd.to_datetime(ci_series.index, utc=True)]
    )
    submit_to_class = dict(zip(
        jobs_with_tiers["submit_time_epoch"].astype(float).tolist(),
        jobs_with_tiers["workload_class"].astype(str).tolist(),
    ))
    per_class_energy = {c: 0.0 for c in CLASS_ORDER}
    per_class_ciw = {c: 0.0 for c in CLASS_ORDER}
    P_NODE_KW = 1.5
    for j in completed:
        cls = submit_to_class.get(float(j.submit_epoch))
        if cls is None:
            continue
        start = float(j.start_epoch)
        idx = int(np.clip(np.searchsorted(ci_ts, start, side="right") - 1,
                           0, len(ci_vals) - 1))
        ci_here = float(ci_vals[idx])
        energy_kwh = (float(j.nodes) * float(j.replicas)
                      * P_NODE_KW * float(j.runtime_s) / 3600.0)
        per_class_energy[cls] = per_class_energy.get(cls, 0.0) + energy_kwh
        per_class_ciw[cls]    = per_class_ciw.get(cls, 0.0) + energy_kwh * ci_here
    for cls in CLASS_ORDER:
        e = per_class_energy[cls]
        out[f"class_{cls}_energy_kwh"] = e
        if e > 0:
            ci_eff = per_class_ciw[cls] / e
            out[f"class_{cls}_ci_eff"] = ci_eff
            out[f"class_{cls}_cfe_pct"] = max(0.0, min(100.0,
                100.0 * (1.0 - ci_eff / CFE_REF_CI_G)))
        else:
            out[f"class_{cls}_ci_eff"] = 0.0
            out[f"class_{cls}_cfe_pct"] = 0.0
    return out


def run_one_cell(country: str, season: str, layer: str, seed: int,
                 jobs_df: pd.DataFrame,
                 n_jobs_per_day: int, mw: int, days_per_window: int,
                 realistic_flexibility: bool,
                 sampling: str = "energy_weighted") -> dict:
    anchor = SEASONS[season]
    # CI window: 24 h pre-trace + the trace + 7 d T3-deferral tail.
    # Symmetric centred windows would waste half the CI hours before
    # the trace ever started and leave T3 tails un-defined; the
    # asymmetric layout keeps every candidate deferral hour inside the
    # CI series so the scheduler's argmax (CFE share) can compare real
    # values rather than the median pad.
    window_hours = (1 + days_per_window + 7) * 24
    ci_df, ci_source = load_seasonal_ci(country, anchor, window_hours)
    pue_curve = pd.Series(1.20, index=ci_df.index, name="pue")
    rng = np.random.default_rng(seed + hash(country) % 1000)
    total_nodes = _nodes_for_mw(mw)
    win_trace = _build_window_trace(
        jobs_df, anchor, n_jobs_per_day, days_per_window, rng,
        sampling=sampling,
    )
    sim_end_epoch = (anchor + timedelta(days=days_per_window + 1)).timestamp()

    base = {
        "country": country, "season": season, "layer": layer,
        "seed": int(seed), "mw": int(mw),
        "ci_source": ci_source,
        "n_input_jobs": len(win_trace),
        "days_per_window": int(days_per_window),
        "flexibility_mode": "dirichlet" if realistic_flexibility else "deterministic",
    }

    if layer in BASELINE_FNS:
        schedule = BASELINE_FNS[layer](
            win_trace, total_nodes=total_nodes,
            ci_df=ci_df, pue_curve=pue_curve,
            sim_end_epoch=sim_end_epoch,
        )
        m = run_metrics(schedule, ci_df, pue_curve=pue_curve)
        completed = schedule.completed_within_window
        if completed:
            slows = np.array([
                max(1.0, (j.end_epoch - j.submit_epoch) / max(1.0, j.runtime_s))
                for j in completed
            ])
            p95 = float(np.percentile(slows, 95))
        else:
            p95 = 1.0
        base.update({
            "n_completed": m["n_completed_within_window"],
            "n_truncated": m["n_truncated"],
            "energy_kwh":  m["energy_kwh"],
            "ci_weighted_mean":  m["ci_weighted_mean"],
            "cfe_canonical_pct": m["cfe_canonical_pct"],
            "co2_g_facility":    m["co2_g_facility"],
            "p95_slowdown":      p95,
        })
        return base

    elif layer == "fsla_taxonomy":
        # Classify, then assign tiers via either:
        #   - deterministic class → tier mapping (--no-realistic-flex), or
        #   - per-class Dirichlet over plausible tier choices (--realistic-flex,
        #     default for v2 paper figures).
        classified = classify_jobs(win_trace, rng=rng)
        if realistic_flexibility:
            jobs_with_tiers = assign_tiers_dirichlet_per_class(
                classified, rng=rng
            )
        else:
            jobs_with_tiers = assign_tiers_from_taxonomy(classified)
        # v2-native carbon-aware deferral: argmin CI over each job's
        # [submit, submit+d_max] window subject to resource availability.
        # This replaces the legacy replay_proact_opt_pue dispatcher,
        # which only PASSIVELY deferred (queue carry-forward + backfill)
        # and routinely produced negative Delta CFE because deferred
        # jobs were dispatched whenever resources freed up rather than
        # at the cleanest hour in-window.  See fsla_carbon_aware.py for
        # the placement-decision code and the failure-mode write-up.
        schedule = fsla_carbon_aware.run(
            jobs_with_tiers,
            total_nodes=total_nodes,
            ci_df=ci_df,
            pue_curve=pue_curve,
            sim_end_epoch=sim_end_epoch,
        )
        m = run_metrics(schedule, ci_df, pue_curve=pue_curve)
        per_class = _per_class_breakdown_from_schedule(
            jobs_with_tiers, schedule, ci_df
        )
        completed = schedule.completed_within_window
        if completed:
            slows = np.array([
                max(1.0, (j.end_epoch - j.submit_epoch) / max(1.0, j.runtime_s))
                for j in completed
            ])
            p95 = float(np.percentile(slows, 95))
        else:
            p95 = 1.0
        base.update({
            "n_completed":       m["n_completed_within_window"],
            "n_truncated":       m["n_truncated"],
            "energy_kwh":        m["energy_kwh"],
            "ci_weighted_mean":  m["ci_weighted_mean"],
            "cfe_canonical_pct": m["cfe_canonical_pct"],
            "co2_g_facility":    m["co2_g_facility"],
            "p95_slowdown":      p95,
            **per_class,
        })
        return base
    else:
        raise ValueError(f"unknown layer {layer!r}")


# ─────────────────────────────────────────────────────────────────────
# CLI driver
# ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path,
                    default=ROOT / "gridpilot" / "experiments_v2" / "data" / "taxonomy_sweep")
    p.add_argument("--countries", default=",".join(DEFAULT_COUNTRIES))
    p.add_argument("--seeds",     type=int, default=DEFAULT_SEEDS)
    p.add_argument("--mw",        type=int, default=DEFAULT_MW)
    p.add_argument("--n-jobs-per-day", type=int, default=DEFAULT_JOBS_PER_DAY)
    p.add_argument("--days-per-window", type=int, default=DEFAULT_DAYS_PER_WINDOW,
                    help="length of each seasonal replay window, in days. "
                         "Default 7 = 'representative week per season' (v2 paper). "
                         "Set to 1 for the v1-style representative-day mode.")
    p.add_argument("--realistic-flexibility", action="store_true", default=True,
                    help="Use per-class Dirichlet over tier choices (default). "
                         "Pass --no-realistic-flexibility to use the literal "
                         "class→tier mapping (less realistic but tighter audit).")
    p.add_argument("--no-realistic-flexibility", dest="realistic_flexibility",
                    action="store_false")
    p.add_argument("--sampling", choices=["energy_weighted", "uniform"],
                    default="energy_weighted",
                    help="How to sub-sample the M100 trace into each "
                         "(country, season) window.  energy_weighted "
                         "(default) draws jobs with probability proportional "
                         "to nodes*runtime so large elastic_ai / batch_parallel "
                         "jobs are over-represented and the per-class GPU.h "
                         "distribution stays close to the population.  "
                         "uniform = the v2.0 behaviour (every job equally "
                         "likely) — produces unstable lift on small samples.")
    p.add_argument("--workers",   type=int, default=4)
    p.add_argument("--jobs",      type=Path, default=None)
    p.add_argument("--no-cache",  action="store_true")
    args = p.parse_args(argv)

    countries = [c.strip() for c in args.countries.split(",") if c.strip()]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cells_dir = args.output_dir / "cells"
    cells_dir.mkdir(exist_ok=True)

    jobs_path = args.jobs if args.jobs is not None else (
        JOBS_EXT if JOBS_EXT.exists() else JOBS_JAN
    )
    jobs_path = Path(jobs_path)
    if not jobs_path.exists():
        print(f"ABORT: jobs trace not found at {jobs_path}", file=sys.stderr)
        return 2
    print(f"[04c-taxonomy-sweep] trace: {jobs_path}")
    jobs_df = pd.read_parquet(jobs_path)
    # Jan-only compat.
    if ("submit_time_epoch" not in jobs_df.columns
            and "submit_time" in jobs_df.columns):
        s = jobs_df["submit_time"]
        if pd.api.types.is_datetime64_any_dtype(s):
            s_epoch = (s.astype("int64") // 10**9).astype("float64")
        else:
            s_epoch = pd.to_numeric(s, errors="coerce").astype("float64")
        jobs_df = jobs_df.assign(submit_time_epoch=s_epoch)
        print(f"[04c-taxonomy-sweep] renamed legacy 'submit_time' -> 'submit_time_epoch'")
    # Compute + emit the taxonomy mix table BEFORE running cells, so
    # a reviewer can audit the classification against the paper's Fig. 1.
    mix = summarise_taxonomy_mix(jobs_df)
    mix_path = args.output_dir / "TAXONOMY_MIX.csv"
    mix.to_csv(mix_path, index=False, float_format="%.3f")
    print(f"[04c-taxonomy-sweep] wrote {mix_path}")
    print("[04c-taxonomy-sweep] classification audit (% of GPU·h):")
    for _, r in mix.iterrows():
        print(f"   {r['class']:<22s}  tier=T{int(r['tier'])}  "
              f"{r['pct_gpu_hours']:>5.1f}% gpu·h  "
              f"({int(r['n_jobs']):>6d} jobs)")

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
    print(f"[04c-taxonomy-sweep] cells: {len(cells)} total, "
          f"{len(rows)} cached, {len(to_run)} to run, workers={args.workers}")

    t0 = time.time()
    bar = (tqdm(total=len(to_run), desc="taxonomy-sweep", unit="cell",
                 smoothing=0.1, mininterval=0.5, dynamic_ncols=True)
            if HAVE_TQDM else None)
    def _tick():
        if bar is not None: bar.update(1)

    if args.workers <= 1:
        for cid, cell in to_run:
            c, season, layer, seed = cell
            row = run_one_cell(c, season, layer, seed, jobs_df,
                                args.n_jobs_per_day, args.mw,
                                args.days_per_window,
                                args.realistic_flexibility,
                                sampling=args.sampling)
            _persist(cells_dir / f"{cid}.json", row)
            rows.append(row); _tick()
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {
                ex.submit(run_one_cell, c, season, layer, seed, jobs_df,
                          args.n_jobs_per_day, args.mw,
                          args.days_per_window,
                          args.realistic_flexibility,
                          args.sampling):
                (cid, cell)
                for cid, (c, season, layer, seed) in to_run
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
        print("[04c-taxonomy-sweep] WARN: no rows produced.")
        return 3

    df = pd.DataFrame(rows).sort_values(
        ["country", "season", "layer", "seed"], kind="stable")
    csv_path = args.output_dir / "taxonomy_sweep.csv"
    df.to_csv(csv_path, index=False, float_format="%.4f")
    print(f"[04c-taxonomy-sweep] wrote {csv_path}")

    # Per-(country, season, layer) means.
    metric_cols = ["energy_kwh", "ci_weighted_mean", "cfe_canonical_pct",
                   "co2_g_facility", "p95_slowdown"]
    # Include per-class CFE columns (only present in fsla_taxonomy rows;
    # baselines will show NaN, fine).
    extra = [c for c in df.columns if c.startswith("class_") and c.endswith("_cfe_pct")]
    summary = df.groupby(["country", "season", "layer"],
                          as_index=False)[metric_cols + extra].mean()
    # Δ CFE vs FCFS within each (country, season, seed).
    fcfs_base = (df[df["layer"] == "fcfs"]
                 .set_index(["country", "season", "seed"])["cfe_canonical_pct"])
    merged = df.merge(
        fcfs_base.rename("fcfs_cfe").reset_index(),
        on=["country", "season", "seed"], how="left",
    )
    merged["d_cfe_vs_fcfs_pp"] = merged["cfe_canonical_pct"] - merged["fcfs_cfe"]
    csv_path2 = args.output_dir / "taxonomy_sweep.csv"
    merged.to_csv(csv_path2, index=False, float_format="%.4f")

    summary_path = args.output_dir / "TAXONOMY_SUMMARY.csv"
    summary.to_csv(summary_path, index=False, float_format="%.4f")
    print(f"[04c-taxonomy-sweep] wrote {summary_path}")

    (args.output_dir / "RUN_MANIFEST.json").write_text(json.dumps({
        "kind": "taxonomy_sweep", "version": 2,
        "git_sha": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False).stdout.strip() or "unknown",
        "python": platform.python_version(), "host": platform.node(),
        "argv": sys.argv, "n_cells": len(rows),
        "trace": str(jobs_path), "countries": countries,
        "seasons": {k: v.isoformat() for k, v in SEASONS.items()},
        "n_jobs_per_day": args.n_jobs_per_day,
        "days_per_window": args.days_per_window,
        "flexibility_mode": "dirichlet" if args.realistic_flexibility else "deterministic",
        "mw": args.mw, "seeds": args.seeds,
        "classifier": {
            "module": "experiments_v2/src/workload_taxonomy.py",
            "tier_mapping": {k: int(v) for k, v in CLASS_TO_TIER.items()},
        },
        "wall_seconds": int(time.time() - t0),
    }, indent=2, default=str))
    print(f"[04c-taxonomy-sweep] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
