# C2 follow-on: spatial f-SLA and workflow-conditional routing

This document explains the v0.1 scaffolding for the C2 follow-on paper
(*Spatial f-SLA and Workflow-Conditional Carbon-Aware Routing*) that
ships in the GridPilot v1.0 release.

For the scientific framing and the timeline, see
[`../../_dev_archive/PAPER_C2_PLAN.md`](../../_dev_archive/PAPER_C2_PLAN.md).
For the LaTeX skeleton, see `papers/europar2027-c2/main.tex`.
For the rationale for shipping it in v1.0 (rather than waiting for
v1.1), see [`RATIONALE.md`](RATIONALE.md) §12.

---

## 1. What's new

| Component | New in v1.0 | C2-specific |
|---|---|---|
| Six-tier ladder (T0..T5) | yes | T5 (Spatial) is the C2 contribution |
| Workload taxonomy figure | yes | maps each tier to a published workload class |
| `src/scheduler/spatial_routing.py` | new module | `SpatialClause`, `M_Spatial` audit, cleanest-grid selector |
| `src/scheduler/workflow_dag.py` | new module | `WorkflowDAG` with conditional branching |
| `src/scheduler/dag_mechanisms.py` | new module | `M_Workflow` KL-divergence NOM-IC audit |
| `src/scheduler/egress_cost.py` | new module | per-grid-pair g CO₂eq/GB egress emissions |
| `configs/network/egress_emissions.yaml` | new | 36 grid-pair entries calibrated to European backbone |
| `configs/workflows/*.yaml` | new | HPO sweep, HPCG workflow, training-restart configs |
| `scripts/workflows/*.py` | new | synthetic DAG generators + replay driver |
| `scripts/multicountry/replay_spatial_sweep.py` | new | spatial-routing sweep driver |
| `scripts/figures/fig_{spatial_routing_map,workflow_dag_savings,joint_pareto}.py` | new | placeholder figure stubs |
| `tests/test_{spatial_routing,workflow_dag,dag_mechanisms}.py` | new | 16 new tests |
| Schema columns in `replay_country_sweep.py` | added as no-op defaults | `is_spatial_eligible`, `spatial_clause`, `dag_node_id`, `dag_parent_id` |

The PECS v1.0 outputs (`policy_matrix.csv`, `country_sweep.csv`) are
bit-identical with the C2 v0.1 changes — the new schema columns are
no-op defaults that the existing dispatcher ignores.

## 2. Spatial f-SLA primitives

### 2.1 `SpatialClause` dataclass

```python
from scheduler.spatial_routing import SpatialClause
clause = SpatialClause(
    acceptable_grids=("SE", "CH", "FR"),
    excluded_grids=("DE",),         # GDPR-style exclusion
    transfer_size_gb=10.0,
    home_grid="PL",
)
clause.effective_grids       # ('CH', 'FR', 'SE')  --- excluded subtracted
```

Inputs are normalised: case-folded to uppercase, deduplicated,
sorted, validated non-empty.  `effective_grids` is acceptable minus
excluded; the dispatcher's fall-back behaviour when both lists
overlap fully is to keep the job on `home_grid` (graceful T0
degradation under sovereignty constraints — hypothesis H4).

### 2.2 Cleanest-grid selector

```python
from scheduler.spatial_routing import pick_cleanest_grid
ci_now = {"SE": 11.0, "CH": 30.0, "FR": 53.0, "DE": 295.0, "PL": 612.0}
egress = {("PL", "SE"): 0.7, ("PL", "CH"): 1.8}   # g CO2eq per GB
grid, ci = pick_cleanest_grid(clause, ci_now, egress_emissions=egress)
# grid='SE', ci=11.0   when the egress penalty is small
```

When `egress_emissions` is supplied, the selector adds the inter-site
egress charge to each candidate's CI before picking the cleanest;
this makes the routing decision honest at the facility meter
(Scope-3 emissions included).

### 2.3 M-Spatial audit

