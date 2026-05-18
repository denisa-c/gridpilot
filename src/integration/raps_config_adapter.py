"""
integration/raps_config_adapter.py
-----------------------------------

Configuration adapter that extracts canonical system parameters from the
ExaDigiT RAPS configuration files (config/<system>.yaml) so that the ProACT
standalone framework can be calibrated against the same authoritative source
that produced the published Frontier and Marconi100 RAPS results.

This is the lightweight integration mode. It does not require running the
RAPS simulation engine, only reading its configuration files. The benefit
is that ProACT results then carry direct traceability to the official RAPS
parameters published at https://code.ornl.gov/exadigit/raps under Apache 2.0.

Design rationale:
  - We chose a parameter-extraction pattern over a runtime coupling pattern
    because the FMU files for the cooling models are part of a separate
    submodule that requires manual download and OpenModelica install.
  - We retain a deep-coupling adapter for environments that do support FMU
    loading; see raps_engine_adapter.py.
  - Parameter extraction also allows ProACT to validate against systems
    that RAPS supports natively (Frontier, Adastra, Lumi, MIT SuperCloud,
    Marconi100, Lassen) using the same canonical configurations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass
class RAPSSystemConfig:
    """Canonical system parameters extracted from a RAPS config file."""

    system_name: str
    num_cdus: int
    racks_per_cdu: int
    nodes_per_rack: int
    cpus_per_node: int
    gpus_per_node: int
    cpu_peak_flops: float
    gpu_peak_flops: float

    power_cpu_idle_w: float
    power_cpu_max_w: float
    power_gpu_idle_w: float
    power_gpu_max_w: float
    power_mem_w: float
    power_nic_w: float
    power_nvme_w: float

    cooling_efficiency: float
    wet_bulb_temp_k: float
    country_code: str

    raw_config: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_nodes(self) -> int:
        return self.num_cdus * self.racks_per_cdu * self.nodes_per_rack

    @property
    def node_power_idle_w(self) -> float:
        """Idle node power: GPUs + CPUs + memory + NIC + NVMe."""
        return (
            self.gpus_per_node * self.power_gpu_idle_w
            + self.cpus_per_node * self.power_cpu_idle_w
            + self.power_mem_w
            + self.power_nic_w
            + self.power_nvme_w
        )

    @property
    def node_power_max_w(self) -> float:
        return (
            self.gpus_per_node * self.power_gpu_max_w
            + self.cpus_per_node * self.power_cpu_max_w
            + self.power_mem_w
            + self.power_nic_w
            + self.power_nvme_w
        )

    @property
    def total_design_power_kw(self) -> float:
        return self.total_nodes * self.node_power_max_w / 1000

    @property
    def implied_design_pue(self) -> float:
        """RAPS uses cooling_efficiency, which we convert to PUE.

        cooling_efficiency = 0.945 means 5.5 percent of total facility power
        goes to losses, so PUE = 1 / cooling_efficiency for the cooling
        and power-distribution overhead.
        """
        return 1.0 / max(self.cooling_efficiency, 1e-6)


def load_raps_system_config(
    raps_repo_path: str | Path,
    system_name: str = "marconi100",
) -> RAPSSystemConfig:
    """Load a RAPS system configuration from the cloned repository.

    Parameters
    ----------
    raps_repo_path
        Path to a local clone of https://code.ornl.gov/exadigit/raps
    system_name
        Name of the system (matches a YAML file in raps_repo_path/config/).
        Supported by upstream RAPS: marconi100, frontier, adastraMI250, lumi,
        mit_supercloud, lassen, kestrel, gcloudv2.

    Returns
    -------
    RAPSSystemConfig with all canonical parameters extracted.
    """
    repo = Path(raps_repo_path)
    cfg_path = repo / "config" / f"{system_name}.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"RAPS config not found at {cfg_path}. Ensure the RAPS repository "
            f"is cloned at {repo} and the system name is correct."
        )
    raw = yaml.safe_load(cfg_path.read_text())

    sys_block = raw.get("system", {})
    pwr_block = raw.get("power", {})
    cool_block = raw.get("cooling", {})

    return RAPSSystemConfig(
        system_name=system_name,
        num_cdus=int(sys_block.get("num_cdus", 1)),
        racks_per_cdu=int(sys_block.get("racks_per_cdu", 1)),
        nodes_per_rack=int(sys_block.get("nodes_per_rack", 1)),
        cpus_per_node=int(sys_block.get("cpus_per_node", 0)),
        gpus_per_node=int(sys_block.get("gpus_per_node", 0)),
        cpu_peak_flops=float(sys_block.get("cpu_peak_flops", 0.0)),
        gpu_peak_flops=float(sys_block.get("gpu_peak_flops", 0.0)),
        power_cpu_idle_w=float(pwr_block.get("power_cpu_idle", 0.0)),
        power_cpu_max_w=float(pwr_block.get("power_cpu_max", 0.0)),
        power_gpu_idle_w=float(pwr_block.get("power_gpu_idle", 0.0)),
        power_gpu_max_w=float(pwr_block.get("power_gpu_max", 0.0)),
        power_mem_w=float(pwr_block.get("power_mem", 0.0)),
        power_nic_w=float(pwr_block.get("power_nic", 0.0)),
        power_nvme_w=float(pwr_block.get("power_nvme", 0.0)),
        cooling_efficiency=float(cool_block.get("cooling_efficiency", 1.0)),
        wet_bulb_temp_k=float(cool_block.get("wet_bulb_temp", 290.0)),
        country_code=str(cool_block.get("country_code", "US")),
        raw_config=raw,
    )


def list_raps_systems(raps_repo_path: str | Path) -> list[str]:
    """List all systems for which RAPS has a configuration file."""
    repo = Path(raps_repo_path)
    cfg_dir = repo / "config"
    if not cfg_dir.exists():
        return []
    return sorted(p.stem for p in cfg_dir.glob("*.yaml"))


def proact_params_from_raps(raps_cfg: RAPSSystemConfig) -> Dict[str, Any]:
    """Translate a RAPS system config into ProACT parameters.

    Returns a dict that can be passed directly to the ProACT scheduler and
    cooling-PUE model so that they use the same canonical values as RAPS.
    """
    return {
        "system_name": raps_cfg.system_name,
        "total_nodes": raps_cfg.total_nodes,
        "node_power_idle_kw": raps_cfg.node_power_idle_w / 1000,
        "node_power_max_kw": raps_cfg.node_power_max_w / 1000,
        "node_power_avg_kw": (raps_cfg.node_power_idle_w + raps_cfg.node_power_max_w) / 2 / 1000,
        "it_design_power_kw": raps_cfg.total_design_power_kw,
        "design_pue": raps_cfg.implied_design_pue,
        "cooling_efficiency": raps_cfg.cooling_efficiency,
        "country_code": raps_cfg.country_code,
        "gpus_per_node": raps_cfg.gpus_per_node,
        "cpus_per_node": raps_cfg.cpus_per_node,
        "gpu_idle_w": raps_cfg.power_gpu_idle_w,
        "gpu_max_w": raps_cfg.power_gpu_max_w,
        "cpu_idle_w": raps_cfg.power_cpu_idle_w,
        "cpu_max_w": raps_cfg.power_cpu_max_w,
    }
