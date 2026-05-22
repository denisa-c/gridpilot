# RELEASE_CONTENTS — what ships in the public GridPilot kit

**Release scope:** the public GitHub release is the `gridpilot/`
reproducibility kit only.  LaTeX sources for the companion papers
(f-SLA paper, GridPilot paper) are **not** published on GitHub — they ship
through the respective conference proceedings (Springer LNCS) and/or
arXiv.  Both papers remain in the working repository during
development but are excluded from the release tarball.

This document lists exactly which scripts and data live in the public
release, why each one is in the kit, and what was deliberately removed.
Reviewers and downstream users can use it to verify the kit is minimal,
auditable, and free of the v1-era bugs catalogued in
`experiments_v2/AUDIT_FINDINGS.md` (F1–F5).

The release is organised in two tiers:

- **Tier 1** — scripts the two papers (f-SLA paper, GridPilot paper) reproduce
  directly. Removing any one of these breaks reproduction of a figure
  or a table.
- **Tier 2** — general-purpose utilities and follow-on tooling that
  work against the same pipeline and dataset but are not directly
  cited in the published manuscripts.

Everything else has been ARCHIVED (moved to `_dev_archive/<date>/` for
internal traceability) or DELETED (irrecoverable, no scientific value
preserved by keeping). The driver for the cleanup is
`papers/pecs2026/cleanup_dev_archive.sh`; the rationale is in
`papers/pecs2026/PRE_RELEASE_CLEANUP.md` (§§1–8).

---

## Tier 1 — paper headlines

These are exactly what `pdflatex` consumes to regenerate the published
PDFs from the released data.

### Carbon-aware contract pipeline (f-SLA paper + GridPilot E8 multi-country sweep)

```
gridpilot/experiments_v2/
├── src/
│   ├── accounting.py                          # shared energy/CO2/CFE accounting (F3 split enforced)
│   ├── workload_taxonomy.py                   # 6-class workload classifier
│   ├── mechanism_design.py                    # M0–M3 anti-gaming mechanisms
│   ├── figure_style.py                        # paper-wide matplotlib style
│   └── schedulers/
│       ├── fsla_carbon_aware.py               # v2 dispatcher (F1/F2/F3 fixed)
│       ├── accounting.py                      # ScheduleResult, from_dispatch_log
│       └── (fcfs.py, easy_fcfs.py, saf.py)    # canonical published baselines
├── scripts/
│   ├── 00_unit_audit.py                       # closed-form sanity tests for accounting.py
│   ├── 01_single_cell_smoketest.py            # first-pass validation
│   ├── 04c_run_taxonomy_sweep.py              # f-SLA paper Table 2 + GridPilot E8 headline driver
│   ├── 04d_run_mechanism_sweep.py             # f-SLA paper Table 3 M0–M3 evaluation
│   ├── 07_render_seasonal_figure.py           # renders fig_paper_seasonal_2x2_linearC.pdf
│   ├── 09_render_paper_figures.py             # renders fig_paper_headline.pdf
│   ├── 10_extract_paper_macros.py             # produces results.tex consumed by both papers
│   ├── 11_render_mechanism_figure.py          # renders fig_paper_mechanisms.pdf
│   └── test_fsla_scheduler.py                 # unit tests for the v2 dispatcher
├── data/
│   ├── taxonomy_sweep/                        # taxonomy_sweep.csv, TAXONOMY_SUMMARY.csv, TAXONOMY_MIX.csv
│   └── mechanism_sweep/                       # mechanism_sweep.csv, MECHANISM_SUMMARY.csv
└── figs/paper/                                # 5 rendered PDFs + results.tex
```

### Trace + grid data (both papers)

```
gridpilot/data/
├── traces/m100_real_jobs_extended.parquet     # M100 trace with F4-fixed schema
└── ci/entsoe/                                 # 6 hourly CI parquets (SE, CH, FR, IT, DE, PL)

gridpilot/scripts/m100/
├── fetch_real_ci_series.py                    # ENTSO-E A75 + A11 consumption-mix CFE fetcher
└── build_extended_trace.py                    # builds the F4-fixed extended trace from raw sacct
```

