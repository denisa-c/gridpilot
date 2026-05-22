# Rationale: per-decision log for the GridPilot kit

This document records the *why* behind every consequential design
choice in the GridPilot reproducibility kit (f-SLA paper, GridPilot
controller paper, C2 spatial+workflow follow-on).  Future maintainers
and reviewers should be able to look up any decision here without
re-deriving the trade-off.

For the broader ProACT-framework design rationale (cascade control,
predictor choice, calibration anchors), see
[`DESIGN_RATIONALE.md`](DESIGN_RATIONALE.md).  This file is the
kit-side companion: it covers the user-side contract, the metric
choices, the mechanism-design decisions, and the operational
engineering choices that the released kit (gridpilot v1.0 → v1.1)
embodies.

For *what* and *how* of reproduction, see
[`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) and
[`RUNBOOK.md`](RUNBOOK.md).

---

## 1. Why a *user-side* contract rather than operator-inferred flexibility?

The carbon-aware-scheduling literature (Sukprasert et al., NeurIPS
2024) bounds the operator-inferred spatio-temporal-shifting ceiling
at ~30 % on real cloud traces.  Whether this ceiling is a structural
property of AI/HPC workloads or a methodological property of the
elicitation interface is, to our knowledge, unresolved.

GridPilot's hypothesis is that **the ceiling is methodological**.
Users know more about their jobs' deferrability and elasticity than
queue-history-fitted models can recover — a 4 h job submitted
Wednesday that the user's colleagues will only read on Monday is
*deferrable to the weekend*, and no amount of queue-history fitting
recovers that fact.  The f-SLA exposes this knowledge directly as a
tier declaration and rewards honest declarations with proportional
service credits.

The trade-off vs operator-inferred is interface complexity: the user
now needs to think about deferrability at submission time.  We
mitigate that with the AI baseline (M3): the AI shows the user the
tier it expects them to pick, so honest declaration is no harder
than accepting a default, and the user gets a leaderboard reward for
beating it.

## 2. Why six tiers (T0..T5)?

The tier ladder is calibrated to the workload-flexibility taxonomy
of Fig.\ *workloads* in the f-SLA paper:

| Class | Fraction of GPU·h | Maps to |
|---|---|---|
| Interactive / urgent | < 5 % | T0 rigid |
| Workflow-coupled | 5–10 % | T1 hour |
| Elastic AI/HPC | 35–50 % | T2 day, T4 elastic burst |
| Batch / parallel | 10–20 % | T3 week |
| Geo-shiftable | 5–15 % | T5 spatial |

Six tiers is the minimum that exposes all four temporally flexible
classes plus the original rigid baseline.  Adding more tiers
(e.g. "month" or "interactive but capped 1 ms slack") was considered
and rejected: the marginal flexibility-class coverage is small
relative to the interface-complexity cost, and the existing six
tiers already cover ~95 % of the published GPU·h distribution.

Five tiers (the v1.0 ladder before T5 was added) covers ~85 % of
GPU·h but misses the geo-shiftable class entirely, which is the
fastest-growing fraction of new AI training (multi-site distributed
training, federated learning, edge inference).

## 3. Why NOM-IC rather than full IC (Vickrey-Clarke-Groves)?

Full Vickrey-Clarke-Groves (VCG) implementation would require
monetary transfers (the second-price or VCG-tax payments) that are
politically infeasible in publicly funded HPC.  Most academic
clusters have no internal billing system that supports cash transfers
between users; even where one exists (e.g.\ EuroHPC JU regular access
allocations), the cash flow is between funder and centre, not between
users.

Babaioff et al.\ (EC 2022) characterise truthful online cloud-
scheduling policies as monotone in declared value: any monotone
credit schedule is weakly truthful under any constraint-respecting
dispatcher.  This is sufficient for the f-SLA's incentive structure
(M0 posted-price baseline), but not robust to NOM-IC adversaries
(users who manipulate by trying *all* one-tier deviations and picking
the best).

Psomas, Verma & Zampetakis (EC 2022) introduce **Non-Obvious
Manipulability Incentive-Compatibility (NOM-IC)** as an
operationally sufficient relaxation: a mechanism is NOM-IC if no
one-tier deviation strictly improves the user's utility.  This is
much weaker than full strategy-proofness but is empirically the
boundary where lay users stop manipulating (the manipulation
requires checking all single-step deviations, which is cognitive
work the user does not do for free).

M3 (AI-Baseline Audit) is designed to satisfy NOM-IC under any
monotone credit schedule.  The empirical NOM-IC violation rate is
measured in the policy-matrix sweep (`HYPOTHESIS_OUTCOMES.json`,
hypothesis H2).

## 4. Why CFE as the primary metric rather than ΔCO₂%?

The f-SLA paper §4 has a named paragraph on this; the short version:

- **CFE is user-visible.**  The fraction of compute energy actually
  served by carbon-free electricity is the same quantity a Scope-2
  disclosure reports.
- **CFE avoids the static-PUE assumption.**  Any scheduler that
  decreases IT power drives instantaneous PUE *up* (the L² and L³
  cooling-affinity floors bind before IT power does), and an
  intensity-based percentage reduction silently inherits that
  assumption — overstating actual facility-meter savings by 4–7 pp
  on warm-water-cooled HPC sites.
- **CFE composes cleanly across grids of different mean CI**, whereas
  ΔCO₂% depends on the chosen baseline policy and is not comparable
  across grids.

We report CFE alongside two complementary metrics that the per-
country-normalised CFE does not capture: the **absolute CFE**
(fraction of energy below 150 g CO₂eq/kWh, the EU 2030 target) and
the **energy-weighted effective grid CI** (in g/kWh, continuous
dynamic range, ranks grids correctly).  ΔCO₂% is reported in the
kit (the `co2_avoided_tonnes_y` column of `country_sweep.csv`) but
as a *climate-impact* metric, not as the primary measure of the
contract's effectiveness.  f-SLA paper Finding B makes the asymmetry
explicit: CFE-lift is largest on the *cleanest* grids; avoided
tonnage is largest on the *dirtiest* ones — reporting only one is a
category error.

## 5. Why the AI-baseline audit (M3) is the headline mechanism?

The four mechanism plug-ins span the literature design space:

- **M0 posted price.** Static credit schedule, weakly truthful under
  Babaioff et al.\ monotonicity.  Baseline.
- **M1 BlindTrust queue.** Payment-free IC queue with a rolling
  audit (Grosof et al.) priced in lost next-job priority.
- **M2 Deferred-Acceptance Auction.** Per-tick one-shot DAA over
  tier bids, strategy-proof in the full-information regime
  (Bichler et al.).
- **M3 AI-baseline audit.** Submit-time AI prediction visible to
  the user; post-execution NOM-IC penalty proportional to
  (confidence × over-shoot).

M3 is the headline because **the AI baseline is visible**: declaring
T0 when one could absorb a day's delay is then a publicly-visible
under-claim, and declaring T3 when one cannot absorb a week is
publicly-visible over-claim risking a clause violation.  This is the
mechanism that empirically minimises the NOM-IC violation rate at
no fairness or SWF cost (measured in the policy-matrix sweep).

## 6. Why the PUE-aware dispatcher (for the GridPilot paper)?

European balancing markets settle reserves **at the facility meter,
not at the GPU board**.  A controller that commits a 2 MW FFR band
on board power may under- or over-deliver at the meter by the
difference between instantaneous PUE and its design-point value —
typically ±4 pp on warm-water-cooled HPC sites and up to ±7 pp on
chilled-water-cooled hyperscale facilities.

The four-component instantaneous PUE model (chiller + pumps + air +
miscellaneous) is calibrated to the published Marconi100 design
point (PUE 1.20 at full load) via the `raps/config/marconi100.yaml`
adapter; the L² (pumps) and L³ (air-handling) cooling-affinity
floors follow Sun et al.\ (2020) and the multi-chiller MPC
formulation of Zhao et al.\ (2024).  Without the PUE correction the
controller's commitment is *intrinsically* dishonest at the meter;
with it the GridPilot paper shows the dispatched FFR setpoint matches
the metered-side reserve commitment within ±1 pp.

## 7. Why a deterministic safety-island bypass (for the GridPilot paper)?

The 97 ms median end-to-end FR latency is reproducible only because
the safety-island bypass is deterministic — a small (<400 lines of
C, statically linked, run as one `SCHED_FIFO`-priority-80 thread
pinned to an isolated CPU core) program that bypasses the slower
Python supervisor stack.  Without the bypass, identical experiments
through the Python supervisor stack exhibit p99 dispatch latencies
exceeding 250 ms (garbage-collection pauses and lazy-import blocking
on first call).  The TLA⁺ liveness specification (shipped in
`scripts/v100/safety_island/spec.tla`) proves termination within four
NVML cap-update intervals (20 ms) under the assumption that the
kernel honours `SCHED_FIFO`.

## 8. Why bundle the M100 trace?

The bundled `data/traces/m100_real_jobs.parquet` (1 994 jobs,
January 2022) is small (~3 MB) and lets the f-SLA paper's multi-
country sweep run end-to-end without a download step.  In addition,
`data/m100_public/` ships the **Feb 2022 SLURM `sacct` slice** of the
Marconi100 ExaData archive (CINECA / Univ. of Bologna; CC-BY 4.0),
re-distributed here under the upstream licence; `scripts/m100/build_extended_trace.py`
auto-resolves it as the default source and concatenates it with the
January parquet to produce the extended ~3 100-job trace we use for
the headline numbers.  Users with their own ExaMon dump (e.g. a more
recent month) can override the source via `M100_ROOT=<path>`;
`scripts/m100/publish_m100_subset.sh` is the inverse operation that
re-publishes the subset from a local raw archive.

Bundling makes the reviewer's "from clone to camera-ready"
experience hermetic: no downloads, no API keys, no auth tokens
required for the basic pipeline.  Optional features (real ENTSO-E
CI, alternative ExaMon months) are clearly labelled as such.

## 9. Why per-cell JSON checkpointing for the multi-country sweep?

The country sweep has 1 008 cells.  A single crashed cell or a kill
mid-sweep would, without checkpointing, force a full ~30–45 minute
re-run.  Per-cell `cells/<cell-id>.json` checkpointing makes the
sweep resumable: on rerun, existing cell files are loaded off disk
and only unfinished cells re-execute.

The checkpoint is `.json.tmp`-then-`replace()` atomic so a kill
mid-write leaves either a complete JSON or no JSON at all; the
resume loader is also schema-aware, deleting and recomputing cells
whose schema doesn't match the current driver (so stale checkpoints
from an older release don't silently poison the final CSV).

## 10. Why honest data-provenance banners in the rendered PDFs?

The papers use placeholder/stub data during early drafting and real
data near submission.  Reviewers should be able to tell at a glance
which numbers are which.  A red banner in stub mode, neutral grey in
real-data mode, driven by the `\StubDataPresent` macro in the auto-
generated `results.tex`.  The banner appears in both papers' results
sections.

This is the analogue, in publication, of the `RUN_MANIFEST.json`
discipline in the data: every artefact carries an unambiguous origin
trail.

## 11. Why the architecture-5tier.pdf override?

The f-SLA paper's architecture figure has a deterministic redraw
(`papers/pecs2026/figs/architecture-5tier.pdf`, written by
`scripts/figures/fig_architecture_5tier.py`) that depicts the f-SLA
ladder explicitly with the T4 elastic-burst tier added in v1.1.  The
body text references `architecture-5tier.pdf` directly.  The original
hand-drawn `architecture-custom.pdf` (four-tier ladder, pre-T4) is
kept on disk for diff/comparison but is no longer cited.  The
matplotlib placeholder `fig_fsla_architecture.py` still writes
`architecture.pdf` so the paper compiles cleanly when neither the
script-redraw nor the hand-drawn file is present.

The same override pattern works for any other figure: drop a PDF
with the matching name into `papers/<paper>/figs/` and the build
script's placeholder generator will see it exists and skip
regeneration.

## 12. Why the v0.1 C2 scaffolding ships in v1.0?

Schema-forward-compatibility.  The v1.0 f-SLA paper reproducibility kit
needs to be a single artefact under MIT/CC-BY 4.0; if the C2
follow-on paper introduces new columns (`is_spatial_eligible`,
`spatial_clause`, `dag_node_id`, `dag_parent_id`) in v1.1, the v1.0
CSV outputs would be schema-incompatible and reviewers would not be
able to compare f-SLA paper v1.0 numbers across releases.  Shipping the
columns as no-op defaults in v1.0 keeps the schema stable.

The C2 modules (`spatial_routing.py`, `workflow_dag.py`,
`dag_mechanisms.py`, `egress_cost.py`) are dependency-light and
pytest-covered, so they impose no runtime cost on the f-SLA paper pipeline
and no install-cost beyond `networkx>=3.1` (optional).

See [`C2_SPATIAL_AND_WORKFLOW.md`](C2_SPATIAL_AND_WORKFLOW.md) for
the full scaffolding overview.

## 13. Legacy "Finding N" tags in source-code comments

Many source-code docstrings (e.g. in `src/scheduler/fsla.py`,
`scripts/m100/inject_fsla_prior.py`,
`scripts/m100/replay_policy_matrix.py`,
`scripts/multicountry/replay_country_sweep.py`,
`scripts/figures/fig_*.py`) still tag themselves with "Finding 3",
"Finding 4", or "Finding 5".  Those tags refer to the **legacy
single-paper draft** that has since been split into two workshop
papers (f-SLA + GridPilot) and re-numbered.  The current
mapping is:

| Legacy tag | Current f-SLA paper section / artefact |
|------------|---------------------------------|
| Finding 3 | `sec:fsla` — the f-SLA contract + Dirichlet prior; injection counterfactual on the M100 trace.  Drivers: `inject_fsla_prior.py`, `fsla.py`. |
| Finding 4 | Anti-gaming policy matrix in the body of `sec:fsla` and the per-tier-contribution / hyperparameter sweep figure (`tier_and_hyper`).  Drivers: `replay_policy_matrix.py`, `fsla_mechanisms.py`, `fig_{cfe_by_tier,swf_comparison,fairness_pareto,latency_per_tier}.py`. |
| Finding 5 | `sec:results` — the multi-country headline (CFE-lift across the EU CI spectrum).  Drivers: `replay_country_sweep.py`, `fig_country_cfe_lift.py`. |

The user-facing protocol docs (`FSLA_PROTOCOL.md`,
`POLICY_MATRIX_PROTOCOL.md`, `COUNTRY_SWEEP_PROTOCOL.md`) point at
the **current** section labels (`sec:fsla`, `sec:results`).  The
in-code tags are kept for git-history grep-ability — a reviewer
reading a v0.x commit message that references "Finding 4" can still
find the code that implemented it.

## 14. Choices we explicitly rejected

| Considered | Rejected because |
|---|---|
| Full VCG payments | politically infeasible in publicly funded HPC |
| ΔCO₂% as the primary metric | inherits static-PUE assumption; not comparable across grids |
| Operator-inferred flexibility (no f-SLA tier declaration) | bounded at ~30 % by Sukprasert et al.; leaves user knowledge on the table |
| Closed-source release | a public reproducibility kit is what the field needs |
| Only matplotlib architecture figures (no .pptx editable masters) | authors need to iterate on the diagrams in PowerPoint |
| Single-paper Euro-Par submission | exceeded 12-page workshop limit; split into two orthogonal contributions (f-SLA paper + GridPilot) on co-author advice |
| `numpy<2.0` upper bound | no Python 3.13/3.14 wheels available; relaxed to `<3.0` |
| `fork` start method for ProcessPoolExecutor | macOS default is `spawn`; module-level callables only; closures fail to pickle |
| In-line `index()` calls inside hot loops | accidentally O(N²); replaced with `enumerate` |
