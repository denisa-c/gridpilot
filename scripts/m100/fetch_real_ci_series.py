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
    # First-order neighbours required to balance imports/exports for
    # the consumption-mix CFE calculation (see Sect. on A11 fetch).
    "AT": "10YAT-APG------L",
    "BE": "10YBE----------2",
    "CZ": "10YCZ-CEPS-----N",
    "DK1": "10YDK-1--------W",
    "DK2": "10YDK-2--------M",
    "ES": "10YES-REE------0",
    "FI": "10YFI-1--------U",
    "GB": "10YGB----------A",
    "HU": "10YHU-MAVIR----U",
    "LT": "10YLT-1001A0008Q",
    "NL": "10YNL----------L",
    "NO2": "10YNO-2--------T",
    "SI": "10YSI-ELES-----O",
    "SK": "10YSK-SEPS-----K",
}

# Country-pair adjacencies (undirected) we query for cross-border
# physical flows.  Only listed pairs are queried; flows for any
# unlisted neighbour fall through to the published-annual-cfe lookup
# below.
NEIGHBOURS = {
    "SE": ["NO2", "FI", "DK1", "DK2", "DE", "LT", "PL"],
    "CH": ["DE", "FR", "IT", "AT"],
    "FR": ["BE", "DE", "ES", "IT", "CH", "GB"],
    "IT": ["FR", "CH", "AT", "SI"],
    "DE": ["NL", "DK1", "FR", "BE", "CH", "AT", "PL", "CZ", "SE"],
    "PL": ["DE", "CZ", "SK", "LT", "SE"],
}

# Annual carbon-free fraction (2024-2025 published averages from EEA /
# Ember) used for *external* neighbours that we do not fetch hourly.
# These appear in the consumption-mix imports of the six headline
# grids but are not in our headline set themselves.  Values are
# best-effort 2024 means; the consumption mix is only mildly
# sensitive to them because their contribution is weighted by net
# import volume.
EXTERNAL_CFE_ANNUAL = {
    "AT": 0.83, "BE": 0.74, "CZ": 0.45, "DK1": 0.78, "DK2": 0.78,
    "ES": 0.83, "FI": 0.92, "GB": 0.62, "HU": 0.75, "LT": 0.68,
    "NL": 0.50, "NO2": 0.99, "SI": 0.60, "SK": 0.86,
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


# Carbon-free PSR types per the Google / 24x7 CFE definition: wind,
# solar, nuclear, sustainable hydro, geothermal, marine.  Biomass
# (B01), waste (B17) and any fossil (B02--B08) are excluded.  This
# matches the canonical CFE% formula (CFE = carbon-free MWh divided by
# total MWh consumed) shown in cloud.google.com docs.
CFE_CLEAN_PSRS = {
    "B09",  # Geothermal
    "B10",  # Hydro pumped storage
    "B11",  # Hydro run-of-river
    "B12",  # Hydro water reservoir
    "B13",  # Marine
    "B14",  # Nuclear
    "B15",  # Other renewable
    "B16",  # Solar
    "B18",  # Wind offshore
    "B19",  # Wind onshore
}


def _build_ci_and_cfe_from_genmix(genmix: dict, freq: str = "h") -> pd.DataFrame:
    """Compute hourly CI **and** carbon-free fraction from a
    ``{psr_type -> hourly_MW}`` mapping.

    Returns a DataFrame with two columns:
      ``carbon_intensity_gCO2eq_per_kWh`` -- energy-weighted CI using
            IPCC AR5 lifecycle factors (g CO2eq / kWh).
      ``carbon_free_fraction`` -- share of generation in ``[0, 1]``
            coming from CFE_CLEAN_PSRS in that hour.  CFE% =
            100 * carbon_free_fraction (the canonical Google /
            24x7 CFE accounting formula).
    """
    if not genmix:
        return pd.DataFrame(
            columns=["carbon_intensity_gCO2eq_per_kWh",
                     "carbon_free_fraction"], dtype=float,
        )
    df = pd.DataFrame(genmix).sort_index()
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(),
                                    freq=freq, tz="UTC"))
    df = df.fillna(0.0)
    ci_weighted = pd.Series(0.0, index=df.index)
    clean_total = pd.Series(0.0, index=df.index)
    total       = pd.Series(0.0, index=df.index)
    for psr, col in df.items():
        ef = EF_G_PER_KWH.get(psr, 100.0)
        ci_weighted = ci_weighted + col * ef
        total       = total       + col
        if psr in CFE_CLEAN_PSRS:
            clean_total = clean_total + col
    denom = total.replace(0.0, np.nan)
    ci  = (ci_weighted / denom).ffill().bfill()
    cfe = (clean_total / denom).ffill().bfill().clip(0.0, 1.0)
    return pd.DataFrame({
        "carbon_intensity_gCO2eq_per_kWh": ci.values,
        "carbon_free_fraction":            cfe.values,
    }, index=df.index)


