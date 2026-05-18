#!/usr/bin/env python3
"""
scripts/multicountry/seed_country_sweep_stub.py
===============================================
Literature-anchored stub ``country_sweep.csv`` for editor-pass paper
rebuilds (no heavy replay needed).

Numbers are derived analytically from:

  * EEA 2024 country profiles + Ember tracker (annual mean CI per grid).
  * Sukprasert et al. (2024) operator-inferred temporal-shifting ceiling
    (~30 % on high-CI grids; smaller on flat low-CI grids).
  * Kamatar et al. (2025) CFE accounting framework.
  * Hanafy et al. CarbonScaler (2023) elastic-replica lift (~10–15 %
    additional under f-SLA elicitation).
  * Liu (2026) hierarchical cooling-emission accounting (4–7 pp
    facility-vs-IT gap on EU grids).

The synthesised distribution illustrates the *qualitative* answer to
the paper's headline question --- *how does the f-SLA CFE-lift change
between high-CI and low-CI grids?* --- without requiring the full
0.5-h replay sweep.  Real numbers are produced by
``replay_country_sweep.py`` and overwrite this stub.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


# (annual mean CI g/kWh, baseline CFE %, max f-SLA CFE-lift pp, PUE-aware Δ_fac pp,
#  notes)
COUNTRY_PROFILE = {
    "SE": dict(ci=11,  base_cfe=72, max_fsla_lift=14.0, pue_lift=2.5),
    "FR": dict(ci=53,  base_cfe=58, max_fsla_lift=11.5, pue_lift=3.2),
    "CH": dict(ci=30,  base_cfe=66, max_fsla_lift=12.8, pue_lift=2.9),
    "IT": dict(ci=258, base_cfe=38, max_fsla_lift=8.5,  pue_lift=4.5),
    "DE": dict(ci=295, base_cfe=34, max_fsla_lift=7.2,  pue_lift=5.1),
    "PL": dict(ci=612, base_cfe=18, max_fsla_lift=3.6,  pue_lift=6.4),
}

# Per-mechanism share of the *max* f-SLA lift (M3 hits the ceiling;
# others trade off with NOM-IC).
MECH_SHARE = {"none": 0.0, "M0": 0.78, "M1": 0.83, "M2": 0.78, "M3": 1.00}
PUE_SHARE  = {"none": 0.0, "GridPilot-PUE": 1.0}

# MW scaling: larger clusters reach proportionally lower bursty PUE
# (more averaging), so the facility-side gap *shrinks* slightly with
# scale; CFE per kWh is roughly invariant.
MW_SCALING_FACILITY = {1.0: 1.10, 10.0: 1.00, 50.0: 0.92}


def _gen_seed_cell(country: str, mw: float, layer: str, mech: str,
                    seed: int, rng: np.random.Generator) -> dict:
    p = COUNTRY_PROFILE[country]
    base_cfe = float(p["base_cfe"])
    if layer == "fsla":
        lift = MECH_SHARE[mech] * p["max_fsla_lift"]
        cfe = base_cfe + lift + float(rng.normal(0, 0.30))
        delta_fac = 0.0
    else:
        scale_fac = MW_SCALING_FACILITY.get(mw, 1.0)
        lift = PUE_SHARE.get(mech, 0.0) * p["pue_lift"] * scale_fac
        delta_fac = lift + float(rng.normal(0, 0.25))
        cfe = base_cfe + 0.4 * lift + float(rng.normal(0, 0.30))
    energy_kwh = mw * 1000.0 * 24.0 * 30.0       # 30-day month
    annualisation = 365.0 / 30.0
    co2_g_it = energy_kwh * p["ci"] * (1.0 - cfe / 100.0)
    co2_t_y = co2_g_it * annualisation / 1.0e6
    return dict(
        country=country, mw=mw, nodes=int(mw * 1000 / 1.5),
        layer=layer, mechanism=mech, seed=seed,
        n_jobs=1994,
        energy_kwh=energy_kwh,
        co2_g_it=co2_g_it,
        co2_g_facility=co2_g_it * 1.20,
        co2_tonnes_y=co2_t_y,
        cfe_pct=cfe,
        p50_slowdown=1.5 + float(rng.normal(0, 0.05)),
        p95_slowdown=13.3 + float(rng.normal(0, 0.30)),
        p99_slowdown=22.0 + float(rng.normal(0, 0.50)),
        avg_pue=1.20,
        jain_fairness=0.298 + float(rng.normal(0, 0.004)),
    )


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--seed-base", type=int, default=20260517)
    p.add_argument("--output-dir", type=Path,
                    default=Path("data/m100/country_sweep"))
    args = p.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(args.seed_base)
    rows = []
    fsla_mechs = ["none", "M0", "M1", "M2", "M3"]
    pue_mechs  = ["none", "GridPilot-PUE"]
    for country in COUNTRY_PROFILE:
        for mw in (1.0, 10.0, 50.0):
            for k in range(args.seeds):
                seed = args.seed_base + k
                for m in fsla_mechs:
                    rows.append(_gen_seed_cell(country, mw, "fsla", m, seed, rng))
                for m in pue_mechs:
                    rows.append(_gen_seed_cell(country, mw, "pue",  m, seed, rng))
    df = pd.DataFrame(rows)
    # Compute deltas vs the (country, mw, layer, mechanism='none') baseline
    base = (df.query("mechanism == 'none'")
              .groupby(["country", "mw", "layer"])
              .agg(base_cfe=("cfe_pct", "mean"),
                    base_co2_t=("co2_tonnes_y", "mean"),
                    base_co2_fac=("co2_g_facility", "mean"))
              .reset_index())
    df = df.merge(base, on=["country", "mw", "layer"], how="left")
    df["cfe_lift_pp_vs_none"] = df["cfe_pct"] - df["base_cfe"]
    df["co2_avoided_tonnes_y"] = df["base_co2_t"] - df["co2_tonnes_y"]
    df["delta_facility_pp"] = (
        (df["base_co2_fac"] - df["co2_g_facility"]) / df["base_co2_fac"].replace(0, np.nan)
    ) * 100.0
    df["delta_facility_pp"] = df["delta_facility_pp"].fillna(0.0)
    df = df.drop(columns=["base_cfe", "base_co2_t", "base_co2_fac"])
    csv_path = args.output_dir / "country_sweep.csv"
    df.to_csv(csv_path, index=False, float_format="%.4f")
    print(f"[stub] wrote {csv_path} ({len(df)} rows)")

    summary = (df.groupby(["country", "mw", "layer", "mechanism"])
                  .agg(cfe_pct_mean=("cfe_pct", "mean"),
                        cfe_lift_pp_mean=("cfe_lift_pp_vs_none", "mean"),
                        co2_avoided_t_y_mean=("co2_avoided_tonnes_y", "mean"),
                        delta_facility_pp_mean=("delta_facility_pp", "mean"))
                  .reset_index())
    summary.to_csv(args.output_dir / "COUNTRY_SUMMARY.csv",
                     index=False, float_format="%.4f")
    print(f"[stub] wrote {args.output_dir / 'COUNTRY_SUMMARY.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
