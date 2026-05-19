#!/usr/bin/env python3
"""
scripts/m100/inject_fsla_prior.py
=================================

Monte-Carlo f-SLA injection on the M100 trace.

This script is the canonical Finding 3 evidence driver of the PECS 2026
paper:

    "Honest Facility-Level CO₂ Accounting for AI/HPC Workloads:
     A PUE-Aware Carbon-Aware Scheduler with a Flexible-SLA Elicitation
     Contract, Validated on the Marconi100 Production Trace and
     Projected to 50 MW"

It runs the existing PUE-aware scheduler (`replay_proact_opt_pue` in
`src/scheduler/scheduler_pue_aware.py`) twice per Monte-Carlo seed: once
with every job pinned to the rigid tier T0 and once with each job
assigned a tier from a synthetic Dirichlet prior.  The Δ between the
two baselines is the headline contribution of Finding 3.

Output bundle
~~~~~~~~~~~~~

In ``--output-dir`` (default: ``data/m100/fsla_counterfactual/``):

  headline.csv          one row per seed
                          seed, pi_T0, pi_T1, pi_T2, pi_T3,
                          rigid_it_pct, rigid_fac_pct, decl_it_pct,
                          decl_fac_pct, delta_it_pp, delta_fac_pp,
                          p95_rigid, p95_decl, p95_match
  bootstrap_ci.json     bootstrap CI on the headline Δ (default
                        10 000 resamples, 95 % CI)
  prior_sensitivity.csv Δ at α/2, α, 2α (one row per scale)
  seed_runs/seed_<n>.json  full per-seed result and FSLAPriorReport
  RUN_MANIFEST.json     git SHA, command line, package versions,
                        wall time, hostname

Example
~~~~~~~

::

    PYTHONPATH=src python scripts/m100/inject_fsla_prior.py \\
        --jobs    data/traces/m100_real_jobs.parquet \\
        --ci      configs/grids/DE.yaml \\
        --pue     raps/config/marconi100.yaml \\
        --alpha   3.0 3.0 2.5 1.5 \\
        --seeds   32 \\
        --bootstrap 10000 \\
        --sensitivity-scale 0.5,1.0,2.0 \\
        --output-dir data/m100/fsla_counterfactual/

Acceptance criteria (verified by tests/test_fsla.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

  1. Reproducible under fixed seed.  Two runs with the same seed
     produce byte-identical headline.csv and bootstrap_ci.json.
  2. Bootstrap 95 % CI width ≤ 1.5 pp on the default-prior Δ_IT.
  3. Sensitivity envelope at α/2 and 2α brackets the default Δ within
     ±2 pp; the cross-prior ranking Δ > 0 is preserved.
  4. Length-conditioned reassignment counts logged per seed.
  5. Per-job slowdown clause invariant: actual_slowdown ≤ s_max_clause.
  6. Standard CLI: --help, missing-arg error, --force overwrite.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

# ─── Make sibling src/ importable ────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]   # gridpilot/
sys.path.insert(0, str(ROOT / "src"))

from scheduler.fsla import (                           # noqa: E402
    DEFAULT_ALPHA, TIER_NAMES, FSLAPriorReport,
    sample_prior, replay_pair, bootstrap_ci,
)
from cooling.cooling_pue_model import calibrate_to_design_pue  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────────────────────────────
def load_jobs(path: Path) -> pd.DataFrame:
    """Load M100 jobs parquet/csv and normalise to the scheduler's expected
    column names.

    The scheduler (``src/scheduler/scheduler_pue_aware.py``) needs:
        submit_time_epoch  (float seconds since the Unix epoch)
        run_time           (float seconds)
        num_nodes_alloc    (int)

    The released PM100 parquet uses ``submit_time`` rather than
    ``submit_time_epoch``; this loader synthesises the epoch column from
    whichever timestamp representation is on disk (pandas datetime,
    ISO-8601 string, or already-numeric epoch seconds).
    """
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    # ─── Normalise the submit-time column ───────────────────────────
    if "submit_time_epoch" not in df.columns:
        if "submit_time" in df.columns:
            st = df["submit_time"]
            if pd.api.types.is_datetime64_any_dtype(st):
                df["submit_time_epoch"] = st.astype("int64") // 10**9
            elif pd.api.types.is_numeric_dtype(st):
                df["submit_time_epoch"] = st.astype(float)
            else:
                # Try parsing as an ISO-8601 string
                df["submit_time_epoch"] = (
                    pd.to_datetime(st, errors="coerce")
                      .astype("int64") // 10**9
                )
        else:
            # Fall back to a synthesised submission cadence so the
            # scheduler still runs (only useful for tests; production
            # traces should carry a real submission timestamp).
            df["submit_time_epoch"] = np.arange(len(df), dtype=float) * 60.0

    # ─── Normalise the node-count column ────────────────────────────
    if "num_nodes_alloc" not in df.columns:
        for alt in ("num_nodes", "nodes_alloc", "nodes"):
            if alt in df.columns:
                df["num_nodes_alloc"] = df[alt]
                break

    # ─── Normalise the runtime column ───────────────────────────────
    if "run_time" not in df.columns:
        for alt in ("runtime", "duration_s", "duration"):
            if alt in df.columns:
                df["run_time"] = df[alt]
                break

    required = {"submit_time_epoch", "run_time", "num_nodes_alloc"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"jobs file {path} missing required columns after normalisation: "
            f"{missing}. present columns: {list(df.columns)}"
        )

    # Coerce dtypes so downstream `int(...)` / `float(...)` casts work
    df["submit_time_epoch"] = pd.to_numeric(df["submit_time_epoch"],
                                              errors="coerce").astype(float)
    df["run_time"] = pd.to_numeric(df["run_time"], errors="coerce").astype(float)
    df["num_nodes_alloc"] = (
        pd.to_numeric(df["num_nodes_alloc"], errors="coerce")
          .fillna(1).astype(int)
    )
    # Drop rows where coercion failed
    df = df.dropna(subset=["submit_time_epoch", "run_time"]).reset_index(drop=True)

    return df


#: Default anchor year for synthesised CI series.  M100 trace is from
#: January 2022 originally; we re-anchor to the YAML's nominal year so
#: the CI trajectory roadmap (2025/2028/2032) matches the paper's
#: deployment-window framing.
DEFAULT_CI_ANCHOR_YEAR = 2025

#: Diurnal amplitude (fraction of the annual mean) per grid.  Calibrated
#: to the 2020-2024 ENTSO-E diurnal envelope reported in the paper.
#: Six-country headline set covers the EU CI spectrum from very-low
#: (SE, CH, FR) through medium (IT, DE) to high (PL).
DIURNAL_AMPLITUDE_BY_COUNTRY = {
    "SE": 0.10,    # ±10 % (hydro + nuclear + wind, very flat)
    "CH": 0.12,    # ±12 % (hydro-dominated, low variance)
    "FR": 0.15,    # ±15 % (nuclear baseload + peaking)
    "IT": 0.25,    # ±25 % (gas-mixed)
    "PL": 0.28,    # ±28 % (coal-heavy, wind-driven swing)
    "DE": 0.35,    # ±35 % (solar+wind drive a wide swing)
}
DIURNAL_AMPLITUDE_DEFAULT = 0.25
WEEKEND_FACTOR_DEFAULT = 0.92  # weekend CI typically ~8 % below weekday mean


def _synthesise_ci(annual_mean_g_per_kwh: float,
                    country_code: str,
                    year: int = DEFAULT_CI_ANCHOR_YEAR,
                    hours: int = 8760,
                    diurnal_amplitude: Optional[float] = None,
                    weekend_factor: Optional[float] = None) -> pd.DataFrame:
    """Synthesise a deterministic one-year hourly CI series.

    Diurnal pattern: minimum near 13:00 (solar peak), maximum near 19:00
    (evening fossil ramp).  Amplitude scaled by the grid's published
    2020-2024 diurnal envelope.  Weekend factor applied per ENTSO-E
    Saturday/Sunday templates.  When ``diurnal_amplitude`` and
    ``weekend_factor`` are provided (e.g. from a per-country YAML) they
    override the country-keyed defaults — this lets new grids be added
    without editing this file.
    """
    idx = pd.date_range(f"{year}-01-01", periods=hours, freq="h", tz="UTC")
    hour_of_day = idx.hour.values
    day_of_week = idx.dayofweek.values  # 0=Mon, 6=Sun

    # Diurnal: phase-shifted cosine peaking at 19:00
    amp = (diurnal_amplitude if diurnal_amplitude is not None
            else DIURNAL_AMPLITUDE_BY_COUNTRY.get(country_code,
                                                    DIURNAL_AMPLITUDE_DEFAULT))
    diurnal = 1.0 + amp * np.cos(2.0 * np.pi * (hour_of_day - 19) / 24.0)

    # Weekly: weekends slightly cleaner (industrial demand drop)
    wf = weekend_factor if weekend_factor is not None else WEEKEND_FACTOR_DEFAULT
    weekly = np.where(day_of_week >= 5, wf, 1.0)

    # Mild seasonal modulation: ±8 % about the annual mean, peak in winter
    day_of_year = idx.dayofyear.values
    seasonal = 1.0 + 0.08 * np.cos(2.0 * np.pi * (day_of_year - 15) / 365.0)

    ci = annual_mean_g_per_kwh * diurnal * weekly * seasonal
    return pd.DataFrame({"carbon_intensity_gCO2eq_per_kWh": ci}, index=idx)


def load_ci(path: Path) -> pd.DataFrame:
    """Load a per-grid CI series.

    Accepts:
      * a CSV / Parquet with columns (timestamp, carbon_intensity_gCO2eq_per_kWh)
      * a YAML grid config with a ``ci_trajectory: {YYYY: g_per_kWh, ...}`` map —
        synthesises a deterministic hourly series for ``DEFAULT_CI_ANCHOR_YEAR``
        using the annual mean and a country-specific diurnal + weekly +
        seasonal pattern (see ``_synthesise_ci``).
      * a YAML grid config with an explicit ``ci_csv`` key — loads from that
        path (relative paths resolve against the YAML's directory).

    Returns a DataFrame indexed by timestamp.
    """
    if path.suffix in (".yaml", ".yml"):
        cfg = yaml.safe_load(path.read_text())
        if "ci_csv" in cfg:
            ci_path = Path(cfg["ci_csv"])
            if not ci_path.is_absolute():
                ci_path = path.parent / ci_path
            return load_ci(ci_path)
        # Synthesise from the annual-mean trajectory
        traj = cfg.get("ci_trajectory", {})
        # Pull only int keys (the YAML also has a "source" string key)
        yearly = {int(k): float(v) for k, v in traj.items()
                  if isinstance(k, int) or (isinstance(k, str) and k.isdigit())}
        if not yearly:
            raise ValueError(
                f"YAML {path} has no ci_csv key and no ci_trajectory: "
                f"{{year: g/kWh}} entries — cannot derive a CI series."
            )
        anchor_year = DEFAULT_CI_ANCHOR_YEAR if DEFAULT_CI_ANCHOR_YEAR in yearly \
                      else min(yearly.keys())
        annual_mean = yearly[anchor_year]
        country_code = str(cfg.get("country_code", "")).upper()
        # Optional per-YAML overrides; SE/FR/PL configs ship these explicitly.
        diurnal_amp = cfg.get("diurnal_amplitude")
        weekend_fac = cfg.get("weekend_factor")
        return _synthesise_ci(annual_mean, country_code, year=anchor_year,
                                diurnal_amplitude=diurnal_amp,
                                weekend_factor=weekend_fac)
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, parse_dates=[0])
    df = df.set_index(df.columns[0])
    if "carbon_intensity_gCO2eq_per_kWh" not in df.columns:
        raise ValueError(
            f"CI file {path} must have a 'carbon_intensity_gCO2eq_per_kWh' column"
        )
    return df


def align_jobs_to_ci(jobs_df: pd.DataFrame, ci_df: pd.DataFrame) -> pd.DataFrame:
    """Shift the trace so the earliest job aligns with the CI series start.

    The PM100 trace timestamps are real (January 2022) but the CI series
    is synthesised for a different year; without re-anchoring, every
    job's CI lookup would clamp to the boundary and the dispatch signal
    would be constant.  This shift preserves inter-job spacing.
    """
    out = jobs_df.copy()
    first_submit = float(out["submit_time_epoch"].min())
    ci_start = float(pd.to_datetime(ci_df.index[0]).timestamp())
    delta = first_submit - ci_start
    out["submit_time_epoch"] = out["submit_time_epoch"] - delta
    return out


def load_t_amb(path: Optional[Path], ci_index) -> pd.Series:
    """Load ambient-temperature series. If absent, fall back to a
    constant 20 °C series aligned with the CI index.
    """
    if path is None:
        return pd.Series(20.0, index=ci_index, name="t_amb_c")
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, parse_dates=[0])
    df = df.set_index(df.columns[0])
    return df.iloc[:, 0].reindex(ci_index, method="ffill").fillna(20.0)


#: Per-system published-design PUE used to anchor the four-component
#: cooling model.  These are the M100 / Frontier paper-anchor values,
#: NOT the RAPS scalar ``cooling_efficiency`` (which would imply
#: PUE ≈ 1.058 for M100 — the 12 % gap is exactly the point of the
#: §3.6 cross-system calibration discussion).
PAPER_ANCHOR_PUE = {
    "marconi100": 1.20,
    "frontier":   1.03,
    "lumi-g":     1.04,
    "summit":     1.10,
    "fugaku":     1.30,
}


def _is_raps_schema(cfg: dict) -> bool:
    """True if the YAML matches the ExaDigiT RAPS system schema."""
    return all(k in cfg for k in ("system", "power", "cooling"))


def _resolve_pue_path(path: Path) -> Path:
    """Resolve a system YAML path.  If the literal path is missing, try
    the bundled RAPS config dir (``<repo_root>/raps/config/<basename>``).
    Raise FileNotFoundError with an actionable message if both fail.
    """
    if path.exists():
        return path
    bundled = ROOT / "raps" / "config" / path.name
    if bundled.exists():
        print(f"[fsla] --pue path {path} not found; using bundled "
              f"{bundled.relative_to(ROOT)}", file=sys.stderr)
        return bundled
    raise FileNotFoundError(
        f"--pue YAML not found.  Looked for:\n  literal: {path}\n  "
        f"bundled: {bundled}\n\n"
        f"The v1.0 release bundles the ExaDigiT/RAPS canonical configs "
        f"at gridpilot/raps/config/<system>.yaml (e.g. marconi100.yaml, "
        f"frontier.yaml).  Pass --pue raps/config/marconi100.yaml."
    )


def load_pue_params(path: Optional[Path]):
    """Calibrate the four-component cooling model from a RAPS YAML.

    The accepted format is the ExaDigiT/RAPS canonical schema
    (``raps/config/<system>.yaml``, with ``system:`` / ``power:`` /
    ``cooling:`` top-level blocks).  ``it_design_kw`` is derived from
    per-node power × node count via ``load_raps_system_config``; the
    target design PUE is the published anchor value (e.g. 1.20 for
    M100, 1.03 for Frontier), NOT the RAPS scalar
    ``cooling_efficiency`` — the gap between the two is the §3.6
    cross-system calibration finding.

    With ``path=None`` (the CLI default), the M100 anchor is used
    (1400 kW IT design, PUE 1.20) so the script runs out of the box.
    """
    if path is None:
        return calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    path = _resolve_pue_path(path)
    cfg = yaml.safe_load(path.read_text())
    if not _is_raps_schema(cfg):
        raise ValueError(
            f"{path} is not a RAPS-schema YAML (missing system: / power: / "
            f"cooling: top-level keys).  See raps/config/marconi100.yaml "
            f"for the canonical format."
        )
    sys.path.insert(0, str(ROOT / "src"))
    from integration.raps_config_adapter import load_raps_system_config
    raps_cfg = load_raps_system_config(
        raps_repo_path=path.parent.parent,
        system_name=path.stem,
    )
    target_pue = PAPER_ANCHOR_PUE.get(path.stem.lower(), 1.20)
    return calibrate_to_design_pue(
        target_pue=target_pue,
        it_design_kw=raps_cfg.total_design_power_kw,
    )


# ─────────────────────────────────────────────────────────────────────
# Manifest
# ─────────────────────────────────────────────────────────────────────
def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _package_versions() -> dict[str, str]:
    out = {}
    for mod_name in ("numpy", "pandas", "yaml"):
        try:
            mod = __import__(mod_name)
            out[mod_name] = getattr(mod, "__version__", "unknown")
        except Exception:
            out[mod_name] = "missing"
    return out


def write_manifest(out_dir: Path, args: argparse.Namespace, t_start: float):
    manifest = {
        "git_sha": _git_sha(),
        "command_line": " ".join(sys.argv),
        "args": {k: str(v) for k, v in vars(args).items()},
        "python_version": sys.version,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "package_versions": _package_versions(),
        "wall_time_s": time.time() - t_start,
    }
    (out_dir / "RUN_MANIFEST.json").write_text(json.dumps(manifest, indent=2))


# ─────────────────────────────────────────────────────────────────────
# Per-seed runner
# ─────────────────────────────────────────────────────────────────────
def _serialise_report(r: FSLAPriorReport) -> dict:
    return dataclasses.asdict(r)


def run_one_seed(
    seed: int, jobs_df, ci_df, t_amb_series, pi, *,
    cooling_params, scheduler_kwargs, out_dir: Path,
) -> dict:
    res = replay_pair(
        jobs_df, ci_df, t_amb_series, pi, seed,
        cooling_params=cooling_params, **scheduler_kwargs,
    )

    # Per-seed JSON dump (verbose, includes the FSLAPriorReport)
    seed_dir = out_dir / "seed_runs"
    seed_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "seed": res["seed"],
        "pi": res["pi"],
        "prior_report": _serialise_report(res["prior_report"]),
        "all_rigid": res["all_rigid"],
        "declared_tier": res["declared_tier"],
        "delta_it_pp": res["delta_it_pp"],
        "delta_facility_pp": res["delta_facility_pp"],
        "p95_match": res["p95_match"],
    }
    (seed_dir / f"seed_{seed:04d}.json").write_text(json.dumps(out, indent=2))

    # Headline row
    return {
        "seed": seed,
        "pi_T0": pi[0], "pi_T1": pi[1], "pi_T2": pi[2], "pi_T3": pi[3],
        "rigid_it_pct":  res["all_rigid"]["it_co2_pct"],
        "rigid_fac_pct": res["all_rigid"]["facility_co2_pct"],
        "decl_it_pct":   res["declared_tier"]["it_co2_pct"],
        "decl_fac_pct":  res["declared_tier"]["facility_co2_pct"],
        "delta_it_pp":   res["delta_it_pp"],
        "delta_fac_pp":  res["delta_facility_pp"],
        "p95_rigid":     res["all_rigid"]["p95_slowdown"],
        "p95_decl":      res["declared_tier"]["p95_slowdown"],
        "p95_match":     int(res["p95_match"]),
        "n_long_reassigned":  res["prior_report"].n_long_reassigned_from_T0,
        "n_short_reassigned": res["prior_report"].n_short_reassigned_from_high_tier,
    }


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────
def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="inject_fsla_prior",
        description="Monte-Carlo f-SLA injection on the M100 trace "
                    "(PECS 2026 Finding 3 driver).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--jobs", type=Path, required=True,
                   help="Path to M100 jobs parquet/csv "
                        "(must have submit_time_epoch, run_time, num_nodes_alloc).")
    p.add_argument("--ci", type=Path, required=True,
                   help="Path to CI csv/parquet/grid YAML.")
    p.add_argument("--t-amb", type=Path, default=None,
                   help="Optional ambient-temperature csv/parquet "
                        "(falls back to constant 20 °C if absent).")
    p.add_argument("--pue", type=Path, default=None,
                   help="Optional RAPS YAML for PUE calibration "
                        "(falls back to M100 defaults).")
    p.add_argument("--alpha", type=float, nargs=len(TIER_NAMES),
                   default=list(DEFAULT_ALPHA),
                   help=f"Dirichlet concentration alpha "
                        f"({len(TIER_NAMES)} floats; default {DEFAULT_ALPHA}).")
    p.add_argument("--seeds", type=int, default=32,
                   help="Number of Monte-Carlo seeds (default 32).")
    p.add_argument("--bootstrap", type=int, default=10_000,
                   help="Number of bootstrap resamples for the 95 %% CI "
                        "on the headline Δ (default 10 000).")
    p.add_argument("--sensitivity-scale", type=str, default="0.5,1.0,2.0",
                   help="Comma-separated scale factors for the prior "
                        "concentration sensitivity sweep (default 0.5,1.0,2.0).")
    p.add_argument("--output-dir", type=Path,
                   default=Path("data/m100/fsla_counterfactual"),
                   help="Where to write headline.csv, bootstrap_ci.json, etc.")
    p.add_argument("--seed-base", type=int, default=20260513,
                   help="Base for per-MC seeds (default uses today's date).")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing output files.")
    p.add_argument("--time-step", type=int, default=3600,
                   help="Scheduler simulation time step in seconds (default 3600).")
    p.add_argument("--total-nodes", type=int, default=980,
                   help="Cluster size (default 980 = M100).")
    p.add_argument("--node-power-kw", type=float, default=1.5,
                   help="Per-node IT power (default 1.5 kW).")
    p.add_argument("--quiet", action="store_true",
                   help="Suppress per-seed progress prints.")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    t0 = time.time()

    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    headline_csv = out_dir / "headline.csv"
    bootstrap_json = out_dir / "bootstrap_ci.json"
    sens_csv = out_dir / "prior_sensitivity.csv"
    if (headline_csv.exists() or bootstrap_json.exists()) and not args.force:
        print(f"ERROR: {headline_csv.name} or {bootstrap_json.name} already exists "
              f"in {out_dir}. Use --force to overwrite.", file=sys.stderr)
        return 2

    # ─── Load inputs ─────────────────────────────────────────────────
    if not args.quiet:
        print(f"[fsla] loading jobs from {args.jobs}", flush=True)
    jobs_df = load_jobs(args.jobs)
    if not args.quiet:
        print(f"[fsla] loading CI from {args.ci}", flush=True)
    ci_df = load_ci(args.ci)
    jobs_df = align_jobs_to_ci(jobs_df, ci_df)
    t_amb = load_t_amb(args.t_amb, ci_df.index)
    cooling_params = load_pue_params(args.pue)
    if not args.quiet:
        ci_min = float(ci_df['carbon_intensity_gCO2eq_per_kWh'].min())
        ci_max = float(ci_df['carbon_intensity_gCO2eq_per_kWh'].max())
        print(f"[fsla] {len(jobs_df)} jobs (re-anchored to CI start), "
              f"{len(ci_df)} CI samples [{ci_min:.0f}-{ci_max:.0f} g/kWh], "
              f"alpha={tuple(args.alpha)}, seeds={args.seeds}, "
              f"bootstrap={args.bootstrap}", flush=True)

    scheduler_kwargs = dict(
        total_nodes=args.total_nodes,
        node_power_kw=args.node_power_kw,
        time_step=args.time_step,
    )

    # ─── Default-prior Monte Carlo ──────────────────────────────────
    rows: list[dict] = []
    for k in range(args.seeds):
        seed = args.seed_base + k
        rng = np.random.default_rng(seed)
        pi = sample_prior(tuple(args.alpha), rng=rng)
        if not args.quiet:
            print(f"[fsla] seed {seed} (pi=[{pi[0]:.3f},{pi[1]:.3f},"
                  f"{pi[2]:.3f},{pi[3]:.3f}])", flush=True)
        row = run_one_seed(
            seed, jobs_df, ci_df, t_amb, pi,
            cooling_params=cooling_params,
            scheduler_kwargs=scheduler_kwargs,
            out_dir=out_dir,
        )
        rows.append(row)

    headline_df = pd.DataFrame(rows)
    headline_df.to_csv(headline_csv, index=False, float_format="%.4f")
    if not args.quiet:
        print(f"[fsla] wrote {headline_csv}", flush=True)

    # ─── Bootstrap CI on the headline Δ ─────────────────────────────
    rng = np.random.default_rng(args.seed_base + 99_999)
    mean_it, lo_it, hi_it = bootstrap_ci(
        headline_df["delta_it_pp"].values, args.bootstrap, rng=rng)
    mean_fac, lo_fac, hi_fac = bootstrap_ci(
        headline_df["delta_fac_pp"].values, args.bootstrap, rng=rng)
    mean_dec_it, lo_dec_it, hi_dec_it = bootstrap_ci(
        headline_df["decl_it_pct"].values, args.bootstrap, rng=rng)
    mean_dec_fac, lo_dec_fac, hi_dec_fac = bootstrap_ci(
        headline_df["decl_fac_pct"].values, args.bootstrap, rng=rng)
    boot = {
        "n_seeds": int(args.seeds),
        "n_resamples": int(args.bootstrap),
        "confidence": 0.95,
        "alpha": list(args.alpha),
        "delta_it_pp": {"mean": mean_it, "ci_lower": lo_it, "ci_upper": hi_it,
                         "ci_width": hi_it - lo_it},
        "delta_facility_pp": {"mean": mean_fac, "ci_lower": lo_fac, "ci_upper": hi_fac,
                               "ci_width": hi_fac - lo_fac},
        "declared_it_pct": {"mean": mean_dec_it, "ci_lower": lo_dec_it,
                            "ci_upper": hi_dec_it},
        "declared_facility_pct": {"mean": mean_dec_fac, "ci_lower": lo_dec_fac,
                                  "ci_upper": hi_dec_fac},
    }
    bootstrap_json.write_text(json.dumps(boot, indent=2))
    if not args.quiet:
        print(f"[fsla] wrote {bootstrap_json} "
              f"(Δ_IT mean {mean_it:.2f} pp, CI [{lo_it:.2f}, {hi_it:.2f}], "
              f"width {hi_it-lo_it:.2f} pp)", flush=True)

    # ─── Sensitivity sweep over Dirichlet concentration ─────────────
    sens_scales = [float(s) for s in args.sensitivity_scale.split(",")]
    sens_rows = []
    n_sens_seeds = max(8, args.seeds // 4)   # cheaper sub-sweep
    for scale in sens_scales:
        scaled = tuple(a * scale for a in args.alpha)
        per_seed = []
        for k in range(n_sens_seeds):
            seed = args.seed_base + 50_000 + int(scale * 1_000) + k
            rng = np.random.default_rng(seed)
            pi = sample_prior(scaled, rng=rng)
            res = replay_pair(
                jobs_df, ci_df, t_amb, pi, seed,
                cooling_params=cooling_params, **scheduler_kwargs,
            )
            per_seed.append(res["delta_it_pp"])
        per_seed = np.asarray(per_seed)
        sens_rows.append({
            "scale": scale,
            "alpha_T0": scaled[0], "alpha_T1": scaled[1],
            "alpha_T2": scaled[2], "alpha_T3": scaled[3],
            "n_seeds": n_sens_seeds,
            "delta_it_mean": float(per_seed.mean()),
            "delta_it_min":  float(per_seed.min()),
            "delta_it_max":  float(per_seed.max()),
            "delta_it_std":  float(per_seed.std(ddof=1)) if per_seed.size > 1 else 0.0,
        })
    pd.DataFrame(sens_rows).to_csv(sens_csv, index=False, float_format="%.4f")
    if not args.quiet:
        print(f"[fsla] wrote {sens_csv}", flush=True)

    write_manifest(out_dir, args, t0)
    if not args.quiet:
        print(f"[fsla] manifest written; total wall time "
              f"{time.time()-t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
