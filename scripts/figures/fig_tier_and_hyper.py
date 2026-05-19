#!/usr/bin/env python3
"""
scripts/figures/fig_tier_and_hyper.py
=======================================
Composed 2x2 figure for the PECS paper: per-tier CFE contribution
(T0..T5) and contract-hyperparameter sensitivity.

Inputs:
    data/m100/tier_sweep/TIER_SUMMARY.csv
    data/m100/hyper_sweep/HYPER_SUMMARY.csv

Output:
    figs/fig_tier_and_hyper.pdf

Panels:
  (a) Per-tier CFE lift vs T0 baseline, one bar per (tier, country)
  (b) Per-tier p95 slowdown (the cost of the lift)
  (c) Hyperparameter sensitivity: CFE-lift response curve per hyper
  (d) Slowdown vs CFE Pareto across hyperparameter settings

If either CSV is missing the corresponding panel is annotated
"(awaiting <sweep> run)" so the figure still compiles.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Country ordering and palette matched to fig_country_cfe_lift.py.
COUNTRIES = ["SE", "CH", "FR", "IT", "DE", "PL"]
COUNTRY_COLOR = {
    "SE": "#1a7c3a", "CH": "#54a564", "FR": "#92c98e",
    "IT": "#f0b86e", "DE": "#d96d3c", "PL": "#a83a1f",
}
TIERS = [0, 1, 2, 3, 4, 5]
TIER_NAMES = ["T0\nrigid", "T1\nhour", "T2\nday",
               "T3\nweek", "T4\nelastic", "T5\nspatial"]
HYPER_NAMES = {
    "alpha_scale":       "credit-schedule scale (alpha x )",
    "window_scale":      "deferral-window scale (W x )",
    "t4_envelope_scale": "T4 replica envelope scale",
    "short_job_s":       "short-job threshold (s)",
}


def _panel_a_per_tier_lift(ax, tier_df: pd.DataFrame, mw_focus: float):
    """Bar chart: per-tier CFE lift (pp vs T0) grouped by country."""
    if tier_df is None or tier_df.empty:
        ax.text(0.5, 0.5, "(awaiting tier sweep run)",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_title("(a) Per-tier CFE lift")
        ax.set_axis_off()
        return
    df = tier_df.query(f"abs(mw - {mw_focus}) < 1e-6").copy()
    width = 0.13
    x = np.arange(len(TIERS))
    for i, c in enumerate(COUNTRIES):
        sub = df[df["country"] == c].set_index("tier")["cfe_lift_pp_mean"]
        ys = [float(sub.get(t, 0.0)) for t in TIERS]
        ax.bar(x + (i - 2.5) * width, ys, width=width,
               color=COUNTRY_COLOR[c], label=c, edgecolor="white",
               linewidth=0.3)
    ax.set_xticks(x)
    ax.set_xticklabels(TIER_NAMES, fontsize=8)
    ax.axhline(0, color="0.5", lw=0.6)
    ax.set_ylabel("CFE lift (pp) vs T0 baseline")
    ax.set_title(f"(a) Per-tier CFE lift at {mw_focus:g} MW")
    ax.legend(loc="upper left", fontsize=7, ncol=3, framealpha=0.85)


def _panel_b_per_tier_slowdown(ax, tier_df: pd.DataFrame,
                                  mw_focus: float):
    """Bar chart: p95 slowdown per tier (the cost of the lift)."""
    if tier_df is None or tier_df.empty:
        ax.text(0.5, 0.5, "(awaiting tier sweep run)",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_title("(b) Per-tier p95 slowdown")
        ax.set_axis_off()
        return
    df = tier_df.query(f"abs(mw - {mw_focus}) < 1e-6").copy()
    width = 0.13
    x = np.arange(len(TIERS))
    for i, c in enumerate(COUNTRIES):
        sub = df[df["country"] == c].set_index("tier")["p95_slowdown_mean"]
        ys = [float(sub.get(t, 1.0)) for t in TIERS]
        ax.bar(x + (i - 2.5) * width, ys, width=width,
               color=COUNTRY_COLOR[c], edgecolor="white", linewidth=0.3)
    ax.set_xticks(x)
    ax.set_xticklabels(TIER_NAMES, fontsize=8)
    ax.axhline(1.0, color="0.5", lw=0.6)
    ax.set_ylabel("p95 slowdown (x )")
    ax.set_title(f"(b) Per-tier p95 slowdown at {mw_focus:g} MW")


def _panel_c_hyper_response(ax, hyper_df: pd.DataFrame):
    """Line plot: CFE-lift response curve, one line per hyperparameter."""
    if hyper_df is None or hyper_df.empty:
        ax.text(0.5, 0.5, "(awaiting hyperparameter sweep run)",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_title("(c) Hyperparameter sensitivity")
        ax.set_axis_off()
        return
    palette = {"alpha_scale": "#1f4e8c", "window_scale": "#1f7a37",
                "t4_envelope_scale": "#a83a1f",
                "short_job_s": "#7a4a00"}
    for hyper in sorted(hyper_df["hyper"].unique()):
        sub = hyper_df[hyper_df["hyper"] == hyper].sort_values("value")
        # Normalise x so all hypers share the same axis: divide by
        # the smallest non-zero value in the sub-frame.
        xs = sub["value"].values
        if xs.max() > 0:
            xs_norm = xs / xs[xs > 0].min()
        else:
            xs_norm = xs
        ax.plot(xs_norm, sub["cfe_pct_mean"], marker="o", lw=1.5,
                color=palette.get(hyper, "0.4"),
                label=HYPER_NAMES.get(hyper, hyper))
    ax.set_xlabel("hyperparameter value (normalised, log scale)")
    ax.set_xscale("log")
    ax.set_ylabel("mean CFE %")
    ax.set_title("(c) Hyperparameter sensitivity (one-at-a-time)")
    ax.legend(loc="best", fontsize=7)


def _panel_d_pareto(ax, hyper_df: pd.DataFrame):
    """Scatter: p95 slowdown vs CFE pct across all hyperparameter cells."""
    if hyper_df is None or hyper_df.empty:
        ax.text(0.5, 0.5, "(awaiting hyperparameter sweep run)",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_title("(d) Slowdown vs CFE Pareto")
        ax.set_axis_off()
        return
    palette = {"alpha_scale": "#1f4e8c", "window_scale": "#1f7a37",
                "t4_envelope_scale": "#a83a1f",
                "short_job_s": "#7a4a00"}
    for hyper in sorted(hyper_df["hyper"].unique()):
        sub = hyper_df[hyper_df["hyper"] == hyper]
        ax.scatter(sub["p95_slowdown_mean"], sub["cfe_pct_mean"],
                    color=palette.get(hyper, "0.4"), s=45,
                    label=HYPER_NAMES.get(hyper, hyper),
                    edgecolor="white", linewidth=0.5)
    ax.set_xlabel("p95 slowdown (x )")
    ax.set_ylabel("mean CFE %")
    ax.set_title("(d) Slowdown vs CFE Pareto across hyperparameters")
    ax.legend(loc="best", fontsize=7)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tier-summary", type=Path,
                    default=Path("data/m100/tier_sweep/TIER_SUMMARY.csv"))
    p.add_argument("--hyper-summary", type=Path,
                    default=Path("data/m100/hyper_sweep/HYPER_SUMMARY.csv"))
    p.add_argument("--mw-focus", type=float, default=10.0)
    p.add_argument("--out", type=Path,
                    default=Path("figs/fig_tier_and_hyper.pdf"))
    args = p.parse_args(argv)

    tier_df = (pd.read_csv(args.tier_summary)
                if args.tier_summary.exists() else None)
    hyper_df = (pd.read_csv(args.hyper_summary)
                 if args.hyper_summary.exists() else None)

    fig, axes = plt.subplots(2, 2, figsize=(12.0, 8.0),
                              constrained_layout=True)
    _panel_a_per_tier_lift(axes[0, 0], tier_df, args.mw_focus)
    _panel_b_per_tier_slowdown(axes[0, 1], tier_df, args.mw_focus)
    _panel_c_hyper_response(axes[1, 0], hyper_df)
    _panel_d_pareto(axes[1, 1], hyper_df)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_tier_and_hyper] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
