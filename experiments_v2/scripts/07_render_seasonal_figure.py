#!/usr/bin/env python3
"""
experiments_v2/scripts/07_render_seasonal_figure.py
====================================================
Phase 5c — render the 2×2 fig_proact_1x4-style figure.

Panels (left-to-right, top-to-bottom):
  (a) CFE adoption surface   — analytical contour; equilibrium Ω*.
  (b) CO₂ savings by country and season  — bar chart from
      data/seasonal_sweep/SEASONAL_SUMMARY.csv.
  (c) Summer CI diurnal profiles for CH/IT/DE  — real ENTSO-E
      hourly data when present (gridpilot/data/ci/entsoe/),
      synthesised from per-country YAML otherwise.
  (d) Pareto front across all (country × season × layer × seed)
      cells — (mean slowdown, net CO₂ reduction) from the same
      seasonal_sweep CSV.

Missing data → that panel shows an "(awaiting <input>)" placeholder
so the figure compiles cleanly during incremental build-out.

Usage:
  PYTHONPATH=gridpilot/experiments_v2/src python3 \\
      gridpilot/experiments_v2/scripts/07_render_seasonal_figure.py \\
      --seasonal-csv gridpilot/experiments_v2/data/seasonal_sweep/seasonal_sweep.csv \\
      --out          gridpilot/experiments_v2/figs/fig_proact_1x4_v2.pdf
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
GRIDPILOT = ROOT / "gridpilot"
ENTSOE_DIR = GRIDPILOT / "data" / "ci" / "entsoe"
GRIDS_DIR  = GRIDPILOT / "configs" / "grids"

# Match the reference figure's palette.
COLORS = {"CH": "#1f77b4", "IT": "#2ca02c", "DE": "#d62728"}
COUNTRIES = ["CH", "IT", "DE"]
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
SUMMER_ANCHOR = datetime(2025, 7, 15, tzinfo=timezone.utc)

plt.rcParams.update({
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "font.family": "serif", "font.size": 11,
    "axes.titlesize": 12, "axes.labelsize": 11, "legend.fontsize": 9,
    "xtick.labelsize": 9, "ytick.labelsize": 9,
    "axes.spines.top": False, "axes.spines.right": False,
})


def _placeholder(ax, msg: str) -> None:
    ax.text(0.5, 0.5, msg, ha="center", va="center", transform=ax.transAxes,
             fontsize=11, color="#888", style="italic")
    ax.set_xticks([]); ax.set_yticks([])


# ─────────────────────────────────────────────────────────────────────
# Panel (a) — analytical CFE adoption surface (no data needed)
# ─────────────────────────────────────────────────────────────────────

def panel_a(ax) -> None:
    x = np.linspace(0, 1, 80)
    y = np.linspace(0, 1, 80)
    X, Y = np.meshgrid(x, y)
    # CFE score = sigmoid(8(XY - 0.3)) — Bass-style diffusion of CFE
    # adoption × CFE penetration around the equilibrium Ω* where
    # XY = 0.3 (Φ⁻¹(0.5)).
    Z = 1.0 / (1.0 + np.exp(-8 * (X * Y - 0.3)))
    cs = ax.contourf(X, Y, Z, levels=12, cmap="viridis", alpha=0.85)
    # Equilibrium contour Ω*: XY = 0.3.
    ax.contour(X, Y, X * Y - 0.3, levels=[0], colors="red", linewidths=2.0)
    # Mark Ω*.
    ax.text(0.78, 0.52, r"$\Omega^*$", color="white", fontsize=11,
             fontweight="bold",
             bbox=dict(boxstyle="circle", facecolor="red", alpha=0.85))
    ax.set_xlabel("CFE penetration")
    ax.set_ylabel("Adoption rate")
    ax.set_title("(a) CFE adoption surface")
    cb = plt.colorbar(cs, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("CFE score", fontsize=9)
    cb.ax.tick_params(labelsize=8)


# ─────────────────────────────────────────────────────────────────────
# Panel (b) — CO₂ savings by country × season (from seasonal_sweep)
# ─────────────────────────────────────────────────────────────────────

def panel_b(ax, seasonal_csv: Optional[Path]) -> None:
    if seasonal_csv is None or not seasonal_csv.exists():
        _placeholder(ax, "(awaiting seasonal sweep run)")
        ax.set_title("(b) Savings by country and season")
        return
    df = pd.read_csv(seasonal_csv)
    # We want net CO₂ reduction (%) for the headline layer (fsla_M3)
    # vs the FCFS baseline within each (country, season).
    if df.empty:
        _placeholder(ax, "(empty seasonal CSV)")
        ax.set_title("(b) Savings by country and season")
        return

    # Per (country, season, layer) means over seeds.
    means = df.groupby(["country", "season", "layer"],
                       as_index=False)["co2_g_facility"].mean()
    # Pivot to wide format for the bar chart.
    pivot = means.pivot_table(index=["country", "season"],
                              columns="layer", values="co2_g_facility")
    if "fcfs" not in pivot.columns or "fsla_M3" not in pivot.columns:
        _placeholder(ax, "(missing fcfs or fsla_M3 layer)")
        ax.set_title("(b) Savings by country and season")
        return
    pivot["reduction_pct"] = 100.0 * (1.0 - pivot["fsla_M3"] / pivot["fcfs"])
    pivot = pivot.reset_index()

    width = 0.25
    xp = np.arange(len(SEASONS))
    for i, c in enumerate(COUNTRIES):
        vals = []
        for s in SEASONS:
            sub = pivot[(pivot["country"] == c) & (pivot["season"] == s)]
            vals.append(float(sub["reduction_pct"].iloc[0]) if not sub.empty else 0.0)
        ax.bar(xp + (i - 1) * width, vals, width, label=c,
                color=COLORS[c], edgecolor="white", linewidth=0.6)
    ax.set_xticks(xp); ax.set_xticklabels(SEASONS)
    ax.set_ylabel(r"Net CO$_2$ reduction (%)")
    ax.set_title("(b) Savings by country and season")
    ax.legend(frameon=False, loc="best", ncol=3)


# ─────────────────────────────────────────────────────────────────────
# Panel (c) — Summer CI diurnal profiles (ENTSO-E or synth)
# ─────────────────────────────────────────────────────────────────────

def _entsoe_summer_diurnal(country: str) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Return (hours, mean_CI, std_CI) for the country's summer week
    centred on SUMMER_ANCHOR, from local ENTSO-E parquet.
    Returns None if no data."""
    p = ENTSOE_DIR / f"{country}_hourly.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if "carbon_intensity_gCO2eq_per_kWh" not in df.columns:
        return None
    df.index = pd.to_datetime(df.index, utc=True)
    # Take ±3 days around the anchor → 7 days of hourly data for diurnal averaging.
    start = SUMMER_ANCHOR - timedelta(days=3)
    end   = SUMMER_ANCHOR + timedelta(days=4)
    win = df.loc[(df.index >= start) & (df.index < end),
                  "carbon_intensity_gCO2eq_per_kWh"]
    if len(win) < 24:
        return None
    # Group by hour-of-day; compute mean + std.
    by_hour = win.groupby(win.index.hour)
    hours = np.arange(24)
    means = by_hour.mean().reindex(hours).to_numpy()
    stds  = by_hour.std().reindex(hours).fillna(0.0).to_numpy()
    return hours, means, stds


