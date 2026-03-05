# Rejection PPM Report

Source: `rejection_ppm_report/rejection_ppm_report.py`

Daily grouped.

- `date`
- `entries`
- `total_qty`
- `rejection_qty`
- `ppm`: `(rejection_qty / total_qty) * 1,000,000` if `total_qty > 0` else `0`.

