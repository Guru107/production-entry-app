# Daily Strokes SPM Monitor

Source: `daily_strokes_spm_monitor/daily_strokes_spm_monitor.py`

Grouped by date and (optionally) operator.

- `date`: group date.
- `operator`: present only when operator filter is not fixed.
- `setup_time_hrs`: `Σ setup_mins / 60`.
- `loss_time_hrs`: `Σ non_setup_loss_mins / 60`.
- `prod_time_hrs`: `Σ production_mins / 60`.
- `total_strokes`: sum of entry strokes.
- `spm`: `total_strokes / (prod_time_hrs * 60)` if `prod_time_hrs > 0` else `0`.
- `rejection`: sum of rejection qty.
- `rework`: sum of rework qty.

Totals row:
- each numeric column is summed.
- totals `spm = total_strokes / (total_prod_time_hrs * 60)` (not average of row SPMs).

