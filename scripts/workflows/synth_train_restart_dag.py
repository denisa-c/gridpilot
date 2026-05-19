#!/usr/bin/env python3
"""
scripts/workflows/synth_train_restart_dag.py
=============================================
Build a synthetic AI-training DAG with conditional checkpoint-restart.

4-segment chain: segment_1 -> eval_1 -> { default | restart_high_util }
-> eval_2 -> { default | early_terminate } -> final_eval.

The "restart_high_util" branch carries the user-declared higher
GPU-utilisation configuration (more replicas, higher per-GPU power)
and exercises the M-Workflow audit on a branch whose realised resource
profile diverges from the default branch.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from scheduler.workflow_dag import (  # noqa: E402
    ConditionalEdge, JobSpec, WorkflowDAG,
)


def build_train_restart_dag(cfg: dict, base_job_id: int = 0) -> WorkflowDAG:
    n_seg = int(cfg.get("n_segments", 4))
    seg_h = float(cfg.get("segment_runtime_h", 6.0))
    nodes_default = int(cfg.get("num_nodes_per_segment", 8))
    nodes_high = int(cfg.get("num_nodes_restart_high_util", 16))
    declared_tier = int(cfg.get("declared_tier", 2))
    branching = dict(cfg.get("declared_branching", {"default": 1.0}))

    dag = WorkflowDAG()
    # Layout: segment_i (compute) and eval_i (compute eval).  Each
    # segment is one node; eval nodes are short compute jobs at the
    # tail of each segment, carrying the conditional branching coin.
    jid = base_job_id
    seg_ids: list[int] = []
    for i in range(n_seg):
        seg_id = i * 2
        eval_id = seg_id + 1
        dag.add_node(JobSpec(
            node_id=seg_id, job_id=jid,
            runtime_s=seg_h * 3600.0,
            num_nodes_alloc=nodes_default,
            tier=declared_tier,
            name=f"segment_{i}",
        )); jid += 1
        dag.add_node(JobSpec(
            node_id=eval_id, job_id=jid,
            runtime_s=0.25 * 3600.0,
            num_nodes_alloc=1,
            tier=declared_tier,
            name=f"eval_{i}",
        )); jid += 1
        seg_ids.append(seg_id)
        # segment_i -> eval_i  (deterministic default-trigger edge)
        dag.add_edge(ConditionalEdge(
            parent_id=seg_id, child_id=eval_id, p=1.0, trigger="default",
        ))
    # Conditional edges between consecutive segments
    for i in range(n_seg - 1):
        eval_id = i * 2 + 1
        next_seg = (i + 1) * 2
        # default: continue to next segment
        if branching.get("default", 0.0) > 0:
            dag.add_edge(ConditionalEdge(
                parent_id=eval_id, child_id=next_seg,
                p=float(branching["default"]), trigger="default",
            ))
        # loss_plateaued: restart next segment at high utilisation
        if branching.get("loss_plateaued", 0.0) > 0:
            # Add a separate "restart-high-util" node and edge.
            restart_id = 1000 + i
            dag.add_node(JobSpec(
                node_id=restart_id, job_id=jid,
                runtime_s=seg_h * 3600.0,
                num_nodes_alloc=nodes_high,
                tier=declared_tier,
                name=f"segment_{i+1}_restart_high_util",
            )); jid += 1
            dag.add_edge(ConditionalEdge(
                parent_id=eval_id, child_id=restart_id,
                p=float(branching["loss_plateaued"]),
                trigger="loss_plateaued",
            ))
        # converged: terminate (no edge added; chain ends here)
    return dag


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path,
                    default=ROOT / "configs/workflows/train_restart.yaml")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    cfg = yaml.safe_load(args.config.read_text()) or {}
    dag = build_train_restart_dag(cfg)
    out = {
        "config": str(args.config),
        "seed": int(args.seed),
        "name": cfg.get("name", "train_restart"),
        "nodes": [asdict(n) for n in dag.nodes.values()],
        "edges": [asdict(e) for e in dag.edges],
        "declared_branching": cfg.get("declared_branching", {}),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"[synth-train-restart] wrote {args.out} ({len(dag.nodes)} nodes, "
          f"{len(dag.edges)} edges)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
