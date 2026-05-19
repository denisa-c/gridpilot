# Dependencies

This file catalogues every Python package the GridPilot reproducibility
kit imports, why it is needed, and the version constraints in
[`requirements.txt`](../requirements.txt).

For the from-clone walkthrough see [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md).

---

## 1. Python version

| Python | Status | Notes |
|---|---|---|
| 3.10 | ✅ supported | tested in CI |
| 3.11 | ✅ supported | tested in CI |
| 3.12 | ✅ supported (recommended) | wheels available for all deps |
| 3.13 | ✅ supported | requires numpy ≥ 2.1; relaxed in requirements.txt |
| 3.14 | ✅ supported | requires numpy ≥ 2.1, pyarrow ≥ 18, scipy ≥ 1.13 |
| ≤ 3.9 | ❌ unsupported | `from __future__ import annotations` everywhere; some scripts use 3.10+ match/case-style typing |

On Python 3.13 and 3.14 the upper bound on numpy in `requirements.txt`
is `<3.0` rather than `<2.0`, which lets pip resolve to numpy 2.x
(numpy 1.x has no wheels for those Python versions).  The code does
not use any numpy-1.x-only APIs.

## 2. Required runtime dependencies

These are imported by at least one script in
`scripts/run_all_experiments.sh`'s default path:

| Package | Constraint | Used by | Why |
|---|---|---|---|
| `numpy` | `>=1.24,<3.0` | every module under `src/` and `scripts/` | core array library |
| `pandas` | `>=2.0,<3.0` | every replay driver, every figure script | trace / CSV I/O |
| `matplotlib` | `>=3.7,<4.0` | every figure script | PDF rendering |
| `scipy` | `>=1.11,<2.0` | `src/evaluation/metrics.py` (`curve_fit`) | bootstrap CIs and curve fits |
| `pyarrow` | `>=14.0` | `pandas.read_parquet` / `to_parquet` in `scripts/m100/{build_extended_trace,fetch_real_ci_series,inject_fsla_prior}.py` and indirectly `replay_policy_matrix.py`, `replay_country_sweep.py` | parquet I/O (the bundled M100 trace is `.parquet`) |
| `pyyaml` | `>=6.0` | `configs/grids/*.yaml`, `configs/network/egress_emissions.yaml`, `configs/workflows/*.yaml`, `raps/config/*.yaml` | YAML config loading |
| `pytest` | `>=7.0` | `tests/` | unit-test runner |

**Total install size on Linux x86_64 (clean venv): ~280 MiB.**

## 3. Optional dependencies

These are imported only by specific code paths and are degraded-
gracefully when missing:

| Package | Constraint | Used by | Behaviour if missing |
|---|---|---|---|
| `python-pptx` | `>=0.6.21` | `scripts/figures/make_architecture_pptx.py` | the run-all script skips the `.pptx` rebuild via `python -c "import pptx"` gate; the placeholder architecture PDF still renders |
| `networkx` | `>=3.1` | `WorkflowDAG.to_networkx()` (C2 follow-on); the bundled RAPS submodule | the WorkflowDAG abstraction still works; only the `to_networkx()` exporter and the RAPS internals are unavailable |
| `entsoe-py` | not used | (the ENTSO-E fetcher uses stdlib `urllib` + `xml.etree`) | the bundled fetcher does not need it |

## 4. Standard-library packages used heavily

These are part of the Python distribution; listed here for transparency:

- `argparse`, `json`, `csv`, `sys`, `os`, `pathlib`, `time`,
  `subprocess`, `platform`, `socket` (CLI plumbing and `RUN_MANIFEST.json`)
- `concurrent.futures.{ProcessPoolExecutor, as_completed}` (parallel
  replays in step 1 and step 2 of `run_all_experiments.sh`)
- `dataclasses` (`SpatialClause`, `JobSpec`, `ConditionalEdge`, …)
- `typing`, `__future__.annotations`
- `hashlib`, `warnings`, `collections.Counter`, `itertools`,
  `functools`, `re`

