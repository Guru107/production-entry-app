# Production OEE Report

Source: `production_oee_report/production_oee_report.py`

Quality follows the Right-First-Time convention: every rejected part is a quality loss at production time,
including parts marked for rework. Rework Operations do not restore Quality and are excluded from OEE inputs.
The same quantity semantics apply to normal Manufacture and Joint LH/RH Production Entries.

- `day`: linked Completed Shift `shift_date` group key.
- `workstation`: Stock Entry `custom_pea_workstation` group key (`"Unassigned"` fallback).
- `first_shift_strokes`: sum of entry `total_strokes` for rows whose linked shift label is `"1"`.
- `second_shift_strokes`: sum of entry `total_strokes` for rows whose linked shift label is `"2"`.
- `total_strokes`: sum of each entry's authoritative `custom_pea_total_strokes`.
- `quality_total`: part-based gross production total: normal entries use good plus total rejected quantity;
  Joint LH/RH entries use LH gross plus RH gross quantity.
- `rejection`: part-based quality rejection, including rework: normal entries use total rejected quantity;
  Joint LH/RH entries use LH rejection plus RH rejection quantity.
- `std_spm` (OEE Standard SPM): production-time-weighted average of entry rates, matching Shift summary:
  - only entries with `custom_pea_standard_spm > 0` and production minutes `> 0` contribute
  - `std_spm = standard_spm_weighted_sum / production_mins_sum`
  - `standard_spm_weighted_sum += custom_pea_standard_spm * entry_production_minutes`
  - when no entry contributes, `std_spm` is the Workstation `custom_pea_standard_spm` (including downtime-only rows)
- `avl_time_hrs`: on a row with Production Entries, `max(linked_shift_hours - linked_shift_planned_loss_hours, 0)`, where linked shifts are the `custom_pea_shift` values of Stock Entries inside the same `(day, workstation)` row.
  - Shifts with zero linked Stock Entries for that row are excluded from `avl_time_hrs`.
  - On a row with Machine Downtime and no Production Entry, `avl_time_hrs` is the Completed Shifts those Downtime Entries joined, minus their planned Shift losses.
  - Planned Shift loss hours are summed per Shift (overlapping planned rows are not merged).
- `machine_downtime`: uncovered Downtime Entry hours for the row workstation. Each entry is clipped to a Completed Shift on that Production Date. A filled Shift link counts only inside the named Shift. A blank Shift link is clipped to every Completed Shift on that Production Date. Cancelled Downtime Entries are ignored. Minutes that overlap a Production Entry Loss Entry or a planned Shift loss are excluded. Overlapping Downtime Entries count once. Minutes outside the Shift window are excluded. Native stop reasons are not mapped onto Loss Entry buckets.
- `total_loss_time`: `machine_downtime` plus the sum of all merged Production Entry loss-reason hours
  (every `(reason, shift_label)` bucket, whether or not that reason is selected in the filter).
- `running_time`: on a row with Production Entries, `max(avl_time_hrs - total_loss_time, 0)`. On a row with Machine Downtime and no Production Entry, `running_time` is 0, so `stroke_required`, `act_spm`, `productivity_pct`, `quality_pct`, `availability_pct`, `oee_avg_pct`, and `oee_mult_pct` are 0. `machine_downtime` on that row is still only the logged uncovered hours. That row is omitted when the report is filtered by operation. A workstation with neither a Production Entry nor Machine Downtime has no row. Downtime on a Running or Draft Shift does not create one.
- `stroke_required`: `running_time * std_spm * 60`.
- `act_spm`: `total_strokes / (running_time * 60)` if `running_time > 0` else `0`.
- `productivity_pct`: `(act_spm / std_spm) * 100` if `std_spm > 0` else `0`.
- `quality_pct`: `((quality_total - rejection) / quality_total) * 100` if `quality_total > 0` else `0`.
- `availability_pct`: `(running_time / avl_time_hrs) * 100` if `avl_time_hrs > 0` else `0`.
- `oee_avg_pct` (Avg. OEE): `(availability_pct + quality_pct + productivity_pct) / 3`.
- `oee_mult_pct` (OEE %): `(availability_pct * quality_pct * productivity_pct) / 10000`.

Loss reason columns (when the report filter selects Downtime Reason codes):
- Built only from Stock Entry child `Loss Entry` rows on the same `(day, workstation)` row.
- Shift label decides suffix:
  - label `"1"` => `_1st`
  - label `"2"` => `_2nd`
- Overlapping intervals for the same `(reason, shift_label)` are merged to a union before
  hours are shown; different reasons still add separately into `total_loss_time`.
- Duration hours use normalized clock intervals (cross-midnight end `<` start adds 24 hours).
