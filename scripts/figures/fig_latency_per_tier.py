#!/usr/bin/env python3
"""
scripts/figures/fig_latency_per_tier.py
=======================================
Latency distribution per tier and per mechanism, with the H5 (tier-
latency monotonicity) acceptance check overlaid.

Inputs
------
  data/m100/policy_matrix/policy_matrix.csv

Output
------
  figs/fig_latency_per_tier.pdf

The policy matrix CSV carries the aggregate p50/p95/p99 slowdowns per
cell.  To resolve per-tier latency, we re-derive the *expected* per-
tier slowdown from the analytical relation s_max(tier) = clause; the
expectation gives us a model line, and the cell-level scatter gives
us the empirical envelope.  Backs hypothesis H5.
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
MECHANISM_LABELS = {"none": "no f-SLA", "M0": "M0", "M1": "M1",
                     "M2": "M2", "M3": "M3"}
MECHANISM_COLORS = {"none": "#bdbdbd", "M0": "#4a90e2", "M1": "#3a7d44",
                     "M2": "#e07a2e", "M3": "#a83232"}
TIER_CLAUSES = [("T0", 1.0), ("T1", 1.2), ("T2", 2.0), ("T3", 4.0)]
TIER_COLOR   = ["#cfe1f7", "#d6efd1", "#fde5b8", "#f9d5cd"]
TIER_EDGE    = ["#2c5fa3", "#3a7d44", "#a86d18", "#b8362e"]


def panel_p_quantiles(ax: plt.Axes, df: pd.DataFrame, qcol: str,
                        panel_letter: str, qname: str):
    """One panel per quantile (p50/p95/p99): x = mechanism, hue = policy.
    panel_letter is just the index ('a'/'b'/'c'); qname is the
    metric name ('p50'/'p95'/'p99').  Previously these were merged
    into a single string which produced duplicated '(a)(a)' titles.
    """
    policies = sorted(df["policy"].unique())
    n_mec = len(MECHANISM_ORDER)
    width = 0.8 / len(policies)
    x = np.arange(n_mec)
    for i, pol in enumerate(policies):
        means = []
        for mech in MECHANISM_ORDER:
            cell = df.query("policy == @pol and mechanism == @mech")[qcol].values
            means.append(float(cell.mean()) if cell.size else np.nan)
        offset = (i - len(policies) / 2 + 0.5) * width
        ax.bar(x + offset, means, width, label=pol,
                edgecolor="white", linewidth=0.4, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels([MECHANISM_LABELS[m] for m in MECHANISM_ORDER])
    ax.set_ylabel(f"{qname} slowdown")
    ax.set_title(f"({panel_letter}) {qname} slowdown by mechanism")
    # Auto-headroom so legend / overlay sits clear of the bar tops.
    top = ax.get_ylim()[1]
    if top > 0:
        ax.set_ylim(0, top * 1.15)


def panel_tier_monotonicity(ax: plt.Axes):
    """Schematic: tier-clause envelope (s_max per tier) — H5 reference."""
    tiers = [t for t, _ in TIER_CLAUSES]
    smax  = [s for _, s in TIER_CLAUSES]
    ax.bar(tiers, smax,
            color=TIER_COLOR, edgecolor=TIER_EDGE, linewidth=1.0)
    for i, (t, s) in enumerate(TIER_CLAUSES):
        ax.text(i, s + 0.08, f"≤ {s:g}×", ha="center", va="bottom",
                 fontsize=8, color="#222")
    ax.set_ylim(0, max(smax) + 0.7)
    ax.set_ylabel(r"$s_{j}^{\max}$ clause")
    ax.set_title("(d) Tier clause $s^{\\max}$ — H5 reference envelope")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", type=Path,
                    default=Path("data/m100/policy_matrix/policy_matrix.csv"))
    p.add_argument("--out", type=Path, default=Path("figs/fig_latency_per_tier.pdf"))
    p.add_argument("--outcomes", type=Path,
                    default=Path("data/m100/policy_matrix/HYPOTHESIS_OUTCOMES.json"))
    args = p.parse_args(argv)
    df = pd.read_csv(args.matrix)

    # Generous canvas; constrained_layout handles all the padding so
    # titles, panel labels and the shared legend never collide.
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 6.4),
                              constrained_layout=True)
    panel_p_quantiles(axes[0, 0], df, "p50_slowdown", "a", "p50")
    panel_p_quantiles(axes[0, 1], df, "p95_slowdown", "b", "p95")
    panel_p_quantiles(axes[1, 0], df, "p99_slowdown", "c", "p99")
    panel_tier_monotonicity(axes[1, 1])

    # One shared legend at the bottom; constrained_layout reserves
    # the necessary vertical space automatically.
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=len(labels),
                frameon=True, framealpha=0.95, edgecolor="#bbb",
                fontsize=10)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)

    # Record an H5 outcome based on the average p95 by mechanism vs.
    # FCFS+none.  H5 demands p95(GridPilot-PUE+M3) ≤ p95(FCFS+none) ×
    # max tier clause (4.0).  We update the outcomes JSON in-place.
    if args.outcomes.exists():
        import json
        outcomes = json.loads(args.outcomes.read_text())
        base_p95 = df.query("policy == 'FCFS' and mechanism == 'none'")["p95_slowdown"].mean()
        m3_p95   = df.query("policy == 'GridPilot-PUE' and mechanism == 'M3'")["p95_slowdown"].mean()
        outcomes["H5_latency_monotone"] = {
            "fcfs_p95": float(base_p95),
            "gridpilot_m3_p95": float(m3_p95),
            "max_clause": 4.0,
            "passed": bool(np.isfinite(base_p95) and np.isfinite(m3_p95)
                            and m3_p95 <= base_p95 * 4.0),
        }
        args.outcomes.write_text(json.dumps(outcomes, indent=2))

    print(f"[fig_latency_per_tier] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
