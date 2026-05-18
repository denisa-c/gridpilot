# Third-party data and code licences

This document records the licences governing third-party datasets and
codebases referenced or used by GridPilot.

## Datasets

### Marconi100 PM100 (CINECA)
- **Licence:** CC-BY 4.0 per Borghesi et al., Sci Data 2023.
- **Source:** [https://doi.org/10.1038/s41597-023-02174-3](https://doi.org/10.1038/s41597-023-02174-3)
- **Use in this work:** 1,994-job evaluation subset for the multi-scale
  projection. Not redistributed; users must obtain directly from CINECA.

### ENTSO-E A75 (Transparency Platform)
- **Licence:** ENTSO-E open licence (free for non-commercial research).
- **Source:** [https://transparency.entsoe.eu](https://transparency.entsoe.eu)
- **Use in this work:** Hourly carbon-intensity time series for CH/IT/DE
  for 2025. Not redistributed; users must obtain via API key.

### ExaDigiT/RAPS reference-system catalogue
- **Licence:** BSD 3-Clause for the simulator code; CC-BY 4.0 for
  configuration files (verify upstream `LICENSE` before redistribution).
- **Source:** [https://code.ornl.gov/exadigit/raps](https://code.ornl.gov/exadigit/raps)
- **Use in this work:** 13 reference-system configurations imported as
  the canonical source for per-node IT power and design PUE. Not
  redistributed; users must clone upstream.

### Frontier energy dataset (OLCF)
- **Licence:** US DOE open-research-data licence (specific terms via OLCF).
- **Source:** Sun et al. 2024.
- **Use in this work:** Cross-validation reference for the RAPS energy
  residual.

## Code and tools

### `gridpilot_replay` simulator
- **Licence:** MIT (this work).
- **Status:** Companion repository to be released at paper publication.

### `pynvml` (NVIDIA NVML Python bindings)
- **Licence:** BSD 3-Clause.
- **Source:** [https://github.com/gpuopenanalytics/pynvml](https://github.com/gpuopenanalytics/pynvml)

### Matplotlib, NumPy, Pandas, SciPy
- **Licences:** matplotlib (Matplotlib licence), NumPy/SciPy/Pandas (BSD).

## Compatibility note

The MIT licence under which GridPilot's code and reproducibility kit are
released is compatible with all third-party licences listed above for
inclusion in derivative works, with attribution. Users redistributing
GridPilot in modified form should preserve the upstream attributions in
this file.
