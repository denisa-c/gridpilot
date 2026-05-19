"""
experiments_v2/src/schedulers/raps_adapter.py — DEFERRED PLACEHOLDER
=====================================================================
The original v2 plan routed the canonical HPC baselines (FCFS,
EASY-FCFS, SAF, REPLAY) through RAPS via this adapter.  That plan
was retired during Phase 3 of the audit (see ``AUDIT_FINDINGS.md``
§5) for the following reason:

> RAPS' replay path for M100 goes through ``raps/dataloaders/
> marconi100.py``, which requires per-job ``cpu_power_consumption`` /
> ``node_power_consumption`` / ``mem_power_consumption`` arrays
> (the PM100 published-telemetry schema, Zenodo 10127767).  Our
> M100 source is the raw SLURM ``sacct`` dump, which has scheduler-
> relevant columns but NO power arrays.  Forcing the adapter to
> work would require either downloading the PM100 dataset
> (~GB-scale, ties v2 to that schema) or forking RAPS with a new
> ``m100_sacct`` dataloader (diverges from upstream).

The hand-rolled baselines in ``fcfs.py``, ``easy_fcfs.py``,
``saf.py``, and ``replay.py`` are ~500 lines total and faithful to
the cited papers (Mu'alem & Feitelson 2001; Lifka 1995;
Carastan-Santos & de Camargo 2019).  They have no RAPS dependency
at all.

This file is preserved as a placeholder so the (a) and (b) routes
remain documented for a future maintainer who wants to revisit the
RAPS integration after acquiring the PM100 dataset or upstreaming
a SLURM-sacct dataloader.
"""
raise NotImplementedError(
    "experiments_v2/src/schedulers/raps_adapter.py is deferred.  "
    "Use the hand-rolled baselines in experiments_v2/src/schedulers/"
    "{fcfs,easy_fcfs,saf,replay}.py instead.  See AUDIT_FINDINGS.md §5."
)
