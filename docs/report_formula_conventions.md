# Report Formula Conventions

This document defines shared rules used across script reports under `production_entry_app/production_entry_app/report/`.

## Base Data Scope

- All report rows are built from submitted Production Entries:
  - `docstatus = 1`
  - normal entries use `purpose = "Manufacture"`
  - Joint LH/RH entries use `purpose = "Repack"` and `custom_pea_is_joint_lh_rh = 1`
- Generic Repack entries are excluded.
- Additional report filters (date, shift, workstation, operator, BOM, FG item) restrict row inclusion.
- From/To Date filters select entries through linked Completed Shifts and `Shift.shift_date`; Stock Entry
  `posting_date` does not determine date-range membership.
- Rework Register is the exception to this Production Entry scope: it selects submitted Rework Operations and
  uses their `posting_date`, because Rework Operations are not linked to a Shift.

## Quantity Semantics

- `custom_pea_total_strokes` is the sole source for physical stroke counts in normal and Joint
  Production Entries.
- Good, rejection, and rework quantities remain part quantities derived from Stock Entry Detail and
  Rejection Breakup rows; they are not inferred from strokes.
- `rejection_qty` fallback:
  - use `custom_pea_rejection_qty` when `> 0`
  - else aggregate from `Stock Entry Detail` rejection rows
- `rework_qty` fallback:
  - use `custom_pea_rework_qty` when `> 0`
  - else aggregate from `Rejection Breakup` rows where `is_rework = 1`

## Time Semantics

- `custom_pea_actual_duration_mins` = wall-clock interval duration.
- `custom_pea_production_time_mins` = effective production time after loss deductions.
- Preferred denominator for SPM-style metrics is `custom_pea_production_time_mins` when present.
- Shared fallback for production minutes:
  1. If `custom_pea_production_time_mins is not None`, use `max(custom_pea_production_time_mins, 0)`.
  2. Else compute `max(actual_duration_mins - setup_mins - loss_mins, 0)`.
  3. `actual_duration_mins` itself falls back to datetime delta if required.

## Loss Semantics

- Unplanned losses for reports come from `Loss Entry` rows under `Stock Entry` (`parenttype = "Stock Entry"`).
- `Setup Time` is tracked separately from other losses in some reports.
- For cross-midnight loss intervals, duration is normalized by adding 24 hours when `end < start`.

## OEE Semantics

Production OEE Report uses:

- `Availability (A) = running_time / avl_time_hrs * 100`
- `Productivity (P) = act_spm / std_spm * 100`
- `Quality (Q) = (quality_total - quality_rejection) / quality_total * 100`
- For normal Manufacture entries, `quality_total = good_qty + total_rejected_qty` and
  `quality_rejection = total_rejected_qty`, including rework.
- For Joint LH/RH entries, `quality_total = LH gross qty + RH gross qty` and
  `quality_rejection = LH rejection qty + RH rejection qty`, including rework.
- `OEE % = (A * P * Q) / 10000`

Planned losses are applied at report-row scope (linked shifts for that row):

- `avl_time_hrs = max(sum(shift_duration for linked Running/Completed shifts in row scope) - linked_shift_planned_loss_hours, 0)`
- Shifts with no linked Stock Entries for that row do not contribute availability.
- Planned losses are **not** included in workstation loss bucket columns; those columns are unplanned-loss buckets only.
