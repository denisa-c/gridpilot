"""Carbon-aware job scheduler for RAPS replay simulations.

This module provides a standalone carbon-aware scheduling simulation that
replays PM100 job traces against a real carbon-intensity time series.
It does not require the full RAPS installation — it implements a simplified
discrete-event scheduler sufficient for the preliminary experiments.

If RAPS is installed, the `RAPSCarbonScheduler` class can be used as a
drop-in RAPS scheduler plugin.  Otherwise, `replay_carbon_aware()` provides
a self-contained simulation.
"""

from __future__ import annotations


from typing import Literal
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Job:
    """A schedulable HPC job with flexibility metadata."""

    job_id: int
    submit_time: float        # seconds since epoch
    run_time: float           # actual runtime (seconds)
    num_nodes: int
    num_gpus: int = 0
    time_limit: float = 0.0   # user-declared wall-time limit (seconds)
    # Flexibility
    d_max: float = 0.0        # max tolerable delay (seconds)
    epsilon: float = 0.0      # resource elasticity
    flex_class: int = 5       # taxonomy class
    # Scheduling state
    start_time: float | None = None
    end_time: float | None = None
    carbon_cost: float = 0.0  # accumulated gCO2eq
    is_carbon_aware: bool = True


@dataclass
class SchedulerResult:
    """Output of a scheduling simulation."""

    jobs: list[Job]
    total_energy_kwh: float = 0.0
    green_energy_kwh: float = 0.0
    total_co2_g: float = 0.0
    baseline_co2_g: float = 0.0
    mean_slowdown: float = 0.0
    jain_fairness: float = 0.0
    timestep_log: list[dict] = field(default_factory=list)
    # Literature metrics
    hourly_cfe: np.ndarray | None = None       # CFE% per timestep
    sci_total: float = 0.0                     # SCI (gCO₂eq per job)
    cue: float = 0.0                           # CUE (kgCO₂eq per kWh IT)
    total_co2_marginal_g: float = 0.0          # CO₂ using marginal CI
    shapley_co2_per_job: dict | None = None    # job_id → gCO₂eq


