# ERPNext v15/v16: Operation Costing, Additional Costs, and Rework Patterns

Research date: 2026-09-01. Verified against the `version-15` and `develop` (v16) branches of
https://github.com/frappe/erpnext (files fetched from raw.githubusercontent.com on this date;
line numbers refer to that snapshot) and https://docs.frappe.io/erpnext. No forum sources.

## TL;DR — factual basis for "ride native vs. analytical"

- ERPNext already has a first-class, GL-posting mechanism for loading labor/operation cost onto
  stock valuation: the Stock Entry `additional_costs` child table (Landed Cost Taxes and Charges).
  Any amount placed there is prorated onto the finished/target rows, raises their
  `valuation_rate`, flows into the Stock Ledger value, and posts a balancing GL credit to the
  chosen expense account — no custom GL code needed.
- Native operation costing (Workstation `hour_rate` × Job Card time logs → Work Order
  `actual_operating_cost`) reaches valuation **only** through this same `additional_costs` table,
  auto-populated when the Manufacture Stock Entry is built via *Get Items* (`add_additional_cost`
  in `bom.py`). So "labor cost into valuation via additional_costs" is exactly the native pattern.
- Repack entries support `additional_costs` with **identical** server-side distribution/valuation/GL
  logic to Manufacture (`purpose in ("Repack", "Manufacture")` in every relevant branch). A Repack
  Stock Entry (same item out and in, plus an additional-cost row for rework labor) is therefore a
  fully supported native vehicle for adding rework cost to specific quantities.
- ERPNext has **no end-to-end rework workflow**, but it has one close native pattern: **Corrective
  Job Cards**, whose time-log cost accrues to Work Order `corrective_operation_cost` and can be
  loaded into FG valuation via an additional-cost row (opt-in Manufacturing Setting). It is tied to
  an open Work Order, not to arbitrary already-in-stock quantities. Process Loss and QI rejection
  are write-off / gating mechanisms, not rework.
- Main v15→v16 deltas: big internal refactor (purpose service classes, `StockEntryGLComposer`),
  per-component Workstation costs with per-component expense accounts, Standard Cost valuation
  branch in GL, and `landed_cost_voucher_amount` added to Stock Entry valuation. The public
  document surface (fields `additional_costs`, `additional_cost`, `valuation_rate`, purposes) is
  unchanged, so an app writing documents (not calling private internals) works on both.

## 1. Stock Entry `additional_costs` (Landed Cost Taxes and Charges)

Entry point: `calculate_rate_and_amount()` runs `set_basic_rate()` →
`init_landed_taxes_and_totals(self)` → `distribute_additional_costs()` → `update_valuation_rate()`
(`erpnext/stock/doctype/stock_entry/stock_entry.py`, version-15 ~L1376).

**Distribution** — `distribute_additional_costs()` (version-15 ~L1595; develop ~L916, identical):

- If no row has a `t_warehouse`, the table is cleared (costs need a receiving row to land on).
- `total_additional_costs = sum(base_amount)` of all rows.
- Basis: for `purpose in ("Repack", "Manufacture")` the pool is `sum(basic_amount)` of rows with
  `is_finished_item = 1`; for every other purpose, rows with a `t_warehouse`.
- Each eligible item row gets `d.additional_cost = basic_amount / pool × total_additional_costs`
  (value-proportional, not qty-proportional); ineligible rows get `additional_cost = 0`.
- Scrap rows are excluded automatically (they are not `is_finished_item`).

**Valuation** — `update_valuation_rate()` (version-15 ~L1619):
`d.amount = basic_amount + additional_cost`;
`d.valuation_rate = basic_rate + additional_cost / transfer_qty`. On develop (~L940) the formula
additionally includes `d.landed_cost_voucher_amount` (v16 lets a Landed Cost Voucher target Stock
Entries). The FG `basic_rate` itself comes from `set_basic_rate()` →
`get_basic_rate_for_manufactured_item()` (consumed raw-material cost minus scrap, per unit), so
additional costs sit **on top of** material cost.

**GL posting** — `get_gl_entries()` (version-15 ~L2131):

- `super().get_gl_entries()` (`erpnext/controllers/stock_controller.py`, version-15 ~L603) posts the
  perpetual-inventory pair per SLE: **Dr warehouse (stock) account** for `stock_value_difference`
  (which already includes the additional cost, because `valuation_rate` was raised) with the
  balancing line against the item row's `expense_account` as a negative debit.
- The Stock Entry override then builds `item_account_wise_additional_cost` — per (item row ×
  additional-cost row `expense_account`), pro-rata by `basic_amount` (falling back to qty-based
  split when total basic amount is 0) — and appends, per bucket:
  - **Credit** the additional-cost row's `expense_account` (e.g. an operating-cost account),
  - a balancing **negative credit** on the item row's `expense_account` (the stock
    adjustment/difference account), with an explicit code comment "put it as negative credit
    instead of debit purposefully".
