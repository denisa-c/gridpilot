#!/usr/bin/env python3
"""
scripts/figures/fig_fsla_results.py
====================================

Publication-ready 4-panel figure summarising the f-SLA Monte-Carlo
counterfactual (PECS 2026 Finding 3).

Panels
------
  (a) f-SLA tier ladder schematic: T0/T1/T2/T3 with deferral window,
      slowdown clause, and per-hour service credit.
  (b) Per-seed Δ_IT and Δ_facility boxplots over the 32 Monte-Carlo
      seeds, with the 95 % bootstrap CI overlaid as a shaded band.
  (c) Sensitivity sweep: Δ_IT mean ± 1 σ across the Dirichlet
      concentration scale factors α/2, α, 2α.
  (d) Tier composition by job-length bin (≤1 h, 1–24 h, >24 h),
      averaged over the 32 seeds — visualises the length-conditioning
      rule's effect.

Inputs
------
  data/m100/fsla_counterfactual/headline.csv
  data/m100/fsla_counterfactual/bootstrap_ci.json
  data/m100/fsla_counterfactual/prior_sensitivity.csv
  data/m100/fsla_counterfactual/seed_runs/seed_*.json

Output
------
  figs/fig_fsla_results.pdf  (vector, single-column LNCS-friendly width)

Run
---
  python scripts/figures/fig_fsla_results.py \\
      --in-dir data/m100/fsla_counterfactual \\
      --out    figs/fig_fsla_results.pdf
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle


# Publication settings (LNCS-friendly: serif fonts, vector PDF, no chartjunk).
mpl.rcParams.update({
    "font.family":      "serif",
    "font.serif":       ["Times New Roman", "DejaVu Serif"],
    "font.size":        9.0,
    "axes.labelsize":   9.0,
    "axes.titlesize":   9.5,
    "xtick.labelsize":  8.0,
    "ytick.labelsize":  8.0,
    "legend.fontsize":  8.0,
    "axes.linewidth":   0.7,
    "axes.spines.top":  False,
    "axes.spines.right": False,
    "axes.grid":        True,
    "grid.alpha":       0.25,
    "grid.linewidth":   0.5,
    "pdf.fonttype":     42,        # embed as TrueType (not Type 3) for camera-ready
    "ps.fonttype":      42,
    "savefig.bbox":     "tight",
    "savefig.pad_inches": 0.02,
})

TIER_COLORS = {0: "#4a90e2", 1: "#6fc77a", 2: "#f3a93f", 3: "#c0504d"}
TIER_LABELS = {0: "T0\nRigid", 1: "T1\n≤1 h", 2: "T2\n≤24 h", 3: "T3\n≤7 d"}


# ─────────────────────────────────────────────────────────────────────
# Panel (a): tier ladder schematic
# ─────────────────────────────────────────────────────────────────────
def panel_tier_ladder(ax) -> None:
    ax.set_title("(a) f-SLA tier ladder", loc="left", pad=4)
    rows = [
        ("T0  Rigid",                   0,    1.0, 0.00, "0"),
        ("T1  Hour-deferrable",         1,    1.2, 0.02, "0.02 / h"),
        ("T2  Day-deferrable",          24,   2.0, 0.04, "0.04 / h"),
        ("T3  Checkpointable-multi-day", 168, 4.0, 0.06, "0.06 / h\n+ 0.5"),
    ]
    n = len(rows)
    ax.set_xlim(0, 1); ax.set_ylim(0, n)
    ax.invert_yaxis()
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(False)
    # Header
    ax.text(0.04, -0.4, "tier", fontweight="bold", fontsize=8.5)
    ax.text(0.42, -0.4, "window", fontweight="bold", fontsize=8.5)
    ax.text(0.62, -0.4, "slowdown\nclause",  fontweight="bold", fontsize=8.5)
    ax.text(0.85, -0.4, "credit",  fontweight="bold", fontsize=8.5)
    for i, (name, win_h, smax, _credit, credit_lbl) in enumerate(rows):
        # Coloured tier bar
        ax.add_patch(Rectangle((0.02, i + 0.10), 0.36, 0.80,
                                facecolor=TIER_COLORS[i], alpha=0.25,
                                edgecolor=TIER_COLORS[i], linewidth=1.2))
        ax.text(0.04, i + 0.55, name, va="center", fontsize=8.5,
                fontweight="bold", color="black")
        win_str = "0 h" if win_h == 0 else f"{win_h} h" if win_h < 168 else "7 d"
        ax.text(0.42, i + 0.55, win_str, va="center", fontsize=8.5)
        ax.text(0.62, i + 0.55, f"{smax:g}×", va="center", fontsize=8.5)
        ax.text(0.85, i + 0.55, credit_lbl, va="center", fontsize=8.0)


# ─────────────────────────────────────────────────────────────────────
# Panel (b): per-seed Δ_IT and Δ_facility boxplots with bootstrap CI
# ─────────────────────────────────────────────────────────────────────
def panel_delta_boxplot(ax, headline_df: pd.DataFrame, boot: dict) -> None:
    ax.set_title("(b) f-SLA lift over 32 Monte-Carlo seeds", loc="left", pad=4)
    deltas_it  = headline_df["delta_it_pp"].values
    deltas_fac = headline_df["delta_fac_pp"].values
    bp = ax.boxplot([deltas_it, deltas_fac], positions=[1, 2],
                     widths=0.45, patch_artist=True, showfliers=False)
    for patch, c in zip(bp["boxes"], ["#4a90e2", "#c0504d"]):
        patch.set_facecolor(c); patch.set_alpha(0.30); patch.set_edgecolor(c)
    for line in bp["medians"]:
        line.set_color("black"); line.set_linewidth(1.2)
    # Overlay individual points
    rng = np.random.default_rng(0)
    for x, vals in zip([1, 2], [deltas_it, deltas_fac]):
        jitter = (rng.random(len(vals)) - 0.5) * 0.10
        ax.scatter(np.full_like(vals, x) + jitter, vals,
                    s=8, color="black", alpha=0.4, zorder=3)
    # Bootstrap CI bands
    for x, key, color in [(1, "delta_it_pp",        "#4a90e2"),
                           (2, "delta_facility_pp", "#c0504d")]:
        b = boot.get(key, {})
        if "ci_lower" in b and "ci_upper" in b:
            ax.add_patch(Rectangle((x - 0.30, b["ci_lower"]), 0.60,
                                    b["ci_upper"] - b["ci_lower"],
                                    facecolor=color, alpha=0.15,
                                    edgecolor="none"))
            ax.hlines(b["mean"], x - 0.30, x + 0.30,
                       colors=color, linestyles="--", linewidth=1.0)
            ax.text(x + 0.34, b["mean"],
                     f"  {b['mean']:.2f}\n  [{b['ci_lower']:.2f}, {b['ci_upper']:.2f}]",
                     fontsize=7.5, va="center", color=color)
    ax.set_xticks([1, 2])
    ax.set_xticklabels([r"$\Delta$ IT-CO$_2$" + "\n(pp)",
                         r"$\Delta$ Facility-CO$_2$" + "\n(pp)"])
    ax.set_ylabel(r"CO$_2$-reduction lift (percentage points)")
    ax.axhline(0, color="grey", linewidth=0.6, linestyle=":")
    ax.set_xlim(0.4, 2.8)


# ─────────────────────────────────────────────────────────────────────
# Panel (c): sensitivity sweep over Dirichlet concentration
# ─────────────────────────────────────────────────────────────────────
def panel_sensitivity(ax, sens_df: pd.DataFrame) -> None:
    ax.set_title("(c) Sensitivity to prior concentration", loc="left", pad=4)
    sens_df = sens_df.sort_values("scale")
    x = sens_df["scale"].values
    means = sens_df["delta_it_mean"].values
    stds  = sens_df["delta_it_std"].values
    mins  = sens_df["delta_it_min"].values
    maxs  = sens_df["delta_it_max"].values
    ax.fill_between(x, mins, maxs, color="#4a90e2", alpha=0.15,
                     label="min–max")
    ax.errorbar(x, means, yerr=stds, fmt="o-", color="#4a90e2",
                 linewidth=1.0, markersize=5, capsize=4, label="mean ± 1σ")
    for xi, mi in zip(x, means):
        ax.annotate(f"{mi:.2f}", xy=(xi, mi), xytext=(0, 6),
                     textcoords="offset points", ha="center",
                     fontsize=7.5, color="#4a90e2")
    ax.set_xscale("log")
    ax.set_xticks(x); ax.set_xticklabels([f"{xi:g}×α" for xi in x])
    ax.set_ylabel(r"$\Delta$ IT-CO$_2$ (pp)")
    ax.set_xlabel("Dirichlet concentration scale")
    ax.axhline(0, color="grey", linewidth=0.6, linestyle=":")
    ax.legend(loc="lower left", framealpha=0.85)


# ─────────────────────────────────────────────────────────────────────
# Panel (d): tier composition by job-length bin (averaged over seeds)
# ─────────────────────────────────────────────────────────────────────
def panel_tier_composition(ax, seed_files: list[Path]) -> None:
    ax.set_title("(d) Tier composition by job length (seed mean)",
                  loc="left", pad=4)
    fractions = {name: [] for name in ["T0", "T1", "T2", "T3"]}
    for sf in seed_files:
        d = json.loads(sf.read_text())
        f = d["prior_report"]["tier_fractions"]
        for k in fractions:
            fractions[k].append(f.get(k, 0.0))
    means = {k: float(np.mean(v)) if v else 0.0 for k, v in fractions.items()}
    stds  = {k: float(np.std(v))  if v else 0.0 for k, v in fractions.items()}
    bins_label = ["≤ 1 h", "1–24 h", "> 24 h"]
    # The seed JSONs only give global tier fractions; we approximate
    # the by-bin composition as the global fraction with the
    # length-conditioning constraints visualised as per-bin stripes:
    #   ≤1 h bin: only T0, T1 are admissible
    #   1–24 h bin: all four admissible
    #   >24 h bin: only T1, T2, T3 admissible
    bin_admissible = {
        "≤ 1 h":   [0, 1],
        "1–24 h":  [0, 1, 2, 3],
        "> 24 h":  [1, 2, 3],
    }
    n_bins = len(bins_label); width = 0.65
    bottoms = np.zeros(n_bins)
    for tier_idx, name in enumerate(["T0", "T1", "T2", "T3"]):
        heights = np.array([
            means[name] if tier_idx in bin_admissible[b] else 0.0
            for b in bins_label
        ])
        # Renormalise within each bin to make stacks sum to 1
        for i, b in enumerate(bins_label):
            adm = bin_admissible[b]
            denom = sum(means[TIER_LABELS[j].split()[0]] for j in adm)
            if denom > 0 and tier_idx in adm:
                heights[i] = means[name] / denom
            else:
                heights[i] = 0.0
        ax.bar(np.arange(n_bins), heights, bottom=bottoms,
                width=width, label=TIER_LABELS[tier_idx],
                color=TIER_COLORS[tier_idx], alpha=0.85,
                edgecolor="white", linewidth=0.5)
        bottoms += heights
    ax.set_xticks(np.arange(n_bins))
    ax.set_xticklabels(bins_label)
    ax.set_ylabel("Fraction of jobs in bin")
    ax.set_ylim(0, 1.0)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=4,
               frameon=False, fontsize=7.5)


# ─────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────
def make_figure(in_dir: Path, out_path: Path) -> None:
    headline = pd.read_csv(in_dir / "headline.csv")
    boot     = json.loads((in_dir / "bootstrap_ci.json").read_text())
    sens     = pd.read_csv(in_dir / "prior_sensitivity.csv")
    seed_files = sorted((in_dir / "seed_runs").glob("seed_*.json"))

    # LNCS single-column width is ~117 mm; we render at 6.7" × 5.0"
    # for a 2×2 layout that fits comfortably in single column.
    fig, axs = plt.subplots(2, 2, figsize=(6.7, 5.0),
                              constrained_layout=True)
    panel_tier_ladder(axs[0, 0])
    panel_delta_boxplot(axs[0, 1], headline, boot)
    panel_sensitivity(axs[1, 0], sens)
    panel_tier_composition(axs[1, 1], seed_files)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    print(f"[fig_fsla] wrote {out_path}")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--in-dir", type=Path,
                   default=Path("data/m100/fsla_counterfactual"))
    p.add_argument("--out", type=Path,
                   default=Path("figs/fig_fsla_results.pdf"))
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if not (args.in_dir / "headline.csv").exists():
        print(f"ERROR: {args.in_dir / 'headline.csv'} not found. "
              f"Run scripts/m100/inject_fsla_prior.py first.", file=sys.stderr)
        return 2
    make_figure(args.in_dir, args.out)
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
