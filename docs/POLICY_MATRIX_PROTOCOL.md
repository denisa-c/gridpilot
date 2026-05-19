# Policy-matrix protocol (PECS anti-gaming policy matrix, `sec:fsla`)

This protocol explains how the four PECS-paper figures backing the anti-gaming policy matrix (M0..M3 mechanisms × 5 baseline policies) are produced and how each maps to a pre-registered hypothesis (FSLA_GAMIFICATION_POC_PLAN.md §8).  Internal source-code comments still tag this as "Finding 4" — the legacy single-paper draft's numbering; see `RATIONALE.md` §13.

## 1. Inputs

- M100 trace: `data/traces/m100_real_jobs.parquet`
- CI series: `configs/grids/{CH,IT,DE}.yaml` (synthesised from annual mean + diurnal/weekly/seasonal patterns; see `_synthesise_ci` in `scripts/m100/inject_fsla_prior.py`)
- Cooling YAML: `raps/config/marconi100.yaml`

## 2. One-shot replay

```bash
PYTHONPATH=src python scripts/m100/replay_policy_matrix.py \
    --jobs    data/traces/m100_real_jobs.parquet \
    --ci      configs/grids/DE.yaml \
    --pue     raps/config/marconi100.yaml \
    --policies   FCFS,EASY,SAF,RLBackfilling,GridPilot-PUE \
    --mechanisms none,M0,M1,M2,M3 \
    --seeds 8 \
    --workers 4 \
    --output-dir data/m100/policy_matrix/
```

Wall time: ~ 45 min on a 16-core workstation; produces
`policy_matrix.csv` (one row per cell, 200 rows by default) plus
`HYPOTHESIS_OUTCOMES.json` summarising H1-H4 (H5 is filled in by the
latency-figure script below).

## 3. Figures

Each figure script reads `policy_matrix.csv` and writes a vector PDF
under `figs/`:

```bash
PYTHONPATH=src python scripts/figures/fig_cfe_by_tier.py        # Fig. cfe_lift  (H1)
PYTHONPATH=src python scripts/figures/fig_swf_comparison.py     # Fig. swf       (H4)
PYTHONPATH=src python scripts/figures/fig_fairness_pareto.py    # Fig. fairness  (H3)
PYTHONPATH=src python scripts/figures/fig_latency_per_tier.py   # Fig. latency   (H5)
```

The latency figure also updates `data/m100/policy_matrix/HYPOTHESIS_OUTCOMES.json`
with the H5 outcome (p95 at GridPilot-PUE+M3 vs. FCFS+none baseline).

## 4. Architecture figure

```bash
pdflatex --output-directory=figs figs/fig_gamification_architecture.tex
```

Produces `figs/fig_gamification_architecture.pdf`, a fully editable
vector PDF (TikZ source remains in `.tex` for Illustrator/Inkscape
round-trips).

## 5. Verification

```bash
PYTHONPATH=src pytest tests/test_gaming_mechanisms.py -q
```

Eight tests, all passing in ≤ 5 s.  Failure of any test invalidates
the corresponding hypothesis-acceptance claim in §5.5/§7 of the paper.

## 6. Quick smoke run (no real M100 trace required)

If you only want to verify that the pipeline wires together end-to-
end without running the full 45-min sweep:

```bash
PYTHONPATH=src python -c "from scheduler.fsla_mechanisms import build_mechanism; \
    [build_mechanism(m) for m in ('M0','M1','M2','M3')]; \
    print('all four mechanisms instantiated OK')"
```

## 7. Where each pre-registered hypothesis is verified

| Hypothesis | Acceptance criterion                                              | Figure                  | Test |
|------------|-------------------------------------------------------------------|-------------------------|------|
| H1         | $\geq 3$ of M0-M3 keep $\Delta_{IT} \geq 2$ pp over baseline      | `fig_cfe_by_tier.pdf`   | `replay_policy_matrix._evaluate_hypotheses` |
| H2         | M3 NOM-IC violation rate $< 1\%$                                  | (audit metadata in CSV) | `test_ai_baseline_audit_no_penalty_when_realised_matches_declared` + matrix |
| H3         | All cells Jain $\geq 0.95 \times$ FCFS Jain                       | `fig_fairness_pareto.pdf` | `test_jain_fairness_bounds` |
| H4         | $\alpha=2$ SWF under M2 $\geq$ M0 at same $\Delta_{IT}$           | `fig_swf_comparison.pdf` | `test_swf_alpha_limits_match_utilitarian_and_leximin` |
| H5         | p95 latency non-decreasing in tier index for every mechanism      | `fig_latency_per_tier.pdf` | `test_posted_price_tier_assignment_monotone` (proxy) |
