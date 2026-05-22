# Realism axis for the v2 flexibility experiments

This doc enumerates the realism improvements implemented in v2 and
the additional improvements still pending.  It exists so the f-SLA paper
paper's Discussion section can cite a concrete list of *"what we did,
what we know is missing, why each missing item matters"* — and so a
reviewer can audit the claim.

## Improvements implemented (v2 headline)

| Improvement | Where | Defensibility anchor |
|-------------|-------|---------------------|
| Workload classification from observable features (runtime, nodes), not synthetic Dirichlet | `workload_taxonomy.classify_jobs` | Antici 2023 (PM100); Hu 2021 (SenseTime); Hanafy 2023 (CarbonScaler); Wiesner 2021 (WaitAWhile) |
| Per-class **Dirichlet** over plausible tier choices (users in same class don't all declare the same flexibility) | `workload_taxonomy.assign_tiers_dirichlet_per_class` | No published HPC user-declaration distribution exists; we use a model assumption documented in the function docstring |
| **Week-long** replay windows per representative date (was: day-long) | `04c --days-per-window 7` | A 7-day window contains 7 diurnal cycles + 1 weekly cycle, giving the dispatcher enough CI variation to exercise T2/T3/T4 deferral windows.  A single day collapsed the design space (the "hyperparameter null" finding from v1) |
| Real ENTSO-E hourly CI (per country, when fetched) | `04c → load_seasonal_ci` | Real intraday + intra-week swings; the synth fallback uses the per-country YAML envelope (Wiesner 2021 cited values) |
| Geo-shiftable tier T5 maps to T3 deferral semantics | `CLASS_TO_TIER["geo_shiftable"] = T_WEEK` | v1 dispatcher has no spatial routing implementation; honest fallback documented as a limitation rather than a silent broken behaviour |
| Classifier ordering fix: batch_parallel checked before elastic_ai | `workload_taxonomy._classify_one` v2 | v1 had elastic_ai swallowing all 30 min – 24 h jobs, leaving batch_parallel at 0 % of GPU·h on M100 (vs ~15 % in the paper's reference taxonomy) |
| elastic_ai narrowed to multi-node (≥ 2) AND ≤ 6 h | `ELASTIC_NODES_MIN = 2`, `ELASTIC_RUNTIME_MAX_S = 6h` | Hu 2021 SenseTime §3.2: 92 % of training jobs finish within 4 h on 2–32 GPUs; narrower band matches the paper's 43 % reference |
| Aggregate-mix audit per run | `summarise_taxonomy_mix` + `TAXONOMY_MIX.csv` written before any cell runs | Reviewer can sanity-check classification proportions against paper Fig. 1 within ±5 pp |

## Improvements still open (Discussion-section candidates)

| Improvement | Why it matters | Cost | Where it would live |
|-------------|----------------|------|---------------------|
| **Real user-declaration study** | The per-class Dirichlet means in `CLASS_TO_TIER_DIRICHLET` are *modeled assumptions*.  A 20-user pilot at a real HPC site would give measured distributions and turn the assumption into evidence. | High (IRB + 3-month deployment) | Follow-on paper |
| **Job-level metadata classification** | Currently classify by `(runtime, nodes)` only. Real flexibility depends on application type, user account / quota tier, time-of-submit (jobs submitted before weekend more flexible than 5 min before deadline), past user behaviour | Medium (need M100 partition + account columns surfaced) | v2.1 with extended M100 ETL |
| **Bursty submission patterns** | v2 spreads jobs uniformly across the window. Real HPC traces show paper-deadline rushes, post-deployment surges, weekend lulls.  Bursty submissions interact with the dispatcher's queue depth → different lift | Low (just use the trace's real submit times instead of re-anchoring) | v2.1 once `build_extended_trace.py`'s timespan bug is fixed |
| **Spatial routing (T5 native)** | T5 currently falls back to T3 because the dispatcher has no spatial logic.  Wiesner 2021 reports ~17 % CO₂ reduction from spatial shifting on top of temporal.  This is the **largest remaining lift on the table** | High (full DAG + network model) | C2 follow-on paper |
| **Bayes-Nash IC proof for M3** | The contract's NOM-IC property under M3 is verified empirically over Monte-Carlo seeds; a formal proof would close the mechanism-design loop | High (mechanism-design theory) | Theory follow-on |
| **Multi-resource constraints** | Beyond `(nodes, runtime)`, real flexibility depends on memory, network, storage.  A memory-heavy job might be defer-able along the runtime axis but not movable across grids (data locality) | High (full resource model) | v2.2 |
| **Operator-side learning** | M3 currently uses a static AI baseline trained on the user's first 30 jobs.  A real deployment would continuously retrain.  This affects the contract's anti-gaming robustness over time | Medium (online learning hook in `AIBaselinePredictor`) | v2.1 |
| **Cross-tenant fairness** | The current sweep treats all jobs as belonging to a single user pool.  In a multi-tenant facility, tier declarations interact with per-account quotas and shares (SLURM `FairTree`).  The contract should not penalise users who can't declare flexibility | Medium (multi-tenant scheduler integration) | C2 follow-on |
| **Real PUE telemetry** | v2 uses constant PUE = 1.20.  The M100 telemetry archive has hourly PUE measurements that we could plug in.  Per-job PUE-variation contributes < 1 pp to CFE on annualised totals, but ≥ 3 pp in extreme winter/summer | Low (10 lines once the M100 PUE parquet is in `data/m100_public/`) | v2.1 |
| **Workload-trace diversity** | v2 still uses the M100 trace only.  Adding Philly (Microsoft AI), MIT SuperCloud, Frontier traces would test cross-trace generality | High (trace acquisition + ETL) | Follow-on |

## How to run the v2 paper figures with this set of realism levers

```bash
# Required: ENTSO-E API key for the real hourly CI fetch (recommended).
export ENTSOE_API_KEY=<token from https://transparency.entsoe.eu>
PYTHONPATH=gridpilot/src python3 gridpilot/scripts/m100/fetch_real_ci_series.py \
    --start 2025-01-01 --end 2026-01-01 \
    --grids SE,CH,FR,IT,DE,PL \
    --out-dir gridpilot/data/ci/entsoe/

# Phase 4e: 4 weeks × 6 countries × 4 schedulers × 4 seeds = 384 cells.
# Per-cell wall time at 1500 jobs/day × 7 days = ~10500 jobs:
# ~30–60 s/cell sequential; ~10–15 min total at 18 workers.
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/04c_run_taxonomy_sweep.py \
        --days-per-window 7 \
        --realistic-flexibility \
        --workers 18

# Phase 5e: render all paper-facing figures from the taxonomy CSV.
PYTHONPATH=gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/09_render_paper_figures.py \
        --taxonomy-csv gridpilot/experiments_v2/data/taxonomy_sweep/taxonomy_sweep.csv \
        --taxonomy-mix gridpilot/experiments_v2/data/taxonomy_sweep/TAXONOMY_MIX.csv \
        --out-dir      gridpilot/experiments_v2/figs/paper
```

The output `figs/paper/` directory contains four PDFs the paper
imports directly:

| PDF | What the paper uses it for |
|-----|---------------------------|
| `fig_paper_headline.pdf`        | Headline result: per-country Δ CFE with seasonal small-multiples and 8-seed error bars |
| `fig_paper_class_breakdown.pdf` | (a) classification audit donut, (b) per-class CFE achieved |
| `fig_paper_seasonal.pdf`        | Seasonal stability per country (line plot with error bars) |
| `fig_paper_country_vs_ci.pdf`   | "Shape of result" — Δ CFE vs grid CI with a measured-only regression line; no projection |
