#!/usr/bin/env python3
"""
scripts/figures/fig_cfe_by_tier.py
==================================
Panel: carbon-free-energy (CFE %) per (policy, mechanism) cell, with
bootstrap 95% CI error bars and a sub-panel showing the per-tier CFE
breakdown for the GridPilot-PUE + M3 reference configuration.

Inputs
------
  data/m100/policy_matrix/policy_matrix.csv

Output
------
  figs/fig_cfe_by_tier.pdf

PECS Paper B Finding 4, hypothesis H1 (declared-tier lift survives
anti-gaming).
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt


from _figstyle import apply_style
apply_style()

POLICY_ORDER     = ["FCFS", "EASY", "SAF", "RLBackfilling", "GridPilot-PUE"]
MECHANISM_ORDER  = ["none", "M0", "M1", "M2", "M3"]
MECHANISM_LABELS = {"none": "no f-SLA", "M0": "M0 Posted", "M1": "M1 BlindTrust",
                     "M2": "M2 DAA", "M3": "M3 AI-Audit"}
# Colour palette: distinct hues per mechanism, ordered light → dark for
# accessibility (also reads as a luminance ramp in print).
MECHANISM_COLORS = {"none": "#bdbdbd", "M0": "#4a90e2", "M1": "#3a7d44",
                     "M2": "#e07a2e", "M3": "#a83232"}


def _bootstrap_mean_ci(values: np.ndarray, n_resamples: int = 10_000,
                        confidence: float = 0.95,
                        rng: Optional[np.random.Generator] = None) -> tuple[float, float, float]:
    rng = rng or np.random.default_rng(20260517)
    if values.size == 0:
        return 0.0, 0.0, 0.0
    idx = rng.integers(0, values.size, size=(n_resamples, values.size))
    samples = values[idx].mean(axis=1)
    alpha = 1.0 - confidence
    lo = float(np.percentile(samples, 100.0 * alpha / 2.0))
    hi = float(np.percentile(samples, 100.0 * (1.0 - alpha / 2.0)))
    return float(values.mean()), lo, hi


def panel_cfe_grouped_bars(ax: plt.Axes, df: pd.DataFrame, rng: np.random.Generator):
    """Grouped bar chart: x = policies, hue = mechanisms, y = CFE %."""
    n_pol = len(POLICY_ORDER)
    n_mec = len(MECHANISM_ORDER)
    width = 0.8 / n_mec
    x = np.arange(n_pol)
    for i, mech in enumerate(MECHANISM_ORDER):
        means, los, his = [], [], []
        for pol in POLICY_ORDER:
            cell = df.query("policy == @pol and mechanism == @mech")["cfe_pct"].values
            m, lo, hi = _bootstrap_mean_ci(cell, rng=rng)
            means.append(m); los.append(m - lo); his.append(hi - m)
        ax.bar(x + (i - n_mec / 2 + 0.5) * width, means,
                width, yerr=[los, his],
                color=MECHANISM_COLORS[mech], label=MECHANISM_LABELS[mech],
                edgecolor="white", linewidth=0.4,
                error_kw=dict(elinewidth=0.6, capsize=2, ecolor="#333"))
    ax.set_xticks(x)
    ax.set_xticklabels(POLICY_ORDER, rotation=20, ha="right")
    ax.set_ylabel("Carbon-Free Energy (CFE) %")
    ax.set_title("(a) CFE % by baseline policy × f-SLA mechanism (bootstrap 95 % CI)")
    ax.legend(loc="lower left", frameon=True, ncol=2, fontsize=7.5,
               handlelength=1.4, handletextpad=0.5, columnspacing=0.9,
               framealpha=0.95, edgecolor="#bbb")


def panel_delta_it_lift(ax: plt.Axes, df: pd.DataFrame, rng: np.random.Generator):
    """Δ_IT lift of each (GridPilot-PUE, M*) over GridPilot-PUE+none baseline."""
    base = df.query("policy == 'GridPilot-PUE' and mechanism == 'none'")["co2_g_it"]
    base_mean = float(base.mean()) if len(base) else 1.0
    mechs = ["M0", "M1", "M2", "M3"]
    means, los, his = [], [], []
    for m in mechs:
        cell = df.query("policy == 'GridPilot-PUE' and mechanism == @m")["co2_g_it"].values
        lifts = (base_mean - cell) / max(base_mean, 1.0) * 100.0
        mn, lo, hi = _bootstrap_mean_ci(lifts, rng=rng)
        means.append(mn); los.append(mn - lo); his.append(hi - mn)
    x = np.arange(len(mechs))
    ax.bar(x, means, yerr=[los, his],
            color=[MECHANISM_COLORS[m] for m in mechs],
            edgecolor="white", linewidth=0.4,
            error_kw=dict(elinewidth=0.6, capsize=2, ecolor="#333"))
    ax.axhline(2.0, ls="--", lw=0.7, color="#666", label="H1 threshold: 2 pp")
    ax.set_xticks(x)
    ax.set_xticklabels([MECHANISM_LABELS[m] for m in mechs], rotation=20, ha="right")
    ax.set_ylabel(r"$\Delta_{IT}$ lift over GridPilot-PUE (pp)")
    ax.set_title("(b) f-SLA mechanism lift: $\\Delta_{IT}$ vs. GridPilot-PUE+none")
    ax.legend(loc="upper right", frameon=True, fontsize=7.5,
               framealpha=0.95, edgecolor="#bbb")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", type=Path,
                    default=Path("data/m100/policy_matrix/policy_matrix.csv"))
    p.add_argument("--out", type=Path, default=Path("figs/fig_cfe_by_tier.pdf"))
    args = p.parse_args(argv)

    df = pd.read_csv(args.matrix)
    rng = np.random.default_rng(20260517)

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.4), gridspec_kw={"width_ratios": [1.6, 1.0]})
    panel_cfe_grouped_bars(axes[0], df, rng)
    panel_delta_it_lift(axes[1], df, rng)
    fig.tight_layout(w_pad=1.2)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_cfe_by_tier] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
