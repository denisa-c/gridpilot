# Limitations and Lessons Learned

This document mirrors the *Discussion and limitations* section of
the two companion Euro-Par 2026 Workshop papers
(`papers/whpc2026/main.tex` and `papers/pecs2026/main.tex`).  We
document the limitations of GridPilot and the f-SLA contract
explicitly so reviewers and reproducers can calibrate their
expectations and so that follow-on research has a clear improvement
target.

---

## Limitations

### 1. Hardware-testbed scope

The E1–E7 measurement campaign uses a 3× V100-SXM2 32 GB testbed
(`ecocloud-exp06`, EPFL EcoCloud, April 2026). Three GPUs is sufficient
to validate per-GPU control (E2), host-tier prediction (E3, E4),
worst-case-fairness baseline (E6), and end-to-end actuation latency (E7),
but it cannot reproduce true rack-scale contention, cross-node
NVLink/InfiniBand power dynamics, or warm-water-cooling interaction
effects.

The paper's claims at rack/pod/cluster scale are therefore **simulation
projections anchored to per-node measurements**, not measured
cluster-scale results. A follow-on campaign on a 100–500 kW Tier-2
production cluster (e.g. EPFL Helvetios, UniBasel sciCORE, or CSCS Daint
segment) is the natural next step for ProACT WP3.

### 2. V100 vs. contemporary AI accelerators

V100 is the conservative validation target. Contemporary AI training
increasingly runs on H100 (700 W TDP), H200, MI300, MI325, and
Grace-Hopper, all of which exhibit substantially higher power swings —
Choukse et al. report 40% power swings on H100 training — and tighter
thermal envelopes.

The AR(4) predictor MAE of 4.69–19.66 W on V100 likely under-estimates
the residual on H100 by 1.5–2×. On H100 the cascade composition is
consequently *more* important rather than less.

We deliberately validated on V100 because:

1. it is widely available and supports the open NVML power-cap interface
   that other vendors do not yet match,
2. the published Marconi100 PM100 dataset (Antici et al. 2023) provides
   the cross-validation reference, and
3. the qualitative findings (cascade composition, FFR latency margin,
   fairness baseline) are platform-portable.

Quantitative replication on H100/H200 is open work.

### 3. Cross-validation axes

The RAPS cross-validation uses two axes (per-GPU mean power, 980-node
scaling envelope) and reports an *expected* below-band result on
Axis 1 (V100 best-efficiency cell at 121 W/GPU vs. M100 production median
237 W/GPU) because the E1 sweep deliberately probed the low-power regime.

Landing in-band requires repeating E1 at p_cap ≥ 250 W or selecting
the worst-efficiency cell. This is documented in
[`data/v100_raw/cross_validation/comparison_report.json`](data/v100_raw/cross_validation/comparison_report.json);
reviewers should not interpret the −48.85% Axis 1 result as a model
failure.

Axis 3 (AR(4) MAE on multi-phase) is V100-only because the M100 replay
path requires separate predictor instrumentation, deferred to ProACT
WP3.

### 4. Multi-scale projection assumptions

The 50 MW projections (paper Table 3) combine V100 measurements with
simulator outputs:

- per-node power coefficients fitted from the E1 sweep,
- RAPS-canonical PUE and cooling models for the 13 reference systems,
- ENTSO-E carbon-intensity projections for 2025/2028/2032 from
  BFE ES-2050 (CH), NECP 2024 (IT), and EEG 2023 (DE) policy targets.

The projection inherits each input's uncertainty:

- **±10%** on per-node power (RAPS validation)
- **±15%** on grid CI (policy-scenario uncertainty)
- **±5%** on FFR participation rate

These compound; the headline 26% net carbon reduction at 50 MW DE 2025
has a sensitivity envelope of **23% to 32%** across the 5-factor
Plackett-Burman sweep (paper Figure 10).

The cross-country ranking (DE > IT > CH) is preserved across the entire
envelope, but absolute percentages should be treated as **forward
indicators** rather than guaranteed savings.

### 5. Closed-loop runtime

