"""
experiments_v2/src/schedulers/fsla_carbon_aware.py
===================================================
v2-native carbon-aware f-SLA dispatcher (replaces the legacy
``replay_proact_opt_pue`` for the v2 paper figures).

Why this exists
---------------
The v1 dispatcher passively defers (queue + wait) and routinely
yields negative Delta-CFE.  The v2 scheduler below is a literal
reading of the carbon-aware-scheduling literature (Hanafy et
al. 2023, Lechowicz et al. 2025): for every job, scan its declared
deferral window for the *cleanest* feasible hour and start it there.

Forecast assumption
-------------------
**Perfect CI / CFE forecast over the user's declared deferral
window.**  The v2 paper claims this explicitly as the upper-bound
of what a contract-only mechanism (no model uncertainty) can
extract; the downstream production controller (the GridPilot
companion paper) is the place where forecast error is handled.
Here the scheduler peeks at ``ci_df[h]`` and
``ci_df['carbon_free_fraction'][h]`` for every candidate hour ``h
in [submit, submit + d_max_hours]`` without penalty — this is the
oracle baseline against which forecast-error degradation is
measured in follow-on work.

Optimization target
-------------------
When the CI parquet carries ``carbon_free_fraction`` (the canonical
Google / 24x7 CFE numerator), the scheduler does **argmax of the
carbon-free share** within the deferral window.  When only the
legacy CI column is present, it falls back to **argmin of CI**, the
equivalent monotone target up to the ``1 - CI/800`` transform.
Both are subject to per-hour free-node feasibility.

Inputs
------
``jobs_df`` must contain the columns produced by
``workload_taxonomy.assign_tiers_*``:

  * ``submit_time_epoch``  (s since UTC epoch)
  * ``run_time``           (s)
  * ``num_nodes_alloc``    (int)
  * ``d_max_hours``        (deferral window in hours; 0 = tier T0)

``ci_df`` must carry ``carbon_intensity_gCO2eq_per_kWh`` and may
optionally carry ``carbon_free_fraction`` (preferred — switches the
scheduler from argmin-CI to argmax-CFE-share).

Outputs
-------
A standard ``ScheduleResult`` consumable by ``run_metrics``.  Energy
and CFE accounting are done by the accounting module, not here.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .accounting import ScheduleResult, from_dispatch_log


def run(
    jobs_df: pd.DataFrame,
    total_nodes: int,
    ci_df: pd.DataFrame,
    pue_curve: Optional[pd.Series] = None,
    *,
    sim_end_epoch: float,
    submit_col:   str = "submit_time_epoch",
    runtime_col:  str = "run_time",
    nodes_col:    str = "num_nodes_alloc",
    dmax_col:     str = "d_max_hours",
    time_step_s:  float = 3600.0,
) -> ScheduleResult:
    """Dispatch ``jobs_df`` under a greedy carbon-aware deferral policy.

    For each job ``j``, the dispatcher considers every hour ``h`` in
    the half-open interval ``[submit_j, submit_j + d_max_j)`` (or the
    single hour ``[submit_j, submit_j + 1)`` for T0 rigid jobs) and
    picks the hour whose CI is smallest *and* whose run-length still
    fits within the per-hour free-node budget.  If no feasible hour is
    found, the job is dispatched at its earliest fit — same fallback
    as plain FCFS, so a deferral-incapable trace degrades to FCFS, not
    to nothing.

    The time grid is fixed at one hour (matching the ENTSO-E A75 CI
    resolution) so the per-hour bookkeeping is cheap: an array of
    ``free_nodes[t]`` indexed by hour offset from the window start.

    ``pue_curve`` is accepted for API symmetry with the v2 baselines
    and is unused here (PUE-aware deferral is a follow-on lever).
    """
    if jobs_df.empty:
        return ScheduleResult()

    work = jobs_df[[submit_col, runtime_col, nodes_col]].copy()
    if dmax_col in jobs_df.columns:
        work[dmax_col] = pd.to_numeric(
            jobs_df[dmax_col], errors="coerce"
        ).fillna(0.0)
    else:
        # Trace lacks tier info → behave exactly like plain FCFS.
        work[dmax_col] = 0.0

    work[submit_col]  = pd.to_numeric(work[submit_col],  errors="coerce")
    work[runtime_col] = pd.to_numeric(work[runtime_col], errors="coerce")
    work[nodes_col]   = pd.to_numeric(work[nodes_col],   errors="coerce")
    work = work.dropna(subset=[submit_col, runtime_col, nodes_col])
    if work.empty:
        return ScheduleResult()

    order = np.argsort(work[submit_col].to_numpy(), kind="stable")
    work = work.iloc[order].reset_index(drop=True)
    work[nodes_col] = (work[nodes_col]
                       .clip(upper=total_nodes).astype(int))

    submit_times = work[submit_col].to_numpy(dtype=float)
    runtimes     = work[runtime_col].to_numpy(dtype=float)
    nodes_req    = work[nodes_col].to_numpy(dtype=int)
    dmax_h       = work[dmax_col].to_numpy(dtype=float)

    # ── CI + CFE lookup grids ────────────────────────────────────────
    # We optimize the carbon-free generation share (argmax) when the
    # parquet carries it; otherwise we fall back to argmin(CI), which
    # is the same monotone target up to the 1 - CI / 800 transform
    # but loses fidelity when the grid mix is dominated by sources
    # with similar CI but different "clean" classifications (e.g.,
    # biomass).  Using the share directly matches the Google /
    # 24x7 CFE accounting convention.
    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].to_numpy(dtype=float)
    if "carbon_free_fraction" in ci_df.columns:
        cfe = ci_df["carbon_free_fraction"].clip(0.0, 1.0).to_numpy(dtype=float)
        score = cfe          # higher = better
        target_is_max = True
    else:
        score = -ci          # higher = better (equivalent to argmin CI)
        target_is_max = True
    ci_index = pd.to_datetime(ci_df.index, utc=True)
    ci_t0    = float(ci_index[0].timestamp())
    n_hours  = len(ci)
    # Pad scoring arrays so jobs that overrun the window see a defined
    # value (only matters for accounting; ScheduleResult is later
    # truncated by the F3 within-window rule).
    score_pad = float(np.median(score)) if score.size else 0.0

    # ── Resource bookkeeping ──────────────────────────────────────────
    # free_nodes[h] = nodes available during hour ``h`` (0-indexed from
    # ci_t0).  We over-allocate by 48 hours to cover deferral tails that
    # spill past the CI window (same convention as 04c, which pads the
    # CI window by ±24 h on each side).
    horizon_hours = n_hours + 48
    free_nodes = np.full(horizon_hours, total_nodes, dtype=np.int64)

    def first_fit_start_h(nodes: int, len_h: int, lo: int, hi: int) -> int:
        """Earliest hour in ``[lo, hi]`` whose ``len_h``-hour window has
        ``free_nodes >= nodes``.  Returns -1 if none fits.  Linear scan;
        N×W is fine for the v2 paper's 10k jobs × ~200 hour windows.
        """
        lo = max(0, lo)
        hi = min(horizon_hours - len_h, hi)
        for h in range(lo, hi + 1):
            if int(free_nodes[h:h + len_h].min()) >= nodes:
                return h
        return -1

    def best_carbon_aware_h(nodes: int, len_h: int,
                              lo: int, hi: int) -> int:
        """Of the *feasible* hours in ``[lo, hi]``, pick the one whose
        carbon-free score is highest (argmax CFE fraction, or argmin CI
        in the legacy fallback).  Returns -1 if no feasibility window
        exists; the caller then degrades to plain first-fit.

        NOTE (Fix 1 reverted): a previous revision broke CFE ties by
        argmin(CI) to fix CH's small negative Delta-CI.  In practice
        the tie-breaker concentrated load into the lowest-CI hour
        within each tied-CFE window, exhausted node capacity there,
        and forced subsequent jobs into strictly lower-CFE hours --
        worsening the aggregate.  Reverted to argmax(CFE) only;
        the secondary key is left for Fix 2 once the regression is
        diagnosed (concentration vs. CFE/CI metric inconsistency).
        """
        lo = max(0, lo)
        hi = min(horizon_hours - len_h, hi)
        if lo > hi:
            return -1
        best_h, best_score = -1, -float("inf")
        for h in range(lo, hi + 1):
            if int(free_nodes[h:h + len_h].min()) < nodes:
                continue
            # Score at the *start* hour (matches accounting convention).
            s = score[h] if h < n_hours else score_pad
            if s > best_score:
                best_score, best_h = s, h
        return best_h

    # ── Main loop ─────────────────────────────────────────────────────
    dispatch_log: list[dict] = []
    for i in range(len(work)):
        submit_h = int((submit_times[i] - ci_t0) // time_step_s)
        if submit_h < 0:
            submit_h = 0
        len_h = max(1, int(np.ceil(runtimes[i] / time_step_s)))
        d_h   = int(round(dmax_h[i]))      # T0 → 0, T2 → 24, T3 → 168, ...
        latest_start_h = submit_h + d_h

        # T0 rigid: schedule at the earliest fit at-or-after submit_h.
        # All other tiers: argmin CI within [submit_h, submit_h + d_h].
        if d_h <= 0:
            start_h = first_fit_start_h(nodes_req[i], len_h,
                                          submit_h, horizon_hours - len_h)
        else:
            start_h = best_carbon_aware_h(nodes_req[i], len_h,
                                            submit_h, latest_start_h)
            if start_h < 0:
                # Nothing in the deferral window fits — slide forward
                # until something does (degrades to plain FCFS for this
                # job; matches f-SLA's "force-dispatch when infeasible"
                # clause documented in §2.3 of the paper).
                start_h = first_fit_start_h(nodes_req[i], len_h,
                                              submit_h,
                                              horizon_hours - len_h)
        if start_h < 0:
            # No fit anywhere — drop the job (will appear as truncated
            # in run_metrics).  Should be vanishingly rare in practice.
            continue
        # Commit the placement.
        free_nodes[start_h:start_h + len_h] -= int(nodes_req[i])
        start_epoch = ci_t0 + start_h * time_step_s
        end_epoch   = start_epoch + runtimes[i]
        dispatch_log.append({
            "submit_epoch": float(submit_times[i]),
            "start_epoch":  float(start_epoch),
            "end_epoch":    float(end_epoch),
            "nodes":        int(nodes_req[i]),
            "runtime_s":    float(runtimes[i]),
            "replicas":     1.0,
        })

    return from_dispatch_log(dispatch_log, sim_end_epoch)
