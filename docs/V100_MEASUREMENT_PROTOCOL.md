# V100 measurement protocol (E1–E7 campaign)

This document describes the step-by-step procedure for the E1–E7 hardware
measurement campaign on a V100 testbed. The protocol is portable to any
modern NVIDIA GPU with NVML support (V100, A100, H100, H200) and to AMD
GPUs with ROCm-SMI support, with the modifications noted in Section 9.

## 1. Hardware requirements

### Reference testbed (`ecocloud-exp06` at EPFL EcoCloud)

| Component   | Specification                                         |
|-------------|-------------------------------------------------------|
| GPUs        | 3× NVIDIA Tesla V100-SXM2 32 GB (300 W TDP each)      |
| CPU         | 36 physical cores / 72 logical threads                |
| RAM         | 379 GiB usable                                         |
| OS          | Ubuntu 24.04 LTS (kernel ≥ 6.5)                       |
| CUDA / NVML | CUDA 12.x, NVML library version 12.x                  |
| Power tools | `nvidia-smi`, `nvidia-smi --query-gpu`                |
| Network     | Direct local access (no VPN; latency-sensitive E7)    |

### Minimum requirements for portability

- Any NVIDIA GPU with NVML 12.x or later.
- `nvidia-smi --persistence-mode 1` must be enabled (root access required).
- Power-cap range must include 50% of TDP (e.g. 150 W for V100, 350 W for
  H100). Confirm with `nvidia-smi -q -d POWER`.
- For E7 only: a synchronous PTP or NTP-tight (< 1 ms) time source is
  recommended for end-to-end latency measurement.

## 2. Software setup

### One-time

```bash
# Install NVML Python bindings
pip install pynvml>=11.5

# Install dependencies for the campaign harness
pip install -r requirements.txt

# Verify NVML access
python -c "
import pynvml
pynvml.nvmlInit()
n = pynvml.nvmlDeviceGetCount()
print(f'NVML reports {n} GPUs')
for i in range(n):
    h = pynvml.nvmlDeviceGetHandleByIndex(i)
    print(f'  GPU {i}: {pynvml.nvmlDeviceGetName(h).decode()}')
"
```

### Per-session

```bash
# Enable persistence mode (requires root)
sudo nvidia-smi --persistence-mode 1

# Set to maximum performance state (defeats clock throttling)
sudo nvidia-smi --auto-boost-default 0

# Verify power-cap range
nvidia-smi -q -d POWER | grep -A 2 "Power Limit"
```

## 3. Calibration probes (workloads)

We use three open calibration probes designed to stress different aspects
of the controller:

### 3.1 Compute-bound: matrix multiplication

```python
# benchmarks/probes/matmul.py
import torch
def run(device, duration_s=300):
    torch.cuda.set_device(device)
    a = torch.randn(8192, 8192, device='cuda')
    b = torch.randn(8192, 8192, device='cuda')
    t0 = time.time()
    while time.time() - t0 < duration_s:
        c = torch.matmul(a, b)
        torch.cuda.synchronize()
```

### 3.2 Memory-bound: ResNet-50 inference

```python
# benchmarks/probes/resnet50_inference.py
import torch, torchvision
def run(device, duration_s=300, batch=32):
    torch.cuda.set_device(device)
    model = torchvision.models.resnet50(pretrained=False).cuda().eval()
    x = torch.randn(batch, 3, 224, 224, device='cuda')
    t0 = time.time()
    with torch.no_grad():
        while time.time() - t0 < duration_s:
            y = model(x)
            torch.cuda.synchronize()
```

### 3.3 Bursty alternating

```python
# benchmarks/probes/bursty.py
def run(device, duration_s=300, busy_s=10, idle_s=20):
    """Alternates 10 s of matmul with 20 s of idle to deliberately stress
    prediction and control stability."""
    t0 = time.time()
    while time.time() - t0 < duration_s:
        run_matmul(device, busy_s)
        time.sleep(idle_s)
```

## 4. The seven experiments (E1–E7)

### E1 — Power-cap calibration sweep

**Purpose:** Find the energy-efficiency sweet spot $(p_{cap}^*, f_{sm}^*)$
across workload classes.

**Design:** 36-cell sweep
- 3 workloads × 4 power caps × 3 SM clocks = 36 runs
- Power caps: $p_{cap} \in \{150, 200, 250, 300\}$ W
- SM clocks: $f_{sm} \in \{405, 945, 1380\}$ MHz
- 5-minute duration per cell, 30 trials per cell

