# Contributing to GridPilot

We welcome contributions from the community. This document describes how to
extend the GridPilot framework, the reproducibility kit, and the paper.

## Scope of contributions

Contributions in any of the following areas are particularly welcome:

- **Additional grid connectors** beyond the current ENTSO-E coverage
  (e.g. AEMO Australia, CAISO USA, NEM Brazil). See `configs/grids/` for
  the YAML schema.
- **Additional GPU power models** beyond V100 / H100 (e.g. AMD MI300/MI325,
  Intel Gaudi, novel platforms). See `docs/V100_MEASUREMENT_PROTOCOL.md`
  for the measurement procedure that produces the calibration coefficients.
- **Workload archetype additions** beyond the current four (matmul,
  inference, bursty, steady-state). See `benchmarks/` for the existing
  trace formats.
- **Reproductions on other Tier-2 production clusters** with their own
  PUE measurements and ENTSO-E zone.

## How to contribute

1. Fork the repository and create a feature branch.
2. Run the end-to-end pipeline before committing
   (`bash scripts/run_all_experiments.sh stub` for a fast rebuild
   from literature-anchored stub data, or
   `bash scripts/run_all_experiments.sh` for a real ~75 min full run)
   and verify the figure PDFs and the two paper PDFs render without
   warnings.
3. Add or update tests under `tests/` if you change controller or
   scheduler logic; `pytest -q` should pass in under 30 s without
   network access.
4. Open a pull request with a description of the change, the
   scientific rationale, and any cluster or hardware constraints
   relevant to the change.

## Code style

- Python: PEP-8, 100-character line limit.
- LaTeX: 80-character line limit for prose; tables and figure captions
  exempt.
- Bibliography entries: `lastname` + 4-digit year + 1-3 word slug
  (e.g. `latif2024_8gpu`, `newkirk2025h100power`).
- Figure files: `fig_<topic>_<layout>.pdf` (e.g. `fig_pareto_1x4.pdf` for
  a 1-row 4-column Pareto layout).

## Reporting issues

Please use GitHub Issues for bug reports and feature requests. For questions
about the underlying methodology or the SNSF ProACT extension of GridPilot,
contact the corresponding author at `denisa.constantinescu@unibas.ch`.

## Attribution

Contributors are added to `CONTRIBUTORS.md` upon their first merged PR.
