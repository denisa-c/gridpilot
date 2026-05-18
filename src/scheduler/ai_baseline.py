"""
src/scheduler/ai_baseline.py
----------------------------
Naive AI tier-baseline predictor for the f-SLA gamification PoC
(PECS Paper B §5.5 + FSLA_GAMIFICATION_VISION.md §2.1).

Vision §6 (Phase 1) explicitly calls out a per-user-mean predictor as
the prototype-grade fallback before real AIDAS telemetry is wired in.
This module implements that fallback with three additions that make
it useful as a paper-grade baseline:

  - **Bayesian back-off**: a user with k < ``min_history`` jobs is
    predicted from the global tier mean instead of their own mean.
  - **Length conditioning**: short jobs (≤ 1 h) are clipped to
    ``{T0, T1}``; long jobs (> 24 h) are clipped away from T0.
    This mirrors the integrity rules in ``scheduler/fsla.py``.
  - **Confidence interval**: each prediction comes with a 1-σ envelope
    derived from per-user tier variance, enabling the M3 audit to
    penalise *over-confident* over-declarations (vision §7 risk row 2).

The predictor is deterministic given a fixed history; it does NOT
require a training loop, GPU, or sklearn — it is a pure NumPy + Pandas
function. A re-trained learned predictor (per-user gradient-boosting on
runtime / node-count / submission-time features) is left to Phase 2.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Local imports
try:
    from scheduler.fsla import TIER_WINDOW_H, T_RIGID, T_HOUR, T_DAY, T_WEEK
except ModuleNotFoundError:  # pragma: no cover
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scheduler.fsla import TIER_WINDOW_H, T_RIGID, T_HOUR, T_DAY, T_WEEK  # noqa


LONG_JOB_THRESHOLD_S = 24 * 3600
SHORT_JOB_THRESHOLD_S = 1 * 3600


@dataclass
class AIPrediction:
    """Per-job AI prediction returned by ``predict_tier``.

    The ``confidence`` field is the inverse of the per-user tier
    variance, normalised to [0, 1]. The M3 audit weights the over-
    declaration penalty by this confidence so that high-confidence
    AI predictions create strong incentives to be honest while low-
    confidence predictions do not punish exploration.
    """
    tier: int
    confidence: float
    fallback_used: bool


class AIBaselinePredictor:
    """Per-user-mean AI baseline with Bayesian back-off and length-conditioning."""

    def __init__(self, min_history: int = 5):
        """``min_history`` controls the back-off threshold; users with
        fewer than this many historical jobs use the global mean.
        Default 5 is the smallest n at which the sample-mean estimator
        is statistically defensible.
        """
        if min_history < 1:
            raise ValueError(f"min_history must be ≥ 1; got {min_history}")
        self.min_history = int(min_history)
        # Populated by ``fit``
        self._per_user_mean_tier: dict[str, float] = {}
        self._per_user_tier_var: dict[str, float] = {}
        self._global_mean_tier: float = 1.0
        self._global_tier_var: float = 1.0
        self._fitted = False

    def fit(self, historical_jobs: pd.DataFrame) -> "AIBaselinePredictor":
        """Fit the per-user-mean tier estimator from a historical
        DataFrame with at least the columns ``user`` and ``tier``.
        """
        if "tier" not in historical_jobs.columns:
            raise ValueError(
                "fit() requires a 'tier' column in historical_jobs; "
                "did you mean to call this before tiers were assigned?"
            )
        if "user" not in historical_jobs.columns:
            # Default everyone to a single anonymous user — degenerate
            # but lets the PoC run on traces with no user attribution.
            historical_jobs = historical_jobs.assign(user="anonymous")

        self._global_mean_tier = float(historical_jobs["tier"].mean())
        self._global_tier_var = float(historical_jobs["tier"].var(ddof=0))
        grouped = historical_jobs.groupby("user")["tier"]
        self._per_user_mean_tier = grouped.mean().to_dict()
        self._per_user_tier_var = grouped.var(ddof=0).fillna(self._global_tier_var).to_dict()
        # n-per-user, used for back-off
        self._per_user_n = grouped.size().to_dict()
        self._fitted = True
        return self

    def _length_conditioned_clip(self, tier_float: float, runtime_s: float) -> int:
        """Apply the same integrity rules as ``fsla.assign_tiers``.

        Round-to-nearest, then clip away from T0 for long jobs and away
        from T2/T3 for short jobs.
        """
        tier = int(np.clip(round(tier_float), T_RIGID, T_WEEK))
        if runtime_s > LONG_JOB_THRESHOLD_S and tier == T_RIGID:
            tier = T_HOUR
        if runtime_s <= SHORT_JOB_THRESHOLD_S and tier >= T_DAY:
            tier = T_HOUR
        return tier

    def predict_tier(self, user: str, runtime_s: float) -> AIPrediction:
        """Return the AI baseline prediction for one job.

        Falls back to the global mean if the user has fewer than
        ``min_history`` historical jobs (Bayesian back-off).
        """
        if not self._fitted:
            # Cold start: predict T1 with low confidence
            tier = self._length_conditioned_clip(1.0, runtime_s)
            return AIPrediction(tier=tier, confidence=0.0, fallback_used=True)

        n = self._per_user_n.get(user, 0)
        if n < self.min_history:
            mean = self._global_mean_tier
            var = self._global_tier_var
            fallback = True
        else:
            mean = self._per_user_mean_tier[user]
            var = self._per_user_tier_var.get(user, self._global_tier_var)
            fallback = False

        # Confidence: inverse-variance normalised to (0, 1] over the
        # 4-tier range. var of a 4-bin uniform is ≈ 1.25 → conf ≈ 0.2.
        confidence = float(1.0 / (1.0 + var))
        tier = self._length_conditioned_clip(mean, runtime_s)
        return AIPrediction(tier=tier, confidence=confidence, fallback_used=fallback)

    def predict_batch(self, jobs_df: pd.DataFrame) -> pd.DataFrame:
        """Vectorised batch prediction.  Returns a DataFrame with
        the columns ``tier_ai``, ``ai_confidence``, ``ai_fallback``.
        """
        out_rows = []
        for _, row in jobs_df.iterrows():
            user = str(row.get("user", "anonymous"))
            runtime_s = float(row["run_time"])
            p = self.predict_tier(user, runtime_s)
            out_rows.append({
                "tier_ai": p.tier,
                "ai_confidence": p.confidence,
                "ai_fallback": int(p.fallback_used),
            })
        return jobs_df.assign(**pd.DataFrame(out_rows, index=jobs_df.index).to_dict("series"))