```python
from scheduler.spatial_routing import m_spatial_audit
import pandas as pd
job = pd.Series({"job_id": 42, "spatial_clause": "SE,CH,FR",
                  "home_grid": "PL", "transfer_size_gb": 5.0})
audit = m_spatial_audit(job, realised_grid="DE",
                         egress_emissions={("PL", "DE"): 17.7})
audit.nom_ic_violation        # True --- DE is not in the declared clause
audit.egress_charge_g_co2     # 88.5  (17.7 g/GB * 5 GB)
```

The audit is a one-shot record per dispatched job; the C2 paper's
`replay_spatial_sweep.py` driver aggregates these to a per-cell
NOM-IC violation rate that mirrors PECS's H2 hypothesis.

### 2.4 Per-grid-pair egress YAML

`configs/network/egress_emissions.yaml` carries 36 entries keyed by
`<SRC>_to_<DST>` (e.g. `PL_to_SE: 0.7`).  Calibration: 0.06 kWh per
GB at the European backbone (Aslan et al., 2017) times the
destination grid's CI.  Self-loops are zero by convention; missing
pairs default to 0.0.  See
[`RATIONALE.md`](RATIONALE.md) for the choice of
the 0.06 kWh/GB anchor.

### 2.5 Spatial sweep driver

```bash
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/multicountry/replay_spatial_sweep.py \
    --jobs gridpilot/data/traces/m100_real_jobs.parquet \
    --output-dir gridpilot/data/m100/spatial_sweep/ \
    --force
```

Sweep dimensions: 6 grids × 3 MW × 3 egress regimes × 8 seeds = 432
cells (~30 s on 4 workers in this v0.1 shell; the full sweep with
PECS-style cell-level dispatch will be ~25 min in the C2 P3 phase).

Output:

- `data/m100/spatial_sweep/spatial_sweep.csv` — one row per
  (home_grid, mw, egress_regime, seed); columns:
  `dest_<CC>` per destination grid (count of T5-eligible jobs routed
  there), `egress_total_g_co2`.
- `data/m100/spatial_sweep/RUN_MANIFEST.json` — git SHA, command
  line, args, Python version, hostname, wall-clock time.

Default paths are anchored at the gridpilot/ root so the driver
runs from either the workspace root or from inside gridpilot/.

## 3. Workflow-conditional DAG primitives

### 3.1 `WorkflowDAG` abstraction

```python
from scheduler.workflow_dag import (
    ConditionalEdge, JobSpec, WorkflowDAG,
)
dag = WorkflowDAG()
dag.add_node(JobSpec(node_id=0, job_id=1, runtime_s=3600.0,
                       num_nodes_alloc=4, tier=2, name="train_segment_1"))
dag.add_node(JobSpec(node_id=1, job_id=2, runtime_s=900.0,
                       num_nodes_alloc=1, tier=2, name="eval_1"))
dag.add_edge(ConditionalEdge(0, 1, p=1.0, trigger="default"))
```

Conditional edges carry a branching probability `p` *and* a trigger
label.  At runtime the DAG is materialised by `realise(rng,
parent_result={0: "loss_plateaued"})`, which keeps only edges whose
trigger matches the parent's result and whose `p` random Bernoulli
fires.  PCAPS-style static DAGs are recovered by setting every
trigger to `"default"` and every `p` to 1.0.

### 3.2 M-Workflow audit

```python
from scheduler.dag_mechanisms import m_workflow_audit
declared = {"default": 0.50, "early_stopped": 0.50}
realised = {"default": 0.95, "early_stopped": 0.05}   # over-claimed flex
audit = m_workflow_audit(
    job_id=42, declared_p=declared, realised_p=realised,
    credit_rate_per_hour=0.06, parent_runtime_h=4.0,
)
audit.kl_divergence       # ~0.44 nats
audit.penalty_credit_hours  # 0.06 * 4.0 * 0.44
audit.nom_ic_violation    # True (KL > default threshold 0.10)
```

