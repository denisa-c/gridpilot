#!/usr/bin/env python3
"""
scripts/figures/fig_fairness_pareto.py
======================================
Two-panel figure: (a) carbon-vs-fairness Pareto scatter across all
(policy × mechanism) cells; (b) Jain-fairness violin per mechanism.

Backs PECS Paper B Finding 4, hypothesis H3 (no fairness regression
under any anti-gaming mechanism).

Inputs
------
  data/m100/policy_matrix/policy_matrix.csv

Output
------
  figs/fig_fairness_pareto.pdf
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt


from _figstyle import apply_style
apply_style()

MECHANISM_ORDER  = ["none", "M0", "M1", "M2", "M3"]
MECHANISM_LABELS = {"none": "no f-SLA", "M0": "M0 Posted", "M1": "M1 BlindTrust",
                     "M2": "M2 DAA", "M3": "M3 AI-Audit"}
MECHANISM_COLORS = {"none": "#bdbdbd", "M0": "#4a90e2", "M1": "#3a7d44",
                     "M2": "#e07a2e", "M3": "#a83232"}
POLICY_MARKERS   = {"FCFS": "o", "EASY": "s", "SAF": "^",
                     "RLBackfilling": "D", "GridPilot-PUE": "*"}


def panel_pareto(ax: plt.Axes, df: pd.DataFrame):
    """Carbon (Δ_IT vs FCFS) on x; Jain on y; colour = mechanism;
    marker = policy.  Pareto frontier emphasised with a dashed line.
    """
    base = df.query("policy == 'FCFS' and mechanism == 'none'")["co2_g_it"]
    base_mean = float(base.mean()) if len(base) else 1.0
    df = df.assign(
        delta_it_pct=(base_mean - df["co2_g_it"]) / max(base_mean, 1.0) * 100.0
    )
    for (pol, mech), cell in df.groupby(["policy", "mechanism"]):
        ax.scatter(cell["delta_it_pct"], cell["jain_fairness"],
                    marker=POLICY_MARKERS.get(pol, "x"),
                    color=MECHANISM_COLORS.get(mech, "#555"),
                    s=36, alpha=0.85, edgecolor="white", linewidth=0.4)
    # Pareto frontier: upper-right hull of (carbon, fairness)
    pts = df.groupby(["policy", "mechanism"])[["delta_it_pct", "jain_fairness"]].mean()
    pts = pts.sort_values("delta_it_pct")
    front_x, front_y = [], []
    best_y = -np.inf
    for _, row in pts.iloc[::-1].iterrows():
        if row["jain_fairness"] > best_y:
            best_y = row["jain_fairness"]
            front_x.append(row["delta_it_pct"])
            front_y.append(row["jain_fairness"])
    if front_x:
        ax.plot(front_x[::-1], front_y[::-1], ls="--", color="#444",
                 lw=0.8, alpha=0.7, label="Pareto frontier")
    ax.set_xlabel(r"IT-CO$_2$ reduction vs. FCFS (%)")
    ax.set_ylabel("Jain fairness index")
    ax.set_title("(a) Carbon vs. fairness Pareto scatter")

    # Build a compact two-row legend: policies (markers), mechanisms (colours)
    from matplotlib.lines import Line2D
    pol_handles = [Line2D([0], [0], marker=POLICY_MARKERS[p], color="w",
                           markerfacecolor="#555", markersize=7, label=p)
                   for p in POLICY_MARKERS]
    mech_handles = [Line2D([0], [0], marker="s", color="w",
                            markerfacecolor=MECHANISM_COLORS[m],
                            markersize=8, label=MECHANISM_LABELS[m])
                    for m in MECHANISM_ORDER]
    # Two compact legends placed OUTSIDE the Pareto-scatter axis (to
    # the right) so they never collide with title or data points.
    leg1 = ax.legend(handles=pol_handles, loc="upper left",
                      bbox_to_anchor=(1.02, 1.0), title="Policy",
                      fontsize=9, title_fontsize=9.5, frameon=True,
                      ncol=1, handletextpad=0.4,
                      framealpha=0.95, edgecolor="#bbb")
    ax.add_artist(leg1)
    ax.legend(handles=mech_handles, loc="upper left",
               bbox_to_anchor=(1.02, 0.55), title="Mechanism",
               fontsize=9, title_fontsize=9.5, frameon=True,
               ncol=1, handletextpad=0.4,
               framealpha=0.95, edgecolor="#bbb")


def panel_jain_violin(ax: plt.Axes, df: pd.DataFrame):
    """Per-mechanism Jain violin; horizontal H3 0.95-of-FCFS line."""
    baseline_jain = float(df.query("policy == 'FCFS' and mechanism == 'none'")
                              ["jain_fairness"].mean())
    threshold = 0.95 * baseline_jain
    data, positions, colors = [], [], []
    for i, m in enumerate(MECHANISM_ORDER):
        v = df.query("mechanism == @m")["jain_fairness"].values
        if v.size == 0:
            continue
        data.append(v); positions.append(i); colors.append(MECHANISM_COLORS[m])
    parts = ax.violinplot(data, positions=positions, widths=0.7,
                            showmeans=True, showmedians=False, showextrema=False)
    for body, c in zip(parts["bodies"], colors):
        body.set_facecolor(c); body.set_edgecolor("#333"); body.set_alpha(0.7)
    parts["cmeans"].set_color("#222"); parts["cmeans"].set_linewidth(0.8)
    ax.axhline(threshold, ls="--", lw=0.7, color="#c0504d",
                label=f"H3 threshold (0.95 × FCFS = {threshold:.3f})")
    ax.set_xticks(np.arange(len(MECHANISM_ORDER)))
    ax.set_xticklabels([MECHANISM_LABELS[m] for m in MECHANISM_ORDER],
                         rotation=20, ha="right")
    ax.set_ylabel("Jain fairness")
    ax.set_title("(b) Jain fairness per mechanism (all policies pooled)")
    ax.legend(loc="lower right", frameon=True, fontsize=7.5,
               framealpha=0.95, edgecolor="#bbb")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", type=Path,
                    default=Path("data/m100/policy_matrix/policy_matrix.csv"))
    p.add_argument("--out", type=Path, default=Path("figs/fig_fairness_pareto.pdf"))
    args = p.parse_args(argv)
    df = pd.read_csv(args.matrix)

    # Generous canvas + constrained_layout so titles, legends and bars
    # never collide.  Panel widths leave room for legends OUTSIDE the
    # data region.
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.6),
                              gridspec_kw={"width_ratios": [1.3, 1.0]},
                              constrained_layout=True)
    panel_pareto(axes[0], df)
    panel_jain_violin(axes[1], df)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_fairness_pareto] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
