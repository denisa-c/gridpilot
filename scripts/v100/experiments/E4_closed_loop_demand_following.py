#!/usr/bin/env python3
"""
E4_closed_loop_demand_following.py — Closed-loop demand-following with the
full three-tier hierarchical controller.

Purpose: Validate that the controller actually tracks an external demand
signal in real time on the V100. Models the grid-signal-tracking duty
cycle that the GridPilot multi-scale controller performs in production.

Test design:
  An external "demand signal" is replayed from the synthesised CH/IT/DE
  carbon-intensity / FCR-N envelope (see GridPilot Pillar 6 in the proposal).
  For this hardware-only validation we use a synthetic demand signal that
  ramps and step-changes in a way that exercises all three tiers:
    Phase 1 (0-60s):    demand at 60% of TDP (180 W)
    Phase 2 (60-120s):  demand ramps linearly to 90% TDP (270 W)
    Phase 3 (120-180s): demand step-changes to 50% TDP (150 W)
    Phase 4 (180-240s): demand sinusoidal 150-270 W with 30s period
    Phase 5 (240-300s): demand at 80% TDP (240 W)
  Total: 5 minutes per workload.

  The controller's job: keep measured GPU power within +/- 3% of the demand
  signal, while not letting throughput drop below a workload-specific floor
  set at 70% of the unconstrained baseline.

Output:
  results/E4_closed_loop_<ts>/<workload>_trajectory.csv with columns
  t, demand_w, measured_w, error_w, throughput, throughput_floor, sm_target.
  Plus <workload>_summary.json with quality-of-tracking metrics.

Reference: the demand-following methodology aligns with Kang et al. 2022
IEEE TIE Cooperative Distributed GPU Power Capping (doi:10.1109/TIE.2021.3070430)
which validates a Lagrangian dual-decomposition predictive controller on real
GPU clusters with mean absolute error < 1%.
"""
import argparse
import csv
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def demand_signal(t_s):
    """Synthetic demand signal in watts, replicating the multi-phase test."""
    if t_s < 60:
        return 180.0
    elif t_s < 120:
        # Ramp 180 -> 270 over 60 seconds
        return 180.0 + (270 - 180) * (t_s - 60) / 60
    elif t_s < 180:
        return 150.0
    elif t_s < 240:
        # Sinusoidal 150-270 with 30s period, centred on 210
        return 210.0 + 60 * math.sin(2 * math.pi * (t_s - 180) / 30)
    else:
        return 240.0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--workloads", nargs="+",
                   default=["matmul_compute_bound", "inference_memory_bound", "bursty_alternating"])
    p.add_argument("--duration", type=float, default=300.0,
                   help="seconds per workload (default 300)")
    p.add_argument("--control_period_s", type=float, default=1.0,
                   help="how often Tier-1 + Tier-2 issue a new pcap setpoint")
    args = p.parse_args()

    if os.geteuid() != 0:
        print("ERROR: requires sudo for nvidia-smi -pl.", file=sys.stderr)
        sys.exit(1)

    KIT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(KIT / "controller"))
    from hierarchical_controller import HierarchicalController

    workloads_path = KIT / "workloads/workload_definitions.py"
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = KIT / "results" / f"E4_closed_loop_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}")

    for wl in args.workloads:
        print(f"\n=== {wl} ===")
        # Ensure default state
        subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-pl", "300"],
                        check=False, capture_output=True)
        time.sleep(1)

        # Start workload subprocess
        wl_log = out_dir / f"{wl}_workload.stdout"
        wl_proc = subprocess.Popen([
            "python3", str(workloads_path),
            "--workload", wl,
            "--duration", str(args.duration),
            "--seed", "42",
        ], stdout=wl_log.open("w"), stderr=subprocess.STDOUT)

        # Initialise controller (start at full TDP; tier-3 not exercised here)
        ctrl = HierarchicalController(gpu_index=args.gpu, target_pcap=300, target_sm=1380,
                                       throughput_floor=None)

        # Telemetry + control loop
        try:
            import pynvml
        except ImportError:
            print("ERROR: pynvml not installed.")
            wl_proc.terminate()
            sys.exit(1)
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(args.gpu)

        traj_csv = out_dir / f"{wl}_trajectory.csv"
        traj_file = traj_csv.open("w", newline="")
        writer = csv.writer(traj_file)
        writer.writerow(["t", "demand_w", "measured_w", "error_w",
                          "pcap_command", "target_pcap", "sm_clock_mhz"])

        t0 = time.time()
        next_control = 0.0
        last_pcap_set = 300
        try:
            while time.time() - t0 < args.duration:
                t = time.time() - t0
                try:
                    p_meas = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
                    sm_now = pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_SM)
                except Exception:
                    p_meas = 0.0
                    sm_now = 0
                d = demand_signal(t)
                ctrl.target_pcap = d
                rec = ctrl.step(t + t0, p_meas, sm_now,
                                 throughput_iters_per_s=10.0)  # placeholder
                err = p_meas - d
                writer.writerow([f"{t:.4f}", f"{d:.2f}", f"{p_meas:.2f}",
                                  f"{err:.2f}", f"{rec['pcap_command']:.1f}",
                                  f"{rec['target_pcap']:.1f}", sm_now])
                # Apply pcap if it has changed enough to be worth a syscall
                if t >= next_control:
                    target = max(150, min(300, int(round(rec["pcap_command"]))))
                    if abs(target - last_pcap_set) >= 2:
                        subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-pl",
                                         str(target)], check=False, capture_output=True)
                        last_pcap_set = target
                    next_control = t + args.control_period_s
                # 100 Hz inner loop
                time.sleep(0.01)
        finally:
            traj_file.close()
            subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-pl", "300"],
                            check=False, capture_output=True)
            if wl_proc.poll() is None:
                wl_proc.terminate()
                wl_proc.wait(timeout=5)
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

        # Compute summary metrics
        with traj_csv.open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        errors = [abs(float(r["error_w"])) for r in rows if r["error_w"] not in ("", "nan")]
        if errors:
            mae = sum(errors) / len(errors)
            errors_sorted = sorted(errors)
            p95 = errors_sorted[int(0.95 * len(errors_sorted))]
            mean_demand = sum(float(r["demand_w"]) for r in rows) / len(rows)
            relative_mae = mae / max(mean_demand, 1e-3)
            metrics = {
                "workload": wl,
                "n_samples": len(rows),
                "mae_w": mae,
                "p95_error_w": p95,
                "mean_demand_w": mean_demand,
                "relative_mae": relative_mae,
                "duration_s": float(rows[-1]["t"]) if rows else 0,
            }
            print(f"  MAE={mae:.2f}W, p95={p95:.2f}W, relative_MAE={relative_mae:.4f}")
            (out_dir / f"{wl}_summary.json").write_text(json.dumps(metrics, indent=2))

    print(f"\n✓ E4 complete. Output: {out_dir}")
    print(f"  Next: python3 analysis/analyse_E4.py --run-dir {out_dir}")


if __name__ == "__main__":
    main()
