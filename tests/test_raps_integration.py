"""
tests/test_raps_integration.py
==============================

Verifies that the released ExaDigiT/RAPS canonical YAMLs at
``gridpilot/raps/config/`` are correctly consumed by the GridPilot
calibration code.

Run::

    PYTHONPATH=src pytest tests/test_raps_integration.py -v

The tests are skipped (not failed) if the RAPS repo is not bundled
in the release — this lets the rest of the test suite still run on a
slim deployment.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAPS_REPO = ROOT / "raps"
RAPS_CFG_DIR = RAPS_REPO / "config"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

raps_available = pytest.mark.skipif(
    not RAPS_CFG_DIR.exists(),
    reason=f"RAPS repo not bundled at {RAPS_REPO}",
)


@raps_available
def test_marconi100_yaml_loads_with_expected_geometry():
    """The bundled Marconi100 YAML must parse cleanly and report the
    canonical 49 CDUs × 1 rack × 20 nodes = 980 nodes."""
    from integration.raps_config_adapter import load_raps_system_config
    cfg = load_raps_system_config(RAPS_REPO, "marconi100")
    assert cfg.num_cdus == 49
    assert cfg.racks_per_cdu == 1
    assert cfg.nodes_per_rack == 20
    assert cfg.total_nodes == 980
    assert cfg.gpus_per_node == 4
    assert cfg.cpus_per_node == 2
    # cooling_efficiency in the released YAML must round-trip exactly
    assert cfg.cooling_efficiency == pytest.approx(0.945, rel=1e-6)


@raps_available
def test_marconi100_it_design_power_matches_paper_anchor():
    """Per-node × node count must give an IT design within ±5 % of the
    paper-anchor 1807.4 kW used in §3.6 of the f-SLA paper."""
    from integration.raps_config_adapter import load_raps_system_config
    cfg = load_raps_system_config(RAPS_REPO, "marconi100")
    # Expected: 4×300 + 2×252 + 74.26 + 21 + 45 = 1844.26 W/node × 980 = 1807.4 kW
    expected_node_kw = (
        4 * 300 + 2 * 252 + 74.26 + 21 + 45
    ) / 1000.0
    assert cfg.node_power_max_w / 1000 == pytest.approx(expected_node_kw, rel=1e-3)
    assert cfg.total_design_power_kw == pytest.approx(1807.4, rel=0.05)


@raps_available
def test_frontier_yaml_loads_with_missing_rack_geometry():
    """Frontier has 25 CDUs × 3 racks × 128 nodes but missing rack 41.
    raps_config_adapter does not currently apply the missing-rack
    deduction (that's a system_config concern, not a power concern),
    so total_nodes is the gross figure 9 600."""
    from integration.raps_config_adapter import load_raps_system_config
    cfg = load_raps_system_config(RAPS_REPO, "frontier")
    assert cfg.num_cdus == 25
    assert cfg.racks_per_cdu == 3
    assert cfg.nodes_per_rack == 128
    assert cfg.total_nodes == 25 * 3 * 128  # 9 600
    assert cfg.gpus_per_node == 4           # 4 MI250X per Frontier node


@raps_available
def test_load_pue_params_falls_back_to_bundled_raps_yaml():
    """A non-existent --pue path with a canonical basename must
    transparently resolve to raps/config/<basename>."""
    sys.path.insert(0, str(ROOT / "scripts" / "m100"))
    from inject_fsla_prior import load_pue_params, _resolve_pue_path

    stale = Path("does-not-exist/marconi100.yaml")
    resolved = _resolve_pue_path(stale)
    assert resolved == RAPS_CFG_DIR / "marconi100.yaml"
    # End-to-end: load_pue_params must succeed on the stale path
    cp = load_pue_params(stale)
    # CoolingParams dataclass must round-trip the M100 design point
    from cooling.cooling_pue_model import compute_cooling_power_kw
    res = compute_cooling_power_kw(1807.4, 25.0, cp)
    assert abs(res["pue_instantaneous"] - 1.20) < 0.01


@raps_available
def test_load_pue_params_raises_with_actionable_message():
    """A truly bogus --pue path must raise FileNotFoundError naming
    both the literal and the bundled-fallback paths plus the
    canonical hint."""
    sys.path.insert(0, str(ROOT / "scripts" / "m100"))
    from inject_fsla_prior import _resolve_pue_path

    bogus = Path("definitely-not-a-system.yaml")
    with pytest.raises(FileNotFoundError) as exc:
        _resolve_pue_path(bogus)
    msg = str(exc.value)
    assert "literal:" in msg
    assert "bundled:" in msg
    assert "raps/config/marconi100.yaml" in msg   # the actionable hint


@raps_available
def test_m100_calibration_check_subprocess_succeeds():
    """The m100_calibration_check CLI must run cleanly and emit JSON
    with the expected keys."""
    script = ROOT / "scripts" / "raps_adapter" / "m100_calibration_check.py"
    env = {"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"}
    # Inherit interpreter environment for venv
    import os
    env_full = {**os.environ, **env}
    r = subprocess.run(
        [sys.executable, str(script), "--raps-repo", str(RAPS_REPO)],
        capture_output=True, text=True, timeout=30, env=env_full,
    )
    assert r.returncode == 0, f"stderr:\n{r.stderr}\nstdout:\n{r.stdout}"
    out = json.loads(r.stdout)
    for key in ("system", "total_nodes", "it_design_kw",
                "raps_cooling_eff", "calibrated_pue",
                "model_facility_kw", "gap_pct_vs_raps"):
        assert key in out
    assert out["system"] == "marconi100"
    assert out["total_nodes"] == 980
    # The 12 % structural gap should be present (allow a wide band so
    # the test is robust to small calibration adjustments)
    assert 5.0 < abs(out["gap_pct_vs_raps"]) < 25.0
