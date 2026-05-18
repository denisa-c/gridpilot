# Multi-country sweep protocol

Backs the **PECS Paper B Finding 5** (f-SLA CFE-lift across the EU CI spectrum) and the **WHPC PUE-aware controller** multi-country result.

## 1. Inputs

| File | What it is |
|---|---|
| `data/traces/m100_real_jobs.parquet` | M100 production trace (Antici et al. 2023). |
| `configs/grids/{SE,CH,FR,IT,DE,PL}.yaml` | Per-country annual mean CI + diurnal amplitude + weekly factor (Section 6 of PECS). |
| `raps/config/marconi100.yaml` | Cooling-model anchor (PUE 1.20 at full load). |

## 2. One-shot sweep

```bash
PYTHONPATH=src python scripts/multicountry/replay_country_sweep.py \
    --jobs             data/traces/m100_real_jobs.parquet \
    --grids            configs/grids/SE.yaml,configs/grids/FR.yaml,configs/grids/CH.yaml,configs/grids/IT.yaml,configs/grids/DE.yaml,configs/grids/PL.yaml \
    --pue-yaml         raps/config/marconi100.yaml \
    --mw               1,10,50 \
    --fsla-mechanisms  none,M0,M1,M2,M3 \
    --pue-mechanisms   none,GridPilot-PUE \
    --seeds            8 \
    --workers          4 \
    --output-dir       data/m100/country_sweep/
```

(Use the full flag names exactly — short prefixes like ``--pue`` are
rejected because they are ambiguous between ``--pue-yaml`` and
``--pue-mechanisms``.  The ``--mechanisms`` alias is kept as a
synonym for ``--fsla-mechanisms`` for backwards compatibility.)

Wall time: ~30 min on 16 cores (6 grids × 3 MW × (5 fsla + 2 pue) × 8 seeds = 1\,008 cells). Outputs:

- `country_sweep.csv` — one row per cell with the four headline columns: `cfe_pct`, `cfe_lift_pp_vs_none`, `co2_avoided_tonnes_y`, `delta_facility_pp`.
- `COUNTRY_SUMMARY.csv` — mean per `(country, mw, layer, mechanism)`.
- `RUN_MANIFEST.json` — git SHA + Python/package versions + wall time.

## 3. Stub (for fast paper rebuilds)

```bash
PYTHONPATH=src python scripts/multicountry/seed_country_sweep_stub.py \
    --output-dir data/m100/country_sweep/
```

Produces the same CSV with literature-anchored numbers (see module docstring for the citation chain). Stub takes ~0.5 s.

## 4. Figures

```bash
PYTHONPATH=src python scripts/figures/fig_country_cfe_lift.py    # PECS headline
PYTHONPATH=src python scripts/figures/fig_country_pue_aware.py   # WHPC headline
```

Each writes a vector PDF to `figs/`; `papers/build.sh` then stages those into `papers/{pecs,whpc}2026/figs/` automatically (the build searches both `figs/` and `gridpilot/figs/`).

## 5. Hypothesis & finding map

| Paper | Finding | Figure | What the figure shows |
|---|---|---|---|
| PECS | Finding 5(A) high-CI vs low-CI asymmetry | `fig_country_cfe_lift.pdf` (a) | CFE-lift bars across SE → PL, with annual avoided tCO2/y on right axis |
| PECS | Finding 5(C) scale-invariance | `fig_country_cfe_lift.pdf` (b) | Same lift evaluated at 1/10/50 MW for SE and PL bookends |
| WHPC | PUE-aware FFR drag-closure | `fig_country_pue_aware.pdf` (a) | $\Delta_\mathrm{facility}$ bars across SE → PL at 10 MW |
| WHPC | Cluster-scale drag-envelope | `fig_country_pue_aware.pdf` (b) | $\Delta_\mathrm{facility}$ scaling at 1/10/50 MW |

## 6. Quick smoke run

```bash
PYTHONPATH=src python -c "
import sys
sys.path.insert(0, 'scripts/m100')
from inject_fsla_prior import load_ci
for c in ('SE','CH','FR','IT','DE','PL'):
    df = load_ci(__import__('pathlib').Path(f'configs/grids/{c}.yaml'))
    print(f'{c}: {df.carbon_intensity_gCO2eq_per_kWh.mean():6.1f} g/kWh (n={len(df)})')
"
```

Expected: SE ≈ 11, CH ≈ 30, FR ≈ 53, IT ≈ 258, DE ≈ 295, PL ≈ 612.
