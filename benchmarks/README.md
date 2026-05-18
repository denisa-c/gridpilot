# Workload trace specifications

This directory holds metadata for the four workload archetypes used in the
paper. The actual trace files are documented in
[`../docs/DATASETS.md`](../docs/DATASETS.md) (M100, Philly, Acme).

## Archetype index

| File                      | Source        | Jobs   | Description                       |
|---------------------------|---------------|--------|-----------------------------------|
| `m100_eval_1994.yaml`     | M100 PM100    | 1,994  | matmul + steady-state subset      |
| `philly_8000.yaml`        | Philly        | 8,000  | inference-style DL serving        |
| `acme_synthetic_3000.csv` | this work     | 3,000  | LLM training, synthetic           |

## Synthesising your own trace

To synthesise a workload trace compatible with the GridPilot evaluation
harness, follow the schema in `m100_eval_1994.yaml`. Required fields per
job: `arrival_time_s`, `duration_s`, `gpu_count`, `cpu_count`, `mem_gb`,
`flexibility_class` (one of: matmul, inference, bursty, steady).
