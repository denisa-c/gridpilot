#!/usr/bin/env bash
# =====================================================================
# scripts/run_all_experiments.sh
# ---------------------------------------------------------------------
# Single end-to-end command that runs every experiment behind the two
# papers (GridPilot controller; f-SLA paper: f-SLA contract), extracts
# the headline-number macros from the on-disk outputs, regenerates all
# figures from real data, and rebuilds both PDFs.
#
# What this script does NOT do:
#   * Re-acquire V100 hardware measurements --- those require a 3x V100
#     SXM2 testbed and are covered by docs/V100_MEASUREMENT_PROTOCOL.md.
#     The script assumes data/v100_raw/ is already populated by an
#     earlier campaign run (E1, E2, E3, E4, E7).
#
# Wall-clock budget on a 16-core / 64 GB workstation:
#
#     +-------+--------------------------------------+--------+----------+
#     | Step  | Stage                                | Mode   |  ~Time   |
#     +-------+--------------------------------------+--------+----------+
#     |  0a   | Build extended Jan+Feb 2022 trace    | full   |    1 min |
#     |  0b   | Fetch real ENTSO-E hourly CI         | full*  |    3 min |
#     |   1   | M100 policy-matrix replay            | full   |   26 min |
#     |   2   | Multi-country sweep (6 grids x 3 MW) | full   |   42 min |
#     |  3a   | Regenerate every paper figure (PDF)  | both   |   30 sec |
#     |   4   | Extract macros + rebuild both PDFs   | both   |   30 sec |
#     +-------+--------------------------------------+--------+----------+
#                                          Total full mode: ~75 min
#                                          Total stub mode: ~ 2 min
#     (* step 0b only runs when ENTSOE_API_KEY is exported.)
#
# Progress indication:
#   Every step prints a banner of the form
#       [N/M] <step name>        (elapsed so far: <mm:ss>)
#   Long-running steps (1 and 2) emit a heartbeat line every 30 s of
#   the form  ... still running step <name>: <mm:ss> elapsed.
#   The whole transcript is tee'd to logs/run_all_<UTC-stamp>.log so
#   the user can `tail -f logs/run_all_*.log` from another terminal.
#
# Usage:
#   bash gridpilot/scripts/run_all_experiments.sh           # full run
#   bash gridpilot/scripts/run_all_experiments.sh stub      # fast (stubs)
#   FORCE=1 bash ... stub                                   # force in stub mode
#   FRESH=1 bash ... full                                   # rerun even completed steps
#   ENTSOE_API_KEY=<tok> bash ... full                      # real CI fetch
#   M100_ROOT=/path/to/M100 bash ... full                   # override extended-trace source
#       (default: gridpilot/data/m100_public/, the in-repo subset.
#        Falls back to the developer-workstation raw dump
#        at $M100_ROOT if the in-repo subset is missing.)
#
# Resumability (full mode):
#   * A step is treated as COMPLETE if its canonical artefact AND the
#     companion RUN_MANIFEST.json are both present on disk.  Complete
#     steps are skipped on rerun, so a killed-and-restarted full run
#     does not redo work that already finished cleanly.
#   * The multi-country sweep additionally checkpoints every cell to
#     data/m100/country_sweep/cells/<cell-id>.json.  If the sweep is
#     killed mid-way (no CSV yet, but partial cells/), the rerun
#     resumes from the cells already on disk and only computes the
#     remaining ones --- this is independent of the step-level skip.
#   * Set FRESH=1 to clobber both the completed-step skip and the
#     cells/ directory (delete cells/ manually if you really want a
#     fresh per-cell rerun).
#
# 'full' mode auto-passes --force to the replay drivers so stale stub
# CSVs from a previous fast rebuild are silently overwritten by real-
# experiment outputs.  A 3-second WARN fires before each replay if a
# RUN_MANIFEST.json is already present (i.e. real prior data) so a
# valuable campaign run cannot be silently clobbered.
# =====================================================================
set -euo pipefail

# ---- Resolve paths ---------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${ROOT}/.." && pwd)"
cd "${ROOT}"

