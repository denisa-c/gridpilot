"""
experiments_v2/src/figure_style.py
====================================
Single source of truth for figure styling across every v2 render
script (06, 07, 08, 09).  Importing this module sets the global
``plt.rcParams``.

Conventions
-----------
* Country colour ramp goes clean -> dirty across all six grids; the
  ramp is consistent in every figure so the reader's eye-mapping
  carries over.  SE = purple, PL = brown matches the
  ``fig_country_cfe_lift_v2`` reference colour palette.
* Body font: serif, 12 pt; titles 13 pt.  Smaller than LNCS body to
  leave headroom for ``\\includegraphics[width=\\linewidth]{...}``
  upscaling without losing legibility.
* Axes: top + right spines hidden; gridlines dashed, low-alpha so
  they don't compete with data.
* Error bars: 1 SEM (standard error of the mean over seeds), cap
  size 3, line width 0.9.  Matches PCAPS / CarbonScaler convention.
* Legends: outside the plot area whenever a panel is bar-heavy
  (Figure 1, headline); inside on a low-density corner when scatter
  / lines leave clear space (Pareto, country-vs-CI).
"""
from __future__ import annotations

import matplotlib.pyplot as plt


# ── Country palette (consistent across every v2 figure) ──────────────
COUNTRY_ORDER = ["SE", "CH", "FR", "IT", "DE", "PL"]
COUNTRY_COLORS = {
    "SE": "#5e3a87",   # deep purple - cleanest grid
    "CH": "#1f77b4",   # blue
    "FR": "#17becf",   # cyan
    "IT": "#ff8c1a",   # orange (between green and red on the CI ramp)
    "DE": "#d62728",   # red
    "PL": "#8c4a2d",   # brown - dirtiest grid
}
# Annual mean CI (g CO2eq/kWh) for x-axis annotation; updated to
# 2025 IPCC AR5 lifecycle factors over ENTSO-E A75 generation mix.
# These match the values reported in the methodology section.
COUNTRY_CI_2025 = {
    "SE": 12, "CH": 33, "FR": 58, "IT": 288, "DE": 328, "PL": 681,
}

# ── Season palette (used by 07 and the per-season small-multiples) ─
SEASONS = ["Winter", "Spring", "Summer", "Autumn"]
SEASON_COLORS = {
    "Winter": "#4a90d9",
    "Spring": "#5cb85c",
    "Summer": "#f0ad4e",
    "Autumn": "#d9534f",
}

# ── Workload-class / tier palette ─────────────────────────────────
# The saturated text-fill palette from the "Mapped Workload Class"
# card (Table 1 / ladder graphic in Sect. 2): T0 red, T1 orange,
# T2 green, T3 teal-blue, T4 deep teal, T5 dark green.  Used directly
# as the bar / wedge fill colour (no pastel anywhere); the matching
# pastel tints are kept for legacy code that still wants a backdrop.
TIER_TEXT_COLORS = {
    0: "#BC3D3D",   # T0 rigid           — red
    1: "#C26500",   # T1 hour            — orange
    2: "#1E90FF",   # T2 day             — vivid sky blue  (elastic AI)
    3: "#2470A0",   # T3 week            — teal-blue       (batch parallel)
    4: "#1F6B6B",   # T4 elastic burst   — deep teal
    5: "#1E3A8A",   # T5 spatial         — navy blue       (geo-shiftable)
}
TIER_COLORS = TIER_TEXT_COLORS   # alias: the figure palette is the
                                  # saturated palette (no pastels).

