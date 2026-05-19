#!/usr/bin/env python3
"""
scripts/figures/fig_joint_pareto.py
=====================================
Placeholder figure for the C2 paper's H1 (spatial and temporal
flexibility compound, not substitute).

Reads ``data/m100/spatial_sweep/spatial_sweep.csv`` plus the existing
``data/m100/country_sweep/country_sweep.csv`` (PECS baseline) and
plots the 2-axis Pareto in (mean slowdown, total egress + IT CO2 g).
The 3-axis (joint) variant lives here once the workflow-sweep CSV is
also available.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--spatial-csv", type=Path,
                    default=Path("data/m100/spatial_sweep/spatial_sweep.csv"))
    p.add_argument("--country-csv", type=Path,
                    default=Path("data/m100/country_sweep/country_sweep.csv"))
    p.add_argument("--out", type=Path,
                    default=Path("figs/fig_joint_pareto.pdf"))
    args = p.parse_args(argv)

    fig, ax = plt.subplots(figsize=(7.0, 4.5), constrained_layout=True)
    if args.spatial_csv.exists():
        df_s = pd.read_csv(args.spatial_csv)
        ax.scatter(df_s["egress_regime"],
                    df_s.get("egress_total_g_co2", 0.0),
                    c="#345fa8", label="spatial (T5)", alpha=0.6, s=30)
    if args.country_csv.exists():
        df_c = pd.read_csv(args.country_csv)
        ax.scatter([1.0] * len(df_c),
                    df_c.get("co2_g_facility", 0.0),
                    c="#1f7a37", label="temporal-only (PECS baseline)",
                    alpha=0.4, s=10)
    ax.set_xlabel("egress-cost regime multiplier")
    ax.set_ylabel("g CO2eq (egress for T5; facility for baseline)")
    ax.set_title("Joint spatial + temporal Pareto (placeholder; full 3D variant pending)")
    ax.legend(loc="upper left")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_joint_pareto] wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
