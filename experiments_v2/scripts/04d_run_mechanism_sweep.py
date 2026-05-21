#!/usr/bin/env python3
"""
experiments_v2/scripts/04d_run_mechanism_sweep.py
==================================================
Phase 4f -- the anti-gaming mechanism sweep that powers Finding D
("M3's NOM-IC violation rate is an order of magnitude below the
posted-price baseline at no fairness or SWF cost").

For each of the four mechanism plug-ins M0--M3 (see
``mechanism_design.py``) the sweep:

  1. Samples ``--n-users`` synthetic users.  Each user has a *true*
     tier drawn from the CLASS_TO_TIER_DIRICHLET prior used by the
     v2 taxonomy sweep, plus a per-user AI-confidence value (M3
     only) drawn from Beta(2, 1) so most users have a confident
     prediction but the long-tail has near-zero confidence.
  2. Computes each user's best-response declaration under the
     mechanism's payoff function.
  3. Flags a NOM-IC violation iff some one-tier deviation strictly
     beats the best response.
  4. Aggregates: NOM-IC violation rate, mean realised credit per
     user, Jain's fairness index, alpha-fair social welfare (alpha=1).

Outputs (under ``data/mechanism_sweep/``):
  mechanism_sweep.csv        one row per (mechanism, seed)
  MECHANISM_SUMMARY.csv      one row per mechanism (mean across seeds)
  RUN_MANIFEST.json
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "gridpilot" / "experiments_v2" / "src"))

from mechanism_design import (  # type: ignore[import-not-found]
    User, N_TIERS, PAYOFF_FN, best_response, nomic_violation,
    jain_index, alpha_fair_swf, CREDIT_HONEST,
)
from workload_taxonomy import (  # type: ignore[import-not-found]
    CLASS_ORDER, CLASS_TO_TIER_DIRICHLET,
)


def _sample_users(n: int, rng: np.random.Generator) -> list[User]:
    """Sample ``n`` synthetic users from the v2 taxonomy prior.

    Workload class is drawn uniformly across the 6 classes; the user's
    true tier is then drawn from CLASS_TO_TIER_DIRICHLET[class] so the
    population matches the per-class declaration prior the rest of the
    paper uses.  AI confidence ~ Beta(2, 1) so most users have a
    fairly confident prediction but the long-tail is poorly-known.
    """
    users = []
    classes = list(CLASS_ORDER)
    for uid in range(n):
        cls = classes[rng.integers(0, len(classes))]
        prior = CLASS_TO_TIER_DIRICHLET.get(cls, {0: 1.0})
        tiers = list(prior.keys())
        probs = np.array(list(prior.values()), dtype=float)
        probs /= probs.sum()
        true_tier = int(rng.choice(tiers, p=probs))
        # Runtimes drawn lognormal around 1 h so the credit scale is
        # comparable across users; AI confidence Beta(2, 1).
        runtime_h = float(np.clip(rng.lognormal(0.0, 1.0), 0.05, 12.0))
        ai_conf = float(np.clip(rng.beta(2.0, 1.0), 0.0, 1.0))
        users.append(User(uid=uid, true_tier=true_tier,
                           runtime_h=runtime_h,
                           ai_confidence=ai_conf))
    return users


def _ai_prediction(user: User, rng: np.random.Generator) -> int:
    """Noisy AI prediction of the user's true tier.

    Conditional on ``ai_confidence``: with probability ``confidence``
    the prediction is exact; otherwise it is the true tier perturbed
    by a one-step random walk (clipped to ``[0, N_TIERS-1]``).
    """
    if rng.random() < user.ai_confidence:
        return user.true_tier
    step = int(rng.choice([-1, 1]))
    return int(np.clip(user.true_tier + step, 0, N_TIERS - 1))


def _evaluate_mechanism(mech: str, users: list[User],
                          rng: np.random.Generator) -> dict:
    """Run one (mechanism, seed) cell."""
    fn = PAYOFF_FN[mech]
    declarations = np.zeros(len(users), dtype=int)
    truths       = np.zeros(len(users), dtype=int)
    violations   = np.zeros(len(users), dtype=bool)
    credits      = np.zeros(len(users), dtype=float)
    for i, u in enumerate(users):
        pred = _ai_prediction(u, rng)
        d_br = best_response(fn, u, pred)
        v    = nomic_violation(fn, u, pred)
        declarations[i] = d_br
        truths[i]       = u.true_tier
        violations[i]   = v
        # Realised credit: payoff of the actual best-response
        # declaration against the user's true tier.
        credits[i] = float(fn(d_br, u.true_tier, predicted=pred,
                                 confidence=u.ai_confidence))
    return {
        "mechanism":          mech,
        "n_users":            len(users),
        "violation_rate_pct": 100.0 * float(violations.mean()),
        "mean_credit":        float(credits.mean()),
        "jain_index":         jain_index(credits),
        "alpha_fair_swf_a1":  alpha_fair_swf(credits, alpha=1.0),
        "honest_share":       100.0 * float((declarations == truths).mean()),
        "over_claim_share":   100.0 * float((declarations > truths).mean()),
        "under_claim_share":  100.0 * float((declarations < truths).mean()),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n-users", type=int, default=1000)
    p.add_argument("--seeds",   type=int, default=8)
    p.add_argument("--out-dir", type=Path,
                   default=ROOT / "gridpilot" / "experiments_v2" / "data"
                           / "mechanism_sweep")
    args = p.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    rows = []
    for seed in range(args.seeds):
        rng = np.random.default_rng(seed)
        users = _sample_users(args.n_users, rng)
        for mech in ("M0", "M1", "M2", "M3"):
            row = _evaluate_mechanism(mech, users,
                                        np.random.default_rng(seed + 1000))
            row["seed"] = seed
            rows.append(row)
            print(f"  seed={seed}  {mech}  "
                  f"viol={row['violation_rate_pct']:5.2f}%  "
                  f"credit={row['mean_credit']:6.2f}  "
                  f"jain={row['jain_index']:.3f}  "
                  f"SWF1={row['alpha_fair_swf_a1']:.1f}")

    df = pd.DataFrame(rows)
    csv = args.out_dir / "mechanism_sweep.csv"
    df.to_csv(csv, index=False, float_format="%.4f")
    print(f"[04d-mechanism-sweep] wrote {csv}")

    summary = df.groupby("mechanism", as_index=False).agg(
        violation_rate_pct = ("violation_rate_pct", "mean"),
        violation_rate_sem = ("violation_rate_pct",
                               lambda v: float(np.std(v, ddof=0))
                                          / max(1, np.sqrt(len(v)))),
        mean_credit        = ("mean_credit",        "mean"),
        jain_index         = ("jain_index",         "mean"),
        alpha_fair_swf_a1  = ("alpha_fair_swf_a1",  "mean"),
        honest_share       = ("honest_share",       "mean"),
        over_claim_share   = ("over_claim_share",   "mean"),
        under_claim_share  = ("under_claim_share",  "mean"),
    )
    summary_csv = args.out_dir / "MECHANISM_SUMMARY.csv"
    summary.to_csv(summary_csv, index=False, float_format="%.4f")
    print(f"[04d-mechanism-sweep] wrote {summary_csv}")

    (args.out_dir / "RUN_MANIFEST.json").write_text(json.dumps({
        "kind":     "mechanism_sweep", "version": 2,
        "n_users":  args.n_users, "seeds": args.seeds,
        "python":   platform.python_version(), "host": platform.node(),
        "wall_seconds": int(time.time() - t0),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