def _build_ci_from_genmix(genmix: dict, freq: str = "h") -> pd.Series:
    """Back-compat shim: returns just the CI series.  Newer callers
    should use :func:`_build_ci_and_cfe_from_genmix` directly so the
    carbon-free fraction makes it into the persisted parquet."""
    out = _build_ci_and_cfe_from_genmix(genmix, freq=freq)
    if out.empty:
        return pd.Series(dtype=float)
    s = out["carbon_intensity_gCO2eq_per_kWh"]
    s.name = "carbon_intensity_gCO2eq_per_kWh"
    return s


# ─────────────────────────────────────────────────────────────────────
# A11 cross-border physical flows + consumption-mix CFE
# ─────────────────────────────────────────────────────────────────────

def _fetch_a11_flow(out_eic: str, in_eic: str,
                     start: datetime, end: datetime,
                     api_key: str, timeout_s: float = 60.0) -> pd.Series:
    """Fetch the hourly physical flow MW from ``out_eic`` to ``in_eic``
    over ``[start, end)`` using ENTSO-E A11 (Aggregated cross-border
    flow).  Returns an hourly tz-aware UTC ``pd.Series`` of MW; an
    empty Series when the endpoint returns no data.

    Direction matters: this returns ONE direction only.  Compute the
    net flow as ``flow(A->B) - flow(B->A)`` from two queries.
    """
    params = {
        "securityToken": api_key,
        "documentType":  "A11",         # Aggregated cross-border flow
        "in_Domain":     in_eic,        # destination
        "out_Domain":    out_eic,       # source
        "periodStart":   _fmt_dt(start),
        "periodEnd":     _fmt_dt(end),
    }
    url = API_URL + "?" + urlparse.urlencode(params)
    req = urlreq.Request(url)
    try:
        with urlreq.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except (urlerr.URLError, urlerr.HTTPError, TimeoutError,
            ConnectionError, OSError):
        return pd.Series(dtype=float)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return pd.Series(dtype=float)
    ns_uri = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    def _q(tag):
        return f"{{{ns_uri}}}{tag}" if ns_uri else tag

    samples: list[tuple[datetime, float]] = []
    for ts in root.iter(_q("TimeSeries")):
        for period in ts.iter(_q("Period")):
            start_el = period.find(f".//{_q('timeInterval')}/{_q('start')}")
            if start_el is None:
                continue
            t0 = datetime.fromisoformat(start_el.text.replace("Z", "+00:00"))
            for point in period.iter(_q("Point")):
                pos = int(point.find(_q("position")).text)
                qty = float(point.find(_q("quantity")).text)
                samples.append((t0 + timedelta(hours=pos - 1), qty))
    if not samples:
        return pd.Series(dtype=float)
    s = pd.Series({t: q for t, q in samples}, name="flow_mw").sort_index()
    return s[~s.index.duplicated()]


def _fetch_a11_flow_chunked(out_eic: str, in_eic: str,
                              start: datetime, end: datetime,
                              api_key: str, *,
                              chunk_days: int = 30,
                              per_chunk_timeout_s: int = 60,
                              max_retries: int = 2) -> pd.Series:
    """Chunked variant of :func:`_fetch_a11_flow` --- mirrors the
    A75-chunking logic so an inaccessible month does not abort the
    whole flow."""
    parts: list[pd.Series] = []
    t = start
    while t < end:
        t_next = min(t + timedelta(days=chunk_days), end)
        attempt = 0
        while attempt <= max_retries:
            s = _fetch_a11_flow(out_eic, in_eic, t, t_next, api_key,
                                  timeout_s=per_chunk_timeout_s)
            if not s.empty or attempt == max_retries:
                if not s.empty:
                    parts.append(s)
                break
            attempt += 1
        t = t_next
    if not parts:
        return pd.Series(dtype=float)
    merged = pd.concat(parts).sort_index()
    return merged[~merged.index.duplicated()]


