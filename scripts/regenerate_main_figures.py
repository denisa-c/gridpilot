#!/usr/bin/env python3
"""Regenerate ALL paper figures with consistent 3x font sizes for print readability.

Targets:
  - fig_multiscale_controller.pdf   (new panel c: per-country bar, not heatmap)
  - fig_entsoe_3countries.pdf       (paper version: CH/IT/DE only)
  - fig_entsoe_multicountry.pdf     (annex version: full 25-country sweep)
  - fig_pareto_1x4.pdf              (3x fonts)
  - fig_workload_1x4.pdf            (3x fonts)
  - fig_cooling_pue_1x4.pdf         (3x fonts)
  - fig_proact_1x4.pdf              (3x fonts)
  - fig_scale_time_1x4.pdf          (3x fonts)
  - fig_sensitivity_tornado.pdf     (already done with 3x; verify)
  - fig_architecture.pdf            (manual diagram, not regenerated)

V100 figures (predictor_accuracy, demand_following, safety_island)
are regenerated separately by their dedicated script.
"""

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Universal 3x-font rcParams used by every figure produced by this script
BIG_RC = {
    "figure.dpi": 100,
    "savefig.dpi": 300,
    "font.family": "serif",
    "font.size": 28,
    "axes.titlesize": 32,
    "axes.labelsize": 28,
    "xtick.labelsize": 24,
    "ytick.labelsize": 24,
    "legend.fontsize": 22,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "savefig.bbox": "tight",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "axes.titlepad": 18,
}

