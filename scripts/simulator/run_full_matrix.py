#!/usr/bin/env python3
"""
experiments/run_icpp.py — Comprehensive experiment matrix for ICPP 2026 paper.

Runs all configurations needed for the paper:
  - 3 workloads: M100 (real HPC), Philly-like (DL training), Acme-like (LLM)
  - 3 grids: CH, IT, DE (2025 historical CI)
  - 4 schedulers: FCFS, QoS-bounded, CarbonScaler, Threshold
  - Comprehensive metrics: CO2, CFE, p50/p95/p99 slowdown, Jain, ETTR

Output: results/icpp_full_matrix.csv plus all figures.
"""
from __future__ import annotations
import gc, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "evaluation"))

from ci_2025 import build_ci_2025
from scheduler_carbon import replay_carbon_aware
from metrics import cfe_empirical


# ════════════════════════════════════════════════════════════════════
# Extended schedulers
# ════════════════════════════════════════════════════════════════════

def _lookup_ci(t, ci_ts, ci_vals):
    idx = np.clip(np.searchsorted(ci_ts, t, side="right") - 1, 0, len(ci_vals) - 1)
    return float(ci_vals[idx])




def replay_simple_fcfs(jobs_df, ci_df, total_nodes=980, node_power_kw=1.5,
                       time_step=3600, seed=42):
    """Simple FCFS with the same timestep-based accounting as ProACT++.
    Used as the baseline for fair comparison across schedulers."""
    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_vals = ci.values.astype(float)
    ci_ts = np.array([t.timestamp() for t in pd.to_datetime(ci.index)])
    ci_min, ci_max = ci_vals.min(), ci_vals.max()

    jobs = []
    for _, row in jobs_df.iterrows():
        jobs.append({
            "submit": float(row["submit_time_epoch"]),
            "runtime": max(float(row["run_time"]), 60),
            "nodes": max(int(row["num_nodes_alloc"]), 1),
            "is_ca": False, "start": None, "end": None,
        })
    jobs.sort(key=lambda j: j["submit"])
    if not jobs: return _empty_result()

    sim_start = min(j["submit"] for j in jobs)
    sim_end = max(j["submit"] + j["runtime"] for j in jobs) + 7*86400  # generous tail
    queue, running, completed = [], [], []
    free_nodes = total_nodes
    job_idx = 0
    t = sim_start
    total_e = total_co2 = total_green = 0.0

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

        cur_ci = _lookup_ci(t, ci_ts, ci_vals)
        ci_norm = (cur_ci - ci_min) / max(ci_max - ci_min, 1)
        active = total_nodes - free_nodes
        e = active * node_power_kw * (time_step / 3600)
        total_e += e
        total_co2 += e * cur_ci
        total_green += e * (1.0 - ci_norm)
        t += time_step

    for j in queue + running:
        if j.get("start") is None:
            j["start"] = t; j["end"] = t + j["runtime"]
            completed.append(j)
    return _summarize(completed, total_e, total_co2, total_green)


def replay_fcfs(jobs_df, ci_df, total_nodes=980, node_power_kw=1.5,
                time_step=3600, seed=42):
    """First-come-first-served baseline."""
    return replay_carbon_aware(jobs_df, ci_df, adoption_rate=0.0,
                                node_power_kw=node_power_kw, seed=seed)


def replay_qos_bounded(jobs_df, ci_df, max_delay_h=24,
                        total_nodes=980, node_power_kw=1.5, seed=42):
    """ProACT QoS-bounded carbon-aware (the existing validated scheduler)."""
    # Cap d_max_hours to max_delay_h
    df = jobs_df.copy()
    df["d_max_hours"] = np.minimum(df["d_max_hours"], max_delay_h)
    return replay_carbon_aware(df, ci_df, adoption_rate=1.0,
                                carbon_weight=0.7, ci_defer_percentile=75.0,
                                node_power_kw=node_power_kw, seed=seed)


