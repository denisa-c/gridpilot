#!/usr/bin/env python3
"""
scripts/m100/replay_policy_matrix.py
====================================
Sweep (baseline policy × f-SLA anti-gaming mechanism × seed) and emit
the headline policy-matrix CSV that backs PECS Paper B §7 Finding 4.

Baselines (orthogonal to the f-SLA layer):
    FCFS, EASY-FCFS, SAF, RLBackfilling (rule-based shim),
    GridPilot-PUE.

Mechanisms (the contribution; FSLA_GAMIFICATION_POC_PLAN.md §2):
    none, M0_PostedPrice, M1_BlindTrustQueue, M2_DAAuction,
    M3_AIBaselineAudit.

Acceptance (FSLA_GAMIFICATION_POC_PLAN.md §12):
    * default sweep (5 policies × 5 mechanisms × 8 seeds = 200 cells)
      completes in ≤ 45 min on a 16-core workstation;
    * ``policy_matrix.csv`` carries one row per cell with the four
      headline metrics (CFE %, Δ_IT pp, Jain, p95 latency) plus the
      mechanism's audit report;
    * ``HYPOTHESIS_OUTCOMES.json`` records H1–H5 pass/fail flags.

Example
-------
::

    PYTHONPATH=src python scripts/m100/replay_policy_matrix.py \\
        --jobs    data/traces/m100_real_jobs.parquet \\
        --ci      configs/grids/DE.yaml \\
        --pue     raps/config/marconi100.yaml \\
        --seeds   8 \\
        --output-dir data/m100/policy_matrix/
"""
from __future__ import annotations

import argparse
import json
import platform
import socket
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ─── Make sibling src/ importable ────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from scheduler.scheduler_pue_aware import (  # noqa: E402
    replay_proact_opt_pue, replay_fcfs_pue,
)
from scheduler.fsla import sample_prior, assign_tiers, T_RIGID  # noqa: E402
from scheduler.fsla_mechanisms import (  # noqa: E402
    build_mechanism, MECHANISM_REGISTRY, AntiGamingMechanism,
)
from scheduler.ai_baseline import AIBaselinePredictor  # noqa: E402
from scheduler.swf import (  # noqa: E402
    swf_utilitarian, swf_nash, swf_alpha_fair, jain_fairness,
    per_user_utility,
)
from cooling.cooling_pue_model import calibrate_to_design_pue  # noqa: E402

# Re-use loader helpers from inject_fsla_prior so the policy matrix
# accepts the exact same CLI inputs as the Monte-Carlo driver.
from inject_fsla_prior import (  # noqa: E402
    load_jobs, load_ci, load_t_amb, load_pue_params, align_jobs_to_ci,
)


# ─────────────────────────────────────────────────────────────────────
# Baseline policies (orthogonal to the f-SLA layer)
# ─────────────────────────────────────────────────────────────────────
def _replay_fcfs(jobs_df, ci_df, t_amb, **kw):
    """Pure FCFS without PUE awareness — pinned via ``replay_fcfs_pue``."""
    return replay_fcfs_pue(jobs_df, ci_df, t_amb, **kw)


def _replay_easy(jobs_df, ci_df, t_amb, **kw):
    """EASY-FCFS: FCFS + EASY backfilling. We re-use the PUE-aware
    scheduler with ``pue_weight=0`` (CI-only signal) and a 1-hour
    deferral window so that backfilling is permitted but no carbon-
    aware deferral fires.
    """
    return replay_proact_opt_pue(
        jobs_df, ci_df, t_amb,
        max_delay_h=1, pue_weight=0.0,
        enable_backfilling=True, **kw,
    )


def _replay_saf(jobs_df, ci_df, t_amb, **kw):
    """Smallest-Area-First (Carastan-Santos 2019).  We re-rank the
    queue by ``runtime × num_nodes_alloc`` before passing to the
    PUE-aware scheduler with the same ``pue_weight=0`` setting as EASY.
    """
    sorted_df = jobs_df.assign(
        _area=jobs_df["run_time"] * jobs_df["num_nodes_alloc"]
    ).sort_values(["_area", "submit_time_epoch"]).drop(columns=["_area"])
    return replay_proact_opt_pue(
        sorted_df, ci_df, t_amb,
        max_delay_h=1, pue_weight=0.0,
        enable_backfilling=True, **kw,
    )


