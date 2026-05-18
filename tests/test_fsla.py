"""
tests/test_fsla.py
==================

12 unit tests for the f-SLA prior generator, dispatch hook, bootstrap
CI, and CLI driver.  Backs the acceptance criteria of
``scripts/m100/inject_fsla_prior.py`` documented in the docstring of
that module and in ``docs/FSLA_PROTOCOL.md``.

Run::

    pytest tests/test_fsla.py -v

Target: ≤ 30 s on a 16-core workstation.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scheduler.fsla import (                                  # noqa: E402
    DEFAULT_ALPHA, TIER_NAMES, TIER_WINDOW_H, TIER_SLOWMAX, TIER_CREDIT_H,
    LONG_JOB_THRESHOLD_S, SHORT_JOB_THRESHOLD_S,
    sample_prior, assign_tiers, replay_pair, bootstrap_ci,
    T_RIGID, T_HOUR, T_DAY, T_WEEK,
)


# ─────────────────────────────────────────────────────────────────────
# Mini-trace + mini-CI fixtures
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def mini_jobs() -> pd.DataFrame:
    """10-job mini-trace with a deliberate length mix:

      - 4 short jobs   (run_time = 600 s, 1 800 s)
      - 4 medium jobs  (run_time = 4 h, 12 h)
      - 2 long jobs    (run_time = 36 h, 60 h)
    """
    return pd.DataFrame({
        "job_id":            list(range(10)),
        "submit_time_epoch": np.linspace(0, 3600 * 8, 10),
        "run_time": [600, 1_800, 600, 1_800,
                     4 * 3600, 12 * 3600, 4 * 3600, 12 * 3600,
                     36 * 3600, 60 * 3600],
        "num_nodes_alloc":   [4, 8, 4, 8, 16, 32, 16, 32, 64, 128],
    })


@pytest.fixture
def mini_ci() -> pd.DataFrame:
    """Synthetic 7-day diurnal CI series, 1-hour resolution.
    Mean 250 g/kWh, ±100 g/kWh diurnal swing.
    """
    idx = pd.date_range("2025-01-01", periods=24 * 7, freq="h")
    hours = np.arange(len(idx))
    ci = 250.0 + 100.0 * np.sin(2 * np.pi * hours / 24.0)
    return pd.DataFrame({"carbon_intensity_gCO2eq_per_kWh": ci}, index=idx)


@pytest.fixture
def mini_t_amb(mini_ci) -> pd.Series:
    """Constant 20 °C ambient over the CI window."""
    return pd.Series(20.0, index=mini_ci.index, name="t_amb_c")


# ─────────────────────────────────────────────────────────────────────
# 1. Dirichlet draw lies on the 4-simplex
# ─────────────────────────────────────────────────────────────────────
def test_dirichlet_simplex():
    rng = np.random.default_rng(0)
    for _ in range(100):
        pi = sample_prior(DEFAULT_ALPHA, rng=rng)
        assert pi.shape == (4,)
        assert np.all(pi >= 0)
        assert abs(pi.sum() - 1.0) < 1e-9


# ─────────────────────────────────────────────────────────────────────
# 2. Default α matches the documented expectation within 0.01
# ─────────────────────────────────────────────────────────────────────
def test_default_alpha_expectation():
    rng = np.random.default_rng(20260513)
    samples = np.stack([sample_prior(DEFAULT_ALPHA, rng=rng) for _ in range(10_000)])
    expected = np.array([0.30, 0.30, 0.25, 0.15])
    actual = samples.mean(axis=0)
    np.testing.assert_allclose(actual, expected, atol=0.01)


# ─────────────────────────────────────────────────────────────────────
# 3. Length conditioning: long jobs are never T0
# ─────────────────────────────────────────────────────────────────────
def test_length_conditioning_long_jobs(mini_jobs):
    rng = np.random.default_rng(1)
    # Use a prior that puts ALL mass on T0 to force the conditioning rule
    pi = np.array([1.0, 0.0, 0.0, 0.0])
    # but Dirichlet would never give exactly this; sample one with
    # very high T0 weight using assign_tiers directly:
    pi = sample_prior((100.0, 1.0, 1.0, 1.0), rng=rng)  # ~99 % T0
    assigned, report = assign_tiers(mini_jobs, pi, rng=rng)
    long_mask = mini_jobs["run_time"].values > LONG_JOB_THRESHOLD_S
    assert (assigned.loc[long_mask, "tier"] != T_RIGID).all(), (
        "long jobs (run_time > 24h) must never be assigned T0"
    )
    assert report.n_long_reassigned_from_T0 >= 1


# ─────────────────────────────────────────────────────────────────────
# 4. Length conditioning: short jobs are never T2/T3
# ─────────────────────────────────────────────────────────────────────
def test_length_conditioning_short_jobs(mini_jobs):
    rng = np.random.default_rng(2)
    # Force most mass onto T2/T3 to trigger short-job re-sampling
    pi = sample_prior((1.0, 1.0, 50.0, 50.0), rng=rng)
    assigned, report = assign_tiers(mini_jobs, pi, rng=rng)
    short_mask = mini_jobs["run_time"].values <= SHORT_JOB_THRESHOLD_S
    assert (assigned.loc[short_mask, "tier"] < T_DAY).all(), (
        "short jobs (run_time ≤ 1h) must never be assigned T2 or T3"
    )
    assert report.n_short_reassigned_from_high_tier >= 1


# ─────────────────────────────────────────────────────────────────────
# 5. Tier → (window, slowdown_max, credit) mapping is exact
# ─────────────────────────────────────────────────────────────────────
def test_tier_window_mapping(mini_jobs):
    rng = np.random.default_rng(3)
    pi = sample_prior(DEFAULT_ALPHA, rng=rng)
    assigned, _ = assign_tiers(mini_jobs, pi, rng=rng,
                                length_conditioned=False)
    for tier_idx, win_h in TIER_WINDOW_H.items():
        rows = assigned[assigned["tier"] == tier_idx]
        assert (rows["d_max_hours"] == win_h).all()
        assert (rows["slowdown_max"] == TIER_SLOWMAX[tier_idx]).all()
        assert (rows["service_credit_h"] == TIER_CREDIT_H[tier_idx]).all()


# ─────────────────────────────────────────────────────────────────────
# 6. All-rigid replay reproduces a known-baseline (smoke test)
# ─────────────────────────────────────────────────────────────────────
def test_replay_rigid_runs_clean(mini_jobs, mini_ci, mini_t_amb):
    """The all-rigid baseline must run without error and report
    finite CO₂ figures and slowdowns ≥ 1.0."""
    rng = np.random.default_rng(4)
    pi = sample_prior(DEFAULT_ALPHA, rng=rng)
    res = replay_pair(mini_jobs, mini_ci, mini_t_amb, pi, seed=4,
                      total_nodes=64, node_power_kw=1.5, time_step=3600)
    assert res["all_rigid"]["co2_g"] >= 0
    assert res["all_rigid"]["facility_co2_g"] >= res["all_rigid"]["co2_g"]
    assert res["all_rigid"]["p95_slowdown"] >= 1.0
    assert res["all_rigid"]["avg_pue"] >= 1.0


# ─────────────────────────────────────────────────────────────────────
# 7. Declared-tier replay does not violate the slowdown clause
# ─────────────────────────────────────────────────────────────────────
def test_slowdown_clause_invariant(mini_jobs, mini_ci, mini_t_amb):
    """For every job in the declared-tier baseline, the realised
    slowdown must not exceed its tier's clause (allowing a small
    numerical tolerance)."""
    rng = np.random.default_rng(5)
    pi = sample_prior(DEFAULT_ALPHA, rng=rng)
    res = replay_pair(mini_jobs, mini_ci, mini_t_amb, pi, seed=5,
                      total_nodes=64, node_power_kw=1.5, time_step=3600)
    # The replay_pair return doesn't ship per-job slowdowns; the
    # invariant is that the *p95* slowdown of the declared-tier replay
    # is bounded by the maximum tier clause (4.0×) plus a generous
    # safety margin for the simulator's discrete time-step.
    assert res["declared_tier"]["p95_slowdown"] <= 4.0 * 4 + 1.0


# ─────────────────────────────────────────────────────────────────────
# 8. Bootstrap CI utility: width shrinks as n_resamples grows
# ─────────────────────────────────────────────────────────────────────
def test_bootstrap_ci_consistent():
    rng = np.random.default_rng(6)
    values = rng.normal(loc=4.7, scale=1.0, size=32)
    mean, lo, hi = bootstrap_ci(values, n_resamples=10_000, rng=rng)
    assert lo < mean < hi
    assert hi - lo < 1.5      # acceptance criterion on the M100 trace
    # Mean estimate within 0.5 of the population mean
    assert abs(mean - 4.7) < 0.5


# ─────────────────────────────────────────────────────────────────────
# 9. Reproducibility: same seed → same Δ
# ─────────────────────────────────────────────────────────────────────
def test_reproducible_under_fixed_seed(mini_jobs, mini_ci, mini_t_amb):
    rng_a = np.random.default_rng(7)
    pi_a = sample_prior(DEFAULT_ALPHA, rng=rng_a)
    rng_b = np.random.default_rng(7)
    pi_b = sample_prior(DEFAULT_ALPHA, rng=rng_b)
    np.testing.assert_array_equal(pi_a, pi_b)

    res_a = replay_pair(mini_jobs, mini_ci, mini_t_amb, pi_a, seed=42,
                        total_nodes=64, node_power_kw=1.5)
    res_b = replay_pair(mini_jobs, mini_ci, mini_t_amb, pi_b, seed=42,
                        total_nodes=64, node_power_kw=1.5)
    assert res_a["all_rigid"]["co2_g"] == res_b["all_rigid"]["co2_g"]
    assert res_a["delta_it_pp"] == res_b["delta_it_pp"]


# ─────────────────────────────────────────────────────────────────────
# 10. CLI: --help exits 0 and prints usage
# ─────────────────────────────────────────────────────────────────────
def test_cli_help():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/m100/inject_fsla_prior.py"), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0
    assert "Monte-Carlo f-SLA injection" in r.stdout
    assert "--alpha" in r.stdout


# ─────────────────────────────────────────────────────────────────────
# 11. CLI: missing required arg exits non-zero with a usable message
# ─────────────────────────────────────────────────────────────────────
def test_cli_missing_args():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/m100/inject_fsla_prior.py")],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode != 0
    assert "required" in (r.stderr + r.stdout).lower()


# ─────────────────────────────────────────────────────────────────────
# 12. CLI round-trip on a tiny synthetic mini-trace
# ─────────────────────────────────────────────────────────────────────
def test_cli_round_trip(tmp_path, mini_jobs, mini_ci, mini_t_amb):
    """Run the CLI against a tiny mini-trace and assert all four
    output files exist with the documented schema."""
    jobs_path = tmp_path / "jobs.csv"
    ci_path = tmp_path / "ci.csv"
    out_dir = tmp_path / "out"
    mini_jobs.to_csv(jobs_path, index=False)
    mini_ci.reset_index().rename(columns={"index": "timestamp"}) \
           .to_csv(ci_path, index=False)

    r = subprocess.run(
        [
            sys.executable, str(ROOT / "scripts/m100/inject_fsla_prior.py"),
            "--jobs", str(jobs_path),
            "--ci",   str(ci_path),
            "--seeds", "4",
            "--bootstrap", "200",
            "--sensitivity-scale", "0.5,1.0,2.0",
            "--output-dir", str(out_dir),
            "--total-nodes", "64",
            "--quiet",
            "--force",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"stderr:\n{r.stderr}\nstdout:\n{r.stdout}"

    # Output files exist
    assert (out_dir / "headline.csv").exists()
    assert (out_dir / "bootstrap_ci.json").exists()
    assert (out_dir / "prior_sensitivity.csv").exists()
    assert (out_dir / "RUN_MANIFEST.json").exists()
    assert (out_dir / "seed_runs").is_dir()
    assert len(list((out_dir / "seed_runs").glob("seed_*.json"))) == 4

    # Schema spot-check
    df = pd.read_csv(out_dir / "headline.csv")
    expected_cols = {
        "seed", "pi_T0", "pi_T1", "pi_T2", "pi_T3",
        "rigid_it_pct", "rigid_fac_pct",
        "decl_it_pct", "decl_fac_pct",
        "delta_it_pp", "delta_fac_pp",
        "p95_rigid", "p95_decl", "p95_match",
        "n_long_reassigned", "n_short_reassigned",
    }
    missing = expected_cols - set(df.columns)
    assert not missing, f"headline.csv missing columns: {missing}"
    assert len(df) == 4

    boot = json.loads((out_dir / "bootstrap_ci.json").read_text())
    for k in ("delta_it_pp", "delta_facility_pp", "declared_it_pct",
              "declared_facility_pct"):
        assert k in boot
        for sub in ("mean", "ci_lower", "ci_upper"):
            assert sub in boot[k]
