#!/usr/bin/env python3
"""Aggregate REAL V100 measurement results into the headline numerics
displayed in the paper Table 2.

Reads from data/v100_raw/ (the real April 2026 ecocloud-exp06 campaign)
and produces a unified headline_table.csv matching the paper.

This script reads the JSON summaries produced by the per-experiment scripts
in scripts/v100/experiments/. The raw NVML CSVs are also available under
data/v100_raw/<experiment>/ for full re-analysis.

Authors: Denisa-Andreea Constantinescu, Steven Terry Senator, David Atienza
Licence: MIT
"""

import argparse
import json
import os
import pandas as pd


def parse_e1(raw_dir):
    """E1 best-efficiency operating point per workload."""
    summary_path = os.path.join(raw_dir, 'E1_power_cap_sweep', 'summary_table.csv')
    if not os.path.exists(summary_path):
        return []
    df = pd.read_csv(summary_path)
    rows = []
    for _, r in df.iterrows():
        wl = r.get('workload', 'unknown')
        rows.append({'experiment': 'E1', 'metric': 'best_pcap_w',
                     'workload': wl, 'value': r.get('best_pcap_w', 'NA'),
                     'unit': 'W'})
        rows.append({'experiment': 'E1', 'metric': 'best_fsm_mhz',
                     'workload': wl, 'value': r.get('best_fsm_mhz', 'NA'),
                     'unit': 'MHz'})
        rows.append({'experiment': 'E1', 'metric': 'best_iters_per_joule',
                     'workload': wl,
                     'value': round(r.get('best_iters_per_joule', 0), 4),
                     'unit': '-'})
    return rows


def parse_e3(raw_dir):
    """E3 AR(4) predictor MAE per workload."""
    e3_dir = os.path.join(raw_dir, 'E3_outer_loop')
    rows = []
    for wl in ['inference_memory_bound', 'matmul_compute_bound', 'bursty_alternating']:
        p = os.path.join(e3_dir, f'{wl}_metrics.json')
        if os.path.exists(p):
            with open(p) as f:
                m = json.load(f)
            rows.append({'experiment': 'E3', 'metric': 'ar4_mae_w',
                         'workload': wl, 'value': round(m['mae_w'], 2),
                         'unit': 'W'})
            rows.append({'experiment': 'E3', 'metric': 'ar4_p95_w',
                         'workload': wl, 'value': round(m['p95_w'], 2),
                         'unit': 'W'})
    return rows


def parse_e4(raw_dir):
    """E4 closed-loop demand-following per workload."""
    e4_dir = os.path.join(raw_dir, 'E4_closed_loop')
    rows = []
    for wl in ['inference_memory_bound', 'matmul_compute_bound', 'bursty_alternating']:
        p = os.path.join(e4_dir, f'{wl}_summary.json')
        if os.path.exists(p):
            with open(p) as f:
                s = json.load(f)
            rows.append({'experiment': 'E4', 'metric': 'rel_mae_pct',
                         'workload': wl,
                         'value': round(s['relative_mae'] * 100, 2),
                         'unit': '%'})
            rows.append({'experiment': 'E4', 'metric': 'mae_w',
                         'workload': wl, 'value': round(s['mae_w'], 2),
                         'unit': 'W'})
    return rows


def parse_e6(raw_dir):
    """E6 multi-GPU fairness per budget."""
    e6_dir = os.path.join(raw_dir, 'E6_multigpu')
    rows = []
    for budget in [600, 750, 900]:
        p = os.path.join(e6_dir, f'budget_{budget}_metrics.json')
        if os.path.exists(p):
            with open(p) as f:
                s = json.load(f)
            rows.append({'experiment': 'E6', 'metric': 'jain_fairness',
                         'workload': f'budget_{budget}w',
                         'value': round(s['jain_fairness'], 3),
                         'unit': '-'})
    return rows


