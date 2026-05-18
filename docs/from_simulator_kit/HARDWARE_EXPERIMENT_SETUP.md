# Hardware Experiment Setup for Offline Execution

This document specifies the four hardware experiments required to upgrade the GridPilot validation from simulation-only to hardware-validated. Each experiment is described in enough detail that a researcher with GPU cluster access and an ENTSO-E API key can execute it without further design work, save the resulting telemetry to the kit's `data/hardware/` directory, and re-run the relevant analysis scripts to produce hardware-validated versions of the paper's figures.

The experiments are listed in priority order. Experiments 1 and 2 are individual-component validations; experiment 3 is the cascade integration; experiment 4 is the live grid-data validation. The total estimated execution time is 28 hours of GPU time plus 24 hours of wall time for the live grid-data run.

## Common Setup

All four experiments require the following common infrastructure.

The hardware platform should be at minimum one host with 8 NVIDIA H100 or A100 GPUs, dual EPYC or Xeon CPUs, 1 TB DDR5 memory, NVMe storage, and 200 Gbit/s NICs. Larger configurations (cluster scale) are needed for experiment 3 only.

The software platform should be Ubuntu 22.04 or 24.04 with NVIDIA driver 535+, CUDA 12.0+, NVML library accessible to the experimenter user, Python 3.10+, and the GridPilot reproducibility kit installed at a writable path.

The data-collection wrapper at `experiments/hardware/collect_telemetry.py` (provided in this kit) wraps any executable with NVML power and temperature logging at 1 kHz, CPU utilisation logging at 100 Hz, and a structured CSV output. Run as `python collect_telemetry.py --output telemetry.csv -- <your-program>`.

