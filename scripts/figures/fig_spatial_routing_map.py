#!/usr/bin/env python3
"""
scripts/figures/fig_spatial_routing_map.py
============================================
Placeholder figure for the C2 paper's spatial-routing visualisation.

Reads ``data/m100/spatial_sweep/spatial_sweep.csv`` and emits a bar
chart of per-home-grid destination-grid counts.  The full EU-map
visualisation lives here once the geo backend is wired up (cartopy or
plotly), but the bar chart is enough to ship the v0.1 paper skeleton.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--matrix", type=Path,
                    default=Path("data/m100/spatial_sweep/spatial_sweep.csv"))
    p.add_argument("--out", type=Path,
                    default=Path("figs/fig_spatial_routing_map.pdf"))
    args = p.parse_args(argv)

    if not args.matrix.exists():
        print(f"[fig_spatial_routing_map] WARN: {args.matrix} missing; "
              f"skipping figure", flush=True)
        return 0
    df = pd.read_csv(args.matrix)
    dest_cols = [c for c in df.columns if c.startswith("dest_")]
    if not dest_cols:
        print(f"[fig_spatial_routing_map] WARN: no dest_* columns in CSV",
              flush=True)
        return 0
    agg = df.groupby("home_grid")[dest_cols].mean()

    fig, ax = plt.subplots(figsize=(7.5, 4.5), constrained_layout=True)
    agg.plot(kind="bar", stacked=True, ax=ax, edgecolor="white")
    ax.set_title("Spatial routing: destination-grid counts per home grid (mean over seeds)")
    ax.set_ylabel("number of T5-eligible jobs routed to each grid")
    ax.set_xlabel("home grid")
    ax.legend(title="destination grid", bbox_to_anchor=(1.02, 1.0), loc="upper left")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    plt.close(fig)
    print(f"[fig_spatial_routing_map] wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
