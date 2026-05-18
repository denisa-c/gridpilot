# Known Limitations of the GridPilot Framework

This document is part of the reproducibility kit and is intended to give external users a clear, honest accounting of where the framework's evidence is strong, where it is weaker than the paper might suggest, and where future work is required. It is structured by category and by the location in the paper or kit where the relevant claim is made.

## Validation Scope

GridPilot is a simulation framework. The 200 Hz Tier-1 PID controller, the 1 Hz Tier-2 AR(4) predictor, and the 0.001 Hz Tier-3 cluster optimiser have been validated in software against synthesised power, utilisation, temperature, carbon-intensity, and ancillary-services trajectories. None of the three controller tiers has been driven against real NVML interfaces, real cpuidle interfaces, or real ENTSO-E API streams in a closed-loop production environment. The 5 ms NVML response latency cited in Section 3.3 is the published worst-case from Latif et al. 2024 IEEE Access, not measured in this work. The 26.2 percent energy-savings figure for the Tier-1 PID gains is reproduced in calibration to MF-GPOEO Wang 2024 IEEE TSC, not measured. The framework is therefore best understood as a digital-twin and methodology contribution rather than as an operationally deployed system.

The hardware experiments specified in `hardware_experiment_setup.md` are the natural next step and are scheduled for offline execution by the PI. Once those experiments complete, the relevant claims in the paper can be upgraded from simulation-validated to hardware-validated and a journal-extension manuscript can incorporate the measurements.

## Workload Traces

The M100 trace at `data/traces/m100_real_jobs.parquet` contains 1,994 real SLURM job records from the CINECA Marconi100 GPU cluster published by Antici et al. 2023 PM100 dataset. The Philly-like trace at `data/traces/philly_like.parquet` and the Acme-like trace at `data/traces/acme_like.parquet` are calibrated synthetic traces produced from the published statistical descriptions in Jeon et al. 2019 ATC and Hu et al. 2024 respectively, not the original public datasets. The traces match the published distributional properties (median runtime, GPU-count distribution, job-mix proportions) but are not byte-for-byte reproductions of the published data. The paper text uses "Philly-like" and "Acme-like" consistently to avoid implying that the original traces were used. Researchers wanting to verify GridPilot against the original Philly trace can replace the file at `data/traces/philly_like.parquet` with the original Microsoft Philly download from https://github.com/msr-fiddle/philly-traces and re-run the 63-cell matrix without other code changes; the framework is trace-agnostic.

## Carbon-Intensity Synthesis

The grid CI trajectories in `data/grid_signals/` are constructed from EEA, Ember, and IEA published annual averages combined with diurnal templates derived from 2020-2024 ENTSO-E A75 actual-generation data. The framework does not currently replay actual minute-resolution ENTSO-E telemetry; it samples the diurnal template plus a stochastic modulation calibrated to the country's published renewable share. The error against actual ENTSO-E A75 ground truth has not been measured in this work because the live ENTSO-E API path has not been exercised end-to-end with a real API key. The hardware experiment set in `hardware_experiment_setup.md` includes an explicit live-API validation experiment that will produce the actual-versus-synthesised comparison and the corresponding error bound.

## Country-Parameter Sources

The 25-country parameter set in `src/integration/entsoe_connector.py` mixes published TSO documentation values with engineering estimates. The complete source attribution is documented in `docs/COUNTRY_PARAMETER_SOURCES.md`. Parameters labelled "TSO documentation" are sourced from official transmission-system-operator publications and have direct citation links. Parameters labelled "modelling assumption" are engineering estimates calibrated to the country's overall fuel mix and balancing-market structure but are not directly cited from a single source; these are most commonly the marginal-CI of the balancing reserve, which depends on the operational dispatch policy of the TSO and is not always publicly published.

## Sensitivity Analysis

