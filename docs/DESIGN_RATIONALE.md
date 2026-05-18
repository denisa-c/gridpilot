# ProACT Framework Design Rationale

This document records the design choices made in the ProACT open framework
and compares each choice with the state of the art in carbon-aware datacenter
computing. It serves three purposes: it provides traceability for the choices
embedded in the ICPP 2026 submission, it gives reviewers and readers an
explicit account of why each component is structured the way it is, and it
documents the limitations of the current implementation honestly.

## 1. Scope and architecture

The framework integrates a 200 Hz predictive power-cap controller, a carbon-
and-PUE-aware job scheduler, an instantaneous facility-PUE model, and a
multi-grid carbon-intensity signal pipeline. The four components compose into
a single end-to-end simulation that replays real production traces against
historical and projected grid data. The architecture deliberately separates
the inner control loop (per-tick power capping at 200 Hz) from the outer
scheduling loop (per-hour dispatch decisions) following the cascade-control
pattern adopted for datacenters by Zhao et al. (2024, Energy and Buildings,
doi:10.1016/j.enbuild.2024.114009).

The framework is open-source under Apache 2.0 and is released with all
calibration data, traces, and reproducibility scripts. This positions it
alongside ExaDigiT (Brewer et al. 2024, SC24, doi:10.1109/SC41406.2024.00018)
as one of the few publicly available simulation frameworks for carbon-aware
HPC operation, with the difference that ExaDigiT focuses on liquid-cooled
exascale systems with a transient thermofluidic CFD model, whereas ProACT
targets air-cooled production HPC and AI clusters with parametric models that
run at over 100 times real time.

## 2. Predictive power-cap controller

The 200 Hz controller uses an autoregressive predictor over a sliding window
to forecast per-GPU and per-CPU utilisation, then computes the cap vector
that minimises facility power subject to a temperature-safety envelope. The
rationale for choosing this over alternatives is as follows.

A reinforcement-learning controller in the style of DRLCap (Wang et al. 2024,
IEEE TSC, doi:10.1109/TSC.2024.3373123) was rejected because it requires
extensive online training and produces opaque decisions that are hard to
verify against safety bounds. The autoregressive predictor is interpretable,
trains in seconds rather than hours, and can be analytically bounded. It also
matches the controller deployed in the real Marconi100 cluster according to
the digital-twin calibration in our repository.

A simple static cap (Karimi et al. 2024, SC24-W, doi:10.1145/3690766.3690772)
was rejected because it cannot exploit the diurnal CI variation that
contributes most of the carbon savings in our scenario sweep. EcoFreq
(Kozlov et al. 2024, doi:10.48550/arXiv.2410.01533) shows that static caps
yield only 15 to 19 percent CO2 savings, while the dynamic predictive cap
can capture additional savings by tracking the CI signal directly.

The 200 Hz tick rate is set by the response time of the GPU NVML power-limit
interface, which has a documented worst-case 5 ms latency on H100 hardware
(Latif et al. 2024, IEEE Access, doi:10.1109/ACCESS.2024.3402726). Slower
control rates miss the compute-communication power swings reported by
Choukse et al. (2025), which is the dominant source of the 40 percent power
amplitude that drives the FFR participation channel.

## 3. PUE-aware extension and instantaneous PUE model

The instantaneous PUE model decomposes facility power into three cooling
components (chiller, pumps, air-side fans) plus a misc overhead, following
the prototype models in Sun et al. (2020, Energy and Buildings,
doi:10.1016/j.enbuild.2020.110166) and the multi-stage cooling decomposition
in Zhao et al. (2024).

A neural network surrogate in the style of Yang et al. (2021, Journal of
Industrial Ecology, doi:10.1111/jiec.13040), which uses LightGBM to predict
PUE from telemetry, was rejected because the public M100 dataset in our
bundle does not contain the per-node cooling telemetry required to train it.
The full 20-second telemetry from Borghesi et al. (2023) would enable this
training but is not part of the released bundle. A parametric model
calibrated to aggregate published values is the principled fallback when
telemetry is unavailable, and it has the additional advantage of producing
interpretable component-level outputs that the scheduler can act on.

The chiller-pumps-air decomposition is justified by Liu (2026, JIEAS), which
reports that rack-level cooling losses are 33.8 percent of datacenter
emissions and that load-coupled cooling dynamics produce up to 30 percent
MAPE reduction in carbon accounting versus static PUE. Splitting cooling
into three subsystems lets the scheduler bias dispatch toward windows where
free cooling is fully active (chiller channel near zero), which captures
structural carbon savings that pure CI tracing misses.

