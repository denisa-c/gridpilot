#!/usr/bin/env python3
"""
scripts/figures/fig_swf_comparison.py
=====================================
Social-welfare comparison across (policy, mechanism) cells for the
α-fair family (α ∈ {0, 0.5, 1.0, 2.0}).

Backs PECS Paper B Finding 4, hypothesis H4 (SWF dominance under DAA).

Inputs
------
  data/m100/policy_matrix/policy_matrix.csv

Output
------
  figs/fig_swf_comparison.pdf
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
# Colour palette: matches fig_cfe_by_tier.py for paper-wide consistency.
MECHANISM_COLORS = {"none": "#bdbdbd", "M0": "#4a90e2", "M1": "#3a7d44",
                     "M2": "#e07a2e", "M3": "#a83232"}
ALPHA_COLS = [("swf_utilitarian", r"$\alpha=0$ (utilitarian)"),
              ("swf_alpha_0.5",  r"$\alpha=0.5$"),
              ("swf_alpha_1.0",  r"$\alpha=1$ (Nash)"),
              ("swf_alpha_2.0",  r"$\alpha=2$ (leximin proxy)")]


def _normalise_per_alpha(df: pd.DataFrame, col: str) -> np.ndarray:
    """Min-max normalise each SWF column so the four α panels share
    a comparable [0, 1] y-axis.  We use the *finite* (non-Nash zero)
    rows to define the range so the Nash limit's near-zeros do not
    crush the others.
    """
    v = df[col].values.astype(float)
    finite = v[np.isfinite(v)]
    if finite.size == 0:
        return v
    vmin, vmax = float(np.min(finite)), float(np.max(finite))
    if vmax - vmin < 1e-9:
        return np.zeros_like(v)
    return (v - vmin) / (vmax - vmin)


def panel_swf_per_alpha(ax: plt.Axes, df: pd.DataFrame, col: str, title: str):
    """One sub-panel per α value: x = mechanism, y = normalised SWF."""
    norm = _normalise_per_alpha(df, col)
    gp = df.assign(_norm=norm).query("policy == 'GridPilot-PUE'")
    grouped = gp.groupby("mechanism")["_norm"].agg(["mean", "std"]).reindex(MECHANISM_ORDER)
    x = np.arange(len(grouped))
    ax.bar(x, grouped["mean"].values, yerr=grouped["std"].values,
            color=[MECHANISM_COLORS[m] for m in grouped.index],
            edgecolor="white", linewidth=0.4,
            error_kw=dict(elinewidth=0.6, capsize=2, ecolor="#333"))
    ax.set_xticks(x)
    ax.set_xticklabels([MECHANISM_LABELS[m] for m in grouped.index],
                         rotation=20, ha="right")
    ax.set_ylim(0, 1.15)
    ax.set_ylabel(r"Normalised SWF (per α)")
    ax.set_title(title)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", type=Path,
                    default=Path("data/m100/policy_matrix/policy_matrix.csv"))
    p.add_argument("--out", type=Path, default=Path("figs/fig_swf_comparison.pdf"))
    args = p.parse_args(argv)
    df = pd.read_csv(args.matrix)

    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.0))
    axes_flat = axes.flatten()
    for ax, (col, title) in zip(axes_flat, ALPHA_COLS):
        panel_swf_per_alpha(ax, df, col, title)
    fig.suptitle("Social welfare under the α-fair family (GridPilot-PUE backbone)",
                  y=0.99, fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_swf_comparison] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