**Procedure:**
```bash
python scripts/v100/experiments/E1_power_cap_calibrate.py \
  --testbed ecocloud-exp06 \
  --workloads matmul,inference,bursty \
  --power-caps 150,200,250,300 \
  --sm-clocks 405,945,1380 \
  --duration 300 \
  --trials 30 \
  --output data/e1_results.csv
```

**Headline result (paper):** Robust optimum at
$(p_{cap}^* = 150\,W, f_{sm}^* = 945\,MHz)$ across all three workloads.
Iterations/joule at the optimum: 2.88 (inference), 0.57 (matmul).

### E2 — Step response

**Purpose:** Verify sub-second settling time of the inner-loop power-cap
PID controller.

**Design:** 90 trials of a 280 W → 200 W step at random times during a
matmul-bound run, log NVML power at 200 Hz, measure settling time
within ±2% band.

**Procedure:**
```bash
python scripts/v100/experiments/E2_inner_loop_step_response.py \
  --testbed ecocloud-exp06 \
  --workload matmul \
  --step-from 280 --step-to 200 \
  --trials 90 \
  --output data/e2_results.csv
```

**Headline result (paper):** Sub-second settling within ±2%, validating
the 200 Hz Tier-1 cadence.

### E3 — AR(4) outer-loop predictor accuracy

**Purpose:** Measure mean absolute error (MAE) of the 1 Hz host-level AR(4)
predictor on a 30-second rolling window, per workload.

**Procedure:**
```bash
python scripts/v100/experiments/E3_outer_loop_tracking.py \
  --testbed ecocloud-exp06 \
  --workloads matmul,inference,bursty \
  --window-s 30 \
  --duration 600 \
  --trials 297 \
  --output data/e3_results.csv
```

**Headline results (paper, Table 2):**
- Inference: 4.69 W MAE
- MatMul: 7.00 W MAE
- Bursty: 19.66 W MAE (deliberately difficult)

### E4 — Closed-loop demand-following

**Purpose:** Measure relative tracking error of the closed-loop GridPilot
controller against a synthesised demand profile.

**Procedure:**
```bash
python scripts/v100/experiments/E4_closed_loop_demand_following.py \
  --testbed ecocloud-exp06 \
  --workloads matmul,inference,bursty \
  --demand-profile data/demand_profiles/sinusoidal_30s.csv \
  --duration 600 \
  --trials 30 \
  --output data/e4_results.csv
```

**Headline results (paper, Table 2):**
- Inference: 1.68%
- MatMul: 2.12%
- Bursty: 11.08%

### E5 — Supervisory control

**Purpose:** Validate cluster-level operating-point selection (Tier 3)
under varying CI signals.

**Procedure:**
```bash
python scripts/v100/experiments/E5_supervisory_pareto.py \
  --testbed ecocloud-exp06 \
  --ci-signal data/entsoe_2025_de_summer_week.csv \
  --duration 7d \
  --output data/e5_results.csv
```

**Note:** E5 is deferred to ProACT WP3 (production-scale validation
requires more than 3 GPUs). The current paper does not report E5 results.

### E6 — Multi-GPU fairness baseline

**Purpose:** Measure Jain fairness index under naïve static caps across
the 3-GPU testbed.

**Procedure:**
```bash
python scripts/v100/experiments/E6_multigpu_cpu_coordinated.py \
  --testbed ecocloud-exp06 \
  --static-caps 600,750,900 \
  --workloads matmul,inference,bursty \
  --duration 600 \
  --output data/e6_results.csv
```

**Headline result (paper, Table 2):** Jain fairness index = 0.333 under
the worst static-cap allocation. This baseline motivates the scheduler's
preference for declared-deferrability over uniform per-GPU caps.

### E7 — End-to-end FFR actuation latency

**Purpose:** Measure end-to-end latency from a synthetic frequency-response
trigger to per-GPU power-cap setpoint reaching target. **The binding
result for grid-services certification.**

**Setup:**
- Synthetic frequency-deviation trigger generated on a separate host at a
  random time within a 60 s window.
- Trigger transmitted via local IPC (no network) to the controller.
- Controller issues `nvidia-smi -pl <new-cap>` for all 3 GPUs.
- NVML power is sampled at 1 kHz.
- Latency = time from trigger to NVML reporting power within 5% of new
  setpoint, averaged across 3 GPUs.

