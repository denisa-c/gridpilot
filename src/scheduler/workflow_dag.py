"""
src/scheduler/workflow_dag.py
==============================
Dynamic workflow DAGs for the C2 paper.

PCAPS (Lechowicz, SIGCOMM 2024) extends carbon-aware shifting to
*static* precedence-constrained pipelines: every edge of the DAG is
taken deterministically.  Real AI/HPC workflows are not static --- an
HPO sweep early-stops trials that miss a validation threshold, and a
training run conditionally checkpoints + restarts with a different
config if its loss has not converged.  The branch the workflow takes
at runtime depends on the *result* of the previous node.

This module is the C2 paper's contribution to that gap: a
``WorkflowDAG`` that carries per-edge *conditional* branching
probabilities, materialised at runtime against a parent's result.

The branching probability the user declares is the ``M_Workflow``
mechanism's audit signal: a job that declares 50 % early-stop and
realises 5 % is over-claiming flexibility and owes the proportional
credit-claw.

The module is intentionally minimal --- it provides the
DAG-with-branching-distribution abstraction and a runtime
materialiser.  The audit lives in :mod:`scheduler.dag_mechanisms`;
the replay driver lives in :mod:`scripts.workflows.replay_workflow_sweep`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

try:
    import networkx as nx  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover --- networkx is required
    nx = None


@dataclass
class JobSpec:
    """One DAG node: a job to be dispatched.  Minimal fields needed
    for the C2 replay driver to feed it through the existing f-SLA
    dispatcher.  Extend in the C2 paper's P2 phase.
    """
    node_id: int
    job_id: int                  # global job id (matches the M100 trace)
    runtime_s: float
    num_nodes_alloc: int
    tier: int = 0                # declared f-SLA tier
    name: str = ""               # human-readable label (e.g. "hpo_trial_42")


@dataclass
class ConditionalEdge:
    """One DAG edge: parent -> child, taken with probability ``p``
    when the parent's result is in ``trigger`` (a string label the
    user defines, e.g. ``"converged"`` or ``"early_stopped"``).
    """
    parent_id: int
    child_id: int
    p: float
    trigger: str = "default"


@dataclass
class WorkflowDAG:
    """A dynamic workflow DAG.

    The user-declared form names the nodes, the conditional edges and
    the per-edge branching probability.  At dispatch time the runtime
    rolls a per-parent random outcome (drawn from the parent's
    *realised* result label) and traverses the DAG accordingly.

    The DAG is intentionally a thin layer on top of networkx so that
    PCAPS-style static-DAG algorithms can be applied directly when
    every edge has trigger == "default" and p == 1.
    """
    nodes: dict[int, JobSpec] = field(default_factory=dict)
    edges: list[ConditionalEdge] = field(default_factory=list)

    # --- construction -----------------------------------------------
    def add_node(self, spec: JobSpec) -> None:
        self.nodes[spec.node_id] = spec

    def add_edge(self, edge: ConditionalEdge) -> None:
        if edge.parent_id not in self.nodes or edge.child_id not in self.nodes:
            raise KeyError(
                f"edge ({edge.parent_id} -> {edge.child_id}) references unknown nodes"
            )
        self.edges.append(edge)

    # --- queries ----------------------------------------------------
    def roots(self) -> list[int]:
        """Node ids with no incoming edges."""
        has_parent = {e.child_id for e in self.edges}
        return [nid for nid in self.nodes if nid not in has_parent]

    def children(self, parent_id: int) -> list[ConditionalEdge]:
        return [e for e in self.edges if e.parent_id == parent_id]

    def to_networkx(self):
        """Return a :class:`networkx.DiGraph` view of the DAG.

        Useful for plotting and for plugging into PCAPS-style static
        schedulers (set every edge's p to 1.0 and trigger to default).
        """
        if nx is None:
            raise ImportError("networkx is required for WorkflowDAG.to_networkx()")
        g = nx.DiGraph()
        for nid, spec in self.nodes.items():
            g.add_node(nid, **{"job_id": spec.job_id,
                                "runtime_s": spec.runtime_s,
                                "num_nodes_alloc": spec.num_nodes_alloc,
                                "tier": spec.tier,
                                "name": spec.name})
        for e in self.edges:
            g.add_edge(e.parent_id, e.child_id, p=e.p, trigger=e.trigger)
        return g

    # --- runtime materialisation -----------------------------------
    def realise(
        self,
        rng: np.random.Generator,
        parent_result: Optional[dict[int, str]] = None,
    ) -> "WorkflowDAG":
        """Return a *concrete* DAG where every edge is either present
        (taken at runtime) or absent (its branching coin landed against
        it).  ``parent_result`` maps node id to the result-label that
        node produced when it ran (e.g. ``{17: "converged"}``); edges
        whose ``trigger`` is not in the parent's result are skipped.

        For nodes whose ``parent_result`` is missing, we assume the
        ``"default"`` trigger label (compatible with PCAPS-static DAGs).

        The new DAG has the same nodes; only the edges are reduced.
        """
        if parent_result is None:
            parent_result = {}
        out = WorkflowDAG(nodes=dict(self.nodes))
        # Group edges by (parent, trigger) so the branching coin is
        # rolled once per parent-trigger pair (mutually exclusive branches).
        by_parent: dict[tuple[int, str], list[ConditionalEdge]] = {}
        for e in self.edges:
            by_parent.setdefault((e.parent_id, e.trigger), []).append(e)
        for (parent_id, trigger), group in by_parent.items():
            if parent_result.get(parent_id, "default") != trigger:
                continue
            # Use the per-edge p as independent Bernoullis; this lets
            # the user declare overlapping conditional branches (e.g.
            # both checkpoint AND re-train if the trigger fires).
            for e in group:
                if float(rng.random()) < float(e.p):
                    out.edges.append(e)
        return out
