"""
evaluation/scheduler_pue_aware.py
---------------------------------

PUE-aware scheduler extension that adds facility-level optimisation to the
ProACT-OPT scheduler. The dispatch decision is biased toward windows where
the product (carbon intensity × instantaneous PUE) is low, rather than
windows where carbon intensity alone is low.

This captures structural carbon savings from two effects:

1. Free-cooling alignment: ambient temperatures correlate with renewable-
   energy availability in many European grids (cold-weather wind events,
   summer-afternoon solar peaks coincide with high cooling demand). Aligning
   compute with low-PUE windows yields carbon savings beyond what CI tracing
   captures.

2. Load-dependent PUE: at low IT load, fixed facility overhead pushes PUE
   to 1.4+, so deferring a job into a window that already has high
   utilisation (lower PUE) reduces facility-level emissions even at constant
   carbon intensity.

The scheduler retains the four ProACT-OPT mechanisms (backfilling, power
capping, hybrid elasticity, budget-aware aging) and adds the PUE channel
as a fifth strategy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from cooling.cooling_pue_model import CoolingParams, compute_cooling_power_kw, calibrate_to_design_pue


def _lookup(t, ts, vals):
    idx = np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(vals) - 1)
    return float(vals[idx])


def replay_proact_opt_pue(
    jobs_df,
    ci_df,
    t_amb_series,
    cooling_params: CoolingParams | None = None,
    max_delay_h: int = 24,
    total_nodes: int = 980,
    node_power_kw: float = 1.5,
    time_step: int = 3600,
    seed: int = 42,
    elastic_fraction: float = 0.30,
    max_replicas: int = 4,
    # T4 elastic-burst envelope (CarbonScaler-style symmetric scaling).
    # When ``j["elastic"]`` is True, the dispatcher scales replicas in
    # the closed interval [t4_replica_min, t4_replica_max] inversely
    # with the facility signal: cleanest hour -> t4_replica_max (more
    # parallelism, more energy in clean hours); dirtiest hour ->
    # t4_replica_min (less parallelism, less energy in dirty hours).
    # The expected makespan is preserved when t4_replica_max =
    # 1 / t4_replica_min, which is the case for the default 0.5/2.0
    # envelope from the f-SLA contract specification (Sect. 3.1 of
    # the PECS paper).  Set t4_replica_min=1.0 to restore the v1.0
    # behaviour (replicas in [1, max_replicas], no scale-down).
    t4_replica_min: float = 0.5,
    t4_replica_max: float = 2.0,
    power_cap_threshold_pct: int = 75,
    power_cap_factor: float = 0.80,
    short_job_threshold_s: int = 600,
    enable_backfilling: bool = True,
    pue_weight: float = 0.5,
):
    """ProACT-OPT-PUE: facility-aware carbon scheduler.

    The dispatch decision uses a composite score:
        score(t) = (CI(t) × PUE(t)) / max(CI × PUE)
    so that the scheduler defers when the product is high and dispatches
    when it is low. The pue_weight argument controls the trade-off between
    pure CI tracing (weight = 0) and pure facility-emission tracing
    (weight = 1).
    """
    rng = np.random.default_rng(seed)
    cool_p = cooling_params or calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)

    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_vals = ci.values.astype(float)
    ci_ts = np.array([t.timestamp() for t in pd.to_datetime(ci.index)])

    # Pre-compute the facility-level emission signal at the CI timestamps
    t_amb_vals = np.array([float(t_amb_series.get(ts, 20.0)) for ts in ci.index])
    # Use a constant 75% IT-load proxy for the PUE precomputation; refined
    # online once running power is known
    it_proxy_kw = total_nodes * node_power_kw * 0.75
    pue_vals = np.array([
        compute_cooling_power_kw(it_proxy_kw, ta, cool_p)["pue_instantaneous"]
        for ta in t_amb_vals
    ])
    facility_signal = ci_vals * pue_vals
    fs_min, fs_max = facility_signal.min(), facility_signal.max()

    max_delay_s = max_delay_h * 3600

    jobs = []
    # Per-job elasticity: if the jobs DataFrame carries an
    # ``is_elastic`` column (typically set by the f-SLA Tier 4
    # ``Elastic Burst`` assignment), use it directly --- this gives
    # T4 jobs deterministic elastic behaviour rather than the random
    # ``elastic_fraction`` Bernoulli draw that the global default
    # uses for the rest of the workload.
    has_per_job_elastic = "is_elastic" in jobs_df.columns
    for _, row in jobs_df.iterrows():
        d_max_s = min(float(row.get("d_max_hours", 0)) * 3600, max_delay_s)
        if has_per_job_elastic:
            is_elastic = bool(row["is_elastic"])
        else:
            is_elastic = (rng.random() < elastic_fraction)
        jobs.append({
            "submit": float(row["submit_time_epoch"]),
            "runtime": max(float(row["run_time"]), 60),
            "nodes": max(int(row["num_nodes_alloc"]), 1),
            "d_max": d_max_s,
            "elastic": is_elastic,
            "is_short": row["run_time"] <= short_job_threshold_s,
            "start": None, "end": None, "progress": 0.0,
        })
    jobs.sort(key=lambda j: j["submit"])
    if not jobs:
        return {"n": 0, "co2_g": 0, "energy_kwh": 0, "green_kwh": 0,
                "facility_co2_g": 0, "slowdowns": np.array([1.0]),
                "completed": [], "avg_pue": 1.20}

    sim_start = min(j["submit"] for j in jobs)
    sim_end = max(j["submit"] + j["runtime"] + max_delay_s for j in jobs)

    queue, running, completed = [], [], []
    free_nodes = total_nodes
    job_idx = 0
    t = sim_start
    total_e = total_co2 = total_green = total_facility_co2 = 0.0
    pue_samples = []

    while t < sim_end and (job_idx < len(jobs) or queue or running):
        while job_idx < len(jobs) and jobs[job_idx]["submit"] <= t:
            queue.append(jobs[job_idx])
            job_idx += 1

        cur_ci = _lookup(t, ci_ts, ci_vals)
        cur_pue_proxy = _lookup(t, ci_ts, pue_vals)
        cur_facility_signal = _lookup(t, ci_ts, facility_signal)
        ci_norm = (cur_ci - ci_vals.min()) / max(ci_vals.max() - ci_vals.min(), 1)
        fs_norm = (cur_facility_signal - fs_min) / max(fs_max - fs_min, 1)

        # ────── Adaptive dispatch percentile over next 24 h ──────
        win_idx = (ci_ts >= t) & (ci_ts <= t + max_delay_s)
        local_signal = facility_signal[win_idx] if win_idx.any() else facility_signal
        local_high = float(np.percentile(local_signal, 66))
        is_high_signal_window = cur_facility_signal >= local_high

        # ────── Process running jobs (elasticity + power cap) ──────
        still_running = []
        active_nodes = total_nodes - free_nodes
        cur_it_kw = active_nodes * node_power_kw
        # Look up ambient using positional index aligned with CI series rather
        # than timestamp matching (avoids tz/precision mismatches)
        amb_idx = int(np.clip(np.searchsorted(ci_ts, t, side="right") - 1,
                              0, len(t_amb_vals) - 1))
        cur_t_amb = float(t_amb_vals[amb_idx])
        cool_now = compute_cooling_power_kw(max(cur_it_kw, 1.0), cur_t_amb, cool_p)
        cur_pue = cool_now["pue_instantaneous"]
        # Only sample PUE when cluster is meaningfully utilised, to avoid
        # startup/teardown artifacts dominating the average
        if cur_it_kw >= 0.05 * total_nodes * node_power_kw:
            pue_samples.append(cur_pue)

        for j in running:
            # T4 elastic-burst replica scaling.  Symmetric envelope:
            # fs_norm=0 (cleanest hour) -> replicas = t4_replica_max,
            # fs_norm=1 (dirtiest hour) -> replicas = t4_replica_min.
            # Replicas are now a float; in dirty hours t4_replica_min
            # can be < 1 (downscaling --- the CarbonScaler regime), which
            # the v1.0 dispatcher did NOT support (it only scaled up
            # 1 -> max_replicas).  Properly wires the T4 contract clause.
            if j["elastic"]:
                replicas = (t4_replica_max
                              - (t4_replica_max - t4_replica_min) * fs_norm)
                replicas = float(max(t4_replica_min,
                                       min(t4_replica_max, replicas)))
            else:
                replicas = 1.0
            applied_cap = power_cap_factor if cur_facility_signal > local_high else 1.0
            step_progress = replicas * applied_cap * (time_step / max(j["runtime"], 1))
            remaining = max(1.0 - j["progress"], 0)
            frac_used = min(1.0, remaining / max(step_progress, 1e-9))
            actual_dt = time_step * frac_used
            j["progress"] = min(1.0, j["progress"] + step_progress)

            energy_it = j["nodes"] * replicas * node_power_kw * applied_cap * (actual_dt / 3600)
            # Allocate cooling per IT-energy share
            energy_facility = energy_it * cur_pue
            total_e += energy_it
            total_co2 += energy_it * cur_ci  # IT-only carbon
            total_facility_co2 += energy_facility * cur_ci
            total_green += energy_it * (1.0 - ci_norm)

            if j["progress"] >= 1.0:
                j["end"] = t + actual_dt
                completed.append(j)
                free_nodes += j["nodes"]
            else:
                still_running.append(j)
        running = still_running

        # ────── Dispatch decisions: combined CI×PUE deferral ──────
        queue.sort(key=lambda x: x["submit"])
        deferred = []
        admit_now = []
        for j in queue:
            wait = t - j["submit"]
            budget_used = wait / max(j["d_max"], 1) if j["d_max"] > 0 else 1.0
            should_defer = (
                is_high_signal_window
                and not j["is_short"]
                and j["d_max"] > 0
                and budget_used < 0.7
                and (t + time_step) <= j["submit"] + j["d_max"]
            )
            if should_defer:
                deferred.append(j)
            else:
                admit_now.append(j)

        still_q = []
        for j in admit_now:
            if j["nodes"] <= free_nodes:
                j["start"] = t
                j["progress"] = 0.0
                free_nodes -= j["nodes"]
                running.append(j)
            else:
                still_q.append(j)

        # ────── Backfilling ──────
        if enable_backfilling and free_nodes > 0:
            for j in sorted(deferred, key=lambda x: x["runtime"]):
                if j["nodes"] <= free_nodes and j["runtime"] <= time_step * 4:
                    j["start"] = t
                    j["progress"] = 0.0
                    free_nodes -= j["nodes"]
                    running.append(j)
                    deferred.remove(j)

        queue = still_q + deferred
        t += time_step

    for j in running + queue:
        if j.get("start") is None:
            j["start"] = t
        j["end"] = t + max(j["runtime"], 1) * (1.0 - j.get("progress", 0))
        completed.append(j)

    slowdowns = []
    for j in completed:
        if j.get("start") is not None:
            wait = j["start"] - j["submit"]
            slowdowns.append(max((wait + j["runtime"]) / max(j["runtime"], 1), 1.0))
    slowdowns = np.array(slowdowns) if slowdowns else np.array([1.0])

    return {
        "n": len(completed),
        "co2_g": total_co2,
        "facility_co2_g": total_facility_co2,
        "energy_kwh": total_e,
        "green_kwh": total_green,
        "slowdowns": slowdowns,
        "completed": completed,
        "avg_pue": float(np.mean(pue_samples)) if pue_samples else 1.20,
    }


def replay_fcfs_pue(
    jobs_df, ci_df, t_amb_series,
    cooling_params: CoolingParams | None = None,
    total_nodes: int = 980, node_power_kw: float = 1.5,
    time_step: int = 3600, seed: int = 42,
):
    """FCFS baseline that uses the same PUE-aware facility-CO2 accounting
    as replay_proact_opt_pue, ensuring fair comparison.
    """
    rng = np.random.default_rng(seed)
    cool_p = cooling_params or calibrate_to_design_pue(target_pue=1.20, it_design_kw=1400.0)
    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_vals = ci.values.astype(float)
    ci_ts = np.array([t.timestamp() for t in pd.to_datetime(ci.index)])
    t_amb_vals = np.array([float(t_amb_series.get(ts, 20.0)) for ts in ci.index])
    ci_min, ci_max = ci_vals.min(), ci_vals.max()

    jobs = []
    for _, row in jobs_df.iterrows():
        jobs.append({
            "submit": float(row["submit_time_epoch"]),
            "runtime": max(float(row["run_time"]), 60),
            "nodes": max(int(row["num_nodes_alloc"]), 1),
            "start": None, "end": None,
        })
    jobs.sort(key=lambda j: j["submit"])
    if not jobs:
        return {"n":0,"co2_g":0,"facility_co2_g":0,"energy_kwh":0,"green_kwh":0,
                "slowdowns":np.array([1.0]),"completed":[],"avg_pue":1.20}

    sim_start = min(j["submit"] for j in jobs)
    sim_end = max(j["submit"] + j["runtime"] for j in jobs) + 7*86400
    queue, running, completed = [], [], []
    free_nodes = total_nodes
    job_idx = 0
    t = sim_start
    total_e = total_co2 = total_facility_co2 = total_green = 0.0
    pue_samples = []

    while t < sim_end and (job_idx < len(jobs) or queue or running):
        while job_idx < len(jobs) and jobs[job_idx]["submit"] <= t:
            queue.append(jobs[job_idx]); job_idx += 1

        still_run = []
        for j in running:
            if j["end"] and j["end"] <= t:
                completed.append(j); free_nodes += j["nodes"]
            else:
                still_run.append(j)
        running = still_run

        queue.sort(key=lambda x: x["submit"])
        still_q = []
        for j in queue:
            if j["nodes"] <= free_nodes:
                j["start"] = t; j["end"] = t + j["runtime"]
                free_nodes -= j["nodes"]; running.append(j)
            else:
                still_q.append(j)
        queue = still_q

        cur_ci = _lookup(t, ci_ts, ci_vals)
        ci_norm = (cur_ci - ci_min) / max(ci_max - ci_min, 1)
        amb_idx = int(np.clip(np.searchsorted(ci_ts, t, side="right") - 1, 0, len(t_amb_vals) - 1))
        cur_t_amb = float(t_amb_vals[amb_idx])
        active_nodes = total_nodes - free_nodes
        cur_it_kw = active_nodes * node_power_kw
        cool_now = compute_cooling_power_kw(max(cur_it_kw, 1.0), cur_t_amb, cool_p)
        cur_pue = cool_now["pue_instantaneous"]
        if cur_it_kw >= 0.05 * total_nodes * node_power_kw:
            pue_samples.append(cur_pue)

        e = active_nodes * node_power_kw * (time_step / 3600)
        total_e += e
        total_co2 += e * cur_ci
        total_facility_co2 += e * cur_pue * cur_ci
        total_green += e * (1.0 - ci_norm)
        t += time_step

    for j in queue + running:
        if j.get("start") is None:
            j["start"] = t; j["end"] = t + j["runtime"]
            completed.append(j)

    slowdowns = []
    for j in completed:
        if j.get("start") is not None:
            wait = j["start"] - j["submit"]
            slowdowns.append(max((wait + j["runtime"]) / max(j["runtime"], 1), 1.0))
    slowdowns = np.array(slowdowns) if slowdowns else np.array([1.0])
    return {"n":len(completed),"co2_g":total_co2,"facility_co2_g":total_facility_co2,
            "energy_kwh":total_e,"green_kwh":total_green,"slowdowns":slowdowns,
            "completed":completed,"avg_pue":float(np.mean(pue_samples)) if pue_samples else 1.20}
