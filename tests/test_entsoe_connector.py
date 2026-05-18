"""Tests for the country-parametrisable ENTSO-E connector and the
parametrisable multiscale controller."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import pytest
import numpy as np


def test_country_configs_loadable():
    """All seven built-in countries must load without error."""
    from integration.entsoe_connector import builtin_country_configs, load_country_config
    builtin = builtin_country_configs()
    assert len(builtin) >= 25  # 25 ENTSO-E countries shipped
    for c in ["CH","IT","DE","FR","ES","DK","NL","AT","BE","PL","GB","NO","SE","FI","IE","GR","PT","HR","HU","SK","CZ","RO","SI","BG","EE"]:
        cfg = load_country_config(c)
        assert cfg.country_code == c
        assert cfg.bidding_zone.startswith("10Y")
        assert cfg.annual_mean_ci_g_per_kwh > 0


def test_country_configs_have_required_services():
    """Every country must declare FCR (the most universal European service)."""
    from integration.entsoe_connector import load_country_config
    for c in ["CH","IT","DE","FR","ES","DK","NL","AT","BE","PL","GB","NO","SE","FI","IE","GR","PT","HR","HU","SK","CZ","RO","SI","BG","EE"]:
        cfg = load_country_config(c)
        assert cfg.services["FCR"]["available"] is True


def test_synthesised_fallback_is_deterministic():
    """The synthesised mode must produce reproducible results given the same inputs."""
    from integration.entsoe_connector import ENTSOEConnector
    from datetime import datetime
    conn = ENTSOEConnector(api_key=None)  # force synthesis
    start = datetime(2025, 7, 1, 0, 0)
    end = datetime(2025, 7, 1, 6, 0)
    r1 = conn.fetch_ancillary("DE", "FCR", start, end)
    r2 = conn.fetch_ancillary("DE", "FCR", start, end)
    assert r1.source == "synthesised"
    assert r1.capacity_mw == r2.capacity_mw, "Synthesis must be deterministic"


def test_parametrisable_controller_country_dispatch():
    """Controller must produce country-specific service stacks."""
    from controller.parametrisable import ParametrisableMultiscaleController
    from integration.entsoe_connector import ENTSOEConnector
    conn = ENTSOEConnector(api_key=None)
    ctrl_de = ParametrisableMultiscaleController(
        country="DE", cluster_capacity_mw=50.0, n_hosts=10, gpus_per_host=8,
        connector=conn,
    )
    ctrl_ch = ParametrisableMultiscaleController(
        country="CH", cluster_capacity_mw=50.0, n_hosts=10, gpus_per_host=8,
        connector=conn,
    )
    de_meta = ctrl_de.metadata
    ch_meta = ctrl_ch.metadata
    # Germany participates more heavily than Switzerland
    assert de_meta["total_committed_mw"] > ch_meta["total_committed_mw"]
    assert de_meta["weighted_marginal_ci"] > ch_meta["weighted_marginal_ci"]


def test_minimum_bid_size_is_enforced():
    """A 1 MW cluster in CH must not enable services with 1 MW min bid."""
    from controller.parametrisable import build_stacked_config
    sc = build_stacked_config("CH", cluster_capacity_mw=1.0)
    # CH FCR has min_bid_mw=1.0 and participation_rate=0.15, so bid is 0.15 MW < 1 MW
    assert "FCR" not in sc.services or sc.services["FCR"].bid_mw >= 1.0


def test_unknown_country_raises():
    """Unknown country must raise a clear error."""
    from integration.entsoe_connector import load_country_config
    with pytest.raises(ValueError, match="not in built-in"):
        load_country_config("XX")
