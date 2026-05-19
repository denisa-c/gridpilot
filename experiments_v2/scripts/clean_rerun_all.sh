#!/usr/bin/env bash
# =====================================================================
# experiments_v2/scripts/clean_rerun_all.sh
# ---------------------------------------------------------------------
# Master orchestrator for the clean-room PECS rerun.  Runs Phases 1
# through 5 of the v2 plan with FAIL-STOP gating between phases.  No
# downstream phase is allowed to execute if its upstream gate failed.
#
# Phases (each maps to one numbered script):
#   1.  00_unit_audit.py            ← closed-form metric tests
#   1b. tests/test_schedulers.py    ← per-scheduler sanity tests
#                                     (FCFS pathology, EASY backfill,
#                                      SAF priority, REPLAY history,
#                                      F3 truncation)
#   2.  01_single_cell_smoketest.py ← end-to-end sign trace on SE,10MW
#   3.  (manual audit; not orchestrated --- see README.md §5)
#   4.  02_run_country_sweep.py     ← 1008 cells, all 4 baselines + M3
#       03_run_tier_sweep.py        ← 864 cells, per-tier ablation
#       04_run_hyper_sweep.py       ← 576 cells, hyperparameter sweep
#   5.  05_extract_macros.py        ← signed macros, no hardcoded prefix
#       06_render_figures.py        ← v2 figure PDFs
#       papers/build.sh             ← rebuild the PECS PDF
#
# Scripts 02–06 are NOT YET WRITTEN.  This orchestrator runs Phases 1
# and 2 to completion (the foundation) and then prints a clear
# "WAITING FOR SCRIPT" line for each missing phase, with the exact
# next-step the user needs.  When you add a missing script and
# re-run, the orchestrator picks it up automatically.
#
# Usage:
#     bash gridpilot/experiments_v2/scripts/clean_rerun_all.sh
#
# Env-var knobs:
#     SKIP_GATES=1     skip Phases 1 and 1b (fast iteration on Phase 2+)
#     SKIP_SWEEPS=1    run only the gates (Phases 1, 1b, 2); useful in CI
#     FRESH=1          wipe experiments_v2/data/*/cells/ before starting
#     WORKERS=<n>      pool size for the three sweep drivers (default 4)
#     ENTSOE_API_KEY   exported  → real ENTSO-E CI on (recommended for v2)
#     ALLOW_SYNTH_CI=1 permit synthetic CI fallback if no API key
#
# Exit codes:
#     0   every phase that has a script ran cleanly
#     1   Phase 1 unit audit failed
#     2   Phase 1b scheduler unit tests failed
#     3   Phase 2 smoketest failed (sign convention violation)
#     4   Phase 4 sweep failed
#     5   Phase 5 extractor / build failed
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GRIDPILOT_ROOT="$(cd "${V2_ROOT}/.." && pwd)"
PROJECT_ROOT="$(cd "${GRIDPILOT_ROOT}/.." && pwd)"