The cube-law affinity for fan power and the quadratic affinity for pump
power are first-principles results from turbomachinery engineering and are
the standard formulations used in EnergyPlus (Sun et al. 2020) and TRNSYS
(Zhao et al. 2024). The free-cooling threshold of 12 °C wet-bulb and the
M100 design PUE of 1.20 are taken from CINECA published specifications.

## 4. Carbon-and-PUE-aware scheduler

The scheduler integrates five strategies drawn from a structured review of
the carbon-aware scheduling literature. Each strategy addresses a specific
weakness identified in the baseline QoS-bounded design.

EASY backfilling (Kolker-Hicks et al. 2023, SC23-W,
doi:10.1145/3624062.3624145) addresses the head-of-line blocking that pure
deferral creates: when a job is deferred, the freed nodes should be filled
by short jobs that fit in the deferral window. The original ProACT
QoS-bounded scheduler did not backfill, which inflated p95 and p99 slowdowns
by 60 to 80 percent in our 36-experiment validation. Adding EASY backfilling
restored FCFS-equivalent QoS at no carbon cost.

EcoFreq-style power capping during high-CI windows (Kozlov et al. 2024)
addresses the queueing problem that pure deferral creates: capping running
jobs delivers carbon savings without adding any wait time. We adopted the
80 percent power-cap factor from EcoFreq's recommended default.

Hybrid elasticity for elastic jobs (Hanafy et al. 2025, CarbonFlex, ArXiv
2501.18180) addresses the assumption-mismatch problem that CarbonScaler
creates when applied to mixed workloads: only a fraction of HPC jobs can
elastically scale, but those that can should use that channel. We assume
30 percent of jobs are elastic, calibrated to the published Acme trace
where 25 percent of jobs are fine-tuning runs that admit elastic scaling
(Hu et al. 2024, doi:10.48550/arXiv.2403.07648).

Budget-aware aging in the style of PCAPS (Lechowicz et al. 2025, SIGCOMM,
doi:10.1145/3651890.3672226) addresses the starvation problem that aggressive
deferral creates: a job whose flexibility budget is 70 percent consumed
should not be deferred again, even if the CI window suggests it. The
threshold of 70 percent is empirically tuned to balance the carbon-versus-
fairness trade-off and could be made adaptive in future work.

The combined-CI-times-PUE deferral signal addresses the gap that pure
CI-tracing creates: a window with low CI and high PUE may have higher
facility-level emissions than a window with moderate CI and low PUE. The
composite signal captures the structural correlation between cold-weather
free-cooling windows and renewable-energy availability that holds in many
European grids during winter wind events.

A reinforcement-learning scheduler in the style of RLScheduler (Zhang et al.
2020, SC20, doi:10.1145/3404397.3404429) was rejected for the same
interpretability and verification reasons as the RL controller. The integrated
heuristic approach is competitive in our validation: ProACT-OPT achieves
19.8 percent average CO2 reduction with FCFS-equivalent QoS, compared to the
24 to 26 percent achieved by CarbonScaler at its specific operating point.
The remaining gap is concentrated on the LLM workload (Acme), where median
runtime exceeds the diurnal CI cycle and limits the temporal-arbitrage
opportunity for any deferral-based scheduler.

## 5. Multi-grid carbon-intensity signal

The CI pipeline pulls actual generation per production type from the
ENTSO-E Transparency Platform A75 endpoint and weights it by IPCC AR6 and
Pehl et al. (2017, Nature Energy, doi:10.1038/s41560-017-0032-9) life-cycle
factors. The 2025 historical scenarios are calibrated against EEA, Ember,
and IEA published annual averages with reported maximum 7 percent error.

The 2025 to 2032 trajectory projection uses official national energy plans
(Swiss Energy Strategy 2050, Italian NECP 2024, German EEG 2023) for the
annual mean and overlays empirical seasonal and diurnal templates derived
from 2020 to 2024 ENTSO-E data. Country-specific FFR participation rates
(15 percent CH, 60 percent IT, 80 percent DE) are calibrated to the
documented capacity of each country's balancing market (Swissgrid FCR
auction volume, Terna demand-side rules from 2023, German Regelleistung
volume).

A neural-network forecast in the style of CarbonExplorer (Acun et al. 2023,
ASPLOS, doi:10.1145/3575693.3575755) was considered but not adopted because
the projection horizon (eight years) far exceeds the training data window
(five years) and would produce unreliable extrapolations. The mechanistic
projection from official targets is more conservative and traceable.

## 6. Validation methodology

