# Rework PPM Report

Source: `rework_ppm_report/rework_ppm_report.py`

Daily grouped.

- `date`
- `entries`
- `total_qty`
- `rework_qty`
- `ppm`: `(rework_qty / total_qty) * 1,000,000` if `total_qty > 0` else `0`.

