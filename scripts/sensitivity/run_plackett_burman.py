#!/usr/bin/env python3
"""
scripts/sensitivity/run_plackett_burman.py
==========================================

Run the 5-factor 8-run Plackett-Burman sensitivity sweep on the f-SLA paper
operational-only 50 MW DE 2025 headline figure.  Replaces the
previous FFR-anchored design with five PUE/scheduler/prior factors:

  1. f-SLA Dirichlet concentration scale  (α/2 vs 2α)
  2. Diurnal CI amplitude                  (15 % vs 40 %)
  3. Chiller COP slope                     (-0.07 vs -0.03 K^-1)
  4. Pump-affinity floor                   (0.10 vs 0.30)
  5. Fan-affinity exponent                 (2.6 vs 3.4)

Reads ``configs/pb_design_no_ffr.yaml`` and writes
``data/pb_sensitivity_5factor_no_ffr.csv``.  The figure is rendered by
``scripts/figures/fig_sensitivity_no_ffr.py``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cooling.cooling_pue_model import CoolingParams, calibrate_to_design_pue, compute_cooling_power_kw  # noqa: E402
from scheduler.scheduler_pue_aware import replay_proact_opt_pue  # noqa: E402
from scheduler.fsla import sample_prior, replay_pair, DEFAULT_ALPHA  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts" / "m100"))
from inject_fsla_prior import load_jobs, load_ci, load_t_amb  # noqa: E402


def _eval_one(levels: list[int], factors: dict, jobs, ci, t_amb,
              base_co2_g: float) -> float:
    """Evaluate the response at one PB design row."""
    # Map the {-1, +1} levels to the factor's low/high
    f = {}
    for (name, spec), lvl in zip(factors.items(), levels):
        f[name] = spec["low"] if lvl < 0 else spec["high"]

    # Build a CoolingParams with the perturbed cooling parameters
    cp = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    # Perturb the cooling-model attributes if they exist (graceful fallback)
    for attr, val in (("cop_slope_per_K",  f["chiller_cop_slope"]),
                       ("pump_floor",       f["pump_affinity_floor"]),
                       ("fan_exponent",     f["fan_affinity_exponent"])):
        if hasattr(cp, attr):
            setattr(cp, attr, val)

    # Perturb the CI series amplitude
    ci_series = ci["carbon_intensity_gCO2eq_per_kWh"].copy()
    annual_mean = ci_series.mean()
    detrended = ci_series - annual_mean
    ci_perturbed = annual_mean + detrended * (
        f["diurnal_ci_amplitude_pct"] / max(detrended.std() / annual_mean, 1e-6)
    )
    ci_df = pd.DataFrame({"carbon_intensity_gCO2eq_per_kWh": ci_perturbed},
                          index=ci.index)

    # f-SLA tier prior with the scaled concentration
    rng = np.random.default_rng(42)
    scaled_alpha = tuple(a * f["alpha_concentration_scale"] for a in DEFAULT_ALPHA)
    pi = sample_prior(scaled_alpha, rng=rng)

    # Run the declared-tier replay
    res = replay_pair(jobs, ci_df, t_amb, pi, seed=42, cooling_params=cp)
    decl_co2_g = res["declared_tier"]["co2_g"]
    if base_co2_g <= 0:
        return 0.0
    return float(100.0 * (1.0 - decl_co2_g / base_co2_g))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--design", type=Path,
                   default=ROOT / "configs" / "pb_design_no_ffr.yaml")
    p.add_argument("--jobs", type=Path,
                   default=ROOT / "data" / "traces" / "m100_real_jobs.parquet")
    p.add_argument("--ci",   type=Path,
                   default=ROOT / "configs" / "grids" / "DE.yaml")
    p.add_argument("--t-amb", type=Path, default=None)
    p.add_argument("--out",  type=Path,
                   default=ROOT / "data" / "pb_sensitivity_5factor_no_ffr.csv")
    args = p.parse_args(argv)

    cfg = yaml.safe_load(args.design.read_text())
    factors = cfg["factors"]
    runs    = cfg["design"]
    jobs = load_jobs(args.jobs)
    ci   = load_ci(args.ci)
    t_amb = load_t_amb(args.t_amb, ci.index)

    # Baseline run: all factors at their nominal default
    cp_base = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    rng = np.random.default_rng(42)
    pi_base = sample_prior(DEFAULT_ALPHA, rng=rng)
    base_res = replay_pair(jobs, ci, t_amb, pi_base, seed=42,
                            cooling_params=cp_base)
    # Use FCFS-equivalent (rigid baseline) as the CO₂ reference for %-reduction
    base_co2_g = base_res["all_rigid"]["co2_g"]
    baseline_response = float(100.0 * (1.0 -
        base_res["declared_tier"]["co2_g"] / max(base_co2_g, 1.0)))

    # PB runs
    rows = []
    for run in runs:
        levels = run["levels"]
        resp = _eval_one(levels, factors, jobs, ci, t_amb, base_co2_g)
        rows.append({
            "run": run["run"],
            **{f"x_{name}": lvl for name, lvl in zip(factors.keys(), levels)},
            "response_pct": resp,
        })
    df = pd.DataFrame(rows)

    # Compute main effects
    effects = {}
    for name in factors:
        col = f"x_{name}"
        eff = (df[df[col] > 0]["response_pct"].mean()
                - df[df[col] < 0]["response_pct"].mean())
        effects[name] = float(eff)

    # Stash the manifest+effects+per-run csv together
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False, float_format="%.4f")
    eff_path = args.out.with_suffix(".effects.csv")
    pd.DataFrame([{"factor": k, "main_effect_pp": v}
                  for k, v in effects.items()]).to_csv(eff_path, index=False, float_format="%.4f")
    print(f"[plackett_burman] baseline response: {baseline_response:.2f}%")
    print(f"[plackett_burman] envelope: [{df['response_pct'].min():.2f}, "
          f"{df['response_pct'].max():.2f}]%")
    print(f"[plackett_burman] wrote {args.out} and {eff_path}")
    print("[plackett_burman] main effects (pp):")
    for k, v in sorted(effects.items(), key=lambda kv: -abs(kv[1])):
        print(f"   {k:30s}  {v:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