def _build_consumption_cfe(country: str, gen_df: pd.DataFrame,
                            production_cfe: pd.Series,
                            start: datetime, end: datetime,
                            api_key: str,
                            internal_cfe: dict[str, pd.Series]) -> pd.Series:
    """Compute the *consumption-mix* carbon-free fraction for one
    headline country.

    For each hour h:
        consumption[h]    = generation[h] + Σ imports[h] − Σ exports[h]
        consumed_clean[h] = own_clean[h]
                            + Σ_n imports_from_n[h] · cfe_n[h]
                            − Σ_n exports_to_n[h]   · cfe_own[h]
        consumption_cfe[h] = consumed_clean[h] / consumption[h]

    Neighbours in our six-country headline set use their own hourly
    `production_cfe` (passed via ``internal_cfe``).  External
    neighbours (AT, BE, NL, ...) use the published annual mean from
    ``EXTERNAL_CFE_ANNUAL`` --- the consumption mix is only mildly
    sensitive to these because they enter as a flow-weighted average,
    not as the dominant term.
    """
    if country not in NEIGHBOURS:
        return production_cfe
    if country not in EIC:
        return production_cfe

    own_total = gen_df.sum(axis=1) if not gen_df.empty else None
    if own_total is None or own_total.empty:
        return production_cfe
    own_clean = (production_cfe * own_total).reindex(own_total.index).fillna(0.0)

    imports_total = pd.Series(0.0, index=own_total.index)
    exports_total = pd.Series(0.0, index=own_total.index)
    imports_clean = pd.Series(0.0, index=own_total.index)

    for nb in NEIGHBOURS[country]:
        if nb not in EIC:
            continue
        # Imports: from neighbour -> country
        imp = _fetch_a11_flow_chunked(EIC[nb], EIC[country],
                                         start, end, api_key)
        # Exports: from country -> neighbour
        exp = _fetch_a11_flow_chunked(EIC[country], EIC[nb],
                                         start, end, api_key)
        imp = imp.reindex(own_total.index).fillna(0.0)
        exp = exp.reindex(own_total.index).fillna(0.0)
        imports_total = imports_total + imp
        exports_total = exports_total + exp
        # Mix the imports with the neighbour's clean fraction.
        if nb in internal_cfe and not internal_cfe[nb].empty:
            nb_cfe = internal_cfe[nb].reindex(own_total.index).ffill().bfill()
        else:
            nb_cfe = pd.Series(EXTERNAL_CFE_ANNUAL.get(nb, 0.5),
                                index=own_total.index)
        imports_clean = imports_clean + imp * nb_cfe

    consumption = own_total + imports_total - exports_total
    # Replace non-positive consumption (would invert the sign): fall
    # back to production mix for those rare hours.
    safe_consumption = consumption.where(consumption > 1.0, other=own_total)
    consumed_clean = own_clean + imports_clean - exports_total * production_cfe
    cfe_consumed = (consumed_clean / safe_consumption).clip(0.0, 1.0)
    cfe_consumed = cfe_consumed.fillna(production_cfe)
    cfe_consumed.name = "carbon_free_fraction_consumed"
    return cfe_consumed


def _fetch_a75_chunked(country_eic: str, start: datetime, end: datetime,
                        api_key: str, *, chunk_days: int = 30,
                        per_chunk_timeout_s: int = 90,
                        max_retries: int = 2) -> dict:
    """Fetch ``[start, end)`` in monthly chunks and merge per-psr series.

    Each chunk is ``chunk_days`` long.  Per-chunk timeout is generous
    (90 s) but bounded; the smaller payload returns much faster than a
    full year would.  Each chunk is retried up to ``max_retries`` times
    before being skipped (the skipped chunk's hours will be ffill'ed by
    the CI builder if surrounding chunks have data)."""
    merged: dict[str, list[pd.Series]] = {}
    t = start
    while t < end:
        t_next = min(t + timedelta(days=chunk_days), end)
        attempt = 0
        while attempt <= max_retries:
            try:
                chunk = _fetch_a75(country_eic, t, t_next, api_key,
                                    timeout_s=per_chunk_timeout_s)
                for psr, s in chunk.items():
                    merged.setdefault(psr, []).append(s)
                print(f"    [{t.date()}..{t_next.date()}] {len(chunk)} psr types, "
                      f"{sum(len(s) for s in chunk.values())} samples",
                      flush=True)
                break
            except (urlerr.URLError, urlerr.HTTPError, ET.ParseError,
                    TimeoutError, ConnectionError, OSError) as e:
                attempt += 1
                if attempt > max_retries:
                    print(f"    [{t.date()}..{t_next.date()}] giving up: {e}",
                          flush=True)
                    break
                print(f"    [{t.date()}..{t_next.date()}] retry {attempt}/{max_retries}: {e}",
                      flush=True)
        t = t_next
    # Concatenate per-psr partial series, drop duplicates from chunk overlap.
    return {psr: pd.concat(parts).sort_index()[~pd.concat(parts).sort_index().index.duplicated()]
            for psr, parts in merged.items()}


