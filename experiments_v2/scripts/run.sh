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