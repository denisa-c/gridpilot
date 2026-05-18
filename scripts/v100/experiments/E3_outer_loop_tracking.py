#!/usr/bin/env python3
"""
E3_outer_loop_tracking.py — Outer-loop AR(4) prediction error vs. ground truth.

Purpose: Validate Tier-2 forecast accuracy on real V100 power and throughput
under the three benchmark workloads. Reports MAE and p95 prediction error
on a 1-second horizon.

Test design:
  Run each workload at full power for 5 minutes, sampling NVML at 100 Hz.
  Drive the AR(4) predictor at 1 Hz from the rolling 1-minute buffer.
  Compare the 1-step-ahead prediction against the ground truth (the next
  observed sample). Record MAE and p95 over the run.

Output: results/E3_outer_loop_<ts>/<workload>_predictions.csv with columns
  t, observed, predicted, error.
And summary metrics in <workload>_metrics.json.

Reference: AR(4) baseline established in Box-Jenkins (1976) "Time Series
Analysis: Forecasting and Control" 2nd ed.; the choice of order 4 follows
the empirical fit on M100 GPU power traces (PM100 dataset, Antici et al.
2023 doi:10.1038/s41597-023-02465-9).
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--duration", type=float, default=300.0,
                   help="seconds per workload (default 300)")
    p.add_argument("--workloads", nargs="+",
                   default=["matmul_compute_bound", "inference_memory_bound", "bursty_alternating"])
    args = p.parse_args()

    if os.geteuid() != 0:
        print("WARNING: not running as root; persistence-mode may fail.", file=sys.stderr)

    KIT = Path(__file__).resolve().parent.parent
    workloads_path = KIT / "workloads/workload_definitions.py"
    telemetry_path = KIT / "scripts/04_collect_telemetry.py"

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = KIT / "results" / f"E3_outer_loop_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}")

    # Run each workload sequentially
    for wl in args.workloads:
        print(f"\n=== {wl} ===")
        tel_csv = out_dir / f"{wl}_telemetry.csv"
        wl_log = out_dir / f"{wl}_stdout"
        rc = subprocess.run([
            "python3", str(telemetry_path),
            "--output", str(tel_csv),
            "--rate", "100",
            "--gpus", str(args.gpu),
            "--", "python3", str(workloads_path),
            "--workload", wl,
            "--duration", str(args.duration),
            "--seed", "42",
        ], stdout=wl_log.open("w"), stderr=subprocess.STDOUT).returncode
        print(f"  workload exit={rc}, telemetry rows={sum(1 for _ in tel_csv.open()) - 1}")

        # Run AR(4) over the captured trace and compute prediction error
        sys.path.insert(0, str(KIT / "controller"))
        from hierarchical_controller import AR4Outer
        ar = AR4Outer()

        rows = []
        with tel_csv.open() as f:
            reader = csv.DictReader(f)
            for r in reader:
                try:
                    rows.append({"t": float(r["t_s"]), "power_w": float(r["power_w"])})
                except (ValueError, KeyError):
                    pass

        # Subsample at 1 Hz: one sample per second
        ar_inputs = []
        last_t = -1.0
        for r in rows:
            if r["t"] - last_t >= 1.0:
                ar_inputs.append(r)
                last_t = r["t"]

        # Run online prediction
        predictions = []
        for i, r in enumerate(ar_inputs):
            if i >= 4:
                pred = ar.predict()
                err = r["power_w"] - pred
                predictions.append({"t": r["t"], "observed": r["power_w"],
                                    "predicted": pred, "error": err})
            ar.update(r["t"], r["power_w"])

        # Compute MAE, RMSE, p95
        if predictions:
            errors = [abs(p["error"]) for p in predictions]
            errors_sorted = sorted(errors)
            mae = sum(errors) / len(errors)
            rmse = (sum(e ** 2 for e in errors) / len(errors)) ** 0.5
            p95 = errors_sorted[int(0.95 * len(errors_sorted))]
            metrics = {
                "workload": wl,
                "n_predictions": len(predictions),
                "mae_w": mae, "rmse_w": rmse, "p95_w": p95,
                "ar_phi_final": list(ar.phi),
                "ar_c_final": ar.c,
            }
            print(f"  MAE = {mae:.2f} W, RMSE = {rmse:.2f} W, p95 = {p95:.2f} W")
            print(f"  AR(4) coefficients: phi = {[round(p, 3) for p in ar.phi]}")

            # Save predictions
            pred_csv = out_dir / f"{wl}_predictions.csv"
            with pred_csv.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["t", "observed", "predicted", "error"])
                w.writeheader()
                w.writerows(predictions)

            # Save metrics
            (out_dir / f"{wl}_metrics.json").write_text(json.dumps(metrics, indent=2))

    print(f"\n✓ E3 complete. Output: {out_dir}")
    print(f"  Next: python3 analysis/analyse_E3.py --run-dir {out_dir}")


if __name__ == "__main__":
    main()
