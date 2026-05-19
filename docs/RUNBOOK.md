# GridPilot — End-to-End Runbook

This file is the single source of truth for **rerunning every script
and experiment** that backs the two companion papers
(`papers/whpc2026/` and `papers/pecs2026/`).  Read it once; copy/paste
the blocks you need.

All commands assume:

  * you have activated the bundled virtual-env: `source gridpilot/.venv/bin/activate`
  * your CWD is the repository root `EuroPar2026-GridPilot-Denisa/`
    unless a block explicitly says otherwise
  * `PYTHONPATH=src` makes the local `src/` modules importable —
    every Python command in this runbook prepends it

---

## 0  One-shot: real experiments + both papers from scratch

The single most useful entry point is:

```bash
bash gridpilot/scripts/run_all_experiments.sh
```

This runs **the real M100 trace replay**, the real multi-country
sweep, regenerates every figure from the resulting CSVs, extracts
all paper-headline macros from the on-disk data, and rebuilds both
PDFs.  Wall time on a 16-core / 64 GB workstation: ~75 min.

The script prints a stepwise progress bar of the form

```
======================================================================
[N/7] <step name>    (total elapsed mm:ss)
======================================================================
```

and emits a heartbeat line every 30 s during long-running steps
(``... still running step [N/7] <name>: mm:ss elapsed``), so it is
easy to tell whether the run is alive.  The whole transcript is also
``tee``'d to ``gridpilot/logs/run_all_<UTC-stamp>.log`` so you can
monitor from another terminal:

```bash
tail -f gridpilot/logs/run_all_*.log
```

Optional environment variables:

| Variable | Purpose |
|---|---|
| ``MODE`` (positional arg) | ``full`` (default) runs real replays; ``stub`` runs seeders only. |
| ``FORCE=1`` | Force ``--force`` on the replay drivers even in ``stub`` mode. |
| ``ENTSOE_API_KEY=<tok>`` | Enables step 0b (real ENTSO-E hourly CI fetch). |
| ``M100_ROOT=<path>`` | Overrides the source for step 0a (extends the trace with Feb 2022).  Defaults to the in-repo published subset ``gridpilot/data/m100_public/`` — set this only if you have a different ExaMon dump. |
| ``WORKERS=<n>`` | Pool size for the two replay drivers (default 4). |
| ``HEARTBEAT_SEC=<n>`` | Heartbeat cadence in seconds (default 30). |

For a fast paper rebuild from literature-anchored stub data
(no replays):

```bash
bash gridpilot/scripts/run_all_experiments.sh stub
```

To rebuild only the PDFs without running anything else:

```bash
./papers/build.sh
```

This single command:

1. Detects that the four data figures (`fig_cfe_by_tier.pdf`,
   `fig_swf_comparison.pdf`, `fig_fairness_pareto.pdf`,
   `fig_latency_per_tier.pdf`), the two country figures
   (`fig_country_cfe_lift.pdf`, `fig_country_pue_aware.pdf`) or either
   paper's `architecture.pdf` is missing.
2. Auto-invokes `gridpilot/scripts/demo_policy_matrix.sh`, which
   seeds literature-anchored stub CSVs and re-renders the figures.
3. Defensively re-renders `architecture.pdf` for each paper if the
   demo did not produce it.
4. Stages every figure into `papers/<paper>/figs/` and runs
   `pdflatex + bibtex + pdflatex × 2` for both papers.

If you only want to (re)build one paper:

```bash
./papers/build.sh whpc    # GridPilot controller paper
./papers/build.sh pecs    # f-SLA contract paper
```

Other targets: `./papers/build.sh stage` (figures only, no compile);
`./papers/build.sh clean` (remove `.aux/.log/.pdf` build artefacts);
`./papers/build.sh distclean` (also remove staged `figs/` dirs).

---

## 1  Stub data (≤ 1 minute)

The stubs let the figures and papers rebuild **without** running the
heavy replays.  They use literature-anchored numbers and are
overwritten by the real replays below.

```bash
cd gridpilot
PYTHONPATH=src python scripts/m100/seed_policy_matrix_stub.py \
    --output-dir data/m100/policy_matrix
PYTHONPATH=src python scripts/multicountry/seed_country_sweep_stub.py \
    --output-dir data/m100/country_sweep
```

---

## 2  Real experiments

### 2.1  Legacy — f-SLA Monte-Carlo on M100 (≤ 30 min on 16 cores)

