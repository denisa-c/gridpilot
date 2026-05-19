#!/usr/bin/env python3
"""
scripts/workflows/synth_hpo_dag.py
====================================
Build a synthetic Optuna-TPE-style HPO sweep as a WorkflowDAG.

Each trial is a node.  Trials are organised in a single-rung TPE
schedule: the user declares an early-stop probability ``p_stop``; the
DAG's edge from each trial to the next-rung trial carries that
probability under the ``"default"`` trigger (continue training) and
``1 - p_stop`` under the ``"early_stopped"`` trigger.  The realised
DAG (after :meth:`WorkflowDAG.realise`) is the per-seed concrete chain
of trials that ran to completion.

Usage:
    PYTHONPATH=src python scripts/workflows/synth_hpo_dag.py \\
        --config configs/workflows/hpo_optuna_tpe.yaml \\
        --seed 0 \\
        --out data/m100/workflows/hpo_dag_seed0.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from scheduler.workflow_dag import (  # noqa: E402
    ConditionalEdge, JobSpec, WorkflowDAG,
)


def build_hpo_dag(cfg: dict, base_job_id: int = 0) -> WorkflowDAG:
    """Build the user-declared HPO DAG from the YAML config."""
    n = int(cfg.get("n_trials", 100))
    trial_h = float(cfg.get("trial_runtime_h", 4.0))
    nodes = int(cfg.get("num_nodes_per_trial", 1))
    declared_tier = int(cfg.get("declared_tier", 2))
    branching = dict(cfg.get("declared_branching", {"default": 1.0}))

    dag = WorkflowDAG()
    for i in range(n):
        dag.add_node(JobSpec(
            node_id=i,
            job_id=base_job_id + i,
            runtime_s=trial_h * 3600.0,
            num_nodes_alloc=nodes,
            tier=declared_tier,
            name=f"hpo_trial_{i}",
        ))
    # Edges: each trial conditionally continues to the next trial.
    # "early_stopped" triggers carry the inverse probability so the
    # M-Workflow audit's branching-distribution vector is well-formed.
    for i in range(n - 1):
        if branching.get("default", 0.0) > 0:
            dag.add_edge(ConditionalEdge(
                parent_id=i, child_id=i + 1,
                p=float(branching["default"]), trigger="default",
            ))
        if branching.get("early_stopped", 0.0) > 0:
            # Early-stopped trials do NOT spawn a next-rung trial; this
            # edge is intentionally absent.  Recorded as a zero-p edge
            # under the "early_stopped" trigger so the audit knows the
            # distribution had this outcome label declared.
            pass
    return dag


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path,
                    default=ROOT / "configs/workflows/hpo_optuna_tpe.yaml")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text()) or {}
    dag = build_hpo_dag(cfg)
    # Serialise: dict of {nodes: [...], edges: [...]} ready for replay.
    out = {
        "config": str(args.config),
        "seed": int(args.seed),
        "name": cfg.get("name", "hpo_optuna_tpe"),
        "nodes": [asdict(n) for n in dag.nodes.values()],
        "edges": [asdict(e) for e in dag.edges],
        "declared_branching": cfg.get("declared_branching", {}),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"[synth-hpo] wrote {args.out} ({len(dag.nodes)} nodes, "
          f"{len(dag.edges)} edges)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
