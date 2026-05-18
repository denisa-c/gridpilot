# Configuring GridPilot for a New ENTSO-E Member Country

GridPilot ships with seven built-in country configurations (CH, IT, DE, FR, ES, DK, NL). Adding a new ENTSO-E member country requires three pieces of information and one YAML file — no code changes are needed.

## Step 1: Find the Country's ENTSO-E Bidding-Zone Code

The bidding-zone code (also called EIC code) identifies the country in ENTSO-E API requests. The complete list of codes is published at the [ENTSO-E Transparency Platform API Guide](https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html). Common examples are `10YCH-SWISSGRIDZ` for Switzerland, `10Y1001A1001A82H` for Germany-Luxembourg, and `10YPL-AREA-----S` for Poland.

## Step 2: Identify the Country's Available Ancillary Services

The four primary frequency-control services that GridPilot supports are FCR (30-second), aFRR (5-minute), mFRR (12.5-minute), and RR (the slowest tier). Not every country procures all four. The country's TSO website publishes the list of services and their procurement specifications. For example, Belgium's Elia procures FCR, aFRR, mFRR but not RR; Norway's Statnett procures FCR-N, FCR-D, and aFRR but uses different definitions.

For each service the country procures, you need the following parameters: the participation rate (the share of the country's balancing market that is open to demand-response participants, typically 0.05 to 0.80), the minimum bid size in MW (typically 0.3 to 5 MW), the activation time in seconds (30 for FCR, 300 for aFRR, 750 to 900 for mFRR, 1800 for RR), and the marginal CI of the balancing reserve in gCO2/kWh (typical range 250 for CCGT-dominated reserves to 700 for coal-dominated reserves).

## Step 3: Find the Country's Annual Mean Carbon Intensity

The annual mean CI in gCO2/kWh anchors the operational-carbon calculation. Use the latest published value from the European Environment Agency, Ember, or the IEA. Example values: 30 (CH), 58 (FR), 178 (ES), 295 (DE), 320 (NL).

## Step 4: Create a YAML Configuration File

Save the following YAML file as `my_country.yaml` in any directory you can read at runtime:

```yaml
PL:
  country_code: PL
  bidding_zone: "10YPL-AREA-----S"
  annual_mean_ci_g_per_kwh: 700.0
  timezone: Europe/Warsaw
  capacity_mw: 1500.0
  services:
    FCR:
      available: true
      participation_rate: 0.55
      marginal_ci_g_per_kwh: 800.0
      min_bid_mw: 1.0
      activation_time_s: 30
    aFRR:
      available: true
      participation_rate: 0.45
      marginal_ci_g_per_kwh: 800.0
      min_bid_mw: 1.0
      activation_time_s: 300
    mFRR:
      available: true
      participation_rate: 0.35
      marginal_ci_g_per_kwh: 900.0
      min_bid_mw: 5.0
      activation_time_s: 900
    RR:
      available: false
      participation_rate: 0.0
      marginal_ci_g_per_kwh: 0.0
      min_bid_mw: 0.0
      activation_time_s: 0
```

This example configures Poland (PL). Replace each value with the parameters appropriate to your target country.

## Step 5: Use the Custom Configuration

Pass the path to your YAML file when loading the country configuration:

```python
from integration.entsoe_connector import load_country_config
from controller.parametrisable import ParametrisableMultiscaleController

cfg = load_country_config("PL", custom_yaml="path/to/my_country.yaml")

ctrl = ParametrisableMultiscaleController(
    country="PL",
    cluster_capacity_mw=10.0,
    n_hosts=125,
    gpus_per_host=8,
)
print(ctrl.metadata)
```

The output will show the country code, bidding-zone code, list of enabled services, total committed MW, and the weighted marginal CI for the configured cluster.

## Optional: Use Live ENTSO-E API Data

By default GridPilot operates in synthesised mode that produces deterministic trajectories from the published market statistics encoded in the country configuration. To use live ENTSO-E API data, register for a free security token at the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) and set the environment variable `ENTSOE_API_KEY` before running the controller. The connector automatically detects the key and switches to live mode. If the API is unreachable for any reason, the connector silently falls back to the synthesised mode so the framework remains usable.

```bash
export ENTSOE_API_KEY="your-token-here"
python3 -m experiments.run_multicountry_validation
```

## Verifying Your Configuration

The reproducibility kit ships with a small validation script at `experiments/validate_country_config.py` that exercises a country configuration end-to-end and reports the service stack, the FFR signal characteristics, and the projected carbon savings. Run it as:

```bash
python3 experiments/validate_country_config.py --country PL --capacity-mw 10
```

The output is a one-line summary of the cluster's participation profile, suitable for inclusion in operational documentation or deployment plans.

## Adding a Country Permanently

If you want to merge your country configuration into the GridPilot built-in set, the canonical place is the function `builtin_country_configs()` in `src/integration/entsoe_connector.py`. Open a pull request against the GridPilot repository that adds the new country to the built-in dictionary, includes a corresponding test in `tests/test_entsoe_connector.py`, and references the public sources used for the participation rates and marginal CI values. The maintainers will review and merge after verifying the parameters against the country's published TSO documentation.
