#!/usr/bin/env python3
"""
experiments_v2/scripts/07_render_seasonal_figure.py
====================================================
Phase 5c — render the 2×2 fig_proact_1x4-style figure (Figure B).

Panels (left-to-right, top-to-bottom):
  (a) CFE adoption surface   — analytical contour; equilibrium Ω*.
  (b) CFE-lift by country and season  — bar chart from
      data/taxonomy_sweep/taxonomy_sweep.csv  (the v2 carbon-aware
      f-SLA dispatcher).  Uses the per-(country,season,seed) Δ vs the
      FCFS baseline within the same triple — sign-consistent with Δ CI.
  (c) Summer CI diurnal profiles for CH/IT/DE  — real ENTSO-E
      hourly data when present (gridpilot/data/ci/entsoe/),
      synthesised from per-country YAML otherwise.
  (d) Pareto front across all (country × season × layer × seed)
      cells — (mean slowdown, net Δ CFE pp) from the taxonomy CSV.

Style and colour palette are imported from
``experiments_v2/src/figure_style`` so this figure looks like the
f-SLA paper publication figure pack (09_render_paper_figures.py) at a glance.

Missing data → that panel shows an ``(awaiting <input>)`` placeholder
so the figure compiles cleanly during incremental build-out.

Usage:
  PYTHONPATH=gridpilot/experiments_v2/src python3 \\
      gridpilot/experiments_v2/scripts/07_render_seasonal_figure.py \\
      --taxonomy-csv gridpilot/experiments_v2/data/taxonomy_sweep/taxonomy_sweep.csv \\
      --out          gridpilot/experiments_v2/figs/paper/fig_paper_seasonal_2x2.pdf
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
GRIDPILOT = ROOT / "gridpilot"
ENTSOE_DIR = GRIDPILOT / "data" / "ci" / "entsoe"
GRIDS_DIR  = GRIDPILOT / "configs" / "grids"
sys.path.insert(0, str(ROOT / "gridpilot" / "experiments_v2" / "src"))

from figure_style import (  # type: ignore[import-not-found]
    COUNTRY_ORDER, COUNTRY_COLORS, COUNTRY_CI_2025,
    SEASONS, W_DOUBLE_COL, apply_rcparams,
)

apply_rcparams()
# Slightly smaller body font for the 4-panel grid so titles never
# collide with the colourbar / legends on tight constrained layouts.
plt.rcParams.update({"font.size": 11, "axes.titlesize": 12,
                     "axes.labelsize": 11, "legend.fontsize": 10,
                     "xtick.labelsize": 10, "ytick.labelsize": 10})

SUMMER_ANCHOR = datetime(2025, 7, 15, tzinfo=timezone.utc)


def _placeholder(ax, msg: str, title: str = "") -> None:
    ax.text(0.5, 0.5, msg, ha="center", va="center",
             transform=ax.transAxes, fontsize=11,
             color="#888", style="italic")
    ax.set_xticks([]); ax.set_yticks([])
    if title: ax.set_title(title)


# ─────────────────────────────────────────────────────────────────────
# Panel (a) — Per-country baseline vs f-SLA CFE %  (data-driven)
# ─────────────────────────────────────────────────────────────────────

def panel_a(ax, taxonomy_csv: Optional[Path]) -> None:
    """Per-country side-by-side bars: FCFS-baseline CFE% (lighter) vs
    f-SLA CFE% (darker country colour).  Anchors the reader's
    interpretation of every other panel: where bars are short and
    close (SE, CH) the contract has no headroom; where the FCFS bar
    is short and the f-SLA bar is much taller (DE, PL) is where the
    contract earns its keep.
    """
    if taxonomy_csv is None or not taxonomy_csv.exists():
        _placeholder(ax, "(awaiting taxonomy sweep run)",
                     "(a) FCFS vs f-SLA CFE\\,\\%  ($\\uparrow$ better)")
        return
    df = pd.read_csv(taxonomy_csv)
    sub_b = df[df["layer"] == "fcfs"]
    sub_f = df[df["layer"] == "fsla_taxonomy"]
    if sub_b.empty or sub_f.empty:
        _placeholder(ax, "(missing fcfs or fsla_taxonomy)",
                     "(a) FCFS vs f-SLA CFE\\,\\%  ($\\uparrow$ better)")
        return
    countries = [c for c in COUNTRY_ORDER
                 if c in sub_b["country"].unique()
                 and c in sub_f["country"].unique()]
    x = np.arange(len(countries))
    w = 0.38
    base_v, base_e, f_v, f_e = [], [], [], []
    for c in countries:
        b = sub_b[sub_b["country"] == c]["cfe_canonical_pct"].dropna()
        f = sub_f[sub_f["country"] == c]["cfe_canonical_pct"].dropna()
        base_v.append(float(b.mean()) if len(b) else 0.0)
        base_e.append(float(b.std(ddof=0)) / max(1, np.sqrt(len(b))) if len(b) else 0.0)
        f_v.append(float(f.mean()) if len(f) else 0.0)
        f_e.append(float(f.std(ddof=0)) / max(1, np.sqrt(len(f))) if len(f) else 0.0)
    # FCFS bars: same country colour but heavily de-saturated; f-SLA
    # bars: full country colour.
    base_colors = [COUNTRY_COLORS[c] + "55" for c in countries]   # alpha hex
    fsla_colors = [COUNTRY_COLORS[c] for c in countries]
    ax.bar(x - w/2, base_v, w, yerr=base_e, label="FCFS",
            color=base_colors, edgecolor="black", linewidth=0.5,
            error_kw=dict(ecolor="#333", lw=0.8))
    ax.bar(x + w/2, f_v,   w, yerr=f_e,   label="f-SLA",
            color=fsla_colors, edgecolor="black", linewidth=0.5,
            error_kw=dict(ecolor="#333", lw=0.8))
    ax.set_xticks(x); ax.set_xticklabels(countries, fontweight="bold")
    # Headroom (0..108) so the inside-top legend never overlaps the
    # tall CH / SE bars that already sit at ~98 %.
    ax.set_ylim(0, 108)
    ax.set_ylabel(r"CFE (Google 24$\times$7) \%  ($\uparrow$ better)")
    ax.set_title("(a) FCFS baseline vs f-SLA CFE per country")
    # Legend INSIDE the panel, top-right corner, two columns
    # (FCFS / f-SLA).  Anchored to the top-right of the axes so it
    # sits next to the CH bars without colliding with the title.
    ax.legend(loc="upper right", bbox_to_anchor=(0.99, 0.99),
              frameon=False, ncol=2, handlelength=1.4,
              handletextpad=0.5, columnspacing=1.2)


# ─────────────────────────────────────────────────────────────────────
# Panel (b) — Δ CFE by country × season (from taxonomy_sweep)
# ─────────────────────────────────────────────────────────────────────

def panel_b(ax, taxonomy_csv: Optional[Path]) -> None:
    """Per-(country, season) f-SLA Δ CFE vs FCFS, error bars over seeds.

    Uses the **v2-native carbon-aware** ``fsla_taxonomy`` layer (not
    the legacy ``fsla_M3``); per-triple Δ is sign-consistent with Δ CI
    and avoids the denominator-blowup pathology of an older CO₂-ratio
    formula.
    """
    if taxonomy_csv is None or not taxonomy_csv.exists():
        _placeholder(ax, "(awaiting taxonomy sweep run)",
                     "(b) Δ CFE by country and season")
        return
    df = pd.read_csv(taxonomy_csv)
    if df.empty:
        _placeholder(ax, "(empty taxonomy CSV)",
                     "(b) Δ CFE by country and season")
        return
    if "d_cfe_vs_fcfs_pp" not in df.columns:
        base = (df[df["layer"] == "fcfs"]
                .set_index(["country", "season", "seed"])["cfe_canonical_pct"])
        df = df.merge(
            base.rename("fcfs_cfe").reset_index(),
            on=["country", "season", "seed"], how="left",
        )
        df["d_cfe_vs_fcfs_pp"] = df["cfe_canonical_pct"] - df["fcfs_cfe"]

    sub = df[df["layer"] == "fsla_taxonomy"]
    if sub.empty:
        _placeholder(ax, "(no fsla_taxonomy rows)",
                     "(b) Δ CFE by country and season")
        return

    # All 6 countries × 4 seasons.  Country = colour, season = x-group.
    # Bars are slim (width = 0.13) so 6 countries fit per group with
    # breathing room; SEM clipped at zero so noisy near-ceiling SE/CH
    # bars can't dip below the axis.
    countries = [c for c in COUNTRY_ORDER if c in sub["country"].unique()]
    width = 0.13
    xp = np.arange(len(SEASONS))
    for i, c in enumerate(countries):
        ms, es = [], []
        for s in SEASONS:
            cell = sub[(sub["country"] == c) & (sub["season"] == s)][
                "d_cfe_vs_fcfs_pp"]
            v = cell.dropna()
            if len(v):
                ms.append(float(v.mean()))
                es.append(float(v.std(ddof=0)) / max(1, np.sqrt(len(v))))
            else:
                ms.append(0.0); es.append(0.0)
        offset = (i - (len(countries) - 1) / 2) * width
        ms_arr = np.array(ms, dtype=float)
        es_arr = np.array(es, dtype=float)
        lower = np.minimum(es_arr, np.maximum(ms_arr, 0.0))
        ax.bar(xp + offset, ms, width, yerr=[lower, es_arr], label=c,
                color=COUNTRY_COLORS.get(c, "#888"),
                edgecolor="white", linewidth=0.5,
                error_kw=dict(ecolor="#333", lw=0.7))
    ax.axhline(0, color="black", lw=0.5)
    ax.set_xticks(xp); ax.set_xticklabels(SEASONS)
    ax.set_ylabel(r"$\Delta$ CFE (pp) vs FCFS  ($\uparrow$ better)")
    ax.set_title("(b) Savings by country $\\times$ season")
    # Legend BELOW the panel, single horizontal row of 6 country
    # swatches.  bbox y = -0.22 leaves enough room for the season
    # x-tick labels to sit between the axis and the legend.
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18),
              frameon=False, ncol=len(countries),
              handlelength=1.4, handletextpad=0.5,
              columnspacing=1.5)


# ─────────────────────────────────────────────────────────────────────
# Panel (c) — Summer CI diurnal profiles (ENTSO-E or synth)
# ─────────────────────────────────────────────────────────────────────

def _entsoe_summer_diurnal(country: str) -> Optional[tuple]:
    """Return (hours, mean_CI, std_CI) for the country's summer week
    centred on SUMMER_ANCHOR, from the local ENTSO-E parquet."""
    p = ENTSOE_DIR / f"{country}_hourly.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if "carbon_intensity_gCO2eq_per_kWh" not in df.columns:
        return None
    df.index = pd.to_datetime(df.index, utc=True)
    start = SUMMER_ANCHOR - timedelta(days=3)
    end   = SUMMER_ANCHOR + timedelta(days=4)
    win = df.loc[(df.index >= start) & (df.index < end),
                  "carbon_intensity_gCO2eq_per_kWh"]
    if len(win) < 24:
        return None
    by_hour = win.groupby(win.index.hour)
    hours = np.arange(24)
    means = by_hour.mean().reindex(hours).to_numpy()
    stds  = by_hour.std().reindex(hours).fillna(0.0).to_numpy()
    return hours, means, stds


def _synth_summer_diurnal(country: str) -> tuple:
    hours = np.arange(24)
    base_amp = {
        "SE": (11,   3),  "CH": (30,   8),
        "FR": (53,  12),  "IT": (258, 60),
        "DE": (295, 110), "PL": (612, 70),
    }
    b, a = base_amp.get(country, (200, 40))
    means = b + a * np.sin(2 * np.pi * (hours - 7) / 24) ** 2
    return hours, means, means * 0.15


def panel_c(ax, log_y: bool = True) -> None:
    """Per-country summer diurnal CI profiles.  Log y-axis by default so
    the 60$\\times$ dynamic range from SE (~12 g/kWh) to PL (~600 g/kWh)
    fits on one plot without flattening the smaller-CI curves."""
    for c in COUNTRY_ORDER:
        result = _entsoe_summer_diurnal(c)
        if result is not None:
            hours, means, stds = result
        else:
            hours, means, stds = _synth_summer_diurnal(c)
        ax.plot(hours, means, label=c, color=COUNTRY_COLORS[c],
                 linewidth=1.8)
        ax.fill_between(hours,
                         np.maximum(means - stds, 0.5), means + stds,
                         color=COUNTRY_COLORS[c], alpha=0.15)
    ax.set_xlabel("Hour of day (UTC)")
    ax.set_ylabel(r"Carbon intensity (g CO$_2$/kWh, log) ($\downarrow$ cleaner)")
    ax.set_title("(c) Summer CI diurnal profiles")
    ax.set_xticks([0, 6, 12, 18, 24])
    if log_y:
        ax.set_yscale("log")
    # Legend OUTSIDE the panel on the right, single column of country
    # abbreviations.  constrained_layout reserves the space; the
    # bbox_to_anchor=(1.02, 0.5) keeps a small gap between the plot
    # area and the legend so the rightmost line stays unobscured.
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5),
              frameon=False, handlelength=1.4, handletextpad=0.5,
              labelspacing=0.4, borderaxespad=0.0)


# ─────────────────────────────────────────────────────────────────────
# Panel (d) — Pareto front (slowdown, Δ CFE pp) across cells
# ─────────────────────────────────────────────────────────────────────

def panel_d(ax, taxonomy_csv: Optional[Path], log_x: bool = False) -> None:
    """QoS frontier: every f-SLA cell as one point in (p95 slowdown,
    $\\Delta$CFE).  Points coloured by country so the reader can trace
    where each grid lives in the trade-off; the Pareto front (red line)
    is the operationally relevant "best-achievable" boundary.  The
    upper-left quadrant is the goal: cleanest grids cluster near
    (1$\\times$, 0\\;pp) by construction (no headroom), dirtiest grids
    push the front out to the upper right (real lift, real wait)."""
    if taxonomy_csv is None or not taxonomy_csv.exists():
        _placeholder(ax, "(awaiting taxonomy sweep run)",
                     "(d) QoS frontier")
        return
    df = pd.read_csv(taxonomy_csv)
    if df.empty:
        _placeholder(ax, "(empty taxonomy CSV)", "(d) QoS frontier")
        return
    if "d_cfe_vs_fcfs_pp" not in df.columns:
        base = (df[df["layer"] == "fcfs"]
                .set_index(["country", "season", "seed"])["cfe_canonical_pct"])
        df = df.merge(
            base.rename("fcfs_cfe").reset_index(),
            on=["country", "season", "seed"], how="left",
        )
        df["d_cfe_vs_fcfs_pp"] = df["cfe_canonical_pct"] - df["fcfs_cfe"]

    pts = df[df["layer"] == "fsla_taxonomy"].dropna(
        subset=["p95_slowdown", "d_cfe_vs_fcfs_pp"])
    if pts.empty:
        _placeholder(ax, "(no fsla_taxonomy cells)", "(d) QoS frontier")
        return

    sd = pts["p95_slowdown"].to_numpy(dtype=float)
    sv = pts["d_cfe_vs_fcfs_pp"].to_numpy(dtype=float)
    countries_pts = pts["country"].tolist()
    n = len(sd)
    # Scatter one point per cell, coloured by country.
    for c in COUNTRY_ORDER:
        idx = [i for i, cc in enumerate(countries_pts) if cc == c]
        if not idx: continue
        ax.scatter(sd[idx], sv[idx],
                    color=COUNTRY_COLORS[c], alpha=0.65, s=45,
                    edgecolor="black", linewidth=0.4, label=c)

    # Pareto front: minimise slowdown, maximise Δ CFE.
    pi = []
    for i in range(n):
        dominated = False
        for j in range(n):
            if j == i: continue
            if (sd[j] <= sd[i] and sv[j] >= sv[i]
                    and (sd[j] < sd[i] or sv[j] > sv[i])):
                dominated = True; break
        if not dominated:
            pi.append(i)
    pi = sorted(pi, key=lambda k: sd[k])
    if pi:
        ax.plot(sd[pi], sv[pi], "-", color="#222",
                 linewidth=1.8, label="Pareto front", zorder=3)
        ax.scatter(sd[pi], sv[pi], color="#222", s=55,
                    zorder=5, edgecolor="white", linewidth=0.8)

    ax.axhline(0, color="black", lw=0.5)
    ax.set_xlabel(r"p95 slowdown ($\times$)  ($\leftarrow$ better)")
    ax.set_ylabel(r"$\Delta$ CFE (pp) vs FCFS  ($\uparrow$ better)")
    ax.set_title(f"(d) QoS frontier ({n} cells)")
    if log_x:
        ax.set_xscale("log")
    # Legend OUTSIDE the panel on the right (single column),
    # matching panel (c) so the two right-hand panels read as a pair.
    # Pareto-front line + 6 country swatches in one block.
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5),
              frameon=False, handlelength=1.2, handletextpad=0.5,
              labelspacing=0.4, borderaxespad=0.0, fontsize=10)


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--taxonomy-csv", type=Path, default=None,
                    help="data/taxonomy_sweep/taxonomy_sweep.csv "
                         "(v2 carbon-aware f-SLA dispatcher results)")
    # Back-compat: accept --seasonal-csv if a caller still uses it.
    p.add_argument("--seasonal-csv", type=Path, default=None,
                    help=argparse.SUPPRESS)
    p.add_argument("--out", type=Path, required=True,
                    help="Primary output path (panel (c) on log y).  A "
                         "second variant with panel (c) on a linear y "
                         "scale is also written alongside it, suffixed "
                         "with _linearC.")
    p.add_argument("--log", action="store_true",
                    help="Use log scale for panel (d) X axis.")
    p.add_argument("--no-linear-variant", action="store_true",
                    help="Suppress the linear-y variant of panel (c).")
    args = p.parse_args(argv)
    src_csv = args.taxonomy_csv or args.seasonal_csv

    def _build(log_c_y: bool, out_path: Path) -> None:
        # 50% wider and shorter than the v2.0 layout: 14.4" x 6.0"
        # gives each of the four panels a ~7" x 3" working area --
        # enough horizontal room for the country / season tick labels
        # and the outside-right legends in panels (c) and (d) without
        # the title / axis-label collisions a square layout produced.
        # Extra vertical padding (hspace) reserves room for panel (b)'s
        # below-axis legend without letting it overlap panel (d).
        fig, axes = plt.subplots(2, 2, figsize=(14.4, 6.0),
                                  constrained_layout=True)
        fig.set_constrained_layout_pads(w_pad=0.10, h_pad=0.10,
                                         wspace=0.08, hspace=0.18)
        axes = axes.flatten()
        panel_a(axes[0], src_csv)
        panel_b(axes[1], src_csv)
        panel_c(axes[2], log_y=log_c_y)
        panel_d(axes[3], src_csv, log_x=args.log)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, format="pdf", bbox_inches="tight")
        plt.close(fig)
        print(f"[07-seasonal-figure] wrote {out_path}  "
              f"(panel-c y: {'log' if log_c_y else 'linear'})")

    # Headline variant: panel (c) on log y so SE..PL fit on one plot
    # without the small-CI lines getting flattened.  This is the file
    # included by main.tex.
    _build(log_c_y=True,  out_path=args.out)
    # Companion variant: panel (c) on linear y so the diurnal-amplitude
    # ranking (DE largest swing, SE smallest) is easy to read by eye
    # for grids in the same order of magnitude.  Written alongside the
    # primary output with a "_linearC" suffix in the filename stem.
    if not args.no_linear_variant:
        linear_path = args.out.with_name(
            args.out.stem + "_linearC" + args.out.suffix
        )
        _build(log_c_y=False, out_path=linear_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
