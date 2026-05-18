#!/usr/bin/env python3
"""
scripts/figures/fig_sensitivity_no_ffr.py
=========================================

Publication-ready Plackett-Burman tornado for the 5-factor design
that has NO frequency-response factors.  Backs PECS 2026 §9.

Inputs
------
  data/pb_sensitivity_5factor_no_ffr.effects.csv
  data/pb_sensitivity_5factor_no_ffr.csv

Output
------
  figs/fig_sensitivity_no_ffr.pdf
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt

mpl.rcParams.update({
    "font.family": "serif", "font.size": 9.0,
    "axes.titlesize": 9.5, "axes.labelsize": 9.0,
    "xtick.labelsize": 8.0, "ytick.labelsize": 8.0,
    "axes.linewidth": 0.7,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})


FACTOR_LABELS = {
    "alpha_concentration_scale": "f-SLA Dirichlet conc. scale",
    "diurnal_ci_amplitude_pct":  "Diurnal CI amplitude",
    "chiller_cop_slope":         "Chiller COP slope",
    "pump_affinity_floor":       "Pump-affinity floor",
    "fan_affinity_exponent":     "Fan-affinity exponent",
}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--effects", type=Path,
                   default=Path("data/pb_sensitivity_5factor_no_ffr.effects.csv"))
    p.add_argument("--runs", type=Path,
                   default=Path("data/pb_sensitivity_5factor_no_ffr.csv"))
    p.add_argument("--baseline-pct", type=float, default=9.3,
                   help="Baseline operational-only DE 2025 figure (default 9.3%%).")
    p.add_argument("--out", type=Path,
                   default=Path("figs/fig_sensitivity_no_ffr.pdf"))
    args = p.parse_args(argv)

    eff = pd.read_csv(args.effects)
    runs = pd.read_csv(args.runs)
    eff = eff.assign(abs_=eff["main_effect_pp"].abs()).sort_values("abs_", ascending=True)
    fig, ax = plt.subplots(figsize=(5.5, 3.0), constrained_layout=True)
    colors = ["#c0504d" if v < 0 else "#4a90e2" for v in eff["main_effect_pp"]]
    ax.barh(range(len(eff)), eff["main_effect_pp"], color=colors,
             alpha=0.80, edgecolor="white", linewidth=0.6)
    ax.set_yticks(range(len(eff)))
    ax.set_yticklabels([FACTOR_LABELS.get(f, f) for f in eff["factor"]])
    ax.set_xlabel("Main effect on response (pp)")
    ax.axvline(0, color="grey", linewidth=0.6)
    for i, v in enumerate(eff["main_effect_pp"].values):
        ax.text(v, i, f"  {v:+.2f}", va="center",
                 fontsize=7.5,
                 color=colors[i],
                 ha="left" if v > 0 else "right")
    env_lo = runs["response_pct"].min()
    env_hi = runs["response_pct"].max()
    ax.set_title(f"PB envelope: [{env_lo:.1f}, {env_hi:.1f}]%  "
                  f"(baseline {args.baseline_pct:.1f}%)",
                  loc="left", fontsize=9.0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    print(f"[fig_sensitivity_no_ffr] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