# Resolve the Marconi100 PUE anchor YAML. Prefer the submodule path,
# but fall back to a tracked local copy for remote clones where the
# submodule has not been initialized.
RAPS_PUE_YAML="raps/config/marconi100.yaml"
if [[ ! -f "${RAPS_PUE_YAML}" ]]; then
    if [[ -f "configs/raps_systems/marconi100.yaml" ]]; then
        RAPS_PUE_YAML="configs/raps_systems/marconi100.yaml"
        echo "[run-all] WARN: raps/config/marconi100.yaml missing;"
        echo "          using fallback ${RAPS_PUE_YAML}"
    else
        echo "[run-all] ERROR: missing Marconi100 PUE anchor YAML."
        echo "         Expected one of:"
        echo "           - raps/config/marconi100.yaml"
        echo "           - configs/raps_systems/marconi100.yaml"
        echo "         If you cloned without submodules, run:"
        echo "           git submodule update --init --recursive"
        exit 1
    fi
fi

# ---- Pick the Python interpreter -------------------------------------
if [[ -x "${ROOT}/.venv/bin/python3" ]]; then
    PYTHON="${PYTHON:-${ROOT}/.venv/bin/python3}"
else
    PYTHON="${PYTHON:-python3}"
fi
MODE="${1:-full}"   # 'full' (default) or 'stub' (fast paper rebuild)

# In 'full' mode the user's clear intent is to (over)write the
# headline CSVs with real-experiment outputs.  We therefore default
# --force on; the script still warns when overwriting a CSV that
# carries a RUN_MANIFEST.json (real prior data) so nothing valuable
# is silently clobbered.
FORCE_FLAG=""
if [[ "${MODE}" == "full" ]]; then FORCE_FLAG="--force"; fi
if [[ "${FORCE:-0}" == "1" ]];  then FORCE_FLAG="--force"; fi

# ---- Logging ---------------------------------------------------------
mkdir -p "${ROOT}/logs"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="${ROOT}/logs/run_all_${STAMP}.log"
# tee everything we write below to the log; subprocesses inherit fds.
exec > >(tee -a "${LOG_FILE}") 2>&1

# ---- Progress-bar / step machinery -----------------------------------
RUN_START="${SECONDS}"
TOTAL_STEPS=7         # 0a, 0b, 1, 2, 3a, 3b, 4
CUR_STEP=0
CUR_STEP_LABEL=""
CUR_STEP_START=0
HEARTBEAT_PID=""

_fmt_mmss() {
    local total="$1"
    printf '%02d:%02d' "$((total / 60))" "$((total % 60))"
}

_overall_elapsed() {
    _fmt_mmss "$((SECONDS - RUN_START))"
}

_heartbeat_start() {
    # Print "still running" every HEARTBEAT_SEC seconds in the background.
    local hb_label="$1"
    local hb_start="${SECONDS}"
    local hb_period="${HEARTBEAT_SEC:-30}"
    (
        while true; do
            sleep "${hb_period}"
            local hb_elap=$(( SECONDS - hb_start ))
            printf '   ... still running step %s: %s elapsed\n' \
                "${hb_label}" "$(_fmt_mmss "${hb_elap}")"
        done
    ) &
    HEARTBEAT_PID="$!"
    # Make sure the heartbeat is reaped even on early exit.
    trap '[[ -n "${HEARTBEAT_PID}" ]] && kill "${HEARTBEAT_PID}" 2>/dev/null || true' EXIT
}

_heartbeat_stop() {
    if [[ -n "${HEARTBEAT_PID}" ]]; then
        kill "${HEARTBEAT_PID}" 2>/dev/null || true
        wait "${HEARTBEAT_PID}" 2>/dev/null || true
        HEARTBEAT_PID=""
    fi
}

_step_begin() {
    # Usage: _step_begin <label> [heartbeat=1]
    CUR_STEP=$((CUR_STEP + 1))
    CUR_STEP_LABEL="$1"
    CUR_STEP_START="${SECONDS}"
    local heart="${2:-0}"
    printf '\n'
    printf '======================================================================\n'
    printf '[%d/%d] %s    (total elapsed %s)\n' \
        "${CUR_STEP}" "${TOTAL_STEPS}" "${CUR_STEP_LABEL}" "$(_overall_elapsed)"
    printf '======================================================================\n'
    if [[ "${heart}" == "1" ]]; then
        _heartbeat_start "[${CUR_STEP}/${TOTAL_STEPS}] ${CUR_STEP_LABEL}"
    fi
}

