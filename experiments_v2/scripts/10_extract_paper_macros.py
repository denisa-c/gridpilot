#!/usr/bin/env python3
r"""
experiments_v2/scripts/10_extract_paper_macros.py
==================================================
Phase 5f --- compile ``figs/paper/results.tex`` for the f-SLA paper.

The f-SLA paper manuscript (``papers/pecs2026/main.tex``) reads every
headline number through ``\InputIfFileExists{figs/results.tex}``;
the existing extractor (``05_extract_macros.py``) was built for the
v1 ``country_sweep.csv`` schema and the now-superseded fsla_M3
mechanism layer.  This script replaces it for the v2 taxonomy
pipeline:

  Inputs
  ------
    --tax-csv   experiments_v2/data/taxonomy_sweep/TAXONOMY_SUMMARY.csv
                  (one row per country x season x layer; aggregated
                   across seeds by 04c_run_taxonomy_sweep.py)
    --mix-csv   experiments_v2/data/taxonomy_sweep/TAXONOMY_MIX.csv
                  (6 rows: per-class GPU.h proportions audit)
    --raw-csv   experiments_v2/data/taxonomy_sweep/taxonomy_sweep.csv
                  (per-seed rows, used for ci_source provenance)

  Output
  ------
    --out       experiments_v2/figs/paper/results.tex

Macros emitted (every Delta macro carries an explicit ``+``/``-``):

  Per-country (for each of SE, CH, FR, IT, DE, PL):
    \PecsCfeFcfs<C>            mean fcfs baseline CFE %
    \PecsCfeFslaTaxonomy<C>    mean fsla_taxonomy CFE %
    \PecsCfeLiftFcfs<C>        fsla_taxonomy - fcfs (signed pp)
    \PecsCiBase<C>             mean fcfs baseline effective CI (g/kWh)
    \PecsCiFsla<C>             mean fsla_taxonomy effective CI (g/kWh)
    \PecsCiLiftFcfs<C>         fcfs - fsla_taxonomy (signed g/kWh)
    \PecsAvoidedFcfs<C>        avoided kt CO2/y scaled to 50 MW
    \PecsBaseCfe<C>            (alias of \PecsCfeFcfs<C>, for table)
    \PecsFslaCfe<C>            (alias of \PecsCfeFslaTaxonomy<C>)
    \PecsCfeLift<C>            (alias of \PecsCfeLiftFcfs<C>)
    \PecsCiLift<C>             (alias of \PecsCiLiftFcfs<C>)
    \PecsAvoidedT<C>           (alias of \PecsAvoidedFcfs<C>)

  Per-class (from TAXONOMY_MIX.csv):
    \PecsClassPctInteractive, ...PctWorkflowCoupled,
    ...PctElasticAi, ...PctBatchParallel, ...PctGeoShiftable,
    ...PctLargeHpc                      (each = pct_gpu_hours, 1 dp)
    \PecsClassNJobsInteractive, ...     (raw job counts as comma int)
    \PecsClassFlexPctGpu                (sum elastic+batch+geo % GPU.h)

  Cross-country aggregates (over the 6 grids, fsla_taxonomy layer):
    \PecsMeanCfeLift                   mean of |Delta CFE| pp
    \PecsBestCfeLift                   max Delta CFE pp
    \PecsBestCfeLiftCountry            country that achieved it
    \PecsLiftBookendSE / Lift...PL     SE and PL anchor values

  Provenance / scalars:
    \PecsHeadlineMW                    headline cluster scale (10 MW)
    \PecsCiSource                      "real ENTSO-E" or "synthesised"
    \PecsCiSourceShort                 "entsoe" or "synth"
    \PecsRealCiFraction                fraction of cells using real CI
    \StubDataPresent                   "true" iff every cell is synth

Usage:
    PYTHONPATH=gridpilot/experiments_v2/src python3 \\
      gridpilot/experiments_v2/scripts/10_extract_paper_macros.py \\
      --tax-csv  gridpilot/experiments_v2/data/taxonomy_sweep/TAXONOMY_SUMMARY.csv \\
      --mix-csv  gridpilot/experiments_v2/data/taxonomy_sweep/TAXONOMY_MIX.csv \\
      --raw-csv  gridpilot/experiments_v2/data/taxonomy_sweep/taxonomy_sweep.csv \\
      --out      gridpilot/experiments_v2/figs/paper/results.tex

Then in main.tex add (next to the existing fallback block):

  \InputIfFileExists{figs/paper/results.tex}{}{}

and run ``papers/build.sh`` to stage the figs/ directory before
compiling.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

# -- Constants (match 05_extract_macros.py where they overlap) ----------
HEADLINE_MW       = 10        # cluster scale of the headline cell
AVOIDED_REPORT_MW = 50        # scale to which avoided tonnes are reported
DAYS_PER_WINDOW   = 7         # 04c default --days-per-window
PUE_HEADLINE      = 1.20      # M100 vendor figure, used in results

# Avoided-tonnage convention: report the carbon savings a hypothetical
# AVOIDED_REPORT_MW cluster would book in one year if it ran continuously
# under the contract.  This is a cleaner, sample-independent denominator
# than the v1 ``sample_energy x annualisation`` formula --- the v2
# taxonomy sweep sub-samples the M100 trace to a fixed N jobs/window,
# so the per-window energy is not a faithful proxy for cluster throughput
# and would understate the avoided tonnage by 2--3 orders of magnitude.
# (Honest interpretation: this is the IT-side savings at the cluster
# scale stated in the table; PUE = 1.20 lifts to facility-side.)
ANNUAL_HOURS               = 8760.0
ANNUAL_ENERGY_REPORT_KWH   = AVOIDED_REPORT_MW * 1.0e3 * ANNUAL_HOURS

COUNTRY_ORDER = ["SE", "CH", "FR", "IT", "DE", "PL"]

# Display name -> CSV class label
CLASSES = [
    ("Interactive",       "interactive"),
    ("WorkflowCoupled",   "workflow_coupled"),
    ("ElasticAi",         "elastic_ai"),
    ("BatchParallel",     "batch_parallel"),
    ("GeoShiftable",      "geo_shiftable"),
    ("LargeHpc",          "large_hpc"),
]


# -- Helpers -------------------------------------------------------------

def _signed(x: float, decimals: int = 1) -> str:
    """Format a number with explicit ``+`` / ``-`` sign character.

    ``+0.5`` / ``-0.5`` / ``0.0`` (no sign on a clean zero).
    """
    if pd.isna(x):
        return "?"
    if abs(x) < 0.5 * 10 ** (-decimals):
        return f"{0.0:.{decimals}f}"
    sign = "+" if x > 0 else "-"
    return f"{sign}{abs(x):.{decimals}f}"


def _plain(x: float, decimals: int = 1) -> str:
    """Format a number with no leading sign (for absolute CFE / CI)."""
    if pd.isna(x):
        return "?"
    return f"{x:.{decimals}f}"


def _intcomma(n: int) -> str:
    """``351786`` -> ``351{,}786`` (LaTeX-friendly thousands separator)."""
    return f"{int(n):,}".replace(",", "{,}")


# -- Macro emission ------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tax-csv", type=Path, required=True,
                   help="TAXONOMY_SUMMARY.csv (mean across seeds, per "
                        "country x season x layer)")
    p.add_argument("--mix-csv", type=Path, required=True,
                   help="TAXONOMY_MIX.csv (per-class GPU.h proportions)")
    p.add_argument("--raw-csv", type=Path, default=None,
                   help="taxonomy_sweep.csv (per-seed; for ci_source "
                        "provenance only)")
    p.add_argument("--mech-csv", type=Path, default=None,
                   help="mechanism_sweep/MECHANISM_SUMMARY.csv (per-mechanism "
                        "NOM-IC violation rate, Jain index, alpha-fair SWF). "
                        "Optional; emits \\PecsNomicViol* macros when present.")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    if not args.tax_csv.exists():
        print(f"ABORT: TAXONOMY_SUMMARY.csv not found at {args.tax_csv}",
              file=sys.stderr)
        return 2
    if not args.mix_csv.exists():
        print(f"ABORT: TAXONOMY_MIX.csv not found at {args.mix_csv}",
              file=sys.stderr)
        return 2

    df = pd.read_csv(args.tax_csv)
    mix = pd.read_csv(args.mix_csv)
    print(f"[10-extract-paper-macros] read {len(df)} rows from {args.tax_csv}")
    print(f"[10-extract-paper-macros] read {len(mix)} rows from {args.mix_csv}")

    # ---- Mean across seasons, keyed by (country, layer) ---------------
    keys = ["country", "layer"]
    metric_cols = ["energy_kwh", "ci_weighted_mean", "cfe_canonical_pct",
                   "co2_g_facility", "p95_slowdown"]
    means = df.groupby(keys, as_index=False)[metric_cols].mean()

    def _get(c: str, layer: str, col: str) -> float:
        row = means[(means["country"] == c) & (means["layer"] == layer)]
        return float(row.iloc[0][col]) if not row.empty else float("nan")

    # ---- Detect CI provenance (synth vs real entsoe) ------------------
    if args.raw_csv and args.raw_csv.exists():
        raw = pd.read_csv(args.raw_csv, usecols=["ci_source"])
        n_real  = int((raw["ci_source"] == "entsoe").sum())
        n_total = int(len(raw))
        real_frac = n_real / max(n_total, 1)
    else:
        real_frac = 0.0
    if real_frac >= 0.95:
        ci_source_long  = "real ENTSO-E hourly A75 generation mix"
        ci_source_short = "entsoe"
        stub_present    = "false"
    elif real_frac > 0.0:
        ci_source_long  = (f"mixed (real ENTSO-E for "
                           f"{real_frac*100:.0f}\\% of cells, synthesised "
                           "diurnal-plus-seasonal envelope for the rest)")
        ci_source_short = "mixed"
        stub_present    = "false"
    else:
        ci_source_long  = ("synthesised diurnal-plus-seasonal envelope "
                           "calibrated to ENTSO-E historicals")
        ci_source_short = "synth"
        stub_present    = "true"

    # ---- Emit macros --------------------------------------------------
    out: list[str] = []
    out.append("% =====================================================================")
    out.append("% experiments_v2/figs/paper/results.tex")
    out.append("% Generated by experiments_v2/scripts/10_extract_paper_macros.py")
    rel_tax = (args.tax_csv.relative_to(ROOT)
               if args.tax_csv.is_relative_to(ROOT) else args.tax_csv)
    out.append(f"% Source (taxonomy):  {rel_tax}")
    rel_mix = (args.mix_csv.relative_to(ROOT)
               if args.mix_csv.is_relative_to(ROOT) else args.mix_csv)
    out.append(f"% Source (class mix): {rel_mix}")
    out.append("% Sign convention: every \\PecsCfeLift / \\PecsCiLift macro")
    out.append("% carries its own sign character. DO NOT add a leading + or - in the table.")
    out.append("% =====================================================================")
    out.append("")
    # main.tex \providecommand's these, so \renewcommand here cleanly
    # overrides the defaults; the rule is providecommand-in-the-paper +
    # renewcommand-in-the-script for every shared macro.
    out.append(f"\\renewcommand{{\\StubDataPresent}}{{{stub_present}}}")
    out.append(f"\\renewcommand{{\\PecsHeadlineMW}}{{{HEADLINE_MW}}}")
    out.append(f"\\providecommand{{\\PecsHeadlineLayer}}{{fsla\\_taxonomy}}")
    out.append(f"\\renewcommand{{\\PecsCiSource}}{{{ci_source_long}}}")
    out.append(f"\\renewcommand{{\\PecsCiSourceShort}}{{{ci_source_short}}}")
    out.append(f"\\renewcommand{{\\PecsRealCiFraction}}{{{real_frac*100:.0f}\\%}}")
    out.append("")

    # ---- Per-country macros (override the fallback block) -------------
    out.append("% Per-country CFE / CI / avoided macros (override fallback in main.tex)")
    for c in COUNTRY_ORDER:
        cfe_b = _get(c, "fcfs",          "cfe_canonical_pct")
        cfe_f = _get(c, "fsla_taxonomy", "cfe_canonical_pct")
        ci_b  = _get(c, "fcfs",          "ci_weighted_mean")
        ci_f  = _get(c, "fsla_taxonomy", "ci_weighted_mean")
        d_cfe = cfe_f - cfe_b              # >0 ⇔ contract improves CFE
        d_ci  = ci_b  - ci_f               # >0 ⇔ contract cleans CI

        # Avoided tonnage at AVOIDED_REPORT_MW for one year of continuous
        # operation.  Sample-independent: uses cluster annual energy x
        # measured Delta CI x PUE, so the table column reads as "savings
        # an operator at this scale would book".  Always sign-consistent
        # with Delta CFE (no v1-style sign-disagreement bug).
        avoided_kt = (d_ci * ANNUAL_ENERGY_REPORT_KWH * PUE_HEADLINE) / 1e9

        out.append(f"% --- {c} ---")
        # Renew the macros so the main.tex fallback values are replaced
        # when this file is \input'ed; this is what lets the paper carry
        # a working set of placeholders pre-build and real numbers post.
        out.append(f"\\renewcommand{{\\PecsBaseCfe{c}}}{{{_plain(cfe_b, 1)}}}")
        out.append(f"\\renewcommand{{\\PecsFslaCfe{c}}}{{{_plain(cfe_f, 1)}}}")
        out.append(f"\\renewcommand{{\\PecsCfeLift{c}}}{{{_signed(d_cfe, 2)}}}")
        out.append(f"\\renewcommand{{\\PecsCiBase{c}}}{{{_plain(ci_b, 0)}}}")
        out.append(f"\\renewcommand{{\\PecsCiLift{c}}}{{{_signed(d_ci, 1)}}}")
        out.append(f"\\renewcommand{{\\PecsAvoidedT{c}}}{{{_signed(avoided_kt, 3)}}}")
        # Long-form (preferred for future tables, alongside the table aliases above).
        # providecommand so re-runs of the script don't error on double definition.
        out.append(f"\\providecommand{{\\PecsCfeFcfs{c}}}{{{_plain(cfe_b, 1)}}}")
        out.append(f"\\providecommand{{\\PecsCfeFslaTaxonomy{c}}}{{{_plain(cfe_f, 1)}}}")
        out.append(f"\\providecommand{{\\PecsCfeLiftFcfs{c}}}{{{_signed(d_cfe, 2)}}}")
        out.append(f"\\providecommand{{\\PecsCiFsla{c}}}{{{_plain(ci_f, 0)}}}")
        out.append(f"\\providecommand{{\\PecsCiLiftFcfs{c}}}{{{_signed(d_ci, 1)}}}")
        out.append(f"\\providecommand{{\\PecsAvoidedFcfs{c}}}{{{_signed(avoided_kt, 3)}}}")
        out.append("")

    # ---- Per-class macros (workload composition audit) ----------------
    out.append("% Per-class workload composition (TAXONOMY_MIX.csv)")
    mix_by_class = {row["class"]: row for _, row in mix.iterrows()}
    flex_pct_gpu = 0.0
    for display, csv_label in CLASSES:
        if csv_label not in mix_by_class:
            out.append(f"% (missing class: {csv_label})")
            continue
        row = mix_by_class[csv_label]
        pct = float(row["pct_gpu_hours"])
        n   = int(row["n_jobs"])
        out.append(f"\\renewcommand{{\\PecsClassPct{display}}}{{{pct:.1f}}}")
        out.append(f"\\providecommand{{\\PecsClassNJobs{display}}}{{{_intcomma(n)}}}")
        if csv_label in ("elastic_ai", "batch_parallel", "geo_shiftable"):
            flex_pct_gpu += pct
    out.append(f"\\renewcommand{{\\PecsClassFlexPctGpu}}{{{flex_pct_gpu:.1f}}}")
    out.append("")

    # ---- Cross-country aggregates -------------------------------------
    out.append("% Cross-country aggregates (mean / best / bookends)")
    lifts = {}
    for c in COUNTRY_ORDER:
        lifts[c] = (_get(c, "fsla_taxonomy", "cfe_canonical_pct")
                    - _get(c, "fcfs", "cfe_canonical_pct"))
    mean_lift = sum(lifts.values()) / len(lifts)
    best_c    = max(lifts, key=lambda c: lifts[c])
    best_lift = lifts[best_c]
    out.append(f"\\renewcommand{{\\PecsMeanCfeLift}}{{{_signed(mean_lift, 2)}}}")
    out.append(f"\\renewcommand{{\\PecsBestCfeLift}}{{{_signed(best_lift, 2)}}}")
    out.append(f"\\renewcommand{{\\PecsBestCfeLiftCountry}}{{{best_c}}}")
    # Bookends (the headline pair the paper cites).
    out.append(f"\\renewcommand{{\\PecsLiftBookendSE}}{{{_signed(lifts['SE'], 2)}}}")
    out.append(f"\\renewcommand{{\\PecsLiftBookendPL}}{{{_signed(lifts['PL'], 2)}}}")

    # ---- Per-class CFE on the dirtiest grid (PL), for the body text ---
    out.append("")
    out.append("% Per-class CFE under fsla_taxonomy on PL (dirtiest grid),")
    out.append("% useful for the class-breakdown narrative.")
    pl_rows = df[(df["country"] == "PL") & (df["layer"] == "fsla_taxonomy")]
    if not pl_rows.empty:
        pl = pl_rows.mean(numeric_only=True)
        for display, csv_label in CLASSES:
            col = f"class_{csv_label}_cfe_pct"
            if col in pl.index and not pd.isna(pl[col]):
                out.append(f"\\providecommand{{\\PecsClassCfePl{display}}}"
                           f"{{{_plain(float(pl[col]), 1)}}}")

    # ---- Mechanism-sweep macros (Finding D / Lesson L3) --------------
    # LaTeX command names cannot contain digits, so the macro keys
    # spell the mechanism index out: M0 -> MZero, M1 -> MOne, etc.
    # main.tex \providecommand's these names to "?" in the preamble,
    # so the script MUST use \renewcommand here (a second
    # \providecommand would be a no-op and leave the "?" defaults
    # visible in the rendered PDF).
    out.append("")
    out.append("% Mechanism-sweep results (04d_run_mechanism_sweep.py).")
    MECH_LETTER = {"M0": "MZero", "M1": "MOne",
                    "M2": "MTwo", "M3": "MThree"}
    if args.mech_csv and args.mech_csv.exists():
        mech = pd.read_csv(args.mech_csv).set_index("mechanism")
        for m_csv, m_tex in MECH_LETTER.items():
            if m_csv not in mech.index:
                continue
            row = mech.loc[m_csv]
            v = float(row["violation_rate_pct"])
            j = float(row["jain_index"])
            s = float(row["alpha_fair_swf_a1"])
            out.append(f"\\renewcommand{{\\PecsNomicViol{m_tex}}}"
                       f"{{{_plain(v, 1)}}}")
            out.append(f"\\renewcommand{{\\PecsJain{m_tex}}}"
                       f"{{{_plain(j, 3)}}}")
            out.append(f"\\renewcommand{{\\PecsSwf{m_tex}}}"
                       f"{{{_plain(s, 1)}}}")
        # Headline ratio: by how many factors does M3 beat M0?
        if "M0" in mech.index and "M3" in mech.index:
            v0 = float(mech.loc["M0", "violation_rate_pct"])
            v3 = float(mech.loc["M3", "violation_rate_pct"])
            ratio = v0 / max(v3, 1e-3)
            out.append(f"\\renewcommand{{\\PecsNomicMThreevsMZeroRatio}}"
                       f"{{{_plain(ratio, 1)}}}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out) + "\n")
    print(f"[10-extract-paper-macros] wrote {args.out} "
          f"({len(out)} lines, ci_source={ci_source_short})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
