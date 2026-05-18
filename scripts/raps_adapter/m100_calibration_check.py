#!/usr/bin/env python3
"""
scripts/raps_adapter/m100_calibration_check.py
==============================================

Reproduces the §3.6 PECS-paper finding: the four-component PUE model
calibrated to the published M100 design PUE of 1.20 predicts a
design-point facility power that is ~12 % above the RAPS scalar
``cooling_efficiency`` abstraction (0.945 → PUE 1.058).  That 12 %
is exactly the chiller / pumps / air-side overhead the constant-
coefficient RAPS scalar collapses, and it is the structural twin of
the IT-vs-facility gap reported in §7 Finding 2.

Reads the actual ExaDigiT/RAPS canonical configuration at
``gridpilot/raps/config/marconi100.yaml`` rather than hard-coding the
M100 design parameters.  Run from any directory:

    PYTHONPATH=src python3 scripts/raps_adapter/m100_calibration_check.py

The default ``--raps-repo`` is ``gridpilot/raps`` (one level under
this script's grandparent), matching the v1.0 release layout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cooling.cooling_pue_model import calibrate_to_design_pue, compute_cooling_power_kw  # noqa: E402
from integration.raps_config_adapter import load_raps_system_config                       # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raps-repo", type=Path, default=ROOT / "raps",
                   help="Path to the ExaDigiT/RAPS repo (default: gridpilot/raps).")
    p.add_argument("--system", type=str, default="marconi100",
                   help="System name (matches raps/config/<system>.yaml; "
                        "default: marconi100).")
    p.add_argument("--target-pue", type=float, default=1.20,
                   help="Paper-anchor design PUE (default 1.20 for M100).")
    args = p.parse_args(argv)

    raps = load_raps_system_config(args.raps_repo, args.system)
    it_kw_design = raps.total_design_power_kw
    raps_cool_eff = raps.cooling_efficiency
    raps_pue_implied = raps.implied_design_pue           # = 1 / cooling_efficiency
    raps_facility_kw = it_kw_design * raps_pue_implied

    cp = calibrate_to_design_pue(target_pue=args.target_pue,
                                  it_design_kw=it_kw_design)
    res = compute_cooling_power_kw(it_kw_design, 25.0, cp)
    model_pue = res["pue_instantaneous"]
    model_facility_kw = it_kw_design * model_pue

    gap_pct = 100.0 * (model_facility_kw - raps_facility_kw) / raps_facility_kw

    out = {
        "system":             args.system,
        "raps_config_file":   str((args.raps_repo / "config" / f"{args.system}.yaml").resolve()),
        "num_cdus":           raps.num_cdus,
        "racks_per_cdu":      raps.racks_per_cdu,
        "nodes_per_rack":     raps.nodes_per_rack,
        "total_nodes":        raps.total_nodes,
        "gpus_per_node":      raps.gpus_per_node,
        "cpus_per_node":      raps.cpus_per_node,
        "node_power_max_kw":  round(raps.node_power_max_w / 1000, 3),
        "it_design_kw":       round(it_kw_design, 1),
        "raps_cooling_eff":   raps_cool_eff,
        "raps_pue_implied":   round(raps_pue_implied, 4),
        "raps_facility_kw":   round(raps_facility_kw, 1),
        "paper_anchor_pue":   args.target_pue,
        "calibrated_pue":     round(model_pue, 4),
        "model_facility_kw":  round(model_facility_kw, 1),
        "gap_pct_vs_raps":    round(gap_pct, 2),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
