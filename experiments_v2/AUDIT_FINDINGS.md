# AUDIT_FINDINGS — Phase 3 dispatcher audit

Date: 2026-05-19
Triggered by: Phase 2 single-cell smoketest (SE, 10 MW, seed 0), which
passed the sign-convention gate but surfaced four structural problems
in the v1 dispatcher pipeline.  This file records what we found, with
line references, so the v2 refactor doesn't repeat the same mistakes.

---

## F1 — `pue_weight` is a dead parameter

**Symptom.**  `replay_country_sweep.run_one_cell` passes
`pue_weight=1.0` to `replay_proact_opt_pue` for the f-SLA layer with
the comment *"so the scheduler actually uses the f-SLA tier windows
for CI-aware deferral"* (replay_country_sweep.py L322–323).

**Reality.**  `pue_weight` appears in
`gridpilot/src/scheduler/scheduler_pue_aware.py` exactly twice: once
in the function signature (L69, `pue_weight: float = 0.5`) and once
in the docstring (L76, *"The pue_weight argument controls the trade-
off between"*).  **It is referenced nowhere in the dispatch logic.**
The CI signal is hardcoded into `is_high_signal_window` at L96 (built
from `ci_vals * pue_vals`) and consumed unconditionally in the
deferral branch at L218–224.

**Impact.**  Every v1 result that claims "we ran EASY-FCFS with the
CI signal on (pue_weight=1.0)" is in fact running ProACT-OPT with
its hardcoded CI deferral and no tunable CI-signal-strength.  The
"EASY-FCFS CI-aware" baseline is **not** a CI-tuned variant of
EASY-FCFS; it is the same dispatcher as the f-SLA mechanisms with
`max_delay_h=0` and all jobs in T_RIGID.

**Fix path.**  Either (a) make `pue_weight` actually multiply into
`facility_signal` at L96 so `pue_weight=0` produces a CI-blind
baseline, or (b) remove the parameter and document the dispatcher
as "always CI-aware; CI-blind baselines must use a different code
path".  Option (a) is the right one because it lets v2 produce a
unified plain-FCFS-CI-blind vs EASY-FCFS-CI-aware vs M3 sweep from
the same dispatcher with the same energy accounting.

---

## F2 — `layer="pue"` and `layer="fsla"` are different dispatchers

**Symptom.**  Phase 2 smoketest (SE, 10 MW, seed 0):

| Sub-cell | dispatcher | n_jobs | energy_kwh | co2_g_facility |
|----------|------------|--------|------------|----------------|
| (a) plain-FCFS, `layer="pue"`  | `replay_fcfs_pue`      | 359 481 | **1 889 310** | 48 216 032 |
| (b) EASY-FCFS,  `layer="fsla"` | `replay_proact_opt_pue` |  60 139 |    **61 803** |  1 501 969 |
| (c) f-SLA M3,   `layer="fsla"` | `replay_proact_opt_pue` |  60 139 |    **89 737** |  2 211 215 |

The `pue` path reports 30× more energy than the `fsla` path on the
same trace at the same MW target.

**Reality.**  `replay_country_sweep.run_one_cell` calls two
different dispatcher functions depending on `layer`:

- `layer="fsla"` → `replay_proact_opt_pue(...)` (L331)
- `layer="pue", mechanism="none"` → `replay_fcfs_pue(...)` (L345)
- `layer="pue", mechanism="GridPilot-PUE"` → `replay_proact_opt_pue(...)` (L352)

The two functions accumulate energy on different bases:

- `replay_fcfs_pue` (L350): `active_nodes * node_power_kw * (Δt/3600)`
  — **time-stepped cluster-power integration over active intervals**
- `replay_proact_opt_pue` (L195): `j["nodes"] * replicas * node_power_kw * cap * (actual_dt/3600)`
  — **per-job energy with replica and power-cap scaling**

**Impact.**  Any Δ computed by subtracting (a) from (b) is
methodologically broken.  The current v1 `_compute_deltas` computes
exactly this Δ as `cfe_lift_pp_vs_fcfs` and ships it in
`COUNTRY_SUMMARY.csv`.  The numbers are not comparable.

**Fix path.**  The v2 design must run **plain-FCFS, EASY-FCFS-CI-
aware, and every f-SLA mechanism through the same dispatcher**
(`replay_proact_opt_pue` is the right choice — it's the more
sophisticated path).  Define "plain-FCFS" as
`replay_proact_opt_pue(..., pue_weight=0.0, max_delay_h=0)` once F1
is fixed.

---

## F3 — `result["n"]` is contaminated by end-of-sim padding

**Symptom.**  The M100 extended trace has ~3 100 jobs.  Phase 2
reports `n_jobs = 359 481` and `n_jobs = 360 139` for the same
trace.  Two orders of magnitude too many.

**Reality (from the explorer audit).**  Both `replay_fcfs_pue` and
`replay_proact_opt_pue` add **unfinished running/queued jobs to
`completed` at sim-end** (L253–257 in ProACT-OPT, L357–360 in FCFS).
`len(completed)` therefore counts (a) jobs that actually finished
during the replay window + (b) every job still running or queued
when the window ended.

**Impact.**  `n_jobs` cannot be reported in the paper as "number of
jobs the f-SLA replayed".  Worse, the energy / CO2 accumulators
include these synthetic end-of-window completions, which subtly
inflates absolute emissions.

**Fix path.**  Split `result["completed"]` into
`result["completed_within_window"]` (jobs that terminated cleanly
before sim end) and `result["truncated_at_window"]` (jobs still
running).  Headline metrics (energy, CFE, CI-weighted-mean) compute
from the first set only; the second set is a sanity-check column
(should be small if the trace fits the window comfortably).

---

## F4 — the bundled Jan trace cannot be consumed by the v1 replay

**Symptom.**  Phase 2 originally aborted with `KeyError:
'submit_time_epoch'` when the smoketest pointed at the bundled
`m100_real_jobs.parquet`.

**Reality.**  `align_jobs_to_ci` in `inject_fsla_prior.py` L295
expects column `submit_time_epoch`, which only exists in the
*extended* trace produced by `build_extended_trace.py`.  The
bundled Jan parquet has the legacy column `submit_time`.

**Impact.**  The repo docs (README, RUNBOOK, EXPERIMENTS_REMOTE) all
claim the bundled trace is enough to reproduce the headline.  In
practice, the user must first run `build_extended_trace.py` against
either the in-repo subset or the full ExaMon dump.  Anyone trying
"clone + run" hits this trap.

**Fix path.**  Either (a) auto-detect the column name in
`align_jobs_to_ci` and rename to `submit_time_epoch` if needed,
or (b) re-publish the bundled Jan parquet with the unified schema.

---

## F5 — `load_pue_params` cannot read the documented fallback path

**Symptom.**  Phase 2 originally aborted with `FileNotFoundError:
RAPS config not found at configs/config/marconi100.yaml`.

**Reality.**  `inject_fsla_prior.load_pue_params(path)` computes
`raps_repo_path = path.parent.parent` and
`system_name = path.stem`, then asks the RAPS adapter to load
`<raps_repo>/config/<system>.yaml`.  For the fallback path
`configs/raps_systems/marconi100.yaml`, this resolves to
`configs/config/marconi100.yaml` — which doesn't exist.

**Impact.**  `run_all_experiments.sh` only succeeds because the
RAPS submodule is initialized and the *preferred* path
`raps/config/marconi100.yaml` is taken.  The fallback that the
script explicitly logs as *"using fallback configs/raps_systems/
marconi100.yaml"* would silently break the run.

**Fix path.**  Make `load_pue_params` accept a direct YAML path
(no RAPS-repo layout assumption) when the path doesn't end in the
RAPS `<repo>/config/<system>.yaml` pattern.

---

## What this means for v2  *(revised 2026-05-19 after design discussion)*

The smoketest just earned its keep.  F1, F2, and F3 are all load-
bearing for the paper's defensibility.  But the original fix
proposal — "make ProACT-OPT the universal dispatcher and run plain-
FCFS through `replay_proact_opt_pue(pue_weight=0, max_delay_h=0)`" —
is **withdrawn** for the following reason:

> Comparing the f-SLA contract against a *degenerate-configuration
> version of our own dispatcher* is a strawman.  Reviewers will
> correctly point out that "plain FCFS" via ProACT-OPT is not the
> same algorithm as the canonical plain FCFS in the HPC scheduling
> literature, and any Δ-vs-FCFS claim against a non-canonical FCFS
> is unfalsifiable.

The revised v2 baseline plan is to implement the canonical published
baselines **as separate, faithful schedulers**, run them through a
**shared accounting function**, and compare the f-SLA contract
against them.  ProACT-OPT (= the f-SLA dispatcher) remains in
`gridpilot/src/scheduler/scheduler_pue_aware.py` and is used *only*
for the M0–M3 mechanism cells, clearly labelled as the contract's
own dispatcher.

### v2 scheduler catalogue  *(FINAL — RAPS attempt withdrawn 2026-05-19)*

**Update:** the RAPS-only plan recorded below was withdrawn after a
deeper look at the M100 dataloader.  See §5 below for the
post-mortem.  The actual v2 scheduler catalogue is:

| Baseline | Algorithm + reference | Implementation source | File |
|----------|----------------------|----------------------|------|
| **REPLAY** | Replay historical M100 dispatch | hand-rolled (~80 lines) | `experiments_v2/src/schedulers/replay.py` |
| **Plain FCFS** | FCFS, no backfilling — Mu'alem & Feitelson 2001 §2 | hand-rolled (~100 lines) | `experiments_v2/src/schedulers/fcfs.py` |
| **EASY-FCFS** | FCFS + EASY backfilling — Lifka 1995 §3 | hand-rolled (~160 lines) | `experiments_v2/src/schedulers/easy_fcfs.py` |
| **SAF** | Smallest-Area-First + EASY — Carastan-Santos & de Camargo 2019 §3 | hand-rolled (~150 lines) | `experiments_v2/src/schedulers/saf.py` |
| **f-SLA M0–M3** | The contract's dispatcher *(this paper)* | `gridpilot/src/scheduler/scheduler_pue_aware.py` (unchanged) | n/a |

CI-aware comparator: handled by citation, not by re-implementation.
Sukprasert et al. 2024's empirical 30% temporal-shifting ceiling is
the conservative upper bound the body cites.

### §5 — Post-mortem on the RAPS attempt

The RAPS path failed because **RAPS' M100 dataloader requires the
PM100 published-telemetry schema** (Antici et al. 2023, Zenodo
10127767) with per-job ``cpu_power_consumption`` /
``node_power_consumption`` / ``mem_power_consumption`` arrays.  Our
M100 source is the raw SLURM ``sacct`` dump — same physical
cluster, different dataset — with scheduler-relevant columns but
no power arrays.  Forcing the integration would have required:

  (a) downloading the PM100 dataset (~GB-scale, ties v2 to that schema), or
  (b) forking RAPS with a new SLURM-sacct dataloader (diverges
      from upstream), or
  (c) hand-rolling the four canonical baselines ourselves.

Path (c) was chosen: the algorithms are textbook (~100 lines each),
short enough for a reviewer to read end-to-end, defended by direct
citation of the original papers.  The RAPS submodule is still
loaded for its **cooling/PUE model anchor** (``raps/config/
marconi100.yaml``); only the *scheduler* path is hand-rolled.

The placeholder ``raps_adapter.py`` remains in the tree as
documentation of the route NOT taken, so a future maintainer with
the PM100 dataset can revisit the decision.

### §6 — Original (withdrawn) RAPS-only plan, retained for context

| Baseline | Algorithm + reference | Implementation source | Activation |
|----------|----------------------|----------------------|------------|
| **REPLAY** | Replay historical M100 dispatch (Antici et al. 2023 trace's own start times) | `raps/schedulers/default.py` | `policy=replay` |
| **Plain FCFS** | First-Come-First-Served, no backfilling — Mu'alem & Feitelson 2001 | `raps/schedulers/default.py` | `policy=fcfs, backfill=none` |
| **EASY-FCFS** | FCFS + EASY backfilling — Lifka 1995 | `raps/schedulers/default.py` | `policy=fcfs, backfill=easy` |
| **SAF** | Smallest-Area-First — Carastan-Santos & de Camargo 2019.  Implemented via RAPS' `priority` policy with `priority = −(nodes × runtime)` pre-computed on each Job | `raps/schedulers/default.py` | `policy=priority, backfill=easy` + saf-priority preprocessor |
| **ACCT_EDP** | Energy × Delay Product, operator-side power-aware scheduling — Gonzalez & Horowitz 1996; Patterson et al. | `raps/schedulers/experimental.py:300` | `policy=acct_edp, backfill=easy` |
| **(optional) ACCT_AVG_P / ACCT_LOW_AVG_P / ACCT_ED2P / ACCT_PDP** | Variants of power-aware accounting (Brooks et al.; Fugaku operational practice) | `raps/schedulers/experimental.py:12–19` | various via `policy=acct_*` |
| **f-SLA M0–M3** (this paper's contract) | `gridpilot/src/scheduler/scheduler_pue_aware.py` *(unchanged)* | replay_proact_opt_pue |

**Carbon-aware CI-using comparator: handled by citation, not by re-implementation.**

The paper's body cites Sukprasert et al. 2024's empirical upper bound
of ≈30% temporal-shifting ceiling for operator-inferred CI-aware
scheduling on real cloud traces.  The contract's measured lift on
the M100 trace will be reported against this published ceiling
rather than against a self-implemented PCAPS-temporal comparator.
This is a conservative defensive move: the contract's null result on
M100 cannot be attributed to "we picked a weak CI-aware baseline" —
the published ceiling is an order of magnitude above whatever lift
we measure.

PCAPS-temporal as a RAPS plug-in (`raps/schedulers/carbon_aware.py`)
remains a possible **post-v2** addition if the first v2 sweep result
motivates a stronger CI-aware comparison.  It is **not** on the
critical path for the first v2 rerun.

**Rationale for the pivot.**  The earlier plan was to hand-write FCFS,
EASY-FCFS, SAF, and PCAPS-temporal from scratch in
`experiments_v2/src/schedulers/{fcfs,easy_fcfs,saf,pcaps_temporal}.py`
(estimated ~750 lines + unit tests).  But RAPS is already vendored
into the repo as a submodule for the cooling/PUE model, and RAPS
ships a complete HPC scheduler simulator with:

- five queue policies (FCFS, SJF, LJF, PRIORITY, REPLAY) — `raps/policy.py:4–12`
- three backfill policies (NONE, EASY, FIRSTFIT) — `raps/policy.py:13–20`
- a native Marconi100 dataloader — `raps/dataloaders/marconi100.py:59`
- a programmatic engine that emits a structured schedule —
  `Engine(sim_config).get_job_history_dict()` returns `list[dict]`
  with `id`, `submit_time`, `start_time`, `end_time`, `scheduled_nodes`
- a "disable power + cooling" mode (`sim_config.power=False`,
  `sim_config.cooling=False`) so v2 gets just the schedule and feeds
  it through *our* accounting module, not RAPS' energy model

The integration is a single thin adapter:

```python
# experiments_v2/src/schedulers/raps_adapter.py (sketch)
def run_via_raps(jobs_df, total_nodes, policy, backfill, sim_end_epoch,
                  *, ci_df=None, pue_curve=None) -> ScheduleResult:
    """Run RAPS' engine on the given trace with the requested policy,
    capture the schedule, F3-split it through our accounting helper.
    """
    raps_jobs = marconi100.load_data_from_df(jobs_df).jobs
    if policy == "saf":
        # SAF via PRIORITY: pre-compute priority = -(nodes * runtime)
        for j in raps_jobs:
            j.priority = -(j.nodes_required * j.expected_run_time)
        policy = "priority"
    sim_config = SingleSimConfig(
        scheduler="default", policy=policy, backfill=backfill,
        power=False, cooling=False, ...
    )
    engine = Engine(sim_config)
    engine.run()
    schedule = engine.get_job_history_dict()
    # Convert RAPS' job_history_dict → v2 dispatch_log → F3-split
    return from_dispatch_log([{
        "submit_epoch": r["submit_time"],
        "start_epoch":  r["start_time"],
        "end_epoch":    r["end_time"],
        "nodes":        len(r["scheduled_nodes"]),
        "runtime_s":    r["run_time"],
        "replicas":     1.0,
    } for r in schedule], sim_end_epoch)
```

About **150 lines including the PCAPS-temporal RAPS-side plug-in**,
not 750.

### Per-finding revised disposition

| Finding | Original fix | Revised disposition |
|---------|--------------|---------------------|
| **F1** `pue_weight` dead in ProACT-OPT | Wire it into `facility_signal` at L96 | **Withdrawn.**  ProACT-OPT is the f-SLA dispatcher, not the comparator; it doesn't need a CI-off mode.  The comparator that needs a CI-strength knob is `pcaps_temporal.py`, where the threshold parameter is explicit by construction. |
| **F2** `pue` vs `fsla` paths use different dispatchers | Route plain-FCFS through ProACT-OPT | **Withdrawn.**  Plain-FCFS goes through `fcfs.py` (Mu'alem & Feitelson 2001), not through any version of ProACT-OPT.  `replay_fcfs_pue` stays in the v1 tree as a reference; v2 doesn't call it. |
| **F3** end-of-sim padding in `completed` | Split into `completed_within_window` + `truncated_at_window` | **Still in.**  The v2 shared accounting module enforces this split for every scheduler: only within-window completions contribute to headline metrics; truncated jobs are a sanity-check column. |
| **F-NEW** shared accounting | (new) | **In.**  All v2 schedulers produce a list of `(job, start, end, nodes, replicas)` tuples; a single `accounting.py` module converts that to `(energy_kwh, ci_eff, cfe, co2_g_it, co2_g_facility)`.  Per-job energy `nodes × runtime × P_node × replicas` is the literature convention.  No scheduler is allowed to write its own accumulators. |

### Headline Table 2 (v2 shape)

| Grid | CI 2025 | Plain FCFS CFE | EASY-FCFS CFE | PCAPS CFE | f-SLA M3 CFE | Δ vs FCFS | Δ vs EASY | Δ vs PCAPS |
|------|---------|----------------|---------------|-----------|--------------|-----------|-----------|------------|

- **Δ vs FCFS** isolates the contract's total value over the status-quo HPC scheduler.
- **Δ vs EASY-FCFS** isolates the contract's value over the standard backfilling baseline (no CI awareness).
- **Δ vs PCAPS** isolates the marginal value of *user-declared* flexibility over *operator-inferred* CI-aware flexibility — the conceptual claim of the paper, bounded by Sukprasert et al.'s 30 % ceiling.

### Estimated effort

| Step | Lines (approx) | Reference test |
|------|----------------|----------------|
| `accounting.py` | ~150 | closed-form energy/CO2/CFE tests (extends `00_unit_audit.py`) |
| `fcfs.py` | ~150 | 4-job worked example from Mu'alem & Feitelson 2001 |
| `easy_fcfs.py` | ~200 | EASY backfilling example from Lifka 1995 |
| `saf.py` | ~150 | small trace replay from Carastan-Santos 2019 |
| `pcaps_temporal.py` | ~250 | threshold algorithm example from Lechowicz et al. 2025 |
| Updated smoketest | ~30 lines edit | all four baselines + M3 land within ~10% on absolute energy |
| Total | ~900 | |

One focused implementation session + one validation session.  Only
then is it safe to port the v2 sweep scripts (02–04).
