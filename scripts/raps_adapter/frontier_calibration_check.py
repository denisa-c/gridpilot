#!/usr/bin/env python3
"""
scripts/raps_adapter/frontier_calibration_check.py
===================================================

Cross-validation companion to ``m100_calibration_check.py``: reads
the ExaDigiT/RAPS Frontier config at
``gridpilot/raps/config/frontier.yaml`` and computes the gap between
the four-component PUE model calibrated to the published Frontier
PUE of 1.03 and the RAPS scalar ``cooling_efficiency``.

A Frontier match within ±2 % is the second large-scale anchor (after
M100) that the §3.6 paragraph cites.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.raps_adapter.m100_calibration_check import main as _check_main  # noqa: E402


def main(argv=None) -> int:
    # Reuse the M100 check with Frontier defaults
    default_argv = ["--system", "frontier", "--target-pue", "1.03"]
    if argv is None:
        argv = default_argv
    elif "--system" not in argv:
        argv = default_argv + list(argv)
    return _check_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
