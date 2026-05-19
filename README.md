# GridPilot — Grid-Responsive Control for AI Supercomputers (Euro-Par 2026)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Data: CC-BY 4.0](https://img.shields.io/badge/Data-CC--BY%204.0-lightblue.svg)](licenses/CC-BY-4.0.txt)

**Open reproducibility kit for two companion Euro-Par 2026 Workshop
papers** on flexible, grid-responsive AI/HPC supercomputers — one
on the upstream user-side contract (PECS), one on the downstream
sub-second actuation controller (WHPC).

## What this repository covers

GridPilot is the *downstream actuation layer*: a three-tier predictive
controller (per-GPU at 200 Hz, per-host at 1 Hz, per-cluster hourly)
plus an out-of-band safety-island bypass, validated on a real 3× NVIDIA
V100 SXM2 testbed.  It is paired with the *upstream contract*
(f-SLA): a five-tier ladder (T0 rigid, T1 hour, T2 day, T3 week, T4
elastic burst) under which job submitters declare deferrability and
elasticity in exchange for proportional service credits, evaluated on
the Marconi100 (M100) production trace against six European grids.

The two papers are:

| Paper | Folder | Focus |
|---|---|---|
| WHPC 2026 | `papers/whpc2026/` | GridPilot controller (attributed) |
| PECS 2026 | `papers/pecs2026/` | f-SLA contract (double-blind) |

Together they form a cross-layer flexibility programme: user-side
incentives elicit flexibility (PECS) that the platform-level
controller can dispatch deterministically at the facility meter
(WHPC).



## Headline results

These are auto-extracted from on-disk experiment outputs into
`papers/{whpc,pecs}2026/figs/results.tex` by
`scripts/figures/extract_paper_macros.py` — there are no hard-coded
numbers in the LaTeX body text.  The current real measurements are:

- **WHPC E7 (FFR latency on V100):** ~97 ms median end-to-end response
  across 90 trials (max ≤ 102 ms), ~7× faster than the 700 ms Nordic
  FFR budget.  90/90 trials pass.
- **WHPC E1 (power-cap calibration):** best-efficiency operating point
  $p_{\text{cap}}=150$ W, $f_{\text{sm}}=945$ MHz, within ±5 % on
  iterations-per-joule across matmul / inference / bursty.  Per-workload
  power model LOOCV MAE 3.45 %; 980-node scaling envelope matches the
  published Marconi100 facility-power reference within +1.4 %.
- **WHPC E3 (AR(4) predictor MAE):** ~4.7 W (inference), ~7.0 W (matmul),
  ~19.7 W (bursty) on the V100 testbed.
- **WHPC E8 (PUE-aware controller sweep):** 50 MW cooling-overhead drag
  closed across six European grids is 2.5–5.8 pp; envelope is widest on
  low-CI grids.
- **PECS multi-country sweep:** the f-SLA contract measurably shifts
  both CFE share and energy-weighted effective grid CI on the M100
  trace; the relative lift is largest on the cleanest grids (SE, CH,
  FR) and the largest absolute avoided tonnage is on the dirtiest
  (PL, DE).  

## Quick start

```bash
# From the workspace root (one level above gridpilot/):
git submodule update --init --recursive
python3 -m venv .venv && source .venv/bin/activate
pip3 install --upgrade pip setuptools wheel
pip3 install -r gridpilot/requirements.txt
PYTHONPATH=gridpilot/src pytest -q gridpilot/tests/   # expect 54 passed
bash gridpilot/scripts/run_all_experiments.sh
```

Dependency files used by this repository:

- `requirements.txt` (main GridPilot dependencies; required)
- `raps/api_client/requirements.txt` (optional; only if you use RAPS API client code)
- `raps/pyproject.toml` (optional; only if you develop/run the RAPS package itself)

