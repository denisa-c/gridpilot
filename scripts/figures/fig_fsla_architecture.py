#!/usr/bin/env python3
"""
scripts/figures/fig_fsla_architecture.py
========================================
Simplified f-SLA architecture diagram --- matplotlib renderer
that mirrors the editable papers/pecs2026/architecture.pptx master.

Design rules (mirrors the WHPC architecture):
  * NO hatching --- it makes the box text unreadable.
  * Distinct colours per logical role.
  * Layer labels OUTSIDE the boxes when used.
  * Long arrows with labels positioned ABOVE the arrow with
    white-background bbox so they never overlap source/target boxes.
  * Multi-line text inside boxes with margins; one bold title +
    1-2 lines of regular body.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


mpl.rcParams.update({
    "font.family":      "sans-serif",
    "font.sans-serif":  ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size":        10.0,
    "pdf.fonttype":     42,
    "ps.fonttype":      42,
    "savefig.bbox":     "tight",
    "savefig.pad_inches": 0.10,
})

# Colours per logical role
USER_FC,    USER_EC    = "#cfe1f7", "#2c5fa3"   # blue   - user
AI_FC,      AI_EC      = "#fde5b8", "#a86d18"   # amber  - AI baseline / operator
LEDGER_FC,  LEDGER_EC  = "#d6efd1", "#3a7d44"   # green  - accounting
SCHED_FC,   SCHED_EC   = "#f9d5cd", "#b8362e"   # coral  - scheduler
GRID_FC,    GRID_EC    = "#e7d3ee", "#5d3a78"   # purple - electricity grid
CALLOUT_FC, CALLOUT_EC = "#fffceb", "#a86d18"

ARROW_BLACK = "#222222"
TEXT_COLOR = "#111111"
LABEL_COLOR = "#444444"
POC_COLOR = "#b8362e"


def _box(ax, x, y, w, h, *, title, body=None, fc, ec,
          title_fs=10.5, body_fs=9.0, lw=1.1, title_pad_top=0.024):
    p = FancyBboxPatch((x, y), w, h,
                        boxstyle="round,pad=0.005,rounding_size=0.012",
                        fc=fc, ec=ec, lw=lw)
    ax.add_patch(p)
    if body:
        ax.text(x + w / 2, y + h - title_pad_top, title,
                 ha="center", va="top",
                 fontsize=title_fs, fontweight="bold", color=TEXT_COLOR)
        ax.text(x + w / 2, y + h * 0.40, body,
                 ha="center", va="center",
                 fontsize=body_fs, color=TEXT_COLOR, wrap=True)
    else:
        ax.text(x + w / 2, y + h / 2, title,
                 ha="center", va="center",
                 fontsize=title_fs, fontweight="bold", color=TEXT_COLOR)


def _arrow(ax, x1, y1, x2, y2, *, color=ARROW_BLACK, lw=1.4,
            label=None, label_dx=0.0, label_dy=0.0, ls="-",
            label_fs=8.5, label_align="center"):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="-|>", mutation_scale=12, lw=lw,
        color=color, linestyle=ls, shrinkA=4, shrinkB=4,
    ))
    if label:
        mx = (x1 + x2) / 2 + label_dx
        my = (y1 + y2) / 2 + label_dy
        ax.text(mx, my, label, ha=label_align, va="center",
                 fontsize=label_fs, color=color,
                 bbox=dict(facecolor="white", edgecolor="none",
                            boxstyle="round,pad=0.18", alpha=0.95))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                     default=Path("figs/architecture_pecs.pdf"))
    args = ap.parse_args(argv)

    fig, ax = plt.subplots(figsize=(9.0, 5.5))
    ax.set_xlim(0, 1.0); ax.set_ylim(0, 1.0)
    ax.axis("off")

    # ── Layout ────────────────────────────────────────────────
    # Two-column top, then three full-width rows below.
    USER_L, USER_R   = 0.05, 0.45
    AI_L,   AI_R     = 0.55, 0.95
    FULL_L, FULL_R   = 0.05, 0.95

    Y_TOP    = 0.86          # centre-y of user / AI row
    Y_LEDGER = 0.61          # centre-y of accounting layer
    Y_SCHED  = 0.38          # centre-y of scheduler
    Y_GRID   = 0.14          # centre-y of grid outcome

    H_TOP    = 0.14
    H_FULL   = 0.13

    # ── Top row: user (left) + AI baseline (right)
    _box(ax, USER_L, Y_TOP - H_TOP/2, USER_R - USER_L, H_TOP,
          title="User submits a job",
          body="Picks a tier on a 4-step ladder:\n"
                "T0 rigid  ·  T1 hour  ·  T2 day  ·  T3 week",
          fc=USER_FC, ec=USER_EC, body_fs=9.5)
    _box(ax, AI_L, Y_TOP - H_TOP/2, AI_R - AI_L, H_TOP,
          title="AI baseline  (per-user predictor)",
          body="Shows the user the tier the AI expects;\n"
                "the user beats the AI to earn credit + rank",
          fc=AI_FC, ec=AI_EC, body_fs=9.5)

    # ── f-SLA accounting layer (full width)
    _box(ax, FULL_L, Y_LEDGER - H_FULL/2, FULL_R - FULL_L, H_FULL,
          title="f-SLA accounting layer",
          body="per-user credit ledger  ·  leaderboard  ·  "
                "log of (AI predicted, user declared, actually realised)\n"
                "this log is the dataset that replaces the synthetic prior",
          fc=LEDGER_FC, ec=LEDGER_EC, body_fs=9.0)

    # ── Carbon-aware scheduler (full width)
    _box(ax, FULL_L, Y_SCHED - H_FULL/2, FULL_R - FULL_L, H_FULL,
          title="Carbon-aware scheduler  (any EASY-FCFS dispatcher)",
          body="Defers each job within the declared tier window to a low-CI hour;\n"
                "the slowdown clause caps the worst-case wait",
          fc=SCHED_FC, ec=SCHED_EC, body_fs=9.0)

    # ── Electricity grid outcome (full width)
    _box(ax, FULL_L, Y_GRID - H_FULL/2, FULL_R - FULL_L, H_FULL,
          title="Electricity grid  (multi-country: SE, CH, FR, IT, DE, PL @ 1/10/50 MW)",
          body="Carbon-Free Energy lift ranges from +14 pp on a near-decarbonised grid (SE)\n"
                "down to +3.6 pp on a coal-heavy grid (PL)",
          fc=GRID_FC, ec=GRID_EC, body_fs=9.0)

    # ── Arrows ───────────────────────────────────────────────
    # User -> Accounting (long vertical, label on top)
    _arrow(ax,
            (USER_L + USER_R)/2, Y_TOP - H_TOP/2,
            (USER_L + USER_R)/2, Y_LEDGER + H_FULL/2,
            label="declared tier", label_dx=0.0)

    # AI -> Accounting (logged triple)
    _arrow(ax,
            (AI_L + AI_R)/2, Y_TOP - H_TOP/2,
            (AI_L + AI_R)/2, Y_LEDGER + H_FULL/2,
            label="AI predicted tier")

    # AI -> User (dashed feedback, "AI prediction" shown to the user)
    _arrow(ax,
            AI_L, Y_TOP,
            USER_R + 0.005, Y_TOP,
            ls="dashed", color="#666666",
            label="AI prediction shown to user", label_align="center",
            label_dy=0.045)

    # Accounting -> Scheduler
    _arrow(ax,
            0.50, Y_LEDGER - H_FULL/2,
            0.50, Y_SCHED + H_FULL/2,
            label="tiered jobs")

    # Scheduler -> Grid
    _arrow(ax,
            0.50, Y_SCHED - H_FULL/2,
            0.50, Y_GRID + H_FULL/2,
            label="dispatch")

    # ── Proof-of-concept stamp
    ax.text(0.99, 0.02,
             "Proof of concept --- numbers are illustrative; "
             "the contract is the contribution.",
             ha="right", va="bottom",
             fontsize=8.5, fontstyle="italic",
             color=POC_COLOR)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_fsla_architecture] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