if [[ -x "${GRIDPILOT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON="${PYTHON:-${GRIDPILOT_ROOT}/.venv/bin/python3}"
else
    PYTHON="${PYTHON:-python3}"
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="${V2_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/v2_clean_rerun_${STAMP}.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "======================================================================"
echo "experiments_v2 clean rerun"
echo "  start_utc  : ${STAMP}"
echo "  v2 root    : ${V2_ROOT}"
echo "  python     : ${PYTHON}"
echo "  workers    : ${WORKERS:-4}"
echo "  fresh      : ${FRESH:-0}"
echo "  skip_gates : ${SKIP_GATES:-0}"
echo "  skip_sweeps: ${SKIP_SWEEPS:-0}"
echo "  log        : ${LOG_FILE}"
echo "  git sha    : $(cd "${PROJECT_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "======================================================================"

# ---- 0. FRESH: archive v1 + wipe v2 cells ---------------------------
if [[ "${FRESH:-0}" == "1" ]]; then
    ARCHIVE_DIR="${V2_ROOT}/archived_v1_${STAMP}"
    if [[ -d "${GRIDPILOT_ROOT}/data/m100" ]]; then
        echo ""
        echo "[FRESH] archiving v1 data → ${ARCHIVE_DIR}"
        mkdir -p "${ARCHIVE_DIR}"
        cp -a "${GRIDPILOT_ROOT}/data/m100" "${ARCHIVE_DIR}/v1_data_m100"
    fi
    if [[ -d "${V2_ROOT}/data" ]]; then
        echo "[FRESH] wiping previous v2 cells under ${V2_ROOT}/data"
        rm -rf "${V2_ROOT}/data"/*/cells "${V2_ROOT}/data"/*/RUN_MANIFEST.json
    fi
fi
mkdir -p "${V2_ROOT}/data/country_sweep" \
         "${V2_ROOT}/data/tier_sweep" \
         "${V2_ROOT}/data/hyper_sweep" \
         "${V2_ROOT}/figs"

# ---- Helpers --------------------------------------------------------
_phase_banner() {
    local title="$1"
    echo ""
    echo "----------------------------------------------------------------------"
    echo "${title}"
    echo "----------------------------------------------------------------------"
}

_missing_script() {
    # _missing_script <phase_label> <script_path> <next-step-hint>
    local label="$1"; local path="$2"; local hint="$3"
    echo ""
    echo "[SKIP] ${label}"
    echo "       script not yet written: ${path}"
    echo "       next step: ${hint}"
    echo "       this is expected during incremental v2 build-out."
    echo "       Once the script exists, re-run this orchestrator to pick it up."
}

# Counters for the final summary banner.
N_RAN=0
N_SKIPPED=0

# ---- 1. PHASE 1 GATE: closed-form metric audit ----------------------
if [[ "${SKIP_GATES:-0}" != "1" ]]; then
    _phase_banner "Phase 1 — unit audit (closed-form metric tests)"
    if [[ -f "${V2_ROOT}/scripts/00_unit_audit.py" ]]; then
        PYTHONPATH="${GRIDPILOT_ROOT}/src" \
            "${PYTHON}" "${V2_ROOT}/scripts/00_unit_audit.py" || {
            echo "GATE FAIL: unit audit did not pass.  Stopping rerun."
            exit 1
        }
        N_RAN=$((N_RAN + 1))
    else
        _missing_script "Phase 1 — unit audit" \
            "${V2_ROOT}/scripts/00_unit_audit.py" \
            "write the unit audit (it should exist; check your checkout)"
        exit 1
    fi

    # ---- 1b. PHASE 1b GATE: per-scheduler sanity tests --------------
    _phase_banner "Phase 1b — scheduler unit tests (FCFS pathology, EASY backfill, SAF, REPLAY)"
    if [[ -f "${V2_ROOT}/tests/test_schedulers.py" ]]; then
        PYTHONPATH="${V2_ROOT}/src" \
            "${PYTHON}" "${V2_ROOT}/tests/test_schedulers.py" || {
            echo "GATE FAIL: at least one scheduler unit test did not pass."
            echo "  This means the v2 hand-rolled schedulers have a bug;"
            echo "  do NOT proceed to Phase 2 until it's fixed."
            exit 2
        }
        N_RAN=$((N_RAN + 1))
    else
        _missing_script "Phase 1b — scheduler unit tests" \
            "${V2_ROOT}/tests/test_schedulers.py" \
            "write tests for fcfs / easy_fcfs / saf / replay"
        exit 2
    fi
else
    echo ""
    echo "[SKIP_GATES=1] skipping Phases 1 and 1b"
fi

# ---- 2. PHASE 2 GATE: single-cell sign-convention smoketest ---------
_phase_banner "Phase 2 — single-cell smoketest (SE, 10 MW, seed 0)"
if [[ -f "${V2_ROOT}/scripts/01_single_cell_smoketest.py" ]]; then
    PYTHONPATH="${GRIDPILOT_ROOT}/src" \
        "${PYTHON}" "${V2_ROOT}/scripts/01_single_cell_smoketest.py" || {
        echo "GATE FAIL: single-cell smoketest detected a problem."
        echo "  Likely causes: sign-convention drift, scheduler bug,"
        echo "  M100 trace not present (run build_extended_trace.py first)."
        exit 3
    }
    N_RAN=$((N_RAN + 1))
else
    _missing_script "Phase 2 — single-cell smoketest" \
        "${V2_ROOT}/scripts/01_single_cell_smoketest.py" \
        "write the smoketest (it should exist; check your checkout)"
    exit 3
fi

if [[ "${SKIP_SWEEPS:-0}" == "1" ]]; then
    echo ""
    echo "SKIP_SWEEPS=1 set; stopping after Phase 2."
    echo "Ran ${N_RAN} phases; ${N_SKIPPED} skipped."
    exit 0
fi

# ---- 3. ENTSO-E sanity check (v2 prefers real CI) -------------------
if [[ -z "${ENTSOE_API_KEY:-}" ]] && [[ "${ALLOW_SYNTH_CI:-0}" != "1" ]]; then
    echo ""
    echo "WARN: \$ENTSOE_API_KEY is not set."
    echo "      v2 headline numbers are intended against REAL ENTSO-E hourly"
    echo "      CI, not the synthesised diurnal envelopes used in v1."
    echo "      Get a free token at https://transparency.entsoe.eu and"
    echo "      export it before running this orchestrator in 'full' mode."
    echo "      To continue with synthesised CI anyway, set ALLOW_SYNTH_CI=1."
    echo ""
    echo "Stopping before sweeps.  Phases 4 and 5 not attempted."
    echo "Ran ${N_RAN} phases."
    exit 0
fi

# ---- 4. PHASE 4: the three v2 sweeps --------------------------------
# Each sweep is currently NOT YET WRITTEN.  The orchestrator
# graceful-degrades: missing scripts produce a "SKIP" line and the
# orchestrator continues.  This lets the user run the orchestrator at
# any stage of v2 build-out and see exactly what's done vs pending.

_phase_banner "Phase 4a — country sweep (1008 cells, all baselines + M3)"
if [[ -f "${V2_ROOT}/scripts/02_run_country_sweep.py" ]]; then
    PYTHONPATH="${GRIDPILOT_ROOT}/src:${V2_ROOT}/src" \
        "${PYTHON}" "${V2_ROOT}/scripts/02_run_country_sweep.py" \
            --output-dir "${V2_ROOT}/data/country_sweep" \
            --workers    "${WORKERS:-4}" \
        || { echo "Phase 4a FAIL"; exit 4; }
    N_RAN=$((N_RAN + 1))
else
    _missing_script "Phase 4a — country sweep" \
        "${V2_ROOT}/scripts/02_run_country_sweep.py" \
        "port v1 replay_country_sweep.py through v2 schedulers + accounting"
    N_SKIPPED=$((N_SKIPPED + 1))
fi

_phase_banner "Phase 4b — per-tier sweep (864 cells)"
if [[ -f "${V2_ROOT}/scripts/03_run_tier_sweep.py" ]]; then
    PYTHONPATH="${GRIDPILOT_ROOT}/src:${V2_ROOT}/src" \
        "${PYTHON}" "${V2_ROOT}/scripts/03_run_tier_sweep.py" \
            --output-dir "${V2_ROOT}/data/tier_sweep" \
            --workers    "${WORKERS:-4}" \
        || { echo "Phase 4b FAIL"; exit 4; }
    N_RAN=$((N_RAN + 1))
else
    _missing_script "Phase 4b — per-tier sweep" \
        "${V2_ROOT}/scripts/03_run_tier_sweep.py" \
        "port v1 replay_single_tier_sweep.py through v2 schedulers + accounting"
    N_SKIPPED=$((N_SKIPPED + 1))
fi

_phase_banner "Phase 4c — hyperparameter sweep (576 cells)"
if [[ -f "${V2_ROOT}/scripts/04_run_hyper_sweep.py" ]]; then
    PYTHONPATH="${GRIDPILOT_ROOT}/src:${V2_ROOT}/src" \
        "${PYTHON}" "${V2_ROOT}/scripts/04_run_hyper_sweep.py" \
            --output-dir "${V2_ROOT}/data/hyper_sweep" \
            --workers    "${WORKERS:-4}" \
        || { echo "Phase 4c FAIL"; exit 4; }
    N_RAN=$((N_RAN + 1))
else
    _missing_script "Phase 4c — hyperparameter sweep" \
        "${V2_ROOT}/scripts/04_run_hyper_sweep.py" \
        "port v1 replay_hyperparameter_sweep.py through v2 schedulers + accounting"
    N_SKIPPED=$((N_SKIPPED + 1))
fi

# ---- 5. PHASE 5: extract macros + render figures + rebuild PDF ------
_phase_banner "Phase 5a — extract macros (signed; multi-baseline table)"
if [[ -f "${V2_ROOT}/scripts/05_extract_macros.py" ]]; then
    PYTHONPATH="${GRIDPILOT_ROOT}/src:${V2_ROOT}/src" \
        "${PYTHON}" "${V2_ROOT}/scripts/05_extract_macros.py" \
            --country-csv "${V2_ROOT}/data/country_sweep/country_sweep.csv" \
            --out          "${V2_ROOT}/figs/results.tex" \
        || { echo "Phase 5a FAIL"; exit 5; }
    N_RAN=$((N_RAN + 1))
else
    _missing_script "Phase 5a — extract macros" \
        "${V2_ROOT}/scripts/05_extract_macros.py" \
        "signed macros from v2 country_sweep.csv; drop the hardcoded + prefix"
    N_SKIPPED=$((N_SKIPPED + 1))
fi

_phase_banner "Phase 5b — render figures into ${V2_ROOT}/figs/"
if [[ -f "${V2_ROOT}/scripts/06_render_figures.py" ]]; then
    PYTHONPATH="${GRIDPILOT_ROOT}/src:${V2_ROOT}/src" \
        "${PYTHON}" "${V2_ROOT}/scripts/06_render_figures.py" \
            --country-csv "${V2_ROOT}/data/country_sweep/country_sweep.csv" \
            --tier-summary "${V2_ROOT}/data/tier_sweep/TIER_SUMMARY.csv" \
            --hyper-summary "${V2_ROOT}/data/hyper_sweep/HYPER_SUMMARY.csv" \
            --out-dir "${V2_ROOT}/figs" \
        || { echo "Phase 5b FAIL"; exit 5; }
    N_RAN=$((N_RAN + 1))
else
    _missing_script "Phase 5b — render figures" \
        "${V2_ROOT}/scripts/06_render_figures.py" \
        "port v1 figure pipeline (fig_country_cfe_lift, fig_tier_and_hyper) to v2"
    N_SKIPPED=$((N_SKIPPED + 1))
fi

# ---- 6. Checksum report (only includes whatever ran) ----------------
_phase_banner "Checksum report"
REPORT="${V2_ROOT}/CHECKSUM_REPORT.md"
{
    echo "# experiments_v2 checksum report"
    echo ""
    echo "Generated: ${STAMP}"
    echo "Git SHA  : $(cd "${PROJECT_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "Phases ran: ${N_RAN}; phases skipped (script missing): ${N_SKIPPED}"
    echo ""
    echo "## Artefacts on disk"
    for f in "${V2_ROOT}"/data/*/*.csv \
             "${V2_ROOT}"/data/*/RUN_MANIFEST.json \
             "${V2_ROOT}"/figs/results.tex \
             "${V2_ROOT}"/figs/*.pdf; do
        if [[ -f "${f}" ]]; then
            sha="$( (shasum -a 256 "${f}" 2>/dev/null || sha256sum "${f}") | awk '{print $1}')"
            echo "- \`${f#${PROJECT_ROOT}/}\`  \`${sha:0:16}…\`"
        fi
    done
    echo ""
    echo "## Cell counts"
    for d in country_sweep tier_sweep hyper_sweep; do
        n=$(ls -1 "${V2_ROOT}/data/${d}/cells/"*.json 2>/dev/null | wc -l | tr -d ' ')
        echo "- \`${d}/cells/\`  ${n} files"
    done
} >"${REPORT}"
echo "wrote ${REPORT}"

# ---- 7. Rebuild paper (only if Phase 5 produced fresh macros) -------
if [[ "${N_SKIPPED}" == "0" ]]; then
    _phase_banner "Rebuilding paper PDF"
    bash "${PROJECT_ROOT}/papers/build.sh" pecs || {
        echo "Paper build FAIL"; exit 5;
    }
    N_RAN=$((N_RAN + 1))
else
    echo ""
    echo "Paper rebuild skipped: ${N_SKIPPED} phase(s) had missing scripts."
    echo "Once 02_run_country_sweep.py through 06_render_figures.py are in,"
    echo "re-run this orchestrator and the PDF rebuild will happen automatically."
fi

# ---- 8. Done banner -------------------------------------------------
echo ""
echo "======================================================================"
echo "experiments_v2 orchestrator finished."
echo "  phases ran     : ${N_RAN}"
echo "  phases skipped : ${N_SKIPPED}  (scripts not yet written; see notes above)"
echo "  checksum report: ${REPORT}"
echo "  log file       : ${LOG_FILE}"
if [[ "${N_SKIPPED}" -gt 0 ]]; then
    echo ""
    echo "To make progress on the skipped phases, in priority order:"
    echo "  1. scripts/02_run_country_sweep.py  ← runs the 1008-cell baseline"
    echo "                                        sweep through v2 schedulers"
    echo "  2. scripts/05_extract_macros.py     ← emits signed-macro results.tex"
    echo "  3. scripts/06_render_figures.py     ← v2 figs"
    echo "  4. scripts/03_run_tier_sweep.py     ← per-tier ablation"
    echo "  5. scripts/04_run_hyper_sweep.py    ← hyperparameter ablation"
fi
echo "======================================================================"
