# V100 real-execution vs M100 trace-replay — comparison

_Generated 2026-04-29T22:35:10.005027+00:00_

## Cross-validation axes

| # | Axis | V100-real | M100-replay | Δ% | Pass? |
|---|---|---|---|---|---|
| 1 | per-GPU mean power | 121.2 | 237.0 | -48.9% | · (below_band) |
| 3 | AR(4) MAE on multi-phase | 19.66 | — | — | · (v100_only) |
| 7 | Per-workload CO₂ reduction (M100, country=IT) | — | GP=38.8%, CS=50.3% | -11.5pp | · (neutral) |
| 9 | Scaling envelope @ 980-node scale | 1014.0 | 1000.0 | +1.4% | ✓ (pass) |

## V100-only findings (path A)

| Finding | Value |
|---|---|
| E4 closed-loop relative MAE (bursty_alternating) | 11.08% |
| E4 closed-loop relative MAE (inference_memory_bound) | 1.68% |
| E4 closed-loop relative MAE (matmul_compute_bound) | 2.12% |
| E6 fairness (budget_600w) | 0.333 |
| E6 fairness (budget_750w) | 0.333 |
| E6 fairness (budget_900w) | 0.333 |
| E7 FFR median latency (bursty_alternating) | 97.797 ms (budget 700) |
| E7 FFR median latency (inference_memory_bound) | 97.471 ms (budget 700) |
| E7 FFR median latency (matmul_compute_bound) | 97.221 ms (budget 700) |
| E7 all-workloads pass | True |

## M100-only findings (path B)

| Finding | Value |
|---|---|
| M100 GridPilot CO2 reduction range (country=IT) | 25.8% to 38.8% across cells |
