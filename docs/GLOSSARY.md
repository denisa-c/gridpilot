# Glossary

Acronyms and key terms used across the GridPilot kit and the two
companion Euro-Par 2026 papers.

For full design rationale see [`RATIONALE.md`](RATIONALE.md); for the
reproduction walkthrough see [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md).

---

## Mechanism design

| Term | Expansion | Meaning here |
|---|---|---|
| **IC** | Incentive-Compatible | a mechanism in which truthful declaration is a best response |
| **NOM-IC** | Non-Obviously-Manipulable Incentive-Compatible | weaker than full IC; no one-tier deviation strictly improves utility (Psomas et al., EC 2022) |
| **VCG** | Vickrey-Clarke-Groves | the canonical strategy-proof mechanism with monetary transfers; rejected in GridPilot because payment-free is required for academic HPC |
| **DAA** | Deferred-Acceptance Auction | the M2 mechanism plug-in; strategy-proof in the full-information regime (Bichler et al.) |
| **SWF** | Social Welfare Function | the optimisation objective in M2; we compare the α-fair family (utilitarian, α=0.5, Nash, leximin) |
| **Jain** | Jain's fairness index | $\bigl(\sum x_i\bigr)^2 \big/ \bigl(n \sum x_i^2\bigr)$; reported as a sanity check on every PECS result |

## f-SLA contract

| Term | Meaning |
|---|---|
| **f-SLA** | the *flexible Service-Level Agreement*: the user-side contract introduced in the PECS paper |
| **Tier** | one of T0..T5; the user-declared deferrability/elasticity/spatial class |
| **T0..T5** | T0 rigid, T1 hour, T2 day, T3 week, T4 elastic burst, T5 spatial |
| **Window $W_j$** | the deferral / elastic / spatial window declared by tier (0 h..7 d) |
| **Slowdown clause $s_j^{\max}$** | the maximum acceptable job-slowdown ratio the user accepts |
| **Service-credit rate $\alpha_k$** | per-deferred-hour credit a user earns for tier $k$; monotone in tier index |
| **Checkpoint bonus** | the fixed 0.5 credit T3 jobs receive for being checkpointable |
| **Spatial clause $G_j$** | the non-empty set of grid codes a T5 job declares acceptable (e.g. `{SE, CH, FR}`) |
| **Spatial exclusion** | a GDPR-style data-sovereignty list of forbidden grids (e.g. `{DE}`) |
| **Egress emissions** | data-transfer CO₂ charged on inter-site routing (g CO₂eq per GB) |
| **M0..M3** | the four anti-gaming mechanism plug-ins (posted price, BlindTrust, DAA, AI-baseline audit) |
| **M-Spatial / M-Workflow** | the two new C2-follow-on mechanisms |
| **AI baseline** | the submit-time AI-predicted tier shown to the user; the audit signal for M3 |
| **NOM-IC violation** | a job whose realised tier outcome would have been strictly improved by a one-tier deviation |

## Carbon-aware metrics

| Term | Expansion | Meaning |
|---|---|---|
| **CI** | Carbon Intensity | g CO₂eq per kWh of electricity at a grid at a point in time |
| **CFE** | Carbon-Free Energy share | fraction of compute energy served by carbon-free electricity (Kamatar et al.); the **primary** PECS metric |
| **Absolute CFE** | fraction of energy below 150 g CO₂eq/kWh (EU 2030 target) |
| **Energy-weighted effective grid CI** | the mean grid CI experienced by completed jobs, weighted by their energy consumption (g/kWh) |
| **ΔCO₂%** | percentage CO₂ reduction relative to a baseline policy; reported but *not* primary (inherits static-PUE assumption) |
| **Avoided tonnage** | annualised CO₂ avoided in kt/y |
| **Demand flexibility** | annual GWh that the contract makes movable across hours |

## Workload-flexibility taxonomy (PECS Fig. workloads)

| Class | Fraction of GPU·h | Maps to tier |
|---|---|---|
| Interactive / urgent | < 5 % | T0 rigid |
| Workflow-coupled | 5–10 % | T1 hour |
| Elastic AI / HPC | 35–50 % | T2 day, T4 elastic burst |
| Batch / parallel | 10–20 % | T3 week |
| Geo-shiftable | 5–15 % | T5 spatial |

## Frequency response (WHPC paper)

| Term | Expansion | Meaning |
|---|---|---|
| **FR** | Frequency Response | grid service: adjust facility power within a deadline of a frequency-deviation trigger |
| **FCR** | Frequency Containment Reserve | the 30 s tier of FR services |
| **FFR** | Fast Frequency Reserve | the Nordic 700 ms tier (the strictest published European budget) |
| **aFRR / mFRR** | automatic / manual FR Reserve | 5 min / 12.5 min FR products |
| **TSO** | Transmission System Operator | the entity that procures FR (e.g. Statnett, RTE, Terna, …) |
| **DVFS** | Dynamic Voltage and Frequency Scaling | GPU DVFS via NVML cap-update |
| **NVML** | NVIDIA Management Library | the low-level API for `nvidia-smi -pl` cap updates; worst-case cap latency ~5 ms |
| **PID** | Proportional-Integral-Derivative | Tier-1 controller in WHPC |
| **AR(p)** | Autoregressive model of order p | Tier-2 controller (AR(4)) in WHPC |
| **RLS** | Recursive Least Squares | fits the AR(4) coefficients on a 30 s rolling window |
| **AIC** | Akaike Information Criterion | model-order selection for AR(p) |
| **TLA⁺** | Temporal Logic of Actions | the formal liveness spec the safety-island bypass satisfies |