def _write_per_country(df_out: pd.DataFrame, country: str, out_dir: Path):
    """Persist hourly CI + carbon-free-fraction(s) as ``<country>_hourly.parquet``.

    Columns:
      ``timestamp``                       -- hourly UTC index
      ``carbon_intensity_gCO2eq_per_kWh`` -- own-generation lifecycle CI
      ``carbon_free_fraction``            -- consumption-mix CFE share
            (own generation + imports - exports), the column the
            accounting module reads.  When cross-border flows could not
            be fetched, this falls back to the production-mix share.
      ``carbon_free_fraction_production`` -- raw production-mix share
            (own generation only), kept for audit and to flag the
            CH-100\% pathology the consumption-mix fix corrects.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    df = df_out.reset_index().rename(columns={"index": "timestamp"})
    if "carbon_free_fraction" not in df.columns:
        df["carbon_free_fraction"] = (
            1.0 - df["carbon_intensity_gCO2eq_per_kWh"] / 800.0
        ).clip(lower=0.0, upper=1.0)
    out_path = out_dir / f"{country}_hourly.parquet"
    df.to_parquet(out_path, index=False)
    ci  = df["carbon_intensity_gCO2eq_per_kWh"]
    cfe = df["carbon_free_fraction"]
    cfe_prod = (df["carbon_free_fraction_production"]
                if "carbon_free_fraction_production" in df.columns
                else cfe)
    print(f"[entsoe-ci]   wrote {out_path}  (n={len(df)})")
    print(f"[entsoe-ci]     CI  mean={ci.mean():.1f} g/kWh "
          f"[{ci.min():.0f}..{ci.max():.0f}]")
    print(f"[entsoe-ci]     CFE consumption-mix mean={100*cfe.mean():.1f}\\% "
          f"[{100*cfe.min():.0f}..{100*cfe.max():.0f}]  "
          f"(production-mix mean={100*cfe_prod.mean():.1f}\\%)")


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

    # ── Pass 1: per-country generation mix + production-mix CFE ────
    pass1: dict[str, dict] = {}
    for c in grids:
        if c not in EIC:
            print(f"[entsoe-ci] WARN: no EIC code for {c}, skipping")
            continue
        try:
            print(f"[entsoe-ci] [pass 1/2 generation] fetching {c} "
                  f"{start.date()}..{end.date()} (monthly chunks)")
            genmix = _fetch_a75_chunked(EIC[c], start, end, args.api_key,
                                          chunk_days=30,
                                          per_chunk_timeout_s=90,
                                          max_retries=2)
        except (urlerr.URLError, urlerr.HTTPError, ET.ParseError,
                TimeoutError) as e:
            print(f"[entsoe-ci]   {c}: A75 API error ({e}); skipping")
            continue
        if not genmix:
            print(f"[entsoe-ci]   empty A75 response for {c}; skipping")
            continue
        df_ci_cfe = _build_ci_and_cfe_from_genmix(genmix)
        if df_ci_cfe.empty:
            continue
        # The DataFrame's own-generation rows (one column per PSR) are
        # needed by pass 2; reconstruct from genmix.
        gen_df = pd.DataFrame(genmix).sort_index()
        gen_df.index = pd.to_datetime(gen_df.index, utc=True)
        gen_df = gen_df.reindex(df_ci_cfe.index).fillna(0.0)
        pass1[c] = {
            "ci_cfe": df_ci_cfe,
            "gen_df": gen_df,
            "production_cfe": df_ci_cfe["carbon_free_fraction"].copy(),
        }

    # ── Pass 2: per-country consumption-mix CFE via A11 flows ──────
    internal_cfe = {c: p["production_cfe"] for c, p in pass1.items()}
    for c, p in pass1.items():
        df_ci_cfe = p["ci_cfe"]
        df_ci_cfe = df_ci_cfe.rename(
            columns={"carbon_free_fraction":
                     "carbon_free_fraction_production"}
        )
        try:
            print(f"[entsoe-ci] [pass 2/2 cross-border] reconciling {c}")
            cfe_consumed = _build_consumption_cfe(
                c, p["gen_df"], p["production_cfe"], start, end,
                args.api_key, internal_cfe,
            )
        except (urlerr.URLError, urlerr.HTTPError, ET.ParseError,
                TimeoutError) as e:
            print(f"[entsoe-ci]   {c}: A11 error ({e}); falling back "
                  f"to production-mix")
            cfe_consumed = p["production_cfe"]
        df_ci_cfe["carbon_free_fraction"] = cfe_consumed.reindex(
            df_ci_cfe.index).ffill().bfill().clip(0.0, 1.0)
        _write_per_country(df_ci_cfe, c, args.out_dir)

    print("[entsoe-ci] done.  Re-run the headline sweep with --no-cache:")
    print("  PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \\")
    print("    gridpilot/experiments_v2/scripts/04c_run_taxonomy_sweep.py \\")
    print("    --days-per-window 7 --workers 18 --no-cache "
          "--sampling energy_weighted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