def replay_carbonscaler(jobs_df, ci_df, adoption_rate=1.0,
                         min_replicas=1, max_replicas=4,
                         total_nodes=980, node_power_kw=1.5,
                         time_step=3600, seed=42):
    """CarbonScaler-style (Hanafy et al. 2023, SIGMETRICS).

    Elastic replica scaling: more replicas at low CI, fewer at high CI.
    """
    rng = np.random.default_rng(seed)
    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_vals = ci.values.astype(float)
    ci_ts = np.array([t.timestamp() for t in pd.to_datetime(ci.index)])
    ci_min, ci_max = ci_vals.min(), ci_vals.max()

    jobs = []
    for _, row in jobs_df.iterrows():
        jobs.append({
            "submit": float(row["submit_time_epoch"]),
            "runtime": max(float(row["run_time"]), 60),
            "nodes_base": max(int(row["num_nodes_alloc"]), 1),
            "is_ca": rng.random() < adoption_rate,
            "start": None, "end": None, "progress": 0.0,
        })
    jobs.sort(key=lambda j: j["submit"])
    if not jobs:
        return _empty_result()

    sim_start = min(j["submit"] for j in jobs)
    sim_end = max(j["submit"] + j["runtime"] * 4 for j in jobs)
    queue, running, completed = [], [], []
    free_nodes = total_nodes
    job_idx = 0
    t = sim_start
    total_e = total_co2 = total_green = 0.0

    while t < sim_end and (job_idx < len(jobs) or queue or running):
        while job_idx < len(jobs) and jobs[job_idx]["submit"] <= t:
            queue.append(jobs[job_idx]); job_idx += 1
        cur_ci = _lookup_ci(t, ci_ts, ci_vals)
        ci_norm = (cur_ci - ci_min) / max(ci_max - ci_min, 1)

        still_running = []
        for j in running:
            if j["is_ca"]:
                replicas = max(min_replicas, min(max_replicas,
                    int(round(max_replicas - (max_replicas - min_replicas) * ci_norm))))
            else:
                replicas = 1
            # Progress made in this timestep at given replica count
            step_progress = (replicas / 1.0) * (time_step / max(j["runtime"], 1))
            # Fraction of timestep actually consumed (capped at 1 if step would overshoot)
            remaining = max(1.0 - j["progress"], 0)
            frac_used = min(1.0, remaining / max(step_progress, 1e-9))
            actual_dt = time_step * frac_used
            j["progress"] = min(1.0, j["progress"] + step_progress)
            # Energy accounted for the fraction actually used
            energy = j["nodes_base"] * replicas * node_power_kw * (actual_dt / 3600)
            total_e += energy
            total_co2 += energy * cur_ci
            total_green += energy * (1.0 - ci_norm)
            if j["progress"] >= 1.0:
                j["end"] = t + actual_dt
                completed.append(j); free_nodes += j["nodes_base"]
            else:
                still_running.append(j)
        running = still_running

        queue.sort(key=lambda x: x["submit"])
        still_q = []
        for j in queue:
            if j["nodes_base"] <= free_nodes:
                j["start"] = t
                free_nodes -= j["nodes_base"]
                running.append(j)
            else:
                still_q.append(j)
        queue = still_q
        t += time_step

    for j in running + queue:
        if j.get("start") is None: j["start"] = t
        j["end"] = t + max(j["runtime"], 1)
        completed.append(j)

    return _summarize(completed, total_e, total_co2, total_green)