No network or third-party HTTP library is required for the basic
pipeline; the ENTSO-E live fetcher uses stdlib `urllib.request` and
parses XML with stdlib `xml.etree.ElementTree`.

## 5. Dependency files in the tree

| Path | Purpose |
|---|---|
| `gridpilot/requirements.txt` | the canonical install file for the public release |
| `gridpilot/raps/api_client/requirements.txt` | optional; only needed if you run the RAPS API client code; the bundled GridPilot pipeline does not import it |
| `gridpilot/raps/pyproject.toml` | the upstream ExaDigiT/RAPS project's own pyproject; only needed if you develop/run the RAPS package itself |

The `.gitignore` deliberately tracks all three so a clone produces an
exactly-reproducible environment.

## 6. Python version compatibility decisions

**Why `numpy<3.0` rather than `<2.0`?**  numpy 1.x has no wheels for
Python 3.13 or 3.14 (the last 1.x release was 1.26.x which ships
wheels through 3.12 only).  The PECS f-SLA replays and the figure
scripts use no numpy-1.x-only APIs (`np.NaN` → `np.nan`, no
`np.unicode_` etc.), so numpy 2.x is a drop-in replacement.

**Why `pyarrow>=14.0` rather than a specific minor?**  pyarrow 14 is
the floor needed for the parquet engine to work on Python 3.12+;
14, 15, 16, 17, 18, 19, 20 all work; pip picks the latest with
wheels for the user's Python version.

**Why pin numpy/pandas/matplotlib/scipy at `<3.0`/`<3.0`/`<4.0`/`<2.0`?**
These are the safety margins for the API surfaces we actually use.
The next major of each of these libraries will change APIs we depend
on (e.g.\ pandas 3.0 changes `pd.read_csv` defaults, scipy 2.0 will
remove deprecated `scipy.misc` namespace).  Bump the constraints
when those releases stabilise.

## 7. One-shot install

The canonical install on a fresh remote machine:

```bash
# From the workspace root:
git submodule update --init --recursive
python3 -m venv .venv && source .venv/bin/activate
pip3 install --upgrade pip setuptools wheel
pip3 install -r gridpilot/requirements.txt
PYTHONPATH=gridpilot/src pytest -q gridpilot/tests/   # expect 70 passed
```

If you cloned with `--recurse-submodules`, you can skip the
`git submodule update`.

## 8. Conda alternative

A minimal `environment.yml` for users who prefer conda over venv:

```yaml
name: gridpilot
channels: [conda-forge, defaults]
dependencies:
  - python=3.12
  - numpy>=1.24
  - pandas>=2.0
  - matplotlib>=3.7
  - scipy>=1.11
  - pyarrow>=14.0
  - pyyaml>=6.0
  - networkx>=3.1
  - pytest>=7.0
  - pip
  - pip:
      - python-pptx>=0.6.21
```

Save as `environment.yml`, then `conda env create -f environment.yml`.
Not officially supported; raise an issue if you hit a problem.

## 9. Verifying the install

After `pip install`, you can verify the import graph works without
running the full test suite:

```bash
PYTHONPATH=gridpilot/src python3 -c "
import numpy, pandas, matplotlib, scipy, pyarrow, yaml, pytest
from scheduler.fsla import DEFAULT_ALPHA, TIER_NAMES, sample_prior
from scheduler.fsla_mechanisms import build_mechanism
from scheduler.swf import jain_fairness
from scheduler.spatial_routing import SpatialClause
from scheduler.workflow_dag import WorkflowDAG
from scheduler.dag_mechanisms import m_workflow_audit
from scheduler.egress_cost import load_egress_emissions
from cooling.cooling_pue_model import calibrate_to_design_pue
from integration.raps_config_adapter import load_raps_system_config
print('all imports OK; TIER_NAMES =', TIER_NAMES)
"
```

Expected output:

```
all imports OK; TIER_NAMES = ('T0', 'T1', 'T2', 'T3', 'T4', 'T5')
```
