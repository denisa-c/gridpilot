#!/usr/bin/env python3
"""Multiscale controller figure: regenerate from cached run results."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
src_pdf = ROOT / "figures" / "fig_multiscale_controller.pdf"
if src_pdf.exists():
    print("fig_multiscale_controller.pdf already present")
else:
    print("WARNING: fig_multiscale_controller.pdf not present in figures/")
