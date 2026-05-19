"""
experiments_v2/src/schedulers/saf.py
=====================================
SAF — Smallest-Area-First, with EASY backfilling.

Reference
---------
Carastan-Santos, D., & de Camargo, R. Y. (2019).
*Obtaining dynamic scheduling policies with simulation and machine
learning.*  Proceedings of SC '19.  See §3: at every scheduling
decision, the waiting queue is sorted by
``area = nodes_required × walltime_estimate`` (ascending).

Algorithm summary:
  Online policy, identical event loop to EASY-FCFS except:
    - The waiting queue is a min-heap keyed by area (ties broken
      by submit_time, preserving FCFS within equal-area jobs).
    - At every dispatch decision the lowest-area job that fits
      is taken (NOT necessarily the earliest-arrived one).
    - EASY backfill semantics layered on top: the head of the
      priority queue gets a reservation; trailing entries can
      backfill if they don't delay it.

Implementation: ~110 lines.  Reuses the dispatch / reservation
helpers from EASY-FCFS conceptually but the waiting structure
differs.
"""
from __future__ import annotations

import heapq
from typing import Optional

import numpy as np
import pandas as pd

from .accounting import ScheduleResult, from_dispatch_log


def _earliest_reservation(running_heap, free_nodes, head_nodes):
    """Same as easy_fcfs._earliest_reservation.  Inlined here to keep
    SAF self-contained for citation."""
    if free_nodes >= head_nodes:
        return 0.0
    cumulative_free = free_nodes
    for end_t, freed in sorted(running_heap):
        cumulative_free += freed
        if cumulative_free >= head_nodes:
            return end_t
    return float("inf")


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
    """Dispatch ``jobs_df`` under SAF with EASY backfilling."""
    if jobs_df.empty:
        return ScheduleResult()

    work = jobs_df[[submit_col, runtime_col, nodes_col]].copy()
    # Same defensive numeric coercion as fcfs.run; see comment there.
    work[submit_col]  = pd.to_numeric(work[submit_col],  errors="coerce")
    work[runtime_col] = pd.to_numeric(work[runtime_col], errors="coerce")
    work[nodes_col]   = pd.to_numeric(work[nodes_col],   errors="coerce")
    work = work.dropna(subset=[submit_col, runtime_col, nodes_col])
    if work.empty:
        print(f"[saf] WARN: 0 schedulable rows after dropna")
        return ScheduleResult()
    order = np.argsort(work[submit_col].to_numpy(), kind="stable")
    work = work.iloc[order].reset_index(drop=True)
    work[nodes_col] = work[nodes_col].clip(upper=total_nodes).astype(int)

    submit_times = work[submit_col].to_numpy(dtype=float)
    runtimes     = work[runtime_col].to_numpy(dtype=float)
    nodes_req    = work[nodes_col].to_numpy(dtype=int)
    # SAF priority: smaller area first; ties broken by submit time.
    areas = (nodes_req.astype(float) * runtimes.astype(float))

    n_jobs       = len(work)
    free_nodes   = total_nodes
    submit_idx   = 0
    # Waiting queue: min-heap of (area, submit_time, j_idx).
    waiting_heap: list[tuple[float, float, int]] = []
    running_heap: list[tuple[float, int]] = []
    dispatch_log: list[dict] = []

    def _push(idx: int) -> None:
        heapq.heappush(waiting_heap,
                        (float(areas[idx]), float(submit_times[idx]), int(idx)))

    def _dispatch(j_idx: int, now: float) -> None:
        nonlocal free_nodes
        nodes_j   = int(nodes_req[j_idx])
        runtime_j = float(runtimes[j_idx])
        start_epoch = now
        end_epoch   = now + runtime_j
        free_nodes -= nodes_j
        heapq.heappush(running_heap, (end_epoch, nodes_j))
        dispatch_log.append({
            "submit_epoch": float(submit_times[j_idx]),
            "start_epoch":  start_epoch,
            "end_epoch":    end_epoch,
            "nodes":        nodes_j,
            "runtime_s":    runtime_j,
            "replicas":     1.0,
        })

    now = float(submit_times[0])
    while submit_idx < n_jobs and submit_times[submit_idx] <= now:
        _push(submit_idx)
        submit_idx += 1

    while waiting_heap or running_heap or submit_idx < n_jobs:
        # 1. Dispatch every priority-head job that fits.
        while waiting_heap and free_nodes >= nodes_req[waiting_heap[0][2]]:
            _, _, j = heapq.heappop(waiting_heap)
            _dispatch(j, now)

        # 2. EASY backfill against the priority head.  Bounded scan +
        #    in-place mutation of the heap.  Walking sorted(heap)
        #    every iteration would be O(W log W); instead we use
        #    heapq.nsmallest(MAX_BACKFILL_SCAN+1, ...) which is
        #    O(W log K) with K=MAX_BACKFILL_SCAN, and then heapify
        #    the survivors only if at least one backfill happened.
        import os
        MAX_BACKFILL_SCAN = int(os.environ.get("EASY_BACKFILL_SCAN", "256"))
        if waiting_heap:
            head_idx = waiting_heap[0][2]
            reservation = _earliest_reservation(
                running_heap, free_nodes, int(nodes_req[head_idx])
            )
            top = heapq.nsmallest(MAX_BACKFILL_SCAN + 1, waiting_heap)
            backfilled_idxs: set[int] = set()
            for entry in top:
                _, _, k = entry
                if k == head_idx:
                    continue
                nodes_k   = int(nodes_req[k])
                runtime_k = float(runtimes[k])
                if free_nodes < nodes_k:
                    continue
                if (now + runtime_k) > reservation:
                    continue
                _dispatch(k, now)
                backfilled_idxs.add(k)
            if backfilled_idxs:
                waiting_heap = [e for e in waiting_heap if e[2] not in backfilled_idxs]
                heapq.heapify(waiting_heap)

        # 3. Advance time.
        next_submit = submit_times[submit_idx] if submit_idx < n_jobs else float("inf")
        next_done   = running_heap[0][0] if running_heap else float("inf")
        new_now = min(next_submit, next_done)
        if new_now == float("inf"):
            break
        now = new_now

        # 4. Process completions and arrivals.
        while running_heap and running_heap[0][0] <= now:
            _, freed = heapq.heappop(running_heap)
            free_nodes += freed
        while submit_idx < n_jobs and submit_times[submit_idx] <= now:
            _push(submit_idx)
            submit_idx += 1

    return from_dispatch_log(dispatch_log, sim_end_epoch)
