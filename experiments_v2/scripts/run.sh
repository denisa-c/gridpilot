PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/02_run_country_sweep.py \
    --countries SE --mw 10 --seeds 1 --workers 1 --max-jobs 5000


# Whole pipeline including new seasonal phase:
bash gridpilot/experiments_v2/scripts/clean_rerun_all.sh

# Or just the seasonal pipeline in isolation:
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/04b_run_seasonal_sweep.py --workers 8
PYTHONPATH=gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/07_render_seasonal_figure.py \
        --seasonal-csv gridpilot/experiments_v2/data/seasonal_sweep/seasonal_sweep.csv \
        --out          gridpilot/experiments_v2/figs/fig_proact_1x4_v2.pdf



# Wipe the broken cache from the previous incomplete run, then rerun.
# MAX_JOBS=20000 is the default; override if you want a faster smoketest.
FRESH=1 WORKERS=20 bash gridpilot/experiments_v2/scripts/clean_rerun_all.sh


# What you should see:

# Phase 4a — tqdm progress bar across all 6 countries × 3 MW × 9 schedulers × 8 seeds ≈ 1296 cells, ~10–20 min on 20 workers at --max-jobs 20000.
# Phase 4b — 6 × 3 × 6 tiers × 8 seeds ≈ 864 cells. Same order of magnitude.
# Phase 4c — 6 × 12 hyper-values × 8 seeds = 576 cells. This is the one that wasn't running at all before.
# Phase 4d — seasonal sweep (4 × 3 × 5 × 4 = 240 cells), no --max-jobs needed (already capped per day).
# Phase 5a/5b/5c — extract macros + render figures + the fig_proact_1x4-style 2×2.

# Each cell should take ≤ 5 seconds at --max-jobs 20000 (one-hour timeout is just a safety net). The whole pipeline should finish in 30–60 min on a 20-worker box, not "forever".
# If you want to validate quickly that 04 is now actually producing cells before kicking off the full run:
PYTHONPATH=gridpilot/src:gridpilot/experiments_v2/src python3 \
    gridpilot/experiments_v2/scripts/04_run_hyper_sweep.py \
        --countries SE --seeds 1 --workers 1 --max-jobs 1000