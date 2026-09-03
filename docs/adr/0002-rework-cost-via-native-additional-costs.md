# Record rework cost through native additional costs on a Material Transfer

A Rework Operation is a native Stock Entry using a user-configured Stock Entry Type whose purpose is
Material Transfer. It moves only successfully reworked quantity from the Rejection Warehouse to the good
warehouse. The app computes rework cost as `duration hours x operator count x Workstation hour_rate` and
records it as one `additional_costs` row; ERPNext's native distribution, valuation, Stock Ledger, and
General Ledger behaviour then apply unchanged. Quantity that is not reworked stays in the Rejection
Warehouse, and its eventual write-off is a separate manual Repack to the scrap Item, outside this app.

## Considered Options

- A dedicated Rework Operation DocType that generates Stock Entries. Rejected because the native Stock
  Entry already carries the lifecycle, and a wrapper document would duplicate submission, cancellation,
  and valuation semantics.
- Purpose Repack with finished and scrap rows, so failed rework could be scrapped in the same document.
  Rejected once rework entries were limited to successful quantity only: with equal quantity in and out,
  the same item on both sides, and no scrap rows, Material Transfer expresses the operation exactly and
  never enters Repack finished-item/scrap classification territory (see ADR 0001).
- Analytical-only cost that never touches valuation or GL. Rejected because loading labour cost onto the
  reworked stock is the stated requirement, and `additional_costs` is the native channel for it: ERPNext
  itself converts Workstation labour into finished-goods valuation through the same table.
- Operator-multiplied component rates (`hour_rate_labour` per operator plus machine components once).
  Rejected for now in favour of the net `hour_rate` multiplied by operator count, which behaves
  identically on Frappe/ERPNext v15 and v16 and matches how the plant quotes rework labour.

## Consequences

The app writes exactly one additional-cost row per rework entry and never re-implements distribution,
valuation, or GL posting. The expense account defaults to the Company `default_operating_cost_account`
and may be overridden in Production Entry Settings. The Pending Rework pool is derived per item as
rework-flagged quantity from submitted Production Entries minus submitted rework-entry quantity; because
manual scrap Repacks do not drain it, pending-rework reporting must show the derived pool beside the
actual Rejection Warehouse balance rather than presenting the pool as physical stock on hand.
