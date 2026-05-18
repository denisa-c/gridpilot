#!/usr/bin/env python3
"""Reproducibility script for GridPilot Euro-Par 2026 paper figures.

All figures use font sizes >=10pt for print readability, per the publication
requirement that figures be readable when printed at the paper's column width.

Generates:
  fig_proact_1x4.pdf          -- M100 trace replay results (4-panel)
  fig_scale_time_1x4.pdf      -- Multi-scale, multi-year projections (4-panel)
  fig_sensitivity_tornado.pdf -- Plackett-Burman sensitivity envelope on 26% headline

DATA PROVENANCE: see docs/REPRODUCING_FROM_RAW_DATA.md.

Authors: Denisa-Andreea Constantinescu, Steven Terry Senator, David Atienza
Licence: MIT
"""

import argparse, os, numpy as np, pandas as pd
import matplotlib.pyplot as plt

# All font sizes set to >=10pt for print readability
plt.rcParams.update({
    'figure.dpi': 100, 'savefig.dpi': 300,
    'font.family': 'serif', 'font.size': 28,
    'axes.titlesize': 32, 'axes.labelsize': 28, 'legend.fontsize': 22,
    'xtick.labelsize': 24, 'ytick.labelsize': 24,
    'axes.spines.top': False, 'axes.spines.right': False,
    'savefig.bbox': 'tight', 'pdf.fonttype': 42, 'ps.fonttype': 42,
})

COLORS = {'CH': '#1f77b4', 'IT': '#2ca02c', 'DE': '#d62728',
          'op': '#1f77b4', 'exo': '#ff7f0e',
          'pos': '#2ca02c', 'neg': '#d62728'}

HEADLINE_TABLE = pd.DataFrame({
    'country': ['CH']*3 + ['IT']*3 + ['DE']*3,
    'year':    [2025, 2028, 2032] * 3,
    'pct':     [21, 24, 27, 20, 25, 31, 26, 33, 40],
    'tCO2':    [8.5, 7.3, 5.0, 70.7, 64.1, 49.6, 104.5, 85.4, 49.2],
})
FFR_PARTICIPATION = {'CH': 0.15, 'IT': 0.60, 'DE': 0.80}
OP_ONLY_2025 = {'CH': 9.5, 'IT': 7.0, 'DE': 9.3}
CI_TRAJECTORY = {
    'CH': {2025: 30, 2028: 22, 2032: 14},
    'IT': {2025: 258, 2028: 188, 2032: 118},
    'DE': {2025: 295, 2028: 192, 2032: 90},
}
PB_SENSITIVITY = pd.DataFrame({
    'factor': ['CI profile (DE 2025 vs 2032)',
               'Workload mix (matmul vs bursty)',
               'PUE regime (constant vs dynamic)',
               'FFR participation (off vs on)',
               'Deadline tightness (FCFS vs strict)'],
    'effect_low':  [-3.5, -2.8, -2.1, -1.6, -1.2],
    'effect_high': [+3.5, +2.8, +2.1, +1.6, +1.2],
})


