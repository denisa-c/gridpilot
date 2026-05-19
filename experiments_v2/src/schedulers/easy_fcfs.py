"""
experiments_v2/src/schedulers/easy_fcfs.py
===========================================
EASY-FCFS — FCFS with EASY (Extensible Argonne Scheduling sYstem)
backfilling.

Reference
---------
Lifka, D. A. (1995).  *The ANL/IBM SP scheduling system.*  In
*Job Scheduling Strategies for Parallel Processing* (JSSPP),
LNCS 949, 295–303.  See §3 ("The EASY scheduling algorithm").

Also Mu'alem & Feitelson (2001) §4, who give the modern formulation
in terms of a single head-of-queue *reservation*: the earliest time
the head can start (given currently running jobs' end times) is
computed, and jobs further down the queue may run **only if they
do not delay this reservation**.

Algorithm summary (Lifka 1995 §3):
  1. Dispatch all head-of-queue jobs that fit immediately
     (identical to FCFS).
  2. When the head no longer fits, compute its earliest reservation
     time: scan the running-jobs heap in end-time order, accumulating
     freed nodes, and stop when the head's nodes_required can be
     satisfied.  This gives ``reservation_time``.
  3. Iterate through the rest of the waiting queue in submit order.
     A trailing job is allowed to backfill iff:
        (a) it fits NOW (free_nodes >= its nodes), AND
        (b) it will finish before the reservation OR
            its nodes don't overlap with what the head needs.
     The (b) check has two common forms in the literature; we use the
     conservative one ("must finish before reservation") which is
     Lifka's original.  This guarantees no delay to the head.
  4. Advance the clock to the next event.

Implementation: extends the FCFS event-driven loop with the EASY
backfill step (3).  About 60 extra lines vs FCFS.
"""
from __future__ import annotations

import heapq
from typing import Optional

import numpy as np
import pandas as pd

from .accounting import ScheduledJob, ScheduleResult, from_dispatch_log


def _earliest_reservation(running_heap, free_nodes, head_nodes):
    """Compute the earliest wall-clock time at which the head job
    will fit, given the running heap.  Returns now-relative
    candidates: we walk the heap in order, freeing nodes, until we
    can satisfy ``head_nodes``.

    If the head already fits (free_nodes >= head_nodes), returns 0.0
    (reservation is "now", and the caller should dispatch it).
    """
    if free_nodes >= head_nodes:
        return 0.0
    # We don't mutate the heap; we walk a sorted copy.
    cumulative_free = free_nodes
    for end_t, freed in sorted(running_heap):
        cumulative_free += freed
        if cumulative_free >= head_nodes:
            return end_t  # absolute wall-clock time
    # Should never happen: the head needs more nodes than the cluster
    # has.  Caller clamps nodes_req to total_nodes upstream.
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
    """Dispatch ``jobs_df`` under EASY-FCFS and return the schedule.

    Like FCFS, ``ci_df`` and ``pue_curve`` are unused here — EASY is
    CI-blind.  Carbon-awareness is layered ABOVE the scheduler
    (the f-SLA contract dispatcher) or via the optional PCAPS plug-in.
    """
    if jobs_df.empty:
        return ScheduleResult()

    work = jobs_df[[submit_col, runtime_col, nodes_col]].copy()
    # Same defensive numeric coercion as fcfs.run; see comment there.
    work[submit_col]  = pd.to_numeric(work[submit_col],  errors="coerce")
    work[runtime_col] = pd.to_numeric(work[runtime_col], errors="coerce")
    work[nodes_col]   = pd.to_numeric(work[nodes_col],   errors="coerce")
    work = work.dropna(subset=[submit_col, runtime_col, nodes_col])
    if work.empty:
        print(f"[easy_fcfs] WARN: 0 schedulable rows after dropna")
        return ScheduleResult()
    # numpy argsort to bypass the pandas 2.x sort_values regression
    # (see fcfs.py for the same workaround).
    order = np.argsort(work[submit_col].to_numpy(), kind="stable")
    work = work.iloc[order].reset_index(drop=True)
    work[nodes_col] = work[nodes_col].clip(upper=total_nodes).astype(int)

    submit_times = work[submit_col].to_numpy(dtype=float)
    runtimes     = work[runtime_col].to_numpy(dtype=float)
    nodes_req    = work[nodes_col].to_numpy(dtype=int)

    n_jobs       = len(work)
    free_nodes   = total_nodes
    submit_idx   = 0
    waiting: list[int] = []
    running_heap: list[tuple[float, int]] = []
    dispatch_log: list[dict] = []

    now = float(submit_times[0])
    while submit_idx < n_jobs and submit_times[submit_idx] <= now:
        waiting.append(submit_idx)
        submit_idx += 1

    def _dispatch(j_idx: int) -> None:
        """Dispatch job j_idx at the current ``now`` and log it."""
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

    while waiting or running_heap or submit_idx < n_jobs:
        # 1. Dispatch every head-of-queue job that fits (same as FCFS).
        while waiting and free_nodes >= nodes_req[waiting[0]]:
            j = waiting.pop(0)
            _dispatch(j)

        # 2. EASY backfill step.  The head no longer fits; compute its
        #    reservation, then walk the rest of the queue and dispatch
        #    any job that fits now AND finishes by the reservation time.
        #    This is Lifka 1995 §3 "the EASY scheduling algorithm".
        if waiting:
            head = waiting[0]
            reservation = _earliest_reservation(
                running_heap, free_nodes, int(nodes_req[head])
            )
            # Iterate the rest of the queue (positions 1..) in submit
            # order; allow each to backfill if it doesn't delay the
            # head.  We do NOT pop from the queue if the job can't
            # backfill — it stays in submit order.
            i = 1
            while i < len(waiting):
                k = waiting[i]
                nodes_k   = int(nodes_req[k])
                runtime_k = float(runtimes[k])
                fits_now = free_nodes >= nodes_k
                finishes_by_reservation = (now + runtime_k) <= reservation
                if fits_now and finishes_by_reservation:
                    waiting.pop(i)   # leaves submit order intact for the rest
                    _dispatch(k)
                else:
                    i += 1

        # 3. Advance time to the next event.
        next_submit = submit_times[submit_idx] if submit_idx < n_jobs else float("inf")
        next_done   = running_heap[0][0] if running_heap else float("inf")
        new_now = min(next_submit, next_done)
        if new_now == float("inf"):
            break
        now = new_now

        # 4. Process completions and arrivals at ``now``.
        while running_heap and running_heap[0][0] <= now:
            _, freed = heapq.heappop(running_heap)
            free_nodes += freed
        while submit_idx < n_jobs and submit_times[submit_idx] <= now:
            waiting.append(submit_idx)
            submit_idx += 1

    return from_dispatch_log(dispatch_log, sim_end_epoch)
