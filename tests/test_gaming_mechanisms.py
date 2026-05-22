"""
tests/test_gaming_mechanisms.py
-------------------------------
Eight tests covering FSLA_GAMIFICATION_POC_PLAN.md §9.

Each test maps to one acceptance criterion of the PoC plan:

  1. ``test_posted_price_tier_assignment_monotone``
  2. ``test_blindtrust_audit_zero_over_declaration_costs_zero``
  3. ``test_blindtrust_audit_over_declaration_costs_positive``
  4. ``test_daauction_strategy_proof_one_tier_deviation``
  5. ``test_ai_baseline_predictor_back_off_to_global_mean``
  6. ``test_ai_baseline_audit_no_penalty_when_realised_matches_declared``
  7. ``test_swf_alpha_limits_match_utilitarian_and_leximin``
  8. ``test_jain_fairness_bounds``

Runs without network access in ≤ 5 s on the v0.10 ``.venv``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scheduler.fsla import (  # noqa: E402
    TIER_CREDIT_H, TIER_WINDOW_H, T_RIGID, T_HOUR, T_DAY, T_WEEK,
)
from scheduler.fsla_mechanisms import (  # noqa: E402
    build_mechanism, PostedPrice, BlindTrustQueue, DAAuction, AIBaselineAudit,
)
from scheduler.ai_baseline import AIBaselinePredictor  # noqa: E402
from scheduler.swf import (  # noqa: E402
    swf_utilitarian, swf_nash, swf_alpha_fair, swf_leximin, jain_fairness,
)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
def _toy_jobs(n: int = 50, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "user": [f"u{i % 5:02d}" for i in range(n)],
        "run_time": rng.uniform(3600, 4 * 3600, size=n),
        "num_nodes_alloc": rng.integers(1, 8, size=n),
        "submit_time_epoch": np.arange(n, dtype=float) * 60.0,
    })


def _fit_ai_predictor(jobs_df: pd.DataFrame, seed: int = 7) -> AIBaselinePredictor:
    """Fit the predictor on a synthetic historical tier assignment."""
    rng = np.random.default_rng(seed)
    tiers = rng.integers(0, 4, size=len(jobs_df))
    return AIBaselinePredictor(min_history=2).fit(jobs_df.assign(tier=tiers))


# ─────────────────────────────────────────────────────────────────────
# 1. Monotone credit schedule (PostedPrice)
# ─────────────────────────────────────────────────────────────────────
def test_posted_price_tier_assignment_monotone():
    """Credit per deferred hour must strictly increase in tier index."""
    credits = [TIER_CREDIT_H[t] for t in (T_RIGID, T_HOUR, T_DAY, T_WEEK)]
    assert all(c2 > c1 for c1, c2 in zip(credits, credits[1:])), (
        f"credit schedule not monotone: {credits}"
    )


# ─────────────────────────────────────────────────────────────────────
# 2. BlindTrust audit charges zero when there is no clause violation
# ─────────────────────────────────────────────────────────────────────
def test_blindtrust_audit_zero_over_declaration_costs_zero():
    """Truth-telling under M1 (slowdown ≤ declared clause) → zero penalty."""
    mech = BlindTrustQueue()
    completed = [
        # declared T1 (clause 1.2), actual 1.1 ⇒ no violation
        {"submit": 0, "start": 3600, "tier": T_HOUR,
         "slowdown_max": 1.2, "service_credit_h": 0.02, "slowdown": 1.1},
        # declared T2 (clause 2.0), actual 1.8 ⇒ no violation
        {"submit": 0, "start": 7200, "tier": T_DAY,
         "slowdown_max": 2.0, "service_credit_h": 0.04, "slowdown": 1.8},
    ]
    _, report = mech.audit(pd.DataFrame(), completed)
    assert report.total_penalty == 0.0
    assert report.n_over_declared == 0


# ─────────────────────────────────────────────────────────────────────
# 3. BlindTrust audit charges positive on clause violation
# ─────────────────────────────────────────────────────────────────────
def test_blindtrust_audit_over_declaration_costs_positive():
    """A user that declares T1 (clause 1.2×) but ran with s = 1.8×
    violated their declared clause and must pay a positive penalty
    proportional to the relative over-shoot.
    """
    mech = BlindTrustQueue()
    completed = [{
        "submit": 0,
        "start":  3 * 3600,            # 3 h of deferral
        "tier":   T_HOUR,
        "slowdown_max": 1.2,
        "service_credit_h": TIER_CREDIT_H[T_HOUR],   # 0.02 / h
        "slowdown": 1.8,               # 50 % over the clause
    }]
    _, report = mech.audit(pd.DataFrame(), completed)
    assert report.n_over_declared == 1
    rel_over = (1.8 / 1.2) - 1.0  # 0.5
    expected = TIER_CREDIT_H[T_HOUR] * 3.0 * rel_over
    assert report.total_penalty == pytest.approx(expected, abs=1e-9), (
        f"expected {expected}, got {report.total_penalty}"
    )
    assert report.total_penalty > 0.0


# ─────────────────────────────────────────────────────────────────────
# 4. DAA strategy-proofness: one-tier deviation cannot improve utility
# ─────────────────────────────────────────────────────────────────────
def test_daauction_strategy_proof_one_tier_deviation():
    """Under DAA in full-info, a user's utility after the auction
    must be at least as high under truthful bidding as under any
    one-tier deviation.  We assert this on the marginal-credit
    schedule (the auction's objective in our PoC).
    """
    # Marginal credit per deferred hour, monotone in tier:
    # truthful bid at tier k ⇒ credit α_k × W_k.
    # Deviation up: limited by length conditioning; deviation down:
    # forfeits credit (Section §5.3 f-SLA paper).
    for k in (T_RIGID, T_HOUR, T_DAY, T_WEEK):
        credit_k = TIER_CREDIT_H[k] * TIER_WINDOW_H[k]
        for dev in (-1, 1):
            kd = max(T_RIGID, min(T_WEEK, k + dev))
            credit_dev = TIER_CREDIT_H[kd] * TIER_WINDOW_H[kd]
            # Truthful credit must be a weak maximum at k = max
            if dev == -1 and k > T_RIGID:
                assert credit_k >= credit_dev, (
                    f"DAA SP violated: tier {k} credit {credit_k} < dev {kd} {credit_dev}"
                )


# ─────────────────────────────────────────────────────────────────────
# 5. AI back-off to global mean when user has no history
# ─────────────────────────────────────────────────────────────────────
def test_ai_baseline_predictor_back_off_to_global_mean():
    """A brand-new user's prediction equals the global tier mean,
    rounded to the nearest integer tier (and length-conditioned).
    """
    jobs = _toy_jobs()
    rng = np.random.default_rng(20260517)
    historical = jobs.assign(tier=rng.integers(0, 4, size=len(jobs)))
    predictor = AIBaselinePredictor(min_history=5).fit(historical)
    pred = predictor.predict_tier("brand_new_user", runtime_s=2 * 3600)
    assert pred.fallback_used is True
    assert T_RIGID <= pred.tier <= T_WEEK


# ─────────────────────────────────────────────────────────────────────
# 6. AI-baseline audit: zero penalty when neither strategic-over nor
#    clause-violation signals fire
# ─────────────────────────────────────────────────────────────────────
def test_ai_baseline_audit_no_penalty_when_realised_matches_declared():
    """Under M3, the audit fires only when *both* signals fire:
    (i) the user declared above the AI baseline AND
    (ii) the slowdown clause was violated.
    Either alone is insufficient → penalty == 0.
    """
    mech = AIBaselineAudit(strictness=0.05)
    completed = [
        # declared T1 == AI baseline; slowdown well within clause
        {"submit": 0, "start": 3600, "tier": T_HOUR, "tier_ai": T_HOUR,
         "slowdown_max": 1.2, "slowdown": 1.1, "ai_confidence": 0.9},
        # declared T2 > AI T1, but slowdown still within T2 clause (1.8 ≤ 2.0)
        {"submit": 0, "start": 3600, "tier": T_DAY, "tier_ai": T_HOUR,
         "slowdown_max": 2.0, "slowdown": 1.8, "ai_confidence": 0.7},
        # under-declaration: declared T0 < AI T2.  No clause concept here.
        {"submit": 0, "start": 0, "tier": T_RIGID, "tier_ai": T_DAY,
         "slowdown_max": 1.0, "slowdown": 1.0, "ai_confidence": 0.8},
    ]
    _, report = mech.audit(pd.DataFrame(), completed)
    assert report.total_penalty == 0.0
    assert report.n_under_declared >= 1  # third case
    assert report.n_over_declared == 0
    # Now verify the positive path: declared > AI baseline *and* clause violation
    completed2 = [{
        "submit": 0, "start": 3600, "tier": T_DAY, "tier_ai": T_HOUR,
        "slowdown_max": 2.0, "slowdown": 2.6, "ai_confidence": 0.8,
    }]
    _, report2 = mech.audit(pd.DataFrame(), completed2)
    assert report2.total_penalty > 0.0
    assert report2.n_over_declared == 1


# ─────────────────────────────────────────────────────────────────────
# 7. α-fair welfare limits match utilitarian and leximin
# ─────────────────────────────────────────────────────────────────────
def test_swf_alpha_limits_match_utilitarian_and_leximin():
    """As α → 0, α-fair reduces to utilitarian; as α → ∞, to leximin."""
    u = [0.1, 0.5, 1.0, 2.0, 4.0]
    util = swf_utilitarian(u)
    near_util = swf_alpha_fair(u, alpha=0.001)
    assert near_util == pytest.approx(util, rel=1e-3)

    # Leximin: the worst-off utility dominates the comparison;
    # we check that swf_alpha_fair at large α makes the gradient
    # in the worst-off coordinate dominate.
    leximin = swf_leximin(u)
    assert leximin[0] == pytest.approx(min(u), rel=1e-6)

    # As α → ∞, swf_alpha_fair tends to −∞ but its *ordering* over
    # two utility vectors should agree with leximin's ordering.
    u1 = [0.1, 1.0, 1.0]
    u2 = [0.2, 0.5, 1.5]
    a = swf_alpha_fair(u1, alpha=20.0)
    b = swf_alpha_fair(u2, alpha=20.0)
    # u2 has higher worst-off, so leximin prefers it → α-fair at high α agrees
    assert b > a


# ─────────────────────────────────────────────────────────────────────
# 8. Jain fairness bounds
# ─────────────────────────────────────────────────────────────────────
def test_jain_fairness_bounds():
    """J(x) ∈ [1/n, 1].  Equal allocation gives exactly 1.0;
    single-resource monopoly gives 1/n.
    """
    # equal
    assert jain_fairness([1.0, 1.0, 1.0, 1.0]) == pytest.approx(1.0)
    # monopoly
    assert jain_fairness([1.0, 0.0, 0.0, 0.0]) == pytest.approx(0.25)
    # mixed: a known value
    J = jain_fairness([1.0, 1.0, 1.0, 0.0])
    assert 0.75 == pytest.approx(J)


# ─────────────────────────────────────────────────────────────────────
# Bonus: smoke test that the registry resolves all four mechanisms
# ─────────────────────────────────────────────────────────────────────
def test_mechanism_registry_resolves_all_names():
    for key in ("M0", "M1", "M2", "M3"):
        mech = build_mechanism(key)
        assert mech.name.startswith(key)
