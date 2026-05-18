# f-SLA Protocol — Formal Specification

**Version:** 1.0 (PECS 2026 / GridPilot v1.0 release)
**Backs:** PECS 2026 Paper Section 5 ("The f-SLA Contract: Eliciting Truthful Flexibility") and Finding 3 ("declared-tier f-SLA injection lifts the IT-CO₂ ceiling").

This document defines the flexible Service-Level Agreement (f-SLA) contract precisely enough that an independent implementer can reproduce the Finding 3 evidence chain on any cluster trace. It is the formal companion to `src/scheduler/fsla.py` and `scripts/m100/inject_fsla_prior.py`.

## 1. The four-tier ladder

Each tier `T_k` is a triple `(window, slowdown_max, credit)`:

| Tier | Name | Window `W` | Slowdown clause `s_max` | Credit/h `α` | Extras |
|------|------|------------|------------------------|--------------|--------|
| T0 | Rigid | 0 h | 1.0× | 0.00 | (legacy default; must remain costless) |
| T1 | Hour-deferrable | 1 h | 1.2× | 0.02 | |
| T2 | Day-deferrable | 24 h | 2.0× | 0.04 | |
| T3 | Checkpointable-multi-day | 168 h (7 d) | 4.0× | 0.06 | + 0.5 fixed checkpoint-eligibility bonus per job; user declares checkpoint cadence (e.g. 30 min) so the scheduler may pre-empt and migrate |

Credits are denominated in cluster-credit-hours; the actual exchange rate against compute time is a deployment-side parameter outside the scope of this protocol.

## 2. Synthetic prior

For Monte-Carlo evaluation in the absence of a deployed user cohort, tier assignments are drawn from a Dirichlet distribution over the 4-simplex Δ³:

  π ~ Dirichlet(α₀, α₁, α₂, α₃)

with default concentration α = (3.0, 3.0, 2.5, 1.5). Under this prior:

  E[π] = (0.30, 0.30, 0.25, 0.15)

(biased toward T1 to be conservative); Var[π_k] ≈ 0.02 per component. The total mass Σα = 10 is the "tightness" knob: larger Σα → tighter prior; α/k → flat. The sensitivity sweep at α/2 and 2α brackets the lift across plausible prior concentrations.

## 3. Length conditioning

Two integrity rules are enforced after each raw Dirichlet draw to guarantee that every job receives a physically plausible tier:

1. **Long jobs cannot be T0.** Any job with `run_time > 24 h` whose raw assignment is T0 is re-sampled from {T1, T2, T3} with the prior re-normalised over the remaining tiers.
2. **Short jobs cannot be ≥ T2.** Any job with `run_time ≤ 1 h` whose raw assignment is T2 or T3 is re-sampled from {T0, T1} with the prior re-normalised over the lower tiers.

Both reassignment counts are logged per seed in the `FSLAPriorReport` dataclass and persisted in the per-seed JSON, so the magnitude of the conditioning step is transparent.

## 4. Incentive structure (informal)

The credit schedule α₀ < α₁ < α₂ < α₃ is constructed so that truthful declaration is a (weakly) dominant strategy under the standard rationality assumption, in the following sense:

- **Under-declaration (declaring T_{k−1} when true type is T_k).** The user forfeits the marginal credit Δα = α_k − α_{k−1} per deferred hour. The scheduler delivers stricter QoS than the user's true tolerance, so no clause is violated; the loss is purely in foregone credit.
- **Over-declaration (declaring T_{k+1} when true type is T_k).** The scheduler may exploit the larger window and produce a slowdown up to s_max(T_{k+1}) > s_max(T_k); this exceeds the user's true tolerance and triggers a logged exception (force-dispatch). The user is not charged for the deferred-hours credit, but the QoS hit is real.

A formal incentive-compatibility proof under stronger informational assumptions (single-shot, full-information valuation) is the explicit subject of follow-on work and is not claimed in the PECS 2026 paper.

## 5. Dispatch-loop integration

The existing PUE-aware scheduler (`src/scheduler/scheduler_pue_aware.py:replay_proact_opt_pue`) already reads a per-job `d_max_hours` column from the input jobs DataFrame; the f-SLA layer simply populates it from the tier mapping (Section 1). No modifications to the existing scheduler are required.

The scheduler's QoS guard at line 188 of `scheduler_pue_aware.py` (in the inner dispatch loop) ensures `(t + time_step) ≤ submit + d_max`, which combined with the slowdown clause check enforced by the wrapping `replay_pair` driver gives the per-job invariant `actual_slowdown ≤ s_max(T(j))` — verified by `tests/test_fsla.py::test_slowdown_clause_invariant` and by the per-seed manifest.

## 6. Statistical-rigor protocol

The Finding 3 evidence is a Monte-Carlo + bootstrap + sensitivity bundle:

1. **Monte Carlo over priors.** 32 independent Dirichlet draws of π, one per seed; for each, run the all-rigid and declared-tier replays; record Δ_IT and Δ_facility.
2. **Bootstrap CI.** 10 000 percentile-bootstrap resamples of the 32 per-seed Δ values give the 95 % CI on the headline lift.
3. **Sensitivity sweep.** Re-run a sub-sweep (8 seeds per scale) at α/2, α, 2α to bound the lift across plausible prior concentrations. The cross-prior ranking Δ > 0 must be preserved.

## 7. Acceptance criteria (verified by `tests/test_fsla.py`)

1. Reproducible under fixed seed: byte-identical `headline.csv` and `bootstrap_ci.json` across runs.
2. Bootstrap CI width ≤ 1.5 pp on the default-prior Δ_IT; if wider, the seed count is too small.
3. Sensitivity envelope at α/2 and 2α brackets the default Δ within ±2 pp; cross-prior ranking Δ > 0 preserved.
4. Length-conditioned reassignment counts logged per seed in the manifest.
5. Per-job slowdown-clause invariant: `actual_slowdown ≤ s_max_clause`.
6. Standard CLI: `--help`, missing-arg error, `--force` overwrite semantics.

## 8. Output schema

`scripts/m100/inject_fsla_prior.py` writes a four-file bundle:

  * `headline.csv` (one row per seed; 16 columns including pi, rigid/decl IT/facility %s, deltas, p95s, length-condition counts)
  * `bootstrap_ci.json` (mean and 95 % CI for Δ_IT, Δ_facility, declared-tier IT %, declared-tier facility %)
  * `prior_sensitivity.csv` (one row per scale factor; mean / min / max / std of Δ_IT)
  * `seed_runs/seed_<n>.json` (full per-seed result + `FSLAPriorReport`)
  * `RUN_MANIFEST.json` (git SHA, command line, package versions, hostname, wall time)

## 9. Reproduction recipe (M100 + DE grid)

```bash
python scripts/m100/inject_fsla_prior.py \
    --jobs    data/traces/m100_real_jobs.parquet \
    --ci      configs/grids/DE.yaml \
    --pue     raps/config/marconi100.yaml \
    --alpha   3.0 3.0 2.5 1.5 \
    --seeds   32 \
    --bootstrap 10000 \
    --sensitivity-scale 0.5,1.0,2.0 \
    --output-dir data/m100/fsla_counterfactual/

python scripts/figures/fig_fsla_results.py \
    --in-dir data/m100/fsla_counterfactual \
    --out    figs/fig_fsla_results.pdf
```

Expected wall time on a 16-core workstation: ≤ 30 minutes for the full Monte Carlo + sensitivity sweep + figure render. The figure is publication-quality vector PDF, single-column LNCS-friendly width.
