# GridPilot architecture

## Three-tier multiscale controller

GridPilot composes three time-aligned controllers operating at orders of
magnitude different rates. The timescale separation is what makes the
cascade composition formally tractable.

| Tier   | Rate     | Scope        | Mechanism                                  |
|--------|----------|--------------|--------------------------------------------|
| Tier 1 | 200 Hz   | Per-GPU      | PID power-cap loop tracking via NVML DVFS  |
| Tier 2 | 1 Hz     | Per-host     | AR(4) autoregressive predictor             |
| Tier 3 | 0.001 Hz | Cluster      | Operating-point selector (FFR + CFE)       |

### Tier 1: per-GPU PID

Tracks a per-GPU target power via NVML. PID gains: $K_p=0.6, K_i=0.05,
K_d=0.02$ tuned for stability against the 40% AI-training power swing
(Choukse et al. 2025). Safety envelope derates target if GPU temperature
> 85 °C.

### Tier 2: per-host AR(4) predictor

Coordinates GPU caps within the host envelope. Fits utilisation samples
over a 30-second window by recursive least squares. One-step-ahead
prediction allocates host envelope between CPUs (cpuidle) and GPU
sub-controllers proportionally to job priority.

### Tier 3: cluster operating-point selector

Grid search over (mean operating fraction, FFR band fraction). Maximises
joint FFR + CFE objective: weights 0.55 FFR, 0.45 CFE, biased toward FFR
because exogenous savings often exceed operational savings on coal-heavy
grids.

## Carbon-and-PUE-aware scheduler

The scheduler consumes:
- Workload trace (job arrivals, durations, resource requests)
- Grid CI signal (ENTSO-E A75)
- Facility PUE model (calibrated from RAPS)
- f-SLA flexibility annotations (optional; used in ProACT extension)

Two variants:
- **GridPilot** (CI-only): optimises against carbon intensity alone
- **GridPilot-PUE**: optimises against composite carbon × PUE signal

## Safety island

Physically and procedurally isolated dispatch path bypassing the Python
supervisor stack. Provides deterministic FFR actuation latency suitable
for IEC 61508 SIL-2 pre-qualification (cf. ProACT WP3).

E7 measurements: median 97–98 ms end-to-end latency, max 101.1 ms,
~7× safety margin against the 700 ms Nordic FFR budget.

## Code layout (forthcoming)

The `gridpilot` Python package (separate codebase, MIT licence, repository
to be released alongside this paper) implements the three tiers. This
repository contains the paper, figures, and reproducibility kit only.
