# Production Entry

This context records physical production performed during a Shift, including material consumption,
outputs, quality quantities, elapsed time, losses, and press strokes.

## Language

**Production Entry**:
A record of one physical production operation and its material, output, quality, time, loss, and stroke facts.
_Avoid_: Manufacturing entry, operation entry

**Joint Production**:
One physical stamping operation that consumes common raw material and produces paired LH and RH outputs while
tracking each side's gross quantity and rejection quantity separately.
_Avoid_: Combined production, dual production

**Total Press Strokes**:
The authoritative number of physical strokes performed by the die tool during a Production Entry. It is entered
on the Production Entry and may differ from the quantity produced because one stroke may produce multiple parts.
_Avoid_: Derived stroke count, produced quantity

**BOM Sheet Capacity**:
The BOM quantity is the maximum total number of parts that can be produced from the raw-material quantity recorded
in that BOM. In Joint Production, each side consumes its proportional share of raw material, and the LH and RH
shares are added: `side gross quantity x BOM raw-material quantity / BOM quantity`.
_Avoid_: Per-side sheet count, shared maximum consumption

**Whole-number Scrap Boundary**:
Joint Production aggregates scrap by item before rounding whole-number UOMs with half-up rounding. A positive
aggregate below `0.5` rounds to zero and is omitted because native Stock Entry rows cannot represent zero quantity;
its calculated value remains allocated to the joint outputs. For a positive rounded quantity, the rate is
recalculated so the pre-round aggregate scrap value is preserved.
_Avoid_: Per-side rounding, zero-quantity scrap row

**Production Date**:
The `shift_date` of the Completed Shift to which a submitted Production Entry belongs. Operational reports use
this date for range membership and period grouping, regardless of the Stock Entry posting date.
_Avoid_: Posting date, transaction date

**Production Date Range**:
An inclusive From Date and To Date that selects Completed Shifts by Production Date and, through them, their
submitted Production Entries. Entries without a Shift and entries belonging to non-Completed Shifts are excluded.
_Avoid_: Posting-date range, entry-date range

## Warehouse defaults

Production Entry Settings holds one warehouse-default row per Company and Branch. A Shift's explicit
warehouse values take precedence over its matching settings row; there is no global fallback. New Shifts
copy only missing values. Existing Shifts keep their chosen warehouses when settings change.

Production consumption defaults to WIP, not the Raw Material Warehouse. Both Fetch Items flows preserve
explicit source/target headers, route rejection to the Rejection Warehouse and scrap to the Scrap Warehouse,
and fail clearly when a required destination is missing. Every configured warehouse must belong to the
selected Company. Work Order-backed flows, including those linked to a Shift, keep ERPNext's native
warehouse configuration. Fetch Items does not introduce a save/submit override of manually selected row
warehouses. Selecting a Shift without WIP still supplies company, branch and dates; missing warehouses
are required only when fetching rows that need them. Raw Material Warehouse remains Shift context;
production consumes from WIP, not directly from the Raw Material Warehouse.

The trade-off is explicit branch setup instead of a convenient but unsafe global fallback. Small, indexed
settings lookups are resolved per request, avoiding stale cached defaults and historical data rewrites.
