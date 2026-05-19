# Reproducibility Master Guide

This document is the single starting point for **reproducing every
artefact of the two Euro-Par 2026 Workshop papers** from a clean
checkout of the public release.  It threads together
`requirements.txt`, the `pytest` suite, `run_all_experiments.sh`, the
LaTeX build, and the per-stage protocols, in the order you would
execute them on a fresh remote machine.

If you only need the per-stage rerun commands, see
[`RUNBOOK.md`](RUNBOOK.md); if you need the claim-to-artefact map,
see [`COMPANION_PAPERS_MAP.md`](COMPANION_PAPERS_MAP.md); for
why the design is the way it is, see
[`DESIGN_RATIONALE.md`](DESIGN_RATIONALE.md).

---

## Table of contents

1. [System requirements](#1-system-requirements)
2. [Layout overview](#2-layout-overview)
3. [Stage A — install](#3-stage-a--install-2-minutes)
4. [Stage B — sanity check (tests)](#4-stage-b--sanity-check-tests-30-seconds)
5. [Stage C — end-to-end pipeline](#5-stage-c--end-to-end-pipeline-75-minutes)
6. [Stage D — build the two papers](#6-stage-d--build-the-two-papers-30-seconds)
7. [Stage E — verify against the published numbers](#7-stage-e--verify-against-the-published-numbers)
8. [Re-running a single stage](#8-re-running-a-single-stage)
9. [Stub vs real-data mode](#9-stub-vs-real-data-mode)
10. [Common failure modes](#10-common-failure-modes-and-how-to-recover)
11. [Going further (C2 follow-on)](#11-going-further-c2-follow-on)

---

## 1. System requirements

| Resource | Minimum | Recommended | Tested |
|---|---|---|---|
| CPU cores | 4 | 16 | 16-core Apple M-series, 16-core x86_64 |
| RAM | 8 GiB | 32 GiB | 64 GiB |
| Disk | 5 GiB | 20 GiB | 50 GiB |
| Python | 3.10 | 3.12 | 3.10, 3.11, 3.12, 3.13, 3.14 |
| OS | Linux x86_64, macOS arm64 | Linux x86_64 (server) | macOS arm64 (dev), Linux x86_64 (remote) |

Network access is **not** required for the basic pipeline.  Optional
features that need a network are clearly labelled in
[`DEPENDENCIES.md`](DEPENDENCIES.md) (ENTSO-E live fetcher, GitHub
clone, pip).

The V100 hardware-measurement campaign (E1–E7 in
`docs/V100_MEASUREMENT_PROTOCOL.md`) requires a 3× NVIDIA V100 SXM2
testbed with NVML and is **not** included in the basic pipeline; the
raw telemetry under `data/v100_raw/` is shipped with the release so
the WHPC paper's figures are reproducible without re-acquiring those
measurements.

## 2. Layout overview

```
EuroPar2026-GridPilot-Denisa/        (workspace root)
├── gridpilot/                       (public reproducibility kit; the
│   │                                 thing you would clone from
│   │                                 https://github.com/denisa-c/gridpilot)
│   ├── src/                          (importable Python library)
│   ├── scripts/                      (drivers; entry: run_all_experiments.sh)
│   ├── data/                         (bundled traces + V100 telemetry)
│   ├── configs/                      (grid CI YAMLs, RAPS systems,
│   │                                  network egress, workflows)
│   ├── tests/                        (pytest suite, ~5 s, 70 tests)
│   ├── docs/                         (the file you are reading is here)
│   ├── requirements.txt              (Python deps; see DEPENDENCIES.md)
│   ├── README.md
│   ├── LICENSE                       (MIT)
│   ├── CONTRIBUTING.md
│   └── LIMITATIONS.md
├── papers/
│   ├── pecs2026/                     (PECS paper, double-blind)
│   ├── whpc2026/                     (WHPC paper, attributed)
│   ├── europar2027-c2/               (C2 follow-on skeleton)
│   └── build.sh                      (LaTeX driver: pdflatex+bibtex)
└── _dev_archive/                     (planning docs; NOT in public release)
```

## 3. Stage A — install (2 minutes)

From a clean clone of the workspace root:

```bash
# Initialise the bundled RAPS submodule (the cooling-model anchor):
git submodule update --init --recursive

# Create and activate a virtualenv:
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip toolchain (recommended on Python 3.13+):
pip3 install --upgrade pip setuptools wheel

# Install dependencies:
pip3 install -r gridpilot/requirements.txt
```

The release works without the submodule because
`scripts/run_all_experiments.sh` falls back to
`gridpilot/configs/raps_systems/marconi100.yaml` when
`gridpilot/raps/config/marconi100.yaml` is missing.  Submodule
initialisation is still recommended for full traceability to the
ExaDigiT/RAPS upstream.

Every dependency, its purpose, and its version constraint is
catalogued in [`DEPENDENCIES.md`](DEPENDENCIES.md).

## 4. Stage B — sanity check (tests, 30 seconds)

```bash
PYTHONPATH=gridpilot/src pytest -q gridpilot/tests/
```

Expected output (last line):

```
70 passed in ~5 s
```

The suite covers, per file:

| File | Coverage |
|---|---|
| `test_fsla.py` | f-SLA Dirichlet prior, six-tier ladder, length conditioning, replay determinism, CLI round-trip |
| `test_gaming_mechanisms.py` | M0–M3 mechanisms, SWFs, Jain fairness index |
| `test_gridpilot_pue.py` | PUE-aware scheduler invariants |
| `test_raps_integration.py` | RAPS YAML adapter |
| `test_entsoe_connector.py` | ENTSO-E CI loader |
| `test_failure_modes.py` | scheduler error paths |
| `test_kit.py` | end-to-end CLI smoke tests |
| `test_spatial_routing.py` | C2: spatial clause, egress cost, M-Spatial audit (6 tests) |
| `test_workflow_dag.py` | C2: WorkflowDAG construction + realisation (6 tests) |
| `test_dag_mechanisms.py` | C2: M-Workflow KL-divergence audit (4 tests) |

If any test fails, **stop**.  The remaining stages depend on a
green test suite.

## 5. Stage C — end-to-end pipeline (75 minutes)

The single end-to-end entry point regenerates every figure and every
headline number macro that the two papers consume:

```bash
bash gridpilot/scripts/run_all_experiments.sh
```

What it does, step by step, with wall-clock budgets on a 16-core
workstation:

| Step | What runs | ~Time | Output |
|---|---|---|---|
| 0a | Extend M100 Jan trace with Feb 2022 (if `M100_ROOT` env var is set) | 1 min | `data/traces/m100_real_jobs_extended.parquet` |
| 0b | Fetch real hourly ENTSO-E CI (if `ENTSOE_API_KEY` env var is set) | 3 min | `data/ci/entsoe/*.parquet` |
| 1 | M100 policy-matrix replay (200 cells) | 26 min | `data/m100/policy_matrix/{policy_matrix.csv,HYPOTHESIS_OUTCOMES.json,RUN_MANIFEST.json}` |
| 2 | Multi-country sweep (1008 cells, 6 grids × 3 MW × 7 mechanisms × 8 seeds) | 30–45 min | `data/m100/country_sweep/{country_sweep.csv,COUNTRY_SUMMARY.csv,RUN_MANIFEST.json,cells/<cell-id>.json}` |
| 3a | Regenerate every paper figure | 30 s | `figs/fig_{cfe_by_tier,swf_comparison,fairness_pareto,latency_per_tier,country_cfe_lift,country_pue_aware}.pdf` |
| 3b | Render per-paper architecture figures | 10 s | `papers/{pecs2026,whpc2026}/figs/architecture*.pdf` |
| 4 | Extract macros (`extract_paper_macros.py`) + LaTeX builds | 30 s | `papers/{pecs2026,whpc2026}/figs/results.tex` + `papers/{pecs2026,whpc2026}/main.pdf` |

Progress is rendered as `[N/7] <step name>    (total elapsed mm:ss)`
banners with 30-second heartbeats on the two long-running steps.  The
full transcript is `tee`-ed to `gridpilot/logs/run_all_<UTC>.log`.

**Resumability.**  A step is treated as complete if its canonical
output AND a companion `RUN_MANIFEST.json` are both present on disk.
Killing the run and restarting it picks up where the prior run left
off; only step 2 (multi-country sweep) needs the per-cell `cells/`
directory to resume mid-step.  Set `FRESH=1` to force a rerun even of
completed steps.

**Environment-variable knobs:**

| Variable | Default | Purpose |
|---|---|---|
| (positional arg) | `full` | `full` = real replays; `stub` = literature-anchored seeders |
| `FRESH` | `0` | When `1`, rerun even completed steps |
| `FORCE` | `0` | Force `--force` on the replay drivers in stub mode |
| `ENTSOE_API_KEY` | unset | Enables step 0b (real ENTSO-E hourly CI) |
| `M100_ROOT` | `/Users/nisa/code/M100` | Enables step 0a (extended trace) |
| `WORKERS` | `4` | Pool size for the two replay drivers |
| `HEARTBEAT_SEC` | `30` | Heartbeat cadence in seconds |

## 6. Stage D — build the two papers (30 seconds)

The end-to-end pipeline already calls `papers/build.sh` as its
step 4, so a successful `run_all_experiments.sh` run produces both
PDFs.  To rebuild only the PDFs (e.g. after editing the body text):

```bash
./papers/build.sh         # both papers
./papers/build.sh pecs    # only PECS
./papers/build.sh whpc    # only WHPC
```

Targets: `stage` (figures only, no compile), `clean` (remove
`.aux/.log/.pdf` build artefacts), `distclean` (also remove staged
`figs/` dirs).

Each paper's `main.tex` inputs an auto-generated
`<paper>/figs/results.tex` macro file produced by
`scripts/figures/extract_paper_macros.py`.  Every headline number is
read from that file — there are no hard-coded numbers in the LaTeX
body text.  The macro file also carries a `\StubDataPresent` flag
that the body uses to render an honest "data-provenance" banner in
the PDF.

The two PDFs land at:

- `papers/whpc2026/main.pdf`
- `papers/pecs2026/main.pdf`

## 7. Stage E — verify against the published numbers

The complete claim-to-artefact map for both papers, with one-line
`jq`/`awk`/`python` verification commands for every headline number,
is in [`COMPANION_PAPERS_MAP.md`](COMPANION_PAPERS_MAP.md).

A reviewer can verify the paper-data correspondence by direct file
inspection without re-running anything; the verification commands
read the CSVs/JSONs the pipeline emits.

Examples (run from `gridpilot/`):

```bash
# WHPC E7 (FFR latency): median, max, pass count
jq '.median_ms, .max_ms, .pass_count, .total_trials' \
   data/v100_raw/E7_ffr_latency/verdict.json

# WHPC E3 (AR(4) MAE per workload):
for w in inference_memory_bound matmul_compute_bound bursty_alternating; do
   jq -r ".mae_W" data/v100_raw/E3_outer_loop/${w}_metrics.json
done

# PECS multi-country headline (CFE-lift by country):
head -1 data/m100/country_sweep/COUNTRY_SUMMARY.csv
awk -F, 'NR==1 || $1 ~ /^(SE|CH|FR|IT|DE|PL)$/' \
   data/m100/country_sweep/COUNTRY_SUMMARY.csv

# PECS policy-matrix hypothesis outcomes (H1..H5):
jq '.' data/m100/policy_matrix/HYPOTHESIS_OUTCOMES.json
```

## 8. Re-running a single stage

[`RUNBOOK.md`](RUNBOOK.md) has the canonical per-stage rerun
commands.  Short summary:

```bash
cd gridpilot

# Stubs only (fast, literature-anchored placeholders):
bash scripts/run_all_experiments.sh stub

# Just the policy matrix replay:
PYTHONPATH=src python scripts/m100/replay_policy_matrix.py \
    --jobs       data/traces/m100_real_jobs.parquet \
    --ci         configs/grids/DE.yaml \
    --pue        raps/config/marconi100.yaml \
    --policies   FCFS,EASY,SAF,RLBackfilling,GridPilot-PUE \
    --mechanisms none,M0,M1,M2,M3 \
    --seeds      8 --workers 4 \
    --output-dir data/m100/policy_matrix/

# Just the multi-country sweep:
PYTHONPATH=src python scripts/multicountry/replay_country_sweep.py \
    --jobs   data/traces/m100_real_jobs.parquet \
    --grids  configs/grids/SE.yaml,configs/grids/CH.yaml,...,configs/grids/PL.yaml \
    --pue-yaml raps/config/marconi100.yaml \
    --mw 1,10,50 --fsla-mechanisms none,M0,M1,M2,M3 \
    --pue-mechanisms none,GridPilot-PUE \
    --seeds 8 --workers 4 \
    --output-dir data/m100/country_sweep/

# Just the figure regeneration (after either of the above):
for f in fig_cfe_by_tier fig_swf_comparison fig_fairness_pareto fig_latency_per_tier; do
    PYTHONPATH=src python "scripts/figures/${f}.py" \
        --matrix data/m100/policy_matrix/policy_matrix.csv \
        --out "figs/${f}.pdf"
done

# Just the macro extractor (after any data update):
PYTHONPATH=src python scripts/figures/extract_paper_macros.py

# Just the PDF rebuild:
../papers/build.sh
```

## 9. Stub vs real-data mode

The release ships two parallel pipelines so reviewers without a
16-core workstation can still rebuild both PDFs.

**Stub mode** (`bash scripts/run_all_experiments.sh stub`, ~2 min)
runs literature-anchored seed scripts
(`scripts/m100/seed_policy_matrix_stub.py` and
`scripts/multicountry/seed_country_sweep_stub.py`) that produce
fixed-content CSVs at the same paths as the real replays.  The PDFs
carry a red "data-provenance" banner in their results sections
indicating that the displayed numbers come from a stub.

**Real-data mode** (`bash scripts/run_all_experiments.sh`, default;
~75 min) runs the real M100 trace through the dispatcher and
emits the same CSV paths.  The banner switches to a neutral "honest
reporting" colour.

The switch is driven by the boolean `\StubDataPresent` macro in each
paper's auto-generated `results.tex`; the extractor sets it based on
whether a `RUN_MANIFEST.json` exists alongside the CSV.

## 10. Common failure modes (and how to recover)

| Symptom | Cause | Fix |
|---|---|---|
| `pip install` errors on Python 3.13/3.14 | numpy 1.x has no wheels for newer Python | Use `pip install -U pip` first; the relaxed `numpy<3.0` constraint in `requirements.txt` lets pip pick numpy 2.x |
| `ImportError: No module named pyarrow` | pyarrow is required for parquet I/O | `pip install pyarrow>=14.0` (already in `requirements.txt`) |
| Step 2 stuck at 0/1008 cells for >30 min | Likely an O(N²) bug in `run_one_cell` (was fixed in v1.0.1) | Make sure you are on the current release; re-run with `FRESH=1` |
| `_pickle.PicklingError: Can't pickle local object` | A nested closure submitted to `ProcessPoolExecutor` (was fixed) | Make sure you are on the current release |
| Step 1 always re-runs (~26 min wasted) | An older release didn't write `RUN_MANIFEST.json` from `replay_policy_matrix.py` | Make sure you are on the current release; the manifest is now written |
| `NameError: name 'LIFT_LABEL' is not defined` in `fig_country_cfe_lift.py` | Missing `global LIFT_LABEL` (was fixed) | Make sure you are on the current release |
| `FileNotFoundError: configs/network/egress_emissions.yaml` | Spatial sweep run from the workspace root (default paths resolve against `gridpilot/`) | Make sure you are on the current release (default paths now anchored at the gridpilot root) |
| LaTeX `! Package graphics Error: File 'workloads.pdf' not found` | The workloads taxonomy figure was uploaded but not copied into the PECS figs/ folder | Drag-and-drop `workloads.pdf` into `papers/pecs2026/figs/` |
| `pkill` fails with "No such process" | Run completed; ignore | n/a |
| LaTeX warning: `\StubDataPresent` undefined | `results.tex` macros not regenerated | Run `PYTHONPATH=gridpilot/src python gridpilot/scripts/figures/extract_paper_macros.py` |

## 11. Going further (C2 follow-on)

The release includes scaffolding for the C2 follow-on paper (*Spatial
f-SLA and Workflow-Conditional Carbon-Aware Routing*).  See
[`C2_SPATIAL_AND_WORKFLOW.md`](C2_SPATIAL_AND_WORKFLOW.md) for the
spatial-routing driver, the workflow-DAG abstraction, the per-grid-pair
egress-emissions YAML, and the three new unit-test files.

The C2 paper's LaTeX skeleton lives at `papers/europar2027-c2/main.tex`
(placeholder body; the full P1–P5 plan is in
`_dev_archive/PAPER_C2_PLAN.md`).

---

**License:** Code MIT, data CC-BY 4.0.  Citation entries:
[`COMPANION_PAPERS_MAP.md`](COMPANION_PAPERS_MAP.md) §8.

**Questions or issues:** see [`CONTRIBUTING.md`](../CONTRIBUTING.md)
or contact the corresponding author (`denisa.constantinescu@epfl.ch`).
