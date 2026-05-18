"""Regenerate Figure 1: Pareto frontier across the 63-cell matrix."""
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
df = pd.read_csv(ROOT / "data" / "results" / "icpp_full_matrix.csv")

plt.rcParams.update({
    "font.family":"serif","font.size":18,"axes.titlesize":22,
    "axes.labelsize":18,"xtick.labelsize":16,"ytick.labelsize":16,
    "legend.fontsize":14,"savefig.dpi":300,
    "axes.spines.top":False,"axes.spines.right":False,
})

# Map the rebranded scheduler labels in the figure
LABEL = {"ProACT-OPT": "GridPilot-OPT", "ProACT-OPT-PUE": "GridPilot-OPT-PUE", "ProACT++": "GridPilot++"}
SCHED = {
    "FCFS":              ("#7f8c8d", "o", "FCFS (baseline)"),
    "Threshold":         ("#e67e22", "s", "Threshold"),
    "ProACT++":          ("#1abc9c", "^", "GridPilot++"),
    "QoS-bounded":       ("#9b59b6", "v", "QoS-bounded"),
    "CarbonScaler":      ("#2ecc71", "D", "CarbonScaler"),
    "ProACT-OPT":        ("#3498db", "P", "GridPilot-OPT"),
    "ProACT-OPT-PUE":    ("#e74c3c", "*", "GridPilot-OPT-PUE"),
}

fig, axes = plt.subplots(1, 4, figsize=(34, 7.5))
panels = [
    ("(a) All workloads (n=63)",       df["workload"].notna()),
    ("(b) M100 (real HPC)",             df["workload"] == "M100"),
    ("(c) Philly (DL training)",        df["workload"] == "Philly"),
    ("(d) Acme (LLM)",                  df["workload"] == "Acme"),
]
for ax_idx, (title, mask) in enumerate(panels):
    ax = axes[ax_idx]
    sub = df[mask]
    for sched, (color, marker, label) in SCHED.items():
        s = sub[sub["scheduler"] == sched]
        if len(s) == 0: continue
        ax.scatter(s["p95_slow"], s["co2_red_pct"], c=color, marker=marker,
                   s=180, alpha=0.85, edgecolor="black", linewidth=0.7,
                   label=label if ax_idx == 0 else None)
    ax.set_xlabel("p95 slowdown (×)")
    ax.set_ylabel("IT CO₂ reduction (%)" if ax_idx == 0 else "")
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    ax.set_xscale("log")
    ax.axhline(0, color="black", linewidth=0.5)

axes[0].legend(loc="upper left", fontsize=11, framealpha=0.95)
fig.suptitle("Carbon-vs-QoS Pareto Frontier: GridPilot-OPT-PUE achieves CarbonScaler-class CO₂ savings at FCFS-class QoS",
             fontsize=20, fontweight="bold", y=1.02)
fig.tight_layout(w_pad=3)
fig.savefig(ROOT / "figures" / "fig_pareto_1x4.pdf", bbox_inches="tight")
fig.savefig(ROOT / "figures" / "fig_pareto_1x4.png", bbox_inches="tight", dpi=150)
print("Saved fig_pareto_1x4.{pdf,png}")
