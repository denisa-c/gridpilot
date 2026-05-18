"""Failure-mode tests for the cascade controller.

These tests exercise three adversarial conditions identified in the
critical review:
    1. FFR signal arriving during a thermal-envelope activation
    2. AR(4) predictor cold-start with insufficient history
    3. Tier-3 grid search returning no feasible operating point
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pytest


def test_thermal_envelope_overrides_ffr():
    """When GPU temperature exceeds 85°C, the safety derate must take precedence
    over the FFR target, regardless of how aggressive the FFR signal is."""
    from controller.multiscale import GPUDVFSController, GPUDVFSParams
    p = GPUDVFSParams()
    ctrl = GPUDVFSController(p)
    # Aggressive upward FFR target (asking for max power)
    p_target = p.p_max_w
    p_actual = 500.0
    # GPU is at 92°C: 7°C over the 85°C envelope
    out = ctrl.step(p_target, p_actual, t_gpu_c=92.0)
    assert out["safety_active"] is True, "Safety envelope should be active"
    # The cap should be derated, not at p_max_w
    assert out["p_cap_w"] < p.p_max_w, \
        f"Expected derated cap, got {out['p_cap_w']}"
    # Specifically: derate factor at 92°C is max(0.5, 1 - 7*0.02) = 0.86,
    # so the *target* used for PID is 0.86 * 700 = 602 W. The cap should
    # be below the un-derated target.
    assert out["p_cap_w"] < p.p_max_w * 0.95


def test_ar_predictor_cold_start_returns_current_value():
    """With insufficient history (less than ar_order+1 samples), the AR(4)
    predictor should fall back to returning the current value rather than
    extrapolating an unstable polynomial."""
    from controller.multiscale import HostPredictiveCoordinator
    coord = HostPredictiveCoordinator()
    # First sample: no history
    pred = coord.predict_util(0.5)
    assert 0.0 <= pred <= 1.0, "Cold-start prediction must be in [0,1]"
    assert abs(pred - 0.5) < 0.01, "Cold-start should fall back to current value"
    # After 4 samples: still at the boundary, should not crash
    for u in [0.5, 0.6, 0.7, 0.8]:
        pred = coord.predict_util(u)
        assert 0.0 <= pred <= 1.0


def test_tier3_optimiser_always_returns_best_found():
    """Even if the search grid produces only suboptimal points, the optimiser
    must return the best one rather than failing or returning None."""
    from controller.multiscale import ClusterMultiscaleOptimiser, ClusterOptimiserParams
    p = ClusterOptimiserParams(n_hosts=1)  # tiny cluster: limited headroom
    opt = ClusterMultiscaleOptimiser(p)
    # Run with extreme inputs
    result = opt.select_operating_point(
        ci_g_per_kwh=999.0,        # absurdly high CI
        green_pct=0.0,             # no renewables
        ffr_signal_amplitude=999.0  # absurdly high FFR demand
    )
    selected = result["selected"]
    assert selected is not None
    assert "objective" in selected
    # The optimiser should still produce a valid 2D point in the search grid
    assert 0.0 <= selected["mean_frac"] <= 1.0
    assert 0.0 <= selected["ffr_band_frac"] <= 1.0


def test_entsoe_connector_handles_unknown_service():
    """Requesting an unavailable service for a country must return a valid
    empty result, not raise."""
    from datetime import datetime
    from integration.entsoe_connector import (
        ENTSOEConnector, load_country_config
    )
    cfg = load_country_config("CH")
    conn = ENTSOEConnector()
    # Switzerland does not provide RR
    result = conn.fetch_ancillary(
        country="CH", service="RR",
        start=datetime(2025, 7, 1, 0, 0),
        end=datetime(2025, 7, 1, 6, 0),
        country_config=cfg,
    )
    # Should return an empty result, not crash
    assert result.source == "not_available"
    assert all(c == 0.0 for c in result.capacity_mw)


def test_cascade_handles_zero_committed_capacity():
    """A sub-threshold cluster (no services active) must still allow the
    parametrisable controller to be constructed and stepped without error."""
    from controller.parametrisable import ParametrisableMultiscaleController
    from integration.entsoe_connector import ENTSOEConnector
    conn = ENTSOEConnector()
    # 0.1 MW Swiss cluster: too small for any service participation
    ctrl = ParametrisableMultiscaleController(
        country="CH", cluster_capacity_mw=0.1,
        n_hosts=1, gpus_per_host=8, connector=conn,
    )
    meta = ctrl.metadata
    assert meta["total_committed_mw"] == 0.0
    # The controller should still step without crashing
    gpu_p = np.full(8, 300.0)
    gpu_t = np.full(8, 65.0)
    out = ctrl.step(t_s=0.0, ci_g_per_kwh=30.0, green_pct=70.0,
                     current_util=0.5, gpu_actual_powers_w=gpu_p,
                     gpu_temps_c=gpu_t)
    # The total exogenous savings should be zero (no services participating)
    assert out["total_exo_kg_per_mwh"] == 0.0


def test_predictor_robust_to_bimodal_workload():
    """Simulate an AI-training bimodal compute-communication trace and verify
    the AR(4) predictor remains stable (does not produce predictions outside
    [0,1] or NaN)."""
    from controller.multiscale import HostPredictiveCoordinator
    coord = HostPredictiveCoordinator()
    # Bimodal trace: 30s of high utilisation, 5s of low
    rng = np.random.default_rng(42)
    high = 0.85 + 0.05 * rng.standard_normal(30)
    low = 0.20 + 0.05 * rng.standard_normal(5)
    trace = np.tile(np.concatenate([high, low]), 5)
    trace = np.clip(trace, 0.0, 1.0)
    preds = []
    for u in trace:
        pred = coord.predict_util(float(u))
        preds.append(pred)
    preds = np.array(preds)
    # Predictions must be valid even for the bimodal pattern
    assert np.all(np.isfinite(preds)), "Predictor produced non-finite values"
    assert np.all((preds >= 0.0) & (preds <= 1.0)), "Predictor escaped [0,1]"
    # MAE must be bounded (not arbitrarily large)
    mae = np.mean(np.abs(preds - trace))
    assert mae < 0.30, f"Bimodal MAE {mae:.3f} exceeded 0.30 threshold"
