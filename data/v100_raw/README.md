# V100 raw measurement data — REAL EXPERIMENTAL DATA

## Status

The CSVs and JSON files in this directory are the **real measurements**
collected on EPFL EcoCloud's `ecocloud-exp06` testbed during the April 2026
GridPilot E1–E7 measurement campaign. Hostname, GPU UUIDs, NVML driver
version, and wallclock timestamps are preserved in the per-experiment
`*.meta.json` and `*.stdout` files.

This is the same telemetry that the paper's headline figures (Figures 7 and
the Table 2 numerics) are derived from. To regenerate the figures from this
raw data, see [`../../docs/V100_MEASUREMENT_PROTOCOL.md`](../../docs/V100_MEASUREMENT_PROTOCOL.md)
and [`../../scripts/v100/`](../../scripts/v100/).

## Hardware and software environment

| Field | Value |
|-------|-------|
| Hostname | `ecocloud-exp06` (EPFL EcoCloud) |
| GPUs | 3× NVIDIA Tesla V100-SXM2 32 GB, 300 W TDP each |
| GPU UUIDs | `GPU-c0334254-...` and 2 others (preserved in `*.meta.json`) |
| Driver / NVML | 580.65.06 / NVML 12.x |
| OS | Ubuntu 24.04 LTS |
| CUDA | 12.x |
| Telemetry rate | 100 Hz NVML, 10 Hz CPU/RAPL |
| Power-cap actuation | `nvidia-smi -pl <W>` |
| Campaign date | 2026-04-28 to 2026-04-30 |

## Directory structure

```
v100_raw/
├── headline_table.csv                    Headline numerics summary (paper Table 2)
├── E1_power_cap_sweep/                   36 cells × 30 s NVML telemetry per cell
│   ├── <workload>_pcap<W>_sm<MHz>.csv    Per-cell timeseries (3659 samples × 14 columns)
│   ├── <workload>_pcap<W>_sm<MHz>.meta.json   Cell metadata (start/end wallclock, GPU info)
│   ├── <workload>_pcap<W>_sm<MHz>.stdout      Workload-driver stdout
│   ├── parsed_results.csv                Aggregated per-cell metrics
│   └── summary_table.csv                 Best-efficiency operating points
├── E2_inner_loop/                        200 Hz step-response telemetry
│   ├── telemetry.csv                     280→200 W step, 100 Hz NVML
│   ├── telemetry.meta.json
│   ├── step_plan.json                    Step protocol
│   └── workload.stdout
├── E3_outer_loop/                        AR(4) predictor accuracy per workload
│   ├── <workload>_metrics.json           MAE, RMSE, p95, AR(4) coefficients
│   ├── <workload>_predictions.csv        One-step-ahead predicted vs measured
│   ├── <workload>_telemetry.csv          Underlying NVML telemetry
│   ├── <workload>_telemetry.meta.json
│   └── <workload>_stdout
├── E4_closed_loop/                       Closed-loop demand-following
│   ├── <workload>_summary.json           N samples, MAE, p95, mean demand
│   ├── <workload>_trajectory.csv         Demand vs measured power trajectory
│   └── <workload>_workload.stdout
├── E6_multigpu/                          Multi-GPU fairness baseline
│   ├── budget_<W>_metrics.json           Jain index, per-GPU energy/power
│   ├── budget_<W>_telemetry.csv
│   └── budget_<W>_gpu<id>_workload.stdout
├── E7_ffr_latency/                       End-to-end FFR actuation latency
│   ├── verdict.json                      All-workloads pass/fail summary
│   ├── workload_<wl>_summary.json        median, mean, p95, max, pass rate per workload
│   ├── workload_<wl>_runs.csv            Per-trial latency + per-GPU actuation timestamps
│   └── workload_<wl>_gpu<id>.stdout
├── raps_calibration/                     RAPS power-model calibration
│   ├── coefficients.json                 Per-workload P_GPU = P_idle + α·f + β·f²·L + γ·L
│   ├── fit_summary.json                  In-sample MAE, RMSE, R², LOOCV %
│   ├── fit_diagnostics.csv
│   ├── leave_one_out_cv.json             Per-cell LOOCV residuals
│   └── fit_curves.png
├── cluster_projection/                   3-GPU node → 36k-GPU cluster envelope
│   ├── projection.csv                    Per-scale max power/throughput/efficiency
│   └── projection_summary.json
└── cross_validation/                     V100 vs M100 cross-validation
    ├── comparison_report.json            All 4 cross-validation axes
    ├── comparison_report.md              Human-readable summary
    └── cross_validation.json             Per-axis pass/fail with notes
```