## Cooling and PUE

| Term | Expansion | Meaning |
|---|---|---|
| **PUE** | Power Usage Effectiveness | facility power divided by IT power; a measure of cooling overhead |
| **Instantaneous PUE** | time-varying PUE that the WHPC paper's four-component model exposes; binds the FR commitment at the facility meter |
| **Free cooling** | direct outdoor-air cooling when $T_{\mathrm{amb}} < $ wet-bulb threshold (12 °C) |
| **L² / L³ floors** | the affinity-law floors that bind cooling power (pump 20 %, air 15 %) before IT power does |
| **Marconi100 / M100** | the bundled production HPC trace and the calibration anchor for the cooling model |

## Hardware and HPC infrastructure

| Term | Expansion | Meaning |
|---|---|---|
| **V100** | NVIDIA Volta-class GPU | the 3-GPU testbed for the WHPC paper's E1–E7 campaign |
| **H100/H200/MI300** | NVIDIA Hopper / AMD Instinct | next-generation accelerators with 1.5–2× higher power swings |
| **M100** | Marconi100 | the bundled CINECA production trace (Antici et al. 2023) |
| **EuroHPC JU** | European High-Performance Computing Joint Undertaking | funds SEANERGYS |
| **SEANERGYS** | Software for Efficient and Energy-Aware Supercomputers | the EuroHPC JU energy-aware HPC stack; reference architecture is CMI + AIDAS + DSRM |
| **CMI** | Comprehensive Monitoring Infrastructure | the telemetry layer of SEANERGYS |
| **AIDAS** | AI Data Analytics System | the model-serving layer of SEANERGYS |
| **DSRM** | Dynamic Scheduling and Resource Manager | the scheduling layer; the f-SLA slots in here |
| **EAR** | Energy Aware Runtime | BSC's production runtime; deployed at MareNostrum and LUMI |
| **GEOPM** | Global Extensible Open Power Manager | open-source power-management runtime |
| **LDMS** | Lightweight Distributed Metric Service | telemetry service |
| **ExaDigiT / RAPS** | exascale digital twin / Resource and Application Profiling Service | the upstream digital-twin framework (Brewer et al. 2024) |
| **Slurm spank** | Slurm Plug-in Architecture for Node and job Kontrol | the Python-plugin hook layer Springborg et al. demonstrate |
| **Slinky** | SchedMD/NVIDIA Slurm-in-Kubernetes integration | the modern admission-webhook path |

## Grid codes

| Code | Country | 2025 mean CI (g CO₂eq/kWh) |
|---|---|---|
| SE | Sweden | 11 |
| CH | Switzerland | 30 |
| FR | France | 53 |
| IT | Italy | 258 |
| DE | Germany | 295 |
| PL | Poland | 612 |

Per-country CI configs live under `configs/grids/<CC>.yaml`; the
ENTSO-E A75 endpoint is used for the live-fetch path (set
`ENTSOE_API_KEY` to enable).

## Datasets and standards

| Term | Meaning |
|---|---|
| **ENTSO-E** | European Network of Transmission System Operators for Electricity; the *A75* (Actual Generation per Production Type) endpoint is what the fetcher queries |
| **A75** | ENTSO-E API endpoint for the per-fuel-type generation mix |
| **IPCC AR5** | the lifecycle CO₂-emission factors used by the fetcher to convert generation mix to grid CI |
| **EEA** | European Environment Agency; source of 2024 country-mean CI profiles |
| **Ember** | UK-based think-tank; an alternative source of country-mean CI |
| **PM100** | the published Marconi100 telemetry dataset (Antici et al. 2023) |
| **Scope 2 / Scope 3** | the GHG-Protocol scopes; Scope-2 is purchased electricity emissions, Scope-3 is upstream (e.g. inter-DC data transfer) |

## Repository conventions

| Term | Meaning |
|---|---|
| **`RUN_MANIFEST.json`** | a per-experiment provenance file (git SHA + command line + wall-clock time + n_cells); presence indicates a completed real-data run |
| **Stub mode** | `bash scripts/run_all_experiments.sh stub`; literature-anchored seeders produce fixed CSVs; the PDF renders a red provenance banner |
| **Real-data mode** | `bash scripts/run_all_experiments.sh` (default); real M100 replays; neutral grey banner |
| **`FRESH=1`** | env var that forces rerun of completed steps |
| **`FORCE=1`** | env var that passes `--force` to the replay drivers in stub mode |
| **Per-cell checkpoint** | `data/m100/country_sweep/cells/<cell-id>.json`; lets the multi-country sweep resume after a kill |
| **`results.tex`** | auto-generated LaTeX macro file the papers `\input{}`; contains every headline number; there are no hard-coded numbers in the body |
| **`\StubDataPresent`** | the boolean macro the papers render the data-provenance banner from |
