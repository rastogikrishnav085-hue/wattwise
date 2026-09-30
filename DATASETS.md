# WattWise Dataset References

## Included test data

The `demo_data/` folder contains compact synthetic datasets designed specifically for WattWise testing. They are safe to redistribute with the project because they were generated for this release and contain no customer information.

## Public benchmark datasets

1. **UCI Individual Household Electric Power Consumption** — about 2.08 million one-minute observations over almost four years, with missing measurements. Useful for testing parsing, resampling, forecasting and data-quality handling.
   https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption

2. **UCI ElectricityLoadDiagrams20112014** — 370 electricity clients with 15-minute consumption values from 2011–2014. Useful for multi-client/time-series benchmarking, but the download is large, so it is intentionally not bundled in this ZIP.
   https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014

3. **UCI Appliances Energy Prediction** — a smaller multivariate energy dataset suitable for experimentation with energy-use prediction.
   https://archive.ics.uci.edu/datasets?search=Appliances%20Energy%20Prediction

Use the public datasets according to their respective licenses and attribution requirements.


### Bundled demo scenarios
The release includes compact, synthetic, clearly labeled MSME scenarios for repeatable demos. They are not presented as real meter data. Use the dashboard's download buttons to export a scenario, then switch to **Upload my data** and upload that same CSV to demonstrate the ingestion path.

Additional profiles include food processing and 24x7 cold storage so the portfolio can demonstrate that the pipeline is not tied to one factory shape.