_step_end() {
    _heartbeat_stop
    local dur=$((SECONDS - CUR_STEP_START))
    printf '\n  done step [%d/%d] %s in %s (total elapsed %s)\n' \
        "${CUR_STEP}" "${TOTAL_STEPS}" "${CUR_STEP_LABEL}" \
        "$(_fmt_mmss "${dur}")" "$(_overall_elapsed)"
}

_step_skip() {
    # _step_skip <label> <reason>
    CUR_STEP=$((CUR_STEP + 1))
    printf '\n--- [%d/%d] SKIP  %s    (reason: %s)\n' \
        "${CUR_STEP}" "${TOTAL_STEPS}" "$1" "$2"
}

_warn_real_overwrite() {
    local manifest="$1"; local label="$2"
    if [[ -f "${manifest}" ]]; then
        echo "WARN: ${label} carries a RUN_MANIFEST.json (real-experiment output)."
        echo "      It will be overwritten.  Press Ctrl+C in the next 3 s to abort,"
        echo "      or set FORCE=0 MODE=stub to switch to stub mode."
        sleep 3
    fi
}

# _step_complete: returns 0 if a step's canonical artefact AND its
# companion RUN_MANIFEST.json are both present, signalling that the
# step finished cleanly on a previous run and can be skipped on
# resume.  FRESH=1 forces a rerun even when complete.
_step_complete() {
    local csv="$1"; local manifest="$2"
    [[ "${FRESH:-0}" == "1" ]] && return 1
    [[ -f "${csv}" && -f "${manifest}" ]]
}

# ---- Pre-flight banner -----------------------------------------------
printf '======================================================================\n'
printf 'GridPilot run-all\n'
printf '  mode      : %s\n'   "${MODE}"
printf '  python    : %s\n'   "${PYTHON}"
printf '  force     : %s\n'   "${FORCE_FLAG:-no}"
printf '  fresh     : %s   (set FRESH=1 to rerun even completed steps)\n' "${FRESH:-0}"
printf '  log       : %s\n'   "${LOG_FILE}"
printf '  workers   : %s\n'   "${WORKERS:-4}"
printf '  heartbeat : %s s\n'   "${HEARTBEAT_SEC:-30}"
printf '  steps     : %d total\n'  "${TOTAL_STEPS}"
printf '======================================================================\n'

mkdir -p data/m100/policy_matrix data/m100/country_sweep
mkdir -p "${PROJECT_ROOT}/papers/pecs2026/figs"
mkdir -p "${PROJECT_ROOT}/papers/whpc2026/figs"

# =====================================================================
# Step 0a: Extend the M100 trace with Feb 2022
#   Source resolution order:
#     1. $M100_ROOT (if exported by the caller)
#     2. gridpilot/data/m100_public/   (the in-repo published subset)
#     3. $M100_ROOT                    (developer-workstation raw dump, if set)
# =====================================================================
EXT_TRACE="data/traces/m100_real_jobs_extended.parquet"
JAN_TRACE="data/traces/m100_real_jobs.parquet"
FEB_KEY="year_month=22-02/plugin=job_table/metric=job_info_marconi100/a_0.parquet"

# Resolve M100_ROOT in priority order.
if [[ -n "${M100_ROOT:-}" && -f "${M100_ROOT}/${FEB_KEY}" ]]; then
    M100_SRC="${M100_ROOT}"
elif [[ -f "data/m100_public/${FEB_KEY}" ]]; then
    M100_SRC="data/m100_public"
else
    M100_SRC=""
fi

if [[ "${MODE}" == "full" ]] \
   && [[ ! -f "${EXT_TRACE}" ]] \
   && [[ -n "${M100_SRC}" ]]; then
    _step_begin "Build extended Jan+Feb 2022 M100 trace"
    echo "[run-all] M100 source: ${M100_SRC}"
    PYTHONPATH=src "${PYTHON}" scripts/m100/build_extended_trace.py \
        --m100-root "${M100_SRC}" \
        --jan-jobs "${JAN_TRACE}" \
        --out      "${EXT_TRACE}" || \
        echo "[run-all] WARN: could not build extended trace; using Jan-only"
    _step_end
else
    _step_skip "Build extended Jan+Feb 2022 M100 trace" \
        "MODE=${MODE} / no M100 source found / extended trace already present"
fi