def _synth_summer_diurnal(country: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Synthesise a 24-h CI profile from the per-country YAML's mean +
    a season-aware diurnal envelope.  Matches v1's reproduce_figures
    panel (c) parameterisation."""
    hours = np.arange(24)
    base_amp = {
        "CH": (30,  8),
        "IT": (258, 60),
        "DE": (295, 110),
    }
    b, a = base_amp.get(country, (200, 40))
    means = b + a * np.sin(2 * np.pi * (hours - 7) / 24) ** 2
    stds  = means * 0.15
    return hours, means, stds


def panel_c(ax) -> None:
    have_real_for = []
    for c in COUNTRIES:
        result = _entsoe_summer_diurnal(c)
        if result is not None:
            hours, means, stds = result
            tag = " (ENTSO-E)"
            have_real_for.append(c)
        else:
            hours, means, stds = _synth_summer_diurnal(c)
            tag = " (synth)"
        ax.plot(hours, means, label=f"{c}{tag}", color=COLORS[c], linewidth=2.0)
        ax.fill_between(hours, means - stds, means + stds,
                         color=COLORS[c], alpha=0.18)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel(r"Carbon intensity (g CO$_2$/kWh)")
    ax.set_title("(c) Summer CI diurnal profiles")
    ax.set_xticks([0, 6, 12, 18, 24])
    # log scale to match v1; works even for low-CI grids like CH.
    ax.set_yscale("log")
    ax.legend(frameon=False, loc="center right")
    ax.grid(alpha=0.2, which="both")


# ─────────────────────────────────────────────────────────────────────
# Panel (d) — Pareto front (slowdown, CO₂ reduction) across cells
# ─────────────────────────────────────────────────────────────────────

def panel_d(ax, seasonal_csv: Optional[Path]) -> None:
    if seasonal_csv is None or not seasonal_csv.exists():
        _placeholder(ax, "(awaiting seasonal sweep run)")
        ax.set_title("(d) Pareto front")
        return
    df = pd.read_csv(seasonal_csv)
    if df.empty:
        _placeholder(ax, "(empty seasonal CSV)")
        ax.set_title("(d) Pareto front")
        return

    # For each (country, season, seed), compute the per-layer
    # (p95_slowdown, co2_reduction_pct_vs_fcfs) point.  Pareto front
    # = the convex hull of points minimising slowdown for any given
    # reduction (and vice versa).
    base = (df[df["layer"] == "fcfs"]
            .set_index(["country", "season", "seed"])["co2_g_facility"])
    df = df.merge(
        base.rename("fcfs_co2_g").reset_index(),
        on=["country", "season", "seed"], how="left",
    )
    df["co2_reduction_pct"] = (
        100.0 * (1.0 - df["co2_g_facility"] / df["fcfs_co2_g"])
    )
    # We only care about non-FCFS rows (FCFS has zero reduction by def).
    pts = df[df["layer"] != "fcfs"]
    pts = pts.dropna(subset=["p95_slowdown", "co2_reduction_pct"])
    if pts.empty:
        _placeholder(ax, "(no non-FCFS cells)")
        ax.set_title("(d) Pareto front")
        return

    sd = pts["p95_slowdown"].to_numpy(dtype=float)
    sv = pts["co2_reduction_pct"].to_numpy(dtype=float)
    n = len(sd)
    ax.scatter(sd, sv, alpha=0.45, s=40, color="gray",
                edgecolor="black", linewidth=0.4,
                label=f"Scenarios (n={n})")

    # Pareto front: points where no other point has lower slowdown
    # AND higher reduction.
    pi = []
    for i in range(n):
        dominated = False
        for j in range(n):
            if j == i: continue
            if sd[j] <= sd[i] and sv[j] >= sv[i] and (sd[j] < sd[i] or sv[j] > sv[i]):
                dominated = True; break
        if not dominated:
            pi.append(i)
    pi = sorted(pi, key=lambda k: sd[k])
    if pi:
        ax.plot(sd[pi], sv[pi], "r-", linewidth=2.0, label="Pareto front")
        ax.scatter(sd[pi], sv[pi], color="red", s=60, zorder=5,
                    edgecolor="darkred", linewidth=0.5)

    mean_sd = float(np.mean(sd))
    ax.axvline(x=mean_sd, color="green", linestyle="--", alpha=0.6,
                label=fr"Mean $\approx${mean_sd:.1f}$\times$", linewidth=2.0)
    ax.set_xlabel("Mean slowdown (p95, 24 h cap)")
    ax.set_ylabel(r"Net CO$_2$ reduction (%)")
    ax.set_title(f"(d) Pareto front ({n} scenarios)")
    ax.set_xscale("log")
    ax.legend(frameon=False, loc="lower right")
    ax.grid(alpha=0.2, which="both")


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--seasonal-csv", type=Path, default=None,
                    help="Path to data/seasonal_sweep/seasonal_sweep.csv")
    p.add_argument("--out", type=Path, required=True,
                    help="Output PDF path")
    args = p.parse_args(argv)

    fig, axes = plt.subplots(2, 2, figsize=(12.0, 8.0),
                              constrained_layout=True)
    axes = axes.flatten()
    panel_a(axes[0])
    panel_b(axes[1], args.seasonal_csv)
    panel_c(axes[2])
    panel_d(axes[3], args.seasonal_csv)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, format="pdf")
    plt.close(fig)
    print(f"[07-seasonal-figure] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
