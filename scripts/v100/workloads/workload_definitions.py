"""
workload_definitions.py — Three reference workloads representative of the
M100 / Philly / Acme job mix used in GridPilot, scaled to single-V100
short-batch experiments.

Each workload exposes a single `run()` function that takes a duration
parameter and a fixed seed for reproducibility. The workloads use only
PyTorch + CUDA, so no extra dependencies beyond the deep-learning stack.

References for workload selection:
  - Antici et al. 2023 PM100 dataset (M100): https://www.nature.com/articles/s41597-023-02465-9
  - Jeon et al. 2019 Philly trace (USENIX ATC):
      https://www.usenix.org/conference/atc19/presentation/jeon
  - Hu et al. 2024 Acme LLM trace (NSDI):
      https://www.usenix.org/conference/nsdi24/presentation/hu
  - Coplin & Burtscher 2018 sweep methodology (IPDPSW):
      https://doi.org/10.1109/IPDPSW.2018.00194

Workloads:
  matmul_compute_bound  — Repeated FP32 matrix multiplication. ~95% SM
                          utilisation, ~85% TDP draw on V100. Models the
                          compute-heavy phase of LLM training.
  inference_memory_bound — Repeated cuBLAS GEMV with small batches. Memory-
                          bandwidth bound, ~50% SM utilisation. Models the
                          decode phase of LLM inference.
  bursty_alternating    — 1 s of compute followed by 0.5 s of idle, looping.
                          Models the bimodal compute/communication pattern
                          characteristic of distributed AI training reported
                          by Choukse et al. 2025 Microsoft.
"""
import argparse
import time
import torch


def matmul_compute_bound(duration_s: float, size: int = 4096, seed: int = 0):
    """Compute-bound: square matmul of float32 tensors.
    On V100 (FP32 ~14 TFLOPS), 4096^3 takes ~10 ms; we loop for `duration_s`."""
    torch.manual_seed(seed)
    device = torch.device("cuda:0")
    a = torch.randn(size, size, device=device, dtype=torch.float32)
    b = torch.randn(size, size, device=device, dtype=torch.float32)
    torch.cuda.synchronize()
    t0 = time.time()
    n = 0
    while (time.time() - t0) < duration_s:
        c = a @ b
        a = c * 1.0001 - b
        n += 1
    torch.cuda.synchronize()
    elapsed = time.time() - t0
    return {"workload": "matmul_compute_bound",
            "size": size, "iterations": n,
            "elapsed_s": elapsed,
            "iters_per_s": n / elapsed}


def inference_memory_bound(duration_s: float, size: int = 16384, seed: int = 0):
    """Memory-bound: small batch GEMV. The matrix is large enough to spill
    out of L2, the batch is small enough that the kernel is bandwidth-bound."""
    torch.manual_seed(seed)
    device = torch.device("cuda:0")
    A = torch.randn(size, size, device=device, dtype=torch.float32)
    x = torch.randn(size, 4, device=device, dtype=torch.float32)  # batch 4
    torch.cuda.synchronize()
    t0 = time.time()
    n = 0
    while (time.time() - t0) < duration_s:
        y = A @ x
        x = y[:, :4] * 1.0001
        n += 1
    torch.cuda.synchronize()
    elapsed = time.time() - t0
    return {"workload": "inference_memory_bound",
            "size": size, "iterations": n,
            "elapsed_s": elapsed,
            "iters_per_s": n / elapsed}


def bursty_alternating(duration_s: float, size: int = 4096,
                        compute_s: float = 1.0, idle_s: float = 0.5,
                        seed: int = 0):
    """Bursty: alternating compute and idle phases, modelling distributed-
    training compute/communication bimodality."""
    torch.manual_seed(seed)
    device = torch.device("cuda:0")
    a = torch.randn(size, size, device=device, dtype=torch.float32)
    b = torch.randn(size, size, device=device, dtype=torch.float32)
    torch.cuda.synchronize()
    t0 = time.time()
    n_iter = 0
    n_burst = 0
    while (time.time() - t0) < duration_s:
        # Compute burst
        burst_start = time.time()
        while (time.time() - burst_start) < compute_s:
            c = a @ b
            a = c * 1.0001 - b
            n_iter += 1
        torch.cuda.synchronize()
        n_burst += 1
        # Idle phase: explicit sleep
        time.sleep(idle_s)
    elapsed = time.time() - t0
    return {"workload": "bursty_alternating",
            "size": size,
            "iterations": n_iter,
            "bursts": n_burst,
            "compute_s": compute_s, "idle_s": idle_s,
            "elapsed_s": elapsed,
            "iters_per_s": n_iter / elapsed}


WORKLOADS = {
    "matmul_compute_bound": matmul_compute_bound,
    "inference_memory_bound": inference_memory_bound,
    "bursty_alternating": bursty_alternating,
}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workload", choices=list(WORKLOADS.keys()), required=True)
    p.add_argument("--duration", type=float, default=30.0,
                   help="seconds to run (default 30)")
    p.add_argument("--size", type=int, default=None,
                   help="matrix size override")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available")
    print(f"Running {args.workload} for {args.duration}s on {torch.cuda.get_device_name(0)}")
    fn = WORKLOADS[args.workload]
    kwargs = {"duration_s": args.duration, "seed": args.seed}
    if args.size is not None:
        kwargs["size"] = args.size
    result = fn(**kwargs)
    import json
    print(json.dumps(result, indent=2))
