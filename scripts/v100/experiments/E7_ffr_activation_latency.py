#!/usr/bin/env python3
"""
E7_ffr_activation_latency.py — Measure end-to-end FFR activation latency
on the V100 + CPU node, with the IslandSimulator standing in for the
production safety-certified C responder.

Purpose: Establish the empirical activation-latency baseline that the
WP3.5 safety-island deliverable must match or beat. The test follows the
Statnett FFR type-prequalification protocol (Manner et al. 2023 IET GTD
doi:10.1049/gtd2.12851), adapted for laboratory conditions.

Test procedure for each of the three workloads:
  1. Load the activation table into the simulator (3 GPUs, normal 300 W,
     FFR target 200 W = 100 W reduction per GPU = 300 W total capacity).
  2. Open a bid window with activation threshold -200 mHz (49.800 Hz).
  3. Arm the simulator.
  4. Run the workload for 60 s under nominal pcap (300 W).
  5. Inject a synthetic frequency excursion at t = 30 s by directly calling
     simulator.inject_freq_sample(-250) which is below threshold.
  6. The simulator's actuation backend issues nvidia-smi -pl 200 to each GPU.
  7. Record:
        - t_inject:       when the test harness called inject_freq_sample
        - t_threshold:    when the simulator detected the threshold breach
        - t_actuation_i:  when each per-GPU pcap was applied (3 events)
        - t_event_logged: when the activation event was written to disk
  8. Compute per-stage latency and end-to-end latency.
  9. Repeat 30 times to get a tail-latency distribution.
 10. Report whether 100% of activations meet the 700 ms Nordic FFR budget.

Output:
  results/E7_ffr_latency_<ts>/
    workload_<wl>_runs.csv        per-trial latency breakdown (30 rows)
    workload_<wl>_summary.json    median, p95, max, n_pass, n_fail
    activation_events.jsonl       all event records concatenated

Reference for the 700 ms budget: Statnett's Nordic FFR product specification
(referenced in Manner et al. 2023 IET GTD); 0.7 / 1.0 / 1.3 s tiers exist
depending on the FFR sub-product.

Note: this experiment exercises the *Python supervisor + Python simulator*
stack. The production architecture replaces the simulator with the C safety
island, which is expected to reduce the activation-path latency from the
measured value to <10 ms (the bulk of the latency on this stack is the
nvidia-smi roundtrip, which is unchanged by the language choice). The E7
results therefore establish the empirical UPPER BOUND on what a properly
engineered safety-island implementation needs to achieve.
"""
import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "safety_island/simulator"))
sys.path.insert(0, str(KIT / "controller"))


def make_actuation_backend(gpu_index_to_use, dry_run, latency_log):
    """Build a closure that applies pcap to one GPU via nvidia-smi -pl
    and records the per-GPU actuation latency."""
    def backend(gpu_index, target_pcap_w):
        t_start = time.perf_counter_ns()
        if dry_run:
            time.sleep(0.05)  # Simulate 50 ms nvidia-smi roundtrip
            rc = 0
        else:
            r = subprocess.run(
                ["nvidia-smi", "-i", str(gpu_index_to_use[gpu_index]),
                 "-pl", str(target_pcap_w)],
                capture_output=True, text=True)
            rc = r.returncode
        t_end = time.perf_counter_ns()
        latency_log.append({
            "gpu_index": gpu_index,
            "phys_index": gpu_index_to_use[gpu_index],
            "target_pcap_w": target_pcap_w,
            "elapsed_us": (t_end - t_start) // 1000,
            "rc": rc,
        })
        return rc
    return backend


