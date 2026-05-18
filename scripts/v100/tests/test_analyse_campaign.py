"""
test_analyse_campaign.py — guard against the iters_per_joule KeyError and
adjacent missing-column bugs in the campaign aggregator.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "analysis"))

import analyse_campaign


def _write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        if not rows:
            return
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def patched_find_latest(tmp_path, monkeypatch):
    sweep = tmp_path / "sweep_test"
    sweep.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(analyse_campaign, "find_latest",
                         lambda prefix: sweep if prefix.startswith("sweep_") else None)
    return sweep


def test_handles_missing_iters_per_joule(patched_find_latest):
    rows = [
        {"workload": "matmul", "pcap_w": "150", "sm_target_mhz": "945",
          "power_mean_w": "114.0", "iters_per_s": "64.95"},
        {"workload": "matmul", "pcap_w": "300", "sm_target_mhz": "1380",
          "power_mean_w": "206.3", "iters_per_s": "93.73"},
        {"workload": "memory", "pcap_w": "150", "sm_target_mhz": "945",
          "power_mean_w": "144.4", "iters_per_s": "403.78"},
    ]
    _write_csv(patched_find_latest / "parsed_results.csv", rows)
    summary = []
    result = analyse_campaign.analyse_E1_pareto(patched_find_latest, summary)
    assert result is not None
    assert len(summary) == 2
    by_wl = {s["workload"]: s["value"] for s in summary}
    assert abs(by_wl["matmul"] - (64.95 / 114.0)) < 0.01
    assert abs(by_wl["memory"] - (403.78 / 144.4)) < 0.01


def test_uses_iters_per_joule_when_present(patched_find_latest):
    rows = [
        {"workload": "matmul", "pcap_w": "150", "sm_target_mhz": "945",
          "power_mean_w": "100.0", "iters_per_s": "50.0",
          "iters_per_joule": "0.9"},
    ]
    _write_csv(patched_find_latest / "parsed_results.csv", rows)
    summary = []
    analyse_campaign.analyse_E1_pareto(patched_find_latest, summary)
    assert summary
    assert summary[0]["value"] == 0.9


def test_skips_zero_power(patched_find_latest):
    rows = [
        {"workload": "matmul", "pcap_w": "150", "sm_target_mhz": "945",
          "power_mean_w": "0", "iters_per_s": "50.0"},
        {"workload": "matmul", "pcap_w": "200", "sm_target_mhz": "1380",
          "power_mean_w": "150.0", "iters_per_s": "75.0"},
    ]
    _write_csv(patched_find_latest / "parsed_results.csv", rows)
    summary = []
    analyse_campaign.analyse_E1_pareto(patched_find_latest, summary)
    assert len(summary) == 1
    assert abs(summary[0]["value"] - (75.0 / 150.0)) < 0.01
