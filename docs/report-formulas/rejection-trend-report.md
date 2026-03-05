# Rejection Trend Report

Source: `rejection_trend_report/rejection_trend_report.py`

Grouped by time grain (`Daily`, `Weekly`, `Monthly`).

- `period`: formatted period label.
- `entries`: count of entries in period.
- `total_qty`: sum of entry total qty.
- `rejection_qty`: sum of entry rejection qty.
- `ok_qty`: `total_qty - rejection_qty`.
- `rejection_rate_pct`: `(rejection_qty / total_qty) * 100` if `total_qty > 0` else `0`.

