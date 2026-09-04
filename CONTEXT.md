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
Operational validation classifies Joint Production from selected Stock Entry Type
`custom_pea_joint_lh_rh_production`; submitted-entry reports use saved Stock Entry header marker
`custom_pea_is_joint_lh_rh`.
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

**Rework Operation**:
A native Material Transfer Stock Entry, using the configured rework Stock Entry Type, that moves successfully
reworked quantity from the Rejection Warehouse to the good warehouse and loads its labour cost onto that stock
through one native additional-cost row. It records the Rework Type, Workstation, actual start/end times, and the
named Operators involved. It is not managed through Shift. When the host does not provide `Stock Entry.branch`,
operators must explicitly set a rejected source warehouse; Company/Branch defaults are applied only when the
host branch field exists. Quantity not reworked stays in the Rejection Warehouse. See ADR 0002.
_Avoid_: Rework entry document type, rework repack

**Rework Type**:
Master data naming the corrective operation performed on rework-flagged parts, such as Deburring. It may name a
default Workstation. It is distinct from a Rejection Reason, which records why a part was rejected.
_Avoid_: Rejection reason, rework reason

**Pending Rework Pool**:
The derived, per-item quantity awaiting rework: rework-flagged quantity from submitted Production Entries minus
quantity consumed by submitted Rework Operations. It is fungible per item — Rework Operations do not attribute
parts back to source entries. Blank-item breakup rows are valid only when the Stock Entry has one rejected Item;
multi-item rejections must name the Item on each breakup row so the pool cannot silently fan out or drop quantity.
Manual scrap write-offs do not drain it, so reports show it beside the actual Rejection Warehouse balance.
_Avoid_: Rework backlog document, rework warehouse balance

**Branch Ownership Handoff**:
Production Entry App owns `Shift.branch` only. The production ERPNext instance owns any `Stock Entry.branch`,
`Stock Entry Detail.branch`, and accounting-dimension branch fields. When a linked Shift is selected, the app
copies `Shift.branch` to `Stock Entry.branch` only if that host-owned field already exists; otherwise it skips
the handoff safely and leaves branch/header-detail synchronization to the production instance.
_Avoid_: App-created Stock Entry Branch field, app-owned detail branch sync, legacy branch-field migration

**Right-First-Time Quality**:
The OEE Quality convention in which rework-flagged quantity counts as a quality loss at production time, in both
normal Manufacture and Joint Production, because the part was not good on its first pass. Rework Operations
themselves are excluded from OEE and utilization.
_Avoid_: Scrap-only quality, mode-specific rework treatment

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
