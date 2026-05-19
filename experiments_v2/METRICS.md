# METRICS — closed-form definitions for the v2 pipeline

Every quantity reported by the v2 pipeline is defined here as a
closed-form expression on observable inputs.  The `00_unit_audit.py`
script tests each metric against a reference value computed from
these formulae; any drift fail-stops the orchestrator.

Notation:

- $J$ = set of completed jobs in the replay.
- $e_j$ = energy in kWh consumed by job $j$, computed as
  $e_j = \mathrm{nodes}_j \cdot \mathrm{runtime}_j / 3600 \cdot P_{\mathrm{node}}$
  with $P_{\mathrm{node}} = 1.5$ kW (M100 vendor figure).
- $\mathrm{CI}(t)$ = grid carbon intensity at wall-clock time $t$, in g CO₂eq / kWh.
- $\mathrm{CI}_j$ = $\mathrm{CI}(\mathrm{start}_j)$, evaluated at the job's start time.
- $E = \sum_{j \in J} e_j$ = total energy consumed by completed jobs.
- $\mathrm{PUE}(t)$ = facility power-usage effectiveness at time $t$ (from the four-component cooling model anchored on `raps/config/marconi100.yaml`).
- $\mathrm{CI}_{\mathrm{ref}} = 800$ g CO₂eq / kWh — the fossil-marginal reference for canonical 24/7 CFE (Kamatar et al., 2025).
- $\mathrm{CI}_{\mathrm{thr}} = 150$ g CO₂eq / kWh — the EU 2030 grid-decarbonisation target; used only for the legacy threshold-based CFE.

---

## 1. Energy-weighted effective grid CI

$$\mathrm{CI}_{\mathrm{eff}} \;=\; \frac{\sum_{j \in J} \mathrm{CI}_j \cdot e_j}{E} \quad \text{(g CO₂eq / kWh)}$$

Implementation: `_ci_weighted_mean_g(result, ci_df)` in
`replay_country_sweep.py`.

Reference values for the unit test:

| Test | Inputs | Expected $\mathrm{CI}_{\mathrm{eff}}$ |
|------|--------|---------------------------------------|
| All jobs at CI = 0 | $\mathrm{CI}_j \equiv 0$ | 0 g/kWh |
| All jobs at CI = 800 | $\mathrm{CI}_j \equiv 800$ | 800 g/kWh |
| 50% energy at CI=0, 50% at CI=200 | balanced | 100 g/kWh |
| Empty job set | $J = \emptyset$ | 0 g/kWh (defined value) |

---

## 2. Canonical 24/7 Carbon-Free-Energy share (HEADLINE METRIC)

$$\mathrm{CFE}_{24/7} \;=\; 100 \cdot \max\!\left(0,\ 1 - \frac{\mathrm{CI}_{\mathrm{eff}}}{\mathrm{CI}_{\mathrm{ref}}}\right) \quad \text{(percent, clipped to [0, 100])}$$

This is a **load-weighted carbon-free-supply match**, not a fraction
of hours below a threshold.  It is the metric of Kamatar et al. (2025)
and Google's 24/7 CFE programme (Radovanovic et al., 2021).

Implementation: `_cfe_canonical_pct(result, ci_df)` —
$\mathrm{CI}_{\mathrm{eff}}$ from §1, then the formula above.

Reference values:

| Test | $\mathrm{CI}_{\mathrm{eff}}$ | Expected CFE |
|------|------------------------------|--------------|
| SE-clean | 11 g/kWh | 98.625 % |
| Fossil-only | 800 g/kWh | 0 % |
| Above reference | 1200 g/kWh | 0 % (clipped) |
| Negative impossible | n/a | n/a |

---

## 3. Legacy threshold CFE (secondary metric only)

$$\mathrm{CFE}_{\mathrm{thr}} \;=\; 100 \cdot \frac{\sum_{j \in J} e_j \cdot \mathbb{1}[\mathrm{CI}_j \le \mathrm{CI}_{\mathrm{thr}}]}{E} \quad \text{(percent)}$$

Reported as a secondary column in CSV for backward compatibility
with v1 figures.  **Not used in Table 2.**

Implementation: `_cfe_threshold_pct(result, ci_df, threshold_g)`.

---

## 4. IT carbon emissions

$$\mathrm{CO}_2^{\mathrm{IT}} \;=\; \sum_{j \in J} \mathrm{CI}_j \cdot e_j \quad \text{(g CO₂eq)}$$

i.e. $\mathrm{CO}_2^{\mathrm{IT}} = E \cdot \mathrm{CI}_{\mathrm{eff}}$.

## 5. Facility carbon emissions (PUE-corrected)

