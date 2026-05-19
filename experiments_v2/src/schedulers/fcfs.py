"""
experiments_v2/src/schedulers/fcfs.py
======================================
Plain FCFS — First-Come-First-Served, **no backfilling**.

Reference
---------
Mu'alem, A. W., & Feitelson, D. G. (2001).
*Utilization, Predictability, Workloads, and User Runtime Estimates
in Scheduling the IBM SP2 with Backfilling.*  IEEE TPDS 12(6),
529–543.  See §2 ("FCFS without backfilling") for the canonical
specification.

Algorithm summary (§2):
  - Jobs dispatched strictly in submit-time order.
  - Head-of-queue job blocks every later job until it fits.
  - No reordering, no backfilling, no carbon-awareness.

Implementation: event-driven simulation with a min-heap of running
jobs by end-time and a deque of waiting jobs in submit order.
O((N + E) log N) where N is the number of jobs and E is the number
of dispatch events.

This module produces a ``ScheduleResult`` (see ``accounting.py``).
Metrics (energy, CFE, CO₂) are computed by ``run_metrics(...)`` on
the result — this module does NOT compute energy itself.
"""
from __future__ import annotations

import heapq
from collections import deque
from typing import Optional

import numpy as np
import pandas as pd

from .accounting import ScheduledJob, ScheduleResult, from_dispatch_log


def run(
    jobs_df: pd.DataFrame,
    total_nodes: int,
    ci_df: Optional[pd.DataFrame] = None,
    pue_curve: Optional[pd.Series] = None,
    *,
    sim_end_epoch: float,
    submit_col: str = "submit_time_epoch",
    runtime_col: str = "run_time",
    nodes_col: str = "num_nodes_alloc",
) -> ScheduleResult:
    """Dispatch ``jobs_df`` under plain FCFS and return the schedule.

    ``ci_df`` and ``pue_curve`` are accepted for API symmetry with
    the carbon-aware paths and are unused here — FCFS is CI-blind.
    """
    if jobs_df.empty:
        return ScheduleResult()

    work = jobs_df[[submit_col, runtime_col, nodes_col]].copy()
    # Defensive coercion: pandas 2.x can carry nullable Int64 or object
    # dtypes through some parquet/ETL paths; force to float64 so
    # sort_values + downstream arithmetic are deterministic.  Rows with
    # any NaN in these three columns are dropped (they can't be
    # scheduled anyway).
    work[submit_col]  = pd.to_numeric(work[submit_col],  errors="coerce")
    work[runtime_col] = pd.to_numeric(work[runtime_col], errors="coerce")
    work[nodes_col]   = pd.to_numeric(work[nodes_col],   errors="coerce")
    work = work.dropna(subset=[submit_col, runtime_col, nodes_col])
    if work.empty:
        print(f"[fcfs] WARN: 0 schedulable rows after dropna on "
              f"{submit_col}/{runtime_col}/{nodes_col}")
        return ScheduleResult()
    # Sort via numpy argsort to bypass a pandas 2.x sort_values
    # regression that triggers IndexError on otherwise-valid float64
    # columns when kind="stable" is requested.  numpy.argsort returns
    # a permutation index; iloc then re-orders the DataFrame.
    order = np.argsort(work[submit_col].to_numpy(), kind="stable")
    work = work.iloc[order].reset_index(drop=True)
    work[nodes_col] = work[nodes_col].clip(upper=total_nodes).astype(int)

    submit_times = work[submit_col].to_numpy(dtype=float)
    runtimes     = work[runtime_col].to_numpy(dtype=float)
    nodes_req    = work[nodes_col].to_numpy(dtype=int)

    n_jobs       = len(work)
    free_nodes   = total_nodes
    submit_idx   = 0
    # deque (NOT list): popleft() is O(1) vs list.pop(0)'s O(W).
    # For traces with hundreds of thousands of jobs, this is the
    # difference between an O(N) and an O(N×W) main loop.
    waiting: deque[int] = deque()
    running_heap: list[tuple[float, int]] = []   # (end_epoch, nodes)
    dispatch_log: list[dict] = []

    now = float(submit_times[0])
    while submit_idx < n_jobs and submit_times[submit_idx] <= now:
        waiting.append(submit_idx)
        submit_idx += 1

    while waiting or running_heap or submit_idx < n_jobs:
        # 1. Dispatch every waitable head that fits.  Plain FCFS:
        #    NO reordering — if the head doesn't fit, we don't look
        #    at later jobs (that's the pathology EASY-FCFS fixes).
        while waiting and free_nodes >= nodes_req[waiting[0]]:
            j = waiting.popleft()
            nodes_j   = int(nodes_req[j])
            runtime_j = float(runtimes[j])
            start_epoch = now
            end_epoch   = now + runtime_j
            free_nodes -= nodes_j
            heapq.heappush(running_heap, (end_epoch, nodes_j))
            dispatch_log.append({
                "submit_epoch": float(submit_times[j]),
                "start_epoch":  start_epoch,
                "end_epoch":    end_epoch,
                "nodes":        nodes_j,
                "runtime_s":    runtime_j,
                "replicas":     1.0,
            })

        # 2. Advance time to the next event.
        next_submit = submit_times[submit_idx] if submit_idx < n_jobs else float("inf")
        next_done   = running_heap[0][0] if running_heap else float("inf")
        new_now = min(next_submit, next_done)
        if new_now == float("inf"):
            break
        now = new_now

        # 3. Process completions and arrivals at ``now``.
        while running_heap and running_heap[0][0] <= now:
            _, freed = heapq.heappop(running_heap)
            free_nodes += freed
        while submit_idx < n_jobs and submit_times[submit_idx] <= now:
            waiting.append(submit_idx)
            submit_idx += 1

    return from_dispatch_log(dispatch_log, sim_end_epoch)
