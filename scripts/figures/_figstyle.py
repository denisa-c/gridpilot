"""
scripts/figures/_figstyle.py
============================
Shared matplotlib rcParams for every paper figure.

Single source of truth for:
  * font sizes (1.5x of the previous baseline so figures stay
    legible when shrunk to a 0.7-linewidth single-column include)
  * TrueType embedding for camera-ready submission
  * tight bbox + small pad
  * a consistent print-safe colour palette

Import as:
    from _figstyle import apply_style, PAPER_PALETTE
    apply_style()
"""
from __future__ import annotations

import matplotlib as mpl


def apply_style() -> None:
    """Apply the paper-wide rcParams.  Call once at module top."""
    mpl.rcParams.update({
        "font.family":      "sans-serif",
        "font.sans-serif":  ["Helvetica", "Arial", "DejaVu Sans"],
        # 1.5x scaling from the previous 9 / 9.5 / 8.0 / 8.0 / 8.0 baseline,
        # so the figure remains legible when included at 0.7 linewidth.
        "font.size":        13.0,
        "axes.labelsize":   13.0,
        "axes.titlesize":   14.0,
        "xtick.labelsize":  12.0,
        "ytick.labelsize":  12.0,
        "legend.fontsize":  12.0,
        # Other quality knobs.
        "axes.linewidth":   0.9,
        "axes.spines.top":  False,
        "axes.spines.right": False,
        "axes.grid":        True,
        "grid.alpha":       0.25,
        "grid.linewidth":   0.6,
        "pdf.fonttype":     42,
        "ps.fonttype":      42,
        "savefig.bbox":     "tight",
        "savefig.pad_inches": 0.06,
    })


# Print-safe palette used across the paper figures.
PAPER_PALETTE = {
    # mechanism family (distinct hues, light -> dark = none -> M3)
    "M_none": "#bdbdbd",
    "M0":     "#4a90e2",
    "M1":     "#3a7d44",
    "M2":     "#e07a2e",
    "M3":     "#a83232",
    # country diverging ramp (clean -> dirty)
    "SE":     "#1a7c3a",
    "CH":     "#54a564",
    "FR":     "#92c98e",
    "IT":     "#f3a93f",
    "DE":     "#e07a2e",
    "PL":     "#922e29",
}
