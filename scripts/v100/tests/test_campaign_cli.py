"""
test_campaign_cli.py — guard against CLI mismatches between
11_run_parallel_campaign.sh and the experiment scripts.

The earlier failures were:
- E5 missing required --parsed-results
- E6 passing --gpus 0,1,2 (CSV) instead of --gpus 0 1 2 (space-separated)
- E7 same bug as E6

This test parses the wrapper script and asserts the invocation form matches
what each experiment's argparse expects.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
SCRIPT = KIT / "scripts" / "11_run_parallel_campaign.sh"
EXPERIMENTS = KIT / "experiments"


def _exp_argparse(exp_name: str) -> argparse.ArgumentParser:
    """Import an experiment script and re-build its argparse parser.

    We can't just import the script (it runs main()), so we extract the
    add_argument calls textually and reconstruct the parser. Sufficient
    for testing that wrapper invocations pass argparse validation.
    """
    src_files = list(EXPERIMENTS.glob(f"{exp_name}_*.py"))
    assert src_files, f"no source for {exp_name}"
    text = src_files[0].read_text()

    # Find the add_argument block
    p = argparse.ArgumentParser()
    for m in re.finditer(
        r"p\.add_argument\(([^)]+)\)", text, flags=re.DOTALL
    ):
        body = m.group(1)
        # Parse name (first quoted arg)
        name_m = re.search(r'"([^"]+)"', body)
        if not name_m:
            continue
        name = name_m.group(1)
        kwargs = {}
        # Common argparse fields
        if "type=int" in body:    kwargs["type"] = int
        if "type=float" in body:  kwargs["type"] = float
        if "type=Path" in body:   kwargs["type"] = Path
        if "required=True" in body: kwargs["required"] = True
        nargs_m = re.search(r'nargs=(["\'])(\+|\*)\1', body)
        if nargs_m: kwargs["nargs"] = nargs_m.group(2)
        action_m = re.search(r'action=(["\'])([^"\']+)\1', body)
        if action_m: kwargs["action"] = action_m.group(2)
        # default
        d_m = re.search(r'default=(\[[^\]]*\]|[^,)]+)', body)
        if d_m and "required" not in kwargs:
            try:
                kwargs["default"] = eval(d_m.group(1).strip())
            except Exception:
                pass
        try:
            p.add_argument(name, **kwargs)
        except Exception:
            pass
    return p


def _wrapper_invocation(exp_name: str) -> list[str]:
    """Extract the argv that the wrapper passes to a given experiment.

    Looks for `experiments/{exp_name}_*.py \\` blocks and pulls the
    flags. Substitutes shell variables with concrete values matching
    the runtime defaults.
    """
    text = SCRIPT.read_text()
    # Find the block: 'python3 experiments/EX_*.py' to next blank line
    pat = re.compile(
        rf"python3 experiments/{exp_name}_[^\s]+\.py\s+\\?\s*((?:.*\\?\n?)+?)\s*2>&1",
        flags=re.MULTILINE)
    m = pat.search(text)
    assert m, f"could not find {exp_name} invocation in wrapper"
    raw = m.group(1)
    # Substitute the variables we know
    subs = {
        '"${GPU_ARRAY[0]}"': "0",
        '"${GPU_ARRAY[@]}"': "0 1 2",
        '"$GPU_LIST"':       "0,1,2",   # the broken CSV form, kept here so
                                          # tests can detect this regression
        '"$DURATION_E2"':    "60",
        '"$DURATION_E3"':    "60",
        '"$DURATION_E4"':    "60",
        '"$DURATION_E6"':    "30",
        '"$LATEST_SWEEP"':   "/tmp/foo/parsed_results.csv",
        '"$DUR_E5"':         "30",
        '"$N_TRIALS_E7"':    "5",
    }
    for k, v in subs.items():
        raw = raw.replace(k, v)
    raw = raw.replace("\\\n", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    # Strip surrounding double-quotes around bare tokens
    tokens = re.findall(r'"[^"]*"|\S+', raw)
    return [t.strip('"') for t in tokens]


def test_e5_invocation_has_required_parsed_results():
    p = _exp_argparse("E5")
    args = _wrapper_invocation("E5")
    # Must include --parsed-results since it's required
    assert "--parsed-results" in args, \
        f"E5 invocation missing required --parsed-results: {args}"
    # And must parse without error
    p.parse_args(args)


def test_e6_invocation_passes_gpus_as_separate_tokens():
    p = _exp_argparse("E6")
    args = _wrapper_invocation("E6")
    # The CSV form is the bug. Make sure we don't have it.
    assert "0,1,2" not in args, \
        f"E6 still uses broken CSV form for --gpus: {args}"
    # And argparse must accept it
    p.parse_args(args)


def test_e7_invocation_passes_gpus_as_separate_tokens():
    p = _exp_argparse("E7")
    args = _wrapper_invocation("E7")
    assert "0,1,2" not in args, \
        f"E7 still uses broken CSV form for --gpus: {args}"
    p.parse_args(args)
