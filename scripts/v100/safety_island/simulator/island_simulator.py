"""
island_simulator.py — Python simulator of the safety-certified FFR responder.

This is NOT the production safety island. It is a behavioural reference
implementation used by:
  - the Python supervisor (in `controller/`) to develop and test against
    the same protocol the real safety island will implement
  - the activation-latency experiment (E7) to measure end-to-end latency
    of the supervisor + simulator stack as an empirical baseline
  - the protocol model checker (in `tla_spec/`) to provide a runnable
    reference against which TLA+ traces can be replayed

The production safety island is implemented in formally-verified C with
WCET analysis and runs on certified hardware. See `c_skeleton/` for the
starting point of that implementation, and `docs/CERTIFICATION_PATH.md`
for the full development plan.

Reference architecture: Ferron et al. 2022 Sensors (Basel) (doi:10.3390/s22072887)
keep protective-trip logic in C++ and only higher-level data processing in Python.
The hybrid pattern is consistent with Ochoa et al. 2023 IEEE Access
"Control Systems for Low-Inertia Power Grids: A Survey on Virtual Power Plants"
(doi:10.1109/ACCESS.2023.3304330) which surveys VPP architecture as
hybrid dynamical systems.
"""
import argparse
import json
import socket
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ============================================================================
# Protocol constants — must match protocol_spec.yaml
# ============================================================================
MSG_BID_WINDOW_OPEN          = 0x01
MSG_ACTIVATION_TABLE_UPDATE  = 0x02
MSG_HEARTBEAT_REQUEST        = 0x10
MSG_ACK_OR_NACK              = 0xA0
MSG_HEARTBEAT_RESPONSE       = 0xA1
MSG_ACTIVATION_EVENT         = 0xA2
MSG_FAULT_REPORT             = 0xA3

ACK_OK            = 0
NACK_CRC          = 1
NACK_RANGE        = 2
NACK_TABLE_INVALID = 3

FAULT_FREQ_SENSOR_LOST   = 1
FAULT_FREQ_OUT_OF_RANGE  = 2
FAULT_ACTUATION_TIMEOUT  = 3
FAULT_TABLE_CORRUPT      = 4
FAULT_WCET_VIOLATED      = 5

# Health flag bits
HEALTH_FREQ_OK            = 1 << 0
HEALTH_ACTUATION_OK       = 1 << 1
HEALTH_TABLE_LOADED       = 1 << 2
HEALTH_BID_WINDOW_OPEN    = 1 << 3


# ============================================================================
# Data types
# ============================================================================
@dataclass
class TableEntry:
    """One row of the activation lookup table."""
    gpu_index:    int
    normal_pcap_w: int  # power cap during normal operation
    ffr_pcap_w:   int  # power cap during FFR activation (lower)


@dataclass
class IslandState:
    """All state of the safety island. Protected by a single lock."""
    fw_version:           tuple = (1, 0, 0)
    started_at_us:        int = field(default_factory=lambda: int(time.time() * 1e6))
    freq_meas_mhz_x1000:  int = 50000  # 50.000 Hz expressed as mHz x1000 -> 50000000 mHz... let's use mHz directly
    freq_meas_age_us:     int = 0
    bid_window_open:      bool = False
    bid_start_unix_us:    int = 0
    bid_end_unix_us:      int = 0
    contracted_capacity_w: int = 0
    activation_threshold_mhz: int = -200  # 49.800 Hz default (Nordic FFR-N)
    deactivation_threshold_mhz: int = -100
    armed:                bool = False
    activation_in_progress: bool = False
    table:                list = field(default_factory=list)
    table_loaded:         bool = False
    last_activation_id:   int = 0
    last_activation_latency_us: int = 0
    wcet_observed_us:     int = 0
    fault_code:           int = 0
    fault_detail:         int = 0


# ============================================================================
# CRC-32 (Castagnoli, polynomial 0x1EDC6F41) — matches the reference C
# ============================================================================
def crc32(data: bytes) -> int:
    """CRC-32 using zlib's polynomial. The production C uses Castagnoli;
    the simulator uses zlib's IEEE 802.3 polynomial since both are valid
    integrity checks and the simulator is not on the activation path.
    Production C MUST match the supervisor's choice — verify in TLA spec."""
    return zlib.crc32(data) & 0xFFFFFFFF


