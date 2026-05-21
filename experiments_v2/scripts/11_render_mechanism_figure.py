#!/usr/bin/env python3
"""
experiments_v2/scripts/11_render_mechanism_figure.py
=====================================================
Render the M0--M3 comparison figure that backs Finding D / Lesson L3.

Two panels:
  (a) NOM-IC violation rate (%) per mechanism, error bars 1 SEM
      over the 8 seeds.  Headline panel: lower is better.
  (b) Jain fairness index + alpha-fair SWF (alpha=1) per mechanism;
      shows that M3's low violation rate doesn't come at a fairness
      or social-welfare cost.

Input: data/mechanism_sweep/mechanism_sweep.csv (per-seed rows from
       04d_run_mechanism_sweep.py).

Usage:
  PYTHONPATH=gridpilot/experiments_v2/src python3 \\
      gridpilot/experiments_v2/scripts/11_render_mechanism_figure.py \\
      --csv gridpilot/experiments_v2/data/mechanism_sweep/mechanism_sweep.csv \\
      --out gridpilot/experiments_v2/figs/paper/fig_paper_mechanisms.pdf
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "gridpilot" / "experiments_v2" / "src"))

from figure_style import (  # type: ignore[import-not-found]
    W_DOUBLE_COL, apply_rcparams,
)

apply_rcparams()

MECH_ORDER  = ["M0", "M1", "M2", "M3"]
MECH_LABELS = {
    "M0": "M0\nposted price",
    "M1": "M1\nBlindTrust",
    "M2": "M2\nDAA",
    "M3": "M3\nAI baseline",
}
MECH_COLORS = {
    "M0": "#8c8c8c",
    "M1": "#4a91d6",
    "M2": "#d68b2b",
    "M3": "#2b7a3a",
}


def render(csv: Path, out: Path) -> None:
    df = pd.read_csv(csv)
    # Wider canvas (13.0" vs the v2.0 9.6") so the two-line mechanism
    # tick labels ("M0\nposted price", etc.) have enough horizontal
    # room not to collide with their neighbours, even on a 4-bar
    # group where each bar is only ~1.2" wide.  Right panel still
    # gets 1.4x the real-estate of the left because it carries two
    # y axes (Jain index + alpha-fair SWF) plus a paired bar layout.
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 3.8),
                              constrained_layout=True,
                              gridspec_kw={"width_ratios": [1.0, 1.4]})

    # ── (a) NOM-IC violation rate, lower is better ────────────────
    ax = axes[0]
    x = np.arange(len(MECH_ORDER))
    means = [df[df["mechanism"] == m]["violation_rate_pct"].mean()
             for m in MECH_ORDER]
    sems  = [df[df["mechanism"] == m]["violation_rate_pct"].std(ddof=0)
              / max(1, np.sqrt(len(df[df["mechanism"] == m])))
             for m in MECH_ORDER]
    colors = [MECH_COLORS[m] for m in MECH_ORDER]
    ax.bar(x, means, yerr=sems, color=colors, edgecolor="black",
            linewidth=0.6, error_kw=dict(ecolor="#333", lw=0.9))
    ax.set_xticks(x)
    ax.set_xticklabels([MECH_LABELS[m] for m in MECH_ORDER], fontsize=11)
    ax.set_ylabel(r"NOM-IC violation rate (\%)  ($\downarrow$ better)")
    ax.set_title("(a) Strategic-manipulability rate")
    # Annotate bars with the numeric value so the headline is readable
    # at LNCS scale-down.
    for xi, mi in zip(x, means):
        ax.text(xi, mi + max(means) * 0.04, f"{mi:.1f}",
                ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_ylim(0, max(means) * 1.25 if max(means) > 0 else 1.0)

    # ── (b) Fairness + SWF: paired bars, twin y axes ──────────────
    ax = axes[1]
    w = 0.36
    jains = [df[df["mechanism"] == m]["jain_index"].mean() for m in MECH_ORDER]
    swfs  = [df[df["mechanism"] == m]["alpha_fair_swf_a1"].mean()
             for m in MECH_ORDER]
    ax.bar(x - w/2, jains, w, color=colors, edgecolor="black",
            linewidth=0.5, label="Jain's index ($\\uparrow$ fairer)")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel(r"Jain's fairness index  ($\uparrow$ fairer)")
    ax.set_xticks(x)
    ax.set_xticklabels([MECH_LABELS[m] for m in MECH_ORDER], fontsize=11)
    ax.set_title(r"(b) Fairness and social welfare")

    ax2 = ax.twinx()
    ax2.bar(x + w/2, swfs, w, color=colors, edgecolor="black",
             linewidth=0.5, alpha=0.55,
             hatch="///",
             label=r"$\alpha$-fair SWF ($\alpha\!=\!1$, $\uparrow$ better)")
    ax2.set_ylabel(r"$\alpha$-fair SWF ($\alpha\!=\!1$)  ($\uparrow$ better)")
    ax2.spines["right"].set_visible(True)
    ax2.grid(False)

    # Legend combining both axes, below the panel.
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2,
              loc="upper center", bbox_to_anchor=(0.5, -0.20),
              frameon=False, ncol=2, fontsize=10,
              handlelength=1.4, columnspacing=1.5)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"[11-mechanism-figure] wrote {out}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    render(args.csv, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
