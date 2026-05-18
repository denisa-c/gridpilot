#!/usr/bin/env python3
"""
scripts/figures/fig_multiscale_operational_only.py
==================================================

Publication-ready 2×2 multi-year, multi-scale projection figure
(operational-only — NO frequency-response component).

Replaces the previous fig_scale_time_1x4.pdf with a clean version
that the PECS 2026 paper (post-FFR removal) cites.

Inputs
------
  data/multiyear_50mw_operational_only.csv  (from scripts/projection/multiyear_50mw.py)

Output
------
  figs/fig_multiyear_operational.pdf
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt

mpl.rcParams.update({
    "font.family": "serif", "font.size": 9.0,
    "axes.titlesize": 9.5, "axes.labelsize": 9.0,
    "xtick.labelsize": 8.0, "ytick.labelsize": 8.0,
    "legend.fontsize": 8.0, "axes.linewidth": 0.7,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})

GRID_COLORS = {"CH": "#3a7bd5", "IT": "#7ab84a", "DE": "#d96a3a"}


def panel_a_by_grid_by_year(ax, df: pd.DataFrame) -> None:
    ax.set_title(r"(a) Operational-only CO$_2$ reduction (50 MW, 3 grids)",
                  loc="left", pad=4)
    years = sorted(df["year"].unique())
    width = 0.25
    x = np.arange(len(years))
    for i, grid in enumerate(("CH", "IT", "DE")):
        sub = df[df["grid"] == grid].sort_values("year")
        ax.bar(x + (i - 1) * width, sub["operational_pct"].values,
                width=width, color=GRID_COLORS[grid], alpha=0.85,
                edgecolor="white", linewidth=0.5, label=grid)
    ax.set_xticks(x); ax.set_xticklabels([str(y) for y in years])
    ax.set_ylabel("Reduction (%)")
    ax.legend(loc="upper left", frameon=False)


def panel_b_trajectory(ax, df: pd.DataFrame) -> None:
    ax.set_title("(b) Trajectory by grid (operational only)", loc="left", pad=4)
    for grid in ("CH", "IT", "DE"):
        sub = df[df["grid"] == grid].sort_values("year")
        ax.plot(sub["year"], sub["operational_pct"], marker="o",
                 color=GRID_COLORS[grid], linewidth=1.2, markersize=5,
                 label=grid)
        for _, row in sub.iterrows():
            ax.annotate(f"{row['operational_pct']:.1f}",
                         xy=(row["year"], row["operational_pct"]),
                         xytext=(0, 6), textcoords="offset points",
                         fontsize=7, ha="center", color=GRID_COLORS[grid])
    ax.set_ylabel("Reduction (%)"); ax.set_xlabel("Year")
    ax.legend(loc="lower right", frameon=False)


def panel_c_absolute(ax, df: pd.DataFrame) -> None:
    ax.set_title("(c) Absolute daily savings (50 MW)", loc="left", pad=4)
    years = sorted(df["year"].unique()); x = np.arange(len(years)); width = 0.25
    for i, grid in enumerate(("CH", "IT", "DE")):
        sub = df[df["grid"] == grid].sort_values("year")
        ax.bar(x + (i - 1) * width, sub["saved_t_co2_per_day"].values,
                width=width, color=GRID_COLORS[grid], alpha=0.85,
                edgecolor="white", linewidth=0.5, label=grid)
    ax.set_xticks(x); ax.set_xticklabels([str(y) for y in years])
    ax.set_ylabel(r"Daily savings (t CO$_2$ / day)")


def panel_d_ci_trajectory(ax, df: pd.DataFrame) -> None:
    ax.set_title("(d) Grid CI trajectories (g/kWh)", loc="left", pad=4)
    for grid in ("CH", "IT", "DE"):
        sub = df[df["grid"] == grid].sort_values("year")
        ax.plot(sub["year"], sub["ci_g_per_kwh"], marker="s",
                 color=GRID_COLORS[grid], linewidth=1.2, markersize=5,
                 label=grid)
    ax.axvspan(2025, 2032, alpha=0.10, color="grey", label="Deployment window")
    ax.set_xlabel("Year"); ax.set_ylabel("Grid CI (g/kWh)")
    ax.legend(loc="upper right", frameon=False)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in-csv", type=Path,
                   default=Path("data/multiyear_50mw_operational_only.csv"))
    p.add_argument("--out", type=Path,
                   default=Path("figs/fig_multiyear_operational.pdf"))
    args = p.parse_args(argv)
    df = pd.read_csv(args.in_csv)
    fig, axs = plt.subplots(2, 2, figsize=(6.7, 5.0), constrained_layout=True)
    panel_a_by_grid_by_year(axs[0, 0], df)
    panel_b_trajectory(axs[0, 1], df)
    panel_c_absolute(axs[1, 0], df)
    panel_d_ci_trajectory(axs[1, 1], df)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    print(f"[fig_multiyear_operational] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