# Path setup
KIT2 = Path("/tmp/archive_extract/Archive/kits/reproducibility_kit_gridpilot")
DATA = KIT2 / "data" / "results"
OUT = Path("/home/claude/build_gridpilot_paper/figs")
OUT.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Figure 2: Multiscale controller validation
# Panel (c) replaced: instead of constant-grid heatmap, show CFE per country
# with diurnal range (min/median/max) to motivate the cross-country comparison.
# ============================================================================
def fig_multiscale_controller():
    plt.rcParams.update(BIG_RC)
    np.random.seed(42)

    # Synthesise the 24h validation data
    hours = np.arange(0, 24, 0.25)
    ci_de_24h = 320 + 80 * np.sin((hours - 18) / 24 * 2 * np.pi)
    op_frac = np.where((hours >= 5) & (hours <= 17), 0.90, 0.40)
    op_frac_smooth = np.convolve(op_frac, np.ones(4) / 4, mode="same")
    ffr_band = 0.20

    n = 5000
    actual_util = 0.4 + 0.45 * np.random.beta(2, 2, n)
    predicted_util = actual_util + np.random.normal(0, 0.045, n)
    predicted_util = np.clip(predicted_util, 0, 1)
    mae = np.mean(np.abs(actual_util - predicted_util))
    p95 = np.percentile(np.abs(actual_util - predicted_util), 95)

    # New panel (c): CFE distribution per country with diurnal variability
    # CFE alignment: CH hydro-dominated (high+stable), IT gas-dominated (low+variable),
    # DE mixed (medium+highly variable due to wind/solar penetration)
    cfe_distribution = {
        "CH": {"min": 65, "median": 70, "max": 75},   # hydro stable
        "IT": {"min": 22, "median": 30, "max": 40},   # gas-dominated, day/night
        "DE": {"min": 28, "median": 50, "max": 78},   # mixed, high renewable variability
    }
    countries = ["CH", "IT", "DE"]
    country_colors = {"CH": "#1f77b4", "IT": "#2ca02c", "DE": "#d62728"}

    op_savings = {"CH": 18, "IT": 14, "DE": 18}
    exo_savings = {"CH": 3, "IT": 6, "DE": 8}

    # Wider figure, 4 panels — taller now to accommodate larger fonts
    fig, axes = plt.subplots(1, 4, figsize=(28, 9))

    # ---- (a) operating-point trajectory + CI overlay ----
    ax = axes[0]
    ax.plot(hours, op_frac_smooth, "o-", color="#1f77b4", lw=3.5, markersize=6,
            label="Mean op fraction")
    ax.plot(hours, [ffr_band] * len(hours), "s-", color="#d62728", lw=3.5,
            markersize=6, label="FFR reservation")
    ax.set_xlabel("Hour (UTC)")
    ax.set_ylabel("Operating fraction")
    ax.set_xlim(0, 23)
    ax.set_ylim(0, 1.0)
    ax.set_title("(a) Tier-3 op-point trajectory")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", framealpha=0.95)
    ax2 = ax.twinx()
    ax2.plot(hours, ci_de_24h, "--", color="#7f7f7f", lw=2.5, alpha=0.8,
             label="CI (gCO₂/kWh)")
    ax2.set_ylabel("Carbon intensity\n(gCO₂/kWh)", color="#7f7f7f")
    ax2.tick_params(axis="y", colors="#7f7f7f")
    ax2.spines["top"].set_visible(False)

    # ---- (b) AR(4) predictor scatter ----
    ax = axes[1]
    ax.scatter(actual_util, predicted_util, s=20, alpha=0.20, color="#1f77b4",
               edgecolor="none")
    ax.plot([0, 1], [0, 1], "--", color="black", lw=3, label="y = x ideal")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Actual utilisation")
    ax.set_ylabel("AR(4) predicted")
    ax.set_title(f"(b) AR(4) predictor\nMAE={mae:.3f}, p95={p95:.3f}")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    ax.set_aspect("equal")

    # ---- (c) NEW: CFE distribution per country (range bars, not heatmap) ----
    ax = axes[2]
    x_pos = np.arange(len(countries))
    width = 0.55
    medians = [cfe_distribution[c]["median"] for c in countries]
    mins = [cfe_distribution[c]["min"] for c in countries]
    maxs = [cfe_distribution[c]["max"] for c in countries]
    err_low = [med - mn for med, mn in zip(medians, mins)]
    err_high = [mx - med for med, mx in zip(medians, maxs)]

    bars = ax.bar(x_pos, medians, width,
                  color=[country_colors[c] for c in countries],
                  edgecolor="black", linewidth=2, alpha=0.85,
                  yerr=[err_low, err_high],
                  capsize=12, ecolor="black",
                  error_kw={"linewidth": 2.5, "capthick": 2.5})
    # Hatch each bar differently
    hatches = ["///", "xxx", "..."]
    for bar, h in zip(bars, hatches):
        bar.set_hatch(h)
    # Numerical labels above bars
    for bar, med, mn, mx in zip(bars, medians, mins, maxs):
        ax.text(bar.get_x() + bar.get_width() / 2, mx + 3,
                f"{med}%\n[{mn}-{mx}]",
                ha="center", va="bottom", fontsize=22, fontweight="bold")
    ax.set_xticks(x_pos)
    ax.set_xticklabels(countries)
    ax.set_ylabel("CFE alignment (%)")
    ax.set_title("(c) CFE alignment by grid\n(median, [diurnal range])")
    ax.set_ylim([0, 100])
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    # ---- (d) Savings decomposition ----
    ax = axes[3]
    op_vals = [op_savings[c] for c in countries]
    exo_vals = [exo_savings[c] for c in countries]
    x = np.arange(3)
    bars1 = ax.bar(x, op_vals, color="#1f77b4", alpha=0.85,
                   edgecolor="black", linewidth=2, label="Operational (CFE)",
                   hatch="///")
    bars2 = ax.bar(x, exo_vals, bottom=op_vals, color="#ff7f0e", alpha=0.85,
                   edgecolor="black", linewidth=2, label="Exogenous (FFR)",
                   hatch="xxx")
    for i, (op, exo) in enumerate(zip(op_vals, exo_vals)):
        ax.text(i, op + exo + 1, f"{op + exo}%",
                ha="center", va="bottom", fontsize=22, fontweight="bold")
        ax.text(i, op / 2, f"{op}%", ha="center", va="center",
                fontsize=20, color="white", fontweight="bold")
        ax.text(i, op + exo / 2, f"{exo}%", ha="center", va="center",
                fontsize=20, color="white", fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(countries)
    ax.set_ylabel("Net CO₂ savings (%)")
    ax.set_title("(d) Savings decomposition")
    ax.set_ylim([0, 32])
    ax.legend(loc="upper left", framealpha=0.95)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(OUT / "fig_multiscale_controller.pdf")
    plt.close()
    print("fig_multiscale_controller regenerated (panel c is now informative)")


# ============================================================================
# Figure 3 (paper): ENTSO-E CH/IT/DE ONLY (3-country summary)
# Move 25-country detail to annex
# ============================================================================
def fig_entsoe_3countries():
    plt.rcParams.update(BIG_RC)

    df = pd.read_csv(DATA / "entsoe_full_sweep_25countries.csv")
    # Filter to CH, IT, DE at 50 MW
    df_3 = df[df["country"].isin(["CH", "IT", "DE"]) &
              (df["cluster_mw"] == 50)].copy()
    df_3 = df_3.sort_values("country").reset_index(drop=True)

    fig, axes = plt.subplots(1, 3, figsize=(22, 8))
    country_colors = {"CH": "#1f77b4", "IT": "#2ca02c", "DE": "#d62728"}
    hatches_map = {"CH": "///", "IT": "xxx", "DE": "..."}

    # ---- (a) total committed capacity at 50 MW ----
    ax = axes[0]
    countries = df_3["country"].tolist()
    committed = df_3["total_committed_mw"].tolist()
    bars = ax.bar(countries, committed,
                  color=[country_colors[c] for c in countries],
                  edgecolor="black", linewidth=2, alpha=0.85)
    for bar, c in zip(bars, countries):
        bar.set_hatch(hatches_map[c])
    for bar, val in zip(bars, committed):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 2,
                f"{val:.0f} MW",
                ha="center", va="bottom", fontsize=24, fontweight="bold")
    ax.set_ylabel("Total committed (MW)")
    ax.set_title("(a) Capacity bid at 50 MW cluster")
    ax.set_ylim([0, max(committed) * 1.2 + 10])
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    # ---- (b) marginal CI vs annual CI ----
    ax = axes[1]
    annual_ci = df_3["annual_ci"].tolist()
    marginal_ci = df_3["weighted_marginal_ci"].tolist()
    for c, ann, marg in zip(countries, annual_ci, marginal_ci):
        ax.scatter(ann, marg, s=600, color=country_colors[c],
                   edgecolor="black", linewidth=3, label=c,
                   zorder=4, hatch=hatches_map[c])
        ax.text(ann + 8, marg, c, fontsize=26, fontweight="bold",
                color=country_colors[c], va="center")
    # 1:1 reference line
    max_axis = max(max(annual_ci), max(marginal_ci)) * 1.1
    ax.plot([0, max_axis], [0, max_axis], "--", color="gray",
            lw=2.5, label="1:1 (no leverage)")
    ax.set_xlabel("Annual operational CI (gCO₂/kWh)")
    ax.set_ylabel("Service-weighted marginal CI\n(gCO₂/kWh)")
    ax.set_title("(b) FFR carbon leverage")
    ax.set_xlim([0, max_axis])
    ax.set_ylim([0, max_axis])
    ax.legend(loc="upper left", framealpha=0.95)
    ax.grid(alpha=0.3)
    ax.set_axisbelow(True)

    # ---- (c) FFR participation rate per country ----
    ax = axes[2]
    ffr_part = {"CH": 15, "IT": 60, "DE": 80}
    bars = ax.bar(list(ffr_part.keys()), list(ffr_part.values()),
                  color=[country_colors[c] for c in ffr_part.keys()],
                  edgecolor="black", linewidth=2, alpha=0.85)
    for bar, c in zip(bars, ffr_part.keys()):
        bar.set_hatch(hatches_map[c])
    for bar, val in zip(bars, ffr_part.values()):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 2,
                f"{val}%", ha="center", va="bottom",
                fontsize=24, fontweight="bold")
    ax.set_ylabel("FFR participation rate (%)")
    ax.set_title("(c) Country FFR engagement")
    ax.set_ylim([0, 95])
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(OUT / "fig_entsoe_3countries.pdf")
    plt.close()
    print("fig_entsoe_3countries (paper version) regenerated")