This driver predates the two-paper split.  It is kept for traceability
of the early-stage results; the current PECS results come from §2.2
and §2.3 below.


```bash
cd gridpilot
PYTHONPATH=src python scripts/m100/inject_fsla_prior.py \
    --jobs       data/traces/m100_real_jobs.parquet \
    --ci         configs/grids/DE.yaml \
    --pue        raps/config/marconi100.yaml \
    --alpha      3.0 3.0 2.5 1.5 \
    --seeds      32 \
    --bootstrap  10000 \
    --sensitivity-scale 0.5,1.0,2.0 \
    --output-dir data/m100/fsla_counterfactual/
```

Outputs `headline.csv`, `bootstrap_ci.json`, `prior_sensitivity.csv`,
per-seed JSONs, plus a `RUN_MANIFEST.json` with the git SHA, Python
and package versions, and wall-clock time.  The PECS paper §3.4
"M100 sanity-check" cites these files.

Note: this driver's `--pue` flag is unambiguous (it has no `--pue-*`
sibling), so the short name is fine.

### 2.2  PECS anti-gaming policy matrix on M100 (≈ 26 min on 16 cores)

Backs the policy-matrix figure (PECS Sect.~\ref{sec:policy}).


```bash
cd gridpilot
PYTHONPATH=src python scripts/m100/replay_policy_matrix.py \
    --jobs         data/traces/m100_real_jobs.parquet \
    --ci           configs/grids/DE.yaml \
    --pue          raps/config/marconi100.yaml \
    --policies     FCFS,EASY,SAF,RLBackfilling,GridPilot-PUE \
    --mechanisms   none,M0,M1,M2,M3 \
    --seeds        8 \
    --workers      4 \
    --output-dir   data/m100/policy_matrix/
```

Outputs `policy_matrix.csv` (one row per cell) and
`HYPOTHESIS_OUTCOMES.json` summarising H1--H5.

### 2.3  PECS multi-country results + WHPC E8 — multi-country sweep (~30–45 min on 16 cores)

