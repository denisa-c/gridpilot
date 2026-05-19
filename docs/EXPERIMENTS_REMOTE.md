# Running every experiment from scratch on a remote machine

This file is the **canonical end-to-end recipe** for reproducing every
experimental artefact behind both companion Euro-Par 2026 Workshop
papers (PECS f-SLA + WHPC GridPilot) on a fresh remote machine.

It covers, in order:

0. [Prerequisites](#0-prerequisites)
1. [Clone and bootstrap](#1-clone-and-bootstrap-3-min)
2. [Optional inputs (extended trace, real ENTSO-E CI)](#2-optional-inputs)
3. [Sanity tests](#3-sanity-tests-30-s)
4. [Phase 1 — headline pipeline (~75 min)](#4-phase-1--headline-pipeline-75-min)
5. [Phase 2 — ablation sweeps (~55 min)](#5-phase-2--ablation-sweeps-55-min)
6. [Phase 3 — V100 hardware campaign (optional, ~48 GPU-h)](#6-phase-3--v100-hardware-campaign-optional-48-gpu-h)
7. [Phase 4 — extract macros + build the two PDFs (~1 min)](#7-phase-4--extract-macros--build-the-two-pdfs-1-min)
8. [Copy results back from the remote machine](#8-copy-results-back-from-the-remote-machine)
9. [Verification commands](#9-verification-commands)
10. [Troubleshooting](#10-troubleshooting)

Wall-clock budget on a 16-core / 64 GB workstation, *without* the V100
hardware campaign (which requires its own testbed):

| Phase | What runs                                                                       | ~Time     | Required?          |
| ----- | ------------------------------------------------------------------------------- | --------- | ------------------ |
| 0 + 1 | Clone, bootstrap, install dependencies                                          | ~3 min    | yes                |
| 2 (a) | Optional: extended Jan+Feb 2022 M100 trace                                      | ~1 min    | optional           |
| 2 (b) | Optional: real ENTSO-E hourly CI                                                | ~3 min    | optional           |
| 3     | Pytest sanity (70 tests)                                                        | ~30 s     | yes                |
| 4     | Policy matrix (200 cells) + multi-country sweep (1008 cells) + figures + papers | ~75 min   | yes                |
| 5 (a) | Per-tier contribution sweep (864 cells)                                         | ~35 min   | for paper figure 3 |
| 5 (b) | Contract-hyperparameter sensitivity sweep (576 cells)                           | ~20 min   | for paper figure 3 |
| 6     | V100 hardware E1–E7 (separate testbed)                                         | ~48 GPU-h | for WHPC body      |
| 7     | Extract macros + rebuild PECS + WHPC PDFs                                       | ~1 min    | yes                |

**Total**: ~75 min headline + ~55 min ablations = **~2 h 10 min** for a
complete from-scratch run on the M100 simulated side.  V100 hardware
experiments are independent.

For per-stage rerun commands (e.g. just step 4 of the headline
pipeline), see [`gridpilot/docs/RUNBOOK.md`](gridpilot/docs/RUNBOOK.md).

For the design rationale behind each sweep, see
[`gridpilot/docs/RATIONALE.md`](gridpilot/docs/RATIONALE.md) and the
per-sweep protocols
([`COUNTRY_SWEEP_PROTOCOL.md`](gridpilot/docs/COUNTRY_SWEEP_PROTOCOL.md),
[`POLICY_MATRIX_PROTOCOL.md`](gridpilot/docs/POLICY_MATRIX_PROTOCOL.md),
[`TIER_AND_HYPER_SWEEPS.md`](gridpilot/docs/TIER_AND_HYPER_SWEEPS.md)).

---

## 0. Prerequisites

**Hardware:**

- 16 cores / 32 GiB RAM minimum for the simulated pipeline; the
  parallel workers are configured for 4 by default and scale linearly
  to 16+ on a beefier machine.
- ~10 GiB free disk space (the bundled M100 trace + V100 telemetry
  + new sweep outputs).

**Software:**

- `git` 2.30+ (for submodule init)
- `python3` 3.10 or newer (tested up to 3.14; see
  [`gridpilot/docs/DEPENDENCIES.md`](gridpilot/docs/DEPENDENCIES.md))
- `bash` 4+, `awk`, `jq` (for verification commands)
- A working LaTeX distribution with the LNCS class
  (`splncs04.bst`, `llncs.cls`) and `pdflatex` + `bibtex` for the
  paper builds.  A minimal `texlive-base + texlive-latex-recommended + texlive-fonts-recommended + texlive-bibtex-extra` install is
  sufficient.

**Network:** required only for `git clone`, `pip install`, and the
optional ENTSO-E live-CI fetcher.  None of the simulated pipeline
needs network during a run.

**Optional:**

- The full Marconi100 dataset (`M100_ROOT`) for the **extended Jan+Feb
  2022 trace**.  Without it the kit uses the bundled January-only
  trace (1 994 jobs, also called `m100_real_jobs.parquet`).
- An **ENTSO-E Transparency Platform** API token
  (`ENTSOE_API_KEY`).  Without it the kit synthesises hourly CI from
  the 2020–2024 diurnal envelopes per country.

---

## 1. Clone and bootstrap (~3 min)

```bash
# 1.1 Clone the public repo (or copy the EuroPar2026-GridPilot
# folder from your local workstation):
git clone https://github.com/denisa-c/gridpilot.git EuroPar2026-GridPilot
cd EuroPar2026-GridPilot
# 1.2 Pull the RAPS submodule (cooling-model anchor):
git submodule update --init --recursive

# 1.3 Create + activate a virtualenv:
python3 -m venv .venv
source .venv/bin/activate

# 1.4 Upgrade pip toolchain (recommended on Python 3.13+):
pip3 install --upgrade pip setuptools wheel

# 1.5 Install dependencies:
pip3 install -r gridpilot/requirements.txt
```

Every dependency, what it does, and the version constraint is
documented in [`gridpilot/docs/DEPENDENCIES.md`](gridpilot/docs/DEPENDENCIES.md).

---

## 2. Optional inputs

### 2 (a). Extended Jan+Feb 2022 M100 trace

If you have access to the full Marconi100 dataset
(`https://gitlab.com/ecs-lab/exadata`), point the kit at it via
`M100_ROOT` and step 0a of `run_all_experiments.sh` will build a
`m100_real_jobs_extended.parquet` (Jan + Feb concatenated):

```bash
export M100_ROOT=/path/to/your/M100/dump
```

If you do **not** set `M100_ROOT`, the kit uses the bundled
`gridpilot/data/traces/m100_real_jobs.parquet` (January 2022 only),
which is enough to reproduce the paper's findings.

### 2 (b). Real ENTSO-E hourly CI

If you have an ENTSO-E API token, export it and step 0b will fetch
real hourly CI for the six European grids (SE, CH, FR, IT, DE, PL):

```bash
export ENTSOE_API_KEY=<your-token>
```

The fetcher uses the A75 endpoint (*Actual Generation per Production
Type*) and the IPCC AR5 lifecycle emission factors to compute hourly
g CO\textsubscript{2}eq/kWh per zone.  Without the token the kit
synthesises hourly CI from the 2020–2024 ENTSO-E diurnal envelopes
(\pm 10% SE through \pm 35% DE).

---

## 3. Sanity tests (~30 s)

```bash
PYTHONPATH=gridpilot/src pytest -q gridpilot/tests/
# expect: 70 passed in ~5 s
```

If anything fails, **stop** — the remaining phases depend on a green
test suite.  Common causes are listed in
[`gridpilot/docs/REPRODUCIBILITY.md#10-common-failure-modes-and-how-to-recover`](gridpilot/docs/REPRODUCIBILITY.md).

---

## 4. Phase 1 — headline pipeline (~75 min)

The single end-to-end driver runs steps 0a, 0b, 1, 2, 3a, 3b, 4 in
sequence:

```bash
bash gridpilot/scripts/run_all_experiments.sh
```

What it does:

| Step | Stage                                                            | Output                                                                                                               |
| ---- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 0a   | Build extended Jan+Feb 2022 trace (only if `M100_ROOT` is set) | `gridpilot/data/traces/m100_real_jobs_extended.parquet`                                                            |
| 0b   | Fetch real ENTSO-E hourly CI (only if `ENTSOE_API_KEY` is set) | `gridpilot/data/ci/entsoe/*.parquet`                                                                               |
| 1    | M100 policy-matrix replay (200 cells; ~26 min)                   | `gridpilot/data/m100/policy_matrix/{policy_matrix.csv,HYPOTHESIS_OUTCOMES.json,RUN_MANIFEST.json}`                 |
| 2    | Multi-country sweep (1008 cells; ~30–45 min)                    | `gridpilot/data/m100/country_sweep/{country_sweep.csv,COUNTRY_SUMMARY.csv,RUN_MANIFEST.json,cells/<cell-id>.json}` |
| 3a   | Regenerate every paper figure                                    | `gridpilot/figs/fig_*.pdf`                                                                                         |
| 3b   | Render per-paper architecture figures                            | `papers/{pecs2026,whpc2026}/figs/architecture*.pdf`                                                                |
| 4    | Extract macros + rebuild both PDFs                               | `papers/{pecs2026,whpc2026}/{figs/results.tex,main.pdf}`                                                           |

The script prints a stepwise `[N/7]` progress bar with 30 s
heartbeats on the two long-running replays (step 1 and step 2).
The whole transcript is `tee`'d to
`gridpilot/logs/run_all_<UTC-stamp>.log` so you can `tail -f` from
another terminal.

**Resumability**: a step is treated as complete if its canonical
artefact AND a companion `RUN_MANIFEST.json` are both present on
disk; killed-and-restarted runs pick up where the prior run left
off.  Step 2 additionally checkpoints every cell to
`cells/<cell-id>.json` so a mid-step kill doesn't lose work.

Knobs:

| Env var            | Default                 | Purpose                                                                  |
| ------------------ | ----------------------- | ------------------------------------------------------------------------ |
| (positional)       | `full`                | `full` = real replays; `stub` = literature-anchored seeders (~2 min) |
| `FRESH`          | `0`                   | When `1`, rerun even completed steps                                   |
| `FORCE`          | `0`                   | Force `--force` on the replay drivers in stub mode                     |
| `ENTSOE_API_KEY` | unset                   | Enables step 0b                                                          |
| `M100_ROOT`      | `/Users/.../.../M100` | Enables step 0a                                                          |
| `WORKERS`        | `4`                   | Pool size for the two replay drivers (bump on big machines)              |
| `HEARTBEAT_SEC`  | `30`                  | Heartbeat cadence                                                        |

---

## 5. Phase 2 — ablation sweeps (~55 min)

The two ablation sweeps complement the headline; they explain
*where* the lift comes from (per-tier breakdown) and *how sensitive*
the lift is to the contract's design knobs.

### 5 (a). Per-tier contribution sweep (~35 min)

864 cells: 6 grids × 3 MW × 6 tiers (T0..T5) × 8 seeds.

```bash
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/multicountry/replay_single_tier_sweep.py \
    --jobs gridpilot/data/traces/m100_real_jobs.parquet \
    --grids SE,CH,FR,IT,DE,PL \
    --mw 1,10,50 \
    --tiers 0,1,2,3,4,5 \
    --seeds 8 \
    --workers 4 \
    --output-dir gridpilot/data/m100/tier_sweep/ \
    --force
```

Outputs:

- `gridpilot/data/m100/tier_sweep/tier_sweep.csv` (one row per cell)
- `gridpilot/data/m100/tier_sweep/TIER_SUMMARY.csv` (means per tier)
- `gridpilot/data/m100/tier_sweep/RUN_MANIFEST.json` (provenance)

### 5 (b). Contract-hyperparameter sensitivity sweep (~20 min)

576 cells: 12 hyperparameter settings × 6 grids × 1 MW (10 MW) ×
8 seeds.

```bash
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/multicountry/replay_hyperparameter_sweep.py \
    --jobs gridpilot/data/traces/m100_real_jobs.parquet \
    --grids SE,CH,FR,IT,DE,PL \
    --mw 10 \
    --seeds 8 \
    --workers 4 \
    --output-dir gridpilot/data/m100/hyper_sweep/ \
    --force
```

Outputs:

- `gridpilot/data/m100/hyper_sweep/hyper_sweep.csv`
- `gridpilot/data/m100/hyper_sweep/HYPER_SUMMARY.csv`
- `gridpilot/data/m100/hyper_sweep/RUN_MANIFEST.json`

Hyperparameters swept (one-at-a-time around the defaults):

| Hyperparameter                              | Default | Sweep values       |
| ------------------------------------------- | ------- | ------------------ |
| `alpha_scale` (credit-schedule scale)     | 1.0     | 0.5, 1.0, 2.0, 4.0 |
| `window_scale` (deferral-window scale)    | 1.0     | 0.5, 1.0, 2.0      |
| `t4_envelope_scale` (T4 replica envelope) | 1.0     | 1.0, 2.0           |
| `short_job_s` (short-job threshold, s)    | 60      | 1, 60, 300         |

### 5 (c). Composed 2×2 figure (~5 s)

The figure consumes both summary CSVs and renders even if only one
is present (missing panels show "(awaiting sweep run)"):

```bash
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/figures/fig_tier_and_hyper.py \
    --tier-summary  gridpilot/data/m100/tier_sweep/TIER_SUMMARY.csv \
    --hyper-summary gridpilot/data/m100/hyper_sweep/HYPER_SUMMARY.csv \
    --mw-focus 10 \
    --out gridpilot/figs/fig_tier_and_hyper.pdf
```

Output: `gridpilot/figs/fig_tier_and_hyper.pdf` (2×2 panel composite;
imported by `papers/pecs2026/main.tex` as Fig.~`tier_and_hyper`).

For the protocol and what each panel shows, see
[`gridpilot/docs/TIER_AND_HYPER_SWEEPS.md`](gridpilot/docs/TIER_AND_HYPER_SWEEPS.md).

### 5 (d). Optional — spatial-routing sweep (C2 follow-on; ~30 s)

If you also want to surface the v0.1 spatial-routing scaffolding
that ships in v1.0 of the kit (for the C2 follow-on paper):

```bash
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/multicountry/replay_spatial_sweep.py \
    --jobs gridpilot/data/traces/m100_real_jobs.parquet \
    --output-dir gridpilot/data/m100/spatial_sweep/ \
    --force
```

Outputs `spatial_sweep.csv` with per-grid destination counts per
egress-cost regime.  Not consumed by either paper; useful for the
follow-on.  See
[`gridpilot/docs/C2_SPATIAL_AND_WORKFLOW.md`](gridpilot/docs/C2_SPATIAL_AND_WORKFLOW.md).

---

## 6. Phase 3 — V100 hardware campaign (optional, ~48 GPU-h)

The WHPC paper's headline numbers (FFR latency, AR(4) MAE, power-cap
calibration) require a **real 3× NVIDIA V100 SXM2 testbed with NVML**.
This is independent of the simulated M100 pipeline above.

The released kit ships the raw 100 Hz telemetry from the EPFL
EcoCloud campaign under `gridpilot/data/v100_raw/` so the WHPC
paper's figures and headline-number macros are reproducible WITHOUT
re-acquiring the measurements.  Skip this phase unless you want to
re-run the campaign on a comparable testbed.

If you do want to re-run, the full procedure is in
[`gridpilot/docs/V100_MEASUREMENT_PROTOCOL.md`](gridpilot/docs/V100_MEASUREMENT_PROTOCOL.md).
Short version (run on the V100 testbed):

```bash
cd gridpilot
PYTHONPATH=src python scripts/v100/experiments/run_e1_powercap_sweep.py
PYTHONPATH=src python scripts/v100/experiments/run_e2_step_response.py
PYTHONPATH=src python scripts/v100/experiments/run_e3_ar4_accuracy.py
PYTHONPATH=src python scripts/v100/experiments/run_e4_demand_following.py
PYTHONPATH=src python scripts/v100/experiments/run_e7_ffr_latency.py
```

Raw outputs land in `data/v100_raw/`; the headline table at
`data/v100_raw/headline_table.csv` is what the WHPC paper cites.

---

## 7. Phase 4 — extract macros + build the two PDFs (~1 min)

After the new CSVs land (Phase 1 + Phase 2 + optional Phase 3),
re-extract the LaTeX macro file so the body picks up the new
headline numbers:

```bash
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/figures/extract_paper_macros.py
```

This writes `papers/pecs2026/figs/results.tex` and
`papers/whpc2026/figs/results.tex` (the WHPC equivalent).  Every
quantitative claim in both papers is a `\Pecs...` or `\Whpc...`
macro read from these files — there are no hard-coded numbers in
the LaTeX body.

The macro file also sets `\StubDataPresent` to `true` if the
`RUN_MANIFEST.json` is missing (signalling stub data) and `false`
otherwise.  The papers render a coloured "data provenance" banner
based on this flag (red banner = stub; neutral grey banner =
real-data).

Then rebuild the two PDFs:

```bash
bash papers/build.sh             # both papers
bash papers/build.sh pecs        # only PECS
bash papers/build.sh whpc        # only WHPC
```

Targets: `stage` (figures only, no compile), `clean` (remove
`.aux/.log/.pdf` build artefacts), `distclean` (also remove staged
`figs/` dirs).

Output: `papers/pecs2026/main.pdf`, `papers/whpc2026/main.pdf`.

---

## 8. Copy results back from the remote machine

The minimum bundle to copy back to your local workstation so the
papers render with the new headline numbers:

```
papers/pecs2026/figs/results.tex            # PECS macros
papers/whpc2026/figs/results.tex            # WHPC macros
papers/pecs2026/main.pdf                    # rendered PECS
papers/whpc2026/main.pdf                    # rendered WHPC
gridpilot/data/m100/policy_matrix/          # M0..M3 sweep
gridpilot/data/m100/country_sweep/          # multi-country sweep
gridpilot/data/m100/tier_sweep/             # per-tier sweep
gridpilot/data/m100/hyper_sweep/            # hyperparameter sweep
gridpilot/figs/                             # rendered paper figures
```

On the remote machine, archive:

```bash
tar czf /tmp/gridpilot_full_run.tar.gz \
    papers/pecs2026/figs/results.tex \
    papers/whpc2026/figs/results.tex \
    papers/pecs2026/main.pdf \
    papers/whpc2026/main.pdf \
    gridpilot/data/m100/policy_matrix \
    gridpilot/data/m100/country_sweep \
    gridpilot/data/m100/tier_sweep \
    gridpilot/data/m100/hyper_sweep \
    gridpilot/figs
```

From your local workstation:

```bash
scp <user>@<remote>:/tmp/gridpilot_full_run.tar.gz /tmp/
cd /Users/<you>/path/to/EuroPar2026-GridPilot
tar xzf /tmp/gridpilot_full_run.tar.gz
```

---

## 9. Verification commands

A handful of one-liners that confirm each phase produced the
expected outputs:

```bash
# Tests:
PYTHONPATH=gridpilot/src pytest -q gridpilot/tests/
# expect: 70 passed in ~5 s

# Phase 1 (headline):
jq '.wall_time_s, .n_cells' \
   gridpilot/data/m100/policy_matrix/RUN_MANIFEST.json
# expect: ~1500-2500 s, 200

jq '.wall_time_s, .n_cells // .' \
   gridpilot/data/m100/country_sweep/RUN_MANIFEST.json
# expect: ~1800-3000 s, ~1008

awk -F, 'NR==1' gridpilot/data/m100/country_sweep/COUNTRY_SUMMARY.csv
# expect: country,mw,layer,mechanism,cfe_pct_mean,cfe_lift_pp_mean,
#         cfe_abs_pct_mean,cfe_abs_lift_pp_mean,ci_weighted_mean_g,
#         ci_weighted_lift_g_mean,co2_avoided_t_y_mean,
#         delta_facility_pp_mean,jain_mean,p95_mean

# Phase 2 (ablations):
jq '.wall_time_s, .n_cells' \
   gridpilot/data/m100/tier_sweep/RUN_MANIFEST.json
# expect: ~1800-2400 s, 864

jq '.wall_time_s, .n_cells' \
   gridpilot/data/m100/hyper_sweep/RUN_MANIFEST.json
# expect: ~900-1200 s, 576

ls -la gridpilot/figs/fig_tier_and_hyper.pdf
# expect: ~30-100 KB

# Phase 4 (macros + papers):
grep -E "StubDataPresent|PecsCfeLift|WhpcMed" \
     papers/pecs2026/figs/results.tex \
     papers/whpc2026/figs/results.tex | head -20
# expect: \StubDataPresent = false on both files; non-? numeric values

ls -la papers/pecs2026/main.pdf papers/whpc2026/main.pdf
# expect: both ~1-2 MB
```

The complete claim-to-artefact verification map (one-line `jq` /
`awk` command per headline number in both papers) is in
[`gridpilot/docs/COMPANION_PAPERS_MAP.md`](gridpilot/docs/COMPANION_PAPERS_MAP.md).

---

## 10. Troubleshooting

| Symptom                                                                        | Cause                                                                                   | Fix                                                                                                                                                                                            |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pip install` fails on Python 3.13/3.14                                      | numpy 1.x has no wheels for newer Python                                                | `pip install -U pip` first; the relaxed `numpy<3.0` constraint lets pip pick numpy 2.x                                                                                                     |
| `ImportError: No module named pyarrow`                                       | pyarrow is required for parquet I/O                                                     | `pip install pyarrow>=14.0` (already in `requirements.txt`)                                                                                                                                |
| Step 2 stuck at 0/1008 cells for >30 min                                       | Older release with an O(N²) bug in `run_one_cell`                                    | Make sure you are on the current release; the bug is fixed                                                                                                                                     |
| `_pickle.PicklingError: Can't pickle local object`                           | A nested closure submitted to `ProcessPoolExecutor` (was fixed)                       | Make sure you are on the current release                                                                                                                                                       |
| Step 1 always re-runs (~26 min wasted on rerun)                                | Older release didn't write `RUN_MANIFEST.json`                                        | Make sure you are on the current release                                                                                                                                                       |
| `NameError: name 'LIFT_LABEL' is not defined` in `fig_country_cfe_lift.py` | Missing `global LIFT_LABEL` (was fixed)                                               | Make sure you are on the current release                                                                                                                                                       |
| `FileNotFoundError: configs/network/egress_emissions.yaml`                   | Spatial sweep run from the wrong CWD (defaults are anchored at `gridpilot/`)          | Make sure you are on the current release; defaults now resolve against the script's own location                                                                                               |
| `\StubDataPresent = true` in `results.tex` despite a real run              | The extractor was run before the real CSV landed;`RUN_MANIFEST.json` missing or older | Re-run `extract_paper_macros.py` after the CSV write completes                                                                                                                               |
| Table cells show `?` for `Base CI` and `Δ CI`                           | The extractor ran against the stub CSV (which lacks the `ci_weighted_*` columns)      | Re-run `extract_paper_macros.py` after the real CSV lands; the v1.0 extractor synthesises lift from base − fsla if the pre-aggregated column is missing                                     |
| LaTeX `! Package graphics Error: File 'workloads.pdf' not found`             | The hand-made workload-taxonomy figure isn't yet in `papers/pecs2026/figs/`           | Copy `workloads.pdf` into `papers/pecs2026/figs/` (one-time manual step)                                                                                                                   |
| Multi-country sweep killed mid-way                                             | Hardware / time-budget issue                                                            | Just re-run; the cell-level checkpointing under `cells/*.json` resumes from where it left off                                                                                                |
| Tier sweep runs but figure looks wrong                                         | Tier 0 baseline has noise across seeds                                                  | Per-cell noise is bounded by ~0.05 pp; this is normal                                                                                                                                          |
| Hyperparameter sweep crashes inside `_apply_hyper`                           | `TIER_NAMES` out-of-sync between dispatcher and library                               | Run `pytest -q gridpilot/tests/test_fsla.py` first; should be green                                                                                                                          |
| `pdflatex` errors on `splncs04.bst` not found                              | Missing LNCS bibliography style                                                         | `tlmgr install splncs04` or install `texlive-bibtex-extra` on Debian/Ubuntu                                                                                                                |
| Build script reports "page count 13 exceeds 12-page LNCS ceiling"              | Some section grew beyond budget                                                         | See the surgical-cut list in[`gridpilot/docs/REPRODUCIBILITY.md`](gridpilot/docs/REPRODUCIBILITY.md); for PECS the safe drops are §5.1 sensitivity subsection and the Demand-flex table column |

---

## 11. Sequence summary (TL;DR)

```bash
# === 0. Bootstrap (one-time, ~3 min) ===
git clone https://github.com/denisa-c/gridpilot.git EuroPar2026-GridPilot
cd EuroPar2026-GridPilot
git submodule update --init --recursive
python3 -m venv .venv && source .venv/bin/activate
pip3 install --upgrade pip setuptools wheel
pip3 install -r gridpilot/requirements.txt

# === 1. Optional inputs ===
# export M100_ROOT=/path/to/M100        # extended Jan+Feb trace
# export ENTSOE_API_KEY=<your-token>    # real ENTSO-E hourly CI

# === 2. Sanity (30 s) ===
PYTHONPATH=gridpilot/src pytest -q gridpilot/tests/

# === 3. Headline pipeline (~75 min) ===
bash gridpilot/scripts/run_all_experiments.sh

# === 4. Ablation sweeps (~55 min) ===
PYTHONPATH=gridpilot/src python3 \
  gridpilot/scripts/multicountry/replay_single_tier_sweep.py \
  --jobs gridpilot/data/traces/m100_real_jobs.parquet \
  --output-dir gridpilot/data/m100/tier_sweep/ --force

PYTHONPATH=gridpilot/src python3 \
  gridpilot/scripts/multicountry/replay_hyperparameter_sweep.py \
  --jobs gridpilot/data/traces/m100_real_jobs.parquet \
  --output-dir gridpilot/data/m100/hyper_sweep/ --force

PYTHONPATH=gridpilot/src python3 \
  gridpilot/scripts/figures/fig_tier_and_hyper.py \
  --tier-summary  gridpilot/data/m100/tier_sweep/TIER_SUMMARY.csv \
  --hyper-summary gridpilot/data/m100/hyper_sweep/HYPER_SUMMARY.csv \
  --out gridpilot/figs/fig_tier_and_hyper.pdf

# === 5. Extract macros + rebuild PDFs (~1 min) ===
PYTHONPATH=gridpilot/src python3 \
  gridpilot/scripts/figures/extract_paper_macros.py
bash papers/build.sh

# === 6. Bundle results for copy-back ===
tar czf /tmp/gridpilot_full_run.tar.gz \
  papers/pecs2026/figs/results.tex \
  papers/whpc2026/figs/results.tex \
  papers/pecs2026/main.pdf \
  papers/whpc2026/main.pdf \
  gridpilot/data/m100/policy_matrix \
  gridpilot/data/m100/country_sweep \
  gridpilot/data/m100/tier_sweep \
  gridpilot/data/m100/hyper_sweep \
  gridpilot/figs
```

Done.

---

**License:** Code MIT, data CC-BY 4.0.
**Contact:** denisa.constantinescu@epfl.ch
**Companion docs:** [`INDEX.md`](INDEX.md)
