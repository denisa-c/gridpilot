# Simulator outputs — REAL EXPERIMENTAL DATA

## Status

The CSVs in this directory are the **real outputs** of the GridPilot
simulator and analysis pipeline used to produce the paper's Table 1
(multi-scale carbon savings), Figures 4–6 (Pareto, cross-workload, PUE),
Figure 8 (multi-scale projection), Figure 10 (sensitivity tornado), and
the multi-year decarbonisation trajectory.

These are the CSV inputs that the figure-regeneration scripts under
`../../scripts/` and `../../scripts/simulator/` consume.

## File index

| File | Rows | Purpose |
|------|------|---------|
| `multiyear_matrix.csv` | 135 | Per-(year,country,workload,scheduler) IT and facility CO₂ savings; produces the multi-year decarbonisation trajectory in Section 6 |
| `multiscale_sweep.csv` | 12 | Per-grid scale (rack/1MW/10MW/50MW) operational and net savings for GridPilot-PUE; basis for the scale-vs-savings curves |
| `multiscale_24h_validation.csv` | ~17000 | 24h time-series at 5 s resolution validating the multiscale projection against the synthesised demand profile |
| `icpp_full_matrix.csv` | 63 | 45-cell experiment matrix (3 workloads × 3 grids × 7 schedulers minus invalid combinations); basis for paper Table 1 |
| `multiyear_matrix.csv` | 135 | Per-(year,country,workload) GridPilot-OPT and GridPilot-OPT-PUE results across 2025/2028/2032 |
| `raps_cross_validation.csv` | 2 | RAPS cross-validation of two reference systems (Marconi100, Frontier) |
| `raps_aligned_matrix.csv` | 18 | Subset of the experiment matrix with RAPS-aligned facility-PUE cross-comparison |
| `sensitivity_analysis.csv` | 8 | Plackett-Burman 5-factor 8-run sensitivity sweep on the headline 26.2% DE 2025 50MW result |
| `entsoe_full_sweep_25countries.csv` | 100 | Full 25-country sweep across 4 cluster scales (0.5/1/10/50 MW) |
| `entsoe_multicountry_sweep.csv` | 15 | 3-country focus subset (CH, IT, DE) with per-service breakdown |
| `entsoe_literature_validation.csv` | 8 | Cross-checks against published benchmarks (Bakker, Backer, Mohamed, Brinkel, Klyve, Gade, Sagrestano-Štambuk, Rodríguez-Vilches) |

## Headline numerics derived from these files

### Table 1 headline (paper Section 6, Table 1 — average across 45-cell matrix)

| Scheduler | IT-CO₂ red. (%) | Facility-CO₂ red. (%) | p95 slowdown |
|-----------|-----------------|------------------------|--------------|
| FCFS | 0.0 | 0.0 | 13.1 |
| Threshold | 4.4 | 27.9 | 36.1 |
| CarbonScaler | 24.2 | 40.3 | 13.2 |
| **GridPilot** | 19.8 | 37.3 | 13.1 |
| **GridPilot-PUE** | **20.0** | **15.0** | **13.1** |

Source: `icpp_full_matrix.csv`, aggregated by `scheduler` and averaged across
`(country, workload)` cells. The `facility_co2_red_pct` column is the honest
PUE-aware accounting; CarbonScaler's 40.3% is inflated by static-PUE
assumption (cf. Section 6).

### Multi-scale savings at 50 MW (paper Section 6.4)

| Country | 50 MW operational (%) | 50 MW net (%) |
|---------|------------------------|----------------|
| CH | 17.8 | 21.0 |
| IT | 14.1 | 20.2 |
| DE | 18.2 | **26.2** |

Source: `multiscale_sweep.csv`, filtered to `cluster_50mw` rows. The DE
26.2% is the headline figure that the sensitivity tornado pivots on.

### Multi-year trajectory (paper Section 6.6)

| Country | 2025 IT-CO₂ red. (%) | 2032 IT-CO₂ red. (%) |
|---------|----------------------|------------------------|
| CH | 20.1 | 20.4 |
| IT | 20.1 | 20.7 |
| DE | 20.2 | 20.6 |

Source: `multiyear_matrix.csv`, filtered to `scheduler == ProACT-OPT-PUE`,
averaged across workloads per (country, year). The IT-side savings are
near-flat across years; the increase in net carbon reduction from 26%
(2025) to 40% (2032) on the DE 50 MW projection arises from the
combination of (i) declining grid CI improving the leverage ratio, and
(ii) increasing FFR participation as the grid mix becomes more variable.

### RAPS cross-validation (paper Section 6.7)

The `raps_cross_validation.csv` shows the simulator's RAPS reference-system
comparison: **Marconi100** at 9.9% relative facility-energy error
(RAPS 320.84 MWh vs ProACT 352.59 MWh over 14 days).

The V100 hardware's separate cross-validation (`../v100_raw/cross_validation/`)
is the **scaling envelope** at 980-node scale: V100-projected 1014 kW vs M100
published 1000 kW, **+1.4%** error.

These two validations are complementary: the simulator-side 9.9% reflects
PUE-aware time-series tracking over multiple days, while the V100 +1.4% is
the static design-point comparison at full scale.

## Reproducibility

To regenerate any figure from these CSVs:

```bash
# Sensitivity tornado (paper Figure 10)
python scripts/fig_sensitivity_tornado.py

# Multi-scale projection (paper Figure 8)
python scripts/simulator/run_full_matrix.py --output-dir data/simulator_outputs/

# Reproduce all figures end-to-end
python scripts/simulator/reproduce_all.py
```

See `../../docs/REPRODUCING_FROM_RAW_DATA.md` for the full pipeline.

## Licence

CC-BY 4.0 (this work).
