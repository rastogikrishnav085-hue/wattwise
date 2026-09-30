# WattWise UI/UX

The dashboard uses a consistent WattWise visual system with:

- Dark teal navigation with accessible white text.
- High-contrast KPI values and restrained accent colors for risk, savings, and forecasts.
- Responsive wide-layout cards and tables.
- Plotly charts styled for the dark-only SIH interface.
- WhattsOn presented as an Energy Intelligence workspace without exposing implementation-provider branding.

## Demo scenarios

- `msme_shift`: default factory/MSME load shape with shift windows, realistic operating blocks, and a small number of expected shift-boundary effects.
- `normal`: lower-risk baseline consumption.
- `high_demand`: deliberate sanctioned-load stress scenario for demonstrating breach and penalty warnings.
- `anomaly_heavy`: deliberate anomaly scenario for demonstrating anomaly detection.

Demo data is synthetic and clearly identified in the dashboard; it must not be represented as a real customer dataset.


## Current theme
WattWise uses a dark-only interface for the SIH release. The light-mode toggle has been removed to keep the presentation visually consistent.
