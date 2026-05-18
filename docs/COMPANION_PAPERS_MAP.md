# GridPilot v1.0 — Companion-Papers Reproducibility Map

The GridPilot v1.0 release accompanies two Euro-Par 2026 Workshop papers:

- **WHPC.** *GridPilot: Real-Time Grid-Responsive Control for AI Supercomputers.*  The downstream actuation paper; uses V100 hardware measurements (E1–E7), the four-component PUE model, the RAPS power-model cross-validation, and a multi-country PUE-aware controller sweep (E8).
- **PECS.** *f-SLA: A User-Side Contract for Truthful Workload Flexibility towards Carbon-Free Supercomputing* (double-blind).  The upstream contract paper; uses the M100 production trace replayed against six European grids, a five-tier ladder (T0–T4 including the CarbonScaler-style T4 elastic-burst tier), four anti-gaming mechanisms M0–M3, and a $5\times 5$ policy matrix.

The two manuscripts are **claim-disjoint**: WHPC owns the sub-second actuation latency and the PUE correction; PECS owns the five-tier user-side contract, the multi-country CFE evaluation and the anti-gaming mechanism matrix.  Both share the bundled M100 trace and the per-country CI configs, and they share the multi-country sweep driver (`scripts/multicountry/replay_country_sweep.py`) which produces the PECS f-SLA result and the WHPC PUE-aware result in one pass.

This file maps every headline number in both papers to the exact data file, JSON key, or script that produced it, so that any reviewer (or any future reader of the published proceedings) can verify each claim by direct file inspection.  All headline numbers are read from on-disk experiment outputs by `scripts/figures/extract_paper_macros.py` into `papers/{whpc,pecs}2026/figs/results.tex` — there are no hard-coded numbers in the LaTeX body text.

## WHPC paper — claim-to-artefact map

