# Rework Trend Report

Source: `rework_trend_report/rework_trend_report.py`

Grouped by time grain.

- `period`
- `entries`
- `total_qty`
- `rework_qty`
- `non_rework_rejection_qty`: `max(rejection_qty - rework_qty, 0)` aggregated.
- `rework_rate_pct`: `(rework_qty / total_qty) * 100` if `total_qty > 0` else `0`.

