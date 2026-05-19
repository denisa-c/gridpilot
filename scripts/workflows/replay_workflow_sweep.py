#!/usr/bin/env python3
"""
scripts/workflows/replay_workflow_sweep.py
============================================
End-to-end DAG replay driver for the C2 paper's H3 (conditional DAGs
unlock latent flexibility) hypothesis.

Loads a synthetic DAG (JSON dump produced by
``scripts/workflows/synth_*_dag.py``), realises it under each Monte-
Carlo seed via :meth:`WorkflowDAG.realise`, and writes the per-seed
realised job rows to a CSV that the existing f-SLA dispatcher can
consume.  Also emits an M-Workflow audit JSON for each (job, seed)
pair so the paper can plot the KL divergence and NOM-IC violation rate.

This is the v0.1 shell --- the full sweep over (3 DAG types x 4
branching depths x 5 mechanisms x 8 seeds) cells lives here once the
sweep matrix is finalised.  The shell already runs end-to-end on the
tiny stub configs in ``configs/workflows/``.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from scheduler.workflow_dag import (  # noqa: E402
    ConditionalEdge, JobSpec, WorkflowDAG,
)
from scheduler.dag_mechanisms import m_workflow_audit  # noqa: E402


def load_dag_from_json(path: Path) -> tuple[WorkflowDAG, dict, str]:
    obj = json.loads(path.read_text())
    dag = WorkflowDAG()
    for n in obj.get("nodes", []):
        dag.add_node(JobSpec(**n))
    for e in obj.get("edges", []):
        dag.add_edge(ConditionalEdge(**e))
    declared = dict(obj.get("declared_branching", {}))
    name = obj.get("name", path.stem)
    return dag, declared, name


def _empirical_branching(
    realised_dags_per_seed: list[WorkflowDAG],
) -> dict[str, float]:
    """Across all seeds, count the empirical frequency with which each
    trigger label fired.  Returns a probability distribution over
    trigger labels (sums to 1.0 except when no edges fired anywhere,
    in which case it returns {})."""
    counts: Counter[str] = Counter()
    for dag in realised_dags_per_seed:
        for e in dag.edges:
            counts[e.trigger] += 1
    total = sum(counts.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def replay_one_dag(
    dag: WorkflowDAG,
    declared: dict[str, float],
    n_seeds: int,
    seed_base: int,
    parent_result_sampler=None,
) -> dict:
    """Replay one DAG ``n_seeds`` times and return summary metrics.

    ``parent_result_sampler`` is a callable ``(rng, parent_id) ->
    trigger_label`` that the caller can supply to bias the parent
    results (e.g. for testing H3 with a 50 %% early-stop rate).  When
    None, every parent decides ``"default"`` (PCAPS-static behaviour).
    """
    if parent_result_sampler is None:
        def parent_result_sampler(rng, parent_id):  # noqa: ARG001
            return "default"

    realised: list[WorkflowDAG] = []
    audits: list[dict] = []
    for s in range(n_seeds):
        rng = np.random.default_rng(seed_base + s)
        # Roll each parent's outcome label first, then realise the DAG
        # under those labels.
        parent_result = {nid: parent_result_sampler(rng, nid)
                          for nid in dag.nodes}
        realised_dag = dag.realise(rng, parent_result=parent_result)
        realised.append(realised_dag)
    realised_branching = _empirical_branching(realised)
    # M-Workflow audit at the DAG-level (one record per replay batch).
    audit = m_workflow_audit(
        job_id=0,
        declared_p=declared,
        realised_p=realised_branching,
        credit_rate_per_hour=0.06,    # T3 rate as the audit baseline
        parent_runtime_h=1.0,
    )
    audits.append(asdict(audit))

    # Realised energy and CO2 are computed downstream by the f-SLA
    # dispatcher --- this shell just emits the per-seed realised-job
    # row count + a single M-Workflow audit record per DAG.
    return {
        "n_nodes": len(dag.nodes),
        "n_seeds": n_seeds,
        "declared_branching": declared,
        "realised_branching": realised_branching,
        "mean_realised_edges": float(np.mean([len(d.edges) for d in realised])),
        "audits": audits,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="replay_workflow_sweep",
                                  allow_abbrev=False)
    p.add_argument("--dag-json", type=Path, required=True,
                    help="Path to a DAG JSON produced by synth_*_dag.py")
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--seed-base", type=int, default=20260517)
    p.add_argument("--early-stop-rate", type=float, default=0.0,
                    help="If > 0, each parent decides 'early_stopped' "
                         "with this probability.  Used to test H3.")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    dag, declared, name = load_dag_from_json(args.dag_json)
    if args.early_stop_rate > 0:
        rate = float(args.early_stop_rate)

        def sampler(rng, parent_id):  # noqa: ARG001
            return "early_stopped" if rng.random() < rate else "default"
    else:
        sampler = None

    summary = replay_one_dag(
        dag, declared, args.seeds, args.seed_base,
        parent_result_sampler=sampler,
    )
    summary["dag_name"] = name
    summary["dag_json"] = str(args.dag_json)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"[workflow-sweep] {name}: wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
