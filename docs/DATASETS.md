# Datasets used in GridPilot

This document describes every dataset cited in the paper, its licence, and
how to obtain it. Where the dataset cannot be redistributed in this
repository, we explain the provenance and the procedure for fetching it.

## 1. Marconi100 PM100 (CINECA)

### Description
A holistic Tier-0 supercomputer monitoring dataset from CINECA's
Marconi100 (M100) system, an IBM AC922 with 980 nodes and 3,920 NVIDIA
V100 GPUs. The PM100 derivative covers approximately 2.5 years (2020–2022)
with ~49.9 TB of raw telemetry and ~230,000 jobs.

### Citation
Borghesi, A., Antici, F., Lo Presti, G., et al. *Marconi100: a holistic
Tier-0 supercomputer monitoring dataset.* Scientific Data 10, 288 (2023).
[https://doi.org/10.1038/s41597-023-02174-3](https://doi.org/10.1038/s41597-023-02174-3)

### How to obtain
1. Visit the dataset landing page on the CINECA repository.
2. Register for access (free, requires an academic affiliation).
3. Download the raw telemetry archive (~49.9 TB) or the PM100 derivative
   (~smaller, job-level summaries).
4. Place under `data/m100/` (gitignored). The directory layout expected
   by `scripts/m100_load.py` is documented in `docs/M100_LAYOUT.md`.

### Subset used in this paper
We use a 1,994-job evaluation subset drawn from PM100, restricted to:
- GPU-tagged jobs (i.e. with non-empty NVML telemetry)
- Jobs of duration > 60 s and < 24 h
- Jobs running between 2021-01-01 and 2021-12-31

### Licence
CC-BY 4.0 per the Scientific Data publication. Redistribution is permitted
with attribution; we do not include the raw data in this repository to
respect the CINECA registration workflow.

---

## 2. ENTSO-E A75 carbon-intensity time series

### Description
Hourly carbon-intensity values for the 25 European Network of Transmission
System Operators for Electricity (ENTSO-E) member countries, derived from
the Transparency Platform's A75 actual generation per type. The CI is
computed as the weighted average of generation-type-specific emission
factors over the hourly generation mix.

### Source
ENTSO-E Transparency Platform: [https://transparency.entsoe.eu](https://transparency.entsoe.eu)

API documentation:
[https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html](https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html)

### How to obtain
1. Register for an ENTSO-E API key (free, requires an institutional email).
2. Set the environment variable:
   ```bash
   export ENTSOE_API_KEY=<your-key>
   ```
3. Run the fetch script (separate codebase, not in this repository):
   ```bash
   gridpilot-fetch-entsoe --countries CH,IT,DE --year 2025 \
     --out data/entsoe_cache/
   ```

### Subset used in this paper
- Countries: Switzerland, Italy, Germany.
- Hourly resolution, full calendar year 2025.
- Emission factors per generation type from Ember
  ([https://ember-climate.org](https://ember-climate.org)) and IEA
  ([https://www.iea.org](https://www.iea.org)) cross-checked against
  the EEA Greenhouse Gas inventory.
- Forward trajectories (2025 → 2032) from BFE ES-2050 (Switzerland),
  NECP 2024 (Italy), and EEG 2023 (Germany) policy targets.

### Licence
ENTSO-E open licence (terms at
[https://www.entsoe.eu/data/transparency-platform/](https://www.entsoe.eu/data/transparency-platform/)).
Free for non-commercial research; attribution required.

---

## 3. ExaDigiT / RAPS reference-system catalogue

### Description
The Resource and Application Performance Simulator (RAPS) module of the
ExaDigiT framework provides the canonical configurations for thirteen
reference HPC and AI systems including Frontier, Marconi100, LUMI, Setonix,
Adastra, MareNostrum 5, Karolina, and several US DOE machines.

### Citations
- Brewer, W., et al. *ExaDigiT: An Open-Source Digital-Twin Framework for
  Liquid-Cooled Exascale Supercomputers.* SC24, 2024.
- Maiterth, M., et al. *ExaDigiT/RAPS for AI Cluster Simulation.* HPC
  workshop paper, 2025.

### How to obtain
1. Clone the public ExaDigiT/RAPS repository:
   ```bash
   git clone https://code.ornl.gov/exadigit/raps.git
   cd raps
   ```
2. Install (Python ≥3.10):
   ```bash
   pip install -e .
   ```
3. Reference-system configurations are under `raps/configs/` (13 systems).

### Licence
ExaDigiT/RAPS is open source under the BSD 3-Clause licence (verify the
upstream repository's `LICENSE` file before redistribution). Reference
configurations are released under CC-BY 4.0.

### How GridPilot uses it
GridPilot imports the RAPS configurations as the canonical system
parameters for the multi-scale projection. Specifically:
1. We extract per-node IT power, design PUE, and cooling-regime metadata.
2. We project per-node measurements from the V100 testbed (E1 sweep) into
   the RAPS-calibrated 13 reference systems.
3. We report the energy-residual cross-validation: 1.85% mean across the
   13 reference systems against published Marconi100 and Frontier
   facility-power records.

See [`EXADIGIT_RAPS_SETUP.md`](EXADIGIT_RAPS_SETUP.md) for installation
and integration details.

---

## 4. V100 EcoCloud measurement campaign (this work)

### Description
Hardware-level measurements collected on the EPFL EcoCloud
`ecocloud-exp06` node in April 2026:
- 3× NVIDIA Tesla V100-SXM2 32 GB GPUs
- 36 physical CPU cores / 72 logical threads
- 379 GiB usable RAM
- Ubuntu 24.04, CUDA/NVML telemetry
- `nvidia-smi`-based power-cap actuation

Seven scripted experiments (E1–E7) cover power-cap calibration, step
response, AR(4) predictor accuracy, closed-loop demand-following,
supervisory control, multi-GPU fairness, and end-to-end FFR latency.

### How to obtain
- The raw NVML telemetry CSVs, the seven experiment scripts, the analysis
  scripts, the safety-island artefacts (TLA+, C skeleton, simulator,
  protocol), and the `pytest` suite are included in this repository:
  - Raw measurements: [`data/v100_raw/`](../data/v100_raw/)
  - Experiment drivers: [`scripts/v100/experiments/`](../scripts/v100/experiments/)
  - Controller, workloads, calibration, projection, replot:
    [`scripts/v100/`](../scripts/v100/)
- A complete archive of the V100 campaign will additionally be deposited
  on Zenodo at publication (DOI to be assigned).
- The [`scripts/aggregate_v100_headlines.py`](../scripts/aggregate_v100_headlines.py)
  script reads the raw JSON summaries and reproduces the canonical
  headline-numerics CSV displayed in the paper Table 2.

### How to reproduce on your own V100 / A100 / H100 testbed
See [`V100_MEASUREMENT_PROTOCOL.md`](V100_MEASUREMENT_PROTOCOL.md) for the
step-by-step procedure that produces the calibration coefficients on your
hardware. The protocol is portable to any modern NVIDIA GPU with NVML
support; AMD MI300/MI325 ports are welcome via the workflow in
`CONTRIBUTING.md`.

### Licence
- Raw measurement data: CC-BY 4.0
- Experiment scripts: Apache 2.0 (per the upstream EcoCloud reproducibility
  policy)
- Headline numerics in this repo (CSVs under `data/`): CC-BY 4.0

---

## 5. Workload archetypes

### Description
Four workload archetypes calibrated from public traces:

| Archetype     | Source trace                              | Jobs   |
|---------------|-------------------------------------------|--------|
| matmul-bound  | M100 GPU-heavy CFD/MD subset              | 1,994  |
| inference     | Philly-like deep-learning serving trace   | 8,000  |
| bursty        | Acme-like LLM training trace              | 3,000  |
| steady-state  | M100 production-batch subset              | 1,994  |

### How to obtain
- M100 (matmul, steady-state): see Section 1 above.
- Philly-like (inference): Jeon et al. *Analysis of Large-Scale Multi-Tenant
  GPU Clusters for DNN Training Workloads.* USENIX ATC 2019.
- Acme-like (bursty): synthetic LLM-training trace generated by us with
  realistic compute-communication phase patterns; included as
  `benchmarks/acme_synthetic_3000.csv`.

### Licence
- M100 subset: CC-BY 4.0 (per CINECA).
- Philly trace: per the Philly authors' release terms (free for academic).
- Acme synthetic trace: CC-BY 4.0 (this work).

---

## Data integrity notes

The `data/` directory in this repository contains only the **headline
numerics** referenced in the paper's figures and tables (Table 1
multi-scale savings, CI trajectories, FFR participation, operational-only
baselines, Plackett-Burman sensitivity coefficients). It does not contain
the multi-gigabyte raw traces or the ENTSO-E hourly time series. To
re-derive figures from raw data, follow
[`REPRODUCING_FROM_RAW_DATA.md`](REPRODUCING_FROM_RAW_DATA.md).