The ENTSO-E API key must be obtained from the ENTSO-E Transparency Platform (free registration at https://transparency.entsoe.eu/) and exported as `ENTSOE_API_KEY=<your-token>` before the live experiment.

## Experiment 1: Tier-1 PID Controller Hardware Tuning

The aim is to confirm that the Tier-1 PID gains (Kp=0.6, Ki=0.05, Kd=0.02) deliver stable closed-loop tracking on real NVML interfaces, and to document the actual settling time, overshoot, and disturbance-rejection properties.

The procedure runs four phases. In phase 1, baseline characterisation, run an LLM training workload (any standard reference such as Llama-3-8B fine-tuning) for 30 minutes without GridPilot active, recording NVML power, GPU temperature, and SM utilisation at 1 kHz. The output establishes the natural power-time signature and bounds the closed-loop disturbance amplitude that the controller must reject. In phase 2, step-response characterisation, run the controller with a series of step changes in the target power: 600 W to 400 W, 400 W to 700 W, 700 W to 300 W, holding each level for 60 seconds. Record the actual NVML power tracking the target, compute the rise time (time to reach 90 percent of the target), the settling time (time within ±2 percent of the target), and the steady-state error. The current simulation reports under 200 ms settling; the hardware target is under 500 ms with under ±10 W steady-state error. In phase 3, Ziegler-Nichols re-tuning, intentionally set Ki=0 and Kd=0, raise Kp until the system enters sustained oscillation, record the critical gain Ku and the period Pu, and apply the standard Ziegler-Nichols formulas (Kp=0.6 Ku, Ki=2 Kp/Pu, Kd=Kp Pu/8) to compute the hardware-tuned gains. Compare to the simulation defaults. In phase 4, disturbance rejection, run the controller during a sudden workload change (start of an all-reduce phase in distributed training) and verify that the safety envelope activates correctly when the GPU temperature exceeds 85°C.

The expected output is a CSV at `data/hardware/exp1_pid_tuning.csv` with the four-phase telemetry, a Python analysis script at `experiments/hardware/analyse_exp1.py`, and an updated tuning paragraph in the paper Section 3.3.2.

## Experiment 2: Tier-2 AR(4) Predictor on Real Workload Phases

The aim is to confirm that the AR(4) predictor MAE on real AI-training utilisation traces is comparable to the simulation result of 0.04, and to characterise the predictor's behaviour during the bimodal compute-communication phases that Choukse 2025 documents.

The procedure runs three phases. In phase 1, training-phase-resolved telemetry, run a multi-GPU LLM training workload with NCCL all-reduce for 60 minutes, logging GPU SM utilisation at 100 Hz. The output should reveal the per-iteration utilisation pattern (~5 to 30 second period for the iteration cycle, ~100 ms period for the per-microbatch communication). In phase 2, predictor evaluation, replay the recorded utilisation through the AR(4) predictor at 1 Hz with a 30-second fitting window and record the prediction error per tick. Compute the MAE, p95, and the per-phase breakdown (compute phase versus communication phase MAE separately). The simulation MAE is 0.04; the hardware MAE on real bimodal traces is expected to be 0.10 to 0.20, but the structure of the framework remains valid as long as the prediction error is below the threshold for stable allocation. In phase 3, model-order selection, repeat the predictor evaluation for AR(p) with p in {1, 2, 4, 8, 12, 16} and a fast-component compensator with windows {0, 50 ms, 200 ms, 1 s} to find the best (order, window) combination empirically. The simulation default of (4, none) may be revised based on the result.

The expected output is a CSV at `data/hardware/exp2_ar_predictor.csv`, an analysis script at `experiments/hardware/analyse_exp2.py`, and a paragraph update in paper Section 3.3.3 reporting the hardware MAE and the chosen (p, window) combination.

## Experiment 3: Tier-3 Cluster Optimiser End-to-End

The aim is to demonstrate the cascade running closed-loop on a real cluster against a real or recorded ENTSO-E FFR signal, with the operating-point selector driving the host coordinator, which drives the per-GPU controller.

The procedure runs over a 4-hour wall-clock window on a multi-host configuration (minimum 4 hosts, 32 GPUs total). The cluster runs a continuous LLM training workload at variable replica count. The Tier-3 optimiser is connected to a recorded German PRL FFR signal (recorded at 50 Hz over the previous week and replayed at real-time rate). Telemetry is collected at every level (Tier-1 NVML power per GPU, Tier-2 host envelope, Tier-3 operating point). The expected output validates that the operating point indeed transitions from the green-rich daytime selection (mean fraction 0.90) to the carbon-intensive overnight selection (mean fraction 0.40) over the four hours, and that the FFR provision quality remains above 0.95 for the duration.

This is the most expensive experiment and may require a longer wall window. The expected output is a directory `data/hardware/exp3_cascade/` with per-host CSV files, an analysis script at `experiments/hardware/analyse_exp3.py`, and an updated paper Section 3.3.4 reporting the cascade composition results on real hardware.

## Experiment 4: Live ENTSO-E API Validation

The aim is to confirm that the connector at `src/integration/entsoe_connector.py` parses the live API response correctly, and to compare the live trajectory to the synthesised fallback for a 24-hour window.

The procedure is straightforward. With `ENTSOE_API_KEY` set, run `python experiments/validate_country_config.py --country DE --capacity-mw 10` and capture the output. Then run a 24-hour fetch script (`experiments/hardware/fetch_live_entsoe.py`, provided in this kit) that fetches FCR, aFRR, and mFRR procurement data for Germany, France, Spain, Italy, and Switzerland over the previous 24 hours, saves to `data/hardware/exp4_entsoe_live.csv`, and produces a comparison plot against the synthesised trajectory.

The XML response format from ENTSO-E may differ in details from the parser assumptions in `_parse_xml`. Any parser bugs surface as either zero capacities (graceful failure path) or as parse exceptions (caught by the silent fallback). Both cases trigger a follow-up patch in the connector code; the kit's tests at `tests/test_entsoe_connector.py` should be extended with the actual XML observed in the field.

## Re-Integration Steps

Once experiments 1 through 4 are complete, the following kit-internal updates make the new evidence available in the paper and proposal: (1) replace the simulation paragraph in paper Section 3.3 with a hardware-validated paragraph citing the new CSV files; (2) add a new figure `fig_hardware_validation.pdf` that consolidates the four experiments into one publication-quality multi-panel; (3) update `KNOWN_LIMITATIONS.md` to remove the "simulation-only" framing for the validated tiers; (4) add the four new CSV files and the four new analysis scripts to the reproducibility kit; (5) re-run `experiments/reproduce_all.py` and confirm all stages still pass; (6) increment the kit version from 1.0 to 1.1 and tag the GitHub repository.

The paper-extension version (journal manuscript) can then make the explicit claim "validated on real H100 hardware" in the abstract.
