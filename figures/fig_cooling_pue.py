#!/usr/bin/env python3
"""Regenerate the cooling-PUE validation figure from cached results."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from cooling.cooling_pue_model import calibrate_to_design_pue, compute_cooling_power_kw

plt.rcParams.update({"font.family":"serif","font.size":17,"axes.titlesize":22,
                      "axes.labelsize":18,"savefig.dpi":300,
                      "axes.spines.top":False,"axes.spines.right":False})
cool_p = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
fig, axes = plt.subplots(1, 4, figsize=(32, 7))
loads = np.linspace(0.05, 1.0, 50)
for t_amb, color, label in [(10,"#3498db","T_amb=10 C"),
                              (20,"#f39c12","T_amb=20 C"),
                              (30,"#e74c3c","T_amb=30 C")]:
    pue = [compute_cooling_power_kw(L*1400, t_amb, cool_p)["pue_instantaneous"] for L in loads]
    axes[0].plot(loads*100, pue, lw=3, color=color, label=label)
axes[0].set_xlabel("IT Load (%)"); axes[0].set_ylabel("Instantaneous PUE")
axes[0].set_title("(a) GridPilot PUE = f(IT load, T_amb)")
axes[0].legend(); axes[0].grid(True, alpha=0.2)
axes[0].axhline(1.20, color="gray", ls=":", lw=1)
loads30 = np.linspace(0.05, 1.0, 30)
chiller, pumps, air, misc = [], [], [], []
for L in loads30:
    r = compute_cooling_power_kw(L*1400, 20, cool_p)
    chiller.append(r["chiller_kw"]); pumps.append(r["pumps_kw"])
    air.append(r["air_kw"]); misc.append(r["misc_facility_kw"])
axes[1].stackplot(loads30*100, chiller, pumps, air, misc,
                    labels=["Chiller","Pumps","Air","Misc"],
                    colors=["#e74c3c","#3498db","#2ecc71","#95a5a6"], alpha=0.85)
axes[1].set_xlabel("IT Load (%)"); axes[1].set_ylabel("Cooling Power (kW)")
axes[1].set_title("(b) Cooling Decomposition (T=20 C)")
axes[1].legend(loc="upper left"); axes[1].grid(True, alpha=0.2)
months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
m_t = [3.0,5.0,9.5,13.5,18.0,22.5,25.0,24.5,20.0,14.5,8.5,4.5]
fc = [compute_cooling_power_kw(1100,t,cool_p)["free_cooling_fraction"] for t in m_t]
axes[2].bar(months, fc, color="#3498db", alpha=0.85, edgecolor="black", linewidth=0.5)
axes[2].set_ylabel("Free-Cooling Fraction")
axes[2].set_title("(c) Bologna Free-Cooling Availability")
axes[2].set_ylim(0, 1.05); axes[2].grid(True, alpha=0.2, axis="y")
plt.setp(axes[2].xaxis.get_majorticklabels(), rotation=45, fontsize=12)
import pandas as pd
xv = pd.read_csv(ROOT/"data"/"results"/"raps_cross_validation.csv")
systems = ["Marconi100","Frontier"]
gp = [xv.iloc[0]["proact_design_pue"], xv.iloc[1]["proact_design_pue"]]
rp = [xv.iloc[0]["raps_design_pue"], xv.iloc[1]["raps_design_pue"]]
x = np.arange(2); w = 0.35
axes[3].bar(x-w/2, gp, w, label="GridPilot", color="#3498db", alpha=0.85, edgecolor="black", linewidth=0.5)
axes[3].bar(x+w/2, rp, w, label="RAPS", color="#e74c3c", alpha=0.85, edgecolor="black", linewidth=0.5)
axes[3].set_xticks(x); axes[3].set_xticklabels(systems)
axes[3].set_ylabel("Design-Point PUE")
axes[3].set_title("(d) GridPilot vs RAPS"); axes[3].set_ylim(1.0, 1.25)
axes[3].legend(); axes[3].grid(True, alpha=0.2, axis="y")
fig.suptitle("Instantaneous PUE Model: validated against M100 design + RAPS canonical configurations",
              fontsize=18, fontweight="bold", y=1.03)
fig.tight_layout(w_pad=3)
fig.savefig(ROOT/"figures"/"fig_cooling_pue_1x4.pdf", bbox_inches="tight")
fig.savefig(ROOT/"figures"/"fig_cooling_pue_1x4.png", bbox_inches="tight", dpi=150)
print("Saved fig_cooling_pue_1x4.{pdf,png}")
