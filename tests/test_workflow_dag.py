"""Tests for src/scheduler/workflow_dag.py.

Covers:
  * WorkflowDAG construction + node/edge invariants
  * roots() and children() queries
  * realise() against deterministic parent results
  * realise() with random branching coin gives sensible bounds
  * to_networkx() round-trip (skipped if networkx not installed)
  * unknown-node edge addition raises

Six tests in total.
"""
from __future__ import annotations

import numpy as np
import pytest

from scheduler.workflow_dag import (
    ConditionalEdge, JobSpec, WorkflowDAG,
)


def _trivial_chain_dag(n: int = 3) -> WorkflowDAG:
    dag = WorkflowDAG()
    for i in range(n):
        dag.add_node(JobSpec(
            node_id=i, job_id=i, runtime_s=3600.0, num_nodes_alloc=1,
            tier=0, name=f"n{i}",
        ))
    for i in range(n - 1):
        dag.add_edge(ConditionalEdge(
            parent_id=i, child_id=i + 1, p=1.0, trigger="default",
        ))
    return dag


def test_dag_roots_and_children():
    dag = _trivial_chain_dag(4)
    assert dag.roots() == [0]
    assert [e.child_id for e in dag.children(0)] == [1]
    assert dag.children(3) == []     # tail node has no children


def test_dag_realise_default_trigger_takes_all_edges():
    dag = _trivial_chain_dag(4)
    rng = np.random.default_rng(0)
    realised = dag.realise(rng)
    # default-trigger, p=1.0 -> all three edges taken
    assert len(realised.edges) == 3
    assert {e.parent_id for e in realised.edges} == {0, 1, 2}


def test_dag_realise_skips_edges_whose_trigger_unmet():
    dag = WorkflowDAG()
    for i in range(3):
        dag.add_node(JobSpec(
            node_id=i, job_id=i, runtime_s=1.0, num_nodes_alloc=1,
        ))
    dag.add_edge(ConditionalEdge(0, 1, 1.0, "early_stopped"))
    dag.add_edge(ConditionalEdge(0, 2, 1.0, "default"))
    rng = np.random.default_rng(0)
    # parent 0 decides "default" -> only the default-trigger edge fires
    realised = dag.realise(rng, parent_result={0: "default"})
    assert len(realised.edges) == 1
    assert realised.edges[0].child_id == 2


def test_dag_realise_probability_within_bounds():
    """Across 200 seeds, an edge with p=0.3 fires close to 30 % of the time."""
    dag = WorkflowDAG()
    dag.add_node(JobSpec(node_id=0, job_id=0, runtime_s=1.0, num_nodes_alloc=1))
    dag.add_node(JobSpec(node_id=1, job_id=1, runtime_s=1.0, num_nodes_alloc=1))
    dag.add_edge(ConditionalEdge(0, 1, 0.3, "default"))
    n_seeds = 200
    n_fired = 0
    for s in range(n_seeds):
        rng = np.random.default_rng(s)
        if len(dag.realise(rng).edges) == 1:
            n_fired += 1
    rate = n_fired / n_seeds
    assert 0.20 <= rate <= 0.40       # ~3 sigma band on p=0.3


def test_dag_add_edge_rejects_unknown_node():
    dag = _trivial_chain_dag(2)
    with pytest.raises(KeyError):
        dag.add_edge(ConditionalEdge(0, 99, 1.0, "default"))


def test_dag_to_networkx_roundtrip():
    nx = pytest.importorskip("networkx")
    dag = _trivial_chain_dag(3)
    g = dag.to_networkx()
    assert isinstance(g, nx.DiGraph)
    assert g.number_of_nodes() == 3
    assert g.number_of_edges() == 2
    # Edge attributes round-trip
    e01 = g.get_edge_data(0, 1)
    assert e01["p"] == 1.0
    assert e01["trigger"] == "default"