| § / Table | Claim | Source artefact | Verification command |
|---|---|---|---|
| §3.1, Alg. 1 | Tier-1 PID gains (Kp, Ki, Kd) = (0.6, 0.05, 0.02) | `scripts/v100/controller/tier1_pid.py` (constants `KP, KI, KD`) | `grep -E "^(KP|KI|KD)" scripts/v100/controller/tier1_pid.py` |
| §3.1 | Thermal envelope T_max = 85 °C, τ = 8 s | `scripts/v100/controller/thermal_model.py` | `grep -E "(T_MAX_C|TAU_S)" scripts/v100/controller/thermal_model.py` |
| §3.2, Eq. (3) | AR(4) coefficients per workload, RLS λ = 0.97 | `data/v100_raw/E3_outer_loop/<workload>_metrics.json` (key: `ar4_coefficients`) | `jq '.ar4_coefficients' data/v100_raw/E3_outer_loop/matmul_compute_bound_metrics.json` |
| §3.3, Eq. (4) | Tier-3 objective weights 0.55 FFR + 0.45 CFE | `configs/tier3_objective.yaml` | `grep -E "(ffr_weight|cfe_weight)" configs/tier3_objective.yaml` |
| §4 | Safety-island TLA⁺ liveness spec | `scripts/v100/safety_island/spec.tla` | `wc -l scripts/v100/safety_island/spec.tla` (expect <200 lines) |
| Table 1, E1 | Best-efficiency (p_cap, f_sm) = (150 W, 945 MHz) | `data/v100_raw/E1_power_cap_sweep/summary_table.csv` | `head -1 data/v100_raw/E1_power_cap_sweep/summary_table.csv` |
| Table 1, E1 | iters/J: 2.880 / 0.570 / 0.549 (inf / mm / burst) | `data/v100_raw/headline_table.csv` rows E1.iters_per_joule.* | `awk -F, '/E1.iters_per_joule/' data/v100_raw/headline_table.csv` |
| Table 1, E2 | Settling time 18 / 21 / 29 ms | `data/v100_raw/E2_inner_loop/step_plan.json` (settling computed in `scripts/v100/src/replot_with_real_data.py`) | `python scripts/v100/src/replot_with_real_data.py --metric e2_settling` |
| Table 1, E3 | AR(4) MAE 4.69 / 7.00 / 19.66 W | `data/v100_raw/E3_outer_loop/<workload>_metrics.json` key `mae_W` | `for w in inference_memory_bound matmul_compute_bound bursty_alternating; do jq -r ".mae_W" data/v100_raw/E3_outer_loop/${w}_metrics.json; done` |
| Table 1, E4 | Demand-track rel. MAE 1.68 / 2.12 / 11.08 % | `data/v100_raw/E4_closed_loop/<workload>_summary.json` key `relative_mae_pct` | `for w in inference_memory_bound matmul_compute_bound bursty_alternating; do jq -r ".relative_mae_pct" data/v100_raw/E4_closed_loop/${w}_summary.json; done` |
| Table 1, E6 | Worst-case Jain index 0.333 | `data/v100_raw/E6_multigpu/budget_900_metrics.json` key `jain_index` | `jq '.jain_index' data/v100_raw/E6_multigpu/budget_*_metrics.json \| sort -n \| head -1` |
| Table 1, E7 | Median latency 97.221 / 97.471 / 97.797 ms | `data/v100_raw/E7_ffr_latency/workload_<wl>_summary.json` key `median_ms` | `for w in matmul inference bursty; do jq -r ".median_ms" data/v100_raw/E7_ffr_latency/workload_${w}_summary.json; done` |
| Table 1, E7 | Max latency 101.108 ms, 90/90 pass | `data/v100_raw/E7_ffr_latency/verdict.json` | `jq '.max_ms, .pass_count, .total_trials' data/v100_raw/E7_ffr_latency/verdict.json` |
| §13, Eq. (5) | Power-model coefficients α, β, γ per workload | `data/v100_raw/raps_calibration/coefficients.json` | `jq '.' data/v100_raw/raps_calibration/coefficients.json` |
| Table 1, RAPS | LOOCV mean MAE 3.45 % | `data/v100_raw/raps_calibration/leave_one_out_cv.json` key `mean_mae_pct` | `jq '.mean_mae_pct' data/v100_raw/raps_calibration/leave_one_out_cv.json` |
| Table 1, RAPS | 980-node envelope +1.4 % | `data/v100_raw/cross_validation/comparison_report.json` axis `980_node_scaling` | `jq '."980_node_scaling".delta_pct' data/v100_raw/cross_validation/comparison_report.json` |
| §15 | astroCAMP cross-check: ~100 anonymised WSClean+IDG runs on H100 + EPYC 9334 | external dataset: `astrocamp-zenodo-20093790/traces_anonymized/` (CC-BY 4.0) | `ls astrocamp-zenodo-20093790/traces_anonymized/*.monit \| wc -l` |
| §15 | AR(4) MAE on H100 imaging workload (one-step, 30 s window, λ=0.97) | `data/astrocamp_cross_check/headline.csv` row `ar4_mae_h100_W` | `python scripts/v100/cross_check_astrocamp.py --traces astrocamp-zenodo-20093790/traces_anonymized --output data/astrocamp_cross_check/` |
| §15 | H100 power-model LOOCV MAE (P_idle + α f + β f² L + γ L) | `data/astrocamp_cross_check/coefficients_h100.json` key `loocv_mean_mae_pct` | `jq '.loocv_mean_mae_pct' data/astrocamp_cross_check/coefficients_h100.json` |
| §15 | PMT-vs-PDU integration disagreement (4th measurement chain) | `data/astrocamp_cross_check/headline.csv` row `pmt_vs_pdu_disagree_pct` | `awk -F, '/pmt_vs_pdu/' data/astrocamp_cross_check/headline.csv` |

### WHPC reproduction (full E1–E7 campaign on a comparable 3× V100 testbed)

```bash
cd scripts/v100/
# E1: 36-cell sweep (≈10 GPU-hours)
python experiments/run_e1_sweep.py --output-dir results/E1_power_cap_sweep
# E2: inner-loop step response (≈30 minutes per workload)
python experiments/run_e2_step.py --output-dir results/E2_inner_loop
# E3: AR(4) predictor accuracy (≈45 minutes per workload)
python experiments/run_e3_predictor.py --output-dir results/E3_outer_loop
# E4: closed-loop demand-following (≈1 hour per workload)
python experiments/run_e4_demand_following.py --output-dir results/E4_closed_loop
# E6: multi-GPU fairness baseline (≈3 hours)
python experiments/run_e6_multigpu.py --output-dir results/E6_multigpu
# E7: end-to-end FFR latency (≈4 hours)
python experiments/run_e7_ffr_latency.py --output-dir results/E7_ffr_latency
# Cross-validation against M100 (≈5 minutes)
python src/calibrate_raps.py --sweep results/E1_power_cap_sweep/parsed_results.csv \
                              --output results/raps_calibration/
python src/compare_v100_vs_m100.py --v100 results/ --output results/comparison/
```

Full procedure: `docs/V100_MEASUREMENT_PROTOCOL.md`.

## PECS paper — claim-to-artefact map