$$\mathrm{CO}_2^{\mathrm{fac}} \;=\; \sum_{j \in J} \mathrm{CI}_j \cdot e_j \cdot \mathrm{PUE}(\mathrm{start}_j) \quad \text{(g CO₂eq)}$$

The PUE multiplier is evaluated at the job's start time, not at a
static facility average — this is the load-bearing correction that
distinguishes facility-meter CFE from intensity-based reporting.

## 6. Annualised avoided emissions

The replay covers $D$ days of trace (28 d for Jan-only, ~56 d for
the extended Jan+Feb).  Annualisation factor $A = 365/D$.

$$\mathrm{Avoided}^{\mathrm{kt/y}}_{\mathrm{base}}(c, \mathrm{MW}, m) \;=\; \frac{\left(\mathrm{CO}_2^{\mathrm{fac,base}} - \mathrm{CO}_2^{\mathrm{fac},m}\right) \cdot A \cdot s_{\mathrm{MW}}}{10^{12}}$$

where $s_{\mathrm{MW}} = \mathrm{MW}_{\mathrm{target}} / \mathrm{MW}_{\mathrm{trace}}$
scales the trace's emissions to the target cluster size, and the
$10^{12}$ converts g → kt.

Two baselines are reported (per the v2 design decision):

- $\mathrm{base} = \mathrm{plain\ FCFS}$ — the CI-blind status quo
- $\mathrm{base} = \mathrm{EASY\text{-}FCFS\ CI\text{-}aware}$ — the already-carbon-aware counterpart

## 7. Lift metrics

For each row $(c, \mathrm{MW}, m)$ in the headline CSV:

$$\Delta \mathrm{CFE}_{24/7,\mathrm{vs\ FCFS}}(c, \mathrm{MW}, m) \;=\; \mathrm{CFE}_{24/7}(c, \mathrm{MW}, m) - \mathrm{CFE}_{24/7}(c, \mathrm{MW}, \mathrm{FCFS})$$

$$\Delta \mathrm{CFE}_{24/7,\mathrm{vs\ EASY}}(c, \mathrm{MW}, m) \;=\; \mathrm{CFE}_{24/7}(c, \mathrm{MW}, m) - \mathrm{CFE}_{24/7}(c, \mathrm{MW}, \mathrm{EASY\text{-}FCFS})$$

$$\Delta \mathrm{CI}_{\mathrm{vs\ FCFS}}(c, \mathrm{MW}, m) \;=\; \mathrm{CI}_{\mathrm{eff}}(c, \mathrm{MW}, \mathrm{FCFS}) - \mathrm{CI}_{\mathrm{eff}}(c, \mathrm{MW}, m)$$

(Note the sign: positive $\Delta$ CI = mechanism *reduced* effective
CI = improvement.  This is the convention used in the rendered
table; do not flip signs in the extractor.)

## 8. Sign convention — END-TO-END

The whole pipeline uses the following convention:

> **Positive ⟹ improvement vs baseline.**

Concretely:

- $\Delta \mathrm{CFE} > 0$ means the mechanism shifted more compute
  to carbon-free supply than the baseline.
- $\Delta \mathrm{CI} > 0$ means the mechanism reduced the effective
  grid CI (= cleaner placement).
- $\mathrm{Avoided}^{\mathrm{kt/y}} > 0$ means the mechanism emitted
  less than the baseline.

The macro extractor (`05_extract_macros.py`) emits values with an
**explicit sign character**: `+0.5`, `-0.5`, or `0.0`.  The LaTeX
template **does not** add its own `+` or `-` prefix.  Test 2 of the
audit suite (§Phase 2) verifies this end-to-end.

## 9. Statistical significance

Each $(c, \mathrm{MW}, m)$ cell is run with 8 Monte-Carlo seeds.
The reported headline value is the mean over seeds; the **bootstrap
95 % CI** is computed by 10 000 percentile resamples of the 8 per-
seed values.

A claim of the form *"f-SLA produces a positive Δ CFE on grid c"*
requires the lower edge of the 95 % CI to be > 0.  Cells where the
95 % CI straddles 0 are reported as **null** with both the mean and
the CI in the CSV.

## 10. Data provenance

Every cell JSON written by the v2 sweeps carries:

```json
{
  "_meta": {
    "git_sha": "...",
    "computed_utc": "...",
    "trace_sha256": "...",
    "ci_source": "entsoe_a75" | "synth_diurnal",
    "ci_data_sha256": "...",
    "scheduler_kwargs": { ... },
    "t4_envelope": [0.5, 2.0],
    "schema_version": 2
  },
  ... cell columns ...
}
```

The orchestrator refuses to consume any cell whose `_meta.schema_version`
does not match.  No back-fill, no schema drift.
