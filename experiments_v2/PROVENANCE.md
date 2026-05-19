# PROVENANCE — v2 run metadata

This file is the single point of record for *which inputs went into
which output*.  Every full v2 run appends a block.

## Required environment

| Variable          | Required? | Used for |
|-------------------|-----------|----------|
| `ENTSOE_API_KEY`  | yes       | Real ENTSO-E A75 hourly CI (v2 headline) |
| `M100_ROOT`       | no (auto) | Source of the Feb 2022 SLURM `sacct` slice |
| `WORKERS`         | no        | Pool size for parallel sweeps (default 4) |

If `ENTSOE_API_KEY` is unset, `clean_rerun_all.sh` refuses to advance
past the unit-audit phase unless `ALLOW_SYNTH_CI=1` is also set.
Synthesised CI is **not** part of the v2 headline.

## Input fingerprints

Recorded at the start of every v2 run:

- Git SHA of `EuroPar2026-GridPilot-Denisa` at run start.
- SHA-256 of the bundled Jan 2022 trace
  (`gridpilot/data/traces/m100_real_jobs.parquet`).
- SHA-256 of the published Feb 2022 subset
  (`gridpilot/data/m100_public/year_month=22-02/.../a_0.parquet`).
- SHA-256 of every per-country ENTSO-E parquet under
  `gridpilot/data/ci/entsoe/`.
- Python version + every package version from
  `gridpilot/requirements.txt`.

## Output fingerprints

After every run, `CHECKSUM_REPORT.md` carries a 16-char SHA-256
prefix of:

- `country_sweep.csv`, `COUNTRY_SUMMARY.csv`
- `tier_sweep.csv`, `TIER_SUMMARY.csv`
- `hyper_sweep.csv`, `HYPER_SUMMARY.csv`
- `figs/results.tex` (the macro file the PDF consumes)

If two runs at the same git SHA and the same input fingerprints
produce different output fingerprints, the cause is non-determinism
in the dispatcher or a missing seed.  Investigate.

## Run log

(Each new full v2 run appends a YAML block here.  Most recent first.)

```yaml
# (no v2 runs yet --- this section will populate when clean_rerun_all.sh
# is executed for the first time.)
```