# Prefer the extended trace if present.
JOB_TRACE="${JAN_TRACE}"
if [[ -f "${EXT_TRACE}" ]]; then
    JOB_TRACE="${EXT_TRACE}"
    echo "[run-all] Using extended trace: ${JOB_TRACE}"
fi

# =====================================================================
# Step 0b: Fetch real ENTSO-E hourly CI (optional, needs API token)
# =====================================================================
if [[ "${MODE}" == "full" ]] \
   && [[ -n "${ENTSOE_API_KEY:-}" ]] \
   && [[ ! -d "data/ci/entsoe" ]]; then
    _step_begin "Fetch real hourly CI series from ENTSO-E A75"
    PYTHONPATH=src "${PYTHON}" scripts/m100/fetch_real_ci_series.py \
        --start 2024-01-01 --end 2025-01-01 \
        --grids SE,CH,FR,IT,DE,PL \
        --out-dir data/ci/entsoe/ || \
        echo "[run-all] WARN: ENTSO-E fetch failed; falling back to synth CI"
    _step_end
else
    _step_skip "Fetch real hourly CI series from ENTSO-E A75" \
        "MODE=${MODE}, no ENTSOE_API_KEY, or data/ci/entsoe/ already present"
fi

# =====================================================================
# Step 1: M100 policy-matrix replay
#   5 policies x 5 mechanisms x 8 seeds = 200 cells over the M100 trace.
#   Outputs: data/m100/policy_matrix/policy_matrix.csv
#            data/m100/policy_matrix/HYPOTHESIS_OUTCOMES.json
#            data/m100/policy_matrix/RUN_MANIFEST.json
# =====================================================================
if [[ "${MODE}" == "stub" ]]; then
    _step_begin "Seed stub policy_matrix.csv"
    PYTHONPATH=src "${PYTHON}" scripts/m100/seed_policy_matrix_stub.py \
        --output-dir data/m100/policy_matrix
    _step_end
elif _step_complete data/m100/policy_matrix/policy_matrix.csv \
                     data/m100/policy_matrix/RUN_MANIFEST.json; then
    _step_skip "Real M100 policy-matrix replay" \
        "policy_matrix.csv + RUN_MANIFEST.json already on disk; set FRESH=1 to rerun"
else
    _step_begin "Real M100 policy-matrix replay (~26 min on 16 cores)" 1
    _warn_real_overwrite data/m100/policy_matrix/RUN_MANIFEST.json \
        "data/m100/policy_matrix/"
    PYTHONPATH=src "${PYTHON}" scripts/m100/replay_policy_matrix.py \
        --jobs       "${JOB_TRACE}" \
        --ci         configs/grids/DE.yaml \
        --pue        "${RAPS_PUE_YAML}" \
        --policies   FCFS,EASY,SAF,RLBackfilling,GridPilot-PUE \
        --mechanisms none,M0,M1,M2,M3 \
        --seeds      8 \
        --workers    "${WORKERS:-4}" \
        --output-dir data/m100/policy_matrix/ ${FORCE_FLAG}
    _step_end
fi

# =====================================================================
# Step 2: Multi-country sweep
#   6 grids x 3 MW x (5 fsla + 2 pue) mechanisms x 8 seeds = 1008 cells.
#   Outputs: data/m100/country_sweep/country_sweep.csv
#            data/m100/country_sweep/COUNTRY_SUMMARY.csv
#            data/m100/country_sweep/RUN_MANIFEST.json
# =====================================================================
if [[ "${MODE}" == "stub" ]]; then
    _step_begin "Seed stub country_sweep.csv"
    PYTHONPATH=src "${PYTHON}" scripts/multicountry/seed_country_sweep_stub.py \
        --output-dir data/m100/country_sweep
    _step_end
elif _step_complete data/m100/country_sweep/country_sweep.csv \
                     data/m100/country_sweep/RUN_MANIFEST.json; then
    _step_skip "Real multi-country sweep" \
        "country_sweep.csv + RUN_MANIFEST.json already on disk; set FRESH=1 to rerun"