Backs the PECS multi-country CFE/CI-weighted-mean headline
(Sect.~\ref{sec:results}, including the T4-elastic-burst tier marked
deterministically elastic in the dispatcher's job table) and the WHPC
multi-country PUE-aware result (Sect.~\ref{sec:country}), in one pass.
The cell count is $6\,\text{grids} \times 3\,\text{MW} \times
(5\,\text{f-SLA} + 2\,\text{PUE})\,\text{mechanisms} \times
8\,\text{seeds} = 1\,008$ cells.


This drives both the PECS multi-country CFE-lift result and the
WHPC controller's multi-country PUE-aware result, in one pass.

```bash
cd gridpilot
PYTHONPATH=src python scripts/multicountry/replay_country_sweep.py \
    --jobs             data/traces/m100_real_jobs.parquet \
    --grids            configs/grids/SE.yaml,configs/grids/FR.yaml,configs/grids/CH.yaml,configs/grids/IT.yaml,configs/grids/DE.yaml,configs/grids/PL.yaml \
    --pue-yaml         raps/config/marconi100.yaml \
    --mw               1,10,50 \
    --fsla-mechanisms  none,M0,M1,M2,M3 \
    --pue-mechanisms   none,GridPilot-PUE \
    --seeds            8 \
    --workers          4 \
    --output-dir       data/m100/country_sweep/
```

**Important:** use the **full** flag names exactly.  Short prefixes
like ``--pue`` are rejected because they would be ambiguous between
``--pue-yaml`` and ``--pue-mechanisms``.  ``--mechanisms`` is kept as
a backwards-compatible alias for ``--fsla-mechanisms``.

Outputs `country_sweep.csv` (one row per `(country, mw, layer,
mechanism, seed)` cell), `COUNTRY_SUMMARY.csv`, and
`RUN_MANIFEST.json`.

### 2.4  WHPC V100 hardware experiments (≈ 48 GPU-hours)

These require a 3× NVIDIA V100 SXM2 testbed with NVML.  The full
procedure is in `docs/V100_MEASUREMENT_PROTOCOL.md`.  Short version:

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

## 3  Render figures

After any of the experiments above (or after the stubs), re-render
the affected figures:

```bash
cd gridpilot
# PECS policy-matrix figures
for f in fig_cfe_by_tier fig_swf_comparison fig_fairness_pareto fig_latency_per_tier; do
    PYTHONPATH=src python "scripts/figures/${f}.py"
done
# Multi-country figures (used by both papers)
PYTHONPATH=src python scripts/figures/fig_country_cfe_lift.py
PYTHONPATH=src python scripts/figures/fig_country_pue_aware.py
# Per-paper architecture diagrams
PYTHONPATH=src python scripts/figures/fig_fsla_architecture.py \
    --out ../papers/pecs2026/figs/architecture.pdf
PYTHONPATH=src python scripts/figures/fig_gridpilot_architecture.py \
    --out ../papers/whpc2026/figs/architecture.pdf
```

All figures are vector PDFs with `pdf.fonttype=42` (TrueType-embedded
for camera-ready submission) and a greyscale-safe palette + hatching
that prints legibly in black-and-white.

---

## 4  Editable architecture .pptx

The two simplified architecture slides have an editable PowerPoint
master that you can refine and re-export.

```bash
cd gridpilot
# Generate the editable masters (.pptx)
PYTHONPATH=src python scripts/figures/make_architecture_pptx.py
# This writes:
#   ../papers/whpc2026/architecture.pptx
#   ../papers/pecs2026/architecture.pptx
```

To use a refined version in the paper:

1. Open `papers/<paper>/architecture.pptx` in PowerPoint / Keynote /
   LibreOffice Impress and edit.
2. `File > Export > PDF` over the existing
   `papers/<paper>/figs/architecture.pdf`.
3. Re-run `./papers/build.sh <paper>`.

The matplotlib placeholder script (`fig_fsla_architecture.py` /
`fig_gridpilot_architecture.py`) regenerates the same PDF if you
delete it, so the paper always builds with at least a working
diagram even if you have not exported the .pptx yet.

---

## 5  Tests (≤ 30 s)

```bash
cd gridpilot
PYTHONPATH=src pytest -q
```

48 tests in total:

| File | Coverage |
|---|---|
| `tests/test_fsla.py` | f-SLA tier ladder, Dirichlet draw, length-conditioning |
| `tests/test_gaming_mechanisms.py` | M0--M3 mechanisms, SWF, Jain |
| `tests/test_gridpilot_pue.py` | PUE-aware scheduler invariants |
| `tests/test_raps_integration.py` | RAPS YAML adapter |
| `tests/test_entsoe_connector.py` | ENTSO-E CI loader |
| `tests/test_failure_modes.py` | scheduler error paths |

Every test passes without network access in under 30 seconds.

---

## 6  What lands where

A short map for reviewers and re-runners:

```
gridpilot/
├── src/
│   ├── scheduler/
│   │   ├── fsla.py                  (tier ladder + Dirichlet prior)
│   │   ├── fsla_mechanisms.py       (M0/M1/M2/M3 anti-gaming plug-ins)
│   │   ├── ai_baseline.py           (per-user AI predictor)
│   │   ├── swf.py                   (utilitarian/Nash/leximin/alpha-fair)
│   │   ├── scheduler_pue_aware.py   (the dispatch loop both papers use)
│   │   └── scheduler_carbon.py      (legacy CI-only scheduler)
│   ├── cooling/cooling_pue_model.py (four-component PUE model)
│   ├── controller/                  (Tier-1/2/3 implementations)
│   └── integration/                 (RAPS adapter + ENTSO-E connector)
├── scripts/
│   ├── m100/{inject_fsla_prior,replay_policy_matrix,seed_*_stub}.py
│   ├── multicountry/{replay_country_sweep,seed_country_sweep_stub}.py
│   ├── figures/                     (all paper figures)
│   └── v100/experiments/            (V100 measurement campaign)
├── data/
│   ├── m100/{policy_matrix,country_sweep,fsla_counterfactual}/
│   ├── traces/m100_real_jobs.parquet
│   └── v100_raw/                    (V100 hardware traces)
├── configs/grids/{SE,CH,FR,IT,DE,PL}.yaml
├── raps/config/marconi100.yaml      (cooling-model anchor)
├── docs/                            (protocols + this runbook)
└── figs/                            (rendered figure PDFs)

papers/
├── whpc2026/{main.tex,references.bib,architecture.pptx,figs/}
├── pecs2026/{main.tex,references.bib,architecture.pptx,figs/}
└── build.sh                         (this runbook's §0 entry point)
```

If you only remember one thing: **`./papers/build.sh`** rebuilds
both papers end-to-end from a clean checkout.  Everything else in
this document is for re-running individual stages.