def _replay_rl_backfill(jobs_df, ci_df, t_amb, **kw):
    """RLBackfilling shim (Kolker-Hicks 2023).  The published policy
    selects the *shortest job whose nodes fit and whose wait < tier
    window*; we encode the rule via SAF-ordering plus a deferral
    window equal to the global p75 of run-times.
    """
    p75_runtime = float(np.percentile(jobs_df["run_time"], 75))
    max_delay_h = max(1, int(p75_runtime / 3600))
    sorted_df = jobs_df.assign(
        _area=jobs_df["run_time"] * jobs_df["num_nodes_alloc"]
    ).sort_values(["_area", "submit_time_epoch"]).drop(columns=["_area"])
    return replay_proact_opt_pue(
        sorted_df, ci_df, t_amb,
        max_delay_h=max_delay_h, pue_weight=0.0,
        enable_backfilling=True, **kw,
    )


def _replay_gridpilot_pue(jobs_df, ci_df, t_amb, **kw):
    """GridPilot-PUE (Algorithm 2 of PECS Paper B)."""
    return replay_proact_opt_pue(
        jobs_df, ci_df, t_amb,
        max_delay_h=int(max(1, jobs_df.get("d_max_hours", pd.Series([0])).max())),
        pue_weight=0.5,
        enable_backfilling=True, **kw,
    )


POLICY_REGISTRY = {
    "FCFS":          _replay_fcfs,
    "EASY":          _replay_easy,
    "SAF":           _replay_saf,
    "RLBackfilling": _replay_rl_backfill,
    "GridPilot-PUE": _replay_gridpilot_pue,
}


# ─────────────────────────────────────────────────────────────────────
# Per-cell driver
# ─────────────────────────────────────────────────────────────────────
def _attach_user_column(jobs_df: pd.DataFrame, n_users: int = 50,
                          rng: Optional[np.random.Generator] = None) -> pd.DataFrame:
    """If the trace has no ``user`` column, synthesise one with a
    Zipf-ian distribution (top user owns ≈ 1/3 of jobs, tail follows
    s = 1.2).  This is enough for the per-user fairness and SWF
    aggregations downstream.
    """
    if "user" in jobs_df.columns:
        return jobs_df
    rng = rng or np.random.default_rng(20260517)
    user_idx = rng.zipf(1.2, size=len(jobs_df))
    user_idx = np.clip(user_idx, 1, n_users)
    return jobs_df.assign(user=[f"u{idx:03d}" for idx in user_idx])


def _cfe_pct(result: dict) -> float:
    """Carbon-Free-Energy share = ``green_kwh / energy_kwh``.

    Bounds: [0, 1].  The replay_*_pue scoring methods already attach
    ``green_kwh`` (∫ energy × (1 − CI_norm(t))).
    """
    e = float(result.get("energy_kwh", 0.0))
    g = float(result.get("green_kwh", 0.0))
    if e <= 0:
        return 0.0
    return float(np.clip(100.0 * g / e, 0.0, 100.0))


def _make_user_utility_rows(
    completed_jobs: list[dict],
    jobs_with_tiers: pd.DataFrame,
) -> list[dict]:
    """Stitch the scheduler's completed-job dicts back to the tier
    metadata so ``per_user_utility`` and ``jain_fairness`` can be
    computed.  The dicts gain ``user``, ``tier``, ``slowdown``,
    ``service_credit_h``, ``checkpoint_bonus``, ``slowdown_max``.
    """
    # The scheduler does not carry the user/tier fields through; we
    # re-attach them by position (jobs_with_tiers and completed_jobs
    # share the same submission ordering modulo dispatch).  This is
    # an approximation appropriate for the aggregate-level metrics
    # we compute here.
    n = min(len(completed_jobs), len(jobs_with_tiers))
    out = []
    for i in range(n):
        c = dict(completed_jobs[i])
        meta = jobs_with_tiers.iloc[i]
        c["user"] = str(meta.get("user", "anonymous"))
        c["tier"] = int(meta.get("tier", T_RIGID))
        c["service_credit_h"] = float(meta.get("service_credit_h", 0.0))
        c["checkpoint_bonus"] = float(meta.get("checkpoint_bonus", 0.0))
        c["slowdown_max"] = float(meta.get("slowdown_max", 1.0))
        wait = (c.get("start", 0) or 0) - (c.get("submit", 0) or 0)
        runtime = max(c.get("runtime", 1), 1)
        c["slowdown"] = float(max(1.0, (wait + runtime) / runtime))
        out.append(c)
    return out


