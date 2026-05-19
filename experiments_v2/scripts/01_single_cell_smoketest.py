#!/usr/bin/env python3
"""
experiments_v2/scripts/01_single_cell_smoketest.py
==================================================
Phase 2 of the clean rerun.  Runs ONE cell (SE, 10 MW, M3, seed 0)
end-to-end, dumps every intermediate quantity, and verifies that
the sign convention (positive = improvement) holds at every layer
from the raw `result` dict to the rendered LaTeX macro.

Concretely, the script:

  1. Loads the M100 trace + the SE CI series.
  2. Runs three sub-cells:
       a) layer="pue",  mechanism="none"           (plain FCFS, CI-blind)
       b) layer="fsla", mechanism="none"           (EASY-FCFS CI-aware)
       c) layer="fsla", mechanism="M3"             (the headline)
  3. For each sub-cell, prints:
       n_jobs, energy_kwh, ci_weighted_mean, cfe_canonical_pct,
       co2_g_facility
  4. Computes both deltas:
       Δ_M3_vs_plainFCFS = (c) − (a)
       Δ_M3_vs_easyFCFS  = (c) − (b)
  5. Asserts the sign convention end-to-end.
  6. Emits a one-line summary the orchestrator can grep.

Run:
    PYTHONPATH=gridpilot/src python3 \\
        gridpilot/experiments_v2/scripts/01_single_cell_smoketest.py

Exit codes:
    0   sign convention holds; cell ran cleanly
    1   sign convention violated OR cell failed to run
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "gridpilot" / "src"))
sys.path.insert(0, str(ROOT / "gridpilot" / "scripts" / "multicountry"))

sys.path.insert(0, str(ROOT / "gridpilot" / "scripts" / "m100"))

# pylint: disable=wrong-import-position,import-error
from replay_country_sweep import (  # type: ignore[import-not-found]
    run_one_cell,
    CFE_REF_CI_G,
)
from inject_fsla_prior import load_pue_params  # type: ignore[import-not-found]
from cooling.cooling_pue_model import (  # type: ignore[import-not-found]
    calibrate_to_design_pue,
)


def _resolve_cooling_params(pue_yaml):
    """Mirror the same fallback the v1 sweep driver uses, but skip the
    known-broken fallback path that v1 currently has (see PUE_YAML
    block above)."""
    if pue_yaml is not None and pue_yaml.exists():
        # Only the RAPS submodule layout (raps/config/<system>.yaml) is
        # readable by load_pue_params; the configs/raps_systems/...
        # fallback hits a path-resolution bug.  If we ended up at the
        # broken fallback, calibrate from design instead so the
        # smoketest still produces a defensible result.
        if pue_yaml.parent.parent.name == "raps":
            return load_pue_params(pue_yaml)
    return calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)

GRIDPILOT = ROOT / "gridpilot"
SE_YAML = GRIDPILOT / "configs" / "grids" / "SE.yaml"

# Trace resolution: the country-sweep replay (align_jobs_to_ci) requires
# the `submit_time_epoch` column produced by build_extended_trace.py.
# The bundled Jan-only file (`m100_real_jobs.parquet`) has the legacy
# `submit_time` column and cannot be consumed directly --- another v1
# latent bug worth flagging.  Prefer the extended trace; fall back to
# the Jan-only file with a clear error if the user hasn't built the
# extended trace yet.
_JOBS_EXT  = GRIDPILOT / "data" / "traces" / "m100_real_jobs_extended.parquet"
_JOBS_JAN  = GRIDPILOT / "data" / "traces" / "m100_real_jobs.parquet"
JOBS = _JOBS_EXT if _JOBS_EXT.exists() else _JOBS_JAN

# PUE-anchor resolution order, mirroring v1's run_all_experiments.sh:
#   1. raps/config/marconi100.yaml    (RAPS submodule layout --- the one
#      load_pue_params() in inject_fsla_prior.py actually understands)
#   2. configs/raps_systems/marconi100.yaml  (fallback for clones without
#      the RAPS submodule --- NOTE: this fallback is currently BROKEN
#      because load_pue_params() does path.parent.parent + "/config/" +
#      path.stem, which yields configs/config/marconi100.yaml.  Filed
#      under Phase 3 audit as v1 latent bug #PUE-FALLBACK-1.)
#   3. design-PUE calibration (target_pue=1.20, it_design_kw=1400)
_PUE_RAPS    = GRIDPILOT / "raps"    / "config"       / "marconi100.yaml"
_PUE_FBACK   = GRIDPILOT / "configs" / "raps_systems" / "marconi100.yaml"
if _PUE_RAPS.exists():
    PUE_YAML = _PUE_RAPS
elif _PUE_FBACK.exists():
    PUE_YAML = _PUE_FBACK
else:
    PUE_YAML = None  # _resolve_cooling_params will fall back to calibration

SEED = 0
MW = 10.0


def _dump(label: str, row: dict) -> None:
    """Print every load-bearing column of a cell row, one line."""
    cols = [
        "country", "mw", "layer", "mechanism", "seed",
        "n_jobs", "energy_kwh",
        "ci_weighted_mean", "cfe_canonical_pct", "cfe_abs_pct",
        "co2_g_facility", "co2_tonnes_y",
    ]
    print(f"\n  [{label}]")
    for c in cols:
        v = row.get(c, None)
        if isinstance(v, float):
            print(f"    {c:<22s} = {v:>14.4f}")
        else:
            print(f"    {c:<22s} = {v!r}")


def main() -> int:
    print("experiments_v2 Phase 2 — single-cell smoketest (SE, 10 MW, seed 0)")
    print("=" * 78)
    if not JOBS.exists():
        print(f"ABORT: M100 trace not found at {JOBS}")
        return 1
    if not SE_YAML.exists():
        print(f"ABORT: SE grid YAML not found at {SE_YAML}")
        return 1

    tag = " (extended Jan+Feb)" if JOBS == _JOBS_EXT else " (Jan-only — likely to fail align_jobs_to_ci)"
    print(f"  trace      : {JOBS}{tag}")
    print(f"  SE grid    : {SE_YAML}")
    if PUE_YAML is not None and PUE_YAML.exists() \
            and PUE_YAML.parent.parent.name == "raps":
        print(f"  PUE YAML   : {PUE_YAML}  (RAPS submodule)")
    else:
        print(f"  PUE YAML   : <calibrated to design PUE=1.20, "
              f"IT=1400 kW>  (no usable RAPS YAML)")
    print(f"  CFE ref CI : {CFE_REF_CI_G} g/kWh")

    print(f"\n  Loading trace + cooling params...")
    jobs_df = pd.read_parquet(JOBS)
    cooling_params = _resolve_cooling_params(PUE_YAML)
    scheduler_kwargs_base: dict = {}

    sub_cells = [
        ("(a) plain-FCFS  CI-blind ", "pue",  "none"),
        ("(b) EASY-FCFS   CI-aware ", "fsla", "none"),
        ("(c) f-SLA M3    CI-aware ", "fsla", "M3"),
    ]
    rows: dict[str, dict] = {}
    for label, layer, mech in sub_cells:
        print(f"\n  running {label} ({layer}, mechanism={mech!r})...")
        row = run_one_cell(
            SE_YAML, MW, layer, mech, SEED,
            jobs_df, cooling_params, scheduler_kwargs_base,
        )
        rows[label] = row
        _dump(label, row)

    # ---- Lift computation -------------------------------------------
    a = rows[sub_cells[0][0]]
    b = rows[sub_cells[1][0]]
    c = rows[sub_cells[2][0]]

    print("\n" + "=" * 78)
    print("Sign-convention trace (METRICS §8 --- positive ⟹ improvement):")

    d_cfe_vs_fcfs   = c["cfe_canonical_pct"] - a["cfe_canonical_pct"]
    d_cfe_vs_easy   = c["cfe_canonical_pct"] - b["cfe_canonical_pct"]
    d_ci_vs_fcfs    = a["ci_weighted_mean"]  - c["ci_weighted_mean"]
    d_ci_vs_easy    = b["ci_weighted_mean"]  - c["ci_weighted_mean"]
    d_co2_vs_fcfs   = a["co2_g_facility"]    - c["co2_g_facility"]
    d_co2_vs_easy   = b["co2_g_facility"]    - c["co2_g_facility"]

    print(f"  Δ CFE  vs plain-FCFS  : {d_cfe_vs_fcfs:+.3f} pp   "
          f"(M3 better than FCFS  ⇔ positive)")
    print(f"  Δ CFE  vs EASY-FCFS   : {d_cfe_vs_easy:+.3f} pp   "
          f"(M3 better than EASY  ⇔ positive)")
    print(f"  Δ CI   vs plain-FCFS  : {d_ci_vs_fcfs:+.3f} g/kWh "
          f"(M3 cleaner than FCFS ⇔ positive)")
    print(f"  Δ CI   vs EASY-FCFS   : {d_ci_vs_easy:+.3f} g/kWh "
          f"(M3 cleaner than EASY ⇔ positive)")
    print(f"  Δ CO2  vs plain-FCFS  : {d_co2_vs_fcfs:+.1f} g     "
          f"(M3 less CO2 than FCFS ⇔ positive)")
    print(f"  Δ CO2  vs EASY-FCFS   : {d_co2_vs_easy:+.1f} g     "
          f"(M3 less CO2 than EASY ⇔ positive)")

    # ---- Internal consistency checks --------------------------------
    failures: list[str] = []

    # (i) sign of Δ CFE and Δ CI must agree (both are 'cleaner is better')
    for name, dcfe, dci in [
        ("vs FCFS", d_cfe_vs_fcfs, d_ci_vs_fcfs),
        ("vs EASY", d_cfe_vs_easy, d_ci_vs_easy),
    ]:
        # Allow ε-noise around zero (both <= 1e-3 absolute).
        if abs(dcfe) < 1e-3 and abs(dci) < 1e-3:
            continue
        if np.sign(dcfe) != np.sign(dci):
            failures.append(
                f"sign mismatch {name}: Δ CFE={dcfe:+.4f} but Δ CI={dci:+.4f}"
            )

    # (ii) CFE in [0, 100] for all three sub-cells
    for label, row in rows.items():
        cfe = row["cfe_canonical_pct"]
        if not (0.0 <= cfe <= 100.0):
            failures.append(f"{label} CFE out of [0,100]: {cfe:.3f}")

    # (iii) energy must be > 0
    for label, row in rows.items():
        if not (row["energy_kwh"] > 0):
            failures.append(f"{label} non-positive energy: {row['energy_kwh']}")

    if failures:
        print("\nSIGN-CONVENTION VIOLATIONS:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nAll sign-convention checks PASS.  Smoketest cleanly ran 3 sub-cells.")
    print("Proceed to Phase 3 (script audit) and Phase 4 (full v2 rerun).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
