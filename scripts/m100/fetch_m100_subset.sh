#!/usr/bin/env bash
# =====================================================================
# scripts/m100/fetch_m100_subset.sh
# ---------------------------------------------------------------------
# Companion to publish_m100_subset.sh.  Run on a *remote* machine that
# has cloned the GitHub repo without the ExaMon dump, to verify the
# in-repo public subset arrived intact (or, if missing, to surface the
# right error message).
#
# What it does:
#   1. Checks that gridpilot/data/m100_public/ exists and is non-empty.
#   2. Reads MANIFEST.json and re-verifies each file's SHA-256 against
#      the recorded hash, so a corrupted clone is flagged immediately.
#   3. Prints the absolute path the caller should export as M100_ROOT
#      (or leave unset --- run_all_experiments.sh already resolves the
#      in-repo subset automatically).
#
# Usage:
#   bash gridpilot/scripts/m100/fetch_m100_subset.sh
#
# Exit codes:
#   0   subset present and verified
#   1   subset missing entirely (clone fresh from GitHub, or run
#       publish_m100_subset.sh on a workstation that has the full
#       ExaMon dump)
#   2   subset present but one or more files failed SHA-256 check
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRIDPILOT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DST_ROOT="${GRIDPILOT_ROOT}/data/m100_public"
MANIFEST="${DST_ROOT}/MANIFEST.json"

# ---- 1. Existence check ---------------------------------------------
if [[ ! -d "${DST_ROOT}" ]] || [[ ! -f "${MANIFEST}" ]]; then
    echo "[fetch-m100] ERROR: in-repo subset is missing."
    echo "             Expected:"
    echo "               ${DST_ROOT}/MANIFEST.json"
    echo ""
    echo "  Did you clone with shallow history or a sparse checkout?"
    echo "  Either re-clone with the data/ directory included, or, if"
    echo "  you have access to the full ExaMon dump, regenerate it:"
    echo ""
    echo "     bash gridpilot/scripts/m100/publish_m100_subset.sh \\"
    echo "          /path/to/your/M100/dump"
    echo ""
    echo "  Without the subset the kit falls back to the bundled"
    echo "  January-only trace (gridpilot/data/traces/m100_real_jobs.parquet),"
    echo "  which is enough to reproduce the paper's qualitative findings."
    exit 1
fi

# ---- 2. SHA-256 re-verification -------------------------------------
# Parse the manifest with python so we don't depend on jq.
PYTHON="${PYTHON:-python3}"
"${PYTHON}" - <<PY
import hashlib, json, sys
from pathlib import Path

root = Path("${DST_ROOT}")
manifest = json.loads((root / "MANIFEST.json").read_text())
status = 0
for entry in manifest["files"]:
    path = root / entry["path"]
    if not path.is_file():
        print(f"[fetch-m100] MISS  {entry['path']}: file not present")
        status = 2
        continue
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    ok = digest == entry["sha256"]
    print(f"[fetch-m100] {'OK   ' if ok else 'BAD  '}{entry['path']}: "
          f"{digest[:16]}…  ({entry['bytes']:>10} bytes)")
    if not ok:
        status = 2
sys.exit(status)
PY

# ---- 3. Done --------------------------------------------------------
echo ""
echo "[fetch-m100] OK.  Subset verified."
echo "[fetch-m100] M100 source resolved automatically by"
echo "             gridpilot/scripts/run_all_experiments.sh."
echo "             No environment-variable export is needed."
