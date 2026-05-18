#!/usr/bin/env python3
"""Validate a country configuration end-to-end.

Usage:
    python experiments/validate_country_config.py --country DE --capacity-mw 10
    python experiments/validate_country_config.py --country PL --capacity-mw 10 --yaml my_country.yaml
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--country", required=True, help="ENTSO-E country code (e.g. DE, PL)")
    p.add_argument("--capacity-mw", type=float, required=True, help="cluster capacity in MW")
    p.add_argument("--yaml", default=None, help="optional custom country YAML")
    p.add_argument("--api-key", default=None, help="ENTSO-E API key (else uses env)")
    args = p.parse_args()

    from integration.entsoe_connector import (
        load_country_config, ENTSOEConnector
    )
    from controller.parametrisable import ParametrisableMultiscaleController

    cfg = load_country_config(args.country, custom_yaml=args.yaml)
    print(f"Country: {cfg.country_code}")
    print(f"Bidding zone: {cfg.bidding_zone}")
    print(f"Annual mean CI: {cfg.annual_mean_ci_g_per_kwh} gCO2/kWh")
    print(f"Total balancing capacity: {cfg.capacity_mw} MW")
    print()
    print("Available services:")
    for svc, s in cfg.services.items():
        if s["available"]:
            print(f"  {svc}: participation={s['participation_rate']*100:.0f}%, "
                  f"min_bid={s['min_bid_mw']} MW, "
                  f"marginal_ci={s['marginal_ci_g_per_kwh']} gCO2/kWh")

    conn = ENTSOEConnector(api_key=args.api_key)
    print(f"\nConnector mode: {'live API' if conn.is_live() else 'synthesised'}")

    ctrl = ParametrisableMultiscaleController(
        country=args.country, cluster_capacity_mw=args.capacity_mw,
        n_hosts=int(args.capacity_mw * 125), gpus_per_host=8, connector=conn,
    )
    meta = ctrl.metadata
    print(f"\nCluster: {args.capacity_mw} MW, {int(args.capacity_mw * 125)} hosts")
    print(f"Services enabled: {', '.join(meta['services_enabled']) or '(none — cluster too small)'}")
    print(f"Total committed: {meta['total_committed_mw']:.2f} MW")
    print(f"Weighted marginal CI: {meta['weighted_marginal_ci']:.0f} gCO2/kWh")
    print(f"Data source: {meta['data_source']}")


if __name__ == "__main__":
    main()
