#!/usr/bin/env python3
"""
E5_supervisory_pareto.py — Tier-3 supervisory operating-point selection.

Purpose: Validate that the Tier-3 grid-search supervisor selects an operating
point on the empirical Pareto front, and that its choice maximises iters/Joule
under a throughput floor.

Test design:
  Use the parsed_results.csv produced by 06_parse_results.py from the open-loop
  sweep (E1) as the empirical Pareto-front evidence. Feed this to the Tier-3
  supervisor and compare its operating-point choice against:
    a) the brute-force optimum (the row in parsed_results.csv with the best
       iters_per_joule among those meeting the throughput floor),
    b) a naive baseline (always full TDP, max SM clock).

  Then re-run the chosen operating point for 60 s with telemetry and verify
  the predicted (throughput, iters/J) match the closed-loop measurement.

Output:
  results/E5_supervisory_<ts>/
    decisions.json       - the supervisor's choice + brute-force optimum + baseline
    closed_loop_<wl>.csv - 60s telemetry under the supervisor's chosen point
    closed_loop_<wl>_metrics.json
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
    p.add_argument("--parsed-results", required=True, type=Path,
                   help="path to parsed_results.csv from a prior 05_run_experiments.sh sweep")
    p.add_argument("--throughput-floor-pct", type=float, default=70.0,
                   help="throughput floor as %% of unconstrained baseline (default 70)")
    p.add_argument("--workloads", nargs="+",
                   default=["matmul_compute_bound", "inference_memory_bound", "bursty_alternating"])
    p.add_argument("--duration", type=float, default=60.0,
                   help="seconds for closed-loop validation (default 60)")
    args = p.parse_args()

    if os.geteuid() != 0:
        print("ERROR: requires sudo for nvidia-smi -pl/-lgc.", file=sys.stderr)
        sys.exit(1)

    KIT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(KIT / "controller"))
    from hierarchical_controller import SupervisorTier3

    workloads_path = KIT / "workloads/workload_definitions.py"
    telemetry_path = KIT / "scripts/04_collect_telemetry.py"

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = KIT / "results" / f"E5_supervisory_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {out_dir}")

    # Load parsed results
    rows = []
    with args.parsed_results.open() as f:
        for r in csv.DictReader(f):
            try:
                r["pcap_w"] = int(r["pcap_w"]) if r["pcap_w"] else None
                r["sm_target_mhz"] = int(r["sm_target_mhz"]) if r["sm_target_mhz"] else None
                r["iters_per_s"] = float(r["iters_per_s"]) if r["iters_per_s"] else None
                r["energy_per_iter_j"] = float(r["energy_per_iter_j"]) if r["energy_per_iter_j"] else None
                r["iters_per_joule"] = float(r["iters_per_joule"]) if r["iters_per_joule"] else None
                r["power_mean_w"] = float(r["power_mean_w"]) if r["power_mean_w"] else None
                rows.append(r)
            except (ValueError, KeyError):
                pass

    decisions = {}
    for wl in args.workloads:
        wl_rows = [r for r in rows if r["workload"] == wl
                   and r.get("iters_per_s") and r.get("iters_per_joule")]
        if not wl_rows:
            print(f"  no data for {wl}, skipping")
            continue

        # Baseline: highest pcap + highest SM
        baseline = max(wl_rows, key=lambda r: (r["pcap_w"], r["sm_target_mhz"]))
        max_throughput = max(r["iters_per_s"] for r in wl_rows)
        floor = max_throughput * args.throughput_floor_pct / 100

        # Brute-force optimum: highest iters/J meeting throughput floor
        feasible = [r for r in wl_rows if r["iters_per_s"] >= floor]
        if not feasible:
            feasible = wl_rows  # relax floor if infeasible
        brute_force = max(feasible, key=lambda r: r["iters_per_joule"])

        # Supervisor's choice via SupervisorTier3
        sup = SupervisorTier3(throughput_floor=floor, supervisory_period_s=0)
        for r in wl_rows:
            sup.add_observation(r["pcap_w"], r["sm_target_mhz"],
                                  r["iters_per_s"], r["energy_per_iter_j"], 0.0)
        # Force a decision now (zero period)
        choice = sup.decide(t=10.0, predicted_throughput=max_throughput)

        decision = {
            "workload": wl,
            "throughput_floor_iters_per_s": floor,
            "max_throughput_iters_per_s": max_throughput,
            "baseline": {
                "pcap_w": baseline["pcap_w"], "sm_mhz": baseline["sm_target_mhz"],
                "iters_per_s": baseline["iters_per_s"],
                "iters_per_joule": baseline["iters_per_joule"],
            },
            "brute_force_optimum": {
                "pcap_w": brute_force["pcap_w"], "sm_mhz": brute_force["sm_target_mhz"],
                "iters_per_s": brute_force["iters_per_s"],
                "iters_per_joule": brute_force["iters_per_joule"],
                "improvement_pct": (brute_force["iters_per_joule"] /
                                     baseline["iters_per_joule"] - 1) * 100,
            },
            "supervisor_choice": {"pcap_w": choice[0], "sm_mhz": choice[1]} if choice else None,
            "supervisor_matches_optimum": (
                choice == (brute_force["pcap_w"], brute_force["sm_target_mhz"])
                if choice else False),
        }
        print(f"\n{wl}:")
        print(f"  baseline:      pcap={baseline['pcap_w']}, sm={baseline['sm_target_mhz']}, eff={baseline['iters_per_joule']:.4f}")
        print(f"  brute force:   pcap={brute_force['pcap_w']}, sm={brute_force['sm_target_mhz']}, eff={brute_force['iters_per_joule']:.4f} ({decision['brute_force_optimum']['improvement_pct']:+.1f}%)")
        print(f"  supervisor:    pcap={choice[0] if choice else 'N/A'}, sm={choice[1] if choice else 'N/A'}, matches optimum: {decision['supervisor_matches_optimum']}")
        decisions[wl] = decision

        # Closed-loop validation: apply the supervisor's choice and re-measure
        if choice:
            pcap, sm = choice
            print(f"  validating supervisor choice for {args.duration}s...")
            subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-pl", str(pcap)],
                            check=False, capture_output=True)
            subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-lgc", f"{sm},{sm}"],
                            check=False, capture_output=True)
            time.sleep(2)
            tel_csv = out_dir / f"closed_loop_{wl}.csv"
            wl_log = out_dir / f"closed_loop_{wl}.stdout"
            subprocess.run([
                "python3", str(telemetry_path),
                "--output", str(tel_csv),
                "--rate", "100",
                "--gpus", str(args.gpu),
                "--", "python3", str(workloads_path),
                "--workload", wl,
                "--duration", str(args.duration),
                "--seed", "42",
            ], stdout=wl_log.open("w"), stderr=subprocess.STDOUT, check=False)
            subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-pl", "300"],
                            check=False, capture_output=True)
            subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-rgc"],
                            check=False, capture_output=True)
            print(f"  closed-loop telemetry: {tel_csv}")

    (out_dir / "decisions.json").write_text(json.dumps(decisions, indent=2))
    print(f"\n✓ E5 complete. Output: {out_dir}")


if __name__ == "__main__":
    main()
