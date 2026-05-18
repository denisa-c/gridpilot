#!/usr/bin/env python3
"""
scripts/figures/fig_gamification_architecture.py
================================================
matplotlib fallback for ``figs/fig_gamification_architecture.tex``
(the TikZ standalone version).

The TikZ source is the authoritative editable original; this Python
script exists so the demo pipeline can produce the PDF on machines
without the ``standalone`` LaTeX class (the TeX Live 2026 *basic*
install used on macOS does not bundle it).

Both files produce a single-page vector PDF that mirrors §3.1 of
FSLA_GAMIFICATION_VISION.md and maps the four anti-gaming
mechanisms M0--M3 onto the SEANERGYS CMI/AIDAS/DSRM reference
architecture.

Output
------
  figs/fig_gamification_architecture.pdf
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


mpl.rcParams.update({
    "font.family":      "serif",
    "font.serif":       ["Times New Roman", "DejaVu Serif"],
    "font.size":        9.5,
    "pdf.fonttype":     42,
    "ps.fonttype":      42,
    "savefig.bbox":     "tight",
    "savefig.pad_inches": 0.06,
})

USER_BG  = "#dfe9f5"; USER_E  = "#2a5db0"
OP_BG    = "#fbe6c8"; OP_E    = "#b06a16"
LEDG_BG  = "#d5edd5"; LEDG_E  = "#3f8c43"
SCHED_BG = "#f3c9c6"; SCHED_E = "#922e29"
SEAN_BG  = "#e2d8ef"; SEAN_E  = "#5a3e8e"
LINE     = "#444444"
SUBTEXT  = "#222222"


def _box(ax, x, y, w, h, *, fc, ec, text, fs=8.5, lw=0.7, weight="bold"):
    """Rounded-rectangle box with centred text."""
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle="round,pad=0.005,rounding_size=0.012",
                       fc=fc, ec=ec, lw=lw)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
             fontsize=fs, fontweight=weight, color=SUBTEXT)


def _layer_label(ax, y, text):
    ax.text(0.005, y, text, ha="left", va="center",
             fontsize=8.5, fontstyle="italic", color=LINE)


def _arrow(ax, p0, p1, *, label=None, style="-|>",
            ls="solid", color=LINE, lw=0.7, label_xy_offset=(0, 0),
            label_fs=7.5, connectionstyle="arc3,rad=0"):
    ax.add_patch(FancyArrowPatch(
        p0, p1, arrowstyle=style, mutation_scale=10, lw=lw,
        color=color, linestyle=ls, connectionstyle=connectionstyle,
        shrinkA=2, shrinkB=2,
    ))
    if label:
        mx = (p0[0] + p1[0]) / 2 + label_xy_offset[0]
        my = (p0[1] + p1[1]) / 2 + label_xy_offset[1]
        ax.text(mx, my, label, ha="center", va="center",
                 fontsize=label_fs, color=SUBTEXT,
                 bbox=dict(facecolor="white", edgecolor="none",
                            boxstyle="round,pad=0.10", alpha=0.85))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path,
                    default=Path("figs/fig_gamification_architecture.pdf"))
    args = p.parse_args(argv)

    fig, ax = plt.subplots(figsize=(7.0, 5.0))
    ax.set_xlim(0, 1.0); ax.set_ylim(0, 1.0)
    ax.axis("off")

    # ── Layer 1: user/operator front-ends
    _box(ax, 0.10, 0.84, 0.35, 0.13, fc=USER_BG, ec=USER_E,
          text="User-game UI\n(declare honestly, beat the AI baseline)")
    _box(ax, 0.55, 0.84, 0.35, 0.13, fc=OP_BG, ec=OP_E,
          text="Sysadmin-game dashboard\n(tune carbon-CFE-QoS frontier)")

    # ── Layer 2: f-SLA accounting (three sub-boxes inside a frame)
    _box(ax, 0.07, 0.55, 0.86, 0.20, fc="#f4faf4", ec=LEDG_E, text="",
          fs=8.5, lw=0.5)
    _layer_label(ax, 0.65, "f-SLA accounting")
    _box(ax, 0.10, 0.595, 0.24, 0.10, fc=LEDG_BG, ec=LEDG_E,
          text="Per-user\ncredit ledger", fs=8.0, weight="bold")
    _box(ax, 0.385, 0.595, 0.24, 0.10, fc=LEDG_BG, ec=LEDG_E,
          text="Leaderboard\n+ rank", fs=8.0, weight="bold")
    _box(ax, 0.665, 0.595, 0.26, 0.10, fc=LEDG_BG, ec=LEDG_E,
          text="(AI, declared, realised)\nlog", fs=8.0, weight="bold")

    # ── Layer 3: scheduler with M0-M3 plug-ins
    _box(ax, 0.07, 0.27, 0.86, 0.22, fc=SCHED_BG, ec=SCHED_E,
          text="GridPilot-PUE scheduler  (Algorithm 2)\n"
               r"$\sigma(t)=\mathrm{CI}(t)\,\mathrm{PUE}(t,L,T_{\mathrm{amb}})$  ·"
               " EASY-backfill · aging guard · in-flight cap\n"
               "Anti-gaming plug-ins (M0–M3):  Posted Price · BlindTrust · "
               "DAA · AI-Baseline Audit",
          fs=8.2)

    # ── Layer 4: SEANERGYS row
    _box(ax, 0.07, 0.04, 0.86, 0.16, fc="#f6f3fb", ec=SEAN_E, text="",
          fs=8.5, lw=0.5)
    _layer_label(ax, 0.12, "SEANERGYS")
    _box(ax, 0.10, 0.075, 0.24, 0.09, fc=SEAN_BG, ec=SEAN_E,
          text="CMI\n(monitoring infra)", fs=8.0, weight="bold")
    _box(ax, 0.385, 0.075, 0.24, 0.09, fc=SEAN_BG, ec=SEAN_E,
          text="AIDAS\n(AI-baseline source)", fs=8.0, weight="bold")
    _box(ax, 0.665, 0.075, 0.26, 0.09, fc=SEAN_BG, ec=SEAN_E,
          text="DSRM\n(dynamic sched. + RM)", fs=8.0, weight="bold")

    # ── Arrows: user/operator → accounting
    _arrow(ax, (0.27, 0.84), (0.27, 0.695),
            label=r"declared tier $\tau_{\rm decl}$",
            label_xy_offset=(0.0, 0.0))
    _arrow(ax, (0.73, 0.84), (0.73, 0.695),
            label="policy params",
            label_xy_offset=(0.0, 0.0))

    # ── Arrow: accounting → scheduler
    _arrow(ax, (0.50, 0.55), (0.50, 0.49),
            label="tiered jobs + audit penalty",
            label_xy_offset=(0.18, 0.0))

    # ── Arrows: scheduler → SEANERGYS
    _arrow(ax, (0.27, 0.27), (0.22, 0.165),
            label="telemetry",
            label_xy_offset=(-0.08, 0.0))
    _arrow(ax, (0.73, 0.27), (0.78, 0.165),
            label="dispatch",
            label_xy_offset=(0.07, 0.0))

    # ── Feedback arrows (dashed) — AIDAS → user UI, CMI → operator UI
    _arrow(ax, (0.45, 0.165), (0.13, 0.84), ls="dashed",
            connectionstyle="arc3,rad=0.35",
            label=r"AI tier $\tau_{\rm AI}$",
            label_xy_offset=(-0.18, 0.10))
    _arrow(ax, (0.22, 0.165), (0.55, 0.84), ls="dashed",
            connectionstyle="arc3,rad=-0.35",
            label="live carbon-CFE\nfrontier",
            label_xy_offset=(0.04, 0.16),
            label_fs=7.0)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_gamification_architecture] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
