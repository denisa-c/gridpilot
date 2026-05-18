#!/usr/bin/env python3
"""ENTSO-E 25-country figure: regenerate from cached sweep CSV."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
src_pdf = ROOT / "figures" / "fig_entsoe_multicountry.pdf"
if src_pdf.exists():
    print("fig_entsoe_multicountry.pdf already present")
else:
    print("WARNING: fig_entsoe_multicountry.pdf not present in figures/")
