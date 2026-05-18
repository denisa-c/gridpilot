"""
src/scheduler/swf.py
--------------------
Social welfare functions and fairness metrics for the f-SLA policy
matrix evaluation (PECS Paper B §5/§7, Finding 4).

Implements the four-function family of Chen, Hua, Long & Zhu (2023,
"A Guide to Formulating Fairness in Optimization", *Manufacturing &
Service Operations Management*):

  - utilitarian       SWF = Σ_i u_i
  - Nash              SWF = Π_i u_i      (equivalent to Σ log u_i)
  - leximin           lexicographic max-min
  - α-fair            SWF = Σ_i u_i^{1−α} / (1−α)  for α ≥ 0, α ≠ 1
                      → utilitarian as α → 0; Nash at α = 1; leximin as α → ∞

Also exposes the Jain fairness index (Jain, Chiu & Hawe 1984) on a
per-user wait-time vector, used as the QoS-feasibility check in
hypothesis H3 of FSLA_GAMIFICATION_POC_PLAN.md.

All functions are pure (no I/O, no side-effects) and handle the
degenerate u_i ≤ 0 case by clipping at a small ε to keep Nash and
α-fair well-defined.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

EPS = 1e-9


def _to_clipped_array(u: Iterable[float]) -> np.ndarray:
    """Coerce to ndarray and clip non-positive entries to EPS.

    Negative or zero per-user utilities break Nash and α-fair welfare
    (log(0), 0^{1−α} for α > 1). Clipping at EPS preserves ordering
    and produces a well-defined real value; this is the standard
    convention in the fair-resource-allocation literature.
    """
    arr = np.asarray(list(u), dtype=float)
    return np.maximum(arr, EPS)


# ─────────────────────────────────────────────────────────────────────
# Social welfare functions
# ─────────────────────────────────────────────────────────────────────
def swf_utilitarian(u: Iterable[float]) -> float:
    """Total-utility social welfare (Chen 2023 §3.1)."""
    return float(np.sum(_to_clipped_array(u)))


def swf_nash(u: Iterable[float]) -> float:
    """Nash social welfare, computed in log-space for numerical stability.

    Returns the geometric mean to the n-th power, i.e. the product of
    utilities. For comparison across n-of-users values, use
    ``np.exp(np.log(...).mean())`` (the geometric mean) instead.
    """
    arr = _to_clipped_array(u)
    if arr.size == 0:
        return 0.0
    return float(np.exp(np.log(arr).sum()))


def swf_leximin(u: Iterable[float]) -> tuple[float, ...]:
    """Leximin social welfare returned as the *sorted ascending tuple*.

    Comparing two leximin tuples is done lexicographically: tuple A is
    preferred to tuple B iff A[0] > B[0], or A[0] == B[0] and the
    sub-tuples A[1:] > B[1:] leximin.
    """
    arr = _to_clipped_array(u)
    return tuple(float(x) for x in np.sort(arr))


def swf_alpha_fair(u: Iterable[float], alpha: float) -> float:
    """α-fair social welfare (Mo & Walrand 2000; Chen 2023 §3.4).

    SWF_α(u) = Σ_i u_i^{1−α} / (1−α)  for α ≥ 0, α ≠ 1
             = Σ_i log u_i             for α = 1 (Nash limit)

    α = 0  → utilitarian
    α = 1  → Nash (proportional fairness)
    α = 2  → "minimum potential delay" fairness
    α → ∞  → leximin
    """
    arr = _to_clipped_array(u)
    if abs(alpha - 1.0) < EPS:
        return float(np.log(arr).sum())
    return float(np.power(arr, 1.0 - alpha).sum() / (1.0 - alpha))


# ─────────────────────────────────────────────────────────────────────
# Fairness metrics
# ─────────────────────────────────────────────────────────────────────
def jain_fairness(x: Iterable[float]) -> float:
    """Jain's fairness index on a non-negative allocation vector.

    J(x) = (Σ x_i)² / (n · Σ x_i²)   ∈   [1/n, 1]

    1.0  = perfectly fair (equal allocation)
    1/n  = maximally unfair (one user takes everything)

    The conventional input is per-user *throughput* (higher is better).
    For latency-style metrics (where lower is better), invert first:
    pass ``1 / max(wait_time, EPS)``.
    """
    arr = np.asarray(list(x), dtype=float)
    if arr.size == 0:
        return 1.0
    arr = np.clip(arr, 0.0, None)
    s1 = float(arr.sum())
    s2 = float((arr ** 2).sum())
    if s2 < EPS:
        return 1.0
    return (s1 * s1) / (arr.size * s2)


def gini(x: Iterable[float]) -> float:
    """Gini coefficient on a non-negative allocation vector.

    G(x) ∈ [0, 1]; 0 = perfect equality, 1 = perfect inequality.
    Reported alongside Jain in the §7 results table as a complementary
    fairness lens (Jain rewards equality; Gini penalises tail mass).
    """
    arr = np.sort(np.asarray(list(x), dtype=float))
    arr = np.clip(arr, 0.0, None)
    n = arr.size
    if n == 0 or arr.sum() < EPS:
        return 0.0
    idx = np.arange(1, n + 1)
    return float((2 * (idx * arr).sum() - (n + 1) * arr.sum()) / (n * arr.sum()))


# ─────────────────────────────────────────────────────────────────────
# Per-user utility builder
# ─────────────────────────────────────────────────────────────────────
def per_user_utility(
    completed_jobs: list[dict],
    *,
    over_shoot_price: float = 0.02,
) -> dict[str, float]:
    """Aggregate per-user utility from a completed-job list.

    u_i = Σ_{j ∈ user i} ( service_credit_h_j × deferred_hours_j
                            + checkpoint_bonus_j
                            − over_shoot_price × max(s_j − s_j^max, 0) )

    The ``over_shoot_price`` defaults to α₁ (= 0.02 cluster-credit-hours
    per hour) so that one hour of slowdown over-shoot exactly cancels
    one hour of T1 deferral credit. This keeps the utility scale
    interpretable in cluster-credit-hours and makes the social welfare
    numbers comparable across mechanisms.
    """
    utilities: dict[str, float] = {}
    for j in completed_jobs:
        user = str(j.get("user", "anonymous"))
        deferred_h = max(0.0, (j.get("start", 0) - j.get("submit", 0)) / 3600.0)
        credit = float(j.get("service_credit_h", 0.0)) * deferred_h
        credit += float(j.get("checkpoint_bonus", 0.0))
        s_actual = float(j.get("slowdown", 1.0))
        s_max = float(j.get("slowdown_max", 1.0))
        over = max(0.0, s_actual - s_max)
        utilities[user] = utilities.get(user, 0.0) + credit - over_shoot_price * over
    return utilities
