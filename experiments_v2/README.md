# experiments_v2 — clean-room rerun for the f-SLA paper

This directory is the **quarantined replacement** for the f-SLA paper empirical
pipeline.  Every CSV, JSON checkpoint, macro file and rendered figure
that the paper builds against will be produced **here**, by scripts
**here**, with provenance metadata recorded **here**.

The v1 tree (`gridpilot/data/m100/...`, `gridpilot/scripts/{m100,multicountry,figures}/...`)
is preserved untouched as a reference.  It is no longer trusted for
headline paper numbers because:

1. The cell-cache schema drifted across improvements A–F (real
   ENTSO-E CI, canonical CFE, FCFS-baseline, extended trace, T4
   symmetric envelope, higher utilisation).  The
   `DERIVED_BACKFILL` patch landed in v1 lets the country-sweep
   resume after a schema change, but cells written *before* the T4
   envelope went symmetric are not corrected by the back-fill — they
   carry the old asymmetric-envelope behaviour, frozen.
2. The Table 2 LaTeX template hardcodes a `+` prefix on signed
   macros, producing `+−0.1` cells.  The fix touches both the
   extractor and the template; both belong to v2.
3. Headline findings A and B claim CFE-vs-CI gradients and avoided-
   tonnage ranking reversals that the v1 numbers do not show.  The
   v2 rerun is the way to distinguish *"the claim is wrong"* from
   *"the experiment had a bug hiding the effect"*.
