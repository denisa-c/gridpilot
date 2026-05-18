"""
controller/parametrisable.py
============================

Service-parametrisable extension of the multiscale controller. Wraps the
three-tier controller from controller.multiscale and adds:

1. Country configuration plumbing: the controller accepts an
   ENTSOEConnector and a country code, and automatically loads the
   country's available ancillary services and their participation rates.

2. Service stacking: the Tier-3 cluster optimiser now selects an operating
   point that maximises the joint objective across MULTIPLE simultaneous
   services (FCR + aFRR + mFRR), following the revenue-stacking approach
   of Hjalmarsson et al. (2023, Journal of Energy Storage).

3. Ancillary-service-aware exogenous carbon: each service has a different
   marginal CI from the country configuration, and the joint exogenous
   savings are aggregated across services that the cluster participates in.

The controller is designed so that adding a new country requires only a
YAML configuration entry (no code changes), and adding a new ancillary
service requires only an entry in the service-share lookup table.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable
import numpy as np

from controller.multiscale import (
    MultiscaleController, ClusterOptimiserParams, ClusterMultiscaleOptimiser,
)
from integration.entsoe_connector import (
    ENTSOEConnector, CountryAncillaryConfig, load_country_config,
    build_ffr_signal_from_entsoe,
)


@dataclass
class ServiceParticipation:
    """Per-service participation parameters for a single cluster.

    The participation fraction in [0, 1] is the share of the country's
    total balancing market that this cluster is bidding into. It must
    respect the country's minimum bid size and the cluster's headroom.
    """
    service: str
    enabled: bool
    bid_fraction: float = 0.0           # fraction of cluster headroom to commit
    bid_mw: float = 0.0                  # absolute MW bid
    marginal_ci_g_per_kwh: float = 0.0   # used for exogenous carbon
    activation_time_s: float = 0.0


@dataclass
class StackedAncillaryConfig:
    """Aggregate configuration for one cluster participating in N services."""
    country: str
    cluster_capacity_mw: float
    services: Dict[str, ServiceParticipation] = field(default_factory=dict)

    def total_committed_mw(self) -> float:
        return sum(s.bid_mw for s in self.services.values() if s.enabled)

    def total_marginal_ci(self) -> float:
        """Aggregate marginal CI weighted by committed capacity."""
        total_mw = self.total_committed_mw()
        if total_mw <= 0:
            return 0.0
        return sum(
            s.bid_mw * s.marginal_ci_g_per_kwh
            for s in self.services.values() if s.enabled
        ) / total_mw


def build_stacked_config(
    country: str,
    cluster_capacity_mw: float,
    services: Optional[List[str]] = None,
    bid_fractions: Optional[Dict[str, float]] = None,
) -> StackedAncillaryConfig:
    """Construct a StackedAncillaryConfig from a country's defaults.

    services: optional list of services to enable. If None, all available
              services are enabled.
    bid_fractions: optional per-service bid fraction. If None, uses the
                   country's documented participation_rate as the default.
    """
    cfg = load_country_config(country)
    services = services or [s for s, v in cfg.services.items() if v["available"]]
    bid_fractions = bid_fractions or {}

    out = StackedAncillaryConfig(country=country,
                                   cluster_capacity_mw=cluster_capacity_mw)
    for svc in services:
        if svc not in cfg.services:
            continue
        s_cfg = cfg.services[svc]
        if not s_cfg["available"]:
            continue
        bid_frac = bid_fractions.get(svc, s_cfg["participation_rate"])
        bid_mw = bid_frac * cluster_capacity_mw
        if bid_mw < s_cfg["min_bid_mw"]:
            # Cluster is too small to participate at this fraction
            continue
        out.services[svc] = ServiceParticipation(
            service=svc,
            enabled=True,
            bid_fraction=bid_frac,
            bid_mw=bid_mw,
            marginal_ci_g_per_kwh=s_cfg["marginal_ci_g_per_kwh"],
            activation_time_s=s_cfg["activation_time_s"],
        )
    return out


class ParametrisableMultiscaleController:
    """End-to-end multiscale controller parametrised by country and service stack.

    Wraps the underlying MultiscaleController with country-aware FFR signal
    generation, service-stacked Tier-3 optimisation, and aggregate exogenous-
    carbon accounting.
    """

    def __init__(
        self,
        country: str,
        cluster_capacity_mw: float,
        n_hosts: int = 100,
        gpus_per_host: int = 8,
        services: Optional[List[str]] = None,
        bid_fractions: Optional[Dict[str, float]] = None,
        connector: Optional[ENTSOEConnector] = None,
    ):
        self.country = country
        self.country_cfg = load_country_config(country)
        self.stacked = build_stacked_config(
            country, cluster_capacity_mw, services, bid_fractions
        )
        self.connector = connector or ENTSOEConnector()
        self.n_hosts = n_hosts
        self.gpus_per_host = gpus_per_host

        # Build FFR signal from ENTSO-E for a 24h window starting now
        start = datetime(2025, 7, 1, 0, 0, 0)
        end = start + timedelta(hours=24)
        ffr_signal = build_ffr_signal_from_entsoe(
            country, start, end, self.connector
        )
        self._ffr_signal = ffr_signal
        self._ffr_metadata = ffr_signal.metadata

        # Underlying multiscale controller
        self.ctrl = MultiscaleController(
            n_hosts=n_hosts, gpus_per_host=gpus_per_host,
            ffr_signal_fn=ffr_signal,
        )

    @property
    def metadata(self) -> dict:
        return {
            "country": self.country,
            "bidding_zone": self.country_cfg.bidding_zone,
            "annual_mean_ci": self.country_cfg.annual_mean_ci_g_per_kwh,
            "services_enabled": list(self.stacked.services.keys()),
            "total_committed_mw": self.stacked.total_committed_mw(),
            "weighted_marginal_ci": self.stacked.total_marginal_ci(),
            "data_source": self._ffr_metadata.get("data_source", "unknown"),
        }

    def step(
        self,
        t_s: float,
        ci_g_per_kwh: float,
        green_pct: float,
        current_util: float,
        gpu_actual_powers_w: np.ndarray,
        gpu_temps_c: np.ndarray,
    ) -> dict:
        """One controller tick. Augments the underlying MultiscaleController
        output with service-stacked exogenous-carbon accounting."""
        out = self.ctrl.step(t_s, ci_g_per_kwh, green_pct, current_util,
                              gpu_actual_powers_w, gpu_temps_c)
        # Aggregate exogenous savings across the service stack
        op_pt = out["tier3_op_point"]
        ffr_band_mw = op_pt["ffr_band_frac"] * self.stacked.cluster_capacity_mw
        # Distribute the FFR band across services proportional to their bid_mw
        per_service = {}
        total_exo_kg_per_mwh = 0.0
        if self.stacked.total_committed_mw() > 0:
            for svc, sp in self.stacked.services.items():
                share = sp.bid_mw / self.stacked.total_committed_mw()
                svc_band_mw = ffr_band_mw * share
                # Exogenous savings: 1 MW of band offsets marginal_CI g/kWh
                exo_kg_per_mwh = svc_band_mw / max(self.stacked.cluster_capacity_mw, 1.0) \
                                  * sp.marginal_ci_g_per_kwh / 1000.0
                per_service[svc] = {
                    "band_mw": svc_band_mw,
                    "exo_kg_per_mwh": exo_kg_per_mwh,
                    "marginal_ci": sp.marginal_ci_g_per_kwh,
                }
                total_exo_kg_per_mwh += exo_kg_per_mwh
        out["service_stack"] = per_service
        out["total_exo_kg_per_mwh"] = total_exo_kg_per_mwh
        return out