def parse_e7(raw_dir):
    """E7 FFR end-to-end latency per workload."""
    e7_dir = os.path.join(raw_dir, 'E7_ffr_latency')
    rows = []
    for wl in ['matmul_compute_bound', 'inference_memory_bound', 'bursty_alternating']:
        p = os.path.join(e7_dir, f'workload_{wl}_summary.json')
        if os.path.exists(p):
            with open(p) as f:
                s = json.load(f)
            rows.append({'experiment': 'E7', 'metric': 'median_ms',
                         'workload': wl, 'value': round(s['median_ms'], 2),
                         'unit': 'ms'})
            rows.append({'experiment': 'E7', 'metric': 'max_ms',
                         'workload': wl, 'value': round(s['max_ms'], 2),
                         'unit': 'ms'})
            rows.append({'experiment': 'E7', 'metric': 'pass_rate',
                         'workload': wl,
                         'value': f"{s['n_pass']}/{s['n_trials']}",
                         'unit': '-'})
    # All-workloads verdict
    verdict_p = os.path.join(e7_dir, 'verdict.json')
    if os.path.exists(verdict_p):
        with open(verdict_p) as f:
            v = json.load(f)
        rows.append({'experiment': 'E7', 'metric': 'all_workloads_pass',
                     'workload': 'all', 'value': v['all_workloads_pass'],
                     'unit': 'bool'})
    return rows


def parse_raps(raw_dir):
    """RAPS calibration LOOCV results per workload."""
    p = os.path.join(raw_dir, 'raps_calibration', 'fit_summary.json')
    rows = []
    if os.path.exists(p):
        with open(p) as f:
            s = json.load(f)
        loocv_values = []
        for wl, m in s.items():
            if isinstance(m, dict) and 'loocv_mae_pct' in m:
                rows.append({'experiment': 'RAPS', 'metric': 'loocv_mae_pct',
                             'workload': wl,
                             'value': round(m['loocv_mae_pct'], 2),
                             'unit': '%'})
                loocv_values.append(m['loocv_mae_pct'])
        if loocv_values:
            rows.append({'experiment': 'RAPS', 'metric': 'loocv_mae_pct_mean',
                         'workload': 'all',
                         'value': round(sum(loocv_values) / len(loocv_values), 2),
                         'unit': '%'})
    return rows


def parse_cross_validation(raw_dir):
    """V100 vs M100 cross-validation axes."""
    p = os.path.join(raw_dir, 'cross_validation', 'comparison_report.json')
    rows = []
    if os.path.exists(p):
        with open(p) as f:
            c = json.load(f)
        for axis in c.get('cross_validation', []):
            rows.append({
                'experiment': 'CrossVal',
                'metric': f"axis_{axis['axis']}_{axis['name'].replace(' ', '_')}",
                'workload': '-',
                'value': axis.get('pct_err', 'NA'),
                'unit': '% error',
            })
    return rows


def parse_cluster(raw_dir):
    """Cluster scaling projection."""
    p = os.path.join(raw_dir, 'cluster_projection', 'projection_summary.json')
    rows = []
    if os.path.exists(p):
        with open(p) as f:
            s = json.load(f)
        for scale_name, scale in s.items():
            rows.append({'experiment': 'Cluster', 'metric': 'max_facility_kw',
                         'workload': scale_name,
                         'value': round(scale['max_facility_kw'], 2),
                         'unit': 'kW'})
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--raw-dir', default='data/v100_raw')
    p.add_argument('--output', default='data/v100_headlines.csv')
    args = p.parse_args()

    rows = []
    rows.extend(parse_e1(args.raw_dir))
    rows.extend(parse_e3(args.raw_dir))
    rows.extend(parse_e4(args.raw_dir))
    rows.extend(parse_e6(args.raw_dir))
    rows.extend(parse_e7(args.raw_dir))
    rows.extend(parse_raps(args.raw_dir))
    rows.extend(parse_cross_validation(args.raw_dir))
    rows.extend(parse_cluster(args.raw_dir))

    df = pd.DataFrame(rows)
    df.to_csv(args.output, index=False)
    print(df.to_string(index=False))
    print(f"\nWrote {args.output} ({len(df)} rows)")


if __name__ == '__main__':
    main()