def replay_threshold(jobs_df, ci_df, adoption_rate=1.0,
                      ci_threshold_pct=50, max_delay_h=24,
                      total_nodes=980, node_power_kw=1.5,
                      time_step=3600, seed=42):
    """Threshold scheduler: defer when CI > p50, hard 24h cap."""
    rng = np.random.default_rng(seed)
    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_vals = ci.values.astype(float)
    ci_ts = np.array([t.timestamp() for t in pd.to_datetime(ci.index)])
    threshold_ci = float(np.percentile(ci_vals, ci_threshold_pct))
    max_delay_s = max_delay_h * 3600

    jobs = []
    for _, row in jobs_df.iterrows():
        jobs.append({
            "submit": float(row["submit_time_epoch"]),
            "runtime": max(float(row["run_time"]), 60),
            "nodes": max(int(row["num_nodes_alloc"]), 1),
            "is_ca": rng.random() < adoption_rate,
            "start": None, "end": None,
        })
    jobs.sort(key=lambda j: j["submit"])
    if not jobs: return _empty_result()

    sim_start = min(j["submit"] for j in jobs)
    sim_end = max(j["submit"] + j["runtime"] + max_delay_s for j in jobs)
    ci_min, ci_max = ci_vals.min(), ci_vals.max()

    queue, running, completed = [], [], []
    free_nodes = total_nodes
    job_idx = 0
    t = sim_start
    total_e = total_co2 = total_green = 0.0

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

        cur_ci = _lookup_ci(t, ci_ts, ci_vals)
        ci_norm = (cur_ci - ci_min) / max(ci_max - ci_min, 1)

        queue.sort(key=lambda x: x["submit"])
        still_q = []
        for j in queue:
            wait = t - j["submit"]
            defer = (j["is_ca"] and cur_ci > threshold_ci and wait < max_delay_s)
            if defer:
                still_q.append(j); continue
            if j["nodes"] <= free_nodes:
                j["start"] = t; j["end"] = t + j["runtime"]
                free_nodes -= j["nodes"]; running.append(j)
            else:
                still_q.append(j)
        queue = still_q

        active = total_nodes - free_nodes
        e = active * node_power_kw * (time_step / 3600)
        total_e += e; total_co2 += e * cur_ci
        total_green += e * (1.0 - ci_norm)
        t += time_step

    for j in queue + running:
        if j.get("start") is None:
            j["start"] = t; j["end"] = t + j["runtime"]
            completed.append(j)

    return _summarize(completed, total_e, total_co2, total_green)