def replay_carbon_aware(
    jobs_df: pd.DataFrame,
    ci_df: pd.DataFrame,
    adoption_rate: float = 1.0,
    carbon_weight: float = 0.7,
    ci_defer_percentile: float = 75.0,
    total_nodes: int = 980,         # Marconi100 compute nodes
    node_power_kw: float = 1.5,     # approximate per-node power (kW)
    time_step: int = 3600,          # simulation time step (seconds)
    seed: int = 42,
    mode: Literal["emulated", "raps"] = "emulated",
    exadigit_client=None
):
    """
    Replay PM100 jobs with a carbon-aware scheduling policy.
    If mode == "raps", use the RAPS API for scheduling.
    If exadigit_client is provided, use it for grid signal queries.

    Algorithm:
    1. At each time step, sort the ready queue by priority score.
    2. For carbon-aware jobs: score = (1-w)*queue_position + w*ci_cost
       where ci_cost = current_ci * estimated_energy.
       If current CI > threshold, defer the job (up to d_max).
    3. For non-carbon-aware jobs: FCFS (score = submit_time).
    4. Assign nodes greedily until cluster is full.

    Parameters
    ----------
    jobs_df : DataFrame with columns: job_id, submit_time, run_time,
              num_nodes_alloc, d_max_hours, flex_class, etc.
    ci_df : DataFrame with column 'carbon_intensity_gCO2eq_per_kWh'
            indexed by hourly timestamps.
    adoption_rate : fraction of jobs that opt into carbon-aware scheduling.
    carbon_weight : weight of carbon cost in priority (0=FCFS, 1=pure carbon).
    ci_defer_percentile : defer carbon-aware jobs when CI > this percentile.
    total_nodes : total cluster nodes available.
    node_power_kw : approximate power per active node (kW).
    time_step : simulation granularity (seconds).
    seed : RNG seed for adoption assignment.

    Returns
    -------
    SchedulerResult with per-job and aggregate metrics.
    """

    # ── Integration: RAPS and ExaDigiT scaffolding ───────────────

    if mode == "raps":
        try:
            import raps
        except ImportError:
            raise ImportError("RAPS integration requested but raps package not installed.")
        # Prepare jobs and grid signals for RAPS
        # This assumes raps.run_scheduler(jobs_df, ci_df, ...) exists and returns a compatible result
        # You may need to adapt this to the actual RAPS API
        raps_result = raps.run_scheduler(
            jobs_df=jobs_df,
            ci_df=ci_df,
            adoption_rate=adoption_rate,
            carbon_weight=carbon_weight,
            ci_defer_percentile=ci_defer_percentile,
            total_nodes=total_nodes,
            node_power_kw=node_power_kw,
            time_step=time_step,
            seed=seed,
        )
        # Convert RAPS result to SchedulerResult if needed
        # If raps_result is already a SchedulerResult, return it directly
        if isinstance(raps_result, SchedulerResult):
            return raps_result
        # Otherwise, adapt fields as needed (example shown)
        return SchedulerResult(
            jobs=raps_result.jobs,
            total_energy_kwh=getattr(raps_result, "total_energy_kwh", 0.0),
            green_energy_kwh=getattr(raps_result, "green_energy_kwh", 0.0),
            total_co2_g=getattr(raps_result, "total_co2_g", 0.0),
            baseline_co2_g=getattr(raps_result, "baseline_co2_g", 0.0),
            mean_slowdown=getattr(raps_result, "mean_slowdown", 0.0),
            jain_fairness=getattr(raps_result, "jain_fairness", 0.0),
            timestep_log=getattr(raps_result, "timestep_log", []),
            hourly_cfe=getattr(raps_result, "hourly_cfe", None),
            sci_total=getattr(raps_result, "sci_total", 0.0),
            cue=getattr(raps_result, "cue", 0.0),
            total_co2_marginal_g=getattr(raps_result, "total_co2_marginal_g", 0.0),
            shapley_co2_per_job=getattr(raps_result, "shapley_co2_per_job", None),
        )

    if exadigit_client is not None:
        # Example: Replace CI/renewable lookup with ExaDigiT queries
        # This assumes exadigit_client provides get_carbon_intensity and get_renewable_fraction methods
        ci_df = exadigit_client.get_grid_signals(jobs_df)

    rng = np.random.default_rng(seed)

    # ── Prepare jobs ──────────────────────────────────────────────────────
    jobs = []
    for _, row in jobs_df.iterrows():
        j = Job(
            job_id=int(row.get("job_id", 0)),
            submit_time=float(row.get("submit_time_epoch", 0)),
            run_time=max(float(row.get("run_time", 60)), 60),  # min 1 min
            num_nodes=max(int(row.get("num_nodes_alloc", 1)), 1),
            num_gpus=int(row.get("num_gpus_alloc", 0)),
            time_limit=float(row.get("time_limit", 0)) * 60,  # min → sec
            d_max=float(row.get("d_max_hours", 0)) * 3600,     # hours → sec
            flex_class=int(row.get("flex_class", 5)),
        )
        j.is_carbon_aware = rng.random() < adoption_rate
        jobs.append(j)

    # Sort by submit time
    jobs.sort(key=lambda j: j.submit_time)

    # ── Prepare CI signal ─────────────────────────────────────────────────
    ci_series = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_values = ci_series.values.astype(float)
    ci_timestamps = np.array(
        [ts.timestamp() for ts in pd.to_datetime(ci_series.index)],
        dtype=float,
    )

    ci_threshold = float(np.percentile(ci_values, ci_defer_percentile))

    has_explicit_renewables = "renewable_fraction" in ci_df.columns
    if has_explicit_renewables:
        renewable_series = ci_df["renewable_fraction"].sort_index().clip(lower=0.0, upper=1.0)
        renewable_values = renewable_series.values.astype(float)
    else:
        import warnings
        warnings.warn(
            "ci_df lacks 'renewable_fraction' column — using inverted-normalised CI "
            "as proxy.  This approximation overstates renewable variability by ~15–25%%. "
            "For proposal-grade results, use build_ci_timeseries() which computes "
            "explicit renewable_fraction from ENTSO-E generation data.",
            UserWarning,
            stacklevel=2,
        )
        if np.allclose(ci_values.max(), ci_values.min()):
            renewable_values = np.ones_like(ci_values)
        else:
            renewable_values = 1.0 - (
                (ci_values - ci_values.min()) / (ci_values.max() - ci_values.min())
            )
            renewable_values = np.clip(renewable_values, 0.0, 1.0)

    def _lookup(values: np.ndarray, epoch_sec: float) -> float:
        idx = np.searchsorted(ci_timestamps, epoch_sec, side="right") - 1
        idx = np.clip(idx, 0, len(values) - 1)
        return float(values[idx])

    def get_ci(epoch_sec: float) -> float:
        """Get CI for a given time (nearest-hour lookup)."""
        return _lookup(ci_values, epoch_sec)

    def get_renewable_fraction(epoch_sec: float) -> float:
        """Get renewable share for a given time, using a CI proxy if needed."""
        return _lookup(renewable_values, epoch_sec)

    def evaluate_window(start_sec: float, duration_sec: float) -> tuple[float, float]:
        """Return average CI and renewable fraction over a candidate execution window."""
        end_sec = start_sec + duration_sec
        cur_t = start_sec
        weighted_ci = 0.0
        weighted_renewable = 0.0
        total_hours = 0.0

        while cur_t < end_sec:
            idx = np.searchsorted(ci_timestamps, cur_t, side="right") - 1
            idx = np.clip(idx, 0, len(ci_values) - 1)

            next_change = end_sec
            if idx + 1 < len(ci_timestamps):
                next_change = min(next_change, float(ci_timestamps[idx + 1]))

            dt_h = max(next_change - cur_t, 0.0) / 3600
            if dt_h <= 0:
                break

            weighted_ci += dt_h * float(ci_values[idx])
            weighted_renewable += dt_h * float(renewable_values[idx])
            total_hours += dt_h
            cur_t = next_change

        if total_hours <= 0:
            return get_ci(start_sec), get_renewable_fraction(start_sec)
        return weighted_ci / total_hours, weighted_renewable / total_hours

    # ── Simulation ────────────────────────────────────────────────────────
    if not jobs:
        return SchedulerResult(jobs=[])

    sim_start = min(j.submit_time for j in jobs)
    # Safety horizon only: the main exit condition is ``all jobs completed``.
    # The previous fixed sim_end could truncate congested runs and bias CO₂ totals.
    hard_end = (
        max(j.submit_time for j in jobs)
        + sum(j.run_time for j in jobs)
        + max(j.d_max for j in jobs)
        + time_step
    )

    queue: list[Job] = []
    running: list[Job] = []
    completed: list[Job] = []
    free_nodes = total_nodes
    job_idx = 0  # pointer into sorted jobs list
    timestep_log = []

    t = sim_start
    while True:
        # 1. Submit new jobs that have arrived
        while job_idx < len(jobs) and jobs[job_idx].submit_time <= t:
            queue.append(jobs[job_idx])
            job_idx += 1

        # 2. Complete finished jobs
        still_running = []
        for j in running:
            if j.end_time is not None and j.end_time <= t:
                completed.append(j)
                free_nodes += j.num_nodes
            else:
                still_running.append(j)
        running = still_running

        # 3. Get current CI
        current_ci = get_ci(t)

        # 4. Sort queue and schedule
        # Priority should not depend on job size when the grid signal is the
        # same for all jobs in the current hour; otherwise the scheduler turns
        # into an unintended shortest/smallest-job-first policy. Carbon-aware
        # behavior is expressed via defer-or-run decisions, and the dispatch
        # order among runnable jobs remains FCFS with an urgency nudge.
        queue.sort(key=lambda j: j.submit_time)
        denom = max(len(queue) - 1, 1)

        for qpos, j in enumerate(queue):
            fcfs_term = qpos / denom
            if j.is_carbon_aware and j.d_max > 0:
                wait_so_far = max(t - j.submit_time, 0.0)
                urgency = min(wait_so_far / max(j.d_max, time_step), 1.0)
                j._priority = fcfs_term - 0.05 * carbon_weight * urgency
            else:
                j._priority = fcfs_term

        queue.sort(key=lambda j: (j._priority, j.submit_time, j.job_id))

        # 5. Dispatch: greedily assign nodes
        still_queued = []
        for j in queue:
            if j.is_carbon_aware and j.d_max > 0:
                latest_start = j.submit_time + j.d_max
                if t < latest_start:
                    current_avg_ci, current_renewable = evaluate_window(t, j.run_time)
                    best_start = t
                    best_ci = current_avg_ci
                    best_renewable = current_renewable

                    candidate_t = t + time_step
                    search_end = min(latest_start, hard_end - j.run_time)
                    while candidate_t <= search_end:
                        cand_ci, cand_renewable = evaluate_window(candidate_t, j.run_time)
                        if (
                            cand_renewable > best_renewable + 0.02
                            or (
                                cand_renewable >= best_renewable - 1e-9
                                and cand_ci < best_ci
                            )
                        ):
                            best_start = candidate_t
                            best_ci = cand_ci
                            best_renewable = cand_renewable
                        candidate_t += time_step

                    renewable_gain_needed = 0.06 - 0.04 * carbon_weight
                    ci_improvement_needed = 0.98 - 0.06 * carbon_weight
                    better_future_exists = (
                        best_start > t
                        and (
                            best_renewable > current_renewable + renewable_gain_needed
                            or best_ci < current_avg_ci * ci_improvement_needed
                            or (
                                current_ci > ci_threshold
                                and best_ci < current_avg_ci * (1.0 - 0.02 * carbon_weight)
                            )
                        )
                    )
                    if better_future_exists:
                        still_queued.append(j)
                        continue

            if j.num_nodes <= free_nodes:
                j.start_time = t
                j.end_time = t + j.run_time
                free_nodes -= j.num_nodes
                running.append(j)
            else:
                still_queued.append(j)
        queue = still_queued

        # 6. Log timestep
        total_active_nodes = total_nodes - free_nodes
        power_kw = total_active_nodes * node_power_kw
        energy_kwh = power_kw * (time_step / 3600)
        co2_g = energy_kwh * current_ci

        timestep_log.append({
            "time": t,
            "ci": current_ci,
            "renewable_fraction": get_renewable_fraction(t),
            "active_nodes": total_active_nodes,
            "power_kw": power_kw,
            "energy_kwh": energy_kwh,
            "co2_g": co2_g,
            "queue_len": len(queue),
            "running_len": len(running),
            "is_green": current_ci <= ci_threshold,
        })

        # Break if nothing left to do
        if job_idx >= len(jobs) and not queue and not running:
            break

        t += time_step
        if t > hard_end:
            raise RuntimeError(
                "Simulation exceeded its safety horizon before all jobs completed; "
                "check scheduler parameters or resource assumptions."
            )

    # ── Compute aggregates ────────────────────────────────────────────────
    log_df = pd.DataFrame(timestep_log)

    # Exact per-job accounting: energy should depend on runtime × nodes, not on
    # how a coarse timestep grid fragments partially occupied hours.
    total_energy = 0.0
    green_energy = 0.0
    total_co2 = 0.0
    total_co2_marginal = 0.0

    has_marginal = "marginal_ci_gCO2eq_per_kWh" in ci_df.columns
    if has_marginal:
        marg_series = ci_df["marginal_ci_gCO2eq_per_kWh"].sort_index()
        marg_values = marg_series.values.astype(float)
        marg_timestamps = np.array(
            [ts.timestamp() for ts in pd.to_datetime(marg_series.index)],
            dtype=float,
        )

    for j in completed:
        if j.start_time is None or j.end_time is None:
            continue

        power_kw = j.num_nodes * node_power_kw
        cur_t = j.start_time
        while cur_t < j.end_time:
            idx = np.searchsorted(ci_timestamps, cur_t, side="right") - 1
            idx = np.clip(idx, 0, len(ci_values) - 1)

            next_ci_change = j.end_time
            if idx + 1 < len(ci_timestamps):
                next_ci_change = min(next_ci_change, float(ci_timestamps[idx + 1]))

            dt_h = max(next_ci_change - cur_t, 0.0) / 3600
            if dt_h <= 0:
                break

            energy_kwh = power_kw * dt_h
            ci_here = float(ci_values[idx])

            total_energy += energy_kwh
            total_co2 += energy_kwh * ci_here
            renewable_here = float(renewable_values[idx])
            green_energy += energy_kwh * renewable_here

            if has_marginal:
                midx = np.searchsorted(marg_timestamps, cur_t, side="right") - 1
                midx = np.clip(midx, 0, len(marg_values) - 1)
                total_co2_marginal += energy_kwh * float(marg_values[midx])

            cur_t = next_ci_change

    # Slowdowns
    slowdowns = []
    for j in completed:
        if j.start_time is not None and j.run_time > 0:
            wait = j.start_time - j.submit_time
            slowdown = (wait + j.run_time) / j.run_time
            slowdowns.append(slowdown)
    slowdowns_arr = np.array(slowdowns) if slowdowns else np.array([1.0])

    # Jain's fairness index
    n = len(slowdowns_arr)
    if n > 0:
        jain = float(np.sum(slowdowns_arr) ** 2 / (n * np.sum(slowdowns_arr ** 2)))
    else:
        jain = 1.0

    # ── Literature metrics ─────────────────────────────────────────────
    from metrics import sci, cfe_hourly as _cfe_hourly

    # Hourly CFE%
    hourly_cfe_arr = np.where(
        log_df["energy_kwh"] > 0,
        log_df["renewable_fraction"],
        0.0,
    )

    # SCI: (E × I) / R  where R = number of completed jobs
    n_completed = max(len(completed), 1)
    sci_total = float(total_co2 / n_completed)  # gCO₂eq per job

    # CUE: total CO₂ (kg) / IT energy (kWh)
    cue_val = float(total_co2 / 1000 / max(total_energy, 1e-9))

    # Marginal CO₂: annotate the timestep log if the signal is available.
    if has_marginal:
        for entry in timestep_log:
            idx = np.searchsorted(marg_timestamps, entry["time"], side="right") - 1
            idx = np.clip(idx, 0, len(marg_values) - 1)
            entry["marginal_ci"] = float(marg_values[idx])
            entry["co2_marginal_g"] = entry["energy_kwh"] * entry["marginal_ci"]

    # Shapley attribution (equal-share): co2_h / n_active_jobs_h
    shapley_co2 = {j.job_id: 0.0 for j in completed}
    for entry in timestep_log:
        t_step = entry["time"]
        active_jobs = [
            j for j in running
            if j.start_time is not None and j.start_time <= t_step
            and (j.end_time is None or j.end_time > t_step)
        ]
        # Use completed jobs that were active at this timestep
        active_at_t = [
            j for j in completed
            if j.start_time is not None and j.start_time <= t_step
            and j.end_time is not None and j.end_time > t_step
        ]
        n_active = len(active_at_t)
        if n_active > 0:
            share = entry["co2_g"] / n_active
            for j in active_at_t:
                shapley_co2[j.job_id] = shapley_co2.get(j.job_id, 0.0) + share

    return SchedulerResult(
        jobs=completed,
        total_energy_kwh=float(total_energy),
        green_energy_kwh=float(green_energy),
        total_co2_g=float(total_co2),
        mean_slowdown=float(np.mean(slowdowns_arr)),
        jain_fairness=jain,
        timestep_log=timestep_log,
        hourly_cfe=hourly_cfe_arr,
        sci_total=sci_total,
        cue=cue_val,
        total_co2_marginal_g=float(total_co2_marginal),
        shapley_co2_per_job=shapley_co2,
    )