- Net effect: **Dr Stock in Hand / Cr operating-expense account** for the additional cost —
  i.e. cost is capitalized into inventory and relieved from P&L expense.
- On develop this logic moved verbatim into
  `erpnext/stock/doctype/stock_entry/services/gl_composer.py` (`StockEntryGLComposer.compose`,
  `_build_additional_cost_per_item_account` ~L185, `_append_additional_cost_gl_entries` ~L215),
  with one new branch: items with valuation method "Standard Cost" post the balancing side as a
  positive **debit** to the item's expense account (variance stays in P&L) instead of the negative
  credit.

Default expense account when ERPNext populates rows itself: Company
`default_operating_cost_account`, falling back to `expenses_included_in_valuation`
(`add_additional_cost`, `erpnext/manufacturing/doctype/bom/bom.py`, version-15 ~L1319).
Currency handling (`amount` vs `base_amount`, `exchange_rate`) is initialized by
`init_landed_taxes_and_totals` (`erpnext/controllers/taxes_and_totals.py`).

## 2. Job Card / Work Order operation costing → FG valuation

**Hour rate source.** Workstation `hour_rate`; on version-15 it is computed as
`hour_rate_labour + hour_rate_electricity + hour_rate_consumable + hour_rate_rent`
(`workstation.py::set_hour_rate`, version-15 ~L86). On develop it is the sum of `Workstation Cost`
child rows (`operating_component`, `operating_cost`) (`workstation.py`, develop ~L110). Work Order
operations that lack an `hour_rate` pull it via `get_hour_rate(workstation)`
(`work_order.py`, version-15 ~L348, ~L1985). BOM Operation carries its own `hour_rate` for planned
cost; the Workstation rate wins for actuals.

**Time → cost.** Job Card time logs (`from_time`/`to_time` per employee row) sum to
`total_time_in_mins`. On Job Card submit/cancel, `update_work_order_data()`
(`job_card.py`, version-15 ~L824) aggregates all submitted non-corrective Job Cards for the
operation (`get_current_operation_data`, ~L862) and writes `completed_qty`, `process_loss_qty` and
`actual_operation_time` onto the matching Work Order Operation row, updating `hour_rate` from the
(possibly changed) workstation, then calls `wo.calculate_operating_cost()`
(`work_order.py`, version-15 ~L344): per operation,
`planned_operating_cost = hour_rate × time_in_mins/60` and
`actual_operating_cost = hour_rate × actual_operation_time/60`;
`total_operating_cost = additional_operating_cost + (actual or planned) + corrective_operation_cost`.

**Into the Stock Entry.** When *Get Items* builds a Manufacture entry, `get_items()` calls
`add_additional_cost(stock_entry, work_order)` (`stock_entry.py`, version-15 ~L2697 →
`bom.py` ~L1319), which appends `additional_costs` rows for:

- **Non-stock BOM items** cost (`add_non_stock_items_cost`);
- **Operations cost** (`add_operations_cost`, `bom.py` ~L1343): one row per Work Order operation.
  For operations with `completed_qty` it uses `actual_operating_cost` minus what earlier partial
  Manufacture entries already consumed (`get_consumed_operating_cost`, `stock_entry.py` ~L3792 —
  tracked via `has_operating_cost` / `operation_id` / `qty` columns on Landed Cost Taxes and
  Charges), prorated over remaining qty; otherwise `planned_operating_cost / wo.qty ×
  fg_completed_qty`. Without operations it falls back to `get_operating_cost_per_unit()`
  (~L3819), which ultimately falls back to BOM `operating_cost / quantity`.
- **Additional operating cost** from the Work Order, prorated per unit;
- **Corrective operation cost** (see §4), if the Manufacturing Setting is enabled.

From there the rows are ordinary additional costs: §1's distribution/valuation/GL applies, so
labor lands in the FG `valuation_rate` and posts Dr Stock / Cr operating-cost account. Note the
auto-population happens **client-initiated** (Get Items); a Stock Entry created purely server-side
must call `add_additional_cost()` itself or append rows manually.

## 3. Repack and `additional_costs`

Yes — identical to Manufacture on the server. Every purpose-conditional branch groups them:
`distribute_additional_costs()` and `get_gl_entries()` both use
`self.purpose in ("Repack", "Manufacture")` with distribution to `is_finished_item` rows
(version-15 ~L1602, ~L2134); `set_scrap_items`, `set_process_loss_qty` and
`load_items_from_bom` also cover both. `set_basic_rate()` gives Repack FG rows
`get_basic_rate_for_repacked_items()` (consumed source-row cost spread over finished qty,
version-15 ~L1411) before additional costs are layered on. The UI shows the Additional Costs
section for every purpose **except Material Issue**
(`stock_entry.js`, version-15 ~L1522: `toggle_display(..., doc.purpose != "Material Issue")`);
the DocType JSON puts no `depends_on` on the section. The only Manufacture-specific parts are the
auto-population from a Work Order (§2) and the one-Manufacture-per-WO validation — for a
BOM-less Repack the user (or code) adds `additional_costs` rows manually and everything else
(distribution, `valuation_rate`, GL) works the same. Rows on a Repack must have
`is_finished_item = 1` on the receiving item(s) or the cost pool is empty and nothing distributes.