def replay_proact_plus(jobs_df, ci_df, max_delay_h=24,
                        total_nodes=980, node_power_kw=1.5,
                        time_step=3600, seed=42,
                        short_job_threshold_s=3600,
                        ci_pct_low=33, ci_pct_high=50, ci_improvement=0.05):
    """ProACT++ scheduler: improved QoS-bounded carbon-aware deferral.

    Key improvements over the basic QoS-bounded scheduler:
    1. RUNTIME-AWARE: jobs shorter than short_job_threshold_s run immediately
       (small jobs benefit little from deferral, but penalise QoS heavily).
    2. ADAPTIVE THRESHOLD: defer when current CI exceeds the 66th percentile
       of the next 24 hours (not the static full-trace 75th percentile).
    3. AGING: deferral score decreases with wait time so jobs near their
       budget get preferential dispatch.
    4. LOOK-AHEAD WINDOW: only defer if a window with at least 10 percent
       lower CI exists within min(d_max, 24h).
    """
    rng = np.random.default_rng(seed)
    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_vals = ci.values.astype(float)
    ci_ts = np.array([t.timestamp() for t in pd.to_datetime(ci.index)])
    max_delay_s = max_delay_h * 3600

    jobs = []
    for _, row in jobs_df.iterrows():
        d_max_s = float(row.get("d_max_hours", 0)) * 3600
        d_max_s = min(d_max_s, max_delay_s)
        jobs.append({
            "submit": float(row["submit_time_epoch"]),
            "runtime": max(float(row["run_time"]), 60),
            "nodes": max(int(row["num_nodes_alloc"]), 1),
            "d_max": d_max_s,
            "is_ca": True,  # all flexible jobs are carbon-aware
            "start": None, "end": None,
        })
    jobs.sort(key=lambda j: j["submit"])
    if not jobs: return _empty_result()

    sim_start = min(j["submit"] for j in jobs)
    sim_end = max(j["submit"] + j["runtime"] + max_delay_s for j in jobs)

    queue, running, completed = [], [], []
    free_nodes = total_nodes
    job_idx = 0
    t = sim_start
    total_e = total_co2 = total_green = 0.0
    ci_min, ci_max = ci_vals.min(), ci_vals.max()

    while t < sim_end and (job_idx < len(jobs) or queue or running):
        while job_idx < len(jobs) and jobs[job_idx]["submit"] <= t:
            queue.append(jobs[job_idx]); job_idx += 1

        # Complete finished jobs
        still_run = []
        for j in running:
            if j["end"] and j["end"] <= t:
                completed.append(j); free_nodes += j["nodes"]
            else:
                still_run.append(j)
        running = still_run

        cur_ci = _lookup_ci(t, ci_ts, ci_vals)
        # Adaptive local-window threshold: 66th percentile over next 24h
        window_end = t + max_delay_s
        win_idx = (ci_ts >= t) & (ci_ts <= window_end)
        local_ci = ci_vals[win_idx] if win_idx.any() else ci_vals
        local_pct_high = float(np.percentile(local_ci, ci_pct_high))
        local_pct_low = float(np.percentile(local_ci, ci_pct_low))

        # Dispatch decisions
        queue.sort(key=lambda x: x["submit"])
        still_q = []
        for j in queue:
            wait = t - j["submit"]
            budget_left = j["d_max"] - wait

            # Improvement 1: short jobs run immediately
            short_job = j["runtime"] <= short_job_threshold_s

            # Improvement 4: look ahead for genuinely better windows
            search_end = min(t + budget_left, window_end)
            search_mask = (ci_ts >= t) & (ci_ts <= search_end)
            if search_mask.any():
                future_min_ci = float(np.min(ci_vals[search_mask]))
                local_improvement = (cur_ci - future_min_ci) / max(cur_ci, 1)
            else:
                local_improvement = 0

            # Improvement 3: aging — defer less when budget is mostly consumed
            budget_used_frac = wait / max(j["d_max"], 1) if j["d_max"] > 0 else 1.0

            # Defer only if: current CI is above local high threshold,
            # there is a window with ≥10% lower CI, budget is < 50% used,
            # and the job is not "short"
            should_defer = (not short_job
                            and cur_ci > local_pct_high
                            and local_improvement >= ci_improvement
                            and budget_used_frac < 0.7
                            and j["d_max"] > 0)

            # Force-run if budget nearly exhausted
            if wait >= j["d_max"] - time_step:
                should_defer = False

            if should_defer:
                still_q.append(j); continue

            if j["nodes"] <= free_nodes:
                j["start"] = t; j["end"] = t + j["runtime"]
                free_nodes -= j["nodes"]; running.append(j)
            else:
                still_q.append(j)
        queue = still_q

        active = total_nodes - free_nodes
        e = active * node_power_kw * (time_step / 3600)
        total_e += e
        total_co2 += e * cur_ci
        ci_norm = (cur_ci - ci_min) / max(ci_max - ci_min, 1)
        total_green += e * (1.0 - ci_norm)
        t += time_step

    for j in queue + running:
        if j.get("start") is None:
            j["start"] = t; j["end"] = t + j["runtime"]
            completed.append(j)

    return _summarize(completed, total_e, total_co2, total_green)