def run_one_cell(
    policy: str,
    mechanism: str,
    seed: int,
    jobs_df: pd.DataFrame,
    ci_df: pd.DataFrame,
    t_amb: pd.Series,
    cooling_params,
    ai_predictor: AIBaselinePredictor,
    scheduler_kwargs: dict,
) -> dict:
    """Run one (policy, mechanism, seed) cell of the matrix."""
    rng = np.random.default_rng(seed)

    # ── 1. Tier assignment under the chosen mechanism (or all-rigid)
    if mechanism == "none":
        jobs_with_tiers = jobs_df.copy()
        jobs_with_tiers["tier"] = T_RIGID
        jobs_with_tiers["d_max_hours"] = 0
        jobs_with_tiers["slowdown_max"] = 1.0
        jobs_with_tiers["service_credit_h"] = 0.0
        jobs_with_tiers["checkpoint_bonus"] = 0.0
        audit_report = None
    else:
        mech: AntiGamingMechanism = build_mechanism(mechanism)
        jobs_with_tiers = mech.assign_tiers(
            jobs_df, rng=rng, ai_predictor=ai_predictor,
        )
        audit_report = None  # filled in after the replay

    # ── 2. Replay under the chosen baseline policy
    policy_fn = POLICY_REGISTRY[policy]
    result = policy_fn(
        jobs_with_tiers, ci_df, t_amb,
        cooling_params=cooling_params, seed=seed, **scheduler_kwargs,
    )

    # ── 3. Audit (only for non-trivial mechanisms)
    completed = _make_user_utility_rows(result.get("completed", []), jobs_with_tiers)
    if mechanism != "none":
        completed, audit_report = mech.audit(jobs_with_tiers, completed)

    # ── 4. Headline metrics
    utilities = per_user_utility(completed)
    if utilities:
        u_vec = list(utilities.values())
        # Wait-time vector for the Jain index: per-user mean wait,
        # inverted so "throughput-like" semantics apply.
        wait_by_user: dict[str, list[float]] = {}
        for j in completed:
            wait_by_user.setdefault(j["user"], []).append(
                max(0.0, (j.get("start", 0) - j.get("submit", 0)))
            )
        mean_inv_wait = [1.0 / max(np.mean(v), 1.0) for v in wait_by_user.values()]
    else:
        u_vec = [0.0]
        mean_inv_wait = [1.0]

    slowdowns = result.get("slowdowns", np.array([1.0]))
    row = {
        "policy": policy,
        "mechanism": mechanism,
        "seed": seed,
        "n_jobs": int(result.get("n", 0)),
        "energy_kwh": float(result.get("energy_kwh", 0.0)),
        "co2_g_it": float(result.get("co2_g", 0.0)),
        "co2_g_facility": float(result.get("facility_co2_g", 0.0)),
        "cfe_pct": _cfe_pct(result),
        "p50_slowdown": float(np.percentile(slowdowns, 50)),
        "p95_slowdown": float(np.percentile(slowdowns, 95)),
        "p99_slowdown": float(np.percentile(slowdowns, 99)),
        "avg_pue": float(result.get("avg_pue", 1.2)),
        "swf_utilitarian": swf_utilitarian(u_vec),
        "swf_nash": swf_nash(u_vec),
        "swf_alpha_0.5": swf_alpha_fair(u_vec, 0.5),
        "swf_alpha_1.0": swf_alpha_fair(u_vec, 1.0),
        "swf_alpha_2.0": swf_alpha_fair(u_vec, 2.0),
        "jain_fairness": jain_fairness(mean_inv_wait),
        "n_users": len(utilities),
    }
    if audit_report is not None:
        row["audit_n_over_declared"] = audit_report.n_over_declared
        row["audit_n_under_declared"] = audit_report.n_under_declared
        row["audit_total_penalty"] = audit_report.total_penalty
        row["audit_nom_ic_violation_rate"] = audit_report.nom_ic_violation_rate
    else:
        row["audit_n_over_declared"] = 0
        row["audit_n_under_declared"] = 0
        row["audit_total_penalty"] = 0.0
        row["audit_nom_ic_violation_rate"] = 0.0
    return row