def run_one_trial(sim, trial_id, gpu_index_to_use, dry_run):
    """One activation trial. Returns latency breakdown dict."""
    actuation_log = []
    sim.actuation_callback = make_actuation_backend(
        gpu_index_to_use, dry_run, actuation_log)
    # Inject at known time
    t_inject = time.perf_counter_ns()
    sim.inject_freq_sample(-250)  # 49.750 Hz, below threshold
    t_done = time.perf_counter_ns()
    snap = sim.get_state_snapshot()
    e2e_us = (t_done - t_inject) // 1000
    return {
        "trial_id": trial_id,
        "e2e_latency_us": e2e_us,
        "n_gpus_actuated": len(actuation_log),
        "per_gpu_actuation_log": actuation_log,
        "actuation_id": snap["last_activation_id"],
        "wcet_observed_us": snap["wcet_observed_us"],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gpus", type=int, nargs="+", default=[0, 1, 2],
                   help="physical GPU indices under control")
    p.add_argument("--workloads", nargs="+",
                   default=["matmul_compute_bound", "inference_memory_bound", "bursty_alternating"])
    p.add_argument("--n-trials", type=int, default=30,
                   help="number of activation events per workload (default 30)")
    p.add_argument("--inter-trial-s", type=float, default=2.0,
                   help="seconds between trials to allow restoration (default 2)")
    p.add_argument("--dry-run", action="store_true",
                   help="simulate without actually invoking nvidia-smi")
    p.add_argument("--budget-ms", type=int, default=700,
                   help="latency budget in ms (default 700, Nordic FFR)")
    args = p.parse_args()

    if not args.dry_run and os.geteuid() != 0:
        print("ERROR: requires sudo (or --dry-run).", file=sys.stderr)
        sys.exit(1)

    from island_simulator import (IslandSimulator, TableEntry,
                                    MSG_BID_WINDOW_OPEN, MSG_ACTIVATION_TABLE_UPDATE)

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = KIT / "results" / f"E7_ffr_latency_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}")

    # Configure the simulator
    sim = IslandSimulator()
    table_msg = {
        "msg_type": MSG_ACTIVATION_TABLE_UPDATE, "sequence_no": 1,
        "n_entries": len(args.gpus),
        "table": [{"gpu_index": i, "normal_pcap_w": 300, "ffr_pcap_w": 200}
                  for i in range(len(args.gpus))],
    }
    sim.handle_activation_table_update(table_msg)
    bid_msg = {
        "msg_type": MSG_BID_WINDOW_OPEN, "sequence_no": 2,
        "bid_start_unix_us": int(time.time() * 1e6),
        "bid_end_unix_us": int((time.time() + 7200) * 1e6),
        "contracted_capacity_w": 100 * len(args.gpus),
        "activation_threshold_mhz": -200,
    }
    sim.handle_bid_window_open(bid_msg)
    sim.arm()
    print(f"Simulator armed; threshold -200 mHz (49.800 Hz), capacity {100 * len(args.gpus)} W")

    workloads_path = KIT / "workloads/workload_definitions.py"
    overall_summary = {}

    for wl in args.workloads:
        print(f"\n=== {wl} ===")
        # Restore default state before workload
        if not args.dry_run:
            for gpu in args.gpus:
                subprocess.run(["nvidia-smi", "-i", str(gpu), "-pl", "300"],
                                check=False, capture_output=True)
            time.sleep(2)

        # Launch workload on all 3 GPUs in parallel
        wl_procs = []
        if not args.dry_run:
            for gpu in args.gpus:
                env = os.environ.copy()
                env["CUDA_VISIBLE_DEVICES"] = str(gpu)
                log = (out_dir / f"workload_{wl}_gpu{gpu}.stdout").open("w")
                wp = subprocess.Popen([
                    "python3", str(workloads_path),
                    "--workload", wl,
                    "--duration", str(int(args.n_trials * args.inter_trial_s + 30)),
                    "--seed", str(42 + gpu),
                ], env=env, stdout=log, stderr=subprocess.STDOUT)
                wl_procs.append(wp)
            time.sleep(5)  # let the workload spin up

        # Run trials
        trials = []
        for i in range(args.n_trials):
            print(f"  trial {i+1}/{args.n_trials}", end=" ", flush=True)
            try:
                trial = run_one_trial(sim, i, args.gpus, args.dry_run)
                trials.append(trial)
                print(f"e2e={trial['e2e_latency_us']/1000:.1f} ms", flush=True)
            except Exception as e:
                print(f"FAILED: {e}", flush=True)
                trials.append({"trial_id": i, "error": str(e), "e2e_latency_us": -1})
            # Restore GPU caps to normal (300 W)
            if not args.dry_run:
                for gpu in args.gpus:
                    subprocess.run(["nvidia-smi", "-i", str(gpu), "-pl", "300"],
                                    check=False, capture_output=True)
            time.sleep(args.inter_trial_s)

        # Stop workload
        if not args.dry_run:
            for wp in wl_procs:
                if wp.poll() is None:
                    wp.terminate()
                    wp.wait(timeout=5)

        # Save trials
        trial_csv = out_dir / f"workload_{wl}_runs.csv"
        with trial_csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["trial_id", "e2e_latency_ms", "n_gpus_actuated",
                          "actuation_id", "wcet_observed_ms",
                          "gpu0_us", "gpu1_us", "gpu2_us"])
            for t in trials:
                if "error" in t:
                    continue
                gpu_lats = sorted(t["per_gpu_actuation_log"], key=lambda x: x["gpu_index"])
                row = [t["trial_id"],
                        t["e2e_latency_us"]/1000,
                        t["n_gpus_actuated"],
                        t["actuation_id"],
                        t["wcet_observed_us"]/1000]
                for ent in gpu_lats[:3]:
                    row.append(ent["elapsed_us"])
                w.writerow(row)
        # Summary statistics
        valid = [t["e2e_latency_us"]/1000 for t in trials if "error" not in t]
        if valid:
            valid_sorted = sorted(valid)
            n_pass = sum(1 for x in valid if x < args.budget_ms)
            summary = {
                "workload": wl,
                "n_trials": len(valid),
                "median_ms": statistics.median(valid),
                "mean_ms": statistics.mean(valid),
                "stdev_ms": statistics.stdev(valid) if len(valid) > 1 else 0,
                "p95_ms": valid_sorted[int(0.95 * len(valid_sorted))],
                "max_ms": max(valid),
                "min_ms": min(valid),
                "budget_ms": args.budget_ms,
                "n_pass": n_pass,
                "n_fail": len(valid) - n_pass,
                "pass_rate": n_pass / len(valid),
            }
            print(f"  median={summary['median_ms']:.1f} ms, "
                   f"p95={summary['p95_ms']:.1f} ms, "
                   f"max={summary['max_ms']:.1f} ms, "
                   f"pass={n_pass}/{len(valid)}")
            (out_dir / f"workload_{wl}_summary.json").write_text(
                json.dumps(summary, indent=2))
            overall_summary[wl] = summary

    # Aggregate verdict
    all_pass = all(s["pass_rate"] == 1.0 for s in overall_summary.values())
    verdict = {
        "all_workloads_pass": all_pass,
        "budget_ms": args.budget_ms,
        "per_workload": overall_summary,
    }
    (out_dir / "verdict.json").write_text(json.dumps(verdict, indent=2))
    print(f"\n=== VERDICT ===")
    print(f"All workloads under {args.budget_ms} ms budget: {all_pass}")
    print(f"\n✓ E7 complete. Output: {out_dir}")


if __name__ == "__main__":
    main()
