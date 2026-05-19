"""Tests for src/scheduler/dag_mechanisms.py (M-Workflow audit).

Covers:
  * KL divergence is zero on identical distributions and positive on
    non-trivial pairs
  * m_workflow_audit penalises divergence proportional to KL
  * Sub-threshold KL is NOT a NOM-IC violation; above-threshold IS
  * Zero parent runtime gives zero penalty

Four tests.
"""
from __future__ import annotations

import pytest

from scheduler.dag_mechanisms import (
    _kl_divergence, m_workflow_audit,
)


def test_kl_zero_on_identical_distributions():
    p = [0.5, 0.5]
    assert _kl_divergence(p, p) == pytest.approx(0.0, abs=1e-9)


def test_kl_positive_on_distinct_distributions():
    p = [0.9, 0.1]
    q = [0.1, 0.9]
    assert _kl_divergence(p, q) > 0.1


def test_m_workflow_audit_penalty_scales_with_runtime():
    decl = {"default": 0.5, "early_stopped": 0.5}
    real = {"default": 0.9, "early_stopped": 0.1}   # over-claimed flexibility
    a1 = m_workflow_audit(job_id=1, declared_p=decl, realised_p=real,
                            credit_rate_per_hour=0.06, parent_runtime_h=1.0)
    a4 = m_workflow_audit(job_id=1, declared_p=decl, realised_p=real,
                            credit_rate_per_hour=0.06, parent_runtime_h=4.0)
    assert a4.penalty_credit_hours == pytest.approx(4.0 * a1.penalty_credit_hours,
                                                       rel=1e-9)


def test_nom_ic_violation_threshold():
    # tiny divergence: not a violation
    decl = {"default": 0.50, "alt": 0.50}
    realised = {"default": 0.52, "alt": 0.48}
    audit = m_workflow_audit(job_id=1, declared_p=decl, realised_p=realised,
                              credit_rate_per_hour=0.06,
                              violation_kl_threshold=0.10)
    assert audit.nom_ic_violation is False
    # large divergence: violation
    realised_big = {"default": 0.99, "alt": 0.01}
    audit2 = m_workflow_audit(job_id=1, declared_p=decl,
                                realised_p=realised_big,
                                credit_rate_per_hour=0.06,
                                violation_kl_threshold=0.10)
    assert audit2.nom_ic_violation is True