| § / Table | Claim | Source artefact | Verification command |
|---|---|---|---|
| §3.1 | Five-tier ladder (T0..T4) with $\alpha_0..\alpha_4 = (0, 0.02, 0.04, 0.06, 0.08)$ and T4 replica envelope $[0.5\times, 2\times]$ | `src/scheduler/fsla.py` (constants `TIER_WINDOW_H`, `TIER_CREDIT_H`, `T4_REPLICA_MIN/MAX`) | `grep -E "(TIER_NAMES\|TIER_WINDOW_H\|TIER_CREDIT_H\|T4_REPLICA)" src/scheduler/fsla.py` |
| §3.2 | Monotone credit schedule (Babaioff et al. 2022 sufficient condition for IC) | `src/scheduler/fsla.py:DEFAULT_ALPHA` | `python -c "import sys; sys.path.insert(0,'src'); from scheduler.fsla import DEFAULT_ALPHA, TIER_CREDIT_H; assert all(TIER_CREDIT_H[i] < TIER_CREDIT_H[i+1] for i in range(len(TIER_CREDIT_H)-1)); print('monotone OK')"` |
| §3.3 | Four anti-gaming mechanisms M0–M3 | `src/scheduler/fsla_mechanisms.py` | `pytest tests/test_gaming_mechanisms.py -v` |
| §4 | Per-country CI configs SE/CH/FR/IT/DE/PL with 2025 means and diurnal envelopes | `configs/grids/{SE,CH,FR,IT,DE,PL}.yaml` | `for c in SE CH FR IT DE PL; do head -1 configs/grids/${c}.yaml; done` |
| §4 | Real ENTSO-E A75 hourly CI fetcher (IPCC AR5 emission factors) | `scripts/m100/fetch_real_ci_series.py` | `python scripts/m100/fetch_real_ci_series.py --help` |
| §4 | Extended Jan+Feb 2022 M100 trace ETL with fuzzy schema | `scripts/m100/build_extended_trace.py` | `python scripts/m100/build_extended_trace.py --help` |
| §5, Tab.~countries | Per-country headline: CFE, $\Delta$CFE, effective-CI, $\Delta$CI, demand flex, avoided tonnage at 10/50 MW | `data/m100/country_sweep/COUNTRY_SUMMARY.csv` (1 row per grid, 8 metric columns) | `head -1 data/m100/country_sweep/COUNTRY_SUMMARY.csv` (then for the LaTeX macros: `cat ../papers/pecs2026/figs/results.tex \| grep "\\\\PecsBaseCfeSE"`) |
| §5, Fig. country_cfe | Headline CFE-lift + effective-CI reduction + demand-flex 3-panel figure | `figs/fig_country_cfe_lift.pdf` (regenerated by `scripts/figures/fig_country_cfe_lift.py`) | `PYTHONPATH=src python scripts/figures/fig_country_cfe_lift.py --matrix data/m100/country_sweep/country_sweep.csv --out figs/fig_country_cfe_lift.pdf` |
| §5.1, Fig. proact | Sensitivity and adoption analysis (CFE adoption surface, seasonal CO\textsubscript{2}, summer CI, Pareto front) | `figures/fig_proact_1x4.pdf` (bundled artefact, regenerated by the upstream sensitivity sweep) | `ls -la figures/fig_proact_1x4.pdf` |
| §5.2, Fig. policy | Anti-gaming policy matrix (5 baselines × 5 mechanisms × 8 seeds) | `data/m100/policy_matrix/policy_matrix.csv` + `figs/fig_{cfe_by_tier,swf_comparison,fairness_pareto,latency_per_tier}.pdf` | `head -1 data/m100/policy_matrix/policy_matrix.csv` |
| §5.2 | Hypothesis outcomes H1–H5 | `data/m100/policy_matrix/HYPOTHESIS_OUTCOMES.json` | `jq '.' data/m100/policy_matrix/HYPOTHESIS_OUTCOMES.json` |
| §6.1 | T4 elastic burst marked deterministically elastic in dispatcher | `scripts/multicountry/replay_country_sweep.py` (`jobs_with_tiers["is_elastic"] = (jobs_with_tiers.get("tier", T_RIGID) == 4)`) | `grep "is_elastic" scripts/multicountry/replay_country_sweep.py` |
| §6.2 (designed) | Spatial routing across the six grids (GAIA) | not in this release; see Sect.~\ref{sec:discuss} of the PECS paper | n/a |
| §6.2 (designed) | Price-proportional credits (Lechowicz online competitive-ratio framework) | not in this release; see Sect.~\ref{sec:discuss} of the PECS paper | n/a |
| Acceptance | f-SLA tier ladder + ANTI-gaming + dispatch invariants — 48 unit tests | `tests/{test_fsla,test_gaming_mechanisms,test_gridpilot_pue}.py` | `pytest tests/ -q` |

