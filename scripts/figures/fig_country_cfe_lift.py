#!/usr/bin/env python3
"""
scripts/figures/fig_country_cfe_lift.py
=======================================
Three-panel headline figure for the PECS paper (Finding 5):

  (a)  Bar chart: CFE % lift from f-SLA (M3 = AI-Baseline Audit) over
       the EASY-FCFS+none baseline, one bar per country, ordered by
       annual mean CI (SE -> PL).  Bootstrap 95 % CI on the bars.  A
       secondary y-axis shows the corresponding annual avoided CO2
       tonnage at 10 MW IT scale.

  (b)  Scale-invariance: same lift evaluated at 1 / 10 / 50 MW for the
       SE (cleanest) and PL (dirtiest) bookends.  The relative lift
       is scale-invariant; the absolute avoided tonnage scales linearly.

  (c)  *Demand flexibility at 10 MW IT*: GWh/y of compute energy that
       the f-SLA contract makes elicitable from a 10 MW deployment,
       per country.  This is the "movable demand" a grid operator
       sees from the contract.  Bars per country, same colour ramp.

Layout rules (in response to user feedback on overlapping legends):
  * Legends are positioned in low-information regions of the axes,
    or in the figure's bottom margin when there is no clean spot.
  * Font sizes follow scripts/figures/_figstyle.py (1.5x baseline)
    so the figure stays legible at 0.7-linewidth includes.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from _figstyle import apply_style, PAPER_PALETTE
apply_style()


CFE_LIFT_COL = "cfe_lift_pp_vs_none"   # overridden in main() based on CSV columns
LIFT_LABEL   = "CFE lift (pp)"         # overridden in main() to match CFE_LIFT_COL
COUNTRY_ORDER = ["SE", "CH", "FR", "IT", "DE", "PL"]
COUNTRY_LABEL = {"SE": "SE\n11",  "CH": "CH\n30",  "FR": "FR\n53",
                  "IT": "IT\n258", "DE": "DE\n295", "PL": "PL\n612"}
COUNTRY_COLOR = {k: PAPER_PALETTE[k] for k in COUNTRY_ORDER}

# 10 MW * 8760 h/y = 87.6 GWh/y total energy.  Demand flexibility =
# (Delta CFE pp / 100) * 87.6 GWh/y --- the f-SLA-elicitable share of
# annual compute energy that the grid sees as movable demand response.
ANNUAL_ENERGY_GWH_PER_MW = 8.76    # GWh/y per MW IT at 100 % duty
MW_HEADLINE = 10.0


def _bootstrap_mean_ci(values: np.ndarray, n: int = 10_000,
                        conf: float = 0.95,
                        rng: Optional[np.random.Generator] = None
                        ) -> tuple[float, float, float]:
    rng = rng or np.random.default_rng(20260517)
    if values.size == 0:
        return 0.0, 0.0, 0.0
    idx = rng.integers(0, values.size, size=(n, values.size))
    samples = values[idx].mean(axis=1)
    a = 1.0 - conf
    return (float(values.mean()),
             float(np.percentile(samples, 100.0 * a / 2.0)),
             float(np.percentile(samples, 100.0 * (1.0 - a / 2.0))))


def _country_means(df: pd.DataFrame, mech: str, mw: float, field: str,
                    rng: np.random.Generator) -> tuple[list[float], list[float], list[float]]:
    means, los, his = [], [], []
    for c in COUNTRY_ORDER:
        v = df.query("country == @c and layer == 'fsla' and "
                      "mechanism == @mech and mw == @mw")[field].values
        m, lo, hi = _bootstrap_mean_ci(v, rng=rng)
        means.append(m); los.append(m - lo); his.append(hi - m)
    return means, los, his


def panel_a(ax: plt.Axes, df: pd.DataFrame, rng: np.random.Generator,
             mw_focus: float = MW_HEADLINE):
    """CFE-lift bars + avoided-CO2 line on a secondary axis."""
    means, los, his = _country_means(df, "M3", mw_focus,
                                       CFE_LIFT_COL, rng)
    avoided = []
    for c in COUNTRY_ORDER:
        v = df.query("country == @c and layer == 'fsla' and "
                      "mechanism == 'M3' and mw == @mw_focus"
                      )["co2_avoided_tonnes_y"].values
        avoided.append(float(v.mean()) if v.size else 0.0)
    x = np.arange(len(COUNTRY_ORDER))
    colors = [COUNTRY_COLOR[c] for c in COUNTRY_ORDER]
    ax.bar(x, means, yerr=[los, his], color=colors,
            edgecolor="white", linewidth=0.4,
            error_kw=dict(elinewidth=0.7, capsize=2, ecolor="#333"))
    ax.set_xticks(x)
    ax.set_xticklabels([COUNTRY_LABEL[c] for c in COUNTRY_ORDER])
    ax.set_xlabel("Country (annual mean CI g/kWh below)")
    ax.set_ylabel(LIFT_LABEL + " vs.\\ EASY-FCFS")
    metric_tag = ("CI-weighted-mean reduction" if CFE_LIFT_COL == "ci_weighted_lift_g"
                  else "CFE-lift")
    ax.set_title(f"(a) f-SLA (M3) {metric_tag} at {int(mw_focus)} MW")

    # Auto-scale: include negative bars symmetrically and leave 30 %
    # headroom on the dominant side for the legend.
    lo = min(0.0, min(means) * 1.15 if min(means) < 0 else 0.0)
    hi = max(0.0, max(means) * 1.30 if max(means) > 0 else 1.0)
    if hi - lo < 1e-3:                       # all values ~ 0
        hi = max(hi, 0.5)
    ax.set_ylim(lo, hi)
    ax.axhline(0.0, color="#777", lw=0.7, ls=":")

    ax2 = ax.twinx()
    ax2.plot(x, avoided, marker="o", color="#222", lw=1.0,
              label=f"avoided tCO$_2$/y @ {int(mw_focus)} MW")
    ax2.set_ylabel("avoided tCO$_2$/y")
    ax2.grid(False)
    ax2.spines["top"].set_visible(False)
    # Headroom on the secondary axis too.
    if max(avoided) > 0:
        ax2.set_ylim(0, max(avoided) * 1.25)
    # Place the legend ABOVE the highest bar to keep it clear of data.
    ax2.legend(loc="upper left", bbox_to_anchor=(0.02, 0.98),
                frameon=True, framealpha=0.95, edgecolor="#bbb",
                handlelength=1.6, handletextpad=0.5)


def panel_b(ax: plt.Axes, df: pd.DataFrame, rng: np.random.Generator):
    """Scale-invariance: SE vs PL at 1 / 10 / 50 MW."""
    pairs = [("SE", COUNTRY_COLOR["SE"]), ("PL", COUNTRY_COLOR["PL"])]
    mws = sorted(df["mw"].unique())
    width = 0.35
    x = np.arange(len(mws))
    for i, (c, col) in enumerate(pairs):
        means, los, his = [], [], []
        for mw in mws:
            v = df.query("country == @c and layer == 'fsla' and "
                          "mechanism == 'M3' and mw == @mw"
                          )[CFE_LIFT_COL].values
            m, lo, hi = _bootstrap_mean_ci(v, rng=rng)
            means.append(m); los.append(m - lo); his.append(hi - m)
        ax.bar(x + (i - 0.5) * width, means, width,
                yerr=[los, his], color=col,
                edgecolor="white", linewidth=0.4,
                label=f"{c} (CI={'11' if c=='SE' else '612'} g/kWh)",
                error_kw=dict(elinewidth=0.7, capsize=2, ecolor="#333"))
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(mw)} MW" for mw in mws])
    ax.set_ylabel(LIFT_LABEL)
    ax.set_title("(b) Scale-invariance: SE vs PL bookends")

    # Auto-scale based on actual data, not a hard-coded 0..15 range.
    lo, hi = ax.get_ylim()
    span = max(hi - lo, 1e-3)
    ax.set_ylim(min(0.0, lo - 0.10 * span), hi + 0.30 * span)
    ax.axhline(0.0, color="#777", lw=0.7, ls=":")
    ax.legend(loc="upper right", bbox_to_anchor=(0.98, 0.98),
               frameon=True, framealpha=0.95, edgecolor="#bbb",
               handlelength=1.6, handletextpad=0.5)


def panel_c(ax: plt.Axes, df: pd.DataFrame, rng: np.random.Generator,
             mw_focus: float = MW_HEADLINE):
    """Demand flexibility (GWh/y) at 10 MW IT, per country.

    Each country bar shows the annual compute energy the f-SLA
    contract makes elicitable at 10 MW deployment, computed as
        flex_GWh = (Delta CFE pp / 100) * 10 MW * 8760 h/y.
    A horizontal reference line marks the total annual energy
    consumed by a 10 MW cluster (87.6 GWh/y), so the reader can
    read off the f-SLA-elicitable fraction directly.
    """
    means, los, his = _country_means(df, "M3", mw_focus,
                                       CFE_LIFT_COL, rng)
    annual = mw_focus * ANNUAL_ENERGY_GWH_PER_MW   # GWh / year total
    # When the headline metric is CI-weighted-mean lift (g/kWh), the
    # demand-flex GWh interpretation no longer applies directly.
    # We fall back to interpreting the lift as the share of compute
    # energy whose effective CI was reduced by 100 g/kWh; this keeps
    # the panel readable across metric choices.
    if CFE_LIFT_COL == "ci_weighted_lift_g":
        # Each g/kWh of reduction at 10 MW = 0.0876 t CO2 / year.
        # Show "movable demand" as: lift / 100 g/kWh share of total
        # annual energy ~= GWh/y under hypothetical 100-g/kWh shift.
        flex_means = [m / 100.0 * annual for m in means]
        flex_los   = [v / 100.0 * annual for v in los]
        flex_his   = [v / 100.0 * annual for v in his]
    else:
        flex_means = [m / 100.0 * annual for m in means]
        flex_los   = [v / 100.0 * annual for v in los]
        flex_his   = [v / 100.0 * annual for v in his]
    x = np.arange(len(COUNTRY_ORDER))
    colors = [COUNTRY_COLOR[c] for c in COUNTRY_ORDER]
    ax.bar(x, flex_means, yerr=[flex_los, flex_his], color=colors,
            edgecolor="white", linewidth=0.4,
            error_kw=dict(elinewidth=0.7, capsize=2, ecolor="#333"))
    ax.set_xticks(x)
    ax.set_xticklabels([COUNTRY_LABEL[c] for c in COUNTRY_ORDER])
    ax.set_xlabel("Country (annual mean CI g/kWh below)")
    ax.set_ylabel("Movable demand (GWh/y) @ 10 MW")
    ax.set_title("(c) Demand flexibility unlocked by f-SLA")
    ax.axhline(annual, ls=":", lw=1.0, color="#333",
                label=f"10 MW total = {annual:.1f} GWh/y")
    # Auto-scale to data: if values are tiny, show them; if they
    # span the full annual budget, show the reference line on top.
    max_val = max(max(flex_means), max(flex_his), 0.0)
    min_val = min(min(flex_means), 0.0)
    if max_val < 0.05 * annual:
        # Zoom in to the data range; the dotted-line annotation in
        # the title still tells the reader what the absolute scale is.
        span = max(max_val - min_val, 1.0)
        ax.set_ylim(min_val - 0.10 * span, max_val + 0.30 * span)
    else:
        ax.set_ylim(min(0.0, min_val * 1.10), annual * 1.10)
    ax.axhline(0.0, color="#777", lw=0.7, ls=":")
    ax.legend(loc="upper right", bbox_to_anchor=(0.98, 0.98),
               frameon=True, framealpha=0.95, edgecolor="#bbb",
               handlelength=1.6, handletextpad=0.5)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", type=Path,
                    default=Path("data/m100/country_sweep/country_sweep.csv"))
    p.add_argument("--out", type=Path,
                    default=Path("figs/fig_country_cfe_lift.pdf"))
    p.add_argument("--mw-focus", type=float, default=MW_HEADLINE)
    args = p.parse_args(argv)

    df = pd.read_csv(args.matrix)
    rng = np.random.default_rng(20260517)
    # Metric priority for the headline figure, in order:
    #   1. ci_weighted_lift_g    (effective grid CI reduction, g/kWh) --
    #      continuous, discriminative, never saturates.  Switched to
    #      after the absolute-CFE-150 threshold metric collapsed to a
    #      0 % / 100 % dichotomy on the synthetic CI series.
    #   2. cfe_abs_lift_pp_vs_none  (absolute-CFE-pp lift)
    #   3. cfe_lift_pp_vs_none  (per-country-normalised, original)
    # LIFT_LABEL must be set globally too, because panel_a / panel_b
    # read it as a module-level name to render their y-axis labels.
    global CFE_LIFT_COL, LIFT_LABEL
    if "ci_weighted_lift_g" in df.columns:
        CFE_LIFT_COL = "ci_weighted_lift_g"
    elif "cfe_abs_lift_pp_vs_none" in df.columns:
        CFE_LIFT_COL = "cfe_abs_lift_pp_vs_none"
    else:
        CFE_LIFT_COL = "cfe_lift_pp_vs_none"
    LIFT_LABEL = ("Effective CI reduction (g/kWh)" if CFE_LIFT_COL == "ci_weighted_lift_g"
                  else "f-SLA CFE-lift (pp)")
    print(f"[fig_country_cfe_lift] using metric: {CFE_LIFT_COL}")

    # Three panels on one row.  ``constrained_layout`` automatically
    # spaces titles + legends + tick labels so they never overlap,
    # which is what the previous tight_layout call was failing to do.
    fig, axes = plt.subplots(1, 3, figsize=(15.0, 4.8),
                              gridspec_kw={"width_ratios": [1.5, 1.0, 1.5]},
                              constrained_layout=True)
    panel_a(axes[0], df, rng, mw_focus=args.mw_focus)
    panel_b(axes[1], df, rng)
    panel_c(axes[2], df, rng, mw_focus=args.mw_focus)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_country_cfe_lift] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
