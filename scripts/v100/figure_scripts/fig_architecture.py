"""GridPilot end-to-end architecture, v3 with safety-island domain.

Design: 5 horizontal layers, 3 main columns aligned across layers so that
control-flow arrows are strictly vertical and never cross box content.
Inputs row uses 5 cells; the cluster, host, and Tier-1 rows use 3 cells in
the same horizontal positions; the Domain-1 row uses 4 cells in its own
visually-distinct frame.

The 4 cluster boxes (Pillar 6, Pillar 5, Pillar 1, PUE Model) are merged
into 3 boxes for layer alignment: the PUE Model becomes a side-callout to
the right rather than an aligned column.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 11,
    "axes.titlesize": 16,
    "savefig.dpi": 300,
})

COLOR_GRID    = "#fff3cd"
COLOR_CLUSTER = "#d1ecf1"
COLOR_HOST    = "#d4edda"
COLOR_GPU     = "#f8d7da"
COLOR_DOMAIN1 = "#e7d4f5"
COLOR_BORDER  = "#34495e"
COLOR_ARROW   = "#2c3e50"
COLOR_DOMAIN_BORDER = "#5e2ca5"
COLOR_TXT     = "#212121"


# ---- Canvas ----
fig, ax = plt.subplots(figsize=(15, 12))
ax.set_xlim(0, 15)
ax.set_ylim(0, 13)
ax.axis("off")


def box(x, y, w, h, color, title, body_lines, fontsize=10, title_size=11):
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.05,rounding_size=0.12",
        edgecolor=COLOR_BORDER, facecolor=color, linewidth=1.4,
    )
    ax.add_patch(rect)
    ax.text(x + w/2, y + h - 0.22, title,
            ha="center", va="top", fontsize=title_size,
            fontweight="bold", color=COLOR_TXT)
    body_text = "\n".join(body_lines)
    ax.text(x + w/2, y + h - 0.55, body_text,
            ha="center", va="top", fontsize=fontsize, color=COLOR_TXT)


def vert_arrow(x, y_top, y_bot, label="", label_offset_x=0.18,
                color=None, style="-"):
    c = color or COLOR_ARROW
    arr = FancyArrowPatch(
        (x, y_top), (x, y_bot),
        arrowstyle="->,head_length=8,head_width=5",
        linewidth=1.4, color=c, linestyle=style,
        mutation_scale=15,
    )
    ax.add_patch(arr)
    if label:
        ax.text(x + label_offset_x, (y_top + y_bot)/2, label,
                fontsize=8.5, ha="left", va="center",
                color=c, style="italic",
                bbox=dict(boxstyle="round,pad=0.15", fc="white",
                          ec="none", alpha=0.92))


def vert_arrow_up(x, y_bot, y_top, label="", label_offset_x=0.18,
                   color=None):
    c = color or COLOR_ARROW
    arr = FancyArrowPatch(
        (x, y_bot), (x, y_top),
        arrowstyle="->,head_length=8,head_width=5",
        linewidth=1.4, color=c,
        mutation_scale=15,
    )
    ax.add_patch(arr)
    if label:
        ax.text(x + label_offset_x, (y_top + y_bot)/2, label,
                fontsize=8.5, ha="left", va="center",
                color=c, style="italic",
                bbox=dict(boxstyle="round,pad=0.15", fc="white",
                          ec="none", alpha=0.92))


def band_label(y_centre, text, color="#7f8c8d"):
    ax.text(0.4, y_centre, text,
            ha="center", va="center", fontsize=11, fontweight="bold",
            color=color, rotation=90)


# ============================================================================
# Title
# ============================================================================
ax.text(7.5, 12.45, "GridPilot End-to-End Architecture",
        ha="center", va="bottom", fontsize=20, fontweight="bold")
ax.text(7.5, 12.0,
        "Domain 2 (Python supervisor) | Domain 1 (certified C safety island, IEC 61508 SIL-2 / IEC 61131-3 / MISRA-C 2012)",
        ha="center", va="bottom", fontsize=11, style="italic", color="#555")

# ============================================================================
# THREE MAIN COLUMNS used by Tier-3, Tier-2, Tier-1 (so arrows are vertical)
# Each column is 4.0 wide
# ============================================================================
COL1_X = 0.9    # left column
COL2_X = 5.3    # centre column
COL3_X = 9.7    # right column
COL_W  = 4.1
# Centre points used for vertical arrows
COL1_C = COL1_X + COL_W/2  #  2.95
COL2_C = COL2_X + COL_W/2  #  7.35
COL3_C = COL3_X + COL_W/2  # 11.75

# ============================================================================
# LAYER 1 — INPUTS ROW (y = 9.7 to 11.0)
# ============================================================================
y1, h1 = 9.7, 1.3
band_label(y1 + h1/2, "INPUTS\nhour–day")

# 5 input boxes spread across the canvas; arrows feed Tier-3 columns
in_xs = [0.9, 3.6, 6.3, 9.0, 11.7]
in_w = 2.6
in_titles = ["ENTSO-E API", "Country Configs", "Workload Traces",
             "Grid CI signals", "Weather & Tamb"]
in_bodies = [
    ["Transparency platform", "A37/A88/A89 endpoints", "25 EU members"],
    ["YAML-loaded", "CH IT DE FR ES …", "service taxonomy + CI"],
    ["M100 (1,994 jobs)", "Philly-like (8k DL)", "Acme-like (3k LLM)"],
    ["EEA / Ember / IEA", "2025–2032 horizon", "hourly resolution"],
    ["Bologna ref. site", "PUE inputs", "free-cooling fraction"],
]
for x, t, b in zip(in_xs, in_titles, in_bodies):
    box(x, y1, in_w, h1, COLOR_GRID, t, b, 9)

# ============================================================================
# LAYER 2 — TIER 3 (cluster) — 3 main boxes + side PUE callout
# ============================================================================
y2, h2 = 7.7, 1.3
band_label(y2 + h2/2, "TIER 3\n0.001 Hz")

box(COL1_X, y2, COL_W, h2, COLOR_CLUSTER, "Cluster Optimiser (Pillar 6)",
    ["service-stacked grid search",
     "(mean_op_frac, ffr_band_frac)",
     "obj = 0.55·FFR + 0.45·CFE"], 9)
box(COL2_X, y2, COL_W, h2, COLOR_CLUSTER, "GridPilot-PUE Scheduler (Pillar 5)",
    ["EASY backfill + dynamic capping",
     "hybrid elasticity + budget aging",
     "σ(t) = CI(t) · PUE(t,L,Tamb)"], 9)
box(COL3_X, y2, COL_W, h2, COLOR_CLUSTER, "Mechanism Layer (Pillar 1)",
    ["Bayesian persuasion",
     "incentive-compatible elicitation",
     "70% truth threshold"], 9)

# Inst. PUE Model side callout (right-aligned, narrow)
pue_x, pue_w = 14.0, 0.95
ax.text(14.5, y2 + h2/2,
        "PUE\nmodel\n(Sun '20\n+ Zhao '24)",
        ha="center", va="center", fontsize=8.5, color="#555",
        bbox=dict(boxstyle="round,pad=0.3", fc="#fff", ec="#888",
                   linewidth=1.0, alpha=0.9))

# ============================================================================
# LAYER 3 — TIER 2 (host) — 3 boxes aligned with Tier-3 columns
# ============================================================================
y3, h3 = 5.85, 1.2
band_label(y3 + h3/2, "TIER 2\n1 Hz")

box(COL1_X, y3, COL_W, h3, COLOR_HOST, "Host Coordinator",
    ["AR(4) predictor (30 s window)",
     "online RLS refit",
     "MAE 0.04, p95 0.10"], 9)
box(COL2_X, y3, COL_W, h3, COLOR_HOST, "Service-Stack Participation (Pillar 7)",
    ["FCR / aFRR / mFRR / RR",
     "min-bid enforcement",
     "weighted exo-CI accounting"], 9)
box(COL3_X, y3, COL_W, h3, COLOR_HOST, "Cohort Study Bridge (Pillar 8)",
    ["GDPR-compliant data pipe",
     "user-declared flexibility tags",
     "30–50 PI groups, M30 + M60 release"], 9)

# ============================================================================
# LAYER 4 — TIER 1 (GPU/CPU) — 3 boxes aligned
# ============================================================================
y4, h4 = 4.0, 1.2
band_label(y4 + h4/2, "TIER 1\n200 Hz")

box(COL1_X, y4, COL_W, h4, COLOR_GPU, "GPU DVFS Inner Loop",
    ["PID Kp=0.6 Ki=0.05 Kd=0.02",
     "MF-GPOEO Wang '24",
     "NVML 5 ms, T_GPU < 85 °C"], 9)
box(COL2_X, y4, COL_W, h4, COLOR_GPU, "CPU c-state Nudges",
    ["Linux cpuidle interface",
     "per-host envelope alloc.",
     "RAPL-bounded"], 9)
box(COL3_X, y4, COL_W, h4, COLOR_GPU, "Hardware Under Control",
    ["3 × NVIDIA V100 SXM2 (testbed)",
     "2 × H200 PCIe (proposal)",
     "AMD EPYC / Intel Xeon host"], 9)

# ============================================================================
# DOMAIN BOUNDARY (between Tier-1 and Domain-1)
# Place at y = 3.6
# ============================================================================
y_bnd = 3.6
ax.plot([0.9, 13.85], [y_bnd, y_bnd], linestyle=":", linewidth=1.4,
        color=COLOR_DOMAIN_BORDER)
ax.text(7.5, y_bnd + 0.07, "── DOMAIN BOUNDARY ──",
        ha="center", va="bottom", fontsize=9, fontweight="bold",
        color=COLOR_DOMAIN_BORDER, style="italic")

# ============================================================================
# LAYER 5 — DOMAIN 1 (safety island)  (y = 1.4 to 3.0)
# ============================================================================
y5, h5 = 1.4, 1.5
band_label(y5 + h5/2, "DOMAIN 1\nC + WCET", color=COLOR_DOMAIN_BORDER)

# Outer dashed frame
bg = FancyBboxPatch(
    (0.85, y5 - 0.1), 13.05, h5 + 0.55,
    boxstyle="round,pad=0.05,rounding_size=0.18",
    edgecolor=COLOR_DOMAIN_BORDER, facecolor="#f8f3fc", linewidth=2.0,
    linestyle="--",
)
ax.add_patch(bg)
ax.text(7.45, y5 + h5 + 0.20,
        "Safety Island (Pillar 9 / WP3.5) — IEC 61508 SIL-2 target / Statnett FFR pre-qualification",
        ha="center", va="bottom", fontsize=11, fontweight="bold",
        color=COLOR_DOMAIN_BORDER, style="italic")

# 4 columns inside the safety-island row
si_xs = [1.05, 4.30, 7.55, 10.80]
si_w  = 3.1
si_titles = ["Frequency Front-End", "Threshold + Lookup",
             "Actuation Backend", "Protocol Stack"]
si_bodies = [
    ["IEC 61850-9-2 SV", "1 kHz sampling", "hardware time ref."],
    ["constant-time comparator", "CRC-validated table", "FPV-verified"],
    ["NVML (V100 reference)", "Redfish (certified)", "WCET 50 ms / GPU"],
    ["Modbus TCP / OPC UA", "CRC-32, sequence", "TLA+ specified"],
]
for x, t, b in zip(si_xs, si_titles, si_bodies):
    box(x, y5, si_w, h5, COLOR_DOMAIN1, t, b, 9)

# ============================================================================
# Vertical control-flow arrows — strictly vertical within columns
# ============================================================================

# Layer 1 -> Layer 2: each input feeds the cluster layer below it.
# Use slim grey arrows for data flow (dashed).
input_arrow_targets = [COL1_C, COL1_C, COL2_C, COL3_C, COL3_C]
for x_in, w_in, x_target in zip(in_xs, [in_w]*5, input_arrow_targets):
    src_x = x_in + w_in/2
    arr = FancyArrowPatch(
        (src_x, y1), (x_target, y2 + h2),
        arrowstyle="->,head_length=6,head_width=4",
        linewidth=1.0, color="#7f8c8d", linestyle="--",
        mutation_scale=12, alpha=0.7,
    )
    ax.add_patch(arr)

# Layer 2 -> Layer 3 — strictly vertical
vert_arrow(COL1_C, y2, y3 + h3, "op-point")
vert_arrow(COL2_C, y2, y3 + h3, "dispatch")
vert_arrow(COL3_C, y2, y3 + h3, "user signals")

# Layer 3 -> Layer 4 — strictly vertical
vert_arrow(COL1_C, y3, y4 + h4, "GPU caps")
vert_arrow(COL2_C, y3, y4 + h4, "c-state hints")
vert_arrow(COL3_C, y3, y4 + h4, "telemetry")

# Layer 4 -> Domain 1 — supervisor pushes lookup-table (left col),
# Domain 1 reports activation (right col)
# Use distinct purple colour to mark the boundary
# Lookup-table push: from GPU DVFS (left col) down to Frequency Front-End col
src_x = COL1_C
dst_x = si_xs[0] + si_w/2  # Front-End column
arr = FancyArrowPatch(
    (src_x, y4), (dst_x, y5 + h5 + 0.35),
    arrowstyle="->,head_length=8,head_width=5",
    linewidth=1.4, color=COLOR_DOMAIN_BORDER,
    mutation_scale=15,
)
ax.add_patch(arr)
ax.text((src_x + dst_x)/2 + 0.1, (y4 + y5 + h5 + 0.35)/2 + 0.05,
        "lookup-table push\n(bid window opens)",
        fontsize=8.5, ha="left", va="center",
        color=COLOR_DOMAIN_BORDER, style="italic",
        bbox=dict(boxstyle="round,pad=0.2", fc="white",
                  ec="none", alpha=0.92))

# Activation event: from Protocol Stack column up to Hardware Under Control
src_x_act = si_xs[3] + si_w/2
dst_x_act = COL3_C
arr = FancyArrowPatch(
    (src_x_act, y5 + h5 + 0.35), (dst_x_act, y4),
    arrowstyle="->,head_length=8,head_width=5",
    linewidth=1.4, color=COLOR_DOMAIN_BORDER,
    mutation_scale=15,
)
ax.add_patch(arr)
ax.text((src_x_act + dst_x_act)/2 - 0.1, (y4 + y5 + h5 + 0.35)/2 + 0.05,
        "activation event\n(WCET ≤ 700 ms)",
        fontsize=8.5, ha="right", va="center",
        color=COLOR_DOMAIN_BORDER, style="italic",
        bbox=dict(boxstyle="round,pad=0.2", fc="white",
                  ec="none", alpha=0.92))

# ============================================================================
# Legend strip (y = 0.3)
# ============================================================================
y_leg = 0.3
legend_items = [
    (COLOR_GRID,    "Grid layer"),
    (COLOR_CLUSTER, "Tier-3 cluster"),
    (COLOR_HOST,    "Tier-2 host"),
    (COLOR_GPU,     "Tier-1 GPU/CPU"),
    (COLOR_DOMAIN1, "Domain 1 — safety-certified"),
]
x_leg = 0.9
for col, label in legend_items:
    rect = patches.Rectangle((x_leg, y_leg), 0.4, 0.32,
                              facecolor=col, edgecolor=COLOR_BORDER, linewidth=1.0)
    ax.add_patch(rect)
    ax.text(x_leg + 0.5, y_leg + 0.16, label,
            ha="left", va="center", fontsize=10)
    x_leg += 2.7

# Save
fig.savefig(OUT / "fig_architecture.pdf", bbox_inches="tight", pad_inches=0.15)
fig.savefig(OUT / "fig_architecture.png", bbox_inches="tight", dpi=200)
plt.close()
print("✓ fig_architecture.pdf and .png written (v3)")