### V100 hardware controller (GridPilot paper only)

```
gridpilot/scripts/
├── pue_model/cooling_decomposition.py         # 4-component PUE model (GridPilot §3.3, Eq. 4)
└── v100/
    ├── controller/hierarchical_controller.py  # Tier-1/2/3 controller stack
    ├── safety_island/simulator/island_simulator.py  # TLA+-spec'd safety island
    ├── workloads/workload_definitions.py      # 3 workload archetypes
    ├── experiments/
    │   ├── E2_inner_loop_step_response.py     # PID step response
    │   ├── E3_outer_loop_tracking.py          # AR(4) predictor accuracy
    │   ├── E4_closed_loop_demand_following.py # cascade tracking error
    │   ├── E5_supervisory_pareto.py           # supervisory-tier Pareto (kit-only; not in paper)
    │   ├── E6_multigpu_cpu_coordinated.py     # multi-GPU + CPU coordination (kit-only; not in paper)
    │   └── E7_ffr_activation_latency.py       # headline end-to-end latency (90 trials)
    ├── figure_scripts/fig_safety_island.py    # latency-distribution panel
    ├── calibrate_raps.py                      # PUE calibration to Marconi100 design point
    ├── compare_v100_vs_m100.py                # cross-platform validation
    ├── project_cluster.py                     # 1/10/50 MW scaling projection
    ├── replot_with_real_data.py               # re-renders V100 figures from raw CSVs
    └── tests/
        ├── test_analyse_campaign.py
        ├── test_campaign_cli.py
        └── test_compare_v100_vs_m100.py
```

E5 and E6 are not GridPilot headline experiments, but they ship in the
kit as usability tooling — the supervisory-Pareto experiment and the
multi-GPU+CPU coordination experiment are valid extensions a future
user might re-run on a comparable testbed.

---

## Tier 2 — general-purpose utilities

Scripts that work against the same pipeline and data, but are *not*
referenced by either published manuscript. They earn their place by
being correct (no F1–F5 contamination), self-contained, and
documenting a real follow-on use case.

```
gridpilot/scripts/
├── simulator/
│   ├── validate_country_config.py             # YAML config sanity check for new countries
│   └── hardware/
│       ├── fetch_live_entsoe.py               # live ENTSO-E API client (real-time deployment)
│       └── collect_telemetry.py               # generic GPU telemetry harness
├── projection/
│   └── multiyear_50mw.py                      # multi-year facility-scale projection
├── sensitivity/
│   └── run_plackett_burman.py                 # Plackett–Burman screening on dispatcher hyperparameters
├── workflows/
│   ├── synth_hpo_dag.py                       # synthetic HPO workflow DAG generator
│   ├── synth_train_restart_dag.py             # synthetic train-restart DAG generator
│   └── replay_workflow_sweep.py               # workflow-trace replay against the v2 dispatcher
├── raps_adapter/
│   ├── import_yaml.py                         # reads RAPS marconi100.yaml for PUE anchor
│   ├── m100_calibration_check.py              # documents the RAPS route NOT taken (audit §5)
│   └── frontier_calibration_check.py          # same for Frontier
├── figures/
│   ├── _figstyle.py                           # shared matplotlib style
│   ├── fig_country_pue_aware.py               # GridPilot §5.country PUE-aware figure
│   ├── fig_multiscale_operational_only.py     # GridPilot fig_multiscale_controller subpanel
│   └── fig_workflow_dag_savings.py            # synthetic-workflow savings panel
└── m100/__init__.py                           # module marker (kept for import structure)
```

---

## Deliberately excluded — and why

Everything below was either bug-contaminated (F1–F5 in the audit) or
superseded by Tier-1 replacements. None of it carries scientific value
worth preserving in the public kit, but the archive copy in
`_dev_archive/<date>/` (created by `cleanup_dev_archive.sh --execute`)
keeps a record for internal reference.