If you work directly inside `gridpilot/`, use:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip3 install --upgrade pip setuptools wheel
pip3 install -r requirements.txt
```


All subsequent commands assume the virtual environment is active.
The single most useful entry point is:

```bash
bash scripts/run_all_experiments.sh
```

This runs the M100 policy-matrix replay, the multi-country sweep,
regenerates every figure, extracts the headline-number macros, and
rebuilds both PDFs.  Wall time on a 16-core / 64 GB workstation is
~75 minutes.  For a fast paper rebuild from literature-anchored stub
data, append `stub`:

```bash
bash scripts/run_all_experiments.sh stub          # ~2 minutes
```

For a step-by-step description of every stage (including how to
re-run a single stage), see [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Repository structure

```
gridpilot/
├── README.md                    ← this file
├── LICENSE                      ← MIT (code, scripts, configs)
├── CONTRIBUTING.md              ← how to extend the framework
├── LIMITATIONS.md               ← scope caveats and lessons learned
├── requirements.txt             ← Python environment specification
├── .gitignore
├── src/                         ← controller + scheduler library
│   ├── controller/              ← Tier-1/2/3 PID/AR(4)/cluster controllers
│   ├── cooling/                 ← four-component PUE model
│   ├── scheduler/               ← f-SLA ladder, M0–M3 mechanisms, dispatcher
│   └── integration/             ← RAPS adapter + ENTSO-E connector
├── scripts/                     ← all run scripts (entry: run_all_experiments.sh)
│   ├── run_all_experiments.sh   ← single end-to-end command
│   ├── m100/                    ← M100 trace ETL, replays, ENTSO-E fetcher
│   ├── multicountry/            ← multi-country sweep driver + stub seeder
│   ├── v100/experiments/        ← V100 hardware-experiment drivers (E1–E7)
│   └── figures/                 ← figure scripts (read CSVs → PDFs)
├── data/                        ← bundled traces + telemetry (CC-BY 4.0)
│   ├── traces/m100_real_jobs.parquet
│   ├── m100/{policy_matrix,country_sweep}/   ← outputs of the replay drivers
│   └── v100_raw/                ← raw V100 measurement campaign telemetry
├── configs/                     ← YAML configurations
│   ├── grids/{SE,CH,FR,IT,DE,PL}.yaml    ← per-country CI configs
│   └── raps_systems/marconi100.yaml      ← tracked fallback PUE anchor
├── raps/                        ← bundled ExaDigiT/RAPS submodule (read-only)
│   └── config/marconi100.yaml   ← cooling-model calibration anchor
├── figs/                        ← rendered figure PDFs (auto-generated)
├── docs/                        ← protocols + reproducibility documentation
│   ├── RUNBOOK.md               ← step-by-step rerun guide
│   ├── ARCHITECTURE.md          ← three-tier controller details
│   ├── DATASETS.md              ← M100, ENTSO-E, RAPS dataset descriptions
│   ├── V100_MEASUREMENT_PROTOCOL.md ← V100 campaign protocol
│   ├── FSLA_PROTOCOL.md         ← f-SLA contract specification
│   ├── COMPANION_PAPERS_MAP.md  ← claim → script → artefact map
│   └── COUNTRY_SWEEP_PROTOCOL.md, POLICY_MATRIX_PROTOCOL.md
├── tests/                       ← pytest suite (~30 s; 48 tests)
└── licenses/                    ← third-party data licence acknowledgements

```

## RAPS integration

The release bundles a copy of the ExaDigiT/RAPS repository under
`raps/` and consumes its canonical system configurations at
`raps/config/<system>.yaml`.  For remote clones where the submodule is
not initialized, `scripts/run_all_experiments.sh` falls back to
`configs/raps_systems/marconi100.yaml` for the Marconi100 PUE anchor.
This is a **lightweight integration
mode**: we read RAPS configs to extract per-node power, node counts,
cooling efficiency, and country code, but we do **not** run the RAPS
simulation engine.

The bridge is `src/integration/raps_config_adapter.py`, which parses
any RAPS system YAML into a `RAPSSystemConfig` dataclass.  Two
calibration cross-checks ship under `scripts/raps_adapter/`:

```bash
# Run from the gridpilot/ directory with the project's virtualenv active.
python3 scripts/raps_adapter/m100_calibration_check.py
python3 scripts/raps_adapter/frontier_calibration_check.py

