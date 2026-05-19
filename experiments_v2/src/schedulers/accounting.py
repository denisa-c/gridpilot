"""
experiments_v2/src/schedulers/accounting.py
============================================
Single source of truth for converting a scheduler's output schedule
into the headline metrics every v2 figure / table consumes.

Why this module exists
----------------------
The v1 pipeline had two replay functions (`replay_fcfs_pue` and
`replay_proact_opt_pue`) that each rolled their own energy /
CO2 accumulators.  They computed energy on *different bases* (one
time-stepped cluster-power, the other per-job × replicas).  This
produced a 30× absolute-energy gap between the "plain-FCFS" and
"EASY-FCFS" baselines on the same trace at the same MW target,
making any Δ-vs-FCFS column methodologically broken.

The v2 design enforces:

  * **Per-job energy** is the literature convention:
        energy_j = nodes_j × runtime_j × P_node × replicas_j
    where replicas_j defaults to 1 for non-elastic schedulers.

  * **CI is evaluated at job start** (matches the carbon-aware-
    scheduling literature; ENTSO-E hourly CI, IPCC AR5 factors).

  * **PUE is evaluated at job start** (four-component cooling
    model anchored on raps/config/marconi100.yaml).

  * **Only within-window completions** contribute to headline
    metrics.  Jobs still running when the replay window ends are
    reported separately as ``n_truncated``.

No scheduler is allowed to override or shadow the values this
module computes.  Schedulers produce schedules; this module
produces metrics.

References
----------
- Per-job energy convention: Hanafy et al. 2023 (CarbonScaler),
  Wiesner et al. 2021 (Cucumber), Lechowicz et al. 2025 (PCAPS).
- Canonical 24/7 CFE: Kamatar et al. 2025; Radovanovic et al. 2021.
- PUE four-component model: this paper's METRICS.md §4, §5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# Canonical reference CI for 24/7 CFE (fossil marginal, g CO2eq/kWh).
CFE_REF_CI_G: float = 800.0

# M100 vendor figure (kW/node).  All v2 schedulers use the same value.
P_NODE_KW: float = 1.5


# ─────────────────────────────────────────────────────────────────────
# Schedule-level data classes
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScheduledJob:
    """One scheduled job's outcome.

    Attributes
    ----------
    submit_epoch : float
        Wall-clock submission time, seconds since UTC epoch.
    start_epoch : float
        Wall-clock dispatch time.  May be later than submit_epoch
        (deferred) or much later (queued behind earlier jobs).
    end_epoch : float
        Wall-clock completion time.  For jobs truncated at the
        replay window, this is the window end.
    nodes : int
        Number of nodes the dispatcher allocated.
    runtime_s : float
        Original requested / actual runtime in seconds.  Used for
        per-job energy via P_node × runtime.
    replicas : float
        CarbonScaler-style elastic multiplier (default 1.0 for
        non-elastic schedulers).  For T4 jobs in the f-SLA
        dispatcher this is the time-averaged replica count over
        the job's lifetime.
    """
    submit_epoch: float
    start_epoch: float
    end_epoch: float
    nodes: int
    runtime_s: float
    replicas: float = 1.0


@dataclass(frozen=True)
class ScheduleResult:
    """Two disjoint lists: jobs that finished cleanly within the
    replay window, and jobs that were still running (or queued)
    when the window ended.  The F3 split — only the first list
    contributes to headline metrics.
    """
    completed_within_window: list[ScheduledJob] = field(default_factory=list)
    truncated_at_window:     list[ScheduledJob] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# Time-series lookup helpers
# ─────────────────────────────────────────────────────────────────────

def _ts_lookup(ts_series: pd.Series, query_epoch: float) -> float:
    """Return the value of ``ts_series`` at or just before
    ``query_epoch``.  ts_series must be indexed by tz-aware
    datetimes; we convert once to a numpy float vector and use
    np.searchsorted for O(log N) lookup.

    For queries before the series start or after the series end,
    we clamp to the boundary value rather than NaN — this matches
    the v1 convention and is the right behaviour for replays whose
    trace is re-anchored onto the CI window.
    """
    values = ts_series.to_numpy(dtype=float)
    if values.size == 0:
        return 0.0
    ts_epoch = np.fromiter(
        (t.timestamp() for t in pd.to_datetime(ts_series.index, utc=True)),
        dtype=float, count=len(ts_series),
    )
    idx = int(np.searchsorted(ts_epoch, query_epoch, side="right") - 1)
    idx = max(0, min(len(values) - 1, idx))
    return float(values[idx])


# ─────────────────────────────────────────────────────────────────────
# The single metric function
# ─────────────────────────────────────────────────────────────────────

def run_metrics(
    schedule: ScheduleResult,
    ci_df: pd.DataFrame,
    pue_curve: Optional[pd.Series] = None,
    *,
    p_node_kw: float = P_NODE_KW,
    cfe_ref_ci_g: float = CFE_REF_CI_G,
) -> dict[str, float]:
    """Convert a ScheduleResult into the v2 canonical metric dict.

    Parameters
    ----------
    schedule
        The (completed_within_window, truncated_at_window) split.
        Only completed_within_window contributes to headline metrics.
    ci_df
        Hourly CI series, must carry a column
        ``carbon_intensity_gCO2eq_per_kWh`` and a tz-aware datetime
        index.
    pue_curve
        Optional hourly PUE series, indexed by tz-aware datetimes.
        If None, PUE is taken as 1.0 (IT energy == facility energy).
    p_node_kw
        Per-node power draw in kW.  Defaults to the M100 vendor
        figure (1.5 kW/node).
    cfe_ref_ci_g
        Reference CI for the canonical 24/7 CFE formula.  Defaults
        to 800 g/kWh (fossil-marginal; see METRICS §2).

    Returns
    -------
    dict with keys:
        n_completed_within_window  (int)
        n_truncated                (int)
        energy_kwh                 (float, IT only, per-job sum)
        ci_weighted_mean           (float, g CO2eq/kWh)
        cfe_canonical_pct          (float, [0, 100])
        co2_g_it                   (float, g CO2eq)
        co2_g_facility             (float, g CO2eq, PUE-multiplied)

    The function is *pure*: same inputs → same outputs, no side
    effects, no global state.  This is the contract every v2
    scheduler relies on.
    """
    ci_series = ci_df["carbon_intensity_gCO2eq_per_kWh"]

    n_completed = len(schedule.completed_within_window)
    n_truncated = len(schedule.truncated_at_window)

    if n_completed == 0:
        # Defined zero values when no completions; matches the v1
        # convention so downstream Δ computations don't NaN.
        return {
            "n_completed_within_window": 0,
            "n_truncated":                n_truncated,
            "energy_kwh":                 0.0,
            "ci_weighted_mean":           0.0,
            "cfe_canonical_pct":          0.0,
            "co2_g_it":                   0.0,
            "co2_g_facility":             0.0,
        }

    total_energy_kwh = 0.0
    total_ci_weighted_g_kwh = 0.0   # numerator of CI-weighted mean
    total_co2_g_it = 0.0
    total_co2_g_facility = 0.0

    for job in schedule.completed_within_window:
        ci_at_start = _ts_lookup(ci_series, job.start_epoch)
        pue_at_start = (
            _ts_lookup(pue_curve, job.start_epoch) if pue_curve is not None else 1.0
        )

        # Per-job IT energy (kWh).  Replicas scale the IT-side draw
        # 1:1; see CarbonScaler §3 for the convention.
        energy_kwh = (
            job.nodes * job.replicas * p_node_kw * job.runtime_s / 3600.0
        )

        total_energy_kwh         += energy_kwh
        total_ci_weighted_g_kwh  += ci_at_start * energy_kwh
        total_co2_g_it           += ci_at_start * energy_kwh
        total_co2_g_facility     += ci_at_start * energy_kwh * pue_at_start

    ci_weighted_mean = (
        total_ci_weighted_g_kwh / total_energy_kwh if total_energy_kwh > 0 else 0.0
    )
    cfe_canonical_pct = float(
        np.clip(100.0 * (1.0 - ci_weighted_mean / cfe_ref_ci_g), 0.0, 100.0)
    )

    return {
        "n_completed_within_window": n_completed,
        "n_truncated":                n_truncated,
        "energy_kwh":                 float(total_energy_kwh),
        "ci_weighted_mean":           float(ci_weighted_mean),
        "cfe_canonical_pct":          float(cfe_canonical_pct),
        "co2_g_it":                   float(total_co2_g_it),
        "co2_g_facility":             float(total_co2_g_facility),
    }


# ─────────────────────────────────────────────────────────────────────
# Convenience: build a ScheduleResult from a flat list of (job-row,
# start, end) tuples + a window cutoff
# ─────────────────────────────────────────────────────────────────────

def from_dispatch_log(
    dispatch_log: list[dict],
    sim_end_epoch: float,
) -> ScheduleResult:
    """Convert a flat list of dispatch records into the v2
    (completed_within_window, truncated_at_window) split.

    Each record must have at minimum:
        submit_epoch, start_epoch, end_epoch, nodes, runtime_s
    and may optionally carry:
        replicas (defaults to 1.0)

    A job is *completed within window* iff
        end_epoch <= sim_end_epoch,
    otherwise it is *truncated at window*.  Truncated jobs have
    their end_epoch clamped to sim_end_epoch and their runtime_s
    re-computed from (end - start) so that downstream code never
    sees an end past the cutoff.
    """
    done: list[ScheduledJob] = []
    trunc: list[ScheduledJob] = []
    for r in dispatch_log:
        if r["end_epoch"] <= sim_end_epoch:
            done.append(ScheduledJob(
                submit_epoch=float(r["submit_epoch"]),
                start_epoch=float(r["start_epoch"]),
                end_epoch=float(r["end_epoch"]),
                nodes=int(r["nodes"]),
                runtime_s=float(r["runtime_s"]),
                replicas=float(r.get("replicas", 1.0)),
            ))
        else:
            end = sim_end_epoch
            trunc.append(ScheduledJob(
                submit_epoch=float(r["submit_epoch"]),
                start_epoch=float(r["start_epoch"]),
                end_epoch=end,
                nodes=int(r["nodes"]),
                runtime_s=max(0.0, end - float(r["start_epoch"])),
                replicas=float(r.get("replicas", 1.0)),
            ))
    return ScheduleResult(
        completed_within_window=done,
        truncated_at_window=trunc,
    )
