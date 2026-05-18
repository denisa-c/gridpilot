#!/usr/bin/env python3
"""
collect_telemetry.py
====================

Wraps an arbitrary executable with NVML power and temperature logging at
1 kHz, CPU utilisation at 100 Hz, and structured CSV output suitable for
direct consumption by the GridPilot analysis scripts.

Usage:
    python collect_telemetry.py --output telemetry.csv -- <your-program> [args...]

The wrapper requires the pynvml package (`pip install nvidia-ml-py`) and root
or `nvidia-cap-sys-admin` capability to access NVML telemetry. It runs the
target program as a subprocess and concurrently samples NVML and /proc/stat,
writing a row to the output CSV at every sampling tick.

When the target program exits, the wrapper records the exit code and waits
for any in-flight samples to flush, then exits with the target's exit code.
This makes it composable with other shell tools (bash, make, slurm).

The output schema is documented in HARDWARE_EXPERIMENT_SETUP.md and is the
input format expected by the experiment-1, experiment-2, and experiment-3
analysis scripts in this directory.
"""
import argparse
import csv
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import pynvml
    HAVE_NVML = True
except ImportError:
    HAVE_NVML = False
    print("WARNING: pynvml not installed; NVML telemetry will be skipped.",
          file=sys.stderr)


def sample_gpu(handles, t_start):
    """Return one row of GPU telemetry."""
    if not HAVE_NVML:
        return [time.time() - t_start] + [0] * (len(handles) * 3)
    row = [time.time() - t_start]
    for h in handles:
        try:
            p = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0  # mW -> W
            t = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            u = pynvml.nvmlDeviceGetUtilizationRates(h).gpu / 100.0
        except Exception:
            p, t, u = 0.0, 0.0, 0.0
        row.extend([p, t, u])
    return row


def sample_cpu_utilisation():
    """Read /proc/stat to compute the instantaneous CPU utilisation."""
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        parts = line.split()
        idle = int(parts[4])
        total = sum(int(p) for p in parts[1:8])
        return idle, total
    except Exception:
        return 0, 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="output CSV path")
    parser.add_argument("--gpu-rate-hz", type=int, default=1000,
                         help="GPU sampling rate (default 1000 = 1 kHz)")
    parser.add_argument("--cpu-rate-hz", type=int, default=100,
                         help="CPU sampling rate (default 100 = 100 Hz)")
    parser.add_argument("cmd", nargs=argparse.REMAINDER,
                         help="-- followed by the executable to run")
    args = parser.parse_args()

    if not args.cmd:
        parser.error("No command specified after --")
    if args.cmd[0] == "--":
        args.cmd = args.cmd[1:]

    # Initialise NVML
    if HAVE_NVML:
        pynvml.nvmlInit()
        n = pynvml.nvmlDeviceGetCount()
        handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(n)]
        print(f"Detected {n} GPUs via NVML")
    else:
        handles = []

    # Open the CSV output
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out = open(args.output, "w", newline="")
    writer = csv.writer(out)

    # Header row
    header = ["t_s", "cpu_util"]
    for i in range(len(handles)):
        header.extend([f"gpu{i}_power_w", f"gpu{i}_temp_c", f"gpu{i}_util"])
    writer.writerow(header)
    out.flush()

    t_start = time.time()
    stop_event = threading.Event()
    target_exit_code = [None]

    def telemetry_loop():
        """Background thread: sample NVML and CPU and write to CSV."""
        prev_idle, prev_total = sample_cpu_utilisation()
        gpu_dt = 1.0 / args.gpu_rate_hz
        cpu_period = max(args.gpu_rate_hz // args.cpu_rate_hz, 1)
        i = 0
        while not stop_event.is_set():
            tick_start = time.time()
            row = sample_gpu(handles, t_start)
            if i % cpu_period == 0:
                idle, total = sample_cpu_utilisation()
                d_idle = idle - prev_idle
                d_total = total - prev_total
                cpu_util = 1.0 - d_idle / max(d_total, 1)
                prev_idle, prev_total = idle, total
                last_cpu = cpu_util
            else:
                last_cpu = row[1] if len(row) > 1 else 0.0
            row.insert(1, last_cpu)
            writer.writerow(row)
            i += 1
            if i % 1000 == 0:
                out.flush()
            elapsed = time.time() - tick_start
            sleep_t = gpu_dt - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)

    # Start telemetry thread
    t = threading.Thread(target=telemetry_loop, daemon=True)
    t.start()

    # Run the target program
    print(f"Running: {' '.join(args.cmd)}")
    try:
        proc = subprocess.run(args.cmd)
        target_exit_code[0] = proc.returncode
    except KeyboardInterrupt:
        target_exit_code[0] = 130
    finally:
        stop_event.set()
        t.join(timeout=5)
        out.flush()
        out.close()
        if HAVE_NVML:
            pynvml.nvmlShutdown()

    print(f"Telemetry written to {args.output}")
    print(f"Target exit code: {target_exit_code[0]}")
    sys.exit(target_exit_code[0])


if __name__ == "__main__":
    main()
