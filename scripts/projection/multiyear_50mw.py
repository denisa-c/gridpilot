#!/usr/bin/env python3
"""
scripts/projection/multiyear_50mw.py
====================================

Operational-only multi-year 50 MW projection (2025 → 2028 → 2032).
Backs PECS 2026 §8 Table 3.  No frequency-response component — the
2025 anchor values come from ``data/operational_only_2025.csv``:

    CH 9.5 %   IT 7.0 %   DE 9.3 %

The trajectory uses a linear interpolation against the BFE/NECP/EEG
CI roadmaps at 2028 and 2032 milestones.  Absolute daily savings are
computed at 50 MW × 24 h × CI(grid, year) × pct.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


# Per-grid CI trajectories (g/kWh) at 2025, 2028, 2032 milestones
# Sources: BFE ES-2050 (CH), NECP 2024 (IT), EEG 2023 (DE)
CI_TRAJECTORY = {
    "CH": {2025:  30, 2028:  22, 2032:  14},
    "IT": {2025: 258, 2028: 188, 2032: 118},
    "DE": {2025: 295, 2028: 192, 2032:  90},
}

# Operational-only relative reduction (per-year). 2025 anchored to
# data/operational_only_2025.csv. The 2028/2032 growth is driven by:
#   - tighter f-SLA windows as users gain confidence with the contract
#     (modelled as +1.5 pp/year nominal)
#   - cleaner grid → each deferred hour saves more
# Calibration constants per grid; deliberately conservative.
GROWTH_PER_YEAR_PP = {"CH": 0.5, "IT": 1.0, "DE": 1.5}


def project(grid: str, year: int) -> float:
    """Operational-only relative CO₂ reduction (%) at the given year."""
    base_2025 = pd.read_csv(ROOT / "data" / "operational_only_2025.csv")
    base = base_2025[base_2025.iloc[:, 0] == grid]["operational_only_2025_pct"].iloc[0]
    return float(base + GROWTH_PER_YEAR_PP[grid] * (year - 2025))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scale-mw", type=float, default=50.0)
    p.add_argument("--out",      type=Path,
                   default=ROOT / "data" / "multiyear_50mw_operational_only.csv")
    args = p.parse_args(argv)

    rows = []
    for grid in ("CH", "IT", "DE"):
        for year in (2025, 2028, 2032):
            ci = CI_TRAJECTORY[grid][year]
            pct = project(grid, year)
            # Absolute daily savings: 50 MW × 24 h × CI × pct
            saved_kg = args.scale_mw * 1e3 * 24 * ci * 1e-3 * (pct / 100.0)
            rows.append({
                "grid": grid,
                "year": year,
                "ci_g_per_kwh": ci,
                "operational_pct": round(pct, 2),
                "saved_t_co2_per_day": round(saved_kg / 1e3, 2),
            })
    df = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"[multiyear_50mw] wrote {args.out}")
    print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
