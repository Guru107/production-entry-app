# Operator Daily SPM Report

Source: `operator_daily_spm_report/operator_daily_spm_report.py`

Grouped by `(Completed Shift shift_date, operator, workstation)`.

- `date`: linked Completed Shift date.
- `operator`: `custom_pea_operator` fallback `"Unassigned"`.
- `workstation`: `custom_pea_workstation` fallback `"Unassigned"`.
- `working_hours`: sum of `shift_duration` of distinct linked shifts in the group.
- `setting_time_hrs`: `Σ setup_mins / 60`.
- `loss_time_hrs`: `Σ non_setup_loss_mins / 60`.
- `production_time_hrs`: `Σ production_mins / 60`.
- `total_strokes`: sum of each entry's authoritative `custom_pea_total_strokes`.
- `spm`: `total_strokes / (production_time_hrs * 60)` if `production_time_hrs > 0` else `0`.
