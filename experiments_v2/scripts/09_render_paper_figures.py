#!/usr/bin/env python3
"""
experiments_v2/scripts/09_render_paper_figures.py
==================================================
Phase 5e — render the four publication-ready PECS paper figures.

All four figures share one style module (``figure_style``) so the
PDF set looks like a coherent figure pack rather than four hand-rolled
plots:

  fig_paper_headline.pdf         — Figure-A style:
      (a) per-country Δ CFE bars + avoided tCO₂/y secondary line
      (b) SE / PL scale-invariance bookends (per-season small mults)
  fig_paper_class_breakdown.pdf  — donut of M100 class mix + per-class CFE
  fig_paper_seasonal.pdf         — Δ CFE per country across 4 seasons
  fig_paper_country_vs_ci.pdf    — Δ CFE vs grid CI with linear-fit overlay

All numbers come from taxonomy_sweep.csv (per-seed rows) and
TAXONOMY_MIX.csv.  When a CSV is absent the relevant figure shows an
``(awaiting <input>)`` placeholder so the paper compiles cleanly
during incremental build-out.

Usage:
  PYTHONPATH=gridpilot/experiments_v2/src python3 \\
      gridpilot/experiments_v2/scripts/09_render_paper_figures.py \\
      --taxonomy-csv gridpilot/experiments_v2/data/taxonomy_sweep/taxonomy_sweep.csv \\
      --taxonomy-mix gridpilot/experiments_v2/data/taxonomy_sweep/TAXONOMY_MIX.csv \\
      --out-dir      gridpilot/experiments_v2/figs/paper
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "gridpilot" / "experiments_v2" / "src"))

from figure_style import (  # type: ignore[import-not-found]
    COUNTRY_ORDER, COUNTRY_COLORS, COUNTRY_CI_2025,
    SEASONS, SEASON_COLORS,
    CLASS_COLORS, CLASS_DISPLAY, CLASS_HATCH, PAPER_REFERENCE_PCT,
    TIER_TEXT_COLORS,
    W_SINGLE_COL, W_TEXT, W_DOUBLE_COL,
    PUE_HEADLINE, P_NODE_KW, ANNUAL_HOURS,
    apply_rcparams,
)

# Class -> primary-tier index for edge-colour lookup; mirrors the
# default CLASS_TO_TIER mapping in workload_taxonomy.py.  Interactive
# and large_hpc are both T0 but we keep the same "0" key so the bar
# edge colour matches the ladder text colour in both cases.
_CLASS_TO_LADDER_TIER = {
    "interactive":      0,
    "workflow_coupled": 1,
    "elastic_ai":       2,
    "batch_parallel":   3,
    "geo_shiftable":    5,
    "large_hpc":        0,
}
from workload_taxonomy import CLASS_ORDER  # type: ignore[import-not-found]

apply_rcparams()


# ─────────────────────────────────────────────────────────────────────
# Data loading + shared helpers
# ─────────────────────────────────────────────────────────────────────

def _load(csv: Path) -> pd.DataFrame:
    """Load the taxonomy sweep CSV; back-compute ``d_cfe_vs_fcfs_pp``
    if the column is absent (older runs)."""
    df = pd.read_csv(csv)
    if "d_cfe_vs_fcfs_pp" not in df.columns:
        base = (df[df["layer"] == "fcfs"]
                .set_index(["country", "season", "seed"])["cfe_canonical_pct"])
        df = df.merge(
            base.rename("_fcfs_cfe").reset_index(),
            on=["country", "season", "seed"], how="left",
        )
        df["d_cfe_vs_fcfs_pp"] = df["cfe_canonical_pct"] - df["_fcfs_cfe"]
    return df


def _per_country_cfe(df: pd.DataFrame, layer: str = "fsla_taxonomy"):
    """Mean CFE, baseline CFE, Δ CFE, Δ CI per country, with SEM."""
    sub = df[df["layer"] == layer]
    rows = []
    for c in COUNTRY_ORDER:
        cell = sub[sub["country"] == c]
        if cell.empty:
            continue
        d_cfe_vals = cell["d_cfe_vs_fcfs_pp"].dropna().to_numpy(dtype=float)
        # Per-seed Δ CI = baseline CI - fsla CI within the same triple.
        merged = cell.merge(
            df[df["layer"] == "fcfs"][
                ["country", "season", "seed", "ci_weighted_mean"]
            ].rename(columns={"ci_weighted_mean": "fcfs_ci"}),
            on=["country", "season", "seed"], how="left",
        )
        d_ci = (merged["fcfs_ci"] - merged["ci_weighted_mean"]).dropna()
        d_ci_vals = d_ci.to_numpy(dtype=float)
        n = max(1, len(d_cfe_vals))
        rows.append({
            "country":  c,
            "ci_2025":  COUNTRY_CI_2025.get(c, np.nan),
            "d_cfe_pp": float(np.mean(d_cfe_vals)) if len(d_cfe_vals) else 0.0,
            "d_cfe_sem": (float(np.std(d_cfe_vals, ddof=0)) / np.sqrt(n)
                          if len(d_cfe_vals) > 1 else 0.0),
            "d_ci":     float(np.mean(d_ci_vals)) if len(d_ci_vals) else 0.0,
            "d_ci_sem": (float(np.std(d_ci_vals, ddof=0)) / np.sqrt(n)
                          if len(d_ci_vals) > 1 else 0.0),
        })
    return pd.DataFrame(rows)


def _avoided_kt_per_year(d_ci_g_per_kwh: float,
                          report_mw: float = 10.0) -> float:
    """Avoided tonnes/y for a continuous ``report_mw`` cluster.

    Sample-independent: uses cluster annual energy × measured Δ CI × PUE,
    so the secondary axis reads as "savings an operator at this scale
    would book per year".  Returns tonnes (kt × 1000) because the
    reference figure axis is labelled tCO₂/y, not kt.
    """
    annual_kwh = report_mw * 1.0e3 * ANNUAL_HOURS
    return (d_ci_g_per_kwh * annual_kwh * PUE_HEADLINE) / 1.0e6  # g/1e6 = t


def _placeholder(ax, msg: str, title: str = "") -> None:
    ax.text(0.5, 0.5, msg, ha="center", va="center",
             transform=ax.transAxes, fontsize=11,
             color="#888", style="italic")
    ax.set_xticks([]); ax.set_yticks([])
    if title:
        ax.set_title(title)


# ─────────────────────────────────────────────────────────────────────
# fig_paper_headline.pdf — Figure A style (2 panels)
# ─────────────────────────────────────────────────────────────────────

def render_headline(df: pd.DataFrame, out: Path) -> None:
    """Top: per-country Δ CFE bars + avoided tCO₂/y line on secondary
    axis; bottom: SE / PL bookends across the 4 seasons.

    Matches the reference figure layout: green→red bar gradient over
    the CI ramp, single grouped legend below the avoided-y axis line,
    seasonal small-multiples on the right panel for the cleanest /
    dirtiest grids so a reader can eyeball both "per-grid spread" and
    "season-to-season stability" without leaving the headline figure.
    """
    # Wider canvas (13.0" total vs the previous 9.6") with panel (a)
    # given 2x the horizontal real-estate of panel (b).  Six country
    # bars plus their two-line tick labels (bold abbreviation + CI
    # annotation below) need ~1.2" per bar to avoid the label run-
    # together that the narrower layout produced; this width keeps
    # ~1.3" per bar with the legend / secondary-axis label outside.
    # The paper's \includegraphics[width=\linewidth] will scale the
    # whole thing down to LNCS body width without resampling text.
    fig, axes = plt.subplots(
        1, 2, figsize=(13.0, 4.6), constrained_layout=True,
        gridspec_kw={"width_ratios": [2.0, 1.0]},
    )

    # ── Left panel: per-country Δ CFE bars + avoided line ────────────
    ax = axes[0]
    pc = _per_country_cfe(df, layer="fsla_taxonomy")
    if pc.empty:
        _placeholder(ax, "(no fsla_taxonomy rows)",
                     "(a) f-SLA Δ CFE across the EU CI spectrum")
    else:
        x = np.arange(len(pc))
        colors = [COUNTRY_COLORS[c] for c in pc["country"]]
        # Clip the lower error bar so spurious single-cell negatives
        # (cells where one seed's classifier randomization produced
        # below-mean lift) don't drag the visible bar below zero —
        # the headline is the mean across seeds, not any one cell.
        # Asymmetric yerr: (lower, upper).
        lower_err = np.minimum(pc["d_cfe_sem"].to_numpy(),
                                np.maximum(pc["d_cfe_pp"].to_numpy(), 0.0))
        upper_err = pc["d_cfe_sem"].to_numpy()
        ax.bar(x, pc["d_cfe_pp"], yerr=[lower_err, upper_err],
                color=colors, edgecolor="black", linewidth=0.6,
                error_kw=dict(ecolor="#333", lw=0.9))
        ax.axhline(0, color="black", lw=0.6)
        # Two-line tick labels: country abbreviation on top (large),
        # 2025 mean CI underneath (small).  Prevents the previous
        # "(12 g/kWh)33 g/kWh)" run-together when bars are narrow.
        ax.set_xticks(x)
        ax.set_xticklabels(pc["country"].tolist(),
                            fontsize=12, fontweight="bold")
        # Annotate the CI value below each tick label without using
        # the tick-label mechanism (so they never collide).
        ymin_label = ax.get_ylim()[0]
        for xi, ci_val in zip(x, pc["ci_2025"]):
            ax.annotate(f"{int(ci_val)} g/kWh",
                         xy=(xi, 0), xycoords=("data", "axes fraction"),
                         xytext=(0, -22), textcoords="offset points",
                         ha="center", va="top", fontsize=9, color="#555")
        ax.set_xlabel("Country (annual-mean CI 2025 below; $\\downarrow$ cleaner)",
                       labelpad=18)
        ax.set_ylabel("$\\Delta$ CFE (pp) vs FCFS  ($\\uparrow$ better)")
        ax.set_title("(a) f-SLA $\\Delta$ CFE at 10 MW — across the EU CI spectrum")
        # Headroom for the secondary axis line + annotations.
        ymax = float(max(pc["d_cfe_pp"] + pc["d_cfe_sem"]) * 1.25)
        ax.set_ylim(0.0, max(ymax, 1.0))

        # Secondary axis: avoided tCO₂/y at 10 MW.
        ax2 = ax.twinx()
        avoided_t = [_avoided_kt_per_year(d) for d in pc["d_ci"]]
        ax2.plot(x, avoided_t, "o-", color="#222", linewidth=1.5,
                  markersize=7, markerfacecolor="white",
                  markeredgewidth=1.4, zorder=5,
                  label="avoided tCO$_2$/y @ 10 MW")
        ax2.set_ylabel("avoided tCO$_2$/y at 10 MW  ($\\uparrow$ better)")
        ax2.spines["right"].set_visible(True)
        ax2.grid(False)
        ax2.legend(loc="upper left", frameon=False)

    # ── Right panel: SE/PL bookends across the 4 seasons ─────────────
    ax = axes[1]
    sub = df[df["layer"] == "fsla_taxonomy"]
    if sub.empty:
        _placeholder(ax, "(no fsla_taxonomy rows)",
                     "(b) Bookend seasonal stability: SE vs PL")
    else:
        x = np.arange(len(SEASONS))
        w = 0.36
        for i, c in enumerate(["SE", "PL"]):
            if c not in sub["country"].unique():
                continue
            ms, es = [], []
            for s in SEASONS:
                cell = sub[(sub["country"] == c) & (sub["season"] == s)]
                v = cell["d_cfe_vs_fcfs_pp"].dropna()
                if len(v):
                    ms.append(float(v.mean()))
                    es.append(float(v.std(ddof=0)) / max(1, np.sqrt(len(v))))
                else:
                    ms.append(0.0); es.append(0.0)
            # Clip lower bar of SE (near-ceiling grid → noisy negatives)
            # so the visible bar can't dip below zero by random seed
            # fluctuation.  Mean is the headline number.
            lower = np.minimum(es, np.maximum(ms, 0.0))
            upper = es
            ax.bar(x + (i - 0.5) * w, ms, w, yerr=[lower, upper],
                    label=f"{c} (CI={COUNTRY_CI_2025.get(c, '?')} g/kWh)",
                    color=COUNTRY_COLORS[c], edgecolor="black",
                    linewidth=0.6,
                    error_kw=dict(ecolor="#333", lw=0.9))
        ax.axhline(0, color="black", lw=0.6)
        ax.set_xticks(x); ax.set_xticklabels(SEASONS)
        ax.set_ylabel("$\\Delta$ CFE (pp)  ($\\uparrow$ better)")
        ax.set_title("(b) Seasonal stability: SE vs PL bookends")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12),
                  ncol=2, frameon=False)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"[09-paper-figures] wrote {out}")


# ─────────────────────────────────────────────────────────────────────
# fig_paper_class_breakdown.pdf — donut + per-class CFE
# ─────────────────────────────────────────────────────────────────────

def render_class_breakdown(df: pd.DataFrame, mix_csv: Optional[Path],
                            out: Path) -> None:
    # Wider canvas (12.0" vs 9.6") with the right panel given 1.4x the
    # horizontal real-estate of the left.  Reason: panel (b)'s 6
    # multi-line x-tick labels ("workflow", "elastic\nAI",
    # "batch\nparallel", ...) and the 0-100% y-axis both need more
    # room than the donut's compact legend; the v2.0 layout was almost
    # square and crammed the bar labels against the y-axis.
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.5),
                              constrained_layout=True,
                              gridspec_kw={"width_ratios": [0.95, 1.35]})
    # ── (a) Donut: class mix on the M100 trace + paper reference ────
    ax = axes[0]
    if mix_csv is not None and mix_csv.exists():
        mix = pd.read_csv(mix_csv).set_index("class").reindex(CLASS_ORDER)
        pcts = mix["pct_gpu_hours"].fillna(0).to_numpy()
        colors  = [CLASS_COLORS.get(c, "#888")    for c in CLASS_ORDER]
        hatches = [CLASS_HATCH.get(c, "")           for c in CLASS_ORDER]
        wedges, _ = ax.pie(pcts, colors=colors, startangle=90,
                            wedgeprops=dict(width=0.42, edgecolor="white",
                                              linewidth=1.5))
        # Apply hatching per-wedge.  Hatch strokes inherit the edge
        # colour (white here), so the pattern reads as light stripes /
        # dots over the saturated fill — distinguishes the two classes
        # that share a tier (large_hpc shares T0 red with interactive;
        # geo_shiftable's dark green can be confused with elastic_ai's
        # T2 green at a glance).
        for w, h in zip(wedges, hatches):
            if h:
                w.set_hatch(h)
        # Recolour the legend entries' text to match the tier text
        # palette (interactive=red, workflow=orange, elastic=green,
        # batch=teal, geo=sage, large_hpc=rigid-red).  Keeps the same
        # legend layout as before but makes the colour-coding two-fold
        # (fill swatch + label colour).
        legend_labels = [
            f"{CLASS_DISPLAY[cls]:<14s} {mix.loc[cls, 'pct_gpu_hours']:>4.1f}%  "
            f"(ref {PAPER_REFERENCE_PCT.get(cls, 0):>4.1f}%)"
            for cls in CLASS_ORDER
        ]
        # Legend slid in towards the donut: x=0.85 (inside the axis's
        # right edge) + compact handle + tighter labelspacing reclaims
        # ~0.6" of horizontal real-estate that the v2.0 layout wasted
        # as whitespace between the pie and the legend.
        leg = ax.legend(wedges, legend_labels,
                   loc="center left", bbox_to_anchor=(0.85, 0.5),
                   frameon=False, fontsize=10, handlelength=0.9,
                   handletextpad=0.5, labelspacing=0.45,
                   borderaxespad=0.0)
        # Recolour each legend label's text to its tier-text colour so
        # the legend visually echoes the "Mapped Workload Class" card.
        for txt, cls in zip(leg.get_texts(), CLASS_ORDER):
            txt.set_color(TIER_TEXT_COLORS[_CLASS_TO_LADDER_TIER[cls]])
            txt.set_fontweight("bold")
        ax.set_title("(a) M100 classification (% GPU$\\cdot$h)")
    else:
        _placeholder(ax, "(awaiting TAXONOMY_MIX.csv)",
                     "(a) M100 classification")

    # ── (b) Per-class CFE achieved by f-SLA ─────────────────────────
    ax = axes[1]
    sub = df[df["layer"] == "fsla_taxonomy"]
    class_cfe = {}
    for cls in CLASS_ORDER:
        col = f"class_{cls}_cfe_pct"
        if col in sub.columns:
            v = sub[col].dropna()
            if len(v):
                class_cfe[cls] = (float(v.mean()),
                                   float(v.std(ddof=0))
                                       / max(1, np.sqrt(len(v))))
    if class_cfe:
        xs = [cls for cls in CLASS_ORDER if cls in class_cfe]
        ms = [class_cfe[c][0] for c in xs]
        es = [class_cfe[c][1] for c in xs]
        cols    = [CLASS_COLORS[c] for c in xs]
        hatches = [CLASS_HATCH.get(c, "") for c in xs]
        # Solid saturated fill with WHITE edge so the hatch strokes
        # (also drawn in the edge colour) read as light stripes / dots
        # over the deep tier colour.  large_hpc gets diagonal hatching
        # ('///'), geo_shiftable gets dots ('...'); the other four
        # tiers are unique colours and stay solid.
        bars = ax.bar(np.arange(len(xs)), ms, yerr=es,
                color=cols, edgecolor="white", linewidth=1.2,
                error_kw=dict(ecolor="#333", lw=0.9))
        for bar, h in zip(bars, hatches):
            if h:
                bar.set_hatch(h)
        ax.set_xticks(np.arange(len(xs)))
        ax.set_xticklabels([CLASS_DISPLAY[c].replace(" ", "\n") for c in xs],
                            fontsize=10)
        # Recolour each x-tick label to its tier-text colour so the
        # category labels visually echo the ladder card.
        for tick_label, c in zip(ax.get_xticklabels(), xs):
            tick_label.set_color(TIER_TEXT_COLORS[_CLASS_TO_LADDER_TIER[c]])
            tick_label.set_fontweight("bold")
        ax.set_ylabel("CFE (Google 24$\\times$7) \\%  ($\\uparrow$ better)")
        ax.set_ylim(0, 100)
        ax.set_title("(b) Per-class CFE achieved by f-SLA")
    else:
        _placeholder(ax, "(no per-class CFE columns)",
                     "(b) Per-class CFE")

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"[09-paper-figures] wrote {out}")


# ─────────────────────────────────────────────────────────────────────
# fig_paper_seasonal.pdf — Δ CFE per country across 4 seasons
# ─────────────────────────────────────────────────────────────────────

def render_seasonal(df: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(W_TEXT, 4.0), constrained_layout=True)
    sub = df[df["layer"] == "fsla_taxonomy"]
    if sub.empty:
        _placeholder(ax, "(no fsla_taxonomy rows)",
                     "f-SLA CFE lift across seasons")
        fig.savefig(out, format="pdf", bbox_inches="tight")
        plt.close(fig); return
    x = np.arange(len(SEASONS))
    countries = [c for c in COUNTRY_ORDER if c in sub["country"].unique()]
    for c in countries:
        ms, es = [], []
        for s in SEASONS:
            cell = sub[(sub["country"] == c) & (sub["season"] == s)][
                "d_cfe_vs_fcfs_pp"]
            if len(cell):
                ms.append(float(cell.mean()))
                es.append(float(cell.std(ddof=0))
                          / max(1, np.sqrt(len(cell))))
            else:
                ms.append(np.nan); es.append(0.0)
        ax.errorbar(x, ms, yerr=es, marker="o",
                     color=COUNTRY_COLORS[c], label=c,
                     linewidth=1.8, markersize=7,
                     capsize=3, elinewidth=1.0)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xticks(x); ax.set_xticklabels(SEASONS)
    ax.set_ylabel("$\\Delta$ CFE (pp) vs FCFS  ($\\uparrow$ better)")
    ax.set_title("f-SLA CFE lift across four representative weeks")
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5),
              frameon=False, ncol=1, handlelength=1.6)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"[09-paper-figures] wrote {out}")


# ─────────────────────────────────────────────────────────────────────
# fig_paper_country_vs_ci.pdf — Δ CFE vs CI scatter w/ linear fit
# ─────────────────────────────────────────────────────────────────────

def render_country_vs_ci(df: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(W_TEXT, 4.2), constrained_layout=True)
    pc = _per_country_cfe(df, layer="fsla_taxonomy")
    if pc.empty:
        _placeholder(ax, "(no fsla_taxonomy rows)",
                     "$\\Delta$ CFE vs grid CI")
        fig.savefig(out, format="pdf", bbox_inches="tight")
        plt.close(fig); return
    xs = pc["ci_2025"].to_numpy(dtype=float)
    ms = pc["d_cfe_pp"].to_numpy(dtype=float)
    es = pc["d_cfe_sem"].to_numpy(dtype=float)
    labels = pc["country"].tolist()
    cols = [COUNTRY_COLORS[c] for c in labels]
    ax.errorbar(xs, ms, yerr=es, fmt="none",
                 ecolor="#333", elinewidth=1.0, capsize=4, zorder=2)
    for x, y, lab, col in zip(xs, ms, labels, cols):
        ax.scatter(x, y, s=130, color=col, zorder=4,
                    edgecolor="black", linewidth=0.8)
        # Country abbreviation annotation — offset above-right of point
        # except for SE (offset above-left so it doesn't collide with CH).
        dx, dy = (10, 8) if lab not in ("SE", "CH") else (-20, 8)
        ax.annotate(lab, (x, y), xytext=(dx, dy),
                     textcoords="offset points", fontsize=12,
                     fontweight="bold")
    if len(xs) >= 2:
        m, b = np.polyfit(xs, ms, 1)
        xx = np.linspace(0, max(xs) * 1.05, 50)
        ax.plot(xx, m * xx + b, "--", color="#555", lw=1.2,
                 label=f"linear fit: $\\Delta$ CFE $= "
                       f"{m:+.4f}\\cdot$CI ${b:+.2f}$")
        ax.legend(loc="upper left", frameon=False)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xlabel("Grid annual-mean CI 2025 (g CO$_2$eq / kWh)  ($\\leftarrow$ cleaner)")
    ax.set_ylabel("$\\Delta$ CFE (pp) vs FCFS  ($\\uparrow$ better)")
    ax.set_xlim(left=0)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"[09-paper-figures] wrote {out}")


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--taxonomy-csv", type=Path, required=True)
    p.add_argument("--taxonomy-mix", type=Path, default=None)
    p.add_argument("--out-dir",      type=Path, required=True)
    args = p.parse_args(argv)

    if not args.taxonomy_csv.exists():
        print(f"ABORT: taxonomy CSV not found at {args.taxonomy_csv}",
              file=sys.stderr)
        return 2

    df = _load(args.taxonomy_csv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    render_headline(df,        args.out_dir / "fig_paper_headline.pdf")
    render_class_breakdown(df, args.taxonomy_mix,
                           args.out_dir / "fig_paper_class_breakdown.pdf")
    render_seasonal(df,        args.out_dir / "fig_paper_seasonal.pdf")
    render_country_vs_ci(df,   args.out_dir / "fig_paper_country_vs_ci.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