## Headline numerics (real measurements)

The values in `headline_table.csv` are the canonical real numbers cited in
the paper:

| Experiment | Metric | Workload | Value |
|------------|--------|----------|-------|
| E1 | Best-efficiency $p_{cap}$ | all | **150 W** |
| E1 | Best-efficiency $f_{sm}$ | all | **945 MHz** |
| E1 | iters/joule (best) | inference | **2.880** |
| E1 | iters/joule (best) | matmul | **0.570** |
| E1 | iters/joule (best) | bursty | **0.549** |
| E3 | AR(4) MAE | inference | **4.69 W** |
| E3 | AR(4) MAE | matmul | **7.00 W** |
| E3 | AR(4) MAE | bursty | **19.66 W** |
| E4 | Demand-track relative MAE | inference | **1.68%** |
| E4 | Demand-track relative MAE | matmul | **2.12%** |
| E4 | Demand-track relative MAE | bursty | **11.08%** |
| E6 | Jain fairness index | static caps | **0.333** (worst case) |
| E7 | FFR latency, median | matmul | **97.221 ms** |
| E7 | FFR latency, median | inference | **97.471 ms** |
| E7 | FFR latency, median | bursty | **97.797 ms** |
| E7 | FFR latency, max | all | **101.108 ms** |
| E7 | Pass rate at 700 ms budget | all | **90/90** |
| Cluster | Max facility power, 3-GPU node | all | **0.78 kW** |
| Cluster | Max facility power, 36-GPU rack | all | **9.31 kW** |
| Cluster | Max facility power, 1800-GPU pod | all | **465.59 kW** |
| Cluster | Max facility power, 36000-GPU cluster | all | **9311.82 kW** (9.31 MW) |

## Cross-validation against published references

Documented in `cross_validation/comparison_report.json`:

| Axis | V100 (this work) | Reference | Δ% | Pass? |
|------|------------------|-----------|----|----|
| Per-GPU mean power | 121.2 W | M100 production median 237 W (Antici et al. 2023) | -48.9% | below_band (expected: low-power probe regime) |
| AR(4) MAE on multi-phase | 19.66 W (bursty) | — | — | V100-only (M100 replay deferred to ProACT WP3) |
| 980-node scaling envelope | 1014 kW | M100 published 1000 kW (Borghesi et al. 2023) | **+1.4%** | **PASS** (within 10% threshold) |
| Per-workload power-model LOOCV MAE | 2.72% (matmul), 2.94% (bursty), 4.71% (inference); mean 3.45% | — | — | (in-house metric) |

## Reproducibility

Each experiment was driven by the corresponding script in
[`../../scripts/v100/experiments/`](../../scripts/v100/experiments/), with
controller code in [`../../scripts/v100/controller/`](../../scripts/v100/controller/)
and workload definitions in
[`../../scripts/v100/workloads/`](../../scripts/v100/workloads/). To
reproduce on a comparable testbed:

```bash
cd scripts/v100/
# E1: 36-cell sweep
python experiments/run_e1_sweep.py --output-dir results/E1_power_cap_sweep
# E2-E7: see V100_MEASUREMENT_PROTOCOL.md for full procedure
```

Then run the analysis pipeline:

```bash
python src/calibrate_raps.py --sweep results/E1_power_cap_sweep/parsed_results.csv \
                              --output results/raps_calibration/
python src/project_cluster.py --calib results/raps_calibration/coefficients.json \
                              --output results/cluster_projection/
python src/compare_v100_vs_m100.py --v100 results/ --output results/comparison/
python src/replot_with_real_data.py --results results/ --output figures/
```

## Licence

All raw measurement files in this directory are released under
**CC-BY 4.0**. The accompanying scripts under `scripts/v100/` are released
under **MIT**.

## Citation

If you use this data, please cite the paper:

```bibtex
@inproceedings{constantinescu2026gridpilot,
  title     = {GridPilot: A PUE-Aware Predictive Controller for Carbon-Aware
               HPC, Validated from V100 to 50 MW},
  author    = {Constantinescu, Denisa-Andreea and
               Senator, Steven Terry and
               Atienza, David},
  booktitle = {Proceedings of Euro-Par 2026},
  year      = {2026}
}
```

The raw V100 telemetry will additionally be archived on Zenodo at
publication time (DOI to be assigned).
