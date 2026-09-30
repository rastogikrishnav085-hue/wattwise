# WattWise Demo Dataset Suite

Compact synthetic datasets for local testing and SIH demonstrations. They contain no customer information.

| File | Purpose | Expected result |
|---|---|---|
| 01_msme_shift_baseline.csv | Factory-style shifts | Pass |
| 02_normal_operations.csv | Stable operations | Pass |
| 03_high_demand_sanctioned_load.csv | Deliberate high peaks | Pass; use for demand-risk demo |
| 04_anomaly_heavy.csv | Deliberate spikes | Pass; use for anomaly demo |
| 05_growing_production.csv | Gradual load growth | Pass; use for trend demo |
| 06_data_quality_stress.csv | Missing timestamps/values and duplicates | Parser/resampling stress test |
| 07_negative_value_quality_test.csv | Invalid negative readings | Reject |
| 08_constant_value_quality_test.csv | No useful variance | Reject |

All files use `timestamp,load_kw` and can be uploaded through WattWise.


## Recommended SIH demo files

- `01_msme_shift_baseline.csv` — primary factory/MSME shift profile.
- `02_normal_operations.csv` — stable baseline.
- `03_high_demand_sanctioned_load.csv` — deliberate demand-limit stress case.
- `04_anomaly_heavy.csv` — deliberate anomaly-detection case.
- `05_growing_production.csv` — rising production trend.
- `09_food_processing_shift.csv` — food-processing style daytime production.
- `10_cold_storage_24x7.csv` — continuous cold-storage load with compressor/defrost cycles.

The dashboard provides download buttons for the main demo files, and the same CSVs can be uploaded through **Upload my data** to exercise the real upload pipeline.