# ─────────────────────────────────────────────────────────────────────
# CLI driver
# ─────────────────────────────────────────────────────────────────────
def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="replay_policy_matrix",
        description="Sweep (policy × mechanism × seed) on the M100 trace "
                    "(PECS 2026 Finding 4 driver).",
    )
    p.add_argument("--jobs", type=Path, required=True)
    p.add_argument("--ci",   type=Path, required=True)
    p.add_argument("--t-amb", type=Path, default=None)
    p.add_argument("--pue",   type=Path, default=None)
    p.add_argument("--policies", type=str,
                   default="FCFS,EASY,SAF,RLBackfilling,GridPilot-PUE")
    p.add_argument("--mechanisms", type=str,
                   default="none,M0,M1,M2,M3")
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--seed-base", type=int, default=20260517)
    p.add_argument("--output-dir", type=Path,
                   default=Path("data/m100/policy_matrix"))
    p.add_argument("--workers", type=int, default=1,
                   help="Parallel workers (1 = serial, useful for debugging).")
    p.add_argument("--time-step", type=int, default=3600)
    p.add_argument("--total-nodes", type=int, default=980)
    p.add_argument("--node-power-kw", type=float, default=1.5)
    p.add_argument("--force", action="store_true")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args(argv)


def _build_ai_predictor(jobs_df: pd.DataFrame, rng: np.random.Generator) -> AIBaselinePredictor:
    """Bootstrap an AI predictor from a Dirichlet-prior tier draw.

    In a deployed setting the predictor would be fit on the real
    historical (AI, declared, realised) triples described in vision
    §4.1.  For the PoC we feed it a one-shot synthetic prior so the
    Bayesian back-off path is exercised on realistic distributions.
    """
    pi = sample_prior(rng=rng)
    historical, _ = assign_tiers(jobs_df, pi, rng=rng, length_conditioned=True)
    return AIBaselinePredictor(min_history=5).fit(historical)