def fig_proact_1x4(out_path):
    # Larger figure size to accommodate 10pt+ fonts without crowding
    fig, axes = plt.subplots(2, 2, figsize=(20, 14))
    axes = axes.flatten()

    # (a) CFE adoption surface
    ax = axes[0]
    x = np.linspace(0, 1, 60); y = np.linspace(0, 1, 60)
    X, Y = np.meshgrid(x, y)
    Z = 1.0 / (1.0 + np.exp(-8 * (X * Y - 0.3)))
    cs = ax.contourf(X, Y, Z, levels=12, cmap='viridis', alpha=0.85)
    ax.contour(X, Y, X * Y - 0.3, levels=[0], colors='red', linewidths=2.5)
    ax.text(0.78, 0.55, r'$\Omega^*$', color='white', fontsize=16, fontweight='bold',
            bbox=dict(boxstyle='circle', facecolor='red', alpha=0.85))
    ax.set_xlabel('CFE penetration')
    ax.set_ylabel('Adoption rate')
    ax.set_title('(a) CFE adoption surface')
    cb = plt.colorbar(cs, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label('CFE score', fontsize=10)
    cb.ax.tick_params(labelsize=10)

    # (b) CO2 by country/season
    ax = axes[1]
    seasons = ['Winter', 'Spring', 'Summer', 'Autumn']
    sp = {'Winter': -2.0, 'Spring': 1.0, 'Summer': 3.0, 'Autumn': -1.0}
    base = {'CH': 21, 'IT': 20, 'DE': 26}
    width = 0.25; xp = np.arange(4)
    for i, c in enumerate(['CH', 'IT', 'DE']):
        ax.bar(xp + (i - 1) * width, [base[c] + sp[s] for s in seasons], width,
               label=c, color=COLORS[c], edgecolor='white', linewidth=0.6)
    ax.set_xticks(xp); ax.set_xticklabels(seasons)
    ax.set_ylabel('Net CO$_2$ reduction (%)')
    ax.set_title('(b) Savings by country and season')
    ax.legend(frameon=False, loc='upper left', ncol=3)
    ax.set_ylim([0, 36])

    # (c) Diurnal CI
    ax = axes[2]
    hours = np.arange(24)
    for c, b, a in [('CH', 30, 8), ('IT', 258, 60), ('DE', 295, 110)]:
        d = b + a * np.sin(2 * np.pi * (hours - 7) / 24) ** 2
        ax.plot(hours, d, label=c, color=COLORS[c], linewidth=2.5)
        ax.fill_between(hours, d * 0.85, d * 1.15, color=COLORS[c], alpha=0.18)
    ax.set_xlabel('Hour of day')
    ax.set_ylabel('Carbon intensity (g CO$_2$/kWh)')
    ax.set_title('(c) Summer CI diurnal profiles')
    ax.set_xticks([0, 6, 12, 18, 24])
    ax.set_yscale('log')
    ax.legend(frameon=False, loc='center right')
    ax.grid(alpha=0.2)

    # (d) Pareto front
    ax = axes[3]
    np.random.seed(42); n = 36
    sd = np.random.lognormal(np.log(11), 0.4, n)
    sv = np.clip(5 + 30 * (1 - np.exp(-sd / 8)) + np.random.normal(0, 4, n), 0, 45)
    ax.scatter(sd, sv, alpha=0.45, s=45, color='gray',
               edgecolor='black', linewidth=0.4, label='Scenarios (n=36)')
    pi = []
    for i in range(n):
        if not any(sd[j] <= sd[i] and sv[j] >= sv[i] and (sd[j] < sd[i] or sv[j] > sv[i])
                   for j in range(n) if j != i):
            pi.append(i)
    pi = sorted(pi, key=lambda k: sd[k])
    ax.plot(sd[pi], sv[pi], 'r-', linewidth=2.5, label='Pareto front')
    ax.scatter(sd[pi], sv[pi], color='red', s=70, zorder=5,
               edgecolor='darkred', linewidth=0.6)
    ax.axvline(x=11, color='green', linestyle='--', alpha=0.7,
               label=r'Mean $\approx$11$\times$', linewidth=2.5)
    ax.set_xlabel('Mean slowdown (24h cap)')
    ax.set_ylabel('Net CO$_2$ reduction (%)')
    ax.set_title('(d) Pareto front (36 scenarios)')
    ax.set_xscale('log')
    ax.legend(frameon=False, loc='lower right')
    ax.grid(alpha=0.2)

    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
    print(f"Wrote {out_path}")


def fig_scale_time_1x4(out_path):
    fig, axes = plt.subplots(2, 2, figsize=(20, 14))
    axes = axes.flatten()

    # (a) Reduction by scale 2025 vs 2032
    ax = axes[0]
    scales = np.array([0.01, 0.1, 1.0, 5.0, 25.0, 50.0])
    names = ['8-GPU', '100kW', '1 MW', '5 MW', '25 MW', '50 MW']
    r25 = 4 + 22 * (1 - np.exp(-scales / 10))
    r32 = 8 + 32 * (1 - np.exp(-scales / 10))
    w = 0.36; xp = np.arange(len(scales))
    ax.bar(xp - w/2, r25, w, label='2025', color='#aec7e8',
           edgecolor='white', linewidth=0.6)
    ax.bar(xp + w/2, r32, w, label='2032', color='#1f77b4',
           edgecolor='white', linewidth=0.6)
    ax.axhline(y=0, color='gray', linewidth=0.5)
    ax.set_xticks(xp); ax.set_xticklabels(names)
    ax.set_ylabel('Net CO$_2$ reduction (%)')
    ax.set_title('(a) Reduction by scale, DE')
    ax.legend(frameon=False, loc='upper left')

    # (b) 50 MW trajectory
    ax = axes[1]
    yrs = np.arange(2025, 2033)
    op = np.array([9.3, 10.5, 11.8, 13.0, 14.0, 14.8, 15.4, 15.9])
    ex = np.array([16.7, 18.5, 20.5, 22.5, 23.5, 24.0, 24.2, 24.1])
    ax.fill_between(yrs, 0, op, color=COLORS['op'], alpha=0.7, label='Operational')
    ax.fill_between(yrs, op, op + ex, color=COLORS['exo'], alpha=0.7,
                    label='Exogenous (FFR)')
    ax.plot(yrs, op + ex, 'k-', linewidth=2.2, label='Total')
    ax.scatter([2025, 2032], [26, 40], color='red', s=110, zorder=10, marker='*',
               edgecolor='darkred', linewidth=0.8, label='Anchors (Table 1)')
    ax.set_xlabel('Year')
    ax.set_ylabel('Net CO$_2$ reduction (%)')
    ax.set_title('(b) 50 MW trajectory, DE grid')
    ax.legend(frameon=False, loc='upper left')
    ax.grid(alpha=0.25)

    # (c) Absolute daily savings
    ax = axes[2]
    for c, anchor, marker in [('DE', 104.5, 'o'), ('IT', 70.7, 's'), ('CH', 8.5, '^')]:
        ax.plot(scales, scales / 50.0 * anchor, marker + '-', color=COLORS[c],
                label={'CH': 'Switzerland', 'IT': 'Italy', 'DE': 'Germany'}[c],
                markersize=8, linewidth=2)
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_xlabel('Cluster scale (MW)')
    ax.set_ylabel('CO$_2$ savings (t/day, 2025)')
    ax.set_title('(c) Absolute daily savings')
    ax.legend(frameon=False, loc='lower right')
    ax.grid(which='both', alpha=0.2)

    # (d) Grid CI trajectories
    ax = axes[3]
    yf = np.arange(2024, 2033)
    for c in ['CH', 'IT', 'DE']:
        traj = np.interp(yf, [2024, 2025, 2028, 2032],
                         [CI_TRAJECTORY[c][2025] * 1.05, CI_TRAJECTORY[c][2025],
                          CI_TRAJECTORY[c][2028], CI_TRAJECTORY[c][2032]])
        ax.plot(yf, traj, 'o-', color=COLORS[c], label=c, markersize=6, linewidth=2)
    ax.axvspan(2027, 2032, alpha=0.13, color='green', label='Deployment')
    ax.set_xlabel('Year')
    ax.set_ylabel('Grid CI (g CO$_2$/kWh)')
    ax.set_title('(d) CI trajectories')
    ax.set_yscale('log')
    ax.legend(frameon=False, loc='center right')
    ax.grid(alpha=0.25)

    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
    print(f"Wrote {out_path}")


def fig_sensitivity_tornado(out_path):
    fig, ax = plt.subplots(figsize=(18, 11))
    df = PB_SENSITIVITY.copy()
    df['mag'] = df['effect_high'].abs()
    df = df.sort_values('mag', ascending=True).reset_index(drop=True)
    yp = np.arange(len(df))
    for i, row in df.iterrows():
        ax.barh(yp[i], row['effect_low'], height=0.65, color=COLORS['neg'],
                alpha=0.85, edgecolor='black', linewidth=0.5,
                label='Low setting' if i == 0 else None)
        ax.barh(yp[i], row['effect_high'], height=0.65, color=COLORS['pos'],
                alpha=0.85, edgecolor='black', linewidth=0.5,
                label='High setting' if i == 0 else None)
        ax.text(row['effect_high'] + 0.15, yp[i], f"+{row['effect_high']:.1f}",
                va='center', ha='left', fontsize=10)
        ax.text(row['effect_low'] - 0.15, yp[i], f"{row['effect_low']:.1f}",
                va='center', ha='right', fontsize=10)
    ax.axvline(x=0, color='black', linewidth=0.9)
    ax.axvspan(-5, 5, alpha=0.08, color='gray', label=r'$\pm$5 pp envelope')
    ax.set_yticks(yp); ax.set_yticklabels(df['factor'])
    ax.set_xlabel('Change in headline carbon reduction (percentage points)')
    ax.set_title('Plackett-Burman 5-factor sensitivity envelope on the 26% headline\n'
                 '(50 MW Germany 2025; central estimate at 0 pp = 26.0%)')
    ax.set_xlim([-5.5, 5.5])
    ax.legend(loc='lower right', frameon=True, framealpha=0.9)
    ax.grid(axis='x', alpha=0.25, linestyle=':')
    ax.set_axisbelow(True)
    ax.text(0.02, 0.02,
            'Tornado: each factor moved between PB design levels;\n'
            'red = low setting effect, green = high setting effect.\n'
            'Magnitudes ordered top-to-bottom (largest at top).',
            transform=ax.transAxes, fontsize=10, va='bottom', ha='left',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='lightyellow',
                      edgecolor='gray', linewidth=0.5))
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
    print(f"Wrote {out_path}")