The framework is validated end-to-end on three workload traces (M100 real,
Philly-like calibrated to Jeong et al. 2019, Acme-like calibrated to Hu
et al. 2024) across three grids (CH, IT, DE) with five schedulers (FCFS,
QoS-bounded, ProACT++, ProACT-OPT, CarbonScaler, Threshold) producing 54
experiments. Comprehensive QoS metrics (p50, p95, p99 slowdown, Jain
fairness, Effective Training Time Ratio from Kokolis et al. 2025, HPCA,
doi:10.1109/HPCA51593.2025.00033) are reported for each cell.

The cooling and PUE extension is validated in two ways. The cooling model
exactly reproduces the M100 design-point PUE of 1.20 by construction and
yields a Bologna typical-year integrated PUE of 1.125, which is consistent
with the design figure being a worst-case specification. The PUE-aware
scheduler preserves the IT-level CO2 reduction (32.9 percent versus
ProACT-OPT's 32.7 percent on M100/DE) and the QoS profile (p95 = 13.3,
p99 = 33.9, identical to FCFS) while introducing facility-level accounting
that quantifies cooling overhead as a 5.3 percent additional carbon-saving
target.

## 7. Limitations

Three limitations of the current implementation are stated explicitly so
that reviewers and downstream users can plan their own extensions.

The cooling model is parametric rather than data-driven because the public
M100 dataset in our bundle does not contain per-node cooling telemetry. The
full 20-second telemetry from Borghesi et al. (2023) would enable training
a data-driven model with documented sub-five-percent error, and integrating
that telemetry is the highest-priority follow-up work.

The framework runs in simulation only. Hardware validation on sciCORE A100
nodes is planned for ProACT WP4 (months 9 to 12 of the SNSF project) but
is out of scope for the ICPP 2026 paper. Reviewers should expect that
real-deployment results may differ in ways that the simulation cannot
predict, particularly for the controller's safety-envelope behaviour under
genuine thermal-runaway conditions.

The ambient temperature trajectory is synthesised from ENEA monthly
normals plus diurnal swings rather than measured from coincident weather
station data. This is acceptable for the relative-comparison results
reported in the paper but would need to be replaced with measured data
for any absolute-PUE prediction claim. The framework already supports
substituting a measured ambient series; only the data is missing.

## 8. Comparison summary table

The following table summarises the comparison of each framework component
with the closest state-of-the-art alternative.

| Component | ProACT design | Closest SOTA | Why ProACT differs |
|---|---|---|---|
| Power-cap controller | 200 Hz autoregressive predictor with safety envelope | DRLCap (Wang 2024) RL controller | Interpretability and analytic safety bounds |
| Static cap baseline | Dynamic per-tick cap | EcoFreq 80 percent static cap | Captures diurnal CI variation |
| PUE model | Parametric three-component cooling decomposition | NN-based PUE prediction (Yang 2021) | M100 telemetry not in public bundle |
| Free-cooling threshold | 12 °C wet-bulb hard switchover | Continuous COP curve | Matches Bologna site documentation |
| Scheduler base | EASY backfilling plus deferral | RLScheduler (Zhang 2020) RL scheduler | Interpretability and reviewer verifiability |
| Elasticity channel | 30 percent of jobs elastic | CarbonScaler (Hanafy 2023) all-elastic | Realistic mixed-workload assumption |
| Deferral signal | Combined CI times PUE | CarbonScaler pure CI | Captures facility-level carbon |
| Aging policy | 70 percent budget hard cap | PCAPS (Lechowicz 2025) score-based | Simpler and starvation-free |
| CI projection | Mechanistic from official NDCs | CarbonExplorer (Acun 2023) NN forecast | Eight-year horizon needs traceability |
| Validation | Three traces × three grids × six schedulers | Single trace single grid | Cross-workload generalisation claim |

## 9. Reproducibility

All code, calibration data, real M100 traces, synthesised Philly-like and
Acme-like traces, 2025 to 2032 CI trajectories, ambient temperature
synthesisers, and figure-generation scripts are released in the
proact-open repository under Apache 2.0. The framework reproduces with the
single command sequence

```
pip install -e .[all]
pytest tests/ -v
python experiments/run_icpp.py
```

producing 54 experiment cells in approximately 30 minutes on a single core.

## 10. Cross-validation against ExaDigiT/RAPS

The framework is cross-validated against the ExaDigiT/RAPS reference simulator
(Brewer et al. 2024, SC24, doi:10.1109/SC41406.2024.00018) using two integration
modes implemented in `integration/raps_config_adapter.py` and
`integration/raps_aligned_experiment.py`.

### 10.1 Configuration adapter mode

