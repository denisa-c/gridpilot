"""
src/scheduler/dag_mechanisms.py
================================
M-Workflow: NOM-IC audit on (declared workflow DAG, realised DAG).

A user declares a :class:`WorkflowDAG` whose edges carry conditional
branching probabilities.  At runtime the DAG materialises against the
parent nodes' actual results; the realised branching distribution
diverges from the declared one whenever the user mis-estimated their
branching probability (e.g. declared 50 % early-stop, realised 5 %).
The audit charges a penalty proportional to this divergence, calibrated
so a one-edge mis-declaration is never strictly profitable (the
Non-Obviously-Manipulable Incentive-Compatibility property of Psomas
et al., EC 2022).

Concretely, for each (parent, trigger) group we compute a per-group
KL divergence between the declared edge-probability vector and the
realised edge-frequency vector across the Monte-Carlo seeds, and
charge a penalty proportional to the total KL.  The proportionality
constant is the per-tier service-credit rate, so the penalty has the
same unit (cluster-credit-hours) as the credits being clawed back.

The module is dependency-light --- no networkx import at the top
level --- so it can be loaded by the anti-gaming-mechanism registry
without pulling in the full WorkflowDAG runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np


_EPS = 1e-12


def _kl_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """KL(p || q) over discrete distributions, with eps-smoothing.

    Both inputs must be non-negative and sum to a positive number;
    they are renormalised internally.  Returns 0.0 when p is identical
    to q (within ``_EPS``); strictly positive otherwise.
    """
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float)
    if p.shape != q.shape:
        raise ValueError(f"shape mismatch: {p.shape} vs {q.shape}")
    p_sum = float(p.sum())
    q_sum = float(q.sum())
    if p_sum <= 0 or q_sum <= 0:
        return 0.0
    p = p / p_sum
    q = q / q_sum
    # eps-smooth to avoid log(0); preserves the inequality
    # KL(p||q) == 0  iff  p == q (within eps).
    p = np.clip(p, _EPS, 1.0)
    q = np.clip(q, _EPS, 1.0)
    return float(np.sum(p * (np.log(p) - np.log(q))))


@dataclass
class MWorkflowAudit:
    """Audit record produced by M-Workflow for one job (or one DAG)."""
    job_id: int
    declared_branching: dict[str, float]
    realised_branching: dict[str, float]
    kl_divergence: float
    penalty_credit_hours: float
    nom_ic_violation: bool


def declared_branching_distribution(
    edges: Iterable[tuple[int, int, float, str]],
    parent_id: int,
    trigger: str,
) -> np.ndarray:
    """Return the *declared* edge-probability vector for one
    (parent, trigger) group, in the order ``edges`` yields them.

    Each input tuple is ``(parent_id, child_id, p, trigger)``.
    """
    group = [e for e in edges if e[0] == parent_id and e[3] == trigger]
    return np.array([float(e[2]) for e in group], dtype=float)


def realised_branching_frequency(
    realised_children_per_seed: Iterable[set[int]],
    candidate_children: list[int],
) -> np.ndarray:
    """Empirical edge-take frequency across Monte-Carlo seeds.

    ``realised_children_per_seed`` is an iterable of seed-specific
    sets of child ids that were actually taken.  Returns the per-child
    take-frequency vector (length ``len(candidate_children)``) summed
    to the total number of takes (NOT normalised --- the caller's
    :func:`_kl_divergence` normalises internally).
    """
    counts = np.zeros(len(candidate_children), dtype=float)
    cand_idx = {c: i for i, c in enumerate(candidate_children)}
    for taken in realised_children_per_seed:
        for c in taken:
            if c in cand_idx:
                counts[cand_idx[c]] += 1.0
    return counts


def m_workflow_audit(
    job_id: int,
    declared_p: dict[str, float],
    realised_p: dict[str, float],
    credit_rate_per_hour: float,
    parent_runtime_h: float = 1.0,
    violation_kl_threshold: float = 0.10,
) -> MWorkflowAudit:
    """One audit record per (job, branching group).

    The penalty is ``credit_rate_per_hour * parent_runtime_h * KL``.
    Multiplying by the parent's runtime makes the penalty proportional
    to the credit the user *could* have earned on this branch, so a
    monotone-credit-schedule ladder remains NOM-IC after the audit.
    Sub-threshold KL is treated as honest declaration; above-threshold
    KL is flagged as a NOM-IC violation.
    """
    keys = sorted(set(declared_p) | set(realised_p))
    p = np.array([float(declared_p.get(k, 0.0)) for k in keys])
    q = np.array([float(realised_p.get(k, 0.0)) for k in keys])
    kl = _kl_divergence(p, q)
    penalty = float(credit_rate_per_hour) * float(parent_runtime_h) * kl
    return MWorkflowAudit(
        job_id=int(job_id),
        declared_branching={k: float(declared_p.get(k, 0.0)) for k in keys},
        realised_branching={k: float(realised_p.get(k, 0.0)) for k in keys},
        kl_divergence=float(kl),
        penalty_credit_hours=float(penalty),
        nom_ic_violation=bool(kl > violation_kl_threshold),
    )
