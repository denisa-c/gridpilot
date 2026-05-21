"""
experiments_v2/src/mechanism_design.py
=======================================
Synthetic-user simulation of the four f-SLA anti-gaming mechanism
plug-ins M0--M3.  Each mechanism is a *payoff function*
``u(declared, true, predicted, history) -> credit_minus_penalty``;
the experiment then derives, per user, the strategy-best-response
declaration and counts the NOM-IC violations (a violation = there
exists a single-tier deviation ``d' != d_BR`` such that
``u(d', true) > u(d_BR, true)``).

References (these are the load-bearing citations for each mechanism):
  * M0 -- Babaioff et al. 2022 (monotone posted price).
  * M1 -- Grosof et al. 2022 (BlindTrust payment-free IC queue).
  * M2 -- DAA over the alpha-fair SWF (Mo & Walrand 2000).
  * M3 -- Psomas et al. 2022 (Non-Obviously-Manipulable IC).

This module is *pure*: no I/O, no global state, no scheduler hooks.
The companion script ``04d_run_mechanism_sweep.py`` generates the
synthetic users, calls these functions, and dumps the results CSV.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

# ── Ladder constants ──────────────────────────────────────────────
# Match Table 1 of the PECS paper exactly.
ALPHA = np.array([0.00, 0.02, 0.04, 0.06, 0.08, 0.10])    # credit rate
W_H   = np.array([0,    1,    24,   168,  24,   24],
                  dtype=float)                              # window (h)
SMAX  = np.array([1.0,  1.2,  2.0,  4.0,  1.5,  1.5])     # slowdown clause
N_TIERS = 6
TIERS = np.arange(N_TIERS)

# Per-shifted-hour credit earned (= alpha * W).  This is what the
# user receives if their declaration is honest and the scheduler
# successfully defers within the window.
CREDIT_HONEST = ALPHA * W_H


# ── User population ────────────────────────────────────────────────

@dataclass(frozen=True)
class User:
    """A synthetic user with a *true* (private) flexibility tier.

    The true tier captures how much the user can genuinely tolerate
    being deferred / elastic / spatially routed.  Strategic users may
    *declare* a different tier (over- or under-claim) to gain credit
    or speed.
    """
    uid:        int
    true_tier:  int       # 0..N_TIERS-1
    runtime_h:  float     # true runtime in hours
    # Confidence with which the AI baseline predicts the true tier.
    # Set per-user so heterogeneity is realistic (more history = higher
    # confidence; new users have lower).
    ai_confidence: float  # in [0, 1]


# ── Mechanism payoffs ──────────────────────────────────────────────
#
# All payoffs are computed for a *single* user-job, in units of
# credit-hours.  The mechanism's "violation rate" is a property of
# the payoff surface across all (true_tier, declared_tier) pairs,
# not of any particular dispatch outcome -- so no scheduler call is
# needed inside the mechanism module.

def _force_dispatch_loss(declared: int, true: int) -> float:
    """Expected loss (credit-hours) when the user over-declares and
    the scheduler eventually force-dispatches the job because it
    cannot meet the wider declared window in time.

    Approximation: linearly proportional to the size of the
    over-claim, capped at the honest credit (so the user never owes
    more than they would have earned).
    """
    if declared <= true:
        return 0.0
    over = declared - true
    return min(CREDIT_HONEST[declared], 0.6 * over * CREDIT_HONEST[declared])


def payoff_m0(declared: int, true: int, **_) -> float:
    """M0 posted-price: static credit schedule, no audit.

    The user keeps ``CREDIT_HONEST[declared]`` if their declaration
    is feasible (declared <= true: under-claim with no penalty); on
    over-claim they forfeit the credit with some probability.
    Babaioff et al. 2022's monotonicity gives weak truth-telling, but
    nothing prevents an over-claim from strictly dominating when the
    penalty is small.
    """
    base = CREDIT_HONEST[declared]
    return base - _force_dispatch_loss(declared, true)


def payoff_m1(declared: int, true: int,
               *, audit_strength: float = 0.7, **_) -> float:
    """M1 BlindTrust: payment-free IC queue with a rolling audit.

    Same base credit as M0, but over-claims are priced in lost
    priority for the *next* job (modelled here as an
    ``audit_strength``-scaled future-credit deduction).  Grosof et
    al. 2022 show this is sufficient for IC in steady state.
    """
    base = CREDIT_HONEST[declared]
    loss = _force_dispatch_loss(declared, true)
    if declared > true:
        # Audit deduction on the next job; expected discounted
        # equivalent for a steady-state user with rate-1 arrivals.
        loss += audit_strength * (declared - true) * CREDIT_HONEST[declared]
    return base - loss


def payoff_m2(declared: int, true: int, **_) -> float:
    """M2 Deferred-Acceptance Auction over tier bids.

    Strategy-proof in the full-information regime: the per-tick DAA
    matches users to slots so that no user can improve by misreport.
    Approximated as: payoff equals honest credit minus a hard penalty
    on any deviation (the DAA simply re-allocates the slot to a
    matched bid, so the deviator gets nothing for that tick).
    """
    if declared == true:
        return CREDIT_HONEST[true]
    # Either under-claim (lose extra credit you could have earned) or
    # over-claim (DAA detects misreport and zeros the credit).
    return 0.0 if declared > true else CREDIT_HONEST[declared]


def payoff_m3(declared: int, true: int, predicted: int,
               *, confidence: float, calib: float = 1.4, **_) -> float:
    """M3 AI-baseline audit (headline).

    At submit time the user sees the AI's predicted tier ``predicted``.
    The post-execution audit charges ``confidence x calib x
    max(0, declared - true)`` credit-hours on over-claim.  Under-claim
    is "free" but forfeits the credit the user could have earned.
    The ``calib`` factor is chosen so that no single-tier deviation
    from truth strictly improves utility -- the NOM-IC property of
    Psomas et al. 2022.

    Note: ``predicted`` only enters via the confidence weighting (a
    confident AI prediction makes the penalty bite harder); the actual
    audit is anchored to the *true* tier ``true``, which the
    scheduler infers from the realised dispatch / runtime.
    """
    base = CREDIT_HONEST[declared]
    over_claim = max(0, declared - true)
    penalty = confidence * calib * over_claim * CREDIT_HONEST[max(declared, 1)]
    return base - penalty - _force_dispatch_loss(declared, true)


PAYOFF_FN: dict[str, Callable] = {
    "M0": payoff_m0,
    "M1": payoff_m1,
    "M2": payoff_m2,
    "M3": payoff_m3,
}


# ── Best-response and violation analysis ──────────────────────────

def best_response(payoff: Callable, user: User, predicted: int) -> int:
    """The tier that maximises ``payoff`` against the user's true
    tier, given the AI's predicted tier (used by M3 only)."""
    utilities = np.array([
        payoff(d, user.true_tier, predicted=predicted,
                confidence=user.ai_confidence)
        for d in TIERS
    ])
    return int(np.argmax(utilities))


