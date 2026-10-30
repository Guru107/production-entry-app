# Report Formula Conventions

This document defines shared rules used across script reports under `production_entry_app/production_entry_app/report/`.

## Base Data Scope

- All report rows are built from submitted Production Entries:
  - `docstatus = 1`
  - normal entries use `purpose = "Manufacture"`
	- Joint LH/RH entries use `purpose = "Repack"` and the `Joint LH RH Production`
	  Stock Entry Type, which is marked with `custom_pea_joint_lh_rh_production = 1`
- Generic Repack entries are excluded.
- Operational validation classifies Joint LH/RH entries from selected Stock Entry Type
  `custom_pea_joint_lh_rh_production`; reports use the same Stock Entry Type flag for submitted rows.
- Additional report filters (date, shift, workstation, operator, operation, BOM, FG item) restrict row
  inclusion.

## Operation Column and Filter

Reports that show or filter by **Operation** resolve it per Stock Entry via
`get_entry_report_operation()` in `report_utils.py`:

- **Joint LH/RH Production** and **Joint Production** entries use `custom_pea_operation` (the Operation
  link on the Stock Entry).
- **Manufacture** entries use `stock_entry_type` (for example `Shearing`, `Blanking`). The link field is
  not used for grouping or filtering on Manufacture rows.
- The optional **Operation** report filter matches this resolved value, not the raw
  `custom_pea_operation` database field alone.

Reports with an Operation column: Operator Daily SPM Report, Daily Strokes SPM Monitor. Other reports may
expose the Operation filter without an Operation column (efficiency, OEE, item/BOM hotspots).
- From/To Date filters select entries through linked Completed Shifts and `Shift.shift_date`; Stock Entry
  `posting_date` does not determine date-range membership.

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

## PPM Semantics

Normative denominator rule for every Rej / Rew PPM and rework-rate figure in app reports
(ADR 0009; see `docs/adr/0009-rejection-rework-ppm-total-produced-denominator.md`):

- `Rej PPM = rejection qty / total produced qty * 1,000,000`
- `Rework PPM = rework qty / total produced qty * 1,000,000`
- Rework rate percentages (trend reports) use the same base: `rework qty / total produced qty * 100`.

The denominator is always the **total produced quantity for the reporting scope** (day, item, or
period) — never the OK/good quantity. This follows the ASQ PPM and first-pass-yield definitions
and IATF 16949 conventions (see `docs/research/rejection-rework-ppm-denominator.md`). The legacy
Excel register's Rew PPM (rework over finished-good qty) is a local deviation that must not be
copied; reconcile to it with `legacy Rew PPM = standard Rew PPM * (OK qty / total produced qty)`.

"Total produced" keeps the cross-mode meaning used elsewhere in these conventions: normal
Manufacture entries use `fg_completed_qty` (falling back to good + rejected from child rows when
unset); Joint LH/RH and Joint Production entries use their output-slot gross sums. A zero
denominator yields `0`, never an error.

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
- `Avg. OEE = (A + P + Q) / 3`
- `OEE % = (A * P * Q) / 10000`

Planned losses are applied at report-row scope (linked shifts for that row):

- `avl_time_hrs = max(sum(shift_duration for linked Running/Completed shifts in row scope) - linked_shift_planned_loss_hours, 0)`
- Shifts with no linked Stock Entries for that row do not contribute availability.
- Planned losses are **not** included in workstation loss bucket columns; those columns are unplanned-loss buckets only.
