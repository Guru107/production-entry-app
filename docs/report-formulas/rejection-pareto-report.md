# Rejection Pareto Report

Source: `rejection_pareto_report/rejection_pareto_report.py`

Per rejection reason:

- `rank`: order after sorting by descending `rejection_qty` then reason name.
- `rejection_reason`: reason key.
- `rejection_qty`: Σ breakup qty for the reason.
- `rejection_pct`: `(reason_qty / total_rejection_qty) * 100`.
- `cumulative_pct`: running sum of `rejection_pct` by rank; final row forced to `100`.
- `entries`: count of distinct Stock Entries containing that reason.
- `shifts`: count of distinct linked shifts containing that reason.