# If you are one level above (workspace root), use:
python3 gridpilot/scripts/raps_adapter/m100_calibration_check.py
python3 gridpilot/scripts/raps_adapter/frontier_calibration_check.py
```

Both emit JSON reporting the parsed geometry, per-node max power,
calibrated PUE, and the structural gap percentage against the RAPS
scalar `cooling_efficiency`.  The Marconi100 cross-check reports a
~12 % structural gap (the four-component PUE model is calibrated to
the published anchor PUE 1.20 rather than the RAPS scalar cooling
efficiency 0.945); Frontier matches within ±2 %.

## Tests

```bash
PYTHONPATH=src pytest -q
```

48 tests in total, covering: f-SLA tier ladder + Dirichlet prior,
M0–M3 anti-gaming mechanisms + SWFs + Jain, PUE-aware scheduler
invariants, RAPS YAML adapter, ENTSO-E CI loader, scheduler error
paths, CLI round-trip.  All tests pass without network access in
under 30 seconds.

## Claim → script → artefact map

The complete claim-to-artefact map for both companion papers, with
one-line `jq` / `awk` / `python` verification commands for every
headline number, is in
[`docs/COMPANION_PAPERS_MAP.md`](docs/COMPANION_PAPERS_MAP.md).
A reviewer can verify the paper–data correspondence by direct file
comparison without re-running anything.

## Reproducing the V100 controller-side measurements

The V100 hardware E1–E7 campaign is *not* re-runnable from this kit
alone — it requires the EPFL EcoCloud `ecocloud-exp06` testbed (or a
comparable 3× V100 SXM2 testbed with NVML).  The raw 100 Hz NVML
telemetry is shipped under `data/v100_raw/` (CC-BY 4.0); for a fresh
measurement, follow
[`docs/V100_MEASUREMENT_PROTOCOL.md`](docs/V100_MEASUREMENT_PROTOCOL.md)
(≤ 48 GPU-hours on the same testbed class).

## Limitations and lessons learned

We document scope caveats explicitly so reviewers and reproducers can
calibrate expectations.  See
[`LIMITATIONS.md`](LIMITATIONS.md) for the full discussion; four
lessons summarised:

1. The 5 % closed-loop tracking threshold (E4) is a cascade-composition
   diagnostic, not a failure mode — the bursty 11.08 % residual is
   what the Tier-2 host predictor absorbs.
2. The ~97 ms FFR latency (E7) is reproducible only with the
   deterministic safety-island bypass — Python-only implementations
   show p99 > 250 ms.
3. Facility-meter accounting is the binding correctness criterion: a
   controller that ignores the four-component PUE under-delivers at the
   meter by 4–7 pp.
4. Deferral alone is not enough on a small, lightly-loaded trace
   like the bundled M100 month — the literature-grounded T4 elastic-
   burst tier (CarbonScaler), spatial routing (GAIA), and price-
   proportional credits (Lechowicz) are the three SOTA-grounded
   extensions the kit ships or designs.

## Citing

Two papers are in submission for Euro-Par 2026 Workshops; cite the
companion most relevant to your use:

```bibtex
@inproceedings{constantinescu2026gridpilot,
  title     = {{GridPilot}: Real-Time Grid-Responsive Control for {AI} Supercomputers},
  author    = {Constantinescu, Denisa-Andreea and Atienza, David},
  booktitle = {Euro-Par 2026 Workshops --- Women in HPC (WHPC) Session},
  year      = {2026},
  publisher = {Springer LNCS},
  note      = {Companion paper to ``f-SLA: A User-Side Contract for
                Truthful Workload Flexibility towards Carbon-Free
                Supercomputing''}
}

@inproceedings{anonymous2026fsla,
  title     = {{f-SLA}: A User-Side Contract for Truthful Workload Flexibility
               towards Carbon-Free Supercomputing},
  author    = {Anonymous},
  booktitle = {Euro-Par 2026 Workshops --- Performance and Energy-efficient
               Computing Systems (PECS)},
  year      = {2026},
  publisher = {Springer LNCS},
  note      = {Double-blind submission; authorship restored at camera-ready}
}
```

## Acknowledgements

This work has been partially supported by the EPFL Solutions 4 Sustainability program ‘‘HeatingBits: renewable-supplied data centers integrating heating and cooling supply of local districts’’ and the UrbanTwin project (ETH Board Joint Initiatives for the Strategic Area Energy, Climate and Environmental Sustainability, and the Strategic Area Engagement and Dialogue with Society).
The authors also thank the EcoCloud center of EPFL, in particular Dr. Xavier Ouvrard, for providing access to the V100 server node.

## Licence

- **Code (scripts, configs):** [MIT](LICENSE)
- **Figures and data:** [CC-BY 4.0](licenses/CC-BY-4.0.txt)
- **Papers:** subject to the Euro-Par 2026 Workshops publication agreement
- **Third-party data** (M100 PM100, ENTSO-E A75, RAPS configurations):
  see [`licenses/THIRD_PARTY.md`](licenses/THIRD_PARTY.md).

## Contact

For questions, issues, and contributions: see
[`CONTRIBUTING.md`](CONTRIBUTING.md) or email
`denisa.constantinescu@epfl.ch`.
