# Per-tier and hyperparameter sweeps

This protocol documents the two ablation sweeps that complement the
PECS multi-country headline:

1. **Per-tier contribution sweep** (`replay_single_tier_sweep.py`) ---
   isolates the CFE lift each individual tier T0..T5 contributes by
   forcing every job to one tier at a time.  Answers "*which tier does
   the work, and what does the user pay in slowdown?*"
2. **Hyperparameter sensitivity sweep** (`replay_hyperparameter_sweep.py`)
   --- one-at-a-time variation of four contract hyperparameters
   (credit-schedule scale, deferral-window scale, T4 replica envelope,
   short-job threshold).  Answers "*does tuning the contract help, and
   by how much?*"

The two sweeps share the bundled M100 trace, the per-country CI configs
(`configs/grids/<CC>.yaml`) and the Marconi100 cooling-model anchor
(`raps/config/marconi100.yaml`).  Output CSVs feed a single composed
figure (`scripts/figures/fig_tier_and_hyper.py`) that the paper
includes alongside the multi-country headline.

For the remote-run sequence, see
[`EXPERIMENTS_REMOTE.md`](../../EXPERIMENTS_REMOTE.md).

---

## 1. Per-tier contribution sweep

### 1.1 Sweep design

6 grids x 3 MW x **6 tiers** x 8 seeds = **864 cells**.
Wall time ~30-40 min at 4 workers.

For each cell `(country, MW, tier_k, seed)` the driver:

- loads the M100 trace
- aligns jobs to the per-country CI series
- forces *every* job to tier `tier_k` (overriding the Dirichlet
  draw used in the main sweep)
- replays the resulting workload through `replay_proact_opt_pue`
  with the canonical PUE-aware dispatcher
- records CFE %, CFE lift vs T0, p95 slowdown, energy, avoided CO\textsubscript{2}

The "T0 baseline" for the lift column is the same (country, MW)
forced-T0 cell, averaged across seeds.

### 1.2 Outputs (under ``data/m100/tier_sweep/``)

| File | Schema |
|---|---|
| `tier_sweep.csv` | one row per (country, mw, tier, seed); per-cell metrics |
| `TIER_SUMMARY.csv` | mean per (country, mw, tier); used by the figure |
| `RUN_MANIFEST.json` | git SHA, command line, args, wall time, n_cells |

### 1.3 Running it (locally)

```bash
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/multicountry/replay_single_tier_sweep.py \
    --jobs gridpilot/data/traces/m100_real_jobs.parquet \
    --output-dir gridpilot/data/m100/tier_sweep/ \
    --force
```

### 1.4 What to expect

Mostly-flat lift on T0 (by construction) and rising lift on T1 → T3
(more deferral room).  T4 (elastic burst) and T5 (spatial) only
deliver beyond-deferral lift when the dispatcher's elastic-replica
or spatial-routing hooks are fully wired; in the v1.0 kit those
hooks are partially shipped (see [`C2_SPATIAL_AND_WORKFLOW.md`](C2_SPATIAL_AND_WORKFLOW.md))
so T4 and T5 numbers should be read as upper bounds on the
deferral-only contribution.

---

## 2. Hyperparameter sensitivity sweep

### 2.1 Sweep design

Four hyperparameters with measurable effect on CFE lift:

| Hyperparameter | Symbol | Default | Sweep values |
|---|---|---|---|
| Credit-schedule scale | $\alpha$ | $\alpha$ x 1 | {0.5, 1.0, 2.0, 4.0} |
| Deferral-window scale | $W$ | $W$ x 1 | {0.5, 1.0, 2.0} |
| T4 replica-envelope scale | $[0.5, 2.0]$ | scale x 1 | {1.0, 2.0} |
| Short-job threshold | $\tau_{\textrm{short}}$ | 60 s | {1, 60, 300} |

We use a **one-at-a-time design** (vary one hyperparameter while the
others sit at their defaults).  Total: 4+3+2+3 = 12 hyperparameter
settings * 6 grids x 1 MW (default 10) x 8 seeds = **576 cells**.
Wall time ~20-25 min at 4 workers.

A full factorial (4 * 3 * 2 * 3 = 72 settings * 6 * 1 * 8 = 3 456 cells)
is also supported by re-running this driver with comma-lists in the
`SWEEP` dict, but is not worth it for the headline results.

### 2.2 Outputs (under ``data/m100/hyper_sweep/``)

