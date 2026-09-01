# Production OEE Report

Source: `production_oee_report/production_oee_report.py`

- `day`: linked Completed Shift `shift_date` group key.
- `workstation`: Stock Entry `custom_pea_workstation` group key (`"Unassigned"` fallback).
- `first_shift_strokes`: sum of entry `total_strokes` for rows whose linked shift label is `"1"`.
- `second_shift_strokes`: sum of entry `total_strokes` for rows whose linked shift label is `"2"`.
- `total_strokes`: sum of each entry's authoritative `custom_pea_total_strokes`.
- `quality_total`: part-based gross production total: normal entries use good plus total rejected quantity;
  Joint LH/RH entries use LH gross plus RH gross quantity.
- `rejection`: part-based quality rejection, including rework: normal entries use total rejected quantity;
  Joint LH/RH entries use LH rejection plus RH rejection quantity.
- `std_spm`: weighted average by production hours:
  - `std_spm = standard_spm_weighted_sum / duration_hours_sum`
  - `standard_spm_weighted_sum += custom_pea_standard_spm * entry_production_hours`
- `avl_time_hrs`: `max(linked_shift_hours - linked_shift_planned_loss_hours, 0)`, where linked shifts are the `custom_pea_shift` values of Stock Entries inside the same `(day, workstation)` row.
  - Shifts with zero linked Stock Entries for the row are excluded from `avl_time_hrs`.
- `total_loss_time`: sum of all loss bucket hour columns (`*_1st` + `*_2nd`).
- `running_time`: `max(avl_time_hrs - total_loss_time, 0)`.
- `stroke_required`: `running_time * std_spm * 60`.
- `act_spm`: `total_strokes / (running_time * 60)` if `running_time > 0` else `0`.
- `productivity_pct`: `(act_spm / std_spm) * 100` if `std_spm > 0` else `0`.
- `quality_pct`: `((quality_total - rejection) / quality_total) * 100` if `quality_total > 0` else `0`.
- `availability_pct`: `(running_time / avl_time_hrs) * 100` if `avl_time_hrs > 0` else `0`.
- `oee_mult_pct` (OEE %): `(availability_pct * quality_pct * productivity_pct) / 10000`.

Loss bucket columns (`setup_1st`, `setup_2nd`, `trial_1st`, ...):
- Built only from Stock Entry child `Loss Entry` rows.
- Reason -> bucket mapping via `LOSS_REASON_TO_BUCKET`.
- Shift label decides suffix:
  - label `"1"` => `_1st`
  - label `"2"` => `_2nd`
- Duration hours per row = normalized time interval duration in hours.
