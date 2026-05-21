# Reproducing GridPilot figures from raw data

The figures in the GridPilot paper can be regenerated at three levels of
fidelity, depending on what data and infrastructure you have access to.

## Level 1 — Schematic regeneration (no raw data needed)

Run:

```bash
python scripts/reproduce_figures.py --out-dir figures/
```

This regenerates the three figures whose source code is in this repository
(`fig_proact_1x4.pdf`, `fig_scale_time_1x4.pdf`, `fig_sensitivity_tornado.pdf`)
using the headline numerics encoded in `data/`. The visual structure
matches the paper's figures exactly; the underlying functional shapes
(diurnal CI profiles, scale-vs-savings curves, sensitivity envelopes)
are generated from documented analytic forms anchored to the verified
Table 1 numerics.

This level is sufficient for visual inspection of the published results
and for understanding the paper's claims. It is **not** a full
re-derivation: the headline numerics themselves were computed once from
the raw M100 + ENTSO-E + RAPS pipeline and are stored as CSVs.

## Level 2 — Headline numerics re-derivation

To re-derive the headline numerics in `data/table1_headline_savings.csv`,
`data/ci_trajectory.csv`, and `data/pb_sensitivity_5factor.csv` from
intermediate aggregations:

### Prerequisites

- M100 PM100 dataset under `data/m100/` (see [`DATASETS.md`](DATASETS.md))
- ENTSO-E API key (see `DATASETS.md`)
- RAPS reference-system configurations (see [`EXADIGIT_RAPS_SETUP.md`](EXADIGIT_RAPS_SETUP.md))
- The `gridpilot_replay` simulator (separate codebase)

### Procedure

```bash
# Step 1: Pre-process M100 traces to evaluation subset
python scripts/m100_filter.py \
  --input data/m100/raw/ \
  --output data/m100/eval_1994.parquet \
  --filter "duration_s > 60 AND duration_s < 86400 AND has_gpu_telemetry = TRUE" \
  --year 2021

# Step 2: Fetch ENTSO-E CI for the three countries
python scripts/entsoe_fetch.py \
  --countries CH,IT,DE \
  --year 2025 \
  --output data/entsoe_2025.parquet

# Step 3: Run the 2x4 factorial (8 conditions per country per year)
python scripts/run_factorial.py \
  --m100 data/m100/eval_1994.parquet \
  --entsoe data/entsoe_2025.parquet \
  --countries CH,IT,DE \
  --years 2025,2028,2032 \
  --schedulers FCFS,carbon_aware \
  --power-modes none,ci_only,ffr_only,ci_ffr \
  --output data/factorial_results.parquet

# Step 4: Aggregate to headline numerics
python scripts/aggregate_headlines.py \
  --factorial data/factorial_results.parquet \
  --output data/table1_headline_savings.csv

# Step 5: Run Plackett-Burman 5-factor sensitivity
python scripts/run_pb_sensitivity.py \
  --baseline-condition "DE 2025 50MW carbon_aware ci_ffr" \
  --factors data/pb_factor_levels.yaml \
  --output data/pb_sensitivity_5factor.csv
```

Total runtime on a 32-core CPU: ~6 hours for the factorial sweep,
~30 minutes for the PB sensitivity, ~5 minutes for the aggregation.

## Level 3 — Full re-derivation including V100 hardware

To re-derive everything including the V100 calibration coefficients:

### Prerequisites

- All of Level 2 above.
- A V100 (or A100 / H100) testbed with NVML access.
- ~3 days of dedicated wall-clock time on the testbed.

### Procedure

```bash
# Step 1: Run the V100 E1-E7 measurement campaign
# (see V100_MEASUREMENT_PROTOCOL.md for hardware setup)
python scripts/v100_e1_calibrate.py --testbed <your-host> --output data/e1.csv
python scripts/v100_e2_step.py        --testbed <your-host> --output data/e2.csv
python scripts/v100_e3_predictor.py   --testbed <your-host> --output data/e3.csv
python scripts/v100_e4_demand.py      --testbed <your-host> --output data/e4.csv
python scripts/v100_e6_fairness.py    --testbed <your-host> --output data/e6.csv
python scripts/v100_e7_ffr.py         --testbed <your-host> --output data/e7.csv

# Step 2: Generate V100 figures
python scripts/v100_make_figures.py --out-dir figures/v100/

# Step 3: Cross-validate against RAPS (1.85% target residual)
python scripts/raps_cross_validate.py \
  --v100-coeffs data/e1_coefficients.json \
  --raps-configs $RAPS_CONFIGS_PATH \
  --output data/raps_residuals.csv

# Step 4: Run the multi-scale projection (Levels 2 and 3 results merge here)
python scripts/multiscale_projection.py \
  --v100-base-kw 0.78 \
  --raps-calibration data/raps_residuals.csv \
  --headlines data/table1_headline_savings.csv \
  --output data/multiscale_full.csv

# Step 5: Regenerate all figures from the full pipeline
python scripts/reproduce_figures.py \
  --use-real-data \
  --raw-table1 data/multiscale_full.csv \
  --raw-pb data/pb_sensitivity_5factor.csv \
  --out-dir figures/
```

Total Level 3 runtime: ~3 days V100 testbed + ~6 hours CPU pipeline.

## Reproducibility caveats

### What is fully reproducible

- The figure visual structure (Level 1).
- The 2×4 factorial design and aggregation logic (Level 2, given the data).
- The RAPS cross-validation procedure (Level 3, given the data).

### What requires the original infrastructure

- The exact V100 measurements depend on the specific 3× V100 SXM2 board
  layout in `ecocloud-exp06` and the NVML 12.x version. Re-running on a
  different V100 board may produce slightly different coefficients (we
  expect within ±2% per E1 results across hardware revisions).
- The exact ENTSO-E CI values depend on the snapshot date of the API
  query. ENTSO-E publishes corrections to historical data, so a query
  in 2027 for 2025 will not exactly match a query in 2026.
- The Plackett-Burman sensitivity coefficients depend on the specific
  factor levels chosen. We document our choices in
  `configs/pb_design.yaml` for transparency.

### What is intentionally non-reproducible

The 2×4 factorial includes a randomised job-arrival re-sampling step (to
produce bootstrap confidence intervals). The CSV in `data/` is one
realisation; running the pipeline again will produce nearby but not
identical numerics. The headline %-reduction values are stable across
realisations within ±0.5 pp.

## Verification checklist

After running Level 2 or Level 3, verify:

- [ ] `data/table1_headline_savings.csv` matches the in-tree version
  within ±0.5 pp on the reduction column.
- [ ] RAPS residual mean is below 5% (target 1.85%).
- [ ] V100 E7 median latency is below 150 ms (target 97–98 ms; up to
  ~150 ms is acceptable on hardware with weaker NTP synchronisation).
- [ ] PB sensitivity total envelope is within ±5 pp of the headline 26%.

If any of these fail, file a GitHub issue with your environment details
and we will help diagnose.