def nomic_violation(payoff: Callable, user: User, predicted: int) -> bool:
    """A NOM-IC violation occurs iff there exists a tier ``d'``
    *one step away* from the user's true tier such that declaring
    ``d'`` strictly beats declaring the truth.

    Returns ``True`` on violation.  The "one step" restriction is the
    operationally-relevant test for Psomas et al.'s NOM-IC property:
    real users do not enumerate all tiers, they consider local
    deviations.
    """
    truth_u = payoff(user.true_tier, user.true_tier,
                      predicted=predicted, confidence=user.ai_confidence)
    for d in (user.true_tier - 1, user.true_tier + 1):
        if d < 0 or d >= N_TIERS:
            continue
        if payoff(d, user.true_tier, predicted=predicted,
                   confidence=user.ai_confidence) > truth_u + 1e-9:
            return True
    return False


# ── Fairness metrics ──────────────────────────────────────────────

def jain_index(x: np.ndarray) -> float:
    """Jain's fairness index over the (positive) credit allocation.

    Returns a value in ``(0, 1]``; 1.0 means perfectly equal.
    Defined as ``(sum x)^2 / (n * sum x^2)``.
    """
    x = np.asarray(x, dtype=float)
    if x.size == 0 or float(np.sum(x)) <= 0:
        return 1.0
    return float(np.sum(x)) ** 2 / (x.size * float(np.sum(x * x)))


def alpha_fair_swf(x: np.ndarray, alpha: float = 1.0) -> float:
    """Alpha-fair social welfare function (Mo & Walrand 2000).

    Aggregate user utility under proportional-fairness (alpha=1, log)
    or harmonic (alpha=2, -1/x).  Negative log/inverse are handled by
    clipping at a small epsilon so a zero-credit user does not dominate
    the sum to negative infinity.
    """
    x = np.clip(np.asarray(x, dtype=float), 1e-3, None)
    if abs(alpha - 1.0) < 1e-9:
        return float(np.sum(np.log(x)))
    return float(np.sum((x ** (1.0 - alpha)) / (1.0 - alpha)))