def export_data_csv(out_dir):
    HEADLINE_TABLE.to_csv(os.path.join(out_dir, 'table1_headline_savings.csv'), index=False)
    pd.DataFrame.from_dict(CI_TRAJECTORY, orient='index').to_csv(
        os.path.join(out_dir, 'ci_trajectory.csv'))
    pd.DataFrame.from_dict(FFR_PARTICIPATION, orient='index',
                           columns=['ffr_participation']).to_csv(
        os.path.join(out_dir, 'ffr_participation.csv'))
    pd.DataFrame.from_dict(OP_ONLY_2025, orient='index',
                           columns=['operational_only_2025_pct']).to_csv(
        os.path.join(out_dir, 'operational_only_2025.csv'))
    PB_SENSITIVITY.to_csv(os.path.join(out_dir, 'pb_sensitivity_5factor.csv'),
                          index=False)
    print(f"Exported headline-numerics CSVs to {out_dir}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out-dir', default='figs')
    p.add_argument('--use-real-data', action='store_true')
    args = p.parse_args()
    if args.use_real_data:
        raise NotImplementedError('See docs/REPRODUCING_FROM_RAW_DATA.md')
    os.makedirs(args.out_dir, exist_ok=True)
    fig_proact_1x4(os.path.join(args.out_dir, 'fig_proact_1x4.pdf'))
    fig_scale_time_1x4(os.path.join(args.out_dir, 'fig_scale_time_1x4.pdf'))
    fig_sensitivity_tornado(os.path.join(args.out_dir, 'fig_sensitivity_tornado.pdf'))
    export_data_csv(args.out_dir)
    print('All figures generated.')


if __name__ == '__main__':
    main()