### Bug-contaminated (per `experiments_v2/AUDIT_FINDINGS.md`)

| Path | Audit finding |
|---|---|
| `gridpilot/src/scheduler/scheduler_pue_aware.py` | F1: dead `pue_weight`; F2: incompatible energy accumulator with `replay_fcfs_pue` |
| `gridpilot/scripts/scheduler/gridpilot_pue.py` | wrapper around the above; inherits F1/F2 |
| `gridpilot/scripts/multicountry/replay_country_sweep.py` | F1, F2, F3 — produces non-comparable Δ-CFE between FCFS and f-SLA cells |
| `gridpilot/scripts/m100/inject_fsla_prior.py` | F5: broken fallback PUE-loader path (RAPS layout assumption) |

### Superseded by experiments_v2 (Tier-1 replacements)

| Old path | Replaced by |
|---|---|
| `gridpilot/scripts/multicountry/replay_single_tier_sweep.py` | `experiments_v2/scripts/04c_run_taxonomy_sweep.py` |
| `gridpilot/scripts/multicountry/replay_hyperparameter_sweep.py` | (superseded; hyperparameter sensitivity dropped from v2 paper) |
| `gridpilot/scripts/multicountry/replay_spatial_sweep.py` | (T5 spatial evaluation explicitly out of scope) |
| `gridpilot/scripts/m100/replay_all.py`, `replay_policy_matrix.py`, `seed_*` | superseded by 04c and 04d |
| `gridpilot/scripts/aggregate_v100_headlines.py` | `gridpilot/scripts/v100/replot_with_real_data.py` |
| `gridpilot/scripts/regenerate_main_figures.py` | `experiments_v2/scripts/{09,10,11}.py` |
| `gridpilot/scripts/reproduce_figures.py` | per-paper README compile recipe (see below) |
| `gridpilot/scripts/fig_sensitivity{,_tornado}.py` | replaced by `sensitivity/run_plackett_burman.py` (Tier 2) |
| `gridpilot/scripts/simulator/{reproduce_all,run_full_matrix}.py` | 04c taxonomy sweep |
| `gridpilot/scripts/figures/extract_paper_macros.py` | `experiments_v2/scripts/10_extract_paper_macros.py` |
| `gridpilot/scripts/figures/fig_{cfe_by_tier,country_cfe_lift,fairness_pareto,fsla_results,joint_pareto,latency_per_tier,sensitivity_no_ffr,spatial_routing_map,swf_comparison,tier_and_hyper}.py` | superseded by `experiments_v2/scripts/{07,09,11}.py` |
| `experiments_v2/scripts/02_run_country_sweep.py` | superseded by 04c |
| `experiments_v2/scripts/03_run_tier_sweep.py` | superseded by 04c |
| `experiments_v2/scripts/04_run_hyper_sweep.py` | hyperparameter sweep dropped from v2 paper |
| `experiments_v2/scripts/04b_run_seasonal_sweep.py` | superseded by 04c |
| `experiments_v2/scripts/05_extract_macros.py` | superseded by 10 |
| `experiments_v2/scripts/06_render_figures.py` | superseded by 09 + 11 |
| `experiments_v2/scripts/08_render_taxonomy_figure.py` | class-breakdown figure dropped from paper |

### Side-branch / never-promoted

| Path | Reason |
|---|---|
| `experiments_v2/src/schedulers/fsla_carbon_aware_v2.py` | Fix-2 argmin-CI dispatcher A/B test; not adopted |
| `experiments_v2/scripts/run_fix2_sweep.sh` | Fix-2 A/B sweep driver; not used by published numbers |
| `experiments_v2/data/taxonomy_sweep_v2/` | Output dir of the above; never populated for the headline |

### Auto-generated and duplicate trees