def replay_proact_opt(jobs_df, ci_df, max_delay_h=24,
                       total_nodes=980, node_power_kw=1.5,
                       time_step=3600, seed=42,
                       elastic_fraction=0.3,        # fraction of jobs that support elasticity
                       max_replicas=4,              # maximum elastic replica count
                       power_cap_threshold_pct=75,  # apply DVFS when CI > this percentile
                       power_cap_factor=0.80,       # cap power to 80% of nominal
                       short_job_threshold_s=600,   # 10 min: never defer
                       enable_backfilling=True):
    """ProACT-OPT: state-of-the-art carbon-aware scheduler integrating
    backfilling, power capping, hybrid elasticity, and budget-aware aging.

    Per-job control selection:
      • elastic jobs (elastic_fraction) → CarbonScaler-style replica scaling
      • non-elastic jobs with d_max > 0 → bounded deferral with backfilling
      • short jobs and budget-near-zero → run immediately
      • running jobs during high-CI windows → power capping (DVFS)
    """
    rng = np.random.default_rng(seed)
    ci = ci_df["carbon_intensity_gCO2eq_per_kWh"].sort_index()
    ci_vals = ci.values.astype(float)
    ci_ts = np.array([t.timestamp() for t in pd.to_datetime(ci.index)])
    ci_min, ci_max = ci_vals.min(), ci_vals.max()
    max_delay_s = max_delay_h * 3600

    jobs = []
    for _, row in jobs_df.iterrows():
        d_max_s = min(float(row.get("d_max_hours", 0)) * 3600, max_delay_s)
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
    if not jobs: return _empty_result()

    sim_start = min(j["submit"] for j in jobs)
    sim_end = max(j["submit"] + j["runtime"] + max_delay_s for j in jobs)

    queue, running, completed = [], [], []
    free_nodes = total_nodes
    job_idx = 0
    t = sim_start
    total_e = total_co2 = total_green = 0.0

    while t < sim_end and (job_idx < len(jobs) or queue or running):
        # Submit arrivals
        while job_idx < len(jobs) and jobs[job_idx]["submit"] <= t:
            queue.append(jobs[job_idx]); job_idx += 1

        cur_ci = _lookup_ci(t, ci_ts, ci_vals)
        ci_norm = (cur_ci - ci_min) / max(ci_max - ci_min, 1)

        # ──────── Adaptive percentiles over next 24h ────────
        win_idx = (ci_ts >= t) & (ci_ts <= t + max_delay_s)
        local_ci = ci_vals[win_idx] if win_idx.any() else ci_vals
        local_high_ci = float(np.percentile(local_ci, 66))
        powercap_ci = float(np.percentile(local_ci, power_cap_threshold_pct))
        is_high_ci_window = cur_ci >= local_high_ci

        # ──────── Process running jobs (with elasticity + power cap) ────────
        still_running = []
        for j in running:
            # Elasticity: scale replicas inversely with CI
            if j["elastic"]:
                replicas = max(1, min(max_replicas,
                    int(round(max_replicas - (max_replicas - 1) * ci_norm))))
            else:
                replicas = 1

            # Power cap during high-CI window (EcoFreq-style)
            applied_cap = power_cap_factor if cur_ci > powercap_ci else 1.0

            # Progress made in this timestep
            step_progress = (replicas / 1.0) * applied_cap * (time_step / max(j["runtime"], 1))
            remaining = max(1.0 - j["progress"], 0)
            frac_used = min(1.0, remaining / max(step_progress, 1e-9))
            actual_dt = time_step * frac_used
            j["progress"] = min(1.0, j["progress"] + step_progress)

            energy = j["nodes"] * replicas * node_power_kw * applied_cap * (actual_dt / 3600)
            total_e += energy
            total_co2 += energy * cur_ci
            total_green += energy * (1.0 - ci_norm)

            if j["progress"] >= 1.0:
                j["end"] = t + actual_dt
                completed.append(j); free_nodes += j["nodes"]
            else:
                still_running.append(j)
        running = still_running

        # ──────── Dispatch decisions: deferral with backfilling ────────
        queue.sort(key=lambda x: x["submit"])

        # First pass: identify candidates to defer (large jobs in high-CI windows
        # with sufficient budget remaining)
        deferred = []
        admit_now = []
        for j in queue:
            wait = t - j["submit"]
            budget_used = wait / max(j["d_max"], 1) if j["d_max"] > 0 else 1.0
            # Defer condition: high CI window + budget < 70% used + not short + has d_max
            should_defer = (is_high_ci_window
                            and not j["is_short"]
                            and j["d_max"] > 0
                            and budget_used < 0.7
                            and (t + time_step) <= j["submit"] + j["d_max"])
            if should_defer:
                deferred.append(j)
            else:
                admit_now.append(j)

        # Dispatch admit_now jobs in order
        still_q = []
        for j in admit_now:
            if j["nodes"] <= free_nodes:
                j["start"] = t; j["progress"] = 0.0
                free_nodes -= j["nodes"]; running.append(j)
            else:
                still_q.append(j)

        # ──────── EASY-style backfilling ────────
        # When jobs are deferred, freed capacity should be used by shorter
        # jobs that fit. This is the single biggest QoS recovery mechanism.
        if enable_backfilling and free_nodes > 0:
            # Sort deferred jobs by runtime ASC for backfilling priority
            # (any deferred job that is "small enough" can be backfilled in)
            backfill_candidates = sorted(deferred, key=lambda x: x["runtime"])
            still_deferred = []
            for j in backfill_candidates:
                # Backfill only short jobs that fit and don't disturb plan
                if j["nodes"] <= free_nodes and j["runtime"] <= time_step * 4:
                    j["start"] = t; j["progress"] = 0.0
                    free_nodes -= j["nodes"]; running.append(j)
                else:
                    still_deferred.append(j)
            deferred = still_deferred

        queue = still_q + deferred
        t += time_step

    # Force-finish leftovers
    for j in running + queue:
        if j.get("start") is None:
            j["start"] = t
        j["end"] = t + max(j["runtime"], 1) * (1.0 - j.get("progress", 0))
        completed.append(j)

    return _summarize(completed, total_e, total_co2, total_green)