## 4. Native rework/reprocessing patterns — honest inventory

There is **no end-to-end "rework order" workflow** in ERPNext v15/v16 (no document that takes
rejected finished stock, tracks a rework operation on it, and revalues it). What exists:

- **Corrective Job Card** — the closest native rework concept. `make_corrective_job_card()`
  (`job_card.py`, version-15 ~L1296) maps a Job Card to a new one with
  `is_corrective_job_card = 1` against an Operation flagged `is_corrective_operation`
  ([Job Card docs](https://docs.frappe.io/erpnext/user/manual/en/job-card)). On submit,
  `update_corrective_in_work_order()` (~L794) recomputes Work Order
  `corrective_operation_cost = Σ (total_time_in_mins/60 × hour_rate)` over all corrective Job
  Cards. If Manufacturing Settings `add_corrective_operation_cost_in_finished_good_valuation` is
  on, `add_operations_cost` appends a `has_corrective_cost = 1` additional-cost row to the
  Manufacture entry (`bom.py`, version-15 ~L1420-1455), so the rework labor enters FG valuation.
  Limitations: bound to a still-open Work Order and its operations; not usable for stock that
  finished production earlier; qty basis is operation completed qty, not a "rework batch".
- **Process Loss** — a write-off, not rework. Job Card `process_loss_qty`
  (`set_process_loss` = for_quantity − completed_qty, `job_card.py` ~L756) flows to the Work Order
  operation and to Stock Entry `process_loss_qty` (`set_process_loss_qty`, `stock_entry.py`
  version-15 ~L2718; BOM `process_loss_percentage` fallback). The FG row qty becomes
  `fg_completed_qty − process_loss_qty` (~L762) while absorbing the full consumed cost — lost
  units simply inflate the good units' rate. No stock is produced for the loss.
- **Quality Inspection** — a gate, not a flow. Job Cards link a QI; on develop a rejected QI can
  block submission per Stock Settings `action_if_quality_inspection_is_rejected`
  (`job_card.py`, develop ~L870-901). No native movement of rejected qty to a rework/rejection
  warehouse for manufacture (that exists only for Purchase Receipt `rejected_warehouse`).
- **Disassemble purpose** — present on both branches (`stock_entry.json` purpose options; on
  version-15 handled inline, e.g. `get_items_for_disassembly`, on develop via
  `services/disassemble.py::DisassembleStockEntry`). It reverses a Manufacture entry
  (`source_stock_entry`) back into components — an inventory un-build, not a costed rework step.
- Also of note: `set_basic_rate_manually` per item row and manual `additional_costs` rows are
  supported levers on any Repack/Manufacture entry — the ingredients for a custom rework entry
  without touching valuation internals.

## 5. version-15 vs develop (v16) differences that matter

1. **Massive internal refactor on develop.** Stock Entry logic moved into purpose service classes
   (`services/manufacturing.py`, `disassemble.py`, `gl_composer.py`, ...); BOM cost helpers moved
   to `manufacturing/doctype/bom/services/operations_cost.py`. Public behavior of
   distribution/valuation is unchanged, but any app importing private functions (e.g.
   `erpnext.manufacturing.doctype.bom.bom.add_additional_cost` still re-exported, or
   monkey-patching `StockEntry.get_gl_entries`) must verify both import paths/hooks. Document-level
   integration (create Stock Entry with `additional_costs` rows and submit) is version-stable.
2. **Workstation cost components** (develop): `Workstation Cost` child table replaces the four
   fixed `hour_rate_*` fields; `add_operating_cost_component_wise` writes one additional-cost row
   per component with a per-component expense account (`operations_cost.py`, develop ~L72-144,
   new `operating_component` column on Landed Cost Taxes and Charges).
3. **Standard Cost valuation** (develop): `StockEntryGLComposer` posts additional-cost balancing
   entries as a debit (variance in P&L) for Standard Cost items and adds variance GL entries;
   v15 has no Standard Cost method.
4. **`landed_cost_voucher_amount`** on Stock Entry Detail enters `update_valuation_rate()` on
   develop only.
5. **Purpose list** grew on develop (Receive from Customer, Subcontracting Delivery/Return, ...);
   `Disassemble` exists on both.
6. **QI enforcement on Job Cards** (develop, §4) and `job_card` parameter threaded through
   `add_additional_cost` for per-job-card manufacture entries (develop `track_semi_finished_goods`
   flow) — v15 populates operation costs only per Work Order.
