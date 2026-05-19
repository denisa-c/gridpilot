# docs/ index

A one-page navigator for the documentation directory.  Most readers
want either [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) (from-clone
walkthrough) or [`RUNBOOK.md`](RUNBOOK.md) (per-stage rerun commands).

---

## Start here

| File | When to read it |
|---|---|
| [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) | First time you clone the kit.  Walks you through install → tests → end-to-end → paper build → verification. |
| [`DEPENDENCIES.md`](DEPENDENCIES.md) | Every Python package the kit uses, version constraints, Python-version compatibility, install size, what's required vs optional. |
| [`RUNBOOK.md`](RUNBOOK.md) | After the first run.  Per-stage commands you can copy-paste to re-execute a single step. |
| [`GLOSSARY.md`](GLOSSARY.md) | Look up an acronym (NOM-IC, CFE, FFR, …) or a domain term. |

## Why-it-is-the-way-it-is

| File | Scope |
|---|---|
| [`RATIONALE.md`](RATIONALE.md) | The PECS / WHPC / C2 kit-side rationale: per-decision log (why CFE not ΔCO₂%, why 6 tiers, why NOM-IC over VCG, why per-cell checkpointing, …). |
| [`DESIGN_RATIONALE.md`](DESIGN_RATIONALE.md) | The ProACT-framework-wide rationale (cascade control, predictor choice, calibration anchors).  Pre-dates the kit-side log and is broader in scope. |

## Reproducing per-stage

| File | Stage |
|---|---|
| [`POLICY_MATRIX_PROTOCOL.md`](POLICY_MATRIX_PROTOCOL.md) | M100 policy-matrix replay (step 1 of `run_all_experiments.sh`). |
| [`COUNTRY_SWEEP_PROTOCOL.md`](COUNTRY_SWEEP_PROTOCOL.md) | Multi-country sweep (step 2 of `run_all_experiments.sh`). |
| [`V100_MEASUREMENT_PROTOCOL.md`](V100_MEASUREMENT_PROTOCOL.md) | V100 hardware-measurement campaign (the WHPC paper's E1–E7; not included in the basic pipeline). |
| [`FSLA_PROTOCOL.md`](FSLA_PROTOCOL.md) | f-SLA contract specification: per-tier window/clause/credit table; acceptance criteria. |

## Claim-to-artefact

| File | Scope |
|---|---|
| [`COMPANION_PAPERS_MAP.md`](COMPANION_PAPERS_MAP.md) | Every headline number in both papers, paired with the exact data file, JSON key and one-line verification command. |

## Datasets and sources

| File | Scope |
|---|---|
| [`DATASETS.md`](DATASETS.md) | M100, ENTSO-E, RAPS dataset descriptions; download instructions; licences. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Three-tier controller architecture (WHPC paper details). |

## C2 follow-on (Spatial + Workflow)

| File | Scope |
|---|---|
| [`C2_SPATIAL_AND_WORKFLOW.md`](C2_SPATIAL_AND_WORKFLOW.md) | The new C2 scaffolding shipped in v1.0: modules, configs, drivers, tests, schema columns.  Pairs with `_dev_archive/PAPER_C2_PLAN.md` and `papers/europar2027-c2/`. |

---

## Project-wide entry points (not in docs/)

| File | Purpose |
|---|---|
| `../README.md` | Public-facing project README (badges, quick start, layout). |
| `../CONTRIBUTING.md` | How to extend the framework; PR conventions. |
| `../LIMITATIONS.md` | Scope caveats and lessons learned. |
| `../requirements.txt` | Canonical install file; `DEPENDENCIES.md` documents it. |
| `../scripts/run_all_experiments.sh` | Single end-to-end command. |
| `../../papers/build.sh` | LaTeX build driver for both papers. |
| `../../_dev_archive/` | Planning + AI-assisted-development artefacts; NOT in public release. |
