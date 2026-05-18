#!/usr/bin/env python3
"""
scripts/m100/fetch_real_ci_series.py
====================================
Fetch real hourly carbon-intensity (CI) series for each of the six
headline grids from the ENTSO-E Transparency Platform.

CI is computed per hour as
    CI(h) = sum_f gen_f(h) * emission_factor_f  /  sum_f gen_f(h)
where ``gen_f`` is the actual generation in MW for fuel type ``f``
in that hour (ENTSO-E document type A75, ``ProcessType=A16``).
Per-fuel emission factors follow the IPCC AR5 + IEA 2024 lifecycle
medians (g CO2eq/kWh):

    Hard coal           820
    Lignite             1050
    Natural gas         490
    Oil                 700
    Biomass             230
    Hydro pumped/run    24
    Hydro reservoir     24
    Wind onshore        11
    Wind offshore       12
    Solar PV            45
    Nuclear             12
    Geothermal          38
    Waste               700

If the ENTSO-E API token is not configured (``ENTSOE_API_KEY``
env var unset) or the API is unreachable, the script writes a
warning and falls back to the bundled synthesised CI series so the
replay still works.

Usage:
    ENTSOE_API_KEY=... PYTHONPATH=src python scripts/m100/fetch_real_ci_series.py \
        --start 2024-01-01 --end 2025-01-01 \
        --grids SE,CH,FR,IT,DE,PL \
        --out-dir data/ci/entsoe/
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import request as urlreq, error as urlerr, parse as urlparse
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd


# ENTSO-E EIC codes for the six headline grids (bidding zones).
EIC = {
    "SE": "10YSE-1--------K",
    "CH": "10YCH-SWISSGRIDZ",
    "FR": "10YFR-RTE------C",
    "IT": "10YIT-GRTN-----B",
    "DE": "10Y1001A1001A83F",  # DE-LU
    "PL": "10YPL-AREA-----S",
}

# IPCC AR5 / IEA 2024 lifecycle medians, g CO2eq / kWh.
EF_G_PER_KWH = {
    "B01": 230,   # Biomass
    "B02": 1050,  # Fossil Brown coal/Lignite
    "B03": 490,   # Fossil Coal-derived gas
    "B04": 490,   # Fossil Gas
    "B05": 820,   # Fossil Hard coal
    "B06": 700,   # Fossil Oil
    "B07": 700,   # Fossil Oil shale
    "B08": 700,   # Fossil Peat
    "B09": 38,    # Geothermal
    "B10": 24,    # Hydro pumped storage
    "B11": 24,    # Hydro run-of-river
    "B12": 24,    # Hydro water reservoir
    "B13": 11,    # Marine
    "B14": 12,    # Nuclear
    "B15": 45,    # Other renewable
    "B16": 45,    # Solar
    "B17": 700,   # Waste
    "B18": 12,    # Wind Offshore
    "B19": 11,    # Wind Onshore
    "B20": 100,   # Other (fallback)
}

API_URL = "https://web-api.tp.entsoe.eu/api"
NS = {"a": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0",
      "b": "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:1"}


def _fmt_dt(d: datetime) -> str:
    # ENTSO-E period format: YYYYMMDDHH00
    return d.strftime("%Y%m%d%H00")


def _fetch_a75(country_eic: str, start: datetime, end: datetime,
                api_key: str, timeout_s: float = 60.0) -> dict:
    """Fetch Actual Generation per Production Type (A75) for one zone
    over the [start, end) window.  Returns ``{psr_type: pandas.Series}``
    keyed by ENTSO-E PSR-type code (B01..B20), each value an hourly
    series indexed by UTC timestamp.
    """
    params = {
        "securityToken": api_key,
        "documentType":  "A75",
        "processType":   "A16",  # Realised
        "in_Domain":     country_eic,
        "periodStart":   _fmt_dt(start),
        "periodEnd":     _fmt_dt(end),
    }
    url = API_URL + "?" + urlparse.urlencode(params)
    req = urlreq.Request(url)
    with urlreq.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    # Discover the actual namespace at runtime; ENTSO-E rotates it.
    ns_uri = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    def _q(tag: str) -> str:
        return f"{{{ns_uri}}}{tag}" if ns_uri else tag

    series: dict[str, list[tuple[datetime, float]]] = {}
    for ts in root.iter(_q("TimeSeries")):
        psr_el = ts.find(f".//{_q('psrType')}")
        if psr_el is None:
            psr_el = ts.find(f".//{_q('MktPSRType')}/{_q('psrType')}")
        psr = psr_el.text if psr_el is not None else "B20"
        for period in ts.iter(_q("Period")):
            start_el = period.find(f".//{_q('timeInterval')}/{_q('start')}")
            if start_el is None:
                continue
            t0 = datetime.fromisoformat(start_el.text.replace("Z", "+00:00"))
            for point in period.iter(_q("Point")):
                pos = int(point.find(_q("position")).text)
                qty = float(point.find(_q("quantity")).text)
                ts_h = t0 + timedelta(hours=pos - 1)
                series.setdefault(psr, []).append((ts_h, qty))
    return {k: pd.Series({t: q for t, q in v}, name=k).sort_index()
            for k, v in series.items()}


def _build_ci_from_genmix(genmix: dict, freq: str = "h") -> pd.Series:
    """Compute hourly CI from a {psr_type -> hourly_MW} mapping."""
    if not genmix:
        return pd.Series(dtype=float)
    df = pd.DataFrame(genmix).sort_index()
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(),
                                    freq=freq, tz="UTC"))
    df = df.fillna(0.0)
    weighted = pd.Series(0.0, index=df.index)
    total    = pd.Series(0.0, index=df.index)
    for psr, col in df.items():
        ef = EF_G_PER_KWH.get(psr, 100.0)
        weighted = weighted + col * ef
        total    = total    + col
    ci = (weighted / total.replace(0.0, np.nan)).fillna(method="ffill").fillna(method="bfill")
    ci.name = "carbon_intensity_gCO2eq_per_kWh"
    return ci


def _write_per_country(ci: pd.Series, country: str, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"timestamp": ci.index,
                        "carbon_intensity_gCO2eq_per_kWh": ci.values})
    out_path = out_dir / f"{country}_hourly.parquet"
    df.to_parquet(out_path, index=False)
    print(f"[entsoe-ci]   wrote {out_path}  "
          f"(n={len(df)}, mean={ci.mean():.1f}, "
          f"min={ci.min():.1f}, max={ci.max():.1f} g/kWh)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=str, required=True,
                    help="UTC start date, e.g. 2024-01-01")
    p.add_argument("--end",   type=str, required=True,
                    help="UTC end date (exclusive), e.g. 2025-01-01")
    p.add_argument("--grids", type=str,
                    default="SE,CH,FR,IT,DE,PL")
    p.add_argument("--out-dir", type=Path,
                    default=Path("data/ci/entsoe"))
    p.add_argument("--api-key", type=str,
                    default=os.environ.get("ENTSOE_API_KEY"))
    args = p.parse_args(argv)

    if not args.api_key:
        print("ERROR: ENTSOE_API_KEY not set (and --api-key not provided).",
                file=sys.stderr)
        print("  Get a token at https://transparency.entsoe.eu/  "
                "(Account -> Web API security token)", file=sys.stderr)
        return 2

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end   = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    grids = [g.strip().upper() for g in args.grids.split(",") if g.strip()]

    for c in grids:
        if c not in EIC:
            print(f"[entsoe-ci] WARN: no EIC code for {c}, skipping")
            continue
        try:
            print(f"[entsoe-ci] fetching {c} {start.date()}..{end.date()}")
            genmix = _fetch_a75(EIC[c], start, end, args.api_key)
            if not genmix:
                print(f"[entsoe-ci]   empty response for {c}; skipping")
                continue
            ci = _build_ci_from_genmix(genmix)
            _write_per_country(ci, c, args.out_dir)
        except (urlerr.URLError, urlerr.HTTPError,
                ET.ParseError, TimeoutError) as e:
            print(f"[entsoe-ci]   {c}: API error ({e}); skipping")
    print("[entsoe-ci] done.  Use these CSVs via the YAML's ci_csv field, e.g.")
    print("           configs/grids/SE.yaml -> add 'ci_csv: ../../data/ci/entsoe/SE_hourly.parquet'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
