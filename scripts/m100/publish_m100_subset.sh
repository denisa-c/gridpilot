#!/usr/bin/env bash
# =====================================================================
# scripts/m100/publish_m100_subset.sh
# ---------------------------------------------------------------------
# Copy the ONLY file the f-SLA experiments need from the full local
# Marconi100 ExaMon dump into the in-repo public subset, so the kit
# can be cloned and rerun *without* the 100s-of-GB raw archive.
#
# Source (default): /Users/nisa/code/M100      (override with $1)
# Destination     : gridpilot/data/m100_public/
#
# What gets copied:
#   year_month=22-02/plugin=job_table/metric=job_info_marconi100/a_0.parquet
#
# What does NOT get copied:
#   * year_month=22-02/plugin=ganglia_pub/...   (per-node monitoring)
#   * year_month=22-02/plugin=nagios_pub/...    (alert state)
#   * year_month=22-02-01/plugin=logics_pub/... (PDU/cooling logics)
#   None of these are inputs to the f-SLA replay.  The four-component
#   cooling/PUE model is anchored on the ExaDigiT/RAPS YAML
#   (raps/config/marconi100.yaml), not on raw ExaMon telemetry.
#
# Usage:
#   bash gridpilot/scripts/m100/publish_m100_subset.sh                # default src
#   bash gridpilot/scripts/m100/publish_m100_subset.sh /path/to/M100  # custom src
#
# Provenance:
#   * Source dataset : Marconi100 ExaData telemetry (CINECA / Univ. of Bologna)
#                      https://gitlab.com/ecs-lab/exadata
#   * Canonical refs : Borghesi et al., "M100 ExaData", Sci. Data 10:288 (2023)
#                      https://doi.org/10.1038/s41597-023-02174-3
#                      Zenodo mirror: https://doi.org/10.5281/zenodo.7588815
#   * Licence        : CC-BY 4.0 (per Sci. Data publication terms)
#
# After this script writes the file, commit + push it from the same
# working tree:
#
#   cd EuroPar2026-GridPilot-Denisa
#   git add gridpilot/data/m100_public/
#   git commit -m "data(m100): publish Feb-2022 job_table subset"
#   git push origin main
# =====================================================================
set -euo pipefail

# ---- 1. Resolve paths -----------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRIDPILOT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SRC_ROOT="${1:-/Users/nisa/code/M100}"
DST_ROOT="${GRIDPILOT_ROOT}/data/m100_public"

SUBPATH="year_month=22-02/plugin=job_table/metric=job_info_marconi100/a_0.parquet"
SRC_FILE="${SRC_ROOT}/${SUBPATH}"
DST_FILE="${DST_ROOT}/${SUBPATH}"

# ---- 2. Sanity-check source -----------------------------------------
if [[ ! -f "${SRC_FILE}" ]]; then
    echo "[publish-m100] ERROR: source parquet not found:"
    echo "                ${SRC_FILE}"
    echo "  Set the correct M100 archive root as the first argument:"
    echo "    bash $0 /path/to/M100"
    exit 2
fi
SRC_BYTES="$(wc -c <"${SRC_FILE}" | tr -d ' ')"
SRC_MB=$(( SRC_BYTES / 1024 / 1024 ))
echo "[publish-m100] source     : ${SRC_FILE}"
echo "[publish-m100] source size: ${SRC_MB} MiB (${SRC_BYTES} bytes)"

# GitHub hard-rejects single files >100 MiB and warns at 50 MiB.
if [[ "${SRC_BYTES}" -gt 104857600 ]]; then
    echo "[publish-m100] ERROR: file is >100 MiB; GitHub will reject"
    echo "                a non-LFS push.  Either:"
    echo "                  (a) initialise git-lfs and track *.parquet, or"
    echo "                  (b) publish to Zenodo and reference the DOI."
    exit 3
elif [[ "${SRC_BYTES}" -gt 52428800 ]]; then
    echo "[publish-m100] WARN: file is >50 MiB; GitHub will warn on push"
    echo "                but accept it.  Consider git-lfs for cleanliness."
fi

# ---- 3. Copy + write manifest ---------------------------------------
mkdir -p "$(dirname "${DST_FILE}")"
cp -p "${SRC_FILE}" "${DST_FILE}"
echo "[publish-m100] wrote      : ${DST_FILE}"