def _evaluate_hypotheses(headline: pd.DataFrame) -> dict[str, dict]:
    """Score H1–H5 (FSLA_GAMIFICATION_POC_PLAN.md §8) on the matrix."""
    out: dict[str, dict] = {}

    # ── H1: declared-tier lift survives anti-gaming
    base = headline.query("policy == 'GridPilot-PUE' and mechanism == 'none'")
    base_dit = base["co2_g_it"].mean() if len(base) else float("nan")
    h1_results = {}
    for m in ("M0", "M1", "M2", "M3"):
        cell = headline.query(f"policy == 'GridPilot-PUE' and mechanism == '{m}'")
        if not len(cell):
            continue
        lift = (base_dit - cell["co2_g_it"].mean()) / max(base_dit, 1) * 100.0
        h1_results[m] = float(lift)
    out["H1_declared_tier_lift"] = {
        "lifts_pct": h1_results,
        "passed": sum(v > 2.0 for v in h1_results.values()) >= 3,
    }

    # ── H2: NOM-IC of M3 holds
    m3_cells = headline.query("mechanism == 'M3'")
    m0_cells = headline.query("mechanism == 'M0'")
    h2 = {
        "m3_nom_ic_violation_rate": float(m3_cells["audit_nom_ic_violation_rate"].mean())
                                     if len(m3_cells) else float("nan"),
        "m0_nom_ic_violation_rate": float(m0_cells["audit_nom_ic_violation_rate"].mean())
                                     if len(m0_cells) else float("nan"),
        "passed": (
            len(m3_cells)
            and float(m3_cells["audit_nom_ic_violation_rate"].mean()) < 0.01
        ),
    }
    out["H2_nom_ic"] = h2

    # ── H3: no fairness regression
    baseline_jain = headline.query("policy == 'FCFS' and mechanism == 'none'")["jain_fairness"].mean()
    h3 = {"baseline_jain": float(baseline_jain), "min_ratio": 1.0, "passed": True}
    for _, row in headline.iterrows():
        ratio = row["jain_fairness"] / max(baseline_jain, 1e-9)
        if ratio < h3["min_ratio"]:
            h3["min_ratio"] = float(ratio)
        if ratio < 0.95:
            h3["passed"] = False
    out["H3_fairness"] = h3

    # ── H4: SWF dominance under DAA (using α=2 as leximin proxy)
    m2 = headline.query("policy == 'GridPilot-PUE' and mechanism == 'M2'")
    m0 = headline.query("policy == 'GridPilot-PUE' and mechanism == 'M0'")
    h4 = {
        "swf_m2_alpha2": float(m2["swf_alpha_2.0"].mean()) if len(m2) else float("nan"),
        "swf_m0_alpha2": float(m0["swf_alpha_2.0"].mean()) if len(m0) else float("nan"),
        "passed": (len(m2) and len(m0)
                    and float(m2["swf_alpha_2.0"].mean())
                        >= float(m0["swf_alpha_2.0"].mean())),
    }
    out["H4_swf_dominance"] = h4

    # ── H5: latency-tier monotonicity
    # We cannot test per-tier latency from the policy-matrix CSV alone;
    # the figure script ``fig_latency_per_tier.py`` reads the per-cell
    # JSONs to do so.  Here we record a placeholder; the figure script
    # writes a corresponding entry on its own.
    out["H5_latency_monotone"] = {"deferred_to_figure_script": True}

    return out


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    t0 = time.time()
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    headline_csv = out_dir / "policy_matrix.csv"
    if headline_csv.exists() and not args.force:
        print(f"ERROR: {headline_csv} already exists. Use --force.", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"[matrix] loading inputs", flush=True)
    jobs_df = load_jobs(args.jobs)
    ci_df = load_ci(args.ci)
    jobs_df = align_jobs_to_ci(jobs_df, ci_df)
    jobs_df = _attach_user_column(jobs_df)
    t_amb = load_t_amb(args.t_amb, ci_df.index)
    cooling_params = load_pue_params(args.pue)

    ai_rng = np.random.default_rng(args.seed_base)
    ai_predictor = _build_ai_predictor(jobs_df, ai_rng)

    scheduler_kwargs = dict(
        total_nodes=args.total_nodes,
        node_power_kw=args.node_power_kw,
        time_step=args.time_step,
    )

    policies   = [p.strip() for p in args.policies.split(",") if p.strip()]
    mechanisms = [m.strip() for m in args.mechanisms.split(",") if m.strip()]
    seeds      = [args.seed_base + k for k in range(args.seeds)]
    cells      = [(p, m, s) for p in policies for m in mechanisms for s in seeds]

    if not args.quiet:
        print(f"[matrix] {len(policies)} policies × {len(mechanisms)} mechanisms "
              f"× {len(seeds)} seeds = {len(cells)} cells; "
              f"workers={args.workers}", flush=True)

    rows: list[dict] = []
    if args.workers <= 1:
        for k, (p, m, s) in enumerate(cells):
            if not args.quiet and k % max(1, len(cells) // 20) == 0:
                print(f"[matrix]   {k+1}/{len(cells)}  {p:<14} {m:<5} seed={s}",
                      flush=True)
            rows.append(run_one_cell(
                p, m, s, jobs_df, ci_df, t_amb, cooling_params,
                ai_predictor, scheduler_kwargs,
            ))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {
                ex.submit(run_one_cell, p, m, s, jobs_df, ci_df, t_amb,
                           cooling_params, ai_predictor, scheduler_kwargs): (p, m, s)
                for (p, m, s) in cells
            }
            for k, fut in enumerate(as_completed(futs)):
                p, m, s = futs[fut]
                if not args.quiet and k % max(1, len(cells) // 20) == 0:
                    print(f"[matrix]   {k+1}/{len(cells)}  {p:<14} {m:<5} seed={s}",
                          flush=True)
                rows.append(fut.result())

    headline = pd.DataFrame(rows)
    headline.to_csv(headline_csv, index=False, float_format="%.4f")
    if not args.quiet:
        print(f"[matrix] wrote {headline_csv}", flush=True)

    h_outcomes = _evaluate_hypotheses(headline)
    (out_dir / "HYPOTHESIS_OUTCOMES.json").write_text(json.dumps(h_outcomes, indent=2))

    # RUN_MANIFEST.json: marker of a clean completion.  The bash entry
    # point (scripts/run_all_experiments.sh) uses (CSV + manifest) as
    # the "step done" check; without this file a re-invocation always
    # redoes the ~26-minute replay even when the CSV is already present.
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parents[2]),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        git_sha = "unknown"
    manifest = {
        "git_sha": git_sha,
        "command_line": " ".join(sys.argv),
        "args": {k: str(v) for k, v in vars(args).items()},
        "python_version": sys.version,
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "wall_time_s": round(time.time() - t0, 1),
        "n_cells": len(cells),
    }
    (out_dir / "RUN_MANIFEST.json").write_text(json.dumps(manifest, indent=2))

    if not args.quiet:
        print(f"[matrix] hypothesis outcomes: " + ", ".join(
            f"{k}={'PASS' if v.get('passed') else 'INVESTIGATE'}"
            for k, v in h_outcomes.items() if "passed" in v
        ), flush=True)
        print(f"[matrix] total wall time {time.time()-t0:.1f}s", flush=True)
        print(f"[matrix] wrote {out_dir / 'RUN_MANIFEST.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
