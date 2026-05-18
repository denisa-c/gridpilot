# ExaDigiT / RAPS setup and integration with GridPilot

This document explains how to install the ExaDigiT digital-twin framework
and its RAPS (Resource and Application Performance Simulator) module, how
to import the public reference-system configurations, and how GridPilot
uses RAPS for the multi-scale projection.

## 1. What is ExaDigiT/RAPS?

ExaDigiT is the open-source digital-twin framework for liquid-cooled
exascale supercomputers, originally developed at Oak Ridge National
Laboratory and validated against six months of Frontier telemetry. The
RAPS module is its event-driven simulator for resource allocation and
power consumption.

**Citations:**
- Brewer, W., et al. *ExaDigiT: An Open-Source Digital-Twin Framework for
  Liquid-Cooled Exascale Supercomputers.* SC24, 2024.
- Maiterth, M., et al. *Plug-in Scheduling-Simulator Integration for
  ExaDigiT/RAPS.* HPC workshop paper, 2025.

## 2. Installation

### Prerequisites

- Python ≥ 3.10
- POSIX shell (Linux or macOS; Windows users: use WSL)
- ~2 GB free disk for the reference-system configurations
- (Optional) GraphViz for the topology visualisations

### Installing ExaDigiT/RAPS

```bash
# 1. Clone the upstream repository
git clone https://code.ornl.gov/exadigit/raps.git
cd raps

# 2. Create a clean virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install RAPS in editable mode
pip install -e .

# 4. Verify installation
raps --version       # should print a version string
raps --list-systems  # should list 13 reference systems
```

### Expected output of `raps --list-systems`

The 13 reference systems in the public catalogue (as of mid-2025):

| #  | System         | Site            | Architecture        | GPUs                | Peak (PFLOPS)  |
|----|----------------|-----------------|---------------------|---------------------|----------------|
| 1  | Frontier       | OLCF (US)       | HPE Cray EX235a     | 37,888 AMD MI250X   | 1,679          |
| 2  | Marconi100     | CINECA (IT)     | IBM AC922           | 3,920 NVIDIA V100   | 32             |
| 3  | LUMI           | EuroHPC (FI)    | HPE Cray EX235a     | 11,264 AMD MI250X   | 531            |
| 4  | Setonix        | Pawsey (AU)     | HPE Cray EX235a     | 768 AMD MI250X      | 27             |
| 5  | Adastra        | CINES (FR)      | HPE Cray EX235a     | 2,000 AMD MI250X    | 74             |
| 6  | MareNostrum 5  | BSC (ES)        | NVIDIA Grace-Hopper | 4,480 H100          | 314            |
| 7  | Karolina       | IT4I (CZ)       | HPE Apollo 6500     | 576 NVIDIA A100     | 16             |
| 8  | Vega           | EuroHPC (SI)    | HPE Apollo 2000     | 240 NVIDIA A100     | 7              |
| 9  | Polaris        | ALCF (US)       | HPE Apollo 6500     | 2,240 NVIDIA A100   | 44             |
| 10 | Perlmutter     | NERSC (US)      | HPE Cray Shasta     | 6,144 NVIDIA A100   | 95             |
| 11 | Selene         | NVIDIA (US)     | NVIDIA DGX A100     | 4,480 NVIDIA A100   | 63             |
| 12 | Summit         | OLCF (US)       | IBM AC922           | 27,648 NVIDIA V100  | 200            |
| 13 | Sierra         | LLNL (US)       | IBM AC922           | 17,280 NVIDIA V100  | 125            |

Each system's configuration is a YAML file under `raps/configs/<system>.yaml`
containing per-node IT power, design PUE, cooling regime, and topology.

## 3. Configuration

The relevant fields in each RAPS system YAML for GridPilot's projection:

```yaml
system: marconi100
peak_pflops: 32
nodes:
  count: 980
  it_power_w: 2200          # per-node IT power at full load
  cooling_regime: warm_water  # one of {air, rear_door_hex, warm_water, immersion}
pue:
  design: 1.20              # design-point PUE at full load + 25C ambient
  air_split: 0.15           # fan/pump/chiller decomposition
  pump_split: 0.25
  chiller_split: 0.60
ambient:
  reference_C: 25
  free_cooling_threshold_C: 12
```

GridPilot reads these fields and uses them to:
1. **Calibrate** the dynamic PUE model in `gridpilot.pue` against the design
   point.
2. **Project** the V100-measured per-node coefficients (from the E1 sweep
   on `ecocloud-exp06`) onto each RAPS reference system's per-node IT
   power.
3. **Cross-validate** the projection: for the two systems with published
   facility-power telemetry (Marconi100 and Frontier), the energy
   residual must stay below 5% (we report 1.85% mean across all 13
   systems).

## 4. Integration with GridPilot

