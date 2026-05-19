"""
src/scheduler/fsla.py
---------------------

Flexible-SLA (f-SLA) tier ladder, synthetic-prior generator, and paired
all-rigid vs declared-tier replay driver.

Reuses the existing PUE-aware scheduler (`replay_proact_opt_pue`)
without modification: per-job deferrability is encoded by the
`d_max_hours` column of the input jobs DataFrame, which the existing
scheduler already consumes in its inner dispatch loop.

Tier ladder
~~~~~~~~~~~
The four-tier f-SLA ladder is:

  T0 (Rigid):                    d_max_h =   0,   slowdown_max = 1.0,   credit/h = 0.00
  T1 (Hour-deferrable):          d_max_h =   1,   slowdown_max = 1.2,   credit/h = 0.02
  T2 (Day-deferrable):           d_max_h =  24,   slowdown_max = 2.0,   credit/h = 0.04
  T3 (Checkpointable-multi-day): d_max_h = 168,   slowdown_max = 4.0,   credit/h = 0.06
                                                       + 0.5 fixed checkpoint bonus

Synthetic prior
~~~~~~~~~~~~~~~
Tier assignments are sampled from a Dirichlet(α) distribution over the
(len(TIER_NAMES)-1)-simplex.  The default concentration
alpha = DEFAULT_ALPHA = (3.0, 3.0, 2.5, 1.5, 1.0) gives expectation
E[pi] = alpha / sum(alpha) (biased toward T0/T1 to be conservative)
and variance ~ 0.02 per component.  Larger sum(alpha) -> tighter
prior; alpha/k -> flatter.

Length conditioning
~~~~~~~~~~~~~~~~~~~
Two integrity rules are enforced after the raw Dirichlet draw, so that
the synthetic prior produces tier assignments that are physically
plausible for any given job:

  - Jobs with run_time > 24 h cannot be tier T0 (rigid is implausible
    for jobs exceeding the diurnal CI cycle); they are re-sampled from
    {T1, T2, T3} with the prior re-normalised over the remaining tiers.
  - Jobs with run_time ≤ 1 h cannot be tier ≥ T2 (a 7-day window has no
    benefit for sub-hour jobs); they are re-sampled from {T0, T1}.

Citation
~~~~~~~~
The f-SLA contract and this Monte Carlo + bootstrap protocol back
Section 5.4 ("The f-SLA Contract: Eliciting Truthful Flexibility") and
Finding 3 of the PECS 2026 paper.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

# Import the existing scheduler (no modification needed)
try:
    from scheduler.scheduler_pue_aware import replay_proact_opt_pue
except ModuleNotFoundError:  # pragma: no cover
    # When called from outside src/ entrypoints
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scheduler.scheduler_pue_aware import replay_proact_opt_pue  # noqa: F401


# ─────────────────────────────────────────────────────────────────────
# Tier definitions
# ─────────────────────────────────────────────────────────────────────
#: Six-tier ladder.  T4 (Elastic burst) is the CarbonScaler-style
#: replica-scaling tier.  T5 (Spatial) is the GAIA-style geo-shifting
#: tier introduced as a sketch in the PECS paper: a T5 job carries a
#: user-declared non-empty spatial clause G_j (set of acceptable grid
#: codes), and the dispatcher routes it to whichever grid in G_j is
#: cleanest at dispatch time, charging the inter-site data-egress
#: emissions against the IT-side savings.  The full multi-grid
#: evaluation of T5 lives in the C2 follow-on paper; the constants
#: and the per-job ``spatial_clause`` schema column ship in v1.0 so
#: future replays can opt in without a kit rebuild.
TIER_NAMES = ("T0", "T1", "T2", "T3", "T4", "T5")
T_RIGID, T_HOUR, T_DAY, T_WEEK, T_ELASTIC, T_SPATIAL = 0, 1, 2, 3, 4, 5

#: Default Dirichlet concentration; biases toward T1 with small mass
#: on T4 and T5.  Sum = 11.5.  T5 mass is intentionally low (0.5):
#: the spatial tier is the most demanding of the six and most jobs
#: do not satisfy its stateless / data-portable preconditions.
DEFAULT_ALPHA = (3.0, 3.0, 2.5, 1.5, 1.0, 0.5)

#: tier -> (deferral / elastic / spatial window in h, max-acceptable-
#: slowdown clause, service-credit rate per shifted hour).  T3 gets a
#: fixed checkpoint bonus; T4 trades the deferral window for an
#: elastic-replica window (0.5x..2.0x); T5 trades it for a spatial
#: window (route across grids in G_j, charged at the inter-site
#: egress-emissions YAML in configs/network/egress_emissions.yaml).
TIER_WINDOW_H = {0: 0,   1: 1,    2: 24,  3: 168, 4: 24,   5: 24}
TIER_SLOWMAX  = {0: 1.0, 1: 1.2,  2: 2.0, 3: 4.0, 4: 1.5,  5: 1.5}
TIER_CREDIT_H = {0: 0.0, 1: 0.02, 2: 0.04, 3: 0.06, 4: 0.08, 5: 0.10}
T3_FIXED_CHECKPOINT_BONUS = 0.5
#: T4 elastic-burst envelope: minimum and maximum replica multipliers
#: the scheduler is allowed to apply during the dirtiest / cleanest
#: portion of the look-ahead window.
T4_REPLICA_MIN, T4_REPLICA_MAX = 0.5, 2.0

LONG_JOB_THRESHOLD_S = 24 * 3600   # > 24 h → cannot be T0
SHORT_JOB_THRESHOLD_S = 1 * 3600   # ≤ 1 h  → cannot be ≥ T2


# ─────────────────────────────────────────────────────────────────────
# Prior generator
# ─────────────────────────────────────────────────────────────────────
@dataclass
class FSLAPriorReport:
    """Audit record of one tier-assignment pass.

    Persisted in the per-seed JSON for traceability.
    """
    seed: int
    pi: list[float]
    n_jobs: int
    n_long_reassigned_from_T0: int
    n_short_reassigned_from_high_tier: int
    tier_counts: dict[str, int]
    tier_fractions: dict[str, float]


def sample_prior(
    alpha: tuple[float, ...] = DEFAULT_ALPHA,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """One Dirichlet draw → one tier-prior π on the (len(TIER_NAMES)-1)-simplex.

    Parameters
    ----------
    alpha : tuple of ``len(TIER_NAMES)`` positive floats
        Dirichlet concentration.  The current ladder is T0..T4 with
        default ``DEFAULT_ALPHA = (3.0, 3.0, 2.5, 1.5, 1.0)``.
    rng : np.random.Generator, optional
        Source of randomness. If None, uses ``np.random.default_rng()``.

    Returns
    -------
    pi : (len(TIER_NAMES),) array of floats summing to 1.0
        Probability mass for tiers (T0, T1, T2, T3, T4).
    """
    rng = np.random.default_rng() if rng is None else rng
    n_tiers = len(TIER_NAMES)
    if len(alpha) != n_tiers or any(a <= 0 for a in alpha):
        raise ValueError(f"alpha must be {n_tiers} positive floats; got {alpha!r}")
    pi = rng.dirichlet(alpha)
    assert abs(pi.sum() - 1.0) < 1e-9, f"Dirichlet draw not on simplex: {pi}"
    return pi


def assign_tiers(
    jobs_df: pd.DataFrame,
    pi: np.ndarray,
    rng: Optional[np.random.Generator] = None,
    *,
    length_conditioned: bool = True,
    runtime_col: str = "run_time",
) -> tuple[pd.DataFrame, FSLAPriorReport]:
    """Per-job tier assignment from a fixed prior π, with optional
    length conditioning.

    Returns a copy of ``jobs_df`` augmented with the columns:
        ``tier``           int in {0, 1, 2, 3, 4}  (T0..T4 inclusive)
        ``d_max_hours``    deferral window from the tier ladder
        ``slowdown_max``   QoS clause from the tier ladder
        ``service_credit_h`` per-hour credit rate
        ``checkpoint_bonus`` 0.5 for T3 jobs, 0 otherwise

    Plus an FSLAPriorReport summarising the assignment for traceability.
    """
    rng = np.random.default_rng() if rng is None else rng
    n = len(jobs_df)
    if n == 0:
        empty_report = FSLAPriorReport(
            seed=int(rng.integers(0, 2**31 - 1)),
            pi=list(map(float, pi)),
            n_jobs=0,
            n_long_reassigned_from_T0=0,
            n_short_reassigned_from_high_tier=0,
            tier_counts={k: 0 for k in TIER_NAMES},
            tier_fractions={k: 0.0 for k in TIER_NAMES},
        )
        return jobs_df.copy(), empty_report

    if abs(pi.sum() - 1.0) > 1e-6:
        raise ValueError(
            f"pi must lie on the {len(TIER_NAMES)-1}-simplex; sum={pi.sum()}"
        )

    # Raw draw
    tiers = rng.choice(len(TIER_NAMES), size=n, p=pi)

    n_long_reassigned = 0
    n_short_reassigned = 0

    if length_conditioned:
        runtimes = jobs_df[runtime_col].values
        long_mask = runtimes > LONG_JOB_THRESHOLD_S
        short_mask = runtimes <= SHORT_JOB_THRESHOLD_S

        # Forbid T0 for long jobs: re-sample from the remaining tiers
        # (T1..T_last).  Using ``len(TIER_NAMES)`` keeps this correct when
        # the ladder is extended (we now ship T0..T4 including T4 elastic
        # burst); previously this list was hard-coded as
        # ``[T_HOUR, T_DAY, T_WEEK]`` and broke as soon as ``pi`` grew.
        long_t0 = long_mask & (tiers == T_RIGID)
        if long_t0.any():
            high_tier_ids = list(range(T_HOUR, len(TIER_NAMES)))
            p_high = pi[1:] / pi[1:].sum()
            new_tiers = rng.choice(high_tier_ids,
                                   size=int(long_t0.sum()), p=p_high)
            tiers[long_t0] = new_tiers
            n_long_reassigned = int(long_t0.sum())

        # Forbid T2..T_last for short jobs: re-sample from {T0, T1}.
        short_high = short_mask & (tiers >= T_DAY)
        if short_high.any():
            p_low = pi[:2] / pi[:2].sum()
            new_tiers = rng.choice([T_RIGID, T_HOUR],
                                    size=int(short_high.sum()), p=p_low)
            tiers[short_high] = new_tiers
            n_short_reassigned = int(short_high.sum())

    out = jobs_df.copy()
    out["tier"] = tiers
    out["d_max_hours"] = pd.Series(tiers).map(TIER_WINDOW_H).values
    out["slowdown_max"] = pd.Series(tiers).map(TIER_SLOWMAX).values
    out["service_credit_h"] = pd.Series(tiers).map(TIER_CREDIT_H).values
    out["checkpoint_bonus"] = (tiers == T_WEEK).astype(float) * T3_FIXED_CHECKPOINT_BONUS

    counts = {name: int((tiers == idx).sum()) for idx, name in enumerate(TIER_NAMES)}
    fractions = {name: counts[name] / n for name in TIER_NAMES}
    report = FSLAPriorReport(
        seed=int(rng.integers(0, 2**31 - 1)),
        pi=list(map(float, pi)),
        n_jobs=n,
        n_long_reassigned_from_T0=n_long_reassigned,
        n_short_reassigned_from_high_tier=n_short_reassigned,
        tier_counts=counts,
        tier_fractions=fractions,
    )
    return out, report


# ─────────────────────────────────────────────────────────────────────
# Paired replay (the f-SLA counterfactual)
# ─────────────────────────────────────────────────────────────────────
def _to_pct(co2_g: float, baseline_g: float) -> float:
    if baseline_g <= 0:
        return 0.0
    return float(100.0 * (1.0 - co2_g / baseline_g))


def replay_pair(
    jobs_df: pd.DataFrame,
    ci_df: pd.DataFrame,
    t_amb_series: pd.Series,
    pi: np.ndarray,
    seed: int,
    *,
    cooling_params=None,
    fcfs_baseline: Optional[dict] = None,
    length_conditioned: bool = True,
    runtime_col: str = "run_time",
    **scheduler_kwargs,
) -> dict:
    """Run paired all-rigid vs declared-tier replays for one Monte Carlo
    seed, computing the IT- and facility-CO₂ Δ between them.

    Both replays use the SAME existing ``replay_proact_opt_pue``
    scheduler.  Only the per-job ``d_max_hours`` differs:
      - all-rigid baseline: every job has d_max_hours = 0 (forced rigid)
      - declared-tier baseline: per-job d_max_hours from the f-SLA tier

    Returns a dict with the per-baseline raw scheduler outputs plus the
    headline Δs.
    """
    rng = np.random.default_rng(seed)

    # ─── All-rigid baseline ───
    jobs_rigid = jobs_df.copy()
    jobs_rigid["d_max_hours"] = 0
    jobs_rigid["tier"] = T_RIGID
    res_rigid = replay_proact_opt_pue(
        jobs_rigid, ci_df, t_amb_series,
        cooling_params=cooling_params,
        max_delay_h=0,
        seed=seed,
        **scheduler_kwargs,
    )

    # ─── Declared-tier baseline ───
    jobs_decl, prior_report = assign_tiers(
        jobs_df, pi, rng=rng,
        length_conditioned=length_conditioned, runtime_col=runtime_col,
    )
    res_decl = replay_proact_opt_pue(
        jobs_decl, ci_df, t_amb_series,
        cooling_params=cooling_params,
        max_delay_h=int(max(jobs_decl["d_max_hours"].max(), 1)),  # global cap = max per-job window
        seed=seed,
        **scheduler_kwargs,
    )

    # ─── FCFS baseline for IT/facility CO₂ percentage reduction ───
    # If the caller did not supply one, use the all-rigid scheduler as
    # the reference (its deferral budget is 0 so its dispatch matches
    # FCFS to within the elasticity / power-cap channels).
    fcfs_it_g = fcfs_baseline["co2_g"] if fcfs_baseline else res_rigid["co2_g"]
    fcfs_fac_g = fcfs_baseline["facility_co2_g"] if fcfs_baseline else res_rigid["facility_co2_g"]

    rigid_it_pct = _to_pct(res_rigid["co2_g"], fcfs_it_g)
    rigid_fac_pct = _to_pct(res_rigid["facility_co2_g"], fcfs_fac_g)
    decl_it_pct = _to_pct(res_decl["co2_g"], fcfs_it_g)
    decl_fac_pct = _to_pct(res_decl["facility_co2_g"], fcfs_fac_g)

    p95_rigid = float(np.percentile(res_rigid["slowdowns"], 95))
    p95_decl = float(np.percentile(res_decl["slowdowns"], 95))

    return {
        "seed": seed,
        "pi": [float(x) for x in pi],
        "prior_report": prior_report,
        "all_rigid": {
            "co2_g": res_rigid["co2_g"],
            "facility_co2_g": res_rigid["facility_co2_g"],
            "energy_kwh": res_rigid["energy_kwh"],
            "p95_slowdown": p95_rigid,
            "avg_pue": res_rigid["avg_pue"],
            "it_co2_pct": rigid_it_pct,
            "facility_co2_pct": rigid_fac_pct,
        },
        "declared_tier": {
            "co2_g": res_decl["co2_g"],
            "facility_co2_g": res_decl["facility_co2_g"],
            "energy_kwh": res_decl["energy_kwh"],
            "p95_slowdown": p95_decl,
            "avg_pue": res_decl["avg_pue"],
            "it_co2_pct": decl_it_pct,
            "facility_co2_pct": decl_fac_pct,
        },
        "delta_it_pp": decl_it_pct - rigid_it_pct,
        "delta_facility_pp": decl_fac_pct - rigid_fac_pct,
        "p95_match": abs(p95_decl - p95_rigid) < 0.5,
    }


# ─────────────────────────────────────────────────────────────────────
# Bootstrap CI utility
# ─────────────────────────────────────────────────────────────────────
def bootstrap_ci(
    values: np.ndarray,
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    rng: Optional[np.random.Generator] = None,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI on the mean of ``values``.

    Returns
    -------
    mean : float
    lower : float
        ``(1 − confidence)/2`` percentile of the bootstrap mean distribution.
    upper : float
        ``(1 + confidence)/2`` percentile.
    """
    rng = np.random.default_rng() if rng is None else rng
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return 0.0, 0.0, 0.0
    n = values.size
    idx = rng.integers(0, n, size=(n_resamples, n))
    samples = values[idx].mean(axis=1)
    alpha = 1.0 - confidence
    lo = float(np.percentile(samples, 100.0 * alpha / 2.0))
    hi = float(np.percentile(samples, 100.0 * (1.0 - alpha / 2.0)))
    return float(values.mean()), lo, hi