The KL-divergence audit penalises the user proportional to how far
the realised branching distribution diverges from the declared one,
weighted by the credit-rate × parent-runtime to keep the penalty
unit-consistent with the credits being clawed back.

### 3.3 Synthetic DAG generators

Three generators ship under `scripts/workflows/`:

- `synth_hpo_dag.py` — Optuna-TPE-style 100-trial sweep with early
  stopping (config: `hpo_optuna_tpe.yaml`).
- `synth_train_restart_dag.py` — 4-segment training with conditional
  checkpoint-restart at higher GPU utilisation (config:
  `train_restart.yaml`).
- An HPCG-class workflow generator is the obvious next addition;
  the config (`hpcg_workflow.yaml`) is already in place.

### 3.4 Workflow replay driver

```bash
PYTHONPATH=gridpilot/src python3 gridpilot/scripts/workflows/synth_hpo_dag.py \
    --out /tmp/hpo.json
PYTHONPATH=gridpilot/src python3 gridpilot/scripts/workflows/replay_workflow_sweep.py \
    --dag-json /tmp/hpo.json \
    --early-stop-rate 0.5 \
    --out /tmp/hpo_sweep.json
```

The shell tests H3 (conditional DAGs unlock latent flexibility): an
HPO sweep declared as 100 × T2 jobs but with 50 % early-stop rate
produces realised flexibility equivalent to declaring the sweep as
a higher tier without any user changing their declaration.

## 4. Test coverage

The 16 new unit tests under `tests/` cover:

| File | Tests |
|---|---|
| `test_spatial_routing.py` | SpatialClause normalisation; pick_cleanest_grid with and without egress; assign_t5_spatial_eligibility marks correct fraction; m_spatial_audit violation detection; egress YAML self-loops + missing pairs |
| `test_workflow_dag.py` | DAG roots/children queries; realise() with default and conditional triggers; probability-within-bounds across 200 seeds; unknown-node-edge rejection; to_networkx() round-trip |
| `test_dag_mechanisms.py` | KL zero on identical; KL positive on distinct; penalty scales with parent runtime; NOM-IC threshold |

All 16 pass alongside the 54 existing tests (70 total) in ~5 s.

## 5. Open questions for the P3 experimental campaign

The plan in `_dev_archive/PAPER_C2_PLAN.md` enumerates four pre-
registered hypotheses (H1 compounding, H2 egress threshold, H3 DAG
flexibility, H4 sovereignty graceful degradation).  The v0.1
scaffolding answers none of them — it provides the primitives, the
sweep driver, and the test coverage.  Filling in the experimental
results is the P3 phase.

The minimal additional engineering work for P3 (estimated 1–2 weeks):

1. Wire `replay_spatial_sweep.py` into the existing
   `replay_proact_opt_pue` per-destination-grid dispatcher so a
   T5-eligible job's *actual* energy and CO₂ are computed at the
   destination grid (currently the v0.1 shell only computes the
   *routing decision*, not the dispatch energy).
2. Extend `replay_workflow_sweep.py` to feed the realised DAG nodes
   through the same dispatcher (so workflow flexibility is measured
   end-to-end against M100 CI signals).
3. Add a `fig_egress_threshold_E_star.py` figure script that runs
   a range of egress regimes and finds the threshold E* at which
   M-Spatial's CFE-lift drops below M3 alone (H2).

## 6. References

- Hanafy et al., *GAIA: Going Green for Less Green*, ASPLOS 2024.
  Anchor for spatial routing.
- Lechowicz et al., *Carbon-Aware Online Scheduling of Precedence-
  Constrained Workflows*, SIGCOMM 2024.  Anchor for workflow DAGs.
- Babaioff et al., *Truthful Online Scheduling*, EC 2022.  Sufficient
  condition for monotone-credit-schedule incentive compatibility.
- Psomas, Verma & Zampetakis, *Non-Obvious Manipulability*, EC 2022.
  NOM-IC framework.
- Aslan et al., *Electricity Intensity of Internet Data Transmission*,
  J. Industrial Ecology, 2017.  0.06 kWh/GB backbone calibration.
