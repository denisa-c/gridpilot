#!/usr/bin/env python3
"""
scripts/pue_model/cooling_decomposition.py
==========================================

Re-export shim for the four-component cooling decomposition.  Backs the
PUE-model script reference in PECS 2026 §3.

Usage as a CLI::

    python scripts/pue_model/cooling_decomposition.py \\
        --it-load-kw 1400 --t-amb 25 --target-pue 1.20

Prints chiller / pumps / air / misc breakdown and the instantaneous PUE.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# Re-export the underlying API
from cooling.cooling_pue_model import (                # noqa: F401, E402
    CoolingParams,
    compute_cooling_power_kw,
    calibrate_to_design_pue,
)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--it-load-kw", type=float, required=True,
                   help="IT load in kW.")
    p.add_argument("--t-amb", type=float, default=25.0,
                   help="Ambient temperature in °C (default 25).")
    p.add_argument("--target-pue", type=float, default=1.20,
                   help="Calibration target PUE (default 1.20 = M100).")
    p.add_argument("--it-design-kw", type=float, default=1400.0,
                   help="IT design power for calibration (default 1400 kW).")
    args = p.parse_args(argv)
    cp = calibrate_to_design_pue(target_pue=args.target_pue,
                                  it_design_kw=args.it_design_kw)
    out = compute_cooling_power_kw(args.it_load_kw, args.t_amb, cp)
    print(json.dumps(out, indent=2, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
