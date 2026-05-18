"""Regenerate Figure 2: cross-workload comparison heatmaps."""
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
    "axes.labelsize":18,"xtick.labelsize":15,"ytick.labelsize":15,
    "legend.fontsize":13,"savefig.dpi":300,
    "axes.spines.top":False,"axes.spines.right":False,
})

scheds = ["FCFS","Threshold","ProACT++","QoS-bounded","CarbonScaler","ProACT-OPT","ProACT-OPT-PUE"]
labels = ["FCFS","Threshold","GridPilot++","QoS-bounded","CarbonScaler","GridPilot-OPT","GridPilot-OPT-PUE"]
workloads = ["M100","Philly","Acme"]

fig, axes = plt.subplots(1, 4, figsize=(32, 7))

ax = axes[0]
mat = np.zeros((len(scheds), len(workloads)))
for i, s in enumerate(scheds):
    for j, w in enumerate(workloads):
        mat[i,j] = df[(df.scheduler==s)&(df.workload==w)]["co2_red_pct"].mean()
im = ax.imshow(mat, cmap="RdYlGn", aspect="auto", vmin=-5, vmax=45)
ax.set_xticks(range(3)); ax.set_xticklabels(workloads)
ax.set_yticks(range(len(scheds))); ax.set_yticklabels(labels)
for i in range(len(scheds)):
    for j in range(3):
        c = "white" if abs(mat[i,j]) > 25 else "black"
        ax.text(j, i, f"{mat[i,j]:+4.1f}", ha="center", va="center",
                fontsize=13, fontweight="bold", color=c)
ax.set_title("(a) IT CO₂ Reduction (%)")
plt.colorbar(im, ax=ax, shrink=0.7)

ax = axes[1]
mat = np.zeros((len(scheds), len(workloads)))
for i, s in enumerate(scheds):
    for j, w in enumerate(workloads):
        mat[i,j] = df[(df.scheduler==s)&(df.workload==w)]["facility_co2_red_pct"].mean()
im = ax.imshow(mat, cmap="RdYlGn", aspect="auto", vmin=-5, vmax=70)
ax.set_xticks(range(3)); ax.set_xticklabels(workloads)
ax.set_yticks(range(len(scheds))); ax.set_yticklabels(labels)
for i in range(len(scheds)):
    for j in range(3):
        c = "white" if abs(mat[i,j]) > 35 else "black"
        ax.text(j, i, f"{mat[i,j]:+4.1f}", ha="center", va="center",
                fontsize=13, fontweight="bold", color=c)
ax.set_title("(b) Facility CO₂ Reduction (%)")
plt.colorbar(im, ax=ax, shrink=0.7)

ax = axes[2]
sub = df[df.scheduler=="ProACT-OPT-PUE"].groupby("workload").agg(
    it=("co2_red_pct","mean"), fac=("facility_co2_red_pct","mean")).reindex(workloads)
x = np.arange(3); w = 0.35
ax.bar(x-w/2, sub["it"], w, label="IT-only", color="#3498db", alpha=0.85, edgecolor="black", linewidth=0.5)
ax.bar(x+w/2, sub["fac"], w, label="Facility (incl. cooling)", color="#e74c3c", alpha=0.85, edgecolor="black", linewidth=0.5)
for i, (it, fac) in enumerate(zip(sub["it"], sub["fac"])):
    ax.text(i-w/2, it+0.5, f"{it:.1f}%", ha="center", fontsize=12, fontweight="bold")
    ax.text(i+w/2, fac+0.5, f"{fac:.1f}%", ha="center", fontsize=12, fontweight="bold")
ax.set_xticks(x); ax.set_xticklabels(workloads)
ax.set_ylabel("CO₂ Reduction (%)")
ax.set_title("(c) GridPilot-OPT-PUE: IT vs Facility")
ax.legend(loc="upper right", fontsize=12)
ax.grid(True, alpha=0.2, axis="y")
ax.axhline(0, color="black", linewidth=0.5)

ax = axes[3]
pue_by_wl = df[df.scheduler=="FCFS"].groupby("workload")["avg_pue"].mean().reindex(workloads)
colors = ["#3498db","#e67e22","#9b59b6"]
ax.bar(workloads, pue_by_wl.values, color=colors, alpha=0.85, edgecolor="black", linewidth=0.5)
for i, v in enumerate(pue_by_wl.values):
    ax.text(i, v+0.005, f"{v:.3f}", ha="center", fontsize=14, fontweight="bold")
ax.axhline(1.20, color="gray", linestyle="--", linewidth=1, label="Design PUE (1.20)")
ax.set_ylabel("Average PUE")
ax.set_title("(d) Workload-Dependent PUE")
ax.set_ylim(1.10, 1.55)
ax.legend(fontsize=12)
ax.grid(True, alpha=0.2, axis="y")

fig.suptitle("Cross-Workload Validation: M100 (HPC), Philly (DL), Acme (LLM) × CH/IT/DE grids",
             fontsize=20, fontweight="bold", y=1.03)
fig.tight_layout(w_pad=3)
fig.savefig(ROOT / "figures" / "fig_workload_1x4.pdf", bbox_inches="tight")
fig.savefig(ROOT / "figures" / "fig_workload_1x4.png", bbox_inches="tight", dpi=150)
print("Saved fig_workload_1x4.{pdf,png}")
