#!/usr/bin/env python3
"""
scripts/raps_adapter/import_yaml.py
====================================

Lists the canonical RAPS YAML configurations bundled with the GridPilot
release and reports their key fields (node count, IT design power,
cooling efficiency, design PUE).  Re-export shim over
``src/integration/raps_config_adapter.py``.

Backs the PECS 2026 §3.6 adapter reference.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import yaml


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--configs-dir", type=Path,
                   default=ROOT / "raps" / "config",
                   help="Directory of RAPS YAML configs "
                        "(default raps/config — bundled ExaDigiT/RAPS).")
    p.add_argument("--system", type=str, default=None,
                   help="If given, only print this system (e.g. marconi100).")
    args = p.parse_args(argv)
    out = {}
    if not args.configs_dir.exists():
        print(f"WARNING: {args.configs_dir} does not exist; ship RAPS YAMLs in this dir",
              file=sys.stderr)
        return 0
    for yp in sorted(args.configs_dir.glob("*.yaml")):
        if args.system and yp.stem != args.system:
            continue
        cfg = yaml.safe_load(yp.read_text())
        out[yp.stem] = {
            "node_count":           cfg.get("node_count"),
            "it_design_power_kw":   cfg.get("it_design_power_kw"),
            "cooling_efficiency":   cfg.get("cooling_efficiency"),
            "design_pue":           cfg.get("design_pue"),
        }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