def _empty_result():
    return {"n":0,"co2_g":0,"energy_kwh":0,"green_kwh":0,"slowdowns":np.array([1.0]),"completed":[]}


def _summarize(completed, e, co2, green):
    s = []
    for j in completed:
        if j.get("start") is not None:
            wait = j["start"] - j["submit"]
            s.append(max((wait + j["runtime"]) / max(j["runtime"], 1), 1.0))
    return {"n":len(completed), "co2_g":co2, "energy_kwh":e, "green_kwh":green,
            "slowdowns":np.array(s) if s else np.array([1.0]), "completed":completed}


# ════════════════════════════════════════════════════════════════════
# Comprehensive QoS metrics (incl. ETTR per Kokolis et al. HPCA 2025)
# ════════════════════════════════════════════════════════════════════

def compute_qos_metrics(slowdowns, completed_jobs):
    """Return p50, p95, p99 slowdown; Jain's fairness; ETTR."""
    s = np.asarray(slowdowns)
    n = len(s)
    if n == 0:
        return dict(p50=1, p95=1, p99=1, mean=1, jain=1, ettr=1)

    jain = float(np.sum(s)**2 / (n * np.sum(s**2)))

    # ETTR (Effective Training Time Ratio): runtime / (runtime + queue_delay)
    # Per Kokolis et al. 2025: useful time / total wall-clock time
    if completed_jobs:
        total_wall = total_useful = 0.0
        for j in completed_jobs:
            if j.get("start") is not None and j.get("end") is not None:
                wait = j["start"] - j["submit"]
                rt = j["runtime"]
                total_wall += (wait + rt); total_useful += rt
        ettr = total_useful / max(total_wall, 1e-9)
    else:
        ettr = 1.0

    return {"p50": float(np.percentile(s, 50)), "p95": float(np.percentile(s, 95)),
            "p99": float(np.percentile(s, 99)), "mean": float(np.mean(s)),
            "max": float(np.max(s)), "jain": jain, "ettr": float(ettr)}


# ════════════════════════════════════════════════════════════════════
# Workload preparation
# ════════════════════════════════════════════════════════════════════

