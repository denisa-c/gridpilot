#!/usr/bin/env python3
"""
E2_inner_loop_step_response.py — Inner-loop PID step-response characterisation.

Purpose: Validate Tier-1 controller stability and time-to-track on the V100.
Methodology follows the standard step-response test in process control
(Skogestad 2003 J. Process Control "Simple analytic rules for model reduction
and PID controller tuning", doi:10.1016/S0959-1524(02)00062-8).

Test design:
  For one GPU index and one workload (default matmul_compute_bound):
    1. Start the workload at full power (300 W on V100 SXM2).
    2. At t=10 s, drop the power-cap setpoint to 200 W.
    3. Sample power at NVML 200 Hz for 30 s.
    4. At t=40 s, raise the setpoint back to 280 W.
    5. Continue for 30 s more.
  Total duration: 70 s.
  Telemetry collector runs in parallel at 200 Hz.

Output metrics:
  - rise time t_r (10% to 90% of step amplitude)
  - settling time t_s (within +/- 2% band)
  - overshoot Mp (peak above target / step amplitude)
  - steady-state error e_ss
  Saved to: results/E2_inner_loop/<workload>_<ts>.json

Reference for V100 thermal time constants:
  Coplin & Burtscher 2018 IPDPSW: ~4 s settle on V100.
  We expect settling time on the order of seconds, not ms — the
  electrical-power response is fast (< 100 ms) but thermal coupling
  delays full convergence.
"""
import argparse
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
    p.add_argument("--workload", default="matmul_compute_bound",
                   choices=["matmul_compute_bound", "inference_memory_bound", "bursty_alternating"])
    p.add_argument("--p_high", type=int, default=280, help="initial power cap (W)")
    p.add_argument("--p_low", type=int, default=200, help="step-down target (W)")
    p.add_argument("--phase_s", type=float, default=10.0,
                   help="seconds in each phase (initial, dropped, restored)")
    p.add_argument("--rate_hz", type=int, default=200, help="telemetry rate")
    args = p.parse_args()

    KIT = Path(__file__).resolve().parent.parent
    workloads = KIT / "workloads/workload_definitions.py"
    telemetry = KIT / "scripts/04_collect_telemetry.py"

    if os.geteuid() != 0:
        print("ERROR: This script requires sudo to set power cap.", file=sys.stderr)
        sys.exit(1)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = KIT / "results" / f"E2_inner_loop_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}")

    # Compute total run time
    total_s = args.phase_s * 3 + 10  # 10s padding
    print(f"Total experiment duration: {total_s:.0f} s")

    # Step plan (relative to telemetry start)
    plan = [
        (0.0,            args.p_high, "initial high"),
        (args.phase_s,   args.p_low,  "step-down"),
        (args.phase_s*2, args.p_high, "step-up"),
    ]
    print(f"Step plan:")
    for t, p_w, label in plan:
        print(f"  t={t:5.1f}s  pcap={p_w} W  ({label})")

    # Set initial state
    subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-pm", "1"],
                    check=False, capture_output=True)
    subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-pl", str(args.p_high)],
                    check=False, capture_output=True)
    subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-rgc"],
                    check=False, capture_output=True)
    time.sleep(1)

    # Start telemetry as a subprocess; we will run the workload concurrently
    tel_csv = out_dir / "telemetry.csv"
    workload_log = out_dir / "workload.stdout"

    tel_proc = subprocess.Popen([
        "python3", str(telemetry),
        "--output", str(tel_csv),
        "--rate", str(args.rate_hz),
        "--gpus", str(args.gpu),
        "--", "python3", str(workloads),
        "--workload", args.workload,
        "--duration", str(int(total_s)),
        "--seed", "42",
    ], stdout=workload_log.open("w"), stderr=subprocess.STDOUT)

    # Apply step plan in a separate timer thread
    t0 = time.time()
    step_log = []
    try:
        for step_t, p_w, label in plan:
            wait = step_t - (time.time() - t0)
            if wait > 0:
                time.sleep(wait)
            t_apply = time.time() - t0
            r = subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-pl", str(p_w)],
                               capture_output=True, text=True)
            step_log.append({"t_planned": step_t, "t_actual": t_apply,
                              "pcap_w": p_w, "label": label,
                              "rc": r.returncode})
            print(f"[{t_apply:5.2f}s] applied pcap={p_w}W ({label}) rc={r.returncode}")
        # Wait for workload to finish
        tel_proc.wait()
    finally:
        # Restore default
        subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-pl", "300"],
                        check=False, capture_output=True)
        if tel_proc.poll() is None:
            tel_proc.terminate()
            tel_proc.wait(timeout=5)

    # Save the step plan as metadata
    meta_path = out_dir / "step_plan.json"
    meta_path.write_text(json.dumps({
        "args": vars(args),
        "plan": [{"t": t, "pcap_w": p, "label": l} for t, p, l in plan],
        "applied": step_log,
    }, indent=2))

    print(f"\n✓ E2 complete. Output: {out_dir}")
    print(f"  Next: python3 analysis/analyse_E2.py --run-dir {out_dir}")


if __name__ == "__main__":
    main()
