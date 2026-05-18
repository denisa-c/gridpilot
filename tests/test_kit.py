"""
Tests for the GridPilot reproducibility kit.

Run with:
    python -m pytest tests/

These tests verify that the kit's core modules import cleanly, that the
cooling-PUE model reproduces its calibration target, and that the workload
traces have the expected schema.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def test_cooling_model_imports():
    from cooling.cooling_pue_model import (
        CoolingParams, calibrate_to_design_pue, compute_cooling_power_kw
    )
    assert CoolingParams is not None


def test_cooling_model_design_point():
    """The cooling model must reproduce the calibration target exactly."""
    from cooling.cooling_pue_model import calibrate_to_design_pue, compute_cooling_power_kw
    target = 1.20
    cool = calibrate_to_design_pue(target_pue=target, it_design_kw=1400.0)
    r = compute_cooling_power_kw(it_power_kw=1400.0, t_amb_c=25.0, params=cool)
    assert abs(r["pue_instantaneous"] - target) < 0.005, (
        f"Calibration error {r['pue_instantaneous']:.4f} vs target {target}"
    )


def test_cooling_model_load_dependence():
    """PUE should rise at low load due to fixed misc overhead."""
    from cooling.cooling_pue_model import calibrate_to_design_pue, compute_cooling_power_kw
    cool = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    pue_low = compute_cooling_power_kw(140.0, 25.0, cool)["pue_instantaneous"]
    pue_full = compute_cooling_power_kw(1400.0, 25.0, cool)["pue_instantaneous"]
    assert pue_low > pue_full, "PUE must rise at low IT load"


def test_cooling_free_cooling_ramp():
    """Free cooling fraction should be 1 at low ambient and 0 at high ambient."""
    from cooling.cooling_pue_model import calibrate_to_design_pue, compute_cooling_power_kw
    cool = calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    r_cold = compute_cooling_power_kw(1000.0, 5.0, cool)
    r_hot = compute_cooling_power_kw(1000.0, 30.0, cool)
    assert r_cold["free_cooling_fraction"] == 1.0
    assert r_hot["free_cooling_fraction"] == 0.0


def test_workload_traces_loadable():
    """All three workload traces must load and have the required columns."""
    import pandas as pd
    for name in ["m100_real_jobs", "philly_like", "acme_like"]:
        path = ROOT / "data" / "traces" / f"{name}.parquet"
        if not path.exists():
            pytest.skip(f"Trace {name} not present")
        df = pd.read_parquet(path)
        assert len(df) > 0
        assert "run_time" in df.columns or "submit_time" in df.columns


def test_raps_adapter_imports():
    """The RAPS configuration adapter must import without requiring RAPS itself."""
    from integration.raps_config_adapter import (
        load_raps_system_config, list_raps_systems, RAPSSystemConfig
    )
    assert RAPSSystemConfig is not None


def test_raps_adapter_handles_missing_path():
    """The adapter should raise a clear error when the RAPS clone is missing."""
    from integration.raps_config_adapter import load_raps_system_config
    with pytest.raises(FileNotFoundError):
        load_raps_system_config("/nonexistent/path/to/raps", "marconi100")


def test_results_csv_present_or_runnable():
    """At least one of the expected pre-computed result CSVs must be present,
    or the corresponding runner must exist.  Accepts the v1.0 layout
    (data/simulator_outputs/, scripts/simulator/) used by the released kit."""
    candidate_csvs = [
        ROOT / "data" / "simulator_outputs" / "icpp_full_matrix.csv",
        ROOT / "data" / "results" / "icpp_full_matrix.csv",            # legacy path
        ROOT / "data" / "table1_headline_savings.csv",                 # PECS Table 2 source
    ]
    candidate_runners = [
        ROOT / "scripts" / "simulator" / "run_full_matrix.py",
        ROOT / "scripts" / "m100" / "replay_all.py",
        ROOT / "experiments" / "run_full_matrix.py",                   # legacy path
    ]
    any_csv     = any(p.exists() for p in candidate_csvs)
    any_runner  = any(p.exists() for p in candidate_runners)
    assert any_csv or any_runner, (
        "Either a pre-computed results CSV must be present or a runner script "
        "must exist.  Looked for:\n"
        + "\n".join(f"  CSV   : {p}" for p in candidate_csvs)
        + "\n"
        + "\n".join(f"  runner: {p}" for p in candidate_runners)
    )


def test_paper_sources_present():
    """The paper LaTeX source and bibliography must be present.  Accepts the
    v1.0 layout, where the canonical filename is gridpilot_europar2026.tex,
    and falls back to the legacy paper/main.tex if present."""
    candidates_tex = [
        ROOT / "paper" / "gridpilot_europar2026.tex",
        ROOT / "paper" / "main.tex",
        ROOT.parent / "papers" / "pecs2026" / "main.tex",
        ROOT.parent / "papers" / "whpc2026" / "main.tex",
    ]
    candidates_bib = [
        ROOT / "paper" / "references.bib",
        ROOT.parent / "papers" / "pecs2026" / "references.bib",
        ROOT.parent / "papers" / "whpc2026" / "references.bib",
        ROOT.parent / "references.bib",
    ]
    assert any(p.exists() for p in candidates_tex), (
        "No paper LaTeX source found. Looked for:\n  "
        + "\n  ".join(str(p) for p in candidates_tex)
    )
    assert any(p.exists() for p in candidates_bib), (
        "No references.bib found. Looked for:\n  "
        + "\n  ".join(str(p) for p in candidates_bib)
    )


def test_license_present():
    """The MIT licence file must be present at the repository root."""
    license_path = ROOT / "LICENSE"
    assert license_path.exists()
    text = license_path.read_text()
    assert "MIT License" in text
