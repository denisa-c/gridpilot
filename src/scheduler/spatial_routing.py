"""
src/scheduler/spatial_routing.py
=================================
Spatial-flexibility primitives for the f-SLA T5 (Spatial) tier.

A T5 job carries a non-empty ``spatial_clause`` --- a set of grid codes
acceptable to the user (e.g. ``{'SE','CH','FR'}``).  The dispatcher
routes the job to whichever grid in the clause is cleanest at dispatch
time, charging the inter-site data-egress emissions against the IT-side
savings via :mod:`scheduler.egress_cost`.

This module ships the *primitives* (``SpatialClause`` dataclass,
``pick_cleanest_grid`` selector, ``M_Spatial`` mechanism plug-in).  The
end-to-end multi-grid replay driver lives in
``scripts/multicountry/replay_spatial_sweep.py`` and is the load-bearing
piece of the C2 follow-on paper.  See ``_dev_archive/PAPER_C2_PLAN.md``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional

import numpy as np
import pandas as pd

# Note: keep this module dependency-light --- pulling in
# scheduler_pue_aware here would create an import cycle with
# fsla_mechanisms; the dispatch helper takes the cleanest-grid index
# and lets the caller wire it into the per-grid CI tables it already
# loaded.


@dataclass(frozen=True)
class SpatialClause:
    """User-declared spatial flexibility for one job.

    Parameters
    ----------
    acceptable_grids : tuple[str, ...]
        Non-empty tuple of grid codes (e.g. ``("SE", "CH", "FR")``).
        Order is irrelevant; duplicates are dropped.  The dispatcher
        picks the cleanest grid in this set at dispatch time.
    excluded_grids : tuple[str, ...]
        GDPR-style data-sovereignty exclusion list.  Grids in this set
        are never selected, even if they appear in ``acceptable_grids``.
        Used to test H4 (graceful degradation under sovereignty
        constraints) of the C2 paper.
    transfer_size_gb : float
        Approximate per-job data state in GB.  Multiplied by the
        per-grid-pair egress emissions to compute the egress-cost
        charge.  Defaults to 0 GB (stateless job).
    home_grid : str | None
        The grid where the job's data currently lives.  When set, the
        egress cost is computed against this anchor; when None, no
        inter-site transfer is charged (the job's data is assumed
        replicated or generated in-place).
    """
    acceptable_grids: tuple[str, ...]
    excluded_grids: tuple[str, ...] = field(default_factory=tuple)
    transfer_size_gb: float = 0.0
    home_grid: Optional[str] = None

    def __post_init__(self) -> None:  # pragma: no cover (dataclass init)
        if not self.acceptable_grids:
            raise ValueError("SpatialClause.acceptable_grids must be non-empty")
        # Normalise: drop duplicates, enforce uppercase, frozen.
        object.__setattr__(
            self, "acceptable_grids",
            tuple(sorted({g.upper() for g in self.acceptable_grids})),
        )
        object.__setattr__(
            self, "excluded_grids",
            tuple(sorted({g.upper() for g in self.excluded_grids})),
        )

    @property
    def effective_grids(self) -> tuple[str, ...]:
        """Acceptable minus excluded; may be empty if sovereignty over-
        constrains the clause, in which case the dispatcher falls back
        to the job's home grid (degrades gracefully to T0).
        """
        return tuple(g for g in self.acceptable_grids
                     if g not in self.excluded_grids)


def pick_cleanest_grid(
    clause: SpatialClause,
    ci_at_t: Mapping[str, float],
    egress_emissions: Optional[Mapping[tuple[str, str], float]] = None,
) -> tuple[str, float]:
    """Return ``(grid_code, expected_ci_g_per_kwh)`` for the cleanest
    effective grid in ``clause`` at the dispatch instant.

    If ``egress_emissions`` is provided, the function adds the inter-
    site egress emissions (per GB times the job's ``transfer_size_gb``)
    *amortised against the job's energy* before picking, so the choice
    is honest at the facility meter.  An empty ``effective_grids``
    falls back to ``home_grid`` (or, if also None, the first grid in
    ``ci_at_t``).
    """
    effective = clause.effective_grids
    if not effective:
        fallback = clause.home_grid or next(iter(ci_at_t))
        return fallback, float(ci_at_t.get(fallback, 0.0))
    if egress_emissions is None or clause.transfer_size_gb == 0:
        best = min(effective, key=lambda g: ci_at_t.get(g, float("inf")))
        return best, float(ci_at_t[best])
    # Egress-aware selection: penalise transfers from home_grid.
    home = clause.home_grid
    scored: list[tuple[float, str]] = []
    for g in effective:
        ci = float(ci_at_t.get(g, float("inf")))
        if home is None or g == home:
            penalty = 0.0
        else:
            # g CO2eq per GB times the job's data size --- this is a
            # one-time emissions charge, NOT a per-kWh CI shift.  The
            # caller decides how to amortise it; here we surface a
            # comparable scalar by treating it as added emissions
            # per the job's energy (caller passes pre-divided values
            # in egress_emissions if a different convention is wanted).
            penalty = float(
                egress_emissions.get((home, g), 0.0)
            ) * clause.transfer_size_gb
        scored.append((ci + penalty, g))
    score, best = min(scored)
    return best, float(ci_at_t[best])


def assign_t5_spatial_eligibility(
    jobs_df: pd.DataFrame,
    rng: np.random.Generator,
    fraction: float = 0.10,
    default_clause: tuple[str, ...] = ("SE", "CH", "FR", "IT", "DE", "PL"),
) -> pd.DataFrame:
    """Deterministically mark a ``fraction`` of jobs as T5-eligible
    by attaching a default spatial clause.  Used by the spatial sweep
    driver as a baseline against which user-declared clauses can be
    compared.  Returns a copy of ``jobs_df`` with three new columns:
    ``is_spatial_eligible`` (bool), ``spatial_clause`` (str; CSV of
    grid codes for round-trip CSV safety) and ``transfer_size_gb``
    (float; 0.0 by default to make the addition free until calibrated).
    """
    out = jobs_df.copy()
    n = len(out)
    flag = np.zeros(n, dtype=bool)
    if n > 0 and fraction > 0:
        k = max(1, int(round(n * fraction)))
        idx = rng.choice(n, size=k, replace=False)
        flag[idx] = True
    out["is_spatial_eligible"] = flag
    out["spatial_clause"] = [",".join(default_clause) if f else "" for f in flag]
    out["transfer_size_gb"] = 0.0
    return out


# ---------------------------------------------------------------------
# M-Spatial mechanism plug-in
# ---------------------------------------------------------------------
@dataclass
class MSpatialAudit:
    """Audit record produced by the M-Spatial mechanism for one job."""
    job_id: int
    declared_grids: tuple[str, ...]
    realised_grid: str
    home_grid: Optional[str]
    egress_charge_g_co2: float
    nom_ic_violation: bool


def m_spatial_audit(
    job_row: pd.Series,
    realised_grid: str,
    egress_emissions: Mapping[tuple[str, str], float],
) -> MSpatialAudit:
    """One-shot audit: did the realised destination grid lie inside the
    user's declared spatial clause?  If not, mark a NOM-IC violation
    (the dispatcher reset to a fall-back grid; the user owes the
    proportional credit-claw).  Otherwise compute the data-egress
    emissions for honest facility-meter accounting.
    """
    declared_raw = str(job_row.get("spatial_clause", "")).strip()
    declared = tuple(g for g in declared_raw.split(",") if g)
    home = job_row.get("home_grid") or None
    if home is not None:
        home = str(home).upper()
    realised = str(realised_grid).upper()
    transfer_gb = float(job_row.get("transfer_size_gb", 0.0))
    egress_g = 0.0
    if home is not None and home != realised:
        per_gb = float(egress_emissions.get((home, realised), 0.0))
        egress_g = per_gb * transfer_gb
    violation = realised not in declared if declared else False
    return MSpatialAudit(
        job_id=int(job_row.get("job_id", -1)),
        declared_grids=declared,
        realised_grid=realised,
        home_grid=home,
        egress_charge_g_co2=float(egress_g),
        nom_ic_violation=bool(violation),
    )
