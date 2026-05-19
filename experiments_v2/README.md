# experiments_v2 — clean-room rerun for the PECS paper

This directory is the **quarantined replacement** for the PECS empirical
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
├── scripts/
│   ├── 00_unit_audit.py            ← Phase 1: closed-form metric tests
│   ├── 01_single_cell_smoketest.py ← Phase 2: end-to-end sign trace
│   ├── 02_run_country_sweep.py     ← 1008 cells, both baselines
│   ├── 03_run_tier_sweep.py        ← 864 cells, per-tier ablation
│   ├── 04_run_hyper_sweep.py       ← 576 cells, hyperparameter sensitivity
│   ├── 05_extract_macros.py        ← signed macros, no hardcoded prefix
│   ├── 06_render_figures.py        ← v2 PDFs into figs/
│   └── clean_rerun_all.sh          ← master orchestrator (this entry point)
├── data/                ← all v2 CSVs + cell checkpoints land here
│   ├── country_sweep/
│   ├── tier_sweep/
│   └── hyper_sweep/
├── figs/                ← rendered figure PDFs for the paper
└── archived_v1_<UTC>/   ← frozen snapshot of v1 outputs at v2 start
```

## How to run

From the repository root, on a 16-core / 64 GB workstation:

```bash
bash gridpilot/experiments_v2/scripts/clean_rerun_all.sh
```

The orchestrator runs the eight numbered scripts in order with
**fail-stop gating** between phases.  If `00_unit_audit.py` fails,
nothing downstream runs.  If the single-cell smoketest detects a
sign-convention drift, the sweeps don't start.  Total wall time on
a clean workstation: ~90 min for the three sweeps (denser trace +
real ENTSO-E CI is included on the critical path).

Required inputs:

- `gridpilot/data/traces/m100_real_jobs.parquet`  — bundled Jan 2022 trace
- `gridpilot/data/m100_public/year_month=22-02/.../a_0.parquet`  — Feb 2022 SLURM subset (in-repo)
- `$ENTSOE_API_KEY` exported — real ENTSO-E hourly CI fetch

If `$ENTSOE_API_KEY` is not set, the orchestrator refuses to advance
past the unit-audit phase and prints instructions for getting a token.
Synthesised CI is **not** used for the v2 headline (the v1 work
showed its dynamic range is too compressed to exercise the contract).

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
