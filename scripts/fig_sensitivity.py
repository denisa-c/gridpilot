"""Generate Figure 5: Plackett-Burman 5-factor sensitivity tornado.

Print-friendly fixes vs. previous version:
  - Title and subtitle clearly separated (no more overlap).
  - Larger margin between title block and plot area.
  - Bar labels are positioned outside the bar tip, not overlapping it.
  - Single envelope shading band, clearly labelled.
  - Legend positioned outside the plot to the right, no clipping.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "serif", "font.size": 14, "axes.titlesize": 16,
    "axes.labelsize": 16, "xtick.labelsize": 13, "ytick.labelsize": 14,
    "legend.fontsize": 12, "savefig.dpi": 300,
    "axes.spines.top": False, "axes.spines.right": False,
})

# Plackett-Burman 5-factor 8-run main effects on the headline metric
# (50 MW DE 2025 net CO2 reduction). Baseline = 26.2 %.
factors = [
    ("FFR participation rate (DE)",       +5.12, "#e67e22"),
    ("Marginal CI of balancing reserve",  +3.22, "#e67e22"),
    ("Chiller COP slope (1/K)",           -2.07, "#3498db"),
    ("PID derivative gain (Tier-1)",      +0.98, "#e67e22"),
    ("Fan affinity exponent",             +0.62, "#e67e22"),
]
baseline = 26.2

# Sort by absolute magnitude (largest at top) — standard tornado convention
factors_sorted = sorted(factors, key=lambda f: abs(f[1]), reverse=True)
labels = [f[0] for f in factors_sorted]
effects = [f[1] for f in factors_sorted]
colors = [f[2] for f in factors_sorted]
y_positions = np.arange(len(factors_sorted))

# === Figure with explicit axes positioning to control title overlap ===
fig = plt.figure(figsize=(11, 6))
ax = fig.add_axes([0.34, 0.12, 0.62, 0.72])  # left, bottom, width, height

# Envelope band: full ±5 pp range around baseline
xmin = baseline + min(effects) - 1
xmax = baseline + max(effects) + 1
ax.axvspan(xmin, xmax, alpha=0.10, color="grey", label="full envelope")

# Baseline line
ax.axvline(baseline, color="black", linestyle="--", linewidth=1.5,
           label=f"Baseline: {baseline}%")

# Bars
for y, eff, col in zip(y_positions, effects, colors):
    bar_x = baseline if eff > 0 else baseline + eff
    bar_w = abs(eff)
    ax.barh(y, bar_w, left=bar_x, color=col, edgecolor="black",
            linewidth=0.8, height=0.6, zorder=3)

# Bar value labels — placed OUTSIDE the bar tip, never inside
for y, eff in zip(y_positions, effects):
    if eff > 0:
        x_lbl = baseline + eff + 0.25
        ha = "left"
    else:
        x_lbl = baseline + eff - 0.25
        ha = "right"
    sign = "+" if eff > 0 else ""
    ax.text(x_lbl, y, f"{sign}{eff:.2f} pp",
            va="center", ha=ha, fontsize=12, fontweight="bold",
            color=("#c0392b" if eff > 0 else "#2980b9"))

# Y axis: factor labels on the left
ax.set_yticks(y_positions)
ax.set_yticklabels(labels, fontsize=12)
ax.invert_yaxis()  # largest at top

# X axis
ax.set_xlabel("Net CO₂ reduction at 50 MW DE 2025 (%)", labelpad=8)
ax.set_xlim(19, 34)
ax.set_xticks([20, 22, 24, 26, 28, 30, 32, 34])
ax.grid(True, axis="x", alpha=0.25, zorder=1)

# Envelope text annotation, properly positioned below the bottom bar


# Legend OUTSIDE the plot to the right
ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5),
          frameon=True, framealpha=0.95)

# Title/subtitle: each on its own line, big margin to avoid overlap
fig.text(0.5, 0.94,
         "Sensitivity of headline 26.2 % savings to input parameters",
         ha="center", va="center", fontsize=17, fontweight="bold")
fig.text(0.5, 0.89,
         f"Plackett-Burman 5-factor 8-run design — envelope: {xmin:.0f} – {xmax:.0f} %",
         ha="center", va="center", fontsize=12, style="italic", color="#555")

# Save
fig.savefig(OUT / "fig_sensitivity_tornado.pdf", bbox_inches="tight",
            pad_inches=0.15)
fig.savefig(OUT / "fig_sensitivity_tornado.png", bbox_inches="tight", dpi=180)
plt.close()
print("✓ fig_sensitivity_tornado.pdf and .png written (titles separated, labels outside bars)")