### PECS reproduction (full M100 multi-country sweep + policy matrix)

```bash
# Single end-to-end command (full mode, ~75 min on 16 cores):
bash scripts/run_all_experiments.sh
# or split into stages (see docs/RUNBOOK.md):
PYTHONPATH=src python scripts/m100/replay_policy_matrix.py \
    --jobs data/traces/m100_real_jobs.parquet \
    --ci   configs/grids/DE.yaml --pue raps/config/marconi100.yaml \
    --policies FCFS,EASY,SAF,RLBackfilling,GridPilot-PUE \
    --mechanisms none,M0,M1,M2,M3 --seeds 8 --workers 4 \
    --output-dir data/m100/policy_matrix/
PYTHONPATH=src python scripts/multicountry/replay_country_sweep.py \
    --jobs data/traces/m100_real_jobs.parquet \
    --grids configs/grids/SE.yaml,configs/grids/CH.yaml,configs/grids/FR.yaml,configs/grids/IT.yaml,configs/grids/DE.yaml,configs/grids/PL.yaml \
    --pue-yaml raps/config/marconi100.yaml \
    --mw 1,10,50 --fsla-mechanisms none,M0,M1,M2,M3 \
    --pue-mechanisms none,GridPilot-PUE --seeds 8 --workers 4 \
    --output-dir data/m100/country_sweep/
PYTHONPATH=src python scripts/figures/extract_paper_macros.py
bash ../papers/build.sh pecs
```

### Legacy single-paper scripts (not part of the current pipeline)

The scripts `scripts/m100/inject_fsla_prior.py`,
`scripts/projection/multiyear_50mw.py`,
`scripts/sensitivity/run_plackett_burman.py`,
`scripts/figures/fig_fsla_results.py` and
`scripts/figures/fig_multiscale_operational_only.py` predate the
two-paper split.  They are retained for traceability of the early-
stage single-paper draft but are NOT part of the current
`run_all_experiments.sh` pipeline.  The corresponding outputs under
`data/m100/fsla_counterfactual*/` are likewise legacy.

## Cross-paper dependencies

The two papers share the bundled M100 trace
(`data/traces/m100_real_jobs.parquet`), the per-country CI configs
(`configs/grids/*.yaml`), the four-component PUE model
(`src/cooling/cooling_pue_model.py`) and the multi-country sweep
driver (`scripts/multicountry/replay_country_sweep.py`).  The
WHPC paper additionally depends on the V100 hardware telemetry
(`data/v100_raw/`); the PECS paper additionally depends on the
$5\times 5$ policy matrix (`scripts/m100/replay_policy_matrix.py`).
The two papers can be read independently.

## Versioning

- **GridPilot v1.0.0-anon.** Tagged ≤19 May 2026 for the PECS double-blind submission. Hosted on an anonymous mirror (`anonymous.4open.science/r/gridpilot-…`).
- **GridPilot v1.0.0.** Tagged at camera-ready (≤10 July 2026). Public GitHub release with Zenodo DOI.
- **GridPilot v1.1.0** (planned). Adds H100/H200 controller calibration, direct-liquid cooling regime, and the live f-SLA user-cohort dataset (deferred to ProACT WP1).

## Licensing

- **Code:** MIT (see `LICENSE`)
- **Data and figures:** CC-BY 4.0
- **Third-party data:** see `licenses/THIRD_PARTY.md` for the M100 PM100, ENTSO-E, and RAPS upstream licences and how they apply to redistribution.

## Citing

If you use the v1.0 release in your research, please cite both companion papers:

```bibtex
@inproceedings{constantinescu2026gridpilot,
  title     = {{GridPilot}: Real-Time Grid-Responsive Control for {AI} Supercomputers},
  author    = {Constantinescu, Denisa-Andreea and Atienza, David},
  booktitle = {Euro-Par 2026 Workshops --- Women in HPC (WHPC) Session},
  publisher = {Springer LNCS},
  year      = {2026}
}

@inproceedings{anonymous2026fsla,
  title     = {{f-SLA}: A User-Side Contract for Truthful Workload Flexibility
               towards Carbon-Free Supercomputing},
  author    = {Anonymous},
  booktitle = {Euro-Par 2026 Workshops --- Performance and Energy-efficient
               Computing Systems (PECS)},
  publisher = {Springer LNCS},
  year      = {2026},
  note      = {Double-blind submission; authorship restored at camera-ready}
}
```

For contact information, see `CONTRIBUTING.md`.
