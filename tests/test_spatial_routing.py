"""Tests for src/scheduler/spatial_routing.py + src/scheduler/egress_cost.py.

Covers:
  * SpatialClause normalisation + effective_grids
  * pick_cleanest_grid without and with egress cost
  * assign_t5_spatial_eligibility deterministic-fraction marking
  * m_spatial_audit NOM-IC violation detection
  * load_egress_emissions + egress_emissions_g_co2 self-loops and missing pairs

Six tests in total; no network, no real M100 trace.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml
from pathlib import Path

from scheduler.spatial_routing import (
    SpatialClause, assign_t5_spatial_eligibility,
    m_spatial_audit, pick_cleanest_grid,
)
from scheduler.egress_cost import (
    egress_emissions_g_co2, load_egress_emissions,
)


def test_spatial_clause_normalises_input():
    c = SpatialClause(acceptable_grids=("se", "ch", "SE"))
    # de-duplicated, uppercased, sorted
    assert c.acceptable_grids == ("CH", "SE")
    # excluded defaults to empty
    assert c.excluded_grids == ()
    assert c.effective_grids == ("CH", "SE")


def test_pick_cleanest_grid_no_egress():
    c = SpatialClause(acceptable_grids=("SE", "DE", "PL"))
    ci = {"SE": 11.0, "DE": 295.0, "PL": 612.0}
    grid, ci_val = pick_cleanest_grid(c, ci)
    assert grid == "SE"
    assert ci_val == 11.0


def test_pick_cleanest_grid_egress_aware_picks_home_when_penalty_dominates():
    # SE is much cleaner than DE, but egress cost from DE to SE is huge
    # in this test; the egress-aware selector should keep the job home.
    c = SpatialClause(acceptable_grids=("SE", "DE"),
                       transfer_size_gb=100.0, home_grid="DE")
    ci = {"SE": 11.0, "DE": 295.0}
    egress = {("DE", "SE"): 100.0}   # 100 g/GB * 100 GB = 10 000 g penalty
    grid, _ = pick_cleanest_grid(c, ci, egress_emissions=egress)
    assert grid == "DE"     # SE is cleaner but penalty dominates


def test_assign_t5_eligibility_marks_correct_fraction():
    jobs = pd.DataFrame({"job_id": range(100)})
    rng = np.random.default_rng(0)
    out = assign_t5_spatial_eligibility(jobs, rng, fraction=0.20)
    assert "is_spatial_eligible" in out.columns
    assert "spatial_clause" in out.columns
    assert int(out["is_spatial_eligible"].sum()) == 20
    # Eligible rows carry a non-empty spatial clause
    elig = out[out["is_spatial_eligible"]]
    assert all(c != "" for c in elig["spatial_clause"])


def test_m_spatial_audit_detects_violation():
    job = pd.Series({"job_id": 7, "spatial_clause": "SE,CH",
                     "home_grid": "PL", "transfer_size_gb": 5.0})
    egress = {("PL", "SE"): 0.7, ("PL", "DE"): 17.7}
    # Realised grid DE is NOT in the declared clause -> violation
    audit = m_spatial_audit(job, "DE", egress)
    assert audit.nom_ic_violation is True
    assert audit.egress_charge_g_co2 == pytest.approx(17.7 * 5.0)


def test_egress_emissions_zero_for_self_loop_and_missing_pair(tmp_path):
    yaml_path = tmp_path / "egress.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "SE_to_SE": 0.0,
        "SE_to_DE": 17.7,
    }))
    table = load_egress_emissions(yaml_path)
    assert egress_emissions_g_co2(table, "SE", "SE", 100.0) == 0.0
    assert egress_emissions_g_co2(table, "SE", "DE", 100.0) == pytest.approx(1770.0)
    # Missing pair -> 0.0 (no penalty)
    assert egress_emissions_g_co2(table, "FR", "DE", 100.0) == 0.0
