#!/usr/bin/env python3
"""
fetch_live_entsoe.py
====================

Fetch 24 hours of FCR, aFRR, and mFRR procurement data from the live
ENTSO-E Transparency Platform API for a list of countries, save to CSV,
and produce a comparison plot against the synthesised fallback.

Required environment:
    ENTSOE_API_KEY=<your-token>     # free registration at https://transparency.entsoe.eu/

Usage:
    python fetch_live_entsoe.py --countries DE FR ES IT CH --output data/hardware/exp4_entsoe_live.csv
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from integration.entsoe_connector import (
    ENTSOEConnector, load_country_config
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--countries", nargs="+", default=["DE","FR","ES","IT","CH"])
    parser.add_argument("--output", default="data/hardware/exp4_entsoe_live.csv")
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    api_key = os.environ.get("ENTSOE_API_KEY")
    if not api_key:
        print("ERROR: ENTSOE_API_KEY environment variable not set.")
        print("Register for a free token at https://transparency.entsoe.eu/")
        sys.exit(1)

    connector = ENTSOEConnector(api_key=api_key, timeout_s=60.0)
    print(f"Live API mode: {connector.is_live()}")

    end = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=args.hours)
    print(f"Fetching {args.hours}h window: {start} -> {end}")

    rows = []
    for country in args.countries:
        cfg = load_country_config(country)
        print(f"\n  Country: {country} ({cfg.bidding_zone})")
        for service in ["FCR", "aFRR", "mFRR"]:
            if not cfg.services.get(service, {}).get("available"):
                continue
            try:
                result = connector.fetch_ancillary(country, service, start, end, cfg)
                print(f"    {service:5s}: {len(result.timestamps):3d} samples, "
                      f"source={result.source}")
                for ts, cap, price in zip(result.timestamps,
                                            result.capacity_mw,
                                            result.price_eur_per_mw):
                    rows.append({
                        "country": country,
                        "bidding_zone": cfg.bidding_zone,
                        "service": service,
                        "timestamp": ts,
                        "capacity_mw": cap,
                        "price_eur_per_mw": price,
                        "source": result.source,
                    })
            except Exception as e:
                print(f"    {service:5s}: ERROR {e}")

    df = pd.DataFrame(rows)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"\nSaved {len(df)} rows to {output_path}")

    # Summary
    if len(df):
        print("\nSummary by source:")
        print(df.groupby(["country", "service", "source"])["capacity_mw"]
              .agg(["count", "mean"]).round(1))


if __name__ == "__main__":
    main()
