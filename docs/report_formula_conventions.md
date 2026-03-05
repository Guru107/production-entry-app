# Report Formula Conventions

This document defines shared rules used across script reports under `production_entry_app/production_entry_app/report/`.

## Base Data Scope

- All report rows are built from submitted Manufacture Stock Entries:
  - `docstatus = 1`
  - `purpose = "Manufacture"`
- Additional report filters (date, shift, workstation, operator, BOM, FG item) restrict row inclusion.

## Quantity Semantics

- `fg_completed_qty` is treated as total strokes (OK + rejection) when it is `> 0`.
- If `fg_completed_qty <= 0`, fallback reconstruction is used:
  - `total_strokes = good_qty_map + rejection_qty`
- `rejection_qty` fallback:
  - use `custom_rejection_qty` when `> 0`
  - else aggregate from `Stock Entry Detail` rejection rows
- `rework_qty` fallback:
  - use `custom_rework_qty` when `> 0`
  - else aggregate from `Rejection Breakup` rows where `is_rework = 1`

## Time Semantics

- `custom_actual_duration_mins` = wall-clock interval duration.
- `custom_production_time_mins` = effective production time after loss deductions.
- Preferred denominator for SPM-style metrics is `custom_production_time_mins` when present.
- Shared fallback for production minutes:
  1. If `custom_production_time_mins is not None`, use `max(custom_production_time_mins, 0)`.
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
- `Quality (Q) = (total_strokes - rejection) / total_strokes * 100`
- `OEE = (A + P + Q) / 3`
- `OEE Mult % = (A * P * Q) / 10000`

Planned losses are applied as a day-level global pool:

- `avl_time_hrs = max(sum(shift_duration for linked Running/Completed shifts in row scope) - linked_shift_planned_loss_hours, 0)`
- Planned losses are **not** included in workstation loss bucket columns; those columns are unplanned-loss buckets only.
