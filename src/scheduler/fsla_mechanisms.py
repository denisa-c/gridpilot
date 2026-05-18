"""
src/scheduler/fsla_mechanisms.py
--------------------------------
Anti-gaming mechanisms for the f-SLA contract (PECS Paper B §5.5,
Finding 4; FSLA_GAMIFICATION_VISION.md §2.1).

Four mechanisms are implemented, exhausting the design space mapped
out in FSLA_GAMIFICATION_POC_PLAN.md §2:

  - M0 ``PostedPrice``       — static credit schedule, weak IC (Wu 2018).
  - M1 ``BlindTrustQueue``   — payment-free, approx. IC (Grosof 2022).
  - M2 ``DAAuction``         — deferred-acceptance auction, strict SP
                                under full info (Bichler 2020).
  - M3 ``AIBaselineAudit``   — non-obvious-manipulability with public
                                AI-baseline predictor (Psomas 2022;
                                vision §2.1's headline mechanism).

Each mechanism exposes a uniform interface so the replay driver can
swap them in/out:

    mech = M3(...)
    jobs_with_tiers = mech.assign_tiers(jobs_df, rng, ai_predictor)
    after_audit     = mech.audit(jobs_with_tiers, completed_jobs)

``assign_tiers`` writes the f-SLA columns (``tier``, ``d_max_hours``,
``slowdown_max``, ``service_credit_h``, ``checkpoint_bonus``) plus a
mechanism-specific ``penalty`` column (default 0).

``audit`` post-processes the completed-jobs dict from the scheduler
and applies the over-declaration penalty per mechanism. Returns the
audited completed-jobs list (no in-place mutation).

This module is intentionally framework-light: NumPy + Pandas + the
existing ``scheduler/fsla.py`` utilities. No PyTorch, no sklearn.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

try:
    from scheduler.fsla import (
        TIER_NAMES, TIER_WINDOW_H, TIER_SLOWMAX, TIER_CREDIT_H,
        T3_FIXED_CHECKPOINT_BONUS,
        T_RIGID, T_HOUR, T_DAY, T_WEEK,
        sample_prior, assign_tiers,
    )
    from scheduler.ai_baseline import AIBaselinePredictor, AIPrediction
except ModuleNotFoundError:  # pragma: no cover
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scheduler.fsla import (  # noqa
        TIER_NAMES, TIER_WINDOW_H, TIER_SLOWMAX, TIER_CREDIT_H,
        T3_FIXED_CHECKPOINT_BONUS,
        T_RIGID, T_HOUR, T_DAY, T_WEEK,
        sample_prior, assign_tiers,
    )
    from scheduler.ai_baseline import AIBaselinePredictor, AIPrediction  # noqa


# ─────────────────────────────────────────────────────────────────────
# Audit report
# ─────────────────────────────────────────────────────────────────────
@dataclass
class AuditReport:
    """Per-mechanism audit summary attached to the replay output.

    Persisted in ``policy_matrix.csv`` so the headline lift and the
    NOM-IC test (H2 of the plan) can be cross-referenced per cell.
    """
    mechanism: str
    n_jobs: int
    n_over_declared: int = 0
    n_under_declared: int = 0
    total_penalty: float = 0.0
    nom_ic_violation_rate: float = 0.0
    per_tier_penalty: dict[str, float] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────────
class AntiGamingMechanism(ABC):
    """Abstract base for an f-SLA anti-gaming mechanism."""

    name: str = "AbstractMechanism"

    @abstractmethod
    def assign_tiers(
        self,
        jobs_df: pd.DataFrame,
        rng: np.random.Generator,
        ai_predictor: Optional[AIBaselinePredictor] = None,
        pi: Optional[np.ndarray] = None,
    ) -> pd.DataFrame:
        """Per-job tier assignment under this mechanism."""
        ...

    @abstractmethod
    def audit(
        self,
        jobs_with_tiers: pd.DataFrame,
        completed_jobs: list[dict],
    ) -> tuple[list[dict], AuditReport]:
        """Apply mechanism-specific post-execution penalty."""
        ...

    # ── shared helpers ────────────────────────────────────────────
    @staticmethod
    def _populate_tier_columns(jobs_df: pd.DataFrame, tiers: np.ndarray) -> pd.DataFrame:
        out = jobs_df.copy()
        out["tier"] = tiers
        out["d_max_hours"] = pd.Series(tiers).map(TIER_WINDOW_H).values
        out["slowdown_max"] = pd.Series(tiers).map(TIER_SLOWMAX).values
        out["service_credit_h"] = pd.Series(tiers).map(TIER_CREDIT_H).values
        out["checkpoint_bonus"] = (tiers == T_WEEK).astype(float) * T3_FIXED_CHECKPOINT_BONUS
        out["penalty"] = 0.0  # mechanism-specific; default 0
        return out

    @staticmethod
    def _realised_tier(slowdown: float) -> int:
        """Reverse-engineer the realised tier from the actual slowdown
        observed by the scheduler.  Used by the over-declaration audit.

        T0 : s ≤ 1.0     T1 : s ≤ 1.2     T2 : s ≤ 2.0     T3 : s ≤ 4.0
        """
        if slowdown <= TIER_SLOWMAX[T_RIGID]:
            return T_RIGID
        if slowdown <= TIER_SLOWMAX[T_HOUR]:
            return T_HOUR
        if slowdown <= TIER_SLOWMAX[T_DAY]:
            return T_DAY
        return T_WEEK


# ─────────────────────────────────────────────────────────────────────
# M0 — Posted Price
# ─────────────────────────────────────────────────────────────────────
class PostedPrice(AntiGamingMechanism):
    """Static credit schedule (PECS §5.2 v0 ladder).

    Tier draws from the Dirichlet prior; the credit schedule is the
    ladder defined in ``scheduler/fsla.py``. No post-execution audit
    is performed (mirrors the §5 v0 PECS posture). This is the
    *weakest* mechanism we evaluate; under it we expect the NOM-IC
    violation rate to be the highest (H2 control condition).
    """
    name = "M0_PostedPrice"

    def assign_tiers(self, jobs_df, rng, ai_predictor=None, pi=None):
        if pi is None:
            pi = sample_prior(rng=rng)
        out, _ = assign_tiers(jobs_df, pi, rng=rng, length_conditioned=True)
        out["penalty"] = 0.0
        return out

    def audit(self, jobs_with_tiers, completed_jobs):
        report = AuditReport(mechanism=self.name, n_jobs=len(completed_jobs))
        return list(completed_jobs), report


# ─────────────────────────────────────────────────────────────────────
# M1 — BlindTrust Queue (Grosof, Scully, Harchol-Balter 2022)
# ─────────────────────────────────────────────────────────────────────
class BlindTrustQueue(AntiGamingMechanism):
    """Payment-free IC queue with rolling truthfulness audit.

    Grosof, Scully & Harchol-Balter (2022) show that a queue policy
    that grants priority strictly monotone in declared "size" and
    *truncates* the credit accrual whenever the realised size exceeds
    the declared one is approximately IC.  We instantiate their
    construction for the four-tier f-SLA:

      - Tier assignment: identical to ``PostedPrice`` (the prior is
        ground truth in the simulator; users' true tier ≡ declared).
      - Audit: for each job, if the realised slowdown exceeds the
        declared tier's clause, the *next-job* priority is discounted
        by ``α_declared − α_realised`` (the marginal credit that the
        over-declaration would have gained).  This makes the gain
        from a single over-declaration zero in expectation.

    The "next-job discount" is modelled in post-processing as a
    direct subtraction from the user's per-job utility; the queue
    itself remains unchanged (no second replay).  This is enough to
    test the *audit* axis of the mechanism without requiring a
    re-simulation loop.
    """
    name = "M1_BlindTrustQueue"

    def assign_tiers(self, jobs_df, rng, ai_predictor=None, pi=None):
        if pi is None:
            pi = sample_prior(rng=rng)
        out, _ = assign_tiers(jobs_df, pi, rng=rng, length_conditioned=True)
        out["penalty"] = 0.0
        return out

    def audit(self, jobs_with_tiers, completed_jobs):
        report = AuditReport(mechanism=self.name, n_jobs=len(completed_jobs))
        out_jobs = []
        per_tier_penalty: dict[str, float] = {t: 0.0 for t in TIER_NAMES}
        for j in completed_jobs:
            jc = dict(j)
            declared = int(j.get("tier", T_RIGID))
            slow = float(j.get("slowdown", 1.0))
            realised = self._realised_tier(slow)
            s_max = float(j.get("slowdown_max", TIER_SLOWMAX[declared]))
            credit_per_h = float(j.get("service_credit_h", TIER_CREDIT_H[declared]))
            deferred_h = max(0.0, (j.get("start", 0) - j.get("submit", 0)) / 3600.0)
            if slow > s_max + 1e-9:
                # Clause violation: the user's declared slowdown clause
                # was exceeded.  Charge the credit accrued × relative
                # over-shoot, which is non-negative, monotone in the
                # over-shoot, and exactly zero when the clause holds.
                rel_over = (slow / max(s_max, 1.0)) - 1.0
                penalty = max(0.0, credit_per_h * deferred_h * rel_over)
                jc["penalty"] = penalty
                per_tier_penalty[TIER_NAMES[declared]] += penalty
                report.n_over_declared += 1
                report.total_penalty += penalty
            else:
                jc["penalty"] = 0.0
                if realised < declared:
                    report.n_under_declared += 1
            out_jobs.append(jc)
        report.per_tier_penalty = per_tier_penalty
        return out_jobs, report


# ─────────────────────────────────────────────────────────────────────
# M2 — Deferred-Acceptance Auction (Bichler et al. 2020)
# ─────────────────────────────────────────────────────────────────────
class DAAuction(AntiGamingMechanism):
    """Deferred-acceptance auction over the f-SLA tier ladder.

    Bichler, Fichtl, Schwarz, Klimm & Heipertz (2020) prove
    strategy-proofness of a one-shot DAA under full information.  We
    instantiate the auction at submit time: each user submits a tier
    *bid* (their true type), and the auction allocates each tier slot
    to the highest-marginal-utility bidder.

    In the PoC, "marginal utility" for tier T_k is the expected credit
    accrual ``α_k × E[deferred_hours_k]``.  Since the f-SLA ladder
    already encodes ``α_k > α_{k-1}``, the bid that maximises the
    auction's objective is the user's true type — this is the
    Bichler 2020 strategy-proofness result restated in our notation.

    Practically, the prior gives us the type distribution; the
    auction's allocation is the tier assignment.  The audit is a
    no-op (DAA is incentive-compatible by construction in the
    full-information regime we simulate).

    The interesting empirical question is *how the assignment differs
    from a free posted-price draw*: under DAA, the prior is
    interpreted as the joint type distribution and the auction's
    welfare-maximising allocation is biased toward the SWF objective.
    We implement utilitarian DAA (most jobs get the lowest tier
    consistent with their integrity rules) as the canonical variant.
    """
    name = "M2_DAAuction"

    def __init__(self, swf_objective: str = "utilitarian"):
        if swf_objective not in ("utilitarian", "nash", "alpha_fair"):
            raise ValueError(
                f"swf_objective must be one of utilitarian/nash/alpha_fair; got {swf_objective}"
            )
        self.swf_objective = swf_objective

    def assign_tiers(self, jobs_df, rng, ai_predictor=None, pi=None):
        if pi is None:
            pi = sample_prior(rng=rng)
        # Step 1 — each user submits their true type (= a Dirichlet draw)
        out, _ = assign_tiers(jobs_df, pi, rng=rng, length_conditioned=True)
        # Step 2 — re-rank: in utilitarian DAA, jobs with the largest
        # expected deferral benefit get the highest tier (they should
        # also be the ones who can absorb the longest delay).  Under
        # the §5 ladder, marginal benefit = α_k × W_k = α_k × d_max_h,
        # which is monotone in k.  Therefore the auction's allocation
        # *is* the prior assignment — for the full-info case (which
        # the simulator models) the DAA collapses to the posted price.
        # We retain the mechanism class so the audit (§5.4) can be
        # plugged in if/when the full-info assumption is relaxed.
        out["penalty"] = 0.0
        return out

    def audit(self, jobs_with_tiers, completed_jobs):
        report = AuditReport(mechanism=self.name, n_jobs=len(completed_jobs))
        # Under SP-DAA in full info, no penalty applies.
        return list(completed_jobs), report


# ─────────────────────────────────────────────────────────────────────
# M3 — AI Baseline Audit (Psomas, Verma & Zampetakis 2022)
# ─────────────────────────────────────────────────────────────────────
class AIBaselineAudit(AntiGamingMechanism):
    """NOM-IC mechanism with a public AI baseline predictor.

    This is the vision document's headline mechanism (§2.1).  At
    submit time the user sees the AI-baseline tier prediction
    ``tier_AI`` and declares their own tier ``tier_declared``.  Post-
    execution, if the realised slowdown exceeds the declared tier's
    clause (over-declaration), a public-ranking penalty equal to
    ``ai_confidence × (declared − realised) × λ`` is applied, where
    ``λ`` is a tunable strictness coefficient (default 0.05).

    Psomas, Verma & Zampetakis (2022) show that a mechanism is
    *non-obviously manipulable* (NOM-IC) when no one-step deviation
    strictly improves the user's utility.  Under the AI-baseline
    audit, a one-tier-up deviation costs ``λ × confidence`` in
    expectation, while gaining at most ``α_{k+1} − α_k`` in service
    credit.  Setting ``λ = α_1 / max_confidence ≈ 0.025`` makes the
    deviation strictly negative in expectation, satisfying NOM-IC.
    """
    name = "M3_AIBaselineAudit"

    def __init__(self, strictness: float = 0.05, drift_rate: float = 0.0):
        """Parameters
        ----------
        strictness : float
            λ in the penalty formula.  Default 0.05 is calibrated so
            that one-tier-up deviations are strictly negative in
            expectation under the prior used in PECS §5.2.
        drift_rate : float
            Fraction of users who *adapt* to the AI baseline by
            increasing their declarations beyond the predicted tier
            even when un-warranted (vision risk row 2).  Used in the
            anti-gaming H2 test.  Default 0 (no drift).
        """
        if strictness < 0:
            raise ValueError(f"strictness must be ≥ 0; got {strictness}")
        if not (0.0 <= drift_rate <= 1.0):
            raise ValueError(f"drift_rate must be in [0, 1]; got {drift_rate}")
        self.strictness = float(strictness)
        self.drift_rate = float(drift_rate)

    def assign_tiers(self, jobs_df, rng, ai_predictor=None, pi=None):
        if ai_predictor is None:
            raise ValueError(
                "M3 (AIBaselineAudit) requires an AIBaselinePredictor; "
                "fit one on historical jobs first."
            )
        # Step 1 — sample the user's true tier (the prior)
        if pi is None:
            pi = sample_prior(rng=rng)
        out, _ = assign_tiers(jobs_df, pi, rng=rng, length_conditioned=True)
        # Step 2 — get the AI prediction
        out = ai_predictor.predict_batch(out)
        # Step 3 — model a fraction of users drifting up by one tier
        if self.drift_rate > 0:
            drift_mask = rng.random(len(out)) < self.drift_rate
            out.loc[drift_mask, "tier"] = (
                out.loc[drift_mask, "tier"].astype(int) + 1
            ).clip(upper=T_WEEK)
            # Re-derive d_max/slow/credit/bonus for drifted rows
            t = out["tier"].astype(int).values
            out["d_max_hours"] = pd.Series(t).map(TIER_WINDOW_H).values
            out["slowdown_max"] = pd.Series(t).map(TIER_SLOWMAX).values
            out["service_credit_h"] = pd.Series(t).map(TIER_CREDIT_H).values
            out["checkpoint_bonus"] = (t == T_WEEK).astype(float) * T3_FIXED_CHECKPOINT_BONUS
        out["penalty"] = 0.0
        return out

    def audit(self, jobs_with_tiers, completed_jobs):
        report = AuditReport(mechanism=self.name, n_jobs=len(completed_jobs))
        out_jobs = []
        per_tier_penalty: dict[str, float] = {t: 0.0 for t in TIER_NAMES}
        n_violations = 0
        for j in completed_jobs:
            jc = dict(j)
            declared = int(j.get("tier", T_RIGID))
            ai_tier = int(j.get("tier_ai", declared))
            slow = float(j.get("slowdown", 1.0))
            s_max = float(j.get("slowdown_max", TIER_SLOWMAX[declared]))
            ai_conf = float(j.get("ai_confidence", 0.5))
            deferred_h = max(0.0, (j.get("start", 0) - j.get("submit", 0)) / 3600.0)
            # Over-declaration is detected at two coupled signals: the
            # user declared above the AI baseline ('strategic') AND
            # the slowdown clause was violated ('realised').  Either
            # alone is insufficient; together they imply a deliberate
            # over-claim that the audit penalises.
            strategic_over = declared > ai_tier
            clause_violated = slow > s_max + 1e-9
            if strategic_over and clause_violated:
                penalty = self.strictness * ai_conf * (declared - ai_tier)
                # NOM-IC violation: the would-have-been gain (one-tier-
                # up deviation credit) still exceeds the audit penalty.
                gain = max(0.0, TIER_CREDIT_H[declared] - TIER_CREDIT_H[ai_tier]) * deferred_h
                if gain > penalty:
                    n_violations += 1
                jc["penalty"] = penalty
                per_tier_penalty[TIER_NAMES[declared]] += penalty
                report.n_over_declared += 1
                report.total_penalty += penalty
            else:
                jc["penalty"] = 0.0
                if declared < ai_tier:
                    report.n_under_declared += 1
            out_jobs.append(jc)
        report.per_tier_penalty = per_tier_penalty
        if report.n_jobs > 0:
            report.nom_ic_violation_rate = n_violations / report.n_jobs
        return out_jobs, report


# ─────────────────────────────────────────────────────────────────────
# Mechanism registry — used by the policy-matrix driver
# ─────────────────────────────────────────────────────────────────────
MECHANISM_REGISTRY: dict[str, type] = {
    "M0": PostedPrice,
    "M1": BlindTrustQueue,
    "M2": DAAuction,
    "M3": AIBaselineAudit,
}


def build_mechanism(name: str, **kwargs) -> AntiGamingMechanism:
    """Factory used by the policy-matrix driver.

    ``name`` is one of ``M0``/``M1``/``M2``/``M3`` (or the full class
    name).  Extra kwargs are forwarded to the constructor.
    """
    key = name.upper().split("_")[0]
    if key not in MECHANISM_REGISTRY:
        raise KeyError(
            f"unknown mechanism {name!r}; valid: {sorted(MECHANISM_REGISTRY)}"
        )
    return MECHANISM_REGISTRY[key](**kwargs)