def annotate_flexibility(df, seed=42):
    """Assign d_max_hours by job characteristics."""
    rng = np.random.default_rng(seed)
    n = len(df)
    d_max = np.zeros(n)
    for i in range(n):
        rt = df["run_time"].iloc[i]
        nodes = df["num_nodes_alloc"].iloc[i]
        gpus = df["num_gpus_alloc"].iloc[i] if "num_gpus_alloc" in df.columns else 0
        wt = df.get("workload_type", pd.Series(["unknown"]*n)).iloc[i] \
             if "workload_type" in df.columns else "unknown"
        if wt == "eval":            d_max[i] = rng.uniform(0, 1)
        elif wt == "finetune":      d_max[i] = rng.uniform(2, 8)
        elif wt == "pretrain":      d_max[i] = rng.uniform(6, 24)
        elif rt < 600 and nodes <= 2: d_max[i] = rng.uniform(0, 1)
        elif rt < 3600 and nodes <= 4: d_max[i] = rng.uniform(1, 4)
        elif gpus > 0 and rt >= 3600: d_max[i] = rng.uniform(4, 12)
        elif nodes >= 8:               d_max[i] = rng.uniform(6, 24)
        else:                          d_max[i] = rng.uniform(2, 8)
    df = df.copy()
    df["d_max_hours"] = d_max
    return df


