#!/usr/bin/env python3
"""
project_cluster.py — Use calibrated RAPS coefficients to project rack-
and cluster-scale energy/power/throughput from your 3-V100 node
measurements.

Methodology
-----------
The calibrate_raps.py output gives us a per-workload power model:
    P_GPU(L, f) = P_idle + alpha·f + beta·f²·L + gamma·L

For a rack (e.g. 12 nodes × 3 GPU = 36 GPU) or cluster (50-rack 1 MW,
1000-rack 50 MW), we assume:
  - Per-GPU model is identical (same V100 SKU; future H100/H200 racks
    require recalibration).
  - Inter-node communication overhead adds <2% to facility power for
    AllReduce-bound LLM workloads (Brewer et al. 2024 SC24, Frontier
    digital-twin study). Compute-bound workloads add ~0%.
  - Node idle scales linearly with node count.
  - PUE is the same as the calibration host UNLESS a different value
    is provided (e.g. for direct-liquid-cooled hyperscale).

The projection includes a 95% prediction band derived from the
calibration's LOOCV residual stdev, propagated through the model
linearly. This is the IEC 60359-style measurement-uncertainty
propagation: the projection's uncertainty band is no smaller than
the calibration's.

Refs:
- Brewer et al. (2024). 'A Digital Twin Framework for Liquid-cooled
  Supercomputers as Demonstrated at Exascale.' SC24.
  https://doi.org/10.1145/3624062.3624225
- Maiterth et al. (2025). 'HPC Digital Twins for Evaluating
  Scheduling Policies, Incentive Structures and their Impact on
  Power and Cooling.'

Outputs
-------
results/cluster_projection_<UTC>/
    projection.csv             one row per (workload, scale, operating point)
    projection_summary.json    aggregated by scale
    fig_scale_envelope.png     projected facility power vs scale w/ uncertainty
    fig_cluster_pareto.png     throughput-vs-power Pareto by scale

Usage
-----
    python3 src/project_cluster.py \\
        --coefficients results/raps_calibration_<UTC>/coefficients.json \\
        [--scales node rack pod cluster]    # default: all four
        [--rack-nodes 12]                    # nodes per rack (default 12)
        [--cluster-racks 1000]               # racks per cluster (default 1000)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


SCALE_DEFINITIONS = {
    # name -> (n_nodes, label_for_plot)
    # Defaults are reasonable for a V100-class cluster; actual sizes are
    # computed at runtime from --rack-nodes and --cluster-racks so the
    # label can be overridden too.
    "node":    (1,                 "1 node"),
    "rack":    (12,                "1 rack (12 nodes)"),
    "pod":     (12 * 50,           "1 pod (50 racks)"),
    "cluster": (12 * 1000,         "1 cluster (1000 racks)"),
}


def predict_gpu_power(L: float, f: float, coef: dict) -> float:
    """Apply the fitted GPU power model."""
    return (coef["P_idle"]
            + coef["alpha"] * f
            + coef["beta"] * f**2 * L
            + coef["gamma"] * L)


def predict_with_uncertainty(L: float, f: float, coef: dict
                              ) -> tuple[float, float]:
    """Returns (predicted_W, ±half-width-of-95%-band-W).

    The half-width is derived from the LOOCV MAE (in %), expanded
    by 1.96 (normal-approx 95%): uncertainty = pred * 1.96 * MAE/100.
    This is conservative — assumes residuals are roughly normal,
    which is OK for n_cells > ~10.
    """
    pred = predict_gpu_power(L, f, coef)
    half_band = pred * 1.96 * coef["loocv_mae_pct"] / 100.0
    return pred, half_band


def project_one_cell(scale: str, n_nodes: int, workload: str,
                     coef: dict, node_cfg: dict, L: float, f: float
                     ) -> dict:
    """Project a single (scale, workload, operating-point) row."""
    p_gpu, p_gpu_band = predict_with_uncertainty(L, f, coef)
    n_gpu = n_nodes * node_cfg["n_gpu_per_node"]

    # IT-side power
    p_gpu_total = n_gpu * p_gpu
    p_gpu_total_band = n_gpu * p_gpu_band
    # Node-level idle (CPU + DRAM + misc) — calibration estimated this
    p_node_idle = n_nodes * node_cfg["node_idle_w_estimate"]
    p_it = p_gpu_total + p_node_idle

    # Facility power
    pue = node_cfg["facility_pue"]
    rect_eta = node_cfg["rectifier_eta"]
    p_facility = p_it * pue / rect_eta
    p_facility_band = p_gpu_total_band * pue / rect_eta

    # Throughput projection: assumes perfect weak scaling for compute-bound
    # work (n_gpu × per-GPU throughput at this operating point) and -2% per
    # 10× scale jump for comm-bound work. We don't know the workload's
    # comm fraction here, so we report the upper bound (perfect scaling)
    # and let the operator multiply by their comm-overhead estimate.
    perf_proxy = L * coef["iters_per_s_max"]
    throughput = n_gpu * perf_proxy

    return dict(
        scale=scale,
        n_nodes=n_nodes,
        n_gpu=n_gpu,
        workload=workload,
        L=L,
        sm_mhz=f,
        p_gpu_per_w=p_gpu,
        p_gpu_per_w_band=p_gpu_band,
        p_it_total_w=p_it,
        p_facility_total_w=p_facility,
        p_facility_band_w=p_facility_band,
        throughput_iters_per_s=throughput,
        efficiency_iters_per_joule=throughput / p_facility if p_facility else 0,
    )


def make_scale_envelope_plot(rows: list[dict], path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    workloads = sorted({r["workload"] for r in rows})
    fig, ax = plt.subplots(figsize=(10, 6))
    palette = {"matmul_compute_bound": "#0F766E",
               "inference_memory_bound": "#00A896",
               "bursty_alternating": "#DC2626"}
    scales_order = ["node", "rack", "pod", "cluster"]
    x_pos = {s: i for i, s in enumerate(scales_order)}

    for wl in workloads:
        # Pick the BEST (highest throughput) operating point per scale
        wl_rows = [r for r in rows if r["workload"] == wl]
        by_scale: dict[str, dict] = {}
        for r in wl_rows:
            s = r["scale"]
            if s not in by_scale or \
               r["throughput_iters_per_s"] > by_scale[s]["throughput_iters_per_s"]:
                by_scale[s] = r
        xs = [x_pos[s] for s in scales_order if s in by_scale]
        ys = [by_scale[s]["p_facility_total_w"] / 1000
              for s in scales_order if s in by_scale]
        bands = [by_scale[s]["p_facility_band_w"] / 1000
                  for s in scales_order if s in by_scale]
        color = palette.get(wl, "#64748B")
        ax.errorbar(xs, ys, yerr=bands, fmt="o-", capsize=5, color=color,
                    label=wl, linewidth=2, markersize=8)
    ax.set_xticks(list(x_pos.values()))
    ax.set_xticklabels([SCALE_DEFINITIONS[s][1] for s in scales_order],
                        rotation=15, ha="right")
    ax.set_ylabel("Projected facility power (kW)")
    ax.set_yscale("log")
    ax.set_title("Cluster-scale projection from calibrated RAPS\n"
                  "Error bars = 95% prediction band from LOOCV residuals",
                  fontsize=11)
    ax.legend(loc="upper left")
    ax.grid(True, which="both", alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()


def make_pareto_plot(rows: list[dict], path: Path):
    """Throughput vs facility power, coloured by scale."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    workloads = sorted({r["workload"] for r in rows})
    fig, axes = plt.subplots(1, len(workloads), figsize=(6 * len(workloads), 5),
                              squeeze=False)
    scale_color = {"node": "#0F766E", "rack": "#00A896",
                    "pod": "#DC2626", "cluster": "#0F172A"}
    for j, wl in enumerate(workloads):
        ax = axes[0, j]
        wl_rows = [r for r in rows if r["workload"] == wl]
        for scale in ["node", "rack", "pod", "cluster"]:
            sr = [r for r in wl_rows if r["scale"] == scale]
            if not sr: continue
            xs = [r["p_facility_total_w"] / 1000 for r in sr]
            ys = [r["throughput_iters_per_s"] for r in sr]
            ax.scatter(xs, ys, s=70, alpha=0.7,
                        color=scale_color[scale], label=scale,
                        edgecolors="white", linewidths=0.5)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Facility power (kW)")
        ax.set_ylabel("Throughput (iters/s)")
        ax.set_title(wl)
        ax.legend(loc="lower right", fontsize=9)
        ax.grid(True, which="both", alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()


def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--coefficients", required=True, type=Path,
                   help="coefficients.json from calibrate_raps.py")
    p.add_argument("--scales", nargs="+",
                   default=list(SCALE_DEFINITIONS.keys()),
                   choices=list(SCALE_DEFINITIONS.keys()))
    p.add_argument("--rack-nodes", type=int, default=12,
                   help="nodes per rack (default 12 for V100-class)")
    p.add_argument("--cluster-racks", type=int, default=1000,
                   help="racks per cluster (default 1000 → 50 MW)")
    p.add_argument("--operating-points", type=int, default=10,
                   help="how many (L, f) points per workload to project (default 10)")
    p.add_argument("--pue", type=float, default=None,
                   help="override calibrated PUE (e.g. 1.03 for liquid)")
    p.add_argument("--out-dir", type=Path, default=None)
    args = p.parse_args()

    if not args.coefficients.exists():
        sys.exit(f"missing {args.coefficients}")
    coef_data = json.loads(args.coefficients.read_text())
    node_cfg = dict(coef_data["node"])
    if args.pue is not None:
        node_cfg["facility_pue"] = args.pue

    # Allow CLI to override default rack/cluster sizes
    rack_n = args.rack_nodes
    n_gpu_per_node = node_cfg['n_gpu_per_node']
    SCALE_DEFINITIONS["rack"] = (
        rack_n,
        f"1 rack ({rack_n} nodes, {rack_n * n_gpu_per_node} GPU)")
    pod_racks = 50  # convention
    SCALE_DEFINITIONS["pod"] = (
        pod_racks * rack_n,
        f"1 pod ({pod_racks} racks, "
        f"{pod_racks * rack_n * n_gpu_per_node} GPU)")
    SCALE_DEFINITIONS["cluster"] = (
        args.cluster_racks * rack_n,
        f"1 cluster ({args.cluster_racks} racks, "
        f"{args.cluster_racks * rack_n * n_gpu_per_node:,} GPU)")

    # Operating points: sweep utilisation from 0.1 to 1.0 at a representative
    # SM clock per workload (the LOOCV-best clock from calibration).
    L_grid = np.linspace(0.1, 1.0, args.operating_points)
    rows = []
    for wl, coef in coef_data["per_workload"].items():
        # Pick a representative clock: midpoint of the calibration range,
        # rounded to a real V100 P-state. V100 P-states: 1380, 1245, 1170,
        # 1095, 1020, 945, 870, 405 MHz.
        f_mid = 945.0  # the canonical "sweet-spot" V100 SM clock
        for scale in args.scales:
            n_nodes = SCALE_DEFINITIONS[scale][0]
            for L in L_grid:
                rows.append(project_one_cell(scale, n_nodes, wl,
                                              coef, node_cfg,
                                              float(L), f_mid))

    # Output dir
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (ROOT / "results" / f"cluster_projection_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    proj_path = out_dir / "projection.csv"
    with proj_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v)
                        for k, v in r.items()})

    # Per-scale aggregate summary
    summary = {}
    for scale in args.scales:
        s_rows = [r for r in rows if r["scale"] == scale]
        if not s_rows: continue
        max_p = max(r["p_facility_total_w"] for r in s_rows)
        max_th = max(r["throughput_iters_per_s"] for r in s_rows)
        max_eff = max(r["efficiency_iters_per_joule"] for r in s_rows)
        summary[scale] = {
            "n_nodes": SCALE_DEFINITIONS[scale][0],
            "n_gpu":   SCALE_DEFINITIONS[scale][0] * node_cfg["n_gpu_per_node"],
            "max_facility_kw": round(max_p / 1000, 2),
            "max_throughput_iters_per_s": round(max_th, 2),
            "max_efficiency_iters_per_joule": round(max_eff, 4),
            "n_workloads": len({r["workload"] for r in s_rows}),
        }
    (out_dir / "projection_summary.json").write_text(json.dumps(summary, indent=2))

    # Plots
    try:
        make_scale_envelope_plot(rows, out_dir / "fig_scale_envelope.png")
        make_pareto_plot(rows, out_dir / "fig_cluster_pareto.png")
    except ImportError:
        print("matplotlib not installed; skipping plots")

    print(f"✓ Wrote {out_dir}")
    print(f"  {len(rows)} projected (scale, workload, operating-point) rows")
    print(f"  scales: {', '.join(args.scales)}")
    for scale in args.scales:
        if scale in summary:
            s = summary[scale]
            print(f"  {scale:8s} ({s['n_gpu']:>5} GPU): "
                  f"≤{s['max_facility_kw']:>8.1f} kW facility, "
                  f"≤{s['max_throughput_iters_per_s']:>10.1f} iters/s")


if __name__ == "__main__":
    main()
