#!/usr/bin/env python3
"""
scripts/m100/build_extended_trace.py
====================================
Build an extended M100 job trace by concatenating the bundled
January 2022 parquet with the Feb 2022 slice from the Marconi100
ExaData archive.

Default source: the in-repo public subset under
``gridpilot/data/m100_public/`` (published from the full ExaMon dump
by ``scripts/m100/publish_m100_subset.sh``).  If that subset is not
present, the script falls back to the original CINECA raw dump root
``$M100_RAW_PATH`` (developer workstation only).  Either way,
override with ``--m100-root``.  Output:
``data/traces/m100_real_jobs_extended.parquet``.

The two source files have *different* schemas:

  * Jan 2022 (bundled): a tidy schema with columns
    ``job_id, submit_time, run_time, num_nodes_alloc, num_gpus_alloc,
    time_limit, user_id, job_state, partition`` --- submit_time
    already in seconds since the epoch, run_time already in seconds.

  * Feb 2022 (raw archive): the full SLURM ``sacct`` dump, with
    column names like ``accrue_time``, ``alloc_node``, ``submit_time``,
    ``start_time``, ``end_time``, ``num_nodes``, ``user_id``, ...

We normalise both into a unified schema:
    submit_time_epoch (float, seconds since UTC epoch),
    run_time          (float, seconds),
    num_nodes_alloc   (int),
    user              (str, optional)

Run:
    PYTHONPATH=src python scripts/m100/build_extended_trace.py
    PYTHONPATH=src python scripts/m100/build_extended_trace.py --list-columns
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FEB_JOB_TABLE = "year_month=22-02/plugin=job_table/metric=job_info_marconi100/a_0.parquet"

# Default M100 source-root resolution order:
#   1. ``gridpilot/data/m100_public/``   — the published subset
#      (single Feb 2022 job_table parquet, ~tens of MiB; ships with
#      the public repo and is the recommended source on remote
#      machines).
#   2. ``$M100_RAW_PATH``                 — the full ExaMon raw dump
#      (developer workstation only; hundreds of GiB).
# Override either with ``--m100-root``.
_PUBLIC_SUBSET = ROOT / "data" / "m100_public"
DEFAULT_M100_ROOT = _PUBLIC_SUBSET


# Candidate column-name lists for each unified field.  Patterns are
# matched in order; the first hit wins.  Lowercase + substring match.
SUBMIT_CANDS = [
    "submit_time", "submit_ts", "submit", "submission_time",
    "time_submit", "time_submission", "eligible_time", "accrue_time",
]
START_CANDS = [
    "start_time", "time_start", "start_ts", "start",
]
END_CANDS = [
    "end_time", "time_end", "end_ts", "end", "completion_time",
]
RUNTIME_CANDS = [
    "run_time", "runtime", "elapsed_time", "elapsed", "elapsed_seconds",
]
NODES_CANDS = [
    "num_nodes_alloc", "num_nodes", "num_nodes_req", "alloc_nodes", "nnodes",
]
USER_CANDS = [
    "user_id", "user_name", "user", "username", "uid",
]


def _find(df: pd.DataFrame, cands: list[str]) -> Optional[str]:
    """Return the first column in ``df`` whose lower-cased name
    contains any of the candidate substrings (in order).  Exact
    matches take precedence over substring matches.
    """
    lc = {c.lower(): c for c in df.columns}
    for cand in cands:
        if cand in lc:
            return lc[cand]
    for cand in cands:
        for low, orig in lc.items():
            if cand in low:
                return orig
    return None


def _to_epoch_seconds(s: pd.Series) -> pd.Series:
    """Coerce a column of timestamps / strings / numbers to UTC epoch seconds."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return (s.astype("int64") // 10**9).astype("float64")
    if pd.api.types.is_numeric_dtype(s):
        m = float(s.dropna().median()) if s.notna().any() else 0.0
        # Heuristic: > 1e16 => ns, > 1e12 => ms, > 1e9 => s
        if m > 1e16:  return (s / 1e9).astype("float64")
        if m > 1e12:  return (s / 1e3).astype("float64")
        return s.astype("float64")
    parsed = pd.to_datetime(s, errors="coerce", utc=True)
    return (parsed.astype("int64") // 10**9).astype("float64")


def _normalise(df: pd.DataFrame, label: str,
                quiet: bool = False) -> pd.DataFrame:
    """Project an arbitrary job-table dataframe onto the unified schema.

    Auto-detects submit / run-time / num-nodes / user columns by
    fuzzy substring match (see ``_find``).  Falls back to computing
    run_time from end - start when no run-time column is present.
    """
    sub_col   = _find(df, SUBMIT_CANDS)
    start_col = _find(df, START_CANDS)
    end_col   = _find(df, END_CANDS)
    run_col   = _find(df, RUNTIME_CANDS)
    nodes_col = _find(df, NODES_CANDS)
    user_col  = _find(df, USER_CANDS)
    if not quiet:
        print(f"[ext-trace]   [{label}] column mapping:")
        print(f"[ext-trace]     submit_time_epoch <- {sub_col!r}")
        print(f"[ext-trace]     run_time          <- {run_col!r}  "
              f"(or {end_col!r} - {start_col!r})")
        print(f"[ext-trace]     num_nodes_alloc   <- {nodes_col!r}")
        print(f"[ext-trace]     user              <- {user_col!r}")

    out = pd.DataFrame(index=df.index)
    # submit_time_epoch
    if sub_col is None:
        raise KeyError(f"[{label}] no submit-time column found; "
                         f"columns: {list(df.columns)[:30]}")
    out["submit_time_epoch"] = _to_epoch_seconds(df[sub_col])

    # run_time
    if run_col is not None:
        run = pd.to_numeric(df[run_col], errors="coerce")
        # If the column looks like a datetime, it's not a duration.
        m = float(run.dropna().median()) if run.notna().any() else 0.0
        if m > 1e7:  # too big to be seconds-of-runtime; treat as wrong column
            run = pd.Series(np.nan, index=df.index)
        out["run_time"] = run
    else:
        out["run_time"] = pd.Series(np.nan, index=df.index)
    # Fallback: end - start
    if out["run_time"].isna().all() and (start_col is not None
                                          and end_col is not None):
        s = _to_epoch_seconds(df[start_col])
        e = _to_epoch_seconds(df[end_col])
        out["run_time"] = (e - s).clip(lower=1.0)

    # num_nodes_alloc
    if nodes_col is not None:
        out["num_nodes_alloc"] = (
            pd.to_numeric(df[nodes_col], errors="coerce")
              .fillna(1).clip(lower=1).astype(int)
        )
    else:
        out["num_nodes_alloc"] = 1

    # user (optional)
    if user_col is not None:
        out["user"] = df[user_col].astype(str)

    keep = (out["submit_time_epoch"].notna()
            & out["run_time"].notna()
            & (out["run_time"] > 0))
    out = out.loc[keep].reset_index(drop=True)
    if not quiet:
        print(f"[ext-trace]     {len(df)} rows -> {len(out)} after cleanup")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--m100-root", type=Path, default=DEFAULT_M100_ROOT)
    p.add_argument("--jan-jobs", type=Path,
                    default=ROOT / "data" / "traces" / "m100_real_jobs.parquet")
    p.add_argument("--out", type=Path,
                    default=ROOT / "data" / "traces" / "m100_real_jobs_extended.parquet")
    p.add_argument("--list-columns", action="store_true",
                    help="Print the column names of both source parquets and exit")
    args = p.parse_args(argv)

    jan_path = args.jan_jobs
    feb_path = args.m100_root / FEB_JOB_TABLE
    if not jan_path.exists():
        print(f"ERROR: Jan trace not found at {jan_path}", file=sys.stderr)
        return 2
    if not feb_path.exists():
        print(f"ERROR: Feb job table not found at {feb_path}", file=sys.stderr)
        return 2

    print(f"[ext-trace] reading Jan: {jan_path}")
    jan_raw = pd.read_parquet(jan_path)
    print(f"[ext-trace]   {len(jan_raw)} rows, {len(jan_raw.columns)} cols")
    print(f"[ext-trace] reading Feb: {feb_path}")
    feb_raw = pd.read_parquet(feb_path)
    print(f"[ext-trace]   {len(feb_raw)} rows, {len(feb_raw.columns)} cols")

    if args.list_columns:
        print("[ext-trace] --- Jan columns ---")
        for c in sorted(jan_raw.columns): print(f"    {c}")
        print("[ext-trace] --- Feb columns ---")
        for c in sorted(feb_raw.columns): print(f"    {c}")
        return 0

    jan = _normalise(jan_raw, "Jan")
    feb = _normalise(feb_raw, "Feb")

    # Project both to common columns
    common = ["submit_time_epoch", "run_time", "num_nodes_alloc"]
    if "user" in jan.columns and "user" in feb.columns:
        common.append("user")
    jan_p = jan[common].copy()
    feb_p = feb[common].copy()

    # Force numeric dtypes BEFORE re-anchor / concat / sort.
    def _coerce(d, label):
        for c in ("submit_time_epoch", "run_time"):
            s = pd.to_numeric(d[c], errors="coerce")
            d.loc[:, c] = s.values.astype("float64")
        before = len(d)
        d.dropna(subset=["submit_time_epoch", "run_time"], inplace=True)
        finite = np.isfinite(d["submit_time_epoch"]) & np.isfinite(d["run_time"])
        d = d.loc[finite].copy()
        print(f"[ext-trace]   [{label}] post-coerce: dtype="
               f"{d['submit_time_epoch'].dtype}, n={len(d)} "
               f"(dropped {before - len(d)} non-finite); "
               f"submit min={d['submit_time_epoch'].min():.3g}, "
               f"max={d['submit_time_epoch'].max():.3g}")
        return d

    jan_p = _coerce(jan_p, "Jan")
    feb_p = _coerce(feb_p, "Feb")

    if len(jan_p) == 0 and len(feb_p) == 0:
        print("ERROR: both halves are empty after coercion; aborting",
                file=sys.stderr)
        return 3

    # Re-anchor Feb submissions to start 1 h after Jan's tail.
    if len(jan_p) and len(feb_p):
        jan_max = float(jan_p["submit_time_epoch"].max())
        feb_min = float(feb_p["submit_time_epoch"].min())
        offset = jan_max - feb_min + 3600.0
        if abs(offset) > 1.0:
            feb_p["submit_time_epoch"] = feb_p["submit_time_epoch"] + offset

    combined = pd.concat([jan_p, feb_p], ignore_index=True)
    # Filter only on strictly-positive epoch; many SLURM rows can
    # have submit==0 (queued but unscheduled).
    combined = combined.loc[combined["submit_time_epoch"] > 0].copy()
    combined = combined.loc[combined["run_time"] > 0].copy()
    print(f"[ext-trace]   combined: n={len(combined)}, "
           f"submit dtype={combined['submit_time_epoch'].dtype}")
    if combined.empty:
        print("ERROR: combined trace is empty after filtering; "
              "check submit_time_epoch column values", file=sys.stderr)
        return 4

    # Use numpy argsort directly to bypass any pandas sort_values
    # surprises with mixed/unusual dtypes.
    order = np.argsort(combined["submit_time_epoch"].to_numpy(),
                        kind="stable")
    combined = combined.iloc[order].reset_index(drop=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(args.out, index=False)
    span_days = (combined["submit_time_epoch"].max()
                  - combined["submit_time_epoch"].min()) / 86400.0
    print(f"[ext-trace] wrote {args.out}")
    print(f"[ext-trace]   {len(combined)} jobs across {span_days:.1f} days")
    print(f"[ext-trace]   pass this to replay_country_sweep.py via --jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