def load_workload(name, max_jobs=300, seed=42):
    if name == "M100":
        df = pd.read_parquet(ROOT / "data" / "m100" / "m100_real_jobs.parquet")
        ts = pd.to_datetime(df["submit_time"])
        df["submit_time_epoch"] = (ts - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()
    elif name == "Philly":
        df = pd.read_parquet(ROOT / "data" / "traces" / "philly_like.parquet")
    elif name == "Acme":
        df = pd.read_parquet(ROOT / "data" / "traces" / "acme_like.parquet")
    else:
        raise ValueError(name)
    df["num_nodes_alloc"] = df["num_nodes_alloc"].astype(int)
    # Cap individual job runtime at 24h to keep simulation tractable;
    # this only affects Acme pretrain jobs (long LLM runs are checkpointed)
    df["run_time"] = df["run_time"].clip(upper=24*3600).astype(int)
    if "num_gpus_alloc" not in df.columns:
        df["num_gpus_alloc"] = 0
    df = annotate_flexibility(df, seed=seed)
    df = df.sort_values("submit_time_epoch").head(max_jobs).reset_index(drop=True)
    return df


# ════════════════════════════════════════════════════════════════════
# Main experiment loop
# ════════════════════════════════════════════════════════════════════

def run_experiment(workload_name, country, scheduler_name, max_jobs=300, seed=42):
    """Run one (workload, country, scheduler) cell."""
    df = load_workload(workload_name, max_jobs=max_jobs, seed=seed)
    ci = build_ci_2025(country, "summer", "medium", n_days=14)
    offset = ci.index[0].timestamp() - df["submit_time_epoch"].min() + 3600
    df = df.copy()
    df["submit_time_epoch"] = df["submit_time_epoch"] + offset

    # Always run FCFS baseline first (with consistent timestep accounting)
    base_r = replay_simple_fcfs(df, ci, seed=seed)
    base_co2_g = base_r["co2_g"]

    if scheduler_name == "FCFS":
        r = replay_simple_fcfs(df, ci, seed=seed)
        slow = r["slowdowns"]; co2_g = r["co2_g"]
        energy = r["energy_kwh"]; green = r["green_kwh"]
        comp = r["completed"]
    elif scheduler_name == "QoS-bounded":
        r = replay_qos_bounded(df, ci, max_delay_h=24, seed=seed)
        slow = np.array([(j.start_time - j.submit_time + j.run_time) / max(j.run_time, 1)
                          for j in r.jobs if j.start_time]) if r.jobs else np.array([1.0])
        comp = [{"submit":j.submit_time,"start":j.start_time,
                 "end":j.start_time+j.run_time,"runtime":j.run_time}
                for j in r.jobs if j.start_time is not None]
        co2_g = r.total_co2_g; energy = r.total_energy_kwh; green = r.green_energy_kwh
    elif scheduler_name == "CarbonScaler":
        r = replay_carbonscaler(df, ci, adoption_rate=1.0, seed=seed)
        slow = r["slowdowns"]; co2_g = r["co2_g"]
        energy = r["energy_kwh"]; green = r["green_kwh"]
        comp = r["completed"]
    elif scheduler_name == "Threshold":
        r = replay_threshold(df, ci, adoption_rate=1.0, ci_threshold_pct=50, seed=seed)
        slow = r["slowdowns"]; co2_g = r["co2_g"]
        energy = r["energy_kwh"]; green = r["green_kwh"]
        comp = r["completed"]
    elif scheduler_name == "GridPilot-OPT":
        r = replay_proact_opt(df, ci, max_delay_h=24, seed=seed)
        slow = r["slowdowns"]; co2_g = r["co2_g"]
        energy = r["energy_kwh"]; green = r["green_kwh"]
        comp = r["completed"]
    elif scheduler_name == "GridPilot++":
        r = replay_proact_plus(df, ci, max_delay_h=24, seed=seed, ci_pct_high=50, ci_improvement=0.05)
        slow = r["slowdowns"]; co2_g = r["co2_g"]
        energy = r["energy_kwh"]; green = r["green_kwh"]
        comp = r["completed"]
    else:
        raise ValueError(scheduler_name)

    # Baseline CO2 for reduction calculation
    base_co2 = base_co2_g

    qos = compute_qos_metrics(slow, comp)
    cfe = green / max(energy, 1e-9)
    co2_red = (1 - co2_g / max(base_co2, 1)) * 100

    return {
        "workload": workload_name, "country": country, "scheduler": scheduler_name,
        "n_jobs": qos.get("p50", 0) and len(slow) or 0,
        "co2_kg": co2_g / 1000, "baseline_co2_kg": base_co2 / 1000,
        "co2_red_pct": co2_red,
        "energy_kwh": energy, "cfe": cfe * 100,
        "p50_slow": qos["p50"], "p95_slow": qos["p95"], "p99_slow": qos["p99"],
        "mean_slow": qos["mean"], "max_slow": qos["max"],
        "jain": qos["jain"], "ettr": qos["ettr"],
    }


def main():
    workloads = ["M100", "Philly", "Acme"]
    countries = ["CH", "IT", "DE"]
    schedulers = ["FCFS", "QoS-bounded", "GridPilot++", "GridPilot-OPT", "CarbonScaler", "Threshold"]
    # Acme jobs are far heavier (median 24h runtime); cap accordingly
    max_jobs_per_workload = {"M100": 200, "Philly": 200, "Acme": 80}

    rows = []
    total = len(workloads) * len(countries) * len(schedulers)
    n = 0
    print(f"Running {total} experiments...")
    t0 = time.time()
    for wl in workloads:
        for c in countries:
            for s in schedulers:
                n += 1
                t1 = time.time()
                try:
                    r = run_experiment(wl, c, s, max_jobs=max_jobs_per_workload[wl], seed=42)
                    rows.append(r)
                    elapsed = time.time() - t1
                    print(f"  [{n}/{total}] {wl:6s} {c} {s:13s}: "
                          f"CO₂ {r['co2_red_pct']:+5.1f}%, p95={r['p95_slow']:5.1f}×, "
                          f"ETTR={r['ettr']:.2f} ({elapsed:.1f}s)")
                except Exception as e:
                    print(f"  [{n}/{total}] {wl:6s} {c} {s}: FAILED {e}")
                gc.collect()

    df = pd.DataFrame(rows)
    out = ROOT / "results" / "icpp_full_matrix.csv"
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nSaved: {out}")
    print(f"Total time: {(time.time()-t0)/60:.1f} min")
    return df


if __name__ == "__main__":
    main()