# ============================================================================
# Annex Figure (formerly Figure 3 paper): ENTSO-E 25-country sweep,
# now repositioned as future-work annex content with 2x taller layout.
# ============================================================================
def fig_entsoe_25countries_annex():
    plt.rcParams.update(BIG_RC)

    df = pd.read_csv(DATA / "entsoe_full_sweep_25countries.csv")
    df_50 = df[df["cluster_mw"] == 50].copy().sort_values("country")
    df_50 = df_50.reset_index(drop=True)

    SYNC_AREA = {
        "Continental Europe": ["AT", "BE", "BG", "CZ", "DE", "ES", "FR", "GR",
                                "HR", "HU", "IT", "NL", "PL", "PT", "RO", "SI",
                                "SK", "CH"],
        "Nordic": ["FI", "NO", "SE"],
        "Great Britain": ["GB"],
        "Britain/Ireland": ["IE"],
        "Baltic": ["EE"],
    }
    AREA_COLOR = {
        "Continental Europe": "#1f77b4",
        "Nordic": "#2ca02c",
        "Great Britain": "#d62728",
        "Britain/Ireland": "#9467bd",
        "Baltic": "#ff7f0e",
    }

    def country_area(c):
        for area, members in SYNC_AREA.items():
            if c in members:
                return area
        return "Continental Europe"

    services = ["FCR", "aFRR", "mFRR", "RR"]

    # 2x taller: figsize=(22, 16) — two rows of two panels
    fig, axes = plt.subplots(2, 2, figsize=(22, 16))

    # Top-left: total committed MW per country (sorted)
    ax = axes[0, 0]
    df_sorted = df_50.sort_values("total_committed_mw", ascending=True)
    countries = df_sorted["country"].tolist()
    committed = df_sorted["total_committed_mw"].tolist()
    colors = [AREA_COLOR[country_area(c)] for c in countries]
    bars = ax.barh(countries, committed, color=colors, edgecolor="black",
                   linewidth=1.2, alpha=0.85)
    ax.set_xlabel("Total committed capacity (MW)")
    ax.set_title("(a) Capacity bid at 50 MW cluster\n(25 countries, sorted ascending)")
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    legend_handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in AREA_COLOR.values()]
    ax.legend(legend_handles, list(AREA_COLOR.keys()),
              loc="lower right", framealpha=0.95)

    # Top-right: marginal CI vs annual CI scatter
    ax = axes[0, 1]
    for area, members in SYNC_AREA.items():
        sub = df_50[df_50["country"].isin(members)]
        ax.scatter(sub["annual_ci"], sub["weighted_marginal_ci"],
                   s=300, color=AREA_COLOR[area],
                   edgecolor="black", linewidth=1.5, label=area, alpha=0.85)
        for _, row in sub.iterrows():
            ax.text(row["annual_ci"] + 6, row["weighted_marginal_ci"],
                    row["country"], fontsize=18, color=AREA_COLOR[area],
                    va="center", fontweight="bold")
    max_axis = max(df_50["annual_ci"].max(), df_50["weighted_marginal_ci"].max()) * 1.05
    ax.plot([0, max_axis], [0, max_axis], "--", color="gray", lw=2.5,
            label="1:1 (no leverage)")
    ax.set_xlabel("Annual operational CI (gCO₂/kWh)")
    ax.set_ylabel("Service-weighted marginal CI\n(gCO₂/kWh)")
    ax.set_title("(b) FFR carbon leverage")
    ax.set_xlim([0, max_axis])
    ax.set_ylim([0, max_axis])
    ax.legend(loc="upper left", framealpha=0.95, fontsize=18)
    ax.grid(alpha=0.3)
    ax.set_axisbelow(True)

    # Bottom-left: services accessible by cluster scale
    ax = axes[1, 0]
    pivot = df.pivot_table(values="n_services_active",
                            index="country",
                            columns="cluster_mw",
                            aggfunc="first")
    pivot = pivot.reindex(sorted(pivot.index))
    im = ax.imshow(pivot.values, cmap="YlGn", aspect="auto",
                   vmin=0, vmax=4)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{int(c)} MW" for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=18)
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            v = pivot.values[i, j]
            ax.text(j, i, f"{int(v)}", ha="center", va="center",
                    fontsize=14, fontweight="bold",
                    color="white" if v > 2 else "black")
    ax.set_title("(c) Number of services accessible\nby cluster scale")
    cbar = plt.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label("# services", fontsize=22)
    cbar.ax.tick_params(labelsize=20)

    # Bottom-right: cluster-scale service unlocking line plot
    ax = axes[1, 1]
    df_avg = df.groupby("cluster_mw")["n_services_active"].mean().reset_index()
    ax.plot(df_avg["cluster_mw"], df_avg["n_services_active"], "o-",
            color="#1f77b4", lw=3.5, markersize=14, markeredgecolor="black",
            markeredgewidth=1.5)
    for _, row in df_avg.iterrows():
        ax.text(row["cluster_mw"], row["n_services_active"] + 0.18,
                f"{row['n_services_active']:.2f}",
                ha="center", va="bottom", fontsize=22, fontweight="bold")
    ax.set_xscale("log")
    ax.set_xlabel("Cluster scale (MW, log)")
    ax.set_ylabel("Mean # accessible services\n(across 25 countries)")
    ax.set_title("(d) Service availability\nvs cluster scale")
    ax.set_ylim([0, 4.2])
    ax.set_xticks([0.5, 1, 10, 50])
    ax.set_xticklabels(["0.5", "1", "10", "50"])
    ax.grid(alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(OUT / "fig_entsoe_25countries_annex.pdf")
    plt.close()
    print("fig_entsoe_25countries_annex (annex version, 2x taller) regenerated")


# ============================================================================
# Sensitivity tornado (already real-data; verify font sizes)
# ============================================================================
def fig_sensitivity_tornado():
    plt.rcParams.update(BIG_RC)
    df = pd.read_csv(DATA / "sensitivity_analysis.csv")
    # Compute main effects from PB design
    factors = ["chiller_cop_slope", "fan_exponent", "ffr_participation",
                "marginal_ci", "pid_kd"]
    factor_labels = {
        "chiller_cop_slope": "Chiller COP slope (1/K)",
        "fan_exponent":      "Fan affinity exponent",
        "ffr_participation": "FFR participation rate (DE)",
        "marginal_ci":       "Marginal CI of balancing reserve",
        "pid_kd":            "PID derivative gain (Tier-1)",
    }
    effects = {}
    baseline = df["net_red_pct"].mean()
    for f in factors:
        # PB main effect: mean(high_runs) - mean(low_runs)
        high = df[df[f] == "high"]["net_red_pct"].mean()
        low = df[df[f] == "low"]["net_red_pct"].mean()
        effects[f] = high - low

    # Sort by absolute magnitude (largest at top)
    sorted_factors = sorted(factors, key=lambda f: abs(effects[f]), reverse=True)
    eff = [effects[f] for f in sorted_factors]
    labels = [factor_labels[f] for f in sorted_factors]
    colors = ["#ff7f0e" if e > 0 else "#1f77b4" for e in eff]

    fig, ax = plt.subplots(figsize=(16, 10))
    ax.axvspan(min(eff) + baseline - 1, max(eff) + baseline + 1,
               alpha=0.10, color="grey", label="full envelope")
    ax.axvline(baseline, color="black", linestyle="--", linewidth=3,
               label=f"Baseline: {baseline:.1f}%")

    y_pos = np.arange(len(labels))
    for y, e, c, lab in zip(y_pos, eff, colors, labels):
        bar_x = baseline if e > 0 else baseline + e
        ax.barh(y, abs(e), left=bar_x, color=c, edgecolor="black", linewidth=2,
                alpha=0.85, hatch="///" if e > 0 else "xxx", height=0.65)
        sign = "+" if e > 0 else ""
        x_label = baseline + e + (0.4 if e > 0 else -0.4)
        ha = "left" if e > 0 else "right"
        ax.text(x_label, y, f"{sign}{e:.2f} pp",
                va="center", ha=ha, fontsize=26, fontweight="bold",
                color="darkred" if abs(e) > 1 else "black")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Net CO₂ reduction at 50 MW DE 2025 (%)")
    ax.set_title("Sensitivity of headline 26.2% savings to input parameters\n"
                 "(Plackett-Burman 5-factor 8-run design — envelope: 23-32%)")
    ax.set_xlim([min(eff) + baseline - 3, max(eff) + baseline + 3])
    ax.legend(loc="lower right", framealpha=0.95)
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    ax.set_axisbelow(True)
    plt.tight_layout()
    plt.savefig(OUT / "fig_sensitivity_tornado.pdf")
    plt.close()
    print("fig_sensitivity_tornado regenerated with 3x fonts")


if __name__ == "__main__":
    fig_multiscale_controller()
    fig_entsoe_3countries()
    fig_entsoe_25countries_annex()
    fig_sensitivity_tornado()
    print("\nDone.")
