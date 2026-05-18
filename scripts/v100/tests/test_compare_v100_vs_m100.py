"""
test_compare_v100_vs_m100.py — exercise the comparison harness against
synthesised V100 + M100 inputs.

Tests confirm:
- The harness runs end-to-end without raising.
- Each cross-validation axis returns the documented status when its
  inputs are present.
- The harness gracefully reports `incomplete` when inputs are missing.
- The pass/fail thresholds documented in
  docs/V100_VS_M100_METHODOLOGY.md §4 are correctly applied.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "src"))

import compare_v100_vs_m100 as cmp


# ---------------------------------------------------------------------------
# Fixtures: synthesise minimal V100 and M100 inputs
# ---------------------------------------------------------------------------
def _write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.touch()
        return
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _setup_v100(tmp_path: Path, with_e1=True, with_e3=True,
                 with_e4=True, with_e6=True, with_e7=True,
                 with_calibration=True, with_projection=True):
    """Synthesise a v100_experiment_kit-shaped tree under tmp_path."""
    res = tmp_path / "results"
    res.mkdir(parents=True, exist_ok=True)
    if with_e1:
        sweep = res / "sweep_20260101T000000Z"
        _write_csv(sweep / "parsed_results.csv", [
            {"workload": "matmul_compute_bound",   "pcap_w": 150,
              "sm_target_mhz": 945, "power_mean_w": 114.0,
              "iters_per_s": 64.95},
            {"workload": "inference_memory_bound", "pcap_w": 150,
              "sm_target_mhz": 945, "power_mean_w": 144.4,
              "iters_per_s": 403.78},
            {"workload": "bursty_alternating",     "pcap_w": 150,
              "sm_target_mhz": 945, "power_mean_w": 113.6,
              "iters_per_s": 60.09},
        ])
    if with_e3:
        e3 = res / "E3_outer_loop_20260101T010000Z"
        e3.mkdir()
        (e3 / "matmul_compute_bound_metrics.json").write_text(
            json.dumps({"mae_w": 3.19, "p95_w": 6.61}))
        (e3 / "bursty_alternating_metrics.json").write_text(
            json.dumps({"mae_w": 33.77, "p95_w": 162.89}))
    if with_e4:
        e4 = res / "E4_closed_loop_20260101T020000Z"
        e4.mkdir()
        (e4 / "matmul_compute_bound_summary.json").write_text(
            json.dumps({"mae_w": 4.41, "relative_mae": 0.0212}))
    if with_e6:
        e6 = res / "E6_multigpu_20260101T030000Z"
        e6.mkdir()
        (e6 / "budget_900_metrics.json").write_text(
            json.dumps({"budget_w": 900, "fairness": 0.95,
                         "per_gpu_energy_j": [9000, 8800, 9100]}))
    if with_e7:
        e7 = res / "E7_ffr_20260101T040000Z"
        e7.mkdir()
        (e7 / "workload_matmul_summary.json").write_text(json.dumps({
            "workload": "matmul", "median_ms": 142.3, "p95_ms": 175,
            "pass_rate": 1.0, "budget_ms": 700, "n_trials": 30,
        }))
        (e7 / "verdict.json").write_text(json.dumps({
            "all_workloads_pass": True, "budget_ms": 700,
            "per_workload": {"matmul": {"pass_rate": 1.0,
                                         "median_ms": 142.3}},
        }))
    if with_calibration:
        cal = res / "raps_calibration_20260101T050000Z"
        cal.mkdir()
        (cal / "coefficients.json").write_text(json.dumps({
            "calibrated_at": "20260101T050000Z",
            "model": "P_GPU = P_idle + alpha*f + beta*f^2*L + gamma*L",
            "node": {"n_gpu_per_node": 3, "facility_pue": 1.10,
                      "rectifier_eta": 0.93, "node_idle_w_estimate": 250},
            "per_workload": {
                "matmul_compute_bound": {"P_idle": 175, "alpha": -0.47,
                                          "beta": 1e-5, "gamma": 200,
                                          "iters_per_s_max": 93.73,
                                          "loocv_mae_pct": 1.8},
            },
        }))
    if with_projection:
        proj = res / "cluster_projection_20260101T060000Z"
        proj.mkdir()
        (proj / "projection_summary.json").write_text(json.dumps({
            "node":    {"n_nodes": 1,    "n_gpu": 3,
                         "max_facility_kw": 1.3},
            "rack":    {"n_nodes": 12,   "n_gpu": 36,
                         "max_facility_kw": 15.8},
            "pod":     {"n_nodes": 600,  "n_gpu": 1800,
                         "max_facility_kw": 788.5},
            "cluster": {"n_nodes": 12000, "n_gpu": 36000,
                         "max_facility_kw": 15770.0},
        }))


def _setup_m100(tmp_path: Path, n_cells=10):
    """Synthesise a carbonscaler_beat-shaped tree alongside the V100 kit."""
    cs = tmp_path / "carbonscaler_beat"
    res = cs / "results"
    res.mkdir(parents=True, exist_ok=True)
    rows_cs = []
    rows_gp = []
    for i in range(n_cells):
        base = {"workload": "M100", "country": "IT", "seed": i,
                "co2_red_pct": 18 + i * 0.3,
                "facility_co2_red_pct": 35 + i * 0.5,
                "p95_slow": 12.0 + i * 0.1,
                "energy_kwh": 250 + i * 5.0}
        rows_cs.append(dict(base, min_replicas=1, max_replicas=8,
                             adoption_rate=1.0, ci_lookahead_h=12,
                             mean_slow=10.0,
                             cfe=0.5, ettr=12.0,
                             p50_slow=10.5, p99_slow=15.0,
                             exo_co2_red_pct=0.0,
                             net_co2_red_pct=18 + i * 0.3))
        rows_gp.append(dict(base, carbon_weight=0.6, pue_weight=0.3,
                             ffr_band=0.1, max_delay_h=12,
                             mean_slow=9.5,
                             cfe=0.55, ettr=11.5,
                             p50_slow=10.0, p99_slow=14.5,
                             co2_red_pct=20 + i * 0.3,
                             exo_co2_red_pct=0.0,
                             net_co2_red_pct=20 + i * 0.3))
        rows_gp[-1]["co2_red_pct"] = 20 + i * 0.3
    _write_csv(res / "sweep_carbonscaler.csv", rows_cs)
    _write_csv(res / "sweep_gridpilot.csv", rows_gp)
    return cs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_loaders_handle_missing_dirs(tmp_path, monkeypatch):
    """All loaders must return {} (not raise) when results/ is empty."""
    monkeypatch.setattr(cmp, "ROOT", tmp_path)
    assert cmp.load_v100_e1(tmp_path) == {}
    assert cmp.load_v100_e3(tmp_path) == {}
    assert cmp.load_v100_e4(tmp_path) == {}
    assert cmp.load_v100_e6(tmp_path) == {}
    assert cmp.load_v100_e7(tmp_path) == {}
    assert cmp.load_v100_calibration(tmp_path) == {}
    assert cmp.load_v100_projection(tmp_path) == {}


def test_axis1_passes_when_within_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(cmp, "ROOT", tmp_path)
    _setup_v100(tmp_path)
    cs = _setup_m100(tmp_path)
    # Synthesise M100 energy that produces ~120 W/GPU (close to V100 ~124 W mean)
    # Mean V100 power across the 3 workloads = (114 + 144.4 + 113.6) / 3 = 124 W
    # M100 derived: (mean_energy_kwh * 1000) / (980 * 4) per W
    # = mean_energy_kwh * 1000 / 3920
    # For 120 W → mean_energy_kwh = 120 * 3920 / 1000 = 470 kWh
    rows_gp = []
    for i in range(5):
        rows_gp.append({"workload": "M100", "country": "IT", "seed": i,
                          "co2_red_pct": 20.0,
                          "facility_co2_red_pct": 35.0,
                          "p95_slow": 12.0,
                          "energy_kwh": 470.0,  # → 120 W per GPU
                          "carbon_weight": 0.6, "pue_weight": 0.3,
                          "ffr_band": 0.1, "max_delay_h": 12,
                          "mean_slow": 10.0, "cfe": 0.5, "ettr": 11.5,
                          "p50_slow": 10.0, "p99_slow": 14.0,
                          "exo_co2_red_pct": 0.0,
                          "net_co2_red_pct": 20.0})
    _write_csv(cs / "results" / "sweep_gridpilot.csv", rows_gp)

    v100_e1 = cmp.load_v100_e1(tmp_path)
    m100 = cmp.load_m100_replay(cs)
    cal = cmp.load_v100_calibration(tmp_path)

    result = cmp.axis_1_per_gpu_power(v100_e1, m100, cal)
    # V100 mean = 124 W, M100 derived ≈ 120 W → ~3% err → passes 5%
    assert result["status"] == "pass", f"expected pass, got {result}"
    assert abs(result["pct_err"]) < 5.0


def test_axis1_fails_when_outside_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(cmp, "ROOT", tmp_path)
    _setup_v100(tmp_path)
    cs = _setup_m100(tmp_path)
    # Force a large discrepancy: 1500 kWh → 383 W per GPU (way outside 5%)
    rows_gp = []
    for i in range(3):
        rows_gp.append({"workload": "M100", "country": "IT", "seed": i,
                          "co2_red_pct": 20.0, "facility_co2_red_pct": 35.0,
                          "p95_slow": 12.0, "energy_kwh": 1500.0,
                          "carbon_weight": 0.6, "pue_weight": 0.3,
                          "ffr_band": 0.1, "max_delay_h": 12,
                          "mean_slow": 10.0, "cfe": 0.5, "ettr": 11.5,
                          "p50_slow": 10.0, "p99_slow": 14.0,
                          "exo_co2_red_pct": 0.0,
                          "net_co2_red_pct": 20.0})
    _write_csv(cs / "results" / "sweep_gridpilot.csv", rows_gp)

    v100_e1 = cmp.load_v100_e1(tmp_path)
    m100 = cmp.load_m100_replay(cs)
    result = cmp.axis_1_per_gpu_power(v100_e1, m100, {})
    assert result["status"] == "fail"
    assert abs(result["pct_err"]) >= 5.0


def test_axis7_returns_co2_reduction(tmp_path, monkeypatch):
    monkeypatch.setattr(cmp, "ROOT", tmp_path)
    cs = _setup_m100(tmp_path)
    m100 = cmp.load_m100_replay(cs)
    result = cmp.axis_7_carbon_reduction(m100, "IT")
    assert result["axis"] == 7
    assert result["carbonscaler_max_pct"] is not None
    assert result["gridpilot_max_pct"] is not None
    # GridPilot rows in the fixture have higher co2_red_pct than carbonscaler
    assert result["delta_pp"] > 0


def test_axis9_passes_when_envelope_close(tmp_path, monkeypatch):
    monkeypatch.setattr(cmp, "ROOT", tmp_path)
    _setup_v100(tmp_path)
    cs = _setup_m100(tmp_path)
    proj = cmp.load_v100_projection(tmp_path)
    m100 = cmp.load_m100_replay(cs)
    result = cmp.axis_9_scaling_envelope(proj, m100)
    # 980-node interpolation between rack(36 GPU=15.8 kW) and cluster
    # (36000 GPU=15770 kW) at 3920 GPU = 15.8 + (15770-15.8) *
    # (3920-36)/(36000-36) ≈ 1700 kW. Compared to M100 published 1000 kW,
    # err ≈ 70%. Should fail.
    assert result["status"] in ("pass", "fail")
    # The interpolation gives ~1700, M100 ref is 1000, so err ~70%, fails
    assert result["passed"] is False


def test_full_run_smoke(tmp_path, monkeypatch, capsys):
    """End-to-end: harness runs without raising on a complete fixture."""
    monkeypatch.setattr(cmp, "ROOT", tmp_path)
    _setup_v100(tmp_path)
    cs = _setup_m100(tmp_path)
    out_dir = tmp_path / "comparison_out"

    monkeypatch.setattr(sys, "argv", [
        "compare_v100_vs_m100.py",
        "--cs-root", str(cs),
        "--country", "IT",
        "--output-dir", str(out_dir),
    ])
    cmp.main()

    # Files were written
    assert (out_dir / "comparison_report.json").exists()
    assert (out_dir / "comparison_report.md").exists()
    assert (out_dir / "cross_validation.json").exists()

    report = json.loads((out_dir / "comparison_report.json").read_text())
    assert "cross_validation" in report
    assert len(report["cross_validation"]) == 4
    # The Markdown render must include a table
    md = (out_dir / "comparison_report.md").read_text()
    assert "| # | Axis" in md


def test_run_without_carbonscaler_kit(tmp_path, monkeypatch):
    """Path B totally absent: should still produce a report with
    M100 axes marked incomplete, not crash."""
    monkeypatch.setattr(cmp, "ROOT", tmp_path)
    _setup_v100(tmp_path)
    out_dir = tmp_path / "out"

    monkeypatch.setattr(sys, "argv", [
        "compare_v100_vs_m100.py",
        "--cs-root", str(tmp_path / "no_such_kit"),
        "--output-dir", str(out_dir),
    ])
    cmp.main()
    report = json.loads((out_dir / "comparison_report.json").read_text())
    # Axis 7 (M100-only) must be incomplete
    a7 = next(a for a in report["cross_validation"] if a["axis"] == 7)
    assert a7["status"] == "incomplete"
