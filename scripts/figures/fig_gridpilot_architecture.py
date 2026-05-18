#!/usr/bin/env python3
"""
scripts/figures/fig_gridpilot_architecture.py
=============================================
Simplified GridPilot architecture diagram --- matplotlib renderer
that mirrors the editable papers/whpc2026/architecture.pptx master.

Design rules (in response to reviewer feedback):
  * NO hatching --- it makes the box text unreadable.
  * Distinct colours per layer for visual differentiation.
  * Layer labels OUTSIDE the boxes, in a dedicated left margin.
  * Arrows long enough that their labels sit on TOP of the arrow
    line with breathing room (not overlapping the source/target box).
  * Multi-line text inside boxes, with proper margins; one line of
    bold heading + 1-2 lines of regular body.
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

# Distinct colours per logical role -----------------------------------
# Layer fills (light tints, picked for clear separation when printed
# in colour or screenshotted).  Borders are darker shades of the
# same hue for a coherent look.
TIER3_FC, TIER3_EC = "#cfe1f7", "#2c5fa3"   # blue   -- cluster
TIER2_FC, TIER2_EC = "#fde5b8", "#a86d18"   # amber  -- host
TIER1_FC, TIER1_EC = "#d6efd1", "#3a7d44"   # green  -- per-GPU
HW_FC,    HW_EC    = "#dcdcdc", "#444444"   # neutral grey -- hardware
GRID_FC,  GRID_EC  = "#e7d3ee", "#5d3a78"   # purple -- grid
SAFE_FC,  SAFE_EC  = "#f9d5cd", "#b8362e"   # coral  -- safety island
CALLOUT_FC, CALLOUT_EC = "#fff3ee", "#b8362e"

ARROW_BLACK = "#222222"
ARROW_BYPASS = "#b8362e"
TEXT_COLOR = "#111111"
LABEL_COLOR = "#444444"


def _box(ax, x, y, w, h, *, title, body=None, fc, ec,
          title_fs=10.5, body_fs=9.0, lw=1.1, title_pad_top=0.024):
    """Rounded rectangle with a bold title and an optional body line.
    Text is positioned absolutely so it cannot overflow.
    """
    p = FancyBboxPatch((x, y), w, h,
                        boxstyle="round,pad=0.005,rounding_size=0.012",
                        fc=fc, ec=ec, lw=lw)
    ax.add_patch(p)
    # Title near the top of the box
    if body:
        ax.text(x + w / 2, y + h - title_pad_top, title,
                 ha="center", va="top",
                 fontsize=title_fs, fontweight="bold", color=TEXT_COLOR)
        ax.text(x + w / 2, y + h * 0.42, body,
                 ha="center", va="center",
                 fontsize=body_fs, color=TEXT_COLOR, wrap=True)
    else:
        ax.text(x + w / 2, y + h / 2, title,
                 ha="center", va="center",
                 fontsize=title_fs, fontweight="bold", color=TEXT_COLOR)


def _layer_label(ax, x_right, y, text):
    """Italic layer tag positioned to the LEFT of the column."""
    ax.text(x_right, y, text, ha="right", va="center",
             fontsize=10.0, fontstyle="italic", color=LABEL_COLOR,
             fontweight="bold")


def _arrow(ax, x1, y1, x2, y2, *, color=ARROW_BLACK, lw=1.4,
            label=None, label_above=True, label_fs=8.5,
            label_dx=0.0, ls="-"):
    """Straight arrow with an optional label placed cleanly above
    (or beside) the arrow line, well clear of source/target boxes.
    """
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="-|>", mutation_scale=12, lw=lw,
        color=color, linestyle=ls, shrinkA=4, shrinkB=4,
    ))
    if label:
        mx = (x1 + x2) / 2 + label_dx
        my = (y1 + y2) / 2
        # Offset label above the arrow if vertical, beside if horizontal
        if abs(x2 - x1) < abs(y2 - y1):
            # vertical arrow --> label to the side
            ax.text(mx + 0.02, my, label, ha="left", va="center",
                     fontsize=label_fs, color=color,
                     bbox=dict(facecolor="white", edgecolor="none",
                                boxstyle="round,pad=0.18", alpha=0.95))
        else:
            ax.text(mx, my + 0.025, label, ha="center", va="bottom",
                     fontsize=label_fs, color=color,
                     bbox=dict(facecolor="white", edgecolor="none",
                                boxstyle="round,pad=0.18", alpha=0.95))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                     default=Path("figs/architecture_whpc.pdf"))
    args = ap.parse_args(argv)

    fig, ax = plt.subplots(figsize=(9.0, 5.5))
    ax.set_xlim(0, 1.0); ax.set_ylim(0, 1.0)
    ax.axis("off")

    # ── Layout grid (logical coordinates) ────────────────────────
    LABEL_R = 0.13                       # right edge of layer labels
    MAIN_L, MAIN_R = 0.16, 0.62          # main column box bounds
    RIGHT_L, RIGHT_R = 0.70, 0.96        # right column (grid + safety)

    # Tier vertical positions (centre-y of each box)
    Y_T3, Y_T2, Y_T1, Y_HW = 0.83, 0.65, 0.47, 0.21
    BOX_H_MAIN = 0.11
    BOX_H_HW   = 0.13

    # ── Layer labels (left margin)
    _layer_label(ax, LABEL_R - 0.005, Y_T3, "Tier 3\n(hourly)")
    _layer_label(ax, LABEL_R - 0.005, Y_T2, "Tier 2\n(1 Hz)")
    _layer_label(ax, LABEL_R - 0.005, Y_T1, "Tier 1\n(200 Hz)")
    _layer_label(ax, LABEL_R - 0.005, Y_HW, "Hardware")

    # ── Main column: four control tiers
    _box(ax, MAIN_L, Y_T3 - BOX_H_MAIN/2, MAIN_R - MAIN_L, BOX_H_MAIN,
          title="Cluster operating-point selector",
          body="Picks IT power target; includes cooling-overhead correction",
          fc=TIER3_FC, ec=TIER3_EC)

    _box(ax, MAIN_L, Y_T2 - BOX_H_MAIN/2, MAIN_R - MAIN_L, BOX_H_MAIN,
          title="Per-host coordinator",
          body="AR(4) predictor; splits host envelope across GPUs",
          fc=TIER2_FC, ec=TIER2_EC)

    _box(ax, MAIN_L, Y_T1 - BOX_H_MAIN/2, MAIN_R - MAIN_L, BOX_H_MAIN,
          title="Per-GPU power-cap loop",
          body="PID tracking the assigned per-GPU power target via NVML",
          fc=TIER1_FC, ec=TIER1_EC)

    _box(ax, MAIN_L, Y_HW - BOX_H_HW/2, MAIN_R - MAIN_L, BOX_H_HW,
          title="GPU silicon  +  facility meter",
          body="Board power settles within ~20 ms;\n"
                "meter reflects it ~90 ms after the trigger",
          fc=HW_FC, ec=HW_EC, body_fs=8.8)

    # ── Right column: grid + safety island
    _box(ax, RIGHT_L, Y_T3 - BOX_H_MAIN/2 - 0.005,
          RIGHT_R - RIGHT_L, BOX_H_MAIN + 0.01,
          title="Electricity grid",
          body="Frequency event\n(TSO trigger)",
          fc=GRID_FC, ec=GRID_EC, body_fs=9.0)

    # Safety island is taller because it carries the bypass narrative
    _box(ax, RIGHT_L, Y_T1 - 0.08, RIGHT_R - RIGHT_L, 0.22,
          title="Safety island",
          body="Real-time C bypass.\n"
                "Reads the grid trigger and writes\n"
                "the GPU cap directly --- skipping\n"
                "the slower software path.",
          fc=SAFE_FC, ec=SAFE_EC, body_fs=8.8)

    # ── Inter-tier arrows (left column) ──────────────────────────
    # Each arrow goes from the bottom of the upper box to the top of
    # the lower box, with breathing room around the label.
    def _vert_arrow(y_upper, y_lower, label=None):
        y1 = y_upper - BOX_H_MAIN/2          # bottom of upper box
        y2 = y_lower + BOX_H_MAIN/2          # top of lower box
        _arrow(ax, (MAIN_L + MAIN_R)/2, y1,
                    (MAIN_L + MAIN_R)/2, y2, label=label)

    _vert_arrow(Y_T3, Y_T2)
    _vert_arrow(Y_T2, Y_T1)
    # Bottom hardware uses BOX_H_HW; handle separately
    _arrow(ax, (MAIN_L + MAIN_R)/2, Y_T1 - BOX_H_MAIN/2,
                (MAIN_L + MAIN_R)/2, Y_HW + BOX_H_HW/2)

    # ── Grid -> Safety island
    _arrow(ax, (RIGHT_L + RIGHT_R)/2, Y_T3 - BOX_H_MAIN/2 - 0.005,
                (RIGHT_L + RIGHT_R)/2, Y_T1 + 0.14,
                color=ARROW_BYPASS, lw=1.6,
                label="UDP trigger")

    # ── Safety island -> Hardware (DOWN + LEFT hook)
    # First go straight down to just above the hardware box top,
    # then a horizontal segment into the hardware box.
    _arrow(ax, (RIGHT_L + RIGHT_R)/2, Y_T1 - 0.08,
                (RIGHT_L + RIGHT_R)/2, Y_HW + BOX_H_HW/2 + 0.02,
                color=ARROW_BYPASS, lw=1.6,
                label="~97 ms median")
    _arrow(ax, (RIGHT_L + RIGHT_R)/2, Y_HW + BOX_H_HW/2 + 0.02,
                MAIN_R + 0.005, Y_HW + BOX_H_HW/2 + 0.02,
                color=ARROW_BYPASS, lw=1.6)

    # ── Headline callout band (very bottom) ──────────────────────
    cb_y, cb_h = 0.02, 0.07
    p = FancyBboxPatch((LABEL_R - 0.06, cb_y),
                        RIGHT_R - LABEL_R + 0.06, cb_h,
                        boxstyle="round,pad=0.004,rounding_size=0.010",
                        fc=CALLOUT_FC, ec=CALLOUT_EC, lw=1.0)
    ax.add_patch(p)
    ax.text(0.5, cb_y + cb_h/2,
             "Measured end-to-end response: 97 ms median  ·  101 ms worst case (90 trials)  "
             "·  about 7× faster than the Nordic Fast Frequency Reserve 700 ms budget.",
             ha="center", va="center",
             fontsize=9.5, fontstyle="italic", fontweight="bold",
             color=CALLOUT_EC)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_gridpilot_architecture] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
