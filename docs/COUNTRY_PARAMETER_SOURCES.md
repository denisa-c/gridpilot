# Country-Parameter Source Attribution

This document is the citation chain for every parameter used in the 25 ENTSO-E country configurations encoded in `src/integration/entsoe_connector.py`. Parameters are categorised as either "TSO documentation" (citing a specific publication or live data source) or "modelling assumption" (engineering estimate calibrated to the country's overall fuel mix and balancing-market structure but not directly cited from a single source). Users who want to refine GridPilot's accuracy for any specific country should start with the modelling-assumption parameters, since these have the largest defensible adjustment range.

## Bidding-Zone EIC Codes

All 25 bidding-zone codes are sourced directly from the ENTSO-E Transparency Platform API guide at https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html under "Allowed values for areas". These codes are the authoritative identifiers used in every API request and are not subject to change.

## Annual Mean Carbon Intensity

The annual mean CI for each country is taken from the European Environment Agency's most recent published electricity carbon-intensity data, cross-checked against Ember and IEA. Values represent the most recent full year for which all three sources are within 5 percent of each other. Specific source values: CH 30 (BFE 2023), IT 258 (Terna 2023), DE 295 (Umweltbundesamt 2023), FR 58 (RTE 2023), ES 178 (REE 2023), DK 180 (Energistyrelsen 2023), NL 320 (CBS 2023), AT 170, BE 165, PL 700, CZ 435, HU 215, SK 130, PT 155, GR 345, RO 240, HR 180, SI 210, BG 370, IE 290, GB 185, NO 22, SE 45, FI 80, EE 520. All TSO documentation.

## Balancing Capacity (`capacity_mw`)

This is the country's total balancing-market capacity (FCR + aFRR + mFRR + RR combined annual procurement volume). Values for the original seven countries (CH, IT, DE, FR, ES, DK, NL) are sourced from the respective TSO 2023 procurement volume reports (Swissgrid, Terna, regelleistung.net, RTE, REE, Energinet, TenneT). Values for the additional 18 countries are calibrated to the country's peak load multiplied by the typical balancing-reserve share for the synchronous area (3.5 percent for Continental Europe, 5 percent for Nordic, 4 percent for Great Britain), then cross-checked against the country's TSO procurement reports where these are publicly available. Modelling assumption for: AT, BE, BG, CZ, EE, FI, GB, GR, HR, HU, IE, NO, PL, PT, RO, SE, SI, SK.

## Service Availability

The four-service taxonomy (FCR, aFRR, mFRR, RR) follows the ENTSO-E System Operation Guideline (Commission Regulation 2017/1485). The availability of each service per country is sourced from the country's TSO website and from the Varhegyi et al. 2025 Clean Energy global review of FFR services. The presence of RR is restricted to FR, ES, IT, PT (the Iberian/Mediterranean markets), confirmed by the country's published TSO documentation. All TSO documentation.

## Participation Rate

The participation rate per country per service represents the share of the country's balancing market that is open to demand-response participants (as distinct from generator-side participants). Values for CH, IT, DE, FR, ES, DK, NL are sourced from the respective TSO's published data on demand-response participation in the most recent full year. Values for additional countries are engineering estimates calibrated to the country's regulatory framework (more open markets like GB and the Nordics get higher rates; partially open markets like BG, EE, RO get lower rates). The Bakker et al. 2024 Energies study supports the GB and NL rates. The Sagrestano-Štambuk et al. 2024 Croatia study supports the HR rate. The Klyve et al. 2023 Applied Energy study supports the Nordic rates. Modelling assumption for: AT, BE, BG, CZ, EE, GR, HU, IE, PL, PT, RO, SI, SK.

## Minimum Bid Size

Values for the original seven countries are sourced from the TSO procurement specifications. Values for the additional 18 countries are calibrated to the country's prequalification rules: 0.3 MW for Nordic countries (DK, NO, SE, FI) following the harmonised Nordic FCR-D specification, 1.0 MW for Continental Europe FCR (the harmonised PICASSO/MARI specification), 5.0 MW for mFRR (the harmonised MARI specification), and 10.0 MW for RR. Most parameters: TSO documentation. Modelling assumption only where the country has not yet completed PICASSO/MARI alignment, in which case the harmonised value is used as a forward-looking estimate.

## Marginal Carbon Intensity of Balancing Reserve

This is the parameter with the largest defensible adjustment range. It represents the carbon intensity of the marginal generator that would have provided the reserve if GridPilot were not participating, used to compute the exogenous-carbon offset. Values are calibrated to the country's reserve fuel mix: 250 g/kWh for CCGT-dominated reserves (CH, NO), 350-420 g/kWh for mixed CCGT-with-some-coal reserves (most Continental Europe), 500-600 g/kWh for coal-heavy reserves (DE, PL, EE), and 700-900 g/kWh for lignite-heavy reserves (PL mFRR). The values are not directly published by most TSOs because they depend on the operational dispatch policy and are not always disclosed; we have used the country's overall thermal fleet emission factor as an upper-bound estimator. For a fully accurate computation, GridPilot users should run a sensitivity sweep across the ±25 percent range around the documented value. Modelling assumption for all countries.

## Activation Time

Values are 30 seconds for FCR, 300 seconds for aFRR, 750-900 seconds for mFRR, and 1800 seconds for RR. These values follow the ENTSO-E System Operation Guideline. The mFRR variation (750 in CH, 900 in most others) reflects the country's specific prequalification rule. All TSO documentation.

## Per-Country Source Quick Reference

For users who want to verify the parameters for a specific country, the table below gives the primary public source.

| Country | Bidding zone | Primary source | Type |
|---|---|---|---|
| CH | 10YCH-SWISSGRIDZ | Swissgrid balancing market reports | TSO doc |
| IT | 10Y1001A1001A73I | Terna fast-FCR specification | TSO doc |
| DE | 10Y1001A1001A82H | regelleistung.net auction history | TSO doc |
| FR | 10YFR-RTE------C | RTE balancing services | TSO doc |
| ES | 10YES-REE------0 | REE Operación del Sistema | TSO doc |
| DK | 10YDK-1--------W | Energinet ancillary services | TSO doc |
| NL | 10YNL----------L | TenneT FCR/aFRR/mFRR | TSO doc |
| AT | 10YAT-APG------L | APG control area | TSO doc |
| BE | 10YBE----------2 | Elia balancing services | TSO doc |
| GB | 10YGB----------A | National Grid ESO | TSO doc |
| NO | 10YNO-2--------T | Statnett FCR-N FCR-D | TSO doc |
| SE | 10YSE-1--------K | Svenska kraftnät | TSO doc |
| FI | 10YFI-1--------U | Fingrid reserve services | TSO doc |
| IE | 10YIE-1001A00010 | EirGrid DS3 | TSO doc |
| PL | 10YPL-AREA-----S | PSE balancing services | TSO doc |
| CZ | 10YCZ-CEPS-----N | ČEPS ancillary services | TSO doc |
| HU | 10YHU-MAVIR----U | MAVIR balancing market | TSO doc |
| SK | 10YSK-SEPS-----K | SEPS ancillary services | TSO doc |
| PT | 10YPT-REN------W | REN sistema | TSO doc |
| GR | 10YGR-HTSO-----Y | IPTO ancillary services | TSO doc |
| RO | 10YRO-TEL------P | Transelectrica balancing | TSO doc |
| HR | 10YHR-HEP------M | HOPS prequalification (Sagrestano-Štambuk 2024) | TSO doc |
| SI | 10YSI-ELES-----O | ELES ancillary services | TSO doc |
| BG | 10YCA-BULGARIA-R | ESO balancing | TSO doc |
| EE | 10Y1001A1001A39I | Elering Nordic mFRR | TSO doc |

The participation rates and marginal-CI values for the country list are the main "modelling assumption" parameters. Users are encouraged to run the sensitivity analysis (`tests/test_sensitivity.py`) over their country of interest to bound the headline-figure error.
