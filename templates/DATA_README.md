# WattWise real-data template

Use `MSME_LOAD_TEMPLATE.csv` as the simplest supported format. Required columns:

- `datetime` — timestamp such as `2026-09-01 08:00:00`
- `load_kw` — electricity demand/load in kW

WattWise also accepts UCI-style files with `Date;Time;Global_active_power` and common CSV/TXT variants.

Do not commit confidential meter/customer data to GitHub. For a public deployment, use the dashboard upload or a private storage/database workflow.
