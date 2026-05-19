#!/usr/bin/env python3
"""
scripts/figures/fig_workflow_dag_savings.py
=============================================
Placeholder figure for the C2 paper's H3 (conditional DAGs unlock
latent flexibility) result.

Reads one or more workflow-replay summary JSONs and plots realised
edge-counts and M-Workflow KL-divergence per early-stop rate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--summary-jsons", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path,
                    default=Path("figs/fig_workflow_dag_savings.pdf"))
    args = p.parse_args(argv)

    es_rates: list[float] = []
    mean_edges: list[float] = []
    kls: list[float] = []
    for path in args.summary_jsons:
        if not path.exists():
            continue
        obj = json.loads(path.read_text())
        # the replay driver writes the early-stop rate into the file
        # only via the command line; we recover it from the dag_name
        # for the v0.1 shell.  In the final version the driver should
        # store ``early_stop_rate`` in the summary directly.
        es_rates.append(0.0 if "es0" in path.stem else 0.5)
        mean_edges.append(float(obj.get("mean_realised_edges", 0.0)))
        audits = obj.get("audits", [])
        kls.append(float(audits[0]["kl_divergence"]) if audits else 0.0)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.0, 4.0),
                                     constrained_layout=True)
    ax1.bar(range(len(es_rates)), mean_edges, color="#345fa8")
    ax1.set_title("Mean realised edges per DAG")
    ax1.set_xticks(range(len(es_rates)))
    ax1.set_xticklabels([f"es={r:.2f}" for r in es_rates])
    ax1.set_ylabel("edges taken (mean over seeds)")
    ax2.bar(range(len(es_rates)), kls, color="#a83a1f")
    ax2.set_title("M-Workflow KL(declared || realised)")
    ax2.set_xticks(range(len(es_rates)))
    ax2.set_xticklabels([f"es={r:.2f}" for r in es_rates])
    ax2.set_ylabel("KL divergence (nats)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_workflow_dag_savings] wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
