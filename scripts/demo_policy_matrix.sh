#!/usr/bin/env bash
# =====================================================================
# scripts/demo_policy_matrix.sh
# -----------------------------
# One-shot reproducibility script:
#   1. Seeds literature-anchored stub CSVs so figures + papers rebuild
#      before the heavy real replays run.
#   2. Renders the result figures (B&W-print friendly).
#   3. Generates the editable architecture .pptx masters and the
#      matplotlib placeholder architecture PDFs (one per paper).
#
# To replace the stubs with real numbers, run
#   PYTHONPATH=src python scripts/m100/replay_policy_matrix.py ...
#   PYTHONPATH=src python scripts/multicountry/replay_country_sweep.py ...
# (see docs/POLICY_MATRIX_PROTOCOL.md and COUNTRY_SWEEP_PROTOCOL.md)
# and re-run the figure steps below.
# =====================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${ROOT}/.." && pwd)"
cd "${ROOT}"

# Prefer the bundled gridpilot/.venv interpreter; fall back to $PYTHON / python3.
if [[ -x "${ROOT}/.venv/bin/python3" ]]; then
    PYTHON="${PYTHON:-${ROOT}/.venv/bin/python3}"
else
    PYTHON="${PYTHON:-python3}"
fi
PDFLATEX="${PDFLATEX:-pdflatex}"

mkdir -p figs data/m100/policy_matrix data/m100/country_sweep
mkdir -p "${PROJECT_ROOT}/papers/pecs2026/figs"
mkdir -p "${PROJECT_ROOT}/papers/whpc2026/figs"

echo "==> 1/4  Seed stub policy_matrix.csv (anti-gaming policy matrix)"
PYTHONPATH=src "${PYTHON}" scripts/m100/seed_policy_matrix_stub.py \
    --output-dir data/m100/policy_matrix

echo "==> 1b/4 Seed stub country_sweep.csv (multi-country CFE-lift)"
PYTHONPATH=src "${PYTHON}" scripts/multicountry/seed_country_sweep_stub.py \
    --output-dir data/m100/country_sweep

echo "==> 2/4  Render f-SLA paper policy-matrix figures (B&W-print friendly)"
for fig in fig_cfe_by_tier fig_swf_comparison fig_fairness_pareto fig_latency_per_tier; do
    PYTHONPATH=src "${PYTHON}" "scripts/figures/${fig}.py" \
        --matrix data/m100/policy_matrix/policy_matrix.csv \
        --out "figs/${fig}.pdf"
done

echo "==> 2b/4 Render multi-country figures"
for fig in fig_country_cfe_lift fig_country_pue_aware; do
    PYTHONPATH=src "${PYTHON}" "scripts/figures/${fig}.py" \
        --matrix data/m100/country_sweep/country_sweep.csv \
        --out "figs/${fig}.pdf"
done

echo "==> 3/4  Generate editable architecture .pptx for both papers"
if ! "${PYTHON}" -c "import pptx" >/dev/null 2>&1; then
    echo "[demo] installing python-pptx (one-time)"
    "${PYTHON}" -m pip install --quiet python-pptx || \
        echo "[demo] pip install python-pptx failed; skipping pptx generation"
fi
if "${PYTHON}" -c "import pptx" >/dev/null 2>&1; then
    PYTHONPATH=src "${PYTHON}" scripts/figures/make_architecture_pptx.py
fi

echo "==> 3b/4 Extract paper macros from on-disk experiment outputs"
# This populates papers/<paper>/figs/results.tex with \newcommand
# macros that the .tex sources read via \input{results.tex}.  The
# script emits a STUB warning if f-SLA paper data came from the literature-
# anchored stub instead of a real replay_country_sweep.py run.
PYTHONPATH=src "${PYTHON}" scripts/figures/extract_paper_macros.py

echo "==> 4/4  Render placeholder architecture PDFs (per-paper)"
# Each paper's figs/architecture.pdf is rendered by a dedicated
# matplotlib script; the user can replace these by exporting the
# corresponding architecture.pptx from PowerPoint or Keynote
# (File > Export > PDF -> overwrite the same path).
PYTHONPATH=src "${PYTHON}" scripts/figures/fig_fsla_architecture.py \
    --out "${PROJECT_ROOT}/papers/pecs2026/figs/architecture.pdf"
PYTHONPATH=src "${PYTHON}" scripts/figures/fig_gridpilot_architecture.py \
    --out "${PROJECT_ROOT}/papers/whpc2026/figs/architecture.pdf"

# Legacy artefact kept for the older f-SLA paper draft that referenced
# fig_gamification_architecture.pdf; tries TikZ first then matplotlib.
if ( cd figs && "${PDFLATEX}" -interaction=nonstopmode -halt-on-error \
        fig_gamification_architecture.tex >/dev/null 2>&1 ); then
    echo "[demo] (legacy) TikZ gamification arch built"
else
    PYTHONPATH=src "${PYTHON}" scripts/figures/fig_gamification_architecture.py \
        --out figs/fig_gamification_architecture.pdf 2>/dev/null || true
fi

echo
echo "OK  figures and architecture PDFs ready in:"
echo "    ${ROOT}/figs/                              (stage-from source)"
echo "    ${PROJECT_ROOT}/papers/pecs2026/figs/      (f-SLA paper-ready)"
echo "    ${PROJECT_ROOT}/papers/whpc2026/figs/      (GridPilot-ready)"
echo "    architecture.pptx in each paper folder     (refine in PowerPoint)"
echo "Rebuild the papers with:  ./papers/build.sh"