Sections 6–6.2 of the paper use synthesised ENTSO-E trajectories rather
than live API streams in continuous operation. The framework supports
live API ingestion (validated against eight published literature
benchmarks; see paper Figure 3), but a multi-month closed-loop
deployment exercising the Tier-3 cluster optimiser against real-time
grid signals is the binding empirical gap that the broader ProACT
programme will close at the WP3 production milestone.

---

## Lessons Learned

Six findings from this campaign that we would have benefited from
knowing earlier and that we offer to follow-on researchers:

### Lesson 1 — The 5% closed-loop tracking-error threshold (E4) is a cascade-composition diagnostic, not a headline result.

When a workload exceeds 5%, it is not the controller failing; it is the
workload bimodality exceeding the inner-loop time-constant. The bursty
11.08% result is therefore a **feature**: it justifies the multi-tier
design rather than indicating poor performance. We recommend reporting
the threshold semantics explicitly because reviewers initially read the
bursty number as a failure mode.

### Lesson 2 — The Jain fairness index of 0.333 (E6) under naive static caps reflects single-GPU monopoly under heterogeneous-workload contention.

This baseline result motivates the scheduler's preference for declared-
deferrability annotations over uniform per-GPU caps. We recommend that
production deployments require workloads to declare their flexibility
class (matmul-bound / inference / bursty / steady-state) at submission
time so that the cluster optimiser can avoid this failure mode by
construction.

### Lesson 3 — The 97–98 ms FFR actuation latency (E7) is achievable only with a deterministic safety-island bypass.

Our initial Python-only implementation produced p99 latencies above
250 ms with occasional excursions over 500 ms (cf.
[`data/v100_raw/E7_ffr_latency/`](data/v100_raw/E7_ffr_latency/)
per-trial logs from earlier campaigns). The 7× Nordic-budget margin
reported in the paper is a property of the safety-island architecture,
not of NVML alone.

### Lesson 4 — Pareto-optimality at preserved QoS is the binding feasibility constraint, not absolute carbon-reduction percentage.

The first-come-first-served (FCFS) QoS preservation result (20% IT-CO₂
reduction at p95 = 13.1× slowdown) is more important than the headline
percentage. A scheduler that achieves 30% reduction at p95 = 100×
slowdown is operationally infeasible at most production sites.
The absolute carbon reduction percentage is secondary.

### Lesson 5 — IT-only carbon-reduction reporting overstates actual savings.

The IT-CO₂ vs. facility-CO₂ gap (5–14 percentage points) has direct
operational consequences. We recommend facility-level reporting as the
primary metric, supplemented by the IT-level number for comparison with
prior work that uses static-PUE assumptions.

CarbonScaler's reported facility savings (40–70% on Philly) are inflated
by static-PUE; honest accounting reveals 14% on Philly. This is why
GridPilot-PUE delivers 15.0% facility savings rather than the 37.3%
that GridPilot (without PUE awareness) appears to deliver.

### Lesson 6 — Both simulator-side (+9.9%) and hardware-side (+1.4%) RAPS cross-validations are valid; they measure complementary properties.

The simulator-side +9.9% on Marconi100 14-day facility energy
([`data/simulator_outputs/raps_cross_validation.csv`](data/simulator_outputs/raps_cross_validation.csv))
reflects integrated time-series tracking with PUE dynamics.

The hardware-side +1.4% on the 980-node scaling envelope
([`data/v100_raw/cross_validation/`](data/v100_raw/cross_validation/))
is a static design-point comparison.

Reviewers should not be surprised by the gap; both numbers are valid
for their respective comparison axes. Future cross-validations should
report both.

---

## Open invitation

If you reproduce GridPilot on H100 / H200 / MI300 / MI325, on a
production-scale cluster, or with continuous live-API operation, we want
to hear from you. Please open an issue or send your results to the
corresponding author (`denisa.constantinescu@epfl.ch`). Negative or
contradictory results are particularly valuable — see the
[CONTRIBUTING.md](CONTRIBUTING.md) workflow.