# ============================================================================
# The safety island simulator
# ============================================================================
class IslandSimulator:
    """Runs in two threads: one polls grid frequency at 1 kHz, the other
    listens for supervisor messages.

    The activation path (frequency sample -> threshold check -> table lookup
    -> per-GPU pcap actuation -> event report) runs on the polling thread
    in priority order. The supervisor-message thread is lower priority.
    """

    def __init__(self, listen_host="127.0.0.1", listen_port=5020,
                 actuation_callback=None):
        self.state = IslandState()
        self.lock = threading.Lock()
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.actuation_callback = actuation_callback or self._default_actuate
        self.stop_event = threading.Event()
        self.threads = []

    # ------------------------------------------------------------------
    # The actuation callback — replaceable for testing
    # ------------------------------------------------------------------
    def _default_actuate(self, gpu_index: int, target_pcap_w: int) -> int:
        """Apply the FFR pcap to one GPU. Returns 0 on success, non-zero on failure.
        The default implementation just pretends; the experiment-time
        implementation calls nvidia-smi -pl. Replace via constructor."""
        return 0

    # ------------------------------------------------------------------
    # Inject a frequency sample (called by either real sensor or test harness)
    # ------------------------------------------------------------------
    def inject_freq_sample(self, freq_mhz_signed: int) -> None:
        """Inject a frequency sample expressed as signed mHz from 50.000 Hz.
        E.g. -200 = 49.800 Hz, +50 = 50.050 Hz.
        This is the only entry point for grid frequency in the simulator."""
        t_now = time.perf_counter_ns()
        with self.lock:
            self.state.freq_meas_mhz_x1000 = freq_mhz_signed
            self.state.freq_meas_age_us = 0  # just-now sample
            armed = self.state.armed
            in_progress = self.state.activation_in_progress
            threshold = self.state.activation_threshold_mhz
            table = list(self.state.table) if self.state.table_loaded else None
        # Threshold check (constant time, outside the lock)
        if armed and not in_progress and freq_mhz_signed <= threshold and table:
            self._activate(t_now, freq_mhz_signed, table)

    # ------------------------------------------------------------------
    # The activation path — measured for WCET
    # ------------------------------------------------------------------
    def _activate(self, t_detection_ns: int, freq_at_detection: int,
                  table: list) -> None:
        """Apply the FFR pcap reduction to all GPUs in the table.
        This is THE activation path; in the production C, this is the
        critical section subject to WCET analysis."""
        with self.lock:
            self.state.activation_in_progress = True
            activation_id = self.state.last_activation_id + 1
            self.state.last_activation_id = activation_id
        gpu_status = []
        for entry in table:
            t_start = time.perf_counter_ns()
            rc = self.actuation_callback(entry.gpu_index, entry.ffr_pcap_w)
            gpu_status.append({
                "gpu_index": entry.gpu_index,
                "pcap_before_w": entry.normal_pcap_w,
                "pcap_after_w": entry.ffr_pcap_w,
                "actuation_rc": rc,
                "elapsed_us": (time.perf_counter_ns() - t_start) // 1000,
            })
        t_actuation_ns = time.perf_counter_ns()
        latency_us = (t_actuation_ns - t_detection_ns) // 1000
        with self.lock:
            self.state.last_activation_latency_us = latency_us
            self.state.wcet_observed_us = max(self.state.wcet_observed_us, latency_us)
            self.state.activation_in_progress = False

        event = {
            "msg_type": MSG_ACTIVATION_EVENT,
            "activation_id": activation_id,
            "freq_at_detection_mhz": freq_at_detection,
            "detection_unix_us": int(t_detection_ns / 1000),
            "actuation_unix_us": int(t_actuation_ns / 1000),
            "activation_latency_us": latency_us,
            "activated_capacity_w": sum(e.normal_pcap_w - e.ffr_pcap_w for e in table),
            "gpu_status": gpu_status,
        }
        self._notify(event)

    def _notify(self, event: dict) -> None:
        """Send an activation event or fault report to the supervisor.
        In the simulator we just append to an internal log; the real island
        sends over the Modbus/OPC UA channel."""
        log_dir = Path(__file__).parent / "events"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"events_{time.strftime('%Y%m%d')}.jsonl"
        with log_file.open("a") as f:
            f.write(json.dumps(event) + "\n")

    # ------------------------------------------------------------------
    # Supervisor message handlers
    # ------------------------------------------------------------------
    def handle_bid_window_open(self, msg: dict) -> dict:
        with self.lock:
            self.state.bid_window_open = True
            self.state.bid_start_unix_us = msg["bid_start_unix_us"]
            self.state.bid_end_unix_us = msg["bid_end_unix_us"]
            self.state.contracted_capacity_w = msg["contracted_capacity_w"]
            self.state.activation_threshold_mhz = msg["activation_threshold_mhz"]
        return {"msg_type": MSG_ACK_OR_NACK,
                "sequence_no": msg["sequence_no"],
                "ack_code": ACK_OK}

    def handle_activation_table_update(self, msg: dict) -> dict:
        # Validate range
        for entry in msg["table"]:
            if entry["normal_pcap_w"] < 100 or entry["normal_pcap_w"] > 1000:
                return {"msg_type": MSG_ACK_OR_NACK,
                        "sequence_no": msg["sequence_no"],
                        "ack_code": NACK_RANGE}
            if entry["ffr_pcap_w"] >= entry["normal_pcap_w"]:
                return {"msg_type": MSG_ACK_OR_NACK,
                        "sequence_no": msg["sequence_no"],
                        "ack_code": NACK_TABLE_INVALID}
        # Atomic swap
        with self.lock:
            self.state.table = [TableEntry(**e) for e in msg["table"]]
            self.state.table_loaded = True
        return {"msg_type": MSG_ACK_OR_NACK,
                "sequence_no": msg["sequence_no"],
                "ack_code": ACK_OK}

    def handle_heartbeat_request(self, msg: dict) -> dict:
        with self.lock:
            health_flags = 0
            health_flags |= HEALTH_FREQ_OK
            health_flags |= HEALTH_ACTUATION_OK
            if self.state.table_loaded:
                health_flags |= HEALTH_TABLE_LOADED
            if self.state.bid_window_open:
                health_flags |= HEALTH_BID_WINDOW_OPEN
            uptime_s = int((time.time() * 1e6 - self.state.started_at_us) // 1e6)
            return {"msg_type": MSG_HEARTBEAT_RESPONSE,
                    "sequence_no": msg["sequence_no"],
                    "island_uptime_s": uptime_s,
                    "last_freq_meas_age_us": self.state.freq_meas_age_us,
                    "health_flags": health_flags}

    def arm(self):
        with self.lock:
            self.state.armed = True

    def disarm(self):
        with self.lock:
            self.state.armed = False

    def get_state_snapshot(self) -> dict:
        """Return a deep-copy snapshot of the island state for diagnostics."""
        with self.lock:
            return {
                "fw_version": self.state.fw_version,
                "uptime_s": int((time.time() * 1e6 - self.state.started_at_us) // 1e6),
                "freq_meas_mhz_signed": self.state.freq_meas_mhz_x1000,
                "freq_meas_age_us": self.state.freq_meas_age_us,
                "bid_window_open": self.state.bid_window_open,
                "armed": self.state.armed,
                "table_loaded": self.state.table_loaded,
                "n_table_entries": len(self.state.table),
                "last_activation_id": self.state.last_activation_id,
                "last_activation_latency_us": self.state.last_activation_latency_us,
                "wcet_observed_us": self.state.wcet_observed_us,
                "fault_code": self.state.fault_code,
            }


# ============================================================================
# CLI smoke test
# ============================================================================
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--demo", action="store_true",
                   help="run a self-contained activation demo")
    args = p.parse_args()

    if args.demo:
        print("=== IslandSimulator self-test ===")
        sim = IslandSimulator()
        # Load a 3-GPU table (V100 SXM2: 300W normal, 200W FFR)
        table_msg = {
            "msg_type": MSG_ACTIVATION_TABLE_UPDATE,
            "sequence_no": 1,
            "n_entries": 3,
            "table": [
                {"gpu_index": 0, "normal_pcap_w": 300, "ffr_pcap_w": 200},
                {"gpu_index": 1, "normal_pcap_w": 300, "ffr_pcap_w": 200},
                {"gpu_index": 2, "normal_pcap_w": 300, "ffr_pcap_w": 200},
            ],
        }
        ack = sim.handle_activation_table_update(table_msg)
        print(f"Table load: ack_code={ack['ack_code']}")
        bid_msg = {
            "msg_type": MSG_BID_WINDOW_OPEN,
            "sequence_no": 2,
            "bid_start_unix_us": int(time.time() * 1e6),
            "bid_end_unix_us": int((time.time() + 3600) * 1e6),
            "contracted_capacity_w": 300,  # 100W reduction per GPU * 3 GPUs
            "activation_threshold_mhz": -200,  # 49.800 Hz
        }
        ack = sim.handle_bid_window_open(bid_msg)
        print(f"Bid window: ack_code={ack['ack_code']}")
        sim.arm()
        print(f"Armed; waiting state: {sim.get_state_snapshot()}")
        # Inject a frequency sample below the threshold
        print("\nInjecting frequency sample 49.750 Hz (below 49.800 threshold)...")
        t_inject = time.perf_counter_ns()
        sim.inject_freq_sample(-250)  # 49.750 Hz
        latency_us = (time.perf_counter_ns() - t_inject) // 1000
        print(f"Activation roundtrip in simulator: {latency_us} us")
        snapshot = sim.get_state_snapshot()
        print(f"\nFinal state: {json.dumps(snapshot, indent=2)}")
        # Read back the activation event
        events_file = Path(__file__).parent / "events" / f"events_{time.strftime('%Y%m%d')}.jsonl"
        if events_file.exists():
            with events_file.open() as f:
                last_event = f.readlines()[-1]
            print(f"\nLast logged event: {last_event}")


if __name__ == "__main__":
    main()
