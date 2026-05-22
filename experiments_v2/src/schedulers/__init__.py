"""
gridpilot/experiments_v2/src/schedulers/
========================================
Clean-room hand-rolled implementations of the canonical published
HPC schedulers that the f-SLA paper compares against, plus a
shared accounting module so every scheduler's absolute numbers are
directly comparable.

Schedulers
----------
- ``fcfs.run``       — First-Come-First-Served, no backfilling.
                       Mu'alem & Feitelson 2001 §2.
- ``easy_fcfs.run``  — FCFS + EASY backfilling.  Lifka 1995 §3.
- ``saf.run``        — Smallest-Area-First with EASY backfilling.
                       Carastan-Santos & de Camargo 2019 §3.
- ``replay.run``     — Replay the trace at its historical start times
                       (captures whatever operator-side policy was in
                       effect during the M100 trace window).

All schedulers expose the same signature:

    run(jobs_df, total_nodes, ci_df=None, pue_curve=None, *,
        sim_end_epoch, submit_col, runtime_col, nodes_col,
        ...optional scheduler-specific kwargs) -> ScheduleResult

``ci_df`` and ``pue_curve`` are accepted for API symmetry; the
CI-blind baselines ignore them.  Metrics are computed by
``run_metrics(...)`` from the shared accounting module — no
scheduler is allowed to compute its own absolute energy.

Why hand-rolled and not RAPS
----------------------------
The RAPS submodule ships strong scheduler implementations (FCFS,
SJF, LJF, PRIORITY, REPLAY, plus NONE / EASY / FIRSTFIT backfill)
in ``raps/schedulers/default.py``.  However, RAPS' replay path is
gated on the ``raps/dataloaders/marconi100.py`` dataloader, which
requires per-job ``cpu_power_consumption`` / ``node_power_consumption``
/ ``mem_power_consumption`` arrays (the PM100-published telemetry
schema; Antici et al. 2023, Zenodo 10127767).  Our M100 source is
the raw SLURM ``sacct`` dump, which has scheduler-relevant columns
but **no** per-job power arrays.

Three paths were considered (AUDIT_FINDINGS.md §5):
    (a) Download the PM100 dataset (~GB-scale, ties v2 to that schema)
    (b) Fork RAPS with a new ``m100_sacct`` dataloader (diverges upstream)
    (c) Hand-roll FCFS/EASY/SAF/REPLAY ourselves (~500 lines total)

Path (c) was chosen.  The algorithms are textbook (~100 lines each),
the implementations are short enough for a reviewer to read in
ten minutes, and the resulting code has no RAPS dependency at all.
The shared accounting module (``accounting.py``) is the load-bearing
piece — RAPS or not.
"""

from .accounting import (
    ScheduledJob,
    ScheduleResult,
    run_metrics,
    from_dispatch_log,
    CFE_REF_CI_G,
    P_NODE_KW,
)
from . import fcfs, easy_fcfs, saf, replay, fsla_carbon_aware

__all__ = [
    "ScheduledJob",
    "ScheduleResult",
    "run_metrics",
    "from_dispatch_log",
    "CFE_REF_CI_G",
    "P_NODE_KW",
    "fcfs",
    "easy_fcfs",
    "saf",
    "replay",
    "fsla_carbon_aware",
]