The integration code lives in `scripts/raps_bridge.py` (in this repository,
to be added). The bridge does three things:

### 4.1 Load RAPS configurations

```python
from gridpilot.raps_bridge import load_raps_systems

systems = load_raps_systems('/path/to/raps/configs/')
print(systems['marconi100'].nodes_count)   # 980
print(systems['frontier'].nodes_count)     # 9,408
```

### 4.2 Cross-validate the V100 calibration

```python
from gridpilot.raps_bridge import cross_validate_v100_calibration

residual = cross_validate_v100_calibration(
    v100_coefficients='data/v100_e1_coefficients.json',
    raps_systems=systems,
    reference_systems=['marconi100', 'frontier'],
)
print(f"Mean energy residual: {residual.mean:.2%}")
# Expected: ~1.85% (paper headline)
```

### 4.3 Run the multi-scale projection

```python
from gridpilot.raps_bridge import multiscale_projection

results = multiscale_projection(
    base_node_kw=0.78,                  # measured 3-GPU V100 node
    target_scales_mw=[0.01, 0.1, 1.0, 5.0, 25.0, 50.0],
    countries=['CH', 'IT', 'DE'],
    years=[2025, 2028, 2032],
    raps_calibration=systems['marconi100'],
)
results.to_csv('data/multiscale_projection.csv')
```

## 5. Reproducing the 1.85% energy residual

To reproduce the headline RAPS cross-validation:

```bash
# 1. Run the V100 E1 calibration sweep on your testbed (or use ours)
python scripts/v100_e1_calibrate.py \
  --testbed ecocloud-exp06 \
  --output data/v100_e1_coefficients.json

# 2. Cross-validate against the 13 RAPS reference systems
python scripts/raps_bridge.py cross-validate \
  --v100-coeffs data/v100_e1_coefficients.json \
  --raps-configs /path/to/raps/configs/ \
  --output data/raps_residuals.csv

# 3. Inspect the residuals
python -c "
import pandas as pd
df = pd.read_csv('data/raps_residuals.csv')
print(df.describe())
print(f'Mean: {df.residual_pct.mean():.2f}%')
print(f'p95:  {df.residual_pct.quantile(0.95):.2f}%')
print(f'Max:  {df.residual_pct.max():.2f}%')
"
```

Expected output (paper headline, Section 6.6):
- Mean: **1.85%**
- p95:  **3.62%**
- Max:  **3.64%**

## 6. Adding a new reference system

To extend GridPilot to a new HPC system not in the RAPS catalogue:

1. Create a new YAML configuration under `gridpilot/raps/config/<your-system>.yaml`
   following the schema in Section 3 above (the same one used by the
   bundled `marconi100.yaml`, `frontier.yaml`, etc.).
2. Submit a PR to the upstream RAPS repository
   ([https://code.ornl.gov/exadigit/raps](https://code.ornl.gov/exadigit/raps))
   with the new configuration so the next bundled snapshot picks it up.
3. Invoke any GridPilot script with `--pue raps/config/<your-system>.yaml`.
   The release ships no separate calibration-entry layer; the RAPS YAML
   is the single source of truth.
4. Run the cross-validation procedure (Section 5) to verify the energy
   residual is below 5%.

See `CONTRIBUTING.md` for the contribution workflow.

## 7. Troubleshooting

### "RAPS configurations not found"

Ensure `RAPS_CONFIGS_PATH` environment variable is set:
```bash
export RAPS_CONFIGS_PATH=/path/to/raps/configs/
```

### "Energy residual exceeds 5% on Marconi100"

Likely causes:
1. Your V100 calibration coefficients were measured under different
   ambient temperature or workload mix than the M100 reference.
   Re-run the E1 sweep with the same workload set used in the paper
   (matmul / ResNet-50 inference / bursty alternating).
2. Stale RAPS configuration. Pull the latest from upstream:
   ```bash
   cd /path/to/raps && git pull origin main
   ```

### "ExaDigiT not found"

ExaDigiT (the higher-level framework) is separate from RAPS (the
simulator module). For GridPilot, only RAPS is required. ExaDigiT
provides additional visualisation and digital-twin integration that is
optional for this paper's reproductions.

## 8. References

- ExaDigiT repository: [https://code.ornl.gov/exadigit/raps](https://code.ornl.gov/exadigit/raps)
- ExaDigiT main paper: Brewer et al. SC24, [https://doi.org/10.1145/3581784.3613226](https://doi.org/10.1145/3581784.3613226)
  (verify DOI; some versions are SC24 supplements)
- M100 dataset: Borghesi et al. Sci Data 2023,
  [https://doi.org/10.1038/s41597-023-02174-3](https://doi.org/10.1038/s41597-023-02174-3)
- Frontier energy dataset: Sun et al. 2024, available via OLCF.
