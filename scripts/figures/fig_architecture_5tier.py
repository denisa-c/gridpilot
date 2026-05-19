#!/usr/bin/env python3
"""
scripts/figures/fig_architecture_5tier.py
=========================================
Renders the f-SLA architecture diagram with **five** tiers
(T0 rigid / T1 hour / T2 day / T3 week / T4 elastic burst).
This is a redraw of the legacy hand-drawn
papers/pecs2026/figs/architecture-custom.pdf (which only depicts
the original four-tier ladder, pre-T4 elastic-burst) so it stays in
sync with the paper body.  T5 (spatial routing) is the C2 follow-on
and is not drawn here; the PECS body caption notes the omission.

Output: papers/pecs2026/figs/architecture-5tier.pdf
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.transforms import blended_transform_factory  # noqa: F401

# -- Geometry ----------------------------------------------------------
W, H = 12.0, 7.0     # figure size, inches
BOX_RX = 0.04        # rounding pad for FancyBboxPatch
LANE_H = 1.05        # height of each horizontal "lane"

# -- Style -------------------------------------------------------------
LANE_BG = {
    "user":      ("#E8F0FB", "#1f4e8c"),  # fill, edge
    "ai":        ("#FFF2DC", "#b46500"),
    "accounting":("#E5F3E6", "#1f7a37"),
    "scheduler": ("#FDE7E1", "#a83a1f"),
    "grid":      ("#EAE2F5", "#5a3a8a"),
}
TIER_FILL = {
    "T0": "#cdd9ea",
    "T1": "#9bb4d7",
    "T2": "#6589c1",
    "T3": "#345fa8",
    "T4": "#1f3f7e",
}
ARROW_KW = dict(
    arrowstyle="-|>,head_width=4,head_length=6",
    mutation_scale=12, linewidth=1.4, color="#2e2e2e",
)

# -- Render ------------------------------------------------------------

def _box(ax, x, y, w, h, *, fc, ec, lw=1.6, alpha=1.0):
    p = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.02,rounding_size={BOX_RX}",
        linewidth=lw, edgecolor=ec, facecolor=fc, alpha=alpha,
    )
    ax.add_patch(p)


def _txt(ax, x, y, s, *, size=11, weight="normal", color="#101010", ha="center", va="center"):
    ax.text(x, y, s, ha=ha, va=va, fontsize=size,
            fontweight=weight, color=color, zorder=5)


def _arrow(ax, x1, y1, x2, y2, label=None, lab_dx=0, lab_dy=0.18, color=None):
    kw = dict(ARROW_KW)
    if color is not None:
        kw["color"] = color
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), **kw))
    if label:
        ax.text((x1 + x2) / 2 + lab_dx, (y1 + y2) / 2 + lab_dy, label,
                ha="center", va="center", fontsize=9, color="#404040")


def render(outpath: Path) -> None:
    fig, ax = plt.subplots(figsize=(W, H), constrained_layout=True)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8.2)
    ax.set_aspect("equal")
    ax.axis("off")

    # --- Lane 1: user submission + tier ladder (top-left) ---
    fc, ec = LANE_BG["user"]
    _box(ax, 0.4, 6.5, 7.4, 1.5, fc=fc, ec=ec)
    _txt(ax, 1.6, 7.7, "User submits a job", size=12, weight="bold", color=ec)
    _txt(ax, 4.1, 7.25, "Chooses a tier on a 5-step ladder", size=9.8, color=ec)
    # tier tiles
    tiers = [
        ("T0", "rigid"),
        ("T1", "hour"),
        ("T2", "day"),
        ("T3", "week"),
        ("T4", "elastic\nburst"),
    ]
    tile_w, tile_h, tile_gap = 0.95, 0.78, 0.10
    x0 = 2.65
    for i, (name, sub) in enumerate(tiers):
        x = x0 + i * (tile_w + tile_gap)
        _box(ax, x, 6.65, tile_w, tile_h,
             fc=TIER_FILL[name], ec=ec, lw=1.2)
        _txt(ax, x + tile_w / 2, 6.65 + tile_h - 0.22, name,
             size=10, weight="bold", color="white")
        _txt(ax, x + tile_w / 2, 6.65 + 0.20, sub,
             size=8.2, color="white")

    # --- Lane 1b: AI baseline (top-right) ---
    fc, ec = LANE_BG["ai"]
    _box(ax, 8.6, 6.5, 5.0, 1.5, fc=fc, ec=ec)
    _txt(ax, 11.1, 7.7, "AI baseline", size=12, weight="bold", color=ec)
    _txt(ax, 11.1, 7.32, "Shows the user the tier the AI expects",
         size=9.6, color=ec)
    _txt(ax, 11.1, 6.95, "Beat the AI to earn credit + rank",
         size=9.6, color=ec)

    # dashed arrow AI -> user (prediction)
    ax.add_patch(FancyArrowPatch(
        (8.6, 7.45), (7.8, 7.45),
        arrowstyle="-|>,head_width=4,head_length=6",
        linewidth=1.2, linestyle=(0, (4, 2)), color="#7a4a00", mutation_scale=12,
    ))
    _txt(ax, 8.2, 7.78, "AI prediction shown to user",
         size=8.5, color="#7a4a00")

    # --- Lane 2: accounting layer ---
    fc, ec = LANE_BG["accounting"]
    _box(ax, 0.4, 4.55, 13.2, 1.3, fc=fc, ec=ec)
    _txt(ax, 2.3, 5.55, "f-SLA accounting layer",
         size=12, weight="bold", color=ec)
    _txt(ax, 7.5, 5.20, "Per-user credit ledger  •  leaderboard  •  log of (AI predicted, user declared, realised)",
         size=9.6, color=ec)
    _txt(ax, 7.5, 4.85, "This log becomes the dataset that replaces the synthetic prior",
         size=9.0, color=ec)

    # arrows user/AI -> accounting
    _arrow(ax, 3.9, 6.5, 3.9, 5.85, label="declared tier",
           lab_dx=-1.05, lab_dy=0.05)
    _arrow(ax, 11.1, 6.5, 11.1, 5.85, label="AI predicted tier",
           lab_dx=1.05, lab_dy=0.05)

    # --- Lane 3: scheduler ---
    fc, ec = LANE_BG["scheduler"]
    _box(ax, 0.4, 2.6, 13.2, 1.4, fc=fc, ec=ec)
    _txt(ax, 2.45, 3.78, "Carbon-aware scheduler",
         size=12, weight="bold", color=ec)
    _txt(ax, 7.5, 3.35, "Defers each job within the declared window to a low-CI hour",
         size=9.6, color=ec)
    _txt(ax, 7.5, 2.97, "T4: also scales replicas $0.5\\times$–$2\\times$ on the CI signal at constant makespan",
         size=9.0, color=ec)

    # arrow accounting -> scheduler
    _arrow(ax, 7.0, 4.55, 7.0, 4.0, label="tiered jobs (incl. T4 elastic)",
           lab_dx=0, lab_dy=0.0, color="#1f7a37")

    # --- Lane 4: electricity grid ---
    fc, ec = LANE_BG["grid"]
    _box(ax, 0.4, 0.55, 13.2, 1.55, fc=fc, ec=ec)
    _txt(ax, 2.1, 1.85, "Electricity grid",
         size=12, weight="bold", color=ec)
    _txt(ax, 7.5, 1.45, "Multi-country evaluation: SE, CH, FR, IT, DE, PL",
         size=9.6, color=ec)
    _txt(ax, 7.5, 1.08, "Data centre: 1 / 10 / 50 MW   ·   real ENTSO-E hourly CI when API token present",
         size=9.0, color=ec)

    # arrow scheduler -> grid
    _arrow(ax, 7.0, 2.6, 7.0, 2.1, label="dispatch (PUE-aware)",
           lab_dx=0, lab_dy=0.0, color="#a83a1f")

    fig.savefig(outpath, format="pdf", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    here = Path(__file__).resolve()
    repo = here.parents[3]                  # .../EuroPar2026-GridPilot-Denisa
    out = repo / "papers/pecs2026/figs/architecture-5tier.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    render(out)
    print(f"wrote {out}")
