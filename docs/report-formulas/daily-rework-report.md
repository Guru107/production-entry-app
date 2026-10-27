# Daily Rework Report

Source: `daily_rework_report/daily_rework_report.py`

Date-grouped register of submitted Rework Operations (Stock Entries whose Stock Entry Type is marked as a
Rework Entry), replacing the manual "PRESS SHOP REJ REW PPM" Excel log. Like the Rework Register, rows are
selected by Stock Entry `posting_date` — Rework Operations are not linked to a Shift.

Each date renders as a block of:

1. A **date header** row carrying:
   - `No. of Man = count(distinct operators across the day's rework entries)`
   - `Rework Hours = sum of the day's per-entry hours`
2. One row per rework entry: `Items + Qty`, `Total Qty = sum(Stock Entry Detail qty)`, `Rework Type`,
   `Workstation`, `Operators`, and
   `Rework Hours = sum over Rework Operator rows of (Actual End - Actual Start) / 3600`.
3. A **subtotal** row: day `Total Qty`, day `Rework Hours`, day `No. of Man`, and `Daily REW PPM`.

## Daily REW PPM

- `Daily REW PPM = (day reworked qty / day total production) * 1,000,000`; `0` when the day has no
  production.
- Day reworked qty = the subtotal `Total Qty` of the day's listed rework entries.
- Day total production = sum of output quantities of submitted production entries (purpose `Manufacture`
  plus the joint `Repack` types) linked to Completed Shifts with `shift_date` on that day. Manufacture
  entries contribute `fg_completed_qty`; joint entries contribute their gross output quantities
  (`custom_pea_lh_gross_qty + custom_pea_rh_gross_qty`, or Joint Production Line `gross_qty` sums).

**Caveat — execution date vs declaration date:** this report counts rework at its *execution* date (the
rework entry's `posting_date`). The Rework PPM Report counts rework at its *declaration* day (the production
day of the entry that declared the reworkable quantity). Both count the same quantities; rework executed on
a later day than declared lands on different days in the two reports.

## Filters and chart

From/To Date default to the current month. Item, Workstation, Operator, and
Rework Type filters restrict which rework entries are listed; the PPM denominator always covers the day's
whole completed production. The chart plots `Daily REW PPM` per day as a bar series.
