#!/usr/bin/env python3
"""
calibrate_raps.py — Fit RAPS power-model coefficients to your measured
V100 + node data, then write a coefficients file that raps_projection.py
can use for cluster-scale projections.

Model
-----
GPU power as a function of utilisation L (proxied by throughput) and SM
clock f (MHz):
    P_GPU(L, f) = P_idle + alpha·f + beta·f²·L + gamma·L

This is the analytical form used by Ali et al. (FGCS 2023) and the
unified DVFS power model of Núñez-Yáñez et al. (PARMA-DITAM 2020),
both of which report 3-5 % MAE on V100/A100-class GPUs when fit on
~30-50 (frequency, utilisation) cells.

Refs:
- Ali, G. et al. (2023). 'An automated and portable method for
  selecting an optimal GPU frequency.' Future Generation Computer
  Systems. https://doi.org/10.1016/j.future.2023.06.011
- Núñez-Yáñez, J. et al. (2020). 'Run-Time Power Modelling in
  Embedded GPUs with Dynamic Voltage and Frequency Scaling.' In
  Proc. PARMA-DITAM 2020. https://doi.org/10.1145/3381427.3381432

Inputs
------
The parsed_results.csv from your E1 sweep. Required columns:
    workload, pcap_w, sm_target_mhz, power_mean_w, iters_per_s
Optionally:
    sm_actual_mhz   (preferred over sm_target if present)

Outputs
-------
results/raps_calibration_<UTC>/
    coefficients.json         per-workload (P_idle, alpha, beta, gamma)
                              + node-level CPU and PUE estimates
    fit_diagnostics.csv       per-cell (predicted, measured, residual_pct)
    fit_summary.json          MAE, RMSE, R² per workload
    leave_one_out_cv.json     LOOCV residuals (the honest accuracy number)
    fit_curves.png            P(f, L) surface vs measurements per workload

Usage
-----
    python3 src/calibrate_raps.py \\
        --parsed-results results/sweep_20260428_134955/parsed_results.csv \\
        [--node-idle-w 250]      # measured node-level idle (default: estimate)
        [--node-pue 1.10]        # measured/assumed facility PUE
        [--rect-eta 0.93]        # AC rectifier efficiency
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


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_parsed_results(path: Path) -> dict[str, list[dict]]:
    """Load parsed_results.csv, group rows by workload, coerce numerics."""
    rows_by_wl: dict[str, list[dict]] = {}
    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            wl = r["workload"]
            try:
                row = dict(
                    pcap_w=float(r["pcap_w"]),
                    # Prefer measured SM clock if present; many runs only log target.
                    sm_mhz=float(r.get("sm_actual_mhz") or r["sm_target_mhz"]),
                    power_w=float(r["power_mean_w"]),
                    iters_per_s=float(r["iters_per_s"]),
                )
            except (KeyError, ValueError, TypeError):
                continue
            if row["power_w"] <= 0 or row["iters_per_s"] <= 0:
                continue
            rows_by_wl.setdefault(wl, []).append(row)
    return rows_by_wl


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------
def fit_one_workload(rows: list[dict]) -> dict:
    """Fit P_GPU(L, f) = P_idle + alpha·f + beta·f²·L + gamma·L per workload.

    Uses ordinary least squares on the linearised model. With ~12 cells per
    workload and 4 unknowns, the system is well-determined; we report
    leave-one-out CV residuals as the honest accuracy figure.
    """
    if len(rows) < 5:
        raise ValueError(f"need ≥5 cells to fit; have {len(rows)}")

    # Utilisation proxy: throughput normalised by per-workload max
    iters_max = max(r["iters_per_s"] for r in rows)
    for r in rows:
        r["L"] = r["iters_per_s"] / iters_max

    # Design matrix [1, f, f²·L, L]
    X = np.array([[1.0, r["sm_mhz"], r["sm_mhz"]**2 * r["L"], r["L"]]
                  for r in rows])
    y = np.array([r["power_w"] for r in rows])

    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    P_idle, alpha, beta, gamma = coef
    pred = X @ coef
    resid = y - pred
    mae = float(np.mean(np.abs(resid)))
    rmse = float(np.sqrt(np.mean(resid**2)))
    r2 = float(1.0 - np.sum(resid**2) / np.sum((y - np.mean(y))**2))

    # Leave-one-out CV: refit with each cell held out and report its residual
    loocv = []
    for i in range(len(rows)):
        mask = np.arange(len(rows)) != i
        c, *_ = np.linalg.lstsq(X[mask], y[mask], rcond=None)
        pred_i = float(X[i] @ c)
        loocv.append(dict(idx=i, true=float(y[i]), pred=pred_i,
                           pct_err=100 * (pred_i - y[i]) / y[i]))
    loocv_mae = float(np.mean([abs(x["pct_err"]) for x in loocv]))

    return dict(
        n_cells=len(rows),
        iters_per_s_max=iters_max,
        P_idle=float(P_idle),
        alpha=float(alpha),
        beta=float(beta),
        gamma=float(gamma),
        in_sample_mae_w=mae,
        in_sample_rmse_w=rmse,
        in_sample_r2=r2,
        loocv_mae_pct=loocv_mae,
        cells=[dict(pcap_w=r["pcap_w"], sm_mhz=r["sm_mhz"],
                     L=r["L"], measured_w=r["power_w"],
                     predicted_w=float(pred[i]),
                     residual_pct=100 * (pred[i] - r["power_w"]) / r["power_w"])
                for i, r in enumerate(rows)],
        loocv=loocv,
    )


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------
def make_fit_curves(fits: dict, out_path: Path):
    """Per-workload measurement vs prediction scatter + residual histogram."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    workloads = list(fits.keys())
    n = len(workloads)
    fig, axes = plt.subplots(2, n, figsize=(5 * n, 8))
    if n == 1:
        axes = axes[:, None]
    for j, wl in enumerate(workloads):
        f = fits[wl]
        cells = f["cells"]
        meas = [c["measured_w"] for c in cells]
        pred = [c["predicted_w"] for c in cells]
        # Top row: measured vs predicted
        ax = axes[0, j]
        ax.scatter(meas, pred, s=40, alpha=0.7, color="#0F766E")
        lo, hi = min(meas + pred) * 0.9, max(meas + pred) * 1.1
        ax.plot([lo, hi], [lo, hi], "--", color="#64748B", linewidth=1)
        ax.set_xlabel("Measured power (W)")
        ax.set_ylabel("Predicted power (W)")
        ax.set_title(f"{wl}\nLOOCV MAE = {f['loocv_mae_pct']:.1f}%, "
                     f"R² = {f['in_sample_r2']:.3f}")
        ax.grid(True, alpha=0.3)
        # Bottom row: residual histogram
        ax = axes[1, j]
        residuals = [c["residual_pct"] for c in cells]
        ax.hist(residuals, bins=10, color="#00A896", alpha=0.7,
                 edgecolor="#0F172A")
        ax.axvline(0, color="#DC2626", linestyle="--", linewidth=1)
        ax.set_xlabel("Residual (%)")
        ax.set_ylabel("Count")
        ax.set_title(f"{wl} residuals")
        ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--parsed-results", required=True, type=Path,
                   help="path to parsed_results.csv from your E1 sweep")
    p.add_argument("--node-idle-w", type=float, default=None,
                   help="measured node-level idle power; "
                        "default is estimated from minimum-power row")
    p.add_argument("--node-pue", type=float, default=1.10,
                   help="facility PUE (default 1.10; ProACT will refine)")
    p.add_argument("--rect-eta", type=float, default=0.9287,
                   help="AC rectifier efficiency (Wojda 2024 ECCE; "
                        "default 0.9287)")
    p.add_argument("--n-gpu-per-node", type=int, default=3,
                   help="GPUs per node on the calibration host (default 3)")
    p.add_argument("--out-dir", type=Path, default=None)
    args = p.parse_args()

    if not args.parsed_results.exists():
        sys.exit(f"missing {args.parsed_results}")
    rows_by_wl = load_parsed_results(args.parsed_results)
    if not rows_by_wl:
        sys.exit("no usable rows found")

    # Estimate node idle from minimum-power cell if not provided
    all_powers = [r["power_w"] for rs in rows_by_wl.values() for r in rs]
    estimated_node_idle = min(all_powers) * 0.6 if all_powers else 250
    node_idle = args.node_idle_w or estimated_node_idle

    print(f"Calibrating RAPS coefficients on {sum(map(len, rows_by_wl.values()))} "
          f"cells across {len(rows_by_wl)} workloads")

    fits = {}
    for wl, rows in rows_by_wl.items():
        try:
            fits[wl] = fit_one_workload(rows)
            f = fits[wl]
            print(f"  {wl}: {f['n_cells']} cells, "
                  f"P_idle={f['P_idle']:.1f}W, "
                  f"alpha={f['alpha']:.3f} W/MHz, "
                  f"in-sample MAE={f['in_sample_mae_w']:.2f}W "
                  f"(R²={f['in_sample_r2']:.3f}), "
                  f"LOOCV MAE={f['loocv_mae_pct']:.1f}%")
        except ValueError as e:
            print(f"  {wl}: SKIPPED ({e})")

    if not fits:
        sys.exit("no workloads successfully fit")

    # Output
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (ROOT / "results" / f"raps_calibration_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    coefficients = {
        "calibrated_at": stamp,
        "source_csv": str(args.parsed_results.resolve()),
        "model": "P_GPU = P_idle + alpha*f + beta*f^2*L + gamma*L",
        "node": {
            "n_gpu_per_node": args.n_gpu_per_node,
            "node_idle_w_estimate": node_idle,
            "facility_pue": args.node_pue,
            "rectifier_eta": args.rect_eta,
        },
        "per_workload": {wl: {k: v for k, v in f.items()
                              if k not in ("cells", "loocv")}
                          for wl, f in fits.items()},
    }
    (out_dir / "coefficients.json").write_text(
        json.dumps(coefficients, indent=2))

    # Fit diagnostics CSV (one row per cell)
    diag_path = out_dir / "fit_diagnostics.csv"
    with diag_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["workload", "pcap_w", "sm_mhz",
                                             "L", "measured_w", "predicted_w",
                                             "residual_pct"])
        w.writeheader()
        for wl, f in fits.items():
            for c in f["cells"]:
                w.writerow({"workload": wl, **c})

    # Fit summary
    summary = {wl: {k: f[k] for k in ("n_cells", "in_sample_mae_w",
                                        "in_sample_rmse_w", "in_sample_r2",
                                        "loocv_mae_pct")}
                for wl, f in fits.items()}
    (out_dir / "fit_summary.json").write_text(json.dumps(summary, indent=2))

    # Save full LOOCV table
    loocv = {wl: f["loocv"] for wl, f in fits.items()}
    (out_dir / "leave_one_out_cv.json").write_text(json.dumps(loocv, indent=2))

    # Plot
    try:
        make_fit_curves(fits, out_dir / "fit_curves.png")
    except ImportError:
        print("  (matplotlib not installed; skipping plot)")

    print(f"\n✓ Wrote {out_dir}")
    print(f"  use these coefficients with raps_projection.py:")
    print(f"  python3 src/project_cluster.py "
          f"--coefficients {out_dir / 'coefficients.json'}")


if __name__ == "__main__":
    main()