4. The headline baseline in v1 is EASY-FCFS with the CI signal on
   (`pue_weight=1.0`), which already does most of the carbon-aware
   work and crowds the f-SLA's marginal lift down to noise.  v2
   reports two deltas side-by-side: **Δ vs plain FCFS** (status-quo
   counterfactual; isolates the contract's total value) and **Δ vs
   EASY-FCFS CI-aware** (isolates the marginal value of the tier
   declaration on top of an already-CI-aware scheduler).

## Layout

```
experiments_v2/
├── README.md            ← this file
├── METRICS.md           ← closed-form definitions of every metric
├── PROVENANCE.md        ← git SHA, env, M100 source hash, data dictionary
├── AUDIT_FINDINGS.md    ← Phase-3 audit + v1 bugs surfaced + RAPS pivot history
├── src/schedulers/      ← hand-rolled FCFS / EASY-FCFS / SAF / REPLAY
│   │                     + shared accounting module
│   ├── accounting.py    ← single source of truth for energy / CO₂ / CFE
│   ├── fcfs.py          ← Mu'alem & Feitelson 2001 §2
│   ├── easy_fcfs.py     ← Lifka 1995 §3 (bounded backfill, deque-based)
│   ├── saf.py           ← Carastan-Santos & de Camargo 2019 §3
│   └── replay.py        ← historical M100 dispatch
├── scripts/
│   ├── 00_unit_audit.py            ← Phase 1: closed-form metric tests
│   ├── 01_single_cell_smoketest.py ← Phase 2: end-to-end sign trace
│   ├── 02_run_country_sweep.py     ← Phase 4a: 9 schedulers × 6 grids × 3 MW × 8 seeds
│   ├── 03_run_tier_sweep.py        ← Phase 4b: per-tier ablation (T0..T5)
│   ├── 04_run_hyper_sweep.py       ← Phase 4c: hyperparameter sensitivity
│   ├── 04b_run_seasonal_sweep.py   ← Phase 4d: 4 seasons × CH/IT/DE, real CI
│   ├── 05_extract_macros.py        ← Phase 5a: signed macros, no hardcoded prefix
│   ├── 06_render_figures.py        ← Phase 5b: v2 PDFs into figs/
│   ├── 07_render_seasonal_figure.py← Phase 5c: 2×2 fig_proact_1x4-style
│   └── clean_rerun_all.sh          ← master orchestrator
├── tests/
│   └── test_schedulers.py          ← Phase 1b: per-scheduler unit tests
├── data/                ← all v2 CSVs + cell checkpoints land here
│   ├── country_sweep/
│   ├── tier_sweep/
│   ├── hyper_sweep/
│   └── seasonal_sweep/  ← 4 seasons × N countries, real ENTSO-E CI
├── figs/                ← rendered figure PDFs for the paper
└── archived_v1_<UTC>/   ← frozen snapshot of v1 outputs at v2 start
```

## How to run

### One-shot — every phase, fail-stop gating

```bash
bash gridpilot/experiments_v2/scripts/clean_rerun_all.sh
```

The orchestrator runs the eight numbered scripts in order.  If
`00_unit_audit.py` fails, nothing downstream runs.  If the single-
cell smoketest detects sign-convention drift, the sweeps don't
start.  Scripts that don't exist yet are clearly flagged with a
`[SKIP] phase X — script not yet written` line; the orchestrator
continues past them so you can run it at any stage of build-out.

### Phase-by-phase (for fast iteration)

```bash
# Phase 1 — closed-form metric tests (~1 s).  Must pass before anything else.
PYTHONPATH=gridpilot/src python3 \
    gridpilot/experiments_v2/scripts/00_unit_audit.py

# Phase 1b — per-scheduler sanity tests.  Reproduces:
#   FCFS head-of-queue pathology (MF&F 2001), EASY-FCFS fix (Lifka 1995),
#   SAF priority (Carastan-Santos 2019), REPLAY history, F3 truncation.
PYTHONPATH=gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/tests/test_schedulers.py

# Phase 2 — single-cell smoketest on real M100 trace, three sub-cells,
#          asserts sign convention end-to-end.
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/01_single_cell_smoketest.py

# Phase 4a — country sweep (9 schedulers × 6 grids × 3 MW × 8 seeds).
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/02_run_country_sweep.py \
        --workers 20 --max-jobs 20000

# Phase 4b — per-tier ablation.
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/03_run_tier_sweep.py \
        --workers 20 --max-jobs 20000

# Phase 4c — hyperparameter sensitivity.
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/04_run_hyper_sweep.py \
        --workers 20 --max-jobs 20000

# Phase 4d — 4 representative days × CH/IT/DE.
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/04b_run_seasonal_sweep.py \
        --workers 8

# Phase 5a — extract LaTeX macros (signed format).
PYTHONPATH=gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/05_extract_macros.py \
        --country-csv gridpilot/experiments_v2/data/country_sweep/country_sweep.csv \
        --out         gridpilot/experiments_v2/figs/results.tex

# Phase 5b — render the headline + ablation figures.
PYTHONPATH=gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/06_render_figures.py \
        --country-csv  gridpilot/experiments_v2/data/country_sweep/country_sweep.csv \
        --tier-summary gridpilot/experiments_v2/data/tier_sweep/TIER_SUMMARY.csv \
        --hyper-summary gridpilot/experiments_v2/data/hyper_sweep/HYPER_SUMMARY.csv \
        --out-dir gridpilot/experiments_v2/figs

# Phase 5c — fig_proact_1x4-style 2×2 with seasonal sweep + ENTSO-E CI.
PYTHONPATH=gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/07_render_seasonal_figure.py \
        --seasonal-csv gridpilot/experiments_v2/data/seasonal_sweep/seasonal_sweep.csv \
        --out gridpilot/experiments_v2/figs/fig_proact_1x4_v2.pdf
```

### Progress visibility

Every sweep driver (02–04b) renders a **tqdm progress bar** (with a
no-tqdm fallback that prints a one-line counter) and writes a
**per-cell wall-time** column (`_wall_s`) into each cell JSON, so a
slow cell is identifiable in the cache directory.  Per-cell timeout
defaults to 1 hour; cells that exceed it are skipped with `[ERROR]`
rather than hanging the whole sweep.

### Critical CLI flag — `--max-jobs N`

The bundled extended trace
(`gridpilot/data/traces/m100_real_jobs_extended.parquet`) has
360 139 rows but a **broken submit-time span of ~1 hour** (the
`build_extended_trace.py` column auto-detection mis-handles the
Feb 2022 SLURM schema; see `AUDIT_FINDINGS.md` F-NEW-TRACE-TIMESPAN).
Running schedulers against this trace as-is gives a "1-hour
360k-job" replay that doesn't represent reality and is also
catastrophically slow (queue saturated forever).

**Workaround**: pass `--max-jobs 20000` (or smaller for fast
iteration like `5000`).  The sweep uniform-random-samples the
trace to N jobs with a fixed seed (20260519) for reproducibility.
20 000 is the recommended ceiling for the headline; a smoketest
fits in ~30 s at `--max-jobs 1000`.

### Required inputs

- `gridpilot/data/traces/m100_real_jobs_extended.parquet`  — built by
  `gridpilot/scripts/m100/build_extended_trace.py` (Jan+Feb 2022).
  Falls back to `m100_real_jobs.parquet` (Jan-only).
- `gridpilot/raps/config/marconi100.yaml`  — RAPS PUE anchor; v2
  falls back to a design-PUE calibration if the submodule isn't
  initialised.
- `gridpilot/configs/grids/{SE,CH,FR,IT,DE,PL}.yaml`  — per-country
  CI series anchors (annual mean + diurnal/seasonal envelope).
- *(optional)* `gridpilot/data/ci/entsoe/{COUNTRY}_hourly.parquet`
  — real ENTSO-E A75 hourly CI from the `fetch_real_ci_series.py`
  driver.  Currently only `SE_hourly.parquet` ships in the repo;
  the seasonal-sweep figure falls back to synthesised CI for the
  missing countries.

### Sub-sample sizes — what to use for what

| Use case            | `--max-jobs` | Workers | Wall time (~) |
|---------------------|-------------|---------|---------------|
| Smoketest (1 cell)  | 1 000       | 1       | ~5 s          |
| Country sweep (one country, all schedulers) | 5 000 | 4 | ~1 min |
| Country sweep (full 1296 cells) | 20 000 | 20 | ~15–30 min |
| Tier sweep (full)   | 20 000      | 20      | ~10–20 min    |
| Hyper sweep (full)  | 20 000      | 20      | ~8–15 min     |
| Seasonal sweep      | n/a (small trace per day) | 8 | ~3–5 min |

### Run against the bundled Jan-only trace (no `--max-jobs` needed)

The bundled `data/traces/m100_real_jobs.parquet` is a **real 28-day
timespan** with 1 994 jobs (Jan 2022) and is **not affected by the
`build_extended_trace` timespan-collapse bug** that blights the
extended trace.  It is therefore the cleanest input for a paper
result — every job has its actual submit time, the dispatcher sees
a real diurnal CI signal, and the deferral windows actually bite.

All v2 sweep drivers auto-detect the legacy `submit_time` column
and rename it to `submit_time_epoch` on load.  No preprocessing
needed.

End-to-end orchestrator run against the Jan-only trace:

```bash
JOBS_TRACE="$PWD/gridpilot/data/traces/m100_real_jobs.parquet" \
WORKERS=20 \
FRESH=1 \
bash gridpilot/experiments_v2/scripts/clean_rerun_all.sh
```

Per-script invocation (if you want to run one phase only):

```bash
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/02_run_country_sweep.py \
        --jobs gridpilot/data/traces/m100_real_jobs.parquet \
        --workers 20
```

### Linear vs log axis variants

The orchestrator now emits **two** copies of the seasonal figure:

- `figs/fig_proact_1x4_v2_linear.pdf` — linear y on panel (c), linear x
  on panel (d).  Easier to read at a glance; the v2 default.
- `figs/fig_proact_1x4_v2_log.pdf` — log scales, matching the v1
  reference figure's convention.  Useful when CH (low CI) and DE
  (high CI) need to be compared on the same axes.

Pass `--log` to `07_render_seasonal_figure.py` to render the log
variant directly.

### Caveats

- **`$ENTSOE_API_KEY` is *recommended* but not *required*** for any
  individual script.  The orchestrator gates on it; individual
  drivers fall back to the per-country YAML's synthesised diurnal
  envelopes when ENTSO-E hourly data isn't present for that grid.
- **`tqdm` is recommended** (`pip install tqdm`); the drivers fall
  back to a one-line text counter without it.
- **Per-cell timeout = 1 hour** (hard-coded).  If a cell exceeds it,
  the driver logs `[ERROR] cell <id> failed: <reason>` and continues.
  Workers do not hang — `concurrent.futures` cancels the future and
  the worker process is recycled.

## What v2 changes vs v1

| Aspect | v1 | v2 |
|--------|----|----|
| Cell schema | grew incrementally across A–F | frozen at v2 start; documented in METRICS.md |
| Headline baseline | EASY-FCFS CI-aware | both plain FCFS and EASY-FCFS CI-aware, side-by-side |
| CI source | synthesised diurnal envelopes (±10–35 %) | ENTSO-E A75 hourly (real intraday swings) |
| T4 envelope | asymmetric `[1×, 4×]` in old cells; symmetric `[0.5×, 2×]` in live code | symmetric `[0.5×, 2×]` everywhere; no stale cells |
| Trace | Jan 2022 only (1 994 jobs) | Jan + Feb 2022 extended (~3 100 jobs) |
| Macro format | hardcoded `+` prefix + signed value → `+−0.1` | signed macros, no prefix in LaTeX template |
| Provenance | RUN_MANIFEST.json per sweep | RUN_MANIFEST.json + CHECKSUM_REPORT.md across all artefacts |

## Promoting v2 to "canonical"

When v2 is validated end-to-end (PDF builds, every body claim sourced
from a number in `figs/results.tex`, hand-check passes), the
promotion path is:

1. Move `gridpilot/data/m100/` → `gridpilot/archived_v1/`.
2. `mv gridpilot/experiments_v2/data gridpilot/data/m100`.
3. Update `papers/build.sh` to stage from `figs/` directly (drop the
   v2-prefixed path).
4. Update `gridpilot/docs/RUNBOOK.md` and `EXPERIMENTS_REMOTE.md` to
   point at the new scripts.
5. The v1 `scripts/multicountry/` files can either be deleted or
   left as `_archived` for diff.

Until that promotion happens, **the paper builds from v2 paths**,
and v1 is reference-only.

## Seasonal sweep + fig_proact_1x4 (Phases 4d + 5c)

The seasonal sweep evaluates the f-SLA contract against four
representative 2025 dates (mid-Winter / Spring / Summer / Autumn) on
CH, IT and DE, using **real ENTSO-E hourly CI** when a per-country
parquet is present under `gridpilot/data/ci/entsoe/`, and falling
back to the per-country YAML's synthesised diurnal envelope
otherwise.  Currently only `SE_hourly.parquet` ships in the repo;
fetch the rest with:

```bash
export ENTSOE_API_KEY=<token from https://transparency.entsoe.eu>
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/m100/fetch_real_ci_series.py \
        --start 2025-01-01 --end 2026-01-01 \
        --grids SE,CH,FR,IT,DE,PL \
        --out-dir gridpilot/data/ci/entsoe/
```

Then run the seasonal sweep + render:

```bash
# 240-cell sweep (4 seasons × 3 countries × 5 schedulers × 4 seeds).
# Wall time on a 16-core box: ~3–5 min.
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/04b_run_seasonal_sweep.py \
        --workers 8

# Render the 2×2 fig_proact_1x4-style figure with real data.
PYTHONPATH=gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/07_render_seasonal_figure.py \
        --seasonal-csv gridpilot/experiments_v2/data/seasonal_sweep/seasonal_sweep.csv \
        --out          gridpilot/experiments_v2/figs/fig_proact_1x4_v2.pdf
```

The output figure's panels (matching the reference layout):

| Panel | Source | Data |
|-------|--------|------|
| (a) CFE adoption surface | analytical, no data needed | sigmoid contour over (penetration × adoption) with equilibrium Ω* |
| (b) Savings by country and season | `SEASONAL_SUMMARY.csv` | net CO₂ reduction % of `fsla_M3` vs `fcfs` baseline within each (country, season) |
| (c) Summer CI diurnal | ENTSO-E hourly if present, else per-country YAML synth | mean + std bands over ±3 d around the summer anchor |
| (d) Pareto front | per-cell `(p95_slowdown, co2_reduction_vs_fcfs)` from all non-FCFS rows | dominated/non-dominated frontier; mean-slowdown vertical |

Missing input → panel shows an `(awaiting <input>)` placeholder so
the figure compiles end-to-end at any stage of build-out.

## Trace timespan caveat — read before you trust the numbers

`gridpilot/data/traces/m100_real_jobs_extended.parquet` has 360 139
rows but a `submit_time_epoch` span of only ~1 hour (per the v2
diagnostic).  This is a **bug in `build_extended_trace.py`**: the
auto-detection of the Feb 2022 SLURM-sacct submit-time column
mis-handles the schema and collapses the span.  Every v2 sweep
driver has a `--max-jobs N` flag that uniform-random sub-samples
the trace to N rows with a fixed seed (20260519) for
reproducibility; use this until the trace bug is fixed.

The fix lives at `gridpilot/scripts/m100/build_extended_trace.py`'s
`_to_epoch_seconds` / `_normalise` helpers — likely a wrong column
chosen via `SUBMIT_CANDS` (e.g., `accrue_time` instead of
`submit_time`) and/or the heuristic in `_to_epoch_seconds`
mis-classifying the unit scale.  Filed in `AUDIT_FINDINGS.md` as
`F-NEW-TRACE-TIMESPAN`.
