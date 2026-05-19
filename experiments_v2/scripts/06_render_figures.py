#!/usr/bin/env python3
"""
experiments_v2/scripts/06_render_figures.py
============================================
Phase 5b — render v2 figures.

Produces three figure PDFs:
  fig_country_cfe_lift_v2.pdf  — per-country Δ-vs-each-baseline (Table 2 companion)
  fig_tier_contribution_v2.pdf — per-tier CFE lift + p95 slowdown
  fig_hyper_sensitivity_v2.pdf — one-at-a-time hyperparameter sweep

Each figure pulls from its v2 summary CSV; if the CSV is missing,
the figure shows a "(awaiting <sweep> run)" placeholder so the
paper compiles cleanly even with an incomplete pipeline.

Usage:
  PYTHONPATH=gridpilot/experiments_v2/src python3 \\
      gridpilot/experiments_v2/scripts/06_render_figures.py \\
      --country-csv  gridpilot/experiments_v2/data/country_sweep/country_sweep.csv \\
      --tier-summary gridpilot/experiments_v2/data/tier_sweep/TIER_SUMMARY.csv \\
      --hyper-summary gridpilot/experiments_v2/data/hyper_sweep/HYPER_SUMMARY.csv \\
      --out-dir gridpilot/experiments_v2/figs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Greyscale-safe palette + hatching (for B&W print compatibility).
COLORS = {
    "fcfs":      "#2b7a3a",
    "easy_fcfs": "#4a91d6",
    "saf":       "#d68b2b",
    "replay":    "#8a5cb8",
    "fsla_M3":   "#cc3333",
}
HATCHES = {"fcfs": "", "easy_fcfs": "///", "saf": "...", "replay": "xxx", "fsla_M3": ""}

COUNTRY_ORDER = ["SE", "CH", "FR", "IT", "DE", "PL"]
BASELINES     = ["fcfs", "easy_fcfs", "saf", "replay"]
HEADLINE_MW   = 10
HEADLINE_LAYER = "fsla_M3"

plt.rcParams.update({
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "font.size": 9, "axes.labelsize": 10, "axes.titlesize": 10,
    "legend.fontsize": 8,
})


def _placeholder(ax, msg: str) -> None:
    ax.text(0.5, 0.5, msg, ha="center", va="center",
            transform=ax.transAxes, fontsize=11,
            color="#888", style="italic")
    ax.set_xticks([]); ax.set_yticks([])


# ─────────────────────────────────────────────────────────────────────
# Fig 1 — Δ-vs-each-baseline by country
# ─────────────────────────────────────────────────────────────────────

def fig_country_lift(country_csv: Optional[Path], out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.0), constrained_layout=True)
    if country_csv is None or not country_csv.exists():
        for ax in axes:
            _placeholder(ax, "(awaiting country sweep run)")
        fig.savefig(out, format="pdf"); plt.close(fig); return

    df = pd.read_csv(country_csv)
    df = df.query("mw == @HEADLINE_MW and layer == @HEADLINE_LAYER")
    if df.empty:
        for ax in axes:
            _placeholder(ax, "(no data at headline MW/layer)")
        fig.savefig(out, format="pdf"); plt.close(fig); return

    # Mean over seeds, keyed by country.
    means = df.groupby("country", as_index=False).mean(numeric_only=True)
    means = means.set_index("country").reindex(COUNTRY_ORDER)

    # (a) Per-country Δ CFE pp vs each baseline.
    ax = axes[0]
    x = np.arange(len(COUNTRY_ORDER))
    w = 0.18
    for i, base in enumerate(BASELINES):
        vals = means[f"d_cfe_vs_{base}_pp"].fillna(0.0).values
        offset = (i - (len(BASELINES) - 1) / 2) * w
        ax.bar(x + offset, vals, w, label=base.replace("_", "-").upper(),
                color=COLORS[base], hatch=HATCHES.get(base, ""), edgecolor="black", linewidth=0.4)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_xticks(x); ax.set_xticklabels(COUNTRY_ORDER)
    ax.set_ylabel(f"Δ CFE (pp) — {HEADLINE_LAYER} vs baseline")
    ax.set_title(f"(a) f-SLA Δ CFE at {HEADLINE_MW} MW, per country, per baseline")
    ax.legend(loc="best", ncol=2, frameon=False)

    # (b) Per-country Δ CI g/kWh vs each baseline.
    ax = axes[1]
    for i, base in enumerate(BASELINES):
        vals = means[f"d_ci_vs_{base}_g"].fillna(0.0).values
        offset = (i - (len(BASELINES) - 1) / 2) * w
        ax.bar(x + offset, vals, w, label=base.replace("_", "-").upper(),
                color=COLORS[base], hatch=HATCHES.get(base, ""), edgecolor="black", linewidth=0.4)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_xticks(x); ax.set_xticklabels(COUNTRY_ORDER)
    ax.set_ylabel(f"Δ CI (g/kWh) — baseline minus {HEADLINE_LAYER}")
    ax.set_title(f"(b) f-SLA Δ effective CI at {HEADLINE_MW} MW")

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="pdf"); plt.close(fig)
    print(f"[06-render-figures] wrote {out}")


# ─────────────────────────────────────────────────────────────────────
# Fig 2 — per-tier CFE lift + p95 slowdown
# ─────────────────────────────────────────────────────────────────────

def fig_tier_contribution(tier_summary: Optional[Path], out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.0), constrained_layout=True)
    if tier_summary is None or not tier_summary.exists():
        for ax in axes:
            _placeholder(ax, "(awaiting tier sweep run)")
        fig.savefig(out, format="pdf"); plt.close(fig); return

    df = pd.read_csv(tier_summary)
    tiers = sorted(df["tier"].unique())
    countries = [c for c in COUNTRY_ORDER if c in df["country"].unique()]

    # (a) CFE lift over T0 per tier.
    ax = axes[0]
    x = np.arange(len(tiers)); w = 0.13
    for i, c in enumerate(countries):
        vals = df[df["country"] == c].sort_values("tier")["cfe_lift_pp"].values
        offset = (i - (len(countries) - 1) / 2) * w
        ax.bar(x + offset, vals, w, label=c, edgecolor="black", linewidth=0.4)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_xticks(x); ax.set_xticklabels([f"T{t}" for t in tiers])
    ax.set_ylabel("CFE lift over T0 (pp)")
    ax.set_title("(a) Per-tier CFE contribution")
    ax.legend(loc="best", ncol=3, frameon=False)

    # (b) p95 slowdown per tier.
    ax = axes[1]
    for i, c in enumerate(countries):
        vals = df[df["country"] == c].sort_values("tier")["p95_slowdown"].values
        offset = (i - (len(countries) - 1) / 2) * w
        ax.bar(x + offset, vals, w, label=c, edgecolor="black", linewidth=0.4)
    ax.set_xticks(x); ax.set_xticklabels([f"T{t}" for t in tiers])
    ax.set_ylabel("p95 slowdown (×)")
    ax.set_title("(b) Per-tier user-side cost (p95 slowdown)")

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="pdf"); plt.close(fig)
    print(f"[06-render-figures] wrote {out}")


# ─────────────────────────────────────────────────────────────────────
# Fig 3 — hyperparameter sensitivity
# ─────────────────────────────────────────────────────────────────────

def fig_hyper_sensitivity(hyper_summary: Optional[Path], out: Path) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(7.0, 4.0), constrained_layout=True)
    if hyper_summary is None or not hyper_summary.exists():
        _placeholder(ax, "(awaiting hyperparameter sweep run)")
        fig.savefig(out, format="pdf"); plt.close(fig); return

    df = pd.read_csv(hyper_summary)
    # Plot each row as a bar; sort by CFE for visual flow.
    df = df.sort_values("cfe_canonical_pct")
    ax.barh(df["hyper_label"], df["cfe_canonical_pct"],
             color="#4a91d6", edgecolor="black", linewidth=0.4)
    # Reference: the 'alpha_1.0' (default) row's CFE.
    ref_rows = df[df["hyper_label"] == "alpha_1.0"]
    if not ref_rows.empty:
        ref = float(ref_rows.iloc[0]["cfe_canonical_pct"])
        ax.axvline(ref, color="black", linestyle="--", lw=0.8,
                    label=f"default (alpha=1.0): {ref:.2f} %")
        ax.legend(loc="best", frameon=False)
    ax.set_xlabel("CFE (canonical 24/7) %")
    ax.set_title("Contract-hyperparameter sensitivity (one-at-a-time)")

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="pdf"); plt.close(fig)
    print(f"[06-render-figures] wrote {out}")


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--country-csv",   type=Path, default=None)
    p.add_argument("--tier-summary",  type=Path, default=None)
    p.add_argument("--hyper-summary", type=Path, default=None)
    p.add_argument("--out-dir",       type=Path, required=True)
    args = p.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    fig_country_lift(args.country_csv,   args.out_dir / "fig_country_cfe_lift_v2.pdf")
    fig_tier_contribution(args.tier_summary, args.out_dir / "fig_tier_contribution_v2.pdf")
    fig_hyper_sensitivity(args.hyper_summary, args.out_dir / "fig_hyper_sensitivity_v2.pdf")
    print(f"[06-render-figures] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