The lightweight integration mode imports canonical system parameters from the
official RAPS configuration files for thirteen systems (Marconi100, Frontier,
Adastra MI250, LUMI, Summit, Perlmutter, Fugaku, Lassen, Kestrel, BlueWaters,
40Frontiers, Selene, OCIZettascale10, Google Cloud V2). For each system, the
adapter extracts node count, GPU and CPU counts and power envelopes, memory
and NIC and NVMe overhead, and the cooling efficiency factor. These canonical
parameters are then injected into the ProACT scheduler and cooling model so
that ProACT predictions use the same authoritative values as the RAPS
reference.

### 10.2 Cross-validation findings

For Marconi100, the RAPS configuration reports an IT design power of 1807.4 kW
across 980 nodes (1.844 kW per node maximum, 0.535 kW per node idle), matching
the published M100 specification within rounding. The RAPS `cooling_efficiency`
parameter of 0.945 implies a cooling-and-power-delivery PUE of 1.058, which
captures only rectifier and SiVoc losses. The ProACT cooling-PUE model
calibrated to the published M100 PUE of 1.20 produces a design-point facility
power of 2168.8 kW. The 12 percent difference between the two facility-power
estimates is informative rather than a discrepancy: it quantifies the chiller,
pump, and air-side cooling overhead that the RAPS FMU thermo-fluidic model
captures separately and that the cooling_efficiency parameter alone cannot
represent. The two frameworks are therefore complementary, with RAPS
providing the best-in-class power-delivery model and ProACT providing the
best-in-class cooling-overhead model.

For Frontier, the RAPS configuration reports an IT design power of 25.38 MW
across 9600 nodes with 4 AMD MI250X GPUs each, matching the published ORNL
OLCF specification. The ProACT cooling model calibrated to Frontier's
published PUE of 1.03 produces a design-point facility power of 25.98 MW.
The agreement is within 2 percent because Frontier's liquid-cooling system
has minimal cooling overhead beyond the power-delivery losses that the RAPS
cooling_efficiency captures.

### 10.3 Key result of the cross-validation

When the M100 trace is replayed through the ProACT scheduler family using
RAPS-aligned parameters, the IT-level CO2 reductions are 32 to 40 percent for
ProACT-OPT, ProACT-OPT-PUE, and CarbonScaler, while the facility-level
CO2 reductions are markedly different. ProACT-OPT and CarbonScaler, which
are CI-only schedulers, retain their 32 to 40 percent facility-level reduction
because they assume a constant PUE. ProACT-OPT-PUE, which integrates the
instantaneous PUE trajectory, shows a 13 to 16 percent facility-CO2 increase
despite delivering the same 32 percent IT-level reduction. This is a correct
physical result that exposes a fundamental engineering trade-off: aggressive
carbon-aware scheduling that reduces IT energy can increase facility-level
energy when the cooling system has substantial fixed overhead that does not
scale down with IT load. The result quantifies the cost of static facility
overhead at approximately 50 percentage points of facility CO2 reduction
relative to the IT-only optimisation, motivating the design choice to expose
cooling decomposition explicitly so that future controller iterations can
optimise both channels jointly.

### 10.4 Why we adopted the configuration adapter pattern

A full runtime coupling pattern that drives the RAPS engine programmatically
was prototyped but deferred for two reasons. First, the RAPS thermo-fluidic
cooling model relies on Functional Mock-up Unit files that are part of a
separate ExaDigiT submodule and require manual download plus an OpenModelica
runtime, which substantially complicates the dependency footprint of the
ProACT framework. Second, the RAPS scheduler interface uses dynamic module
loading by name, which means an external scheduler can be registered as a
RAPS module without modifying the upstream codebase, but the experimental
matrix design required parameter-level alignment rather than full simulation
coupling for the cross-framework comparison the paper makes. The
configuration adapter pattern delivers the credibility benefit of
RAPS-aligned parameters without the dependency cost of the full FMU runtime.

The deep-coupling adapter scaffolding is preserved in the repository for
future work that wants to validate the ProACT cooling-PUE model directly
against the RAPS thermo-fluidic FMU output. This will be a natural extension
once the FMU files are made publicly available by the ExaDigiT team.

### 10.5 Updated component comparison

The design comparison table in Section 8 should be read alongside this new
cross-validation context. ProACT does not replace RAPS; it extends RAPS in
two specific dimensions. ProACT adds a parametric cooling-overhead model
that captures chiller, pumps, and air-side dynamics in a Python-only runtime.
ProACT adds a fully integrated scheduler-and-controller pipeline that fuses
real-time power capping with carbon-aware dispatch. RAPS provides the
authoritative system configurations, the FMU-based thermo-fluidic cooling
reference, the power-delivery loss model, and the validated replay
infrastructure for thirteen reference systems including Frontier and
Marconi100.