**Procedure:**
```bash
python scripts/v100/experiments/E7_ffr_activation_latency.py \
  --testbed ecocloud-exp06 \
  --workloads matmul,inference,bursty \
  --trigger-power-step 280-to-200 \
  --trials-per-workload 30 \
  --output data/e7_results.csv
```

**Headline result (paper, Table 2):** Median 97.221 ms (matmul),
97.471 ms (inference), 97.797 ms (bursty); max 101.108 ms across all
90 trials; 30/30 pass per workload (90/90 total) at the 700 ms Nordic
FFR budget, yielding a ~7× safety margin.

## 5. Reproducing the figure pipeline

After completing the campaign:

```bash
python scripts/v100/src/replot_with_real_data.py \
  --e3 data/e3_results.csv \
  --e4 data/e4_results.csv \
  --e7 data/e7_results.csv \
  --out figures/v100/
```

This regenerates the three V100 figures used in the paper:
- `fig_predictor_accuracy.pdf` (E3)
- `fig_demand_following.pdf` (E4)
- `fig_safety_island.pdf` (E7)

## 6. Calibration coefficients output

The E1 sweep produces calibration coefficients in JSON format:

```json
{
  "gpu_model": "Tesla V100-SXM2",
  "tdp_w": 300,
  "energy_optimal_pcap_w": 150,
  "energy_optimal_fsm_mhz": 945,
  "iters_per_joule": {
    "matmul": 0.57,
    "inference": 2.88,
    "bursty": 0.31
  },
  "ar4_coefficients": [0.61, 0.18, 0.10, 0.05]
}
```

These coefficients feed into the `gridpilot.raps_bridge` module for the
multi-scale projection (see `EXADIGIT_RAPS_SETUP.md`).

## 7. Statistical reporting

All headline numbers in the paper are reported as **median across trials**
unless explicitly noted as mean. Bootstrap 95% confidence intervals are
included in the per-trial CSVs. The paper figures show median + 95% CI;
the per-trial raw data is available in the released reproducibility kit.

## 8. Common pitfalls

### "NVML reports zero power"

Ensure persistence mode is enabled and the GPU is not in `Default` compute
mode. Run:
```bash
sudo nvidia-smi --persistence-mode 1
sudo nvidia-smi --compute-mode 2  # EXCLUSIVE_PROCESS
```

### "E7 latencies exceed 200 ms on my testbed"

Likely causes:
1. NTP jitter on the trigger host. Use PTP if available.
2. The Python supervisor is on the critical path. Verify the safety-island
   dispatch path bypasses the Python interpreter (cf. paper Section 3.4).
3. CPU governor is in `powersave` mode. Set to `performance`:
   ```bash
   sudo cpupower frequency-set -g performance
   ```

### "Bursty E3 MAE is very different from 33.77 W"

The bursty MAE is sensitive to the busy-idle ratio. We use 10 s busy /
20 s idle. If you change these, the MAE will change accordingly. Document
your busy-idle ratio in the per-trial CSVs.

## 9. Portability to A100, H100, H200

The protocol is largely portable. Key changes per architecture:

| GPU   | TDP   | Power-cap range  | Recommended optimum (E1) |
|-------|-------|------------------|--------------------------|
| V100  | 300 W | 150–300 W        | 150 W, 945 MHz           |
| A100  | 400 W | 200–400 W        | ~200 W (re-measure)      |
| H100  | 700 W | 350–700 W        | ~350 W (re-measure)      |
| H200  | 700 W | 350–700 W        | ~350 W (re-measure)      |

Note that H100/H200 introduce per-GPU NVLink power that NVML does not
break out. For three-chain validation on H100, an external meter
(PowerSensor3 or Yokogawa WT5000) is recommended to capture the NVLink
contribution.

## 10. Portability to AMD GPUs (ROCm)

Replace `pynvml` with `pyrsmi` (the ROCm-SMI Python bindings). The
power-cap interface uses `rocm-smi --setpoweroverdrive <W>` instead of
`nvidia-smi -pl`. Submit AMD ports via the `CONTRIBUTING.md` workflow.

## References

- NVIDIA NVML reference:
  [https://docs.nvidia.com/deploy/nvml-api/](https://docs.nvidia.com/deploy/nvml-api/)
- PowerSensor3 hardware (recommended external meter):
  Romein and van Werkhoven, *PowerSensor3: A Fast and Accurate Energy
  Measurement Tool for HPC*, IEEE/ACM HPDC 2024.
- Velicka et al. *Methodology for GPU Frequency Switching Latency
  Measurement*. IEEE IPDPSW 2025.
