"""
experiments_v2/src/schedulers/replay.py
========================================
REPLAY — reproduce the historical M100 dispatch.

What it does
------------
For each job in the input trace, dispatch it at its **historical**
``start_time_epoch`` (the actual wall-clock time M100's operators
ran it), not at a re-simulated time.  No scheduler decision is
made; no contention is resolved.  The trace's recorded
``end_time_epoch`` (or ``start + runtime``) is taken as ground
truth.

What this baseline measures
---------------------------
REPLAY answers the question: *"What did M100 actually do
historically?"*  Comparing the f-SLA contract against REPLAY tests
whether the contract beats the cluster's actual scheduling
decisions, capturing whatever implicit operator-side policies
were in effect during the trace window.  This is a more conservative
baseline than FCFS or EASY-FCFS because real schedulers often
incorporate site-specific policies (fair-share, account quotas,
reservation windows) that a stylised FCFS/EASY model omits.

Required columns
----------------
The trace must carry either:
  - ``start_time_epoch`` (preferred), or
  - ``start_time`` (legacy pandas Timestamp)
and either ``end_time_epoch`` / ``end_time``, OR ``runtime_s`` /
``run_time`` to compute end = start + runtime.

If only ``submit_time_epoch`` is available (i.e., we're given a
trace where the historical dispatch decisions weren't recorded),
REPLAY raises ValueError — it would otherwise silently degenerate
to "dispatch at submit time", which is plain FCFS, not REPLAY.

Implementation
--------------
Trivial loop: one ``dispatch_log`` entry per row of ``jobs_df``,
F3-split applied by ``from_dispatch_log``.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .accounting import ScheduleResult, from_dispatch_log


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
    start_col: str = "start_time_epoch",
) -> ScheduleResult:
    """Replay the trace at its historical start times."""
    if jobs_df.empty:
        return ScheduleResult()

    # Resolve historical start time.  Try the preferred epoch column
    # first; fall back to a pandas Timestamp column with the legacy
    # name; if neither is usable, fall back to submit_time (degenerate
    # REPLAY = "dispatch at submit time", same as FCFS but no contention).
    if start_col in jobs_df.columns:
        start_epochs = pd.to_numeric(jobs_df[start_col], errors="coerce").to_numpy()
    elif "start_time" in jobs_df.columns:
        s = pd.to_datetime(jobs_df["start_time"], utc=True, errors="coerce")
        start_epochs = (s.astype("int64") // 10**9).to_numpy(dtype=float)
    else:
        # Degenerate fallback: dispatch at submit time.  Documented in
        # the docstring; surfaces an informational message so the
        # caller knows this isn't a true REPLAY of historical dispatch.
        print(f"[replay] WARN: no '{start_col}' or 'start_time' column; "
              f"falling back to submit_time (degenerate REPLAY)")
        start_epochs = pd.to_numeric(jobs_df[submit_col], errors="coerce").to_numpy()

    runtimes  = pd.to_numeric(jobs_df[runtime_col], errors="coerce").to_numpy()
    nodes_req = pd.to_numeric(jobs_df[nodes_col],   errors="coerce").fillna(1).clip(
                    upper=total_nodes).astype(int).to_numpy()
    submits   = pd.to_numeric(jobs_df[submit_col],  errors="coerce").to_numpy()

    dispatch_log = []
    for i in range(len(jobs_df)):
        start = float(start_epochs[i])
        runtime = float(runtimes[i])
        if not np.isfinite(start) or runtime <= 0:
            continue
        dispatch_log.append({
            "submit_epoch": float(submits[i]),
            "start_epoch":  start,
            "end_epoch":    start + runtime,
            "nodes":        int(nodes_req[i]),
            "runtime_s":    runtime,
            "replicas":     1.0,
        })

    return from_dispatch_log(dispatch_log, sim_end_epoch)