| File | Schema |
|---|---|
| `hyper_sweep.csv` | one row per (country, mw, hyper, value, seed) |
| `HYPER_SUMMARY.csv` | mean per (hyper, value); used by the figure |
| `RUN_MANIFEST.json` | git SHA, command line, args, defaults, design |

### 2.3 Running it (locally)

```bash
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/multicountry/replay_hyperparameter_sweep.py \
    --jobs gridpilot/data/traces/m100_real_jobs.parquet \
    --output-dir gridpilot/data/m100/hyper_sweep/ \
    --force
```

### 2.4 What to expect

`alpha_scale` should have **near-zero effect on CFE lift** (the
credit schedule changes the user's reward, not the dispatcher's
decisions).  `window_scale` should have **moderate positive
effect** (larger windows = more deferral opportunity).
`short_job_s` should have **moderate positive effect** when lowered
to 1 s (almost all jobs become deferral-eligible) but the absolute
gain on the bundled M100 trace is bounded by the trace's smooth
synthesised CI.  `t4_envelope_scale` is **experimental**: it
multiplies the replica-scaling envelope, but the dispatcher hook
that consumes that envelope is partial in v1.0 of the kit, so the
effect is bounded.

---

## 3. Composed figure

```bash
PYTHONPATH=gridpilot/src python3 \
    gridpilot/scripts/figures/fig_tier_and_hyper.py \
    --tier-summary gridpilot/data/m100/tier_sweep/TIER_SUMMARY.csv \
    --hyper-summary gridpilot/data/m100/hyper_sweep/HYPER_SUMMARY.csv \
    --out gridpilot/figs/fig_tier_and_hyper.pdf
```

The figure is a 2x2 panel:

- **(a)** Per-tier CFE lift (T0..T5) at 10 MW, one bar group per
  country.
- **(b)** Per-tier p95 slowdown at 10 MW (the cost of the lift).
- **(c)** Hyperparameter response curves (one line per hyper);
  x-axis is the normalised hyper-value, y-axis is mean CFE %.
- **(d)** Slowdown-vs-CFE Pareto scatter across all hyperparameter
  settings (one marker per (hyper, value)).

Both sweep CSVs are independent: if only one is on disk, the
corresponding two panels render real data and the other two display
an "(awaiting sweep run)" annotation so the figure still compiles.

The figure is included in PECS Section~\ref{sec:results} after the
multi-country headline (Table 2 + Fig.~\ref{fig:country_cfe}).

---

## 4. PECS body text

The figure caption is concise (one sentence: "Per-tier and
hyperparameter sweeps on the M100 trace; interpretation in
Section~\ref{sec:results}.").  The interpretation paragraph in the
body reads roughly:

> The per-tier sweep (Fig.~\ref{fig:tier_and_hyper}(a,b)) isolates
> each tier's contribution.  As predicted by the deferral model
> (Sukprasert et al.~\cite{sukprasert2024shifting}), CFE lift grows
> monotonically with the deferral window up to T3 (week) and then
> saturates; T4 and T5 add new dimensions (elastic replicas, spatial
> routing) whose full evaluation is the subject of the follow-on
> paper (Sect.~\ref{sec:ecosystem}).  The hyperparameter sweep
> (Fig.~\ref{fig:tier_and_hyper}(c,d)) confirms that tuning the
> credit schedule $\alpha$ has near-zero effect on CFE lift (it
> shifts the user's reward, not the dispatcher's behaviour); the
> binding lever is the deferral-window scale.  No hyperparameter
> setting in the one-at-a-time grid breaks through the structural
> ceiling of the bundled M100 trace --- Finding C of
> Sect.~\ref{sec:results} unpacks why.

---

## 5. References between docs

- This file: protocol for the two new sweeps.
- [`COUNTRY_SWEEP_PROTOCOL.md`](COUNTRY_SWEEP_PROTOCOL.md): protocol
  for the headline multi-country sweep.
- [`POLICY_MATRIX_PROTOCOL.md`](POLICY_MATRIX_PROTOCOL.md): protocol
  for the M0..M3 anti-gaming policy matrix.
- [`../../EXPERIMENTS_REMOTE.md`](../../EXPERIMENTS_REMOTE.md):
  canonical remote-run sequence including these sweeps.
- [`COMPANION_PAPERS_MAP.md`](COMPANION_PAPERS_MAP.md): claim-to-
  artefact map for both companion papers.