| Path | Reason |
|---|---|
| `papers/{pecs2026,whpc2026}/architecture.pptx` | PowerPoint sources discarded per user instruction; canonical figures are hand-edited PDFs + .drawio sources |
| `gridpilot/scripts/figures/fig_*architecture*.py`, `make_architecture_pptx.py` | auto-generators superseded by hand-edited figures |
| `gridpilot/figures/` | working-in-progress figure dir, duplicate of `papers/*/figs/` |
| `figs/`, `files/` (repo root) | duplicates of `papers/*/figs/` |

---

## Reproducibility recipe

After installing the requirements:

```bash
cd gridpilot
python -m pip install -r requirements.txt
```

### Reproduce the f-SLA paper

```bash
# 1. Taxonomy + mechanism sweeps (≈ 20 min on 4 workers)
PYTHONPATH=experiments_v2/src python3 experiments_v2/scripts/04c_run_taxonomy_sweep.py
PYTHONPATH=experiments_v2/src python3 experiments_v2/scripts/04d_run_mechanism_sweep.py

# 2. Figures + macros
PYTHONPATH=experiments_v2/src python3 experiments_v2/scripts/07_render_seasonal_figure.py
PYTHONPATH=experiments_v2/src python3 experiments_v2/scripts/09_render_paper_figures.py
PYTHONPATH=experiments_v2/src python3 experiments_v2/scripts/11_render_mechanism_figure.py
PYTHONPATH=experiments_v2/src python3 experiments_v2/scripts/10_extract_paper_macros.py \
  --tax-csv  experiments_v2/data/taxonomy_sweep/TAXONOMY_SUMMARY.csv \
  --mix-csv  experiments_v2/data/taxonomy_sweep/TAXONOMY_MIX.csv \
  --raw-csv  experiments_v2/data/taxonomy_sweep/taxonomy_sweep.csv \
  --mech-csv experiments_v2/data/mechanism_sweep/MECHANISM_SUMMARY.csv \
  --out      ../papers/pecs2026/figs/results.tex

# 3. Compile (assumes splncs04.bst on TEXMF path)
cd ../papers/pecs2026 && pdflatex main && bibtex main && pdflatex main && pdflatex main
```

### Reproduce the GridPilot paper (V100 testbed)

```bash
# 1. Hardware experiments (on a comparable 3×V100 node)
PYTHONPATH=scripts python3 scripts/v100/experiments/E2_inner_loop_step_response.py
PYTHONPATH=scripts python3 scripts/v100/experiments/E3_outer_loop_tracking.py
PYTHONPATH=scripts python3 scripts/v100/experiments/E4_closed_loop_demand_following.py
PYTHONPATH=scripts python3 scripts/v100/experiments/E7_ffr_activation_latency.py

# 2. Multi-country PUE-aware sweep (same 04c driver, PUE-aware variant)
PYTHONPATH=experiments_v2/src python3 experiments_v2/scripts/04c_run_taxonomy_sweep.py --pue-aware

# 3. Figures + macros + compile (compile uses biber, not bibtex)
PYTHONPATH=scripts python3 scripts/v100/replot_with_real_data.py
cd ../papers/whpc2026 && pdflatex main && biber main && pdflatex main && pdflatex main
```

Full hardware reproduction takes ≤ 48 GPU-hours on a comparable 3×V100
testbed. The carbon-aware contract reproduction is CPU-only and
finishes in under 30 minutes on 4 workers.

---

## Audit-trail summary

- **Audit findings file:** `gridpilot/experiments_v2/AUDIT_FINDINGS.md`
  (Phase-3 dispatcher audit, 2026-05-19)
- **Pre-release checklist:** `papers/pecs2026/PRE_RELEASE_CLEANUP.md`
  (8 sections; the canonical operational guide)
- **Cleanup driver:** `papers/pecs2026/cleanup_dev_archive.sh`
  (`--archive`, `--delete`, `--all` modes; dry-run by default)
- **This file** lists exactly the residual contents after the cleanup
  driver has been run.