else
    # If a partial run left a cells/ checkpoint directory, the Python
    # driver will resume from it and only compute the remaining cells.
    CELLS_DIR="data/m100/country_sweep/cells"
    if [[ -d "${CELLS_DIR}" ]]; then
        DONE_CELLS=$(ls -1 "${CELLS_DIR}"/*.json 2>/dev/null | wc -l | tr -d ' ')
        if [[ "${DONE_CELLS}" -gt 0 ]]; then
            echo "[run-all] Found ${DONE_CELLS} cell checkpoints under ${CELLS_DIR};"
            echo "         the sweep will resume from them.  Delete the directory"
            echo "         (rm -rf ${CELLS_DIR}) for a fresh per-cell rerun."
        fi
    fi
    _step_begin "Real multi-country sweep (~30-45 min on 16 cores)" 1
    _warn_real_overwrite data/m100/country_sweep/RUN_MANIFEST.json \
        "data/m100/country_sweep/"
    PYTHONPATH=src "${PYTHON}" scripts/multicountry/replay_country_sweep.py \
        --jobs             "${JOB_TRACE}" \
        --grids            configs/grids/SE.yaml,configs/grids/FR.yaml,configs/grids/CH.yaml,configs/grids/IT.yaml,configs/grids/DE.yaml,configs/grids/PL.yaml \
        --pue-yaml         "${RAPS_PUE_YAML}" \
        --mw               1,10,50 \
        --fsla-mechanisms  none,M0,M1,M2,M3 \
        --pue-mechanisms   none,GridPilot-PUE \
        --seeds            8 \
        --workers          "${WORKERS:-4}" \
        --output-dir       data/m100/country_sweep/ ${FORCE_FLAG}
    _step_end
fi

# =====================================================================
# Step 3a: Regenerate every paper figure from the (now real) CSVs
# =====================================================================
_step_begin "Regenerate every paper figure from real CSVs"
for f in fig_cfe_by_tier fig_swf_comparison fig_fairness_pareto fig_latency_per_tier; do
    PYTHONPATH=src "${PYTHON}" "scripts/figures/${f}.py" \
        --matrix data/m100/policy_matrix/policy_matrix.csv \
        --out "figs/${f}.pdf"
done
for f in fig_country_cfe_lift fig_country_pue_aware; do
    PYTHONPATH=src "${PYTHON}" "scripts/figures/${f}.py" \
        --matrix data/m100/country_sweep/country_sweep.csv \
        --out "figs/${f}.pdf"
done

# Optional composed figure: per-tier contribution + hyperparameter
# sensitivity.  Renders even if only one (or zero) of the two summary
# CSVs is on disk --- missing panels display "(awaiting <sweep> run)".
PYTHONPATH=src "${PYTHON}" "scripts/figures/fig_tier_and_hyper.py" \
    --tier-summary  data/m100/tier_sweep/TIER_SUMMARY.csv \
    --hyper-summary data/m100/hyper_sweep/HYPER_SUMMARY.csv \
    --out           figs/fig_tier_and_hyper.pdf \
    || echo "[run-all] WARN: fig_tier_and_hyper.py failed; continuing"
_step_end


# =====================================================================
# Step 4: Extract paper macros and rebuild the two PDFs
# =====================================================================
_step_begin "Extract paper macros and rebuild the two PDFs"
PYTHONPATH=src "${PYTHON}" scripts/figures/extract_paper_macros.py
bash "${PROJECT_ROOT}/papers/build.sh"
_step_end

# ---- Done banner -----------------------------------------------------
TOTAL=$(_fmt_mmss "$((SECONDS - RUN_START))")
printf '\n'
printf '======================================================================\n'
printf 'DONE in %s.  Outputs:\n' "${TOTAL}"
printf '   %s   (GridPilot controller paper)\n' "${PROJECT_ROOT}/papers/whpc2026/main.pdf"
printf '   %s   (f-SLA contract paper)\n'      "${PROJECT_ROOT}/papers/pecs2026/main.pdf"
printf '   Real-data CSVs:\n'
printf '     data/m100/policy_matrix/policy_matrix.csv\n'
printf '     data/m100/country_sweep/country_sweep.csv  (+ COUNTRY_SUMMARY.csv)\n'
printf '   Log:\n'
printf '     %s\n' "${LOG_FILE}"
printf '======================================================================\n'

if [[ "${MODE}" == "stub" ]]; then
    echo
    echo "NOTE: ran in stub mode.  Real M100 numbers are produced by"
    echo "      bash gridpilot/scripts/run_all_experiments.sh     (default 'full' mode)"
fi
