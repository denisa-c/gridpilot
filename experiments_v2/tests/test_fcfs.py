"""
experiments_v2/tests/test_fcfs.py — DEPRECATED PLACEHOLDER
===========================================================
Original hand-written FCFS unit tests are obsolete — RAPS owns
the FCFS implementation now (raps/schedulers/default.py +
raps/policy.py).  The new sanity tests for the v2 adapter live in
``experiments_v2/tests/test_raps_adapter.py``:

  - head-of-queue blocking pathology (MF&F 2001) reproduces
    when policy=FCFS, backfill=NONE
  - EASY backfilling fixes the pathology (Lifka 1995) when
    policy=FCFS, backfill=EASY
  - SAF reorders by (nodes × runtime) when policy=PRIORITY
    with the SAF-priority preprocessor

If you arrive here from an old import path: switch to
``test_raps_adapter`` and delete the import of this file.
"""
raise NotImplementedError(
    "experiments_v2/tests/test_fcfs.py is deprecated.  "
    "See experiments_v2/tests/test_raps_adapter.py for the "
    "current v2 scheduler sanity tests."
)