The full Plackett-Burman 5-factor sensitivity analysis is documented in `data/results/sensitivity_analysis.csv` and visualised in `figures/fig_sensitivity_tornado.png`. The five factors swept are the chiller COP slope, the fan-power affinity exponent, the German FFR participation rate, the German balancing-reserve marginal CI, and the Tier-1 PID derivative gain. The result on the headline 50 MW Germany 2025 net carbon reduction (point estimate 26 percent) shows that the dominant sensitivities are the FFR participation rate (±5 percentage points across the swept range) and the marginal-CI of the balancing reserve (±3 percentage points), with the cooling-model coefficients and the controller gains showing main effects under ±1 percentage point. The qualitative ranking of countries by total committed capacity is preserved across the full sensitivity sweep. This justifies the conclusion that the cross-country structural results are robust, while acknowledging that the precise headline numbers are uncertain at the ±5-percentage-point level.

## Joint Operation Versus Additive Validation

The paper's "joint controller-and-scheduler" framing reflects the architecture but the validation experiments do not exercise the joint runtime operation. The 63-cell scheduler matrix runs the GridPilot-PUE scheduler at hourly dispatch resolution against synthesised CI signals; the 200 Hz Tier-1 controller and the 1 Hz Tier-2 predictor are documented in the architecture but are not active during those experiments. The multiscale controller validation (Section 3.3, Stage 7 of `reproduce_all.py`) runs the cascade against synthesised power, utilisation, and temperature trajectories independently of the scheduler. The integrated joint runtime is future work; the current paper validates the two layers separately and demonstrates that they compose by construction rather than by direct measurement.

## Failure-Mode Coverage

The cascade controller has been tested for nominal-case correctness (FFR provision quality, AR(4) accuracy, PID tracking error) but not for adversarial or failure conditions. The new tests at `tests/test_failure_modes.py` cover three additional cases: FFR signal arriving during a thermal-envelope activation, AR(4) predictor cold-start with insufficient history, and Tier-3 grid search returning no feasible operating point. These three tests pass in the current implementation. Other failure modes (NVML driver bugs, ENTSO-E API outages, cooling-system fault conditions) are not currently tested and are deferred to the hardware-experiment campaign.

## Live ENTSO-E API Path

The connector at `src/integration/entsoe_connector.py` supports two operating modes: synthesised (default, deterministic, used in the kit's tests and in the 25-country sweep) and live (requires `ENTSOE_API_KEY` environment variable). The live mode has been exercised structurally — the URL construction, the XML parsing, and the fallback-on-failure logic are all unit-tested — but not end-to-end with a real API key against real production endpoints. The hardware-experiment setup includes a 24-hour live-API run as the first activation experiment. Any divergence between the actual XML response format and our parser will surface in that experiment and can be patched offline.

## Cooling Model Extrapolation

The cooling-PUE model is calibrated to the M100 design specification (PUE 1.20 at 25°C ambient, full IT load) and validated against the 13 RAPS canonical configurations at the design-point. The model's extrapolation to a 50 MW hyperscale facility is structurally sound (the same equations apply at any scale) but the assumed Bologna ambient-temperature trajectory does not generalise to facilities at other locations. The free-cooling fraction in particular is highly site-dependent. Users running the framework for a non-Bologna site should replace `data/grid_signals/bologna_typical_year.csv` with the appropriate local weather data; the framework is location-agnostic in its equations.

## Items Explicitly Out of Scope

The following are documented as out of scope for the ICPP submission and the SNSF proposal v7 and are left to future work or to the SNSF-funded WP3 deliverables.

- Hardware closed-loop validation against real GPUs and real ENTSO-E API streams.
- Direct co-simulation against the ExaDigiT thermo-fluidic FMU (the FMU artefacts are not openly downloadable from the ORNL GitLab during the relevant working window).
- Live deployment in a production HPC facility with real workload pressure.
- Reinforcement-learning controller comparison (DRLCap-class) under matched workload conditions.
- Per-job carbon attribution at fine granularity (job-level rather than cluster-level).

## How to Address These Limitations

External users wanting to extend GridPilot to address any of these limitations should consult `hardware_experiment_setup.md` for the hardware-side experiments, `docs/CONFIGURE_NEW_COUNTRY.md` for adding non-built-in countries, `docs/DESIGN_RATIONALE.md` for the design choices that may be revisited, and the test suite at `tests/` for the patterns to follow when adding new validation cases. Pull requests against the GridPilot repository that close any of these gaps are welcome.
