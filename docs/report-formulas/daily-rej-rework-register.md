# Daily Rej Rework Register

Source: `daily_rej_rework_register/daily_rej_rework_register.py`

One row per Rejection Breakup line of submitted Production Entries (the standard report scope), replacing
the manual "Daily Rej Rework" Excel register and the old Rework Register / Daily Rework Report pair.

Rows group by `Production Date` into day blocks:

1. a bold **date header** carrying the day's `Total FG Qty for Day` and day-level `No. of
   Operators(working)` / `Time(hrs.)`. These are **day-level** figures: they cover *all* of the day's
   submitted Rework Operations — including items not rejected that day — and do not change when the
   Item / Rejection Reason / Operation filters shrink the lines below,
2. one **item row** per defective item — the item code appears once per day; it carries that item's
   actual same-day rework block (`Rework Qty`, `Rework PPM`, operators, hours, `Responsibility Remark`,
   `Reinspection`) from submitted Rework Operations,
3. the item's rejection lines underneath it (`Rejection Reason`, `Rejection Qty`, `Rej PPM`,
   `Rejection Stage`, `Finished Goods Qty`). A breakup line's qty shows under exactly one quantity
   column: scrap lines under `Rejection Qty`, reworkable (`is_rework`) lines under `Rework Qty` — so
   the reworkable quantity stays visible against its reason. Line `Rework Qty` is the *declared*
   reworkable quantity; the item row's `Rework Qty` is the *actual* same-day rework, and the two differ
   only while declared rework is still pending (see Pending Rework),
4. a bold **subtotal** summing the lines above it: Σ `Rejection Qty` and Σ declared `Rework Qty`, plus
   day-level `Rej PPM` / `Rework PPM` against the day's total FG. The subtotal carries the day-level
   columns (`Total FG Qty for Day`, `No. of Operators(working)`, `Time(hrs.)`) alongside those sums;
   per-item/per-line columns stay blank, and `Finished Goods Qty` is not summed (entry outputs would
   double-count entries with several lines, and entries without rejections are not listed). The
   subtotal reconciles with the lines by construction; it can differ from the item rows' actual rework
   while rework is pending or was executed on items not rejected that day.

## Row values

- `Production Date` = the entry's Completed Shift `shift_date`.
- `Defective Item Code` = the breakup row's Item Code; a blank breakup item resolves to the entry's single
  rejection item (validation forbids blank items when several rejection items exist).
- `Rejection Qty` = the breakup row's qty for scrap (non-reworkable) lines; reworkable (`is_rework`)
  lines show `0` here and carry their qty under `Rework Qty`. `Rejection Reason` = the breakup row's
  reason.
- Line `Rework Qty` = the breakup row's qty for reworkable (`is_rework`) lines; `0` for scrap lines.
  Line `Rework PPM = line Rework Qty / Total FG Qty for Day * 1,000,000`.
- `Rejection Stage` = the resolved report Operation: `stock_entry_type` for Manufacture entries,
  `custom_pea_operation` for Joint entries.
- `Finished Goods Qty` = the entry's output quantity (`fg_completed_qty`; joint gross sums for Joint
  entries), so per-entry values sum to the day total.
- `Total FG Qty for Day` = sum of output quantities of the day's submitted production entries on Completed
  Shifts, including entries with no rejections.
- `Rej PPM = Rejection Qty / Total FG Qty for Day * 1,000,000`; `0` when the day has no production. PPM
  divides raw quantities; only the final value is rounded to system float precision.

## Rework columns (same-day, same-item match)

Rework is not linked back to individual rejections; the register shows against each rejection line whatever
rework happened **on the same item, on the rejection's Production Date** (the rework entry's
`custom_pea_rework_date`), aggregated over that day's submitted Rework Operations:

- `Rework Qty` = sum of the item's reworked qty; `Rework PPM = Rework Qty / Total FG Qty for Day * 1,000,000`.
- `No. of Operators(working)` = distinct operators; `Time(hrs.)` = sum of per-operator
  (Actual End - Actual Start) hours; `Operator Name` = those operators.
- `Responsibility Remark` / `Reinspection` = the rework entries' employee multi-selects, shown as
  employee names (falling back to the Employee ID when no name exists).

Rework done on a later day than the rejection never appears on that rejection's item row — but it does
count in its own execution day's header figures whenever that day has a block. Days with rework but no
rejection lines produce no block: this is a rejection register, and pure-rework days have no lines to
list. Because the rework block lives on the item row, it appears exactly once per day and item, and the
day header and subtotal never double-count rework entries.

## Filters

From/To Date default to the current month. Item, Rejection Reason, and Operation filters restrict rows;
the Operation filter matches the resolved Rejection Stage.

## Dropped with the legacy reports

The legacy reports' Workstation / Operator / Rework Type filters, the Daily REW PPM bar chart, and the
Rework Cost, Rework Entry, Rework Type, and Workstation columns have no equivalent here — the register
keeps exactly the agreed column set. Stored rework cost currently has no report surface.
