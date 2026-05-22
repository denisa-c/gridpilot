#!/usr/bin/env python3
"""
scripts/figures/fig_country_pue_aware.py
========================================
Two-panel headline figure for the GridPilot paper:

  (a)  Δ_facility (pp) from the PUE-aware FFR controller relative to
       the CI-only baseline, one bar per country, ordered by CI.
       The 4–7 pp envelope is the cooling-overhead drag that constant-
       PUE controllers ignore --- it is wider on low-CI grids (where
       absolute IT savings are small) and narrower on high-CI grids
       (where the IT savings dominate the facility budget).

  (b)  MW scaling: how the Δ_facility envelope shrinks at larger
       cluster scale (cooling utilisation averages out the L^2/L^3
       floors of the four-component PUE model), shown for the SE
       (cleanest) and PL (dirtiest) bookends.

Inputs
------
  data/m100/country_sweep/country_sweep.csv

Output
------
  figs/fig_country_pue_aware.pdf
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

COUNTRY_ORDER = ["SE", "CH", "FR", "IT", "DE", "PL"]
COUNTRY_LABEL = {"SE": "SE\n11", "CH": "CH\n30", "FR": "FR\n53",
                  "IT": "IT\n258", "DE": "DE\n295", "PL": "PL\n612"}
# Diverging colour ramp ordered by 2025 mean CI (SE cleanest → PL dirtiest).
COUNTRY_COLOR = {"SE": "#1a7c3a", "CH": "#54a564", "FR": "#92c98e",
                  "IT": "#f3a93f", "DE": "#e07a2e", "PL": "#922e29"}


def _bootstrap_mean_ci(values: np.ndarray, n: int = 10_000,
                        conf: float = 0.95,
                        rng: Optional[np.random.Generator] = None) -> tuple[float, float, float]:
    rng = rng or np.random.default_rng(20260517)
    if values.size == 0:
        return 0.0, 0.0, 0.0
    idx = rng.integers(0, values.size, size=(n, values.size))
    samples = values[idx].mean(axis=1)
    a = 1.0 - conf
    return (float(values.mean()),
             float(np.percentile(samples, 100.0 * a / 2.0)),
             float(np.percentile(samples, 100.0 * (1.0 - a / 2.0))))


def panel_a(ax: plt.Axes, df: pd.DataFrame, rng: np.random.Generator,
             mw_focus: float = 10.0):
    cell_q = df.query("layer == 'pue' and mechanism == 'GridPilot-PUE' and mw == @mw_focus")
    means, los, his = [], [], []
    for c in COUNTRY_ORDER:
        vals = cell_q.query("country == @c")["delta_facility_pp"].values
        m, lo, hi = _bootstrap_mean_ci(vals, rng=rng)
        means.append(m); los.append(m - lo); his.append(hi - m)
    x = np.arange(len(COUNTRY_ORDER))
    colors = [COUNTRY_COLOR[c] for c in COUNTRY_ORDER]
    ax.bar(x, means, yerr=[los, his], color=colors,
            edgecolor="white", linewidth=0.4,
            error_kw=dict(elinewidth=0.6, capsize=2, ecolor="#333"))
    ax.set_xticks(x)
    ax.set_xticklabels([COUNTRY_LABEL[c] for c in COUNTRY_ORDER])
    ax.set_xlabel("Country (annual mean CI g/kWh below)")
    ax.set_ylabel(r"$\Delta_{\rm facility}$ (pp) from PUE-aware FFR")
    ax.set_title(f"(a) Cooling-overhead drag closed at {int(mw_focus)} MW IT")
    # Auto-headroom for clean readability
    top = ax.get_ylim()[1]
    ax.set_ylim(0, top * 1.15 if top > 0 else 1.0)


def panel_b(ax: plt.Axes, df: pd.DataFrame, rng: np.random.Generator):
    pairs = [("SE", COUNTRY_COLOR["SE"]), ("PL", COUNTRY_COLOR["PL"])]
    mws = sorted(df["mw"].unique())
    width = 0.35
    x = np.arange(len(mws))
    for i, (c, col) in enumerate(pairs):
        means, los, his = [], [], []
        for mw in mws:
            v = df.query("country == @c and layer == 'pue' and "
                          "mechanism == 'GridPilot-PUE' and mw == @mw"
                          )["delta_facility_pp"].values
            m, lo, hi = _bootstrap_mean_ci(v, rng=rng)
            means.append(m); los.append(m - lo); his.append(hi - m)
        ax.bar(x + (i - 0.5) * width, means, width,
                yerr=[los, his], color=col,
                edgecolor="white", linewidth=0.4,
                label=f"{c} (CI={'11' if c=='SE' else '612'} g/kWh)",
                error_kw=dict(elinewidth=0.6, capsize=2, ecolor="#333"))
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(mw)} MW" for mw in mws])
    ax.set_ylabel(r"$\Delta_{\rm facility}$ (pp)")
    ax.set_title("(b) Cluster-scale averaging shrinks the envelope")
    # Headroom for the legend, placed outside the bars.
    top = ax.get_ylim()[1]
    ax.set_ylim(0, top * 1.20 if top > 0 else 1.0)
    ax.legend(loc="upper right", bbox_to_anchor=(0.98, 0.98),
               frameon=True, fontsize=11,
               framealpha=0.95, edgecolor="#bbb")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", type=Path,
                    default=Path("data/m100/country_sweep/country_sweep.csv"))
    p.add_argument("--out", type=Path,
                    default=Path("figs/fig_country_pue_aware.pdf"))
    p.add_argument("--mw-focus", type=float, default=10.0)
    args = p.parse_args(argv)
    df = pd.read_csv(args.matrix)
    rng = np.random.default_rng(20260517)

    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.4),
                              gridspec_kw={"width_ratios": [1.4, 1.0]},
                              constrained_layout=True)
    panel_a(axes[0], df, rng, mw_focus=args.mw_focus)
    panel_b(axes[1], df, rng)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_country_pue_aware] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