SHA256="$( (shasum -a 256 "${DST_FILE}" 2>/dev/null \
        || sha256sum "${DST_FILE}") | awk '{print $1}' )"

MANIFEST="${DST_ROOT}/MANIFEST.json"
GIT_SHA="$(cd "${GRIDPILOT_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat >"${MANIFEST}" <<EOF
{
  "kind": "m100_public_subset_manifest",
  "version": 1,
  "published_utc": "${STAMP}",
  "publisher_git_sha": "${GIT_SHA}",
  "source_dataset": "Marconi100 ExaData (CINECA / Univ. of Bologna)",
  "source_url": "https://gitlab.com/ecs-lab/exadata",
  "source_papers": [
    "Borghesi et al., M100 ExaData, Sci. Data 10:288 (2023)",
    "https://doi.org/10.1038/s41597-023-02174-3"
  ],
  "source_zenodo_doi": "10.5281/zenodo.7588815",
  "licence": "CC-BY 4.0",
  "files": [
    {
      "path": "${SUBPATH}",
      "bytes": ${SRC_BYTES},
      "sha256": "${SHA256}",
      "schema": "SLURM sacct dump (Feb 2022)",
      "consumed_by": "gridpilot/scripts/m100/build_extended_trace.py"
    }
  ]
}
EOF
echo "[publish-m100] manifest   : ${MANIFEST}"

# ---- 4. README for the subset ---------------------------------------
README="${DST_ROOT}/README.md"
cat >"${README}" <<'EOF'
# Marconi100 — public subset (Feb 2022 SLURM `sacct`)

This directory ships the **single** Marconi100 file consumed by the
f-SLA experiments in this repository:

```
year_month=22-02/plugin=job_table/metric=job_info_marconi100/a_0.parquet
```

— a one-month SLURM `sacct` dump (Feb 2022) used by
`gridpilot/scripts/m100/build_extended_trace.py` to extend the
bundled Jan 2022 trace (`gridpilot/data/traces/m100_real_jobs.parquet`)
into the full Jan+Feb 2022 replay window.

## Provenance

| Field   | Value |
|---------|-------|
| Dataset | Marconi100 ExaData telemetry (CINECA / Univ. of Bologna) |
| Paper   | Borghesi *et al.*, *Sci. Data* 10:288 (2023). DOI `10.1038/s41597-023-02174-3` |
| Mirror  | https://gitlab.com/ecs-lab/exadata |
| Zenodo  | https://doi.org/10.5281/zenodo.7588815 |
| Licence | CC-BY 4.0 |

The full ExaMon archive is several hundred GB (per-node Ganglia /
Nagios / power-and-cooling telemetry at 20 s resolution); we
re-distribute only the SLURM `sacct` slice, which is the one input
the f-SLA replay actually consumes.  Everything else needed to
reproduce the cooling/PUE model is anchored on the in-repo RAPS YAML
(`raps/config/marconi100.yaml`), not on raw ExaMon metrics.

## How to regenerate

If you have access to the full ExaMon dump (`M100_ROOT`), this
directory is regenerated by:

```bash
bash gridpilot/scripts/m100/publish_m100_subset.sh "$M100_ROOT"
```

Integrity of the parquet is checked against the SHA-256 recorded in
`MANIFEST.json`.

## Citation

If you use this subset in a publication, please cite the original
ExaData paper:

```bibtex
@article{Borghesi2023M100ExaData,
  author  = {Borghesi, Andrea and others},
  title   = {{M100 ExaData: a data collection campaign on the
              CINECA's Marconi100 Tier-0 supercomputer}},
  journal = {Scientific Data},
  year    = {2023},
  volume  = {10},
  pages   = {288},
  doi     = {10.1038/s41597-023-02174-3}
}
```
EOF
echo "[publish-m100] readme     : ${README}"

# ---- 5. Done banner -------------------------------------------------
echo ""
echo "[publish-m100] OK.  Subset ready under ${DST_ROOT}/"
echo "[publish-m100] Commit it with:"
echo "  git add gridpilot/data/m100_public/"
echo "  git commit -m 'data(m100): publish Feb-2022 job_table subset'"
echo "  git push origin main"