# Each class inherits the colour of its primary tier on the ladder.
# Interactive and large_hpc are both T0 -> identical red fill; the
# CLASS_HATCH map below differentiates them with a diagonal hatch on
# large_hpc.  geo_shiftable and elastic_ai are both greens (T5 vs T2)
# and could be confused at a glance -- geo_shiftable also carries a
# hatch so the eye can separate them.
CLASS_COLORS = {
    "interactive":      TIER_TEXT_COLORS[0],   # T0 rigid          — red
    "workflow_coupled": TIER_TEXT_COLORS[1],   # T1 hour           — orange
    "elastic_ai":       TIER_TEXT_COLORS[2],   # T2 day            — green
    "batch_parallel":   TIER_TEXT_COLORS[3],   # T3 week           — teal-blue
    "geo_shiftable":    TIER_TEXT_COLORS[5],   # T5 spatial        — dark green
    "large_hpc":        TIER_TEXT_COLORS[0],   # T0 rigid          — red (hatched)
}
# Hatching pattern per class.  Empty string = solid fill.  Hatch lines
# are drawn in the patch's edge colour (typically white) so the pattern
# reads as light stripes / dots over the saturated background.
# Three blues live on the ladder now (T2 sky, T3 teal, T5 navy), so
# both batch_parallel and geo_shiftable carry hatching to separate
# them from elastic_ai's vivid sky blue at a glance; large_hpc shares
# T0 red with interactive and stays diagonal-hatched.
CLASS_HATCH = {
    "interactive":      "",
    "workflow_coupled": "",
    "elastic_ai":       "",
    "batch_parallel":   "xxx",   # cross-hatch -- T3 teal vs T2 sky
    "geo_shiftable":    "...",   # dots        -- T5 navy vs T3 teal
    "large_hpc":        "///",   # diagonal    -- shares T0 red with interactive
}
CLASS_DISPLAY = {
    "interactive":      "interactive",
    "workflow_coupled": "workflow",
    "elastic_ai":       "elastic AI",
    "batch_parallel":   "batch parallel",
    "geo_shiftable":    "geo-shiftable",
    "large_hpc":        "large HPC",
}
# Tier tags shown alongside class names (small text under the bar,
# legend annotation) so the colour-coding is explicit, not coded.
CLASS_TIER_TAG = {
    "interactive":      "T0",
    "workflow_coupled": "T1",
    "elastic_ai":       "T2",
    "batch_parallel":   "T3",
    "geo_shiftable":    "T5",
    "large_hpc":        "T0",
}
PAPER_REFERENCE_PCT = {
    "interactive":      4.0,
    "workflow_coupled": 15.0,
    "elastic_ai":       43.0,
    "batch_parallel":   15.0,
    "geo_shiftable":    10.0,
    "large_hpc":        13.0,
}

# ── LNCS-ready figure dimensions (inches) ─────────────────────────
W_SINGLE_COL = 4.8     # one column on a two-column layout
W_TEXT       = 6.5     # full text width on LNCS single-column body
W_DOUBLE_COL = 9.6     # spans two columns

# ── Accounting constants (kept here so figure scripts don't need ──
# to import the heavy schedulers package just for one number).
PUE_HEADLINE          = 1.20
P_NODE_KW             = 1.5
ANNUAL_HOURS          = 8760.0


def apply_rcparams() -> None:
    """Install the v2 figure-wide rcParams (idempotent).

    Call once at the top of every render script before constructing
    any figure.  Sets serif fonts, Type-42 PDF embedding (camera-
    ready safe), and removes the top / right spines for the clean
    look the screenshots in the PECS review request showed.
    """
    plt.rcParams.update({
        "pdf.fonttype": 42, "ps.fonttype": 42,
        "font.family": "serif",
        "font.size":         12,
        "axes.titlesize":    13,
        "axes.labelsize":    12,
        "xtick.labelsize":   11,
        "ytick.labelsize":   11,
        "legend.fontsize":   10,
        "axes.spines.top":   False,
        "axes.spines.right": False,
        "axes.grid":         True,
        "grid.alpha":        0.25,
        "grid.linestyle":    "--",
        "grid.linewidth":    0.5,
        "axes.linewidth":    0.8,
        "lines.linewidth":   1.8,
        "lines.markersize":  7,
        "errorbar.capsize":  3,
        # Thicker hatch strokes so the white diagonal / dot patterns
        # over saturated tier fills read clearly even at small bar
        # widths in the per-class breakdown figure.
        "hatch.linewidth":   1.2,
    })
