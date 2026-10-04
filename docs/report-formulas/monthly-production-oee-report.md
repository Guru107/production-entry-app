# Monthly Production OEE Report

Source: `monthly_production_oee_report/monthly_production_oee_report.py`

One row is one Workstation for one calendar month of Production Dates. The report converts
Year + Month into that month's inclusive Production Date Range, runs the same day × workstation
bases as the Production OEE Report, sums those bases by workstation, keeps OEE Standard SPM
production-time-weighted across the month, then recomputes Availability, Quality, Productivity,
and OEE. See ADR 0007.

- `month`: `YYYY-MM` for the selected calendar month.
- `workstation`: same group key as Production OEE Report (`"Unassigned"` fallback).
- Additive bases summed from daily rows: `first_shift_strokes`, `second_shift_strokes`,
  `total_strokes`, `rejection`, `avl_time_hrs`, `machine_downtime`, `total_loss_time`,
  `running_time`, `quality_total`, and selected OEE Loss Breakdown reason × shift hours.
- `std_spm` (OEE Standard SPM): `standard_spm_weighted_sum / production_mins_sum` across the
  month when any entry contributes; otherwise the Workstation standard SPM fallback carried from
  daily rows.
- `stroke_required`: `running_time × std_spm × 60`.
- `act_spm`: `total_strokes / (running_time × 60)` if `running_time > 0` else `0`.
- `productivity_pct`, `quality_pct`, `availability_pct`, `oee` (Avg. OEE), `oee_mult_pct`:
  same formulas as Production OEE Report, applied to the month totals (never averages of
  daily percentages).
- Downtime-only Production Dates are included. There is no cross-workstation totals row.

Filters: Year, Month, Workstation, Operation, Downtime Reason. Operation filter keeps the daily
report's rule of omitting downtime-only contributions.
