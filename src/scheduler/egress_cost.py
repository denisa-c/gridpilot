"""
src/scheduler/egress_cost.py
=============================
Data-egress emissions model for the f-SLA T5 spatial tier.

When a job migrates from its home grid to a cleaner destination grid,
the cluster transfers the job's data state across the European
backbone (or the institutional WAN).  That transfer itself emits CO2,
both directly (network and storage power consumption) and indirectly
(at the destination grid's CI).  Ignoring this cost in spatial
routing produces a Scope-3 blind spot that makes the contract dishonest
at the facility meter.

We model the egress emissions as a *per-grid-pair* table loaded from
``configs/network/egress_emissions.yaml``:

    SE_to_DE: 60.0      # g CO2eq per GB transferred SE -> DE
    ...

The table is calibrated to the published European backbone numbers
(~0.05--0.10 kWh per GB at the WAN level) times the destination grid's
mean carbon intensity.  Anchors:

  * Aslan et al., "Electricity Intensity of Internet Data
    Transmission", J. Industrial Ecology (2017) --- 0.06 kWh / GB.
  * Schien & Preist, "A Review of Top-Down Models of Internet Network
    Energy Intensity" --- bracketed at 0.04 -- 0.10 kWh/GB.
  * Per-grid CI from configs/grids/<CC>.yaml.

Used by:
  * ``scheduler.spatial_routing.pick_cleanest_grid`` (egress-aware
    cleanest-grid selector).
  * ``scheduler.spatial_routing.m_spatial_audit`` (NOM-IC audit:
    egress charge attributed to the user's credit).
  * ``scripts.multicountry.replay_spatial_sweep`` (sweep driver).
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover --- yaml is required at runtime
    yaml = None


def load_egress_emissions(yaml_path: Path) -> dict[tuple[str, str], float]:
    """Read a per-grid-pair egress-emissions YAML and return a dict
    keyed by ``(src_code, dst_code)`` -> g CO2eq per GB.

    The YAML's top-level keys are of the form ``<SRC>_to_<DST>`` where
    SRC and DST are ISO-3166-1 alpha-2 country codes (matching the
    files under ``configs/grids/``).  Self-loop entries (e.g.
    ``SE_to_SE``) default to 0.0 if absent (no inter-site transfer).
    Missing pairs default to 0.0 silently --- callers that need the
    explicit "missing" signal should use ``.get(pair, None)``.
    """
    if yaml is None:
        raise ImportError(
            "PyYAML is required to load the egress-emissions YAML; "
            "install via `pip install pyyaml>=6.0`."
        )
    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out: dict[tuple[str, str], float] = {}
    for key, val in raw.items():
        if not isinstance(key, str) or "_to_" not in key:
            continue
        src, dst = key.split("_to_", 1)
        src = src.strip().upper()
        dst = dst.strip().upper()
        if not src or not dst:
            continue
        try:
            out[(src, dst)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def egress_emissions_g_co2(
    table: Mapping[tuple[str, str], float],
    src_grid: str,
    dst_grid: str,
    transfer_size_gb: float,
) -> float:
    """Total egress emissions for one transfer in g CO2eq.

    Returns 0.0 when source and destination are the same grid, when
    transfer size is non-positive, or when the table has no entry for
    the pair.  Always non-negative.
    """
    if transfer_size_gb <= 0:
        return 0.0
    src = str(src_grid).upper()
    dst = str(dst_grid).upper()
    if src == dst:
        return 0.0
    per_gb = float(table.get((src, dst), 0.0))
    if per_gb < 0:
        per_gb = 0.0
    return per_gb * float(transfer_size_gb)
