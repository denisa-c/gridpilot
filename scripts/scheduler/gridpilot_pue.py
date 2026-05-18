#!/usr/bin/env python3
"""
scripts/scheduler/gridpilot_pue.py
==================================

Thin CLI wrapper over ``src/scheduler/scheduler_pue_aware.py:replay_proact_opt_pue``.
Backs the Algorithm 2 reference in the PECS 2026 paper §4.

Run::

    python scripts/scheduler/gridpilot_pue.py --jobs <parquet> --ci <yaml>

Outputs the standard scheduler-result dict as JSON to stdout (or to
``--output`` if given).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from scheduler.scheduler_pue_aware import replay_proact_opt_pue  # noqa: E402
from cooling.cooling_pue_model import calibrate_to_design_pue   # noqa: E402

# Reuse the same loaders used by the f-SLA driver
sys.path.insert(0, str(ROOT / "scripts" / "m100"))
from inject_fsla_prior import load_jobs, load_ci, load_t_amb, load_pue_params  # noqa: E402


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="gridpilot_pue", description=__doc__)
    p.add_argument("--jobs", type=Path, required=True)
    p.add_argument("--ci", type=Path, required=True)
    p.add_argument("--t-amb", type=Path, default=None)
    p.add_argument("--pue", type=Path, default=None)
    p.add_argument("--max-delay-h", type=int, default=24)
    p.add_argument("--total-nodes", type=int, default=980)
    p.add_argument("--node-power-kw", type=float, default=1.5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=Path, default=None)
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    jobs = load_jobs(args.jobs)
    ci = load_ci(args.ci)
    t_amb = load_t_amb(args.t_amb, ci.index)
    cp = load_pue_params(args.pue)
    res = replay_proact_opt_pue(
        jobs, ci, t_amb,
        cooling_params=cp,
        max_delay_h=args.max_delay_h,
        total_nodes=args.total_nodes,
        node_power_kw=args.node_power_kw,
        seed=args.seed,
    )
    out = {
        "n":              int(res["n"]),
        "co2_g":          float(res["co2_g"]),
        "facility_co2_g": float(res["facility_co2_g"]),
        "energy_kwh":     float(res["energy_kwh"]),
        "p95_slowdown":   float(np.percentile(res["slowdowns"], 95)),
        "avg_pue":        float(res["avg_pue"]),
    }
    payload = json.dumps(out, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
