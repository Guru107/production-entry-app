# Bound app deviations from native Frappe and ERPNext behaviour

Production Entry App runs on the native Stock Entry lifecycle. It does not replace the form, add a
parallel production DocType, or override permissions (#80, #87). It does deviate from native behaviour at
a small number of seams. Each seam is recorded here with its reason so that ERPNext 15 and 16 upgrades can
be checked against one document. ADR 0001 (Repack classification) and ADR 0002 (rework cost) stay
authoritative for their topics; this record covers the remaining seams.

## Stock Entry form (client)

- ERPNext fetches BOM rows as soon as `fg_completed_qty` changes. The app patches
  `erpnext.stock.StockEntry.prototype.fg_completed_qty` to skip that fetch only for Shift-linked direct
  Manufacture entries without a Job Card, so the operator can enter completed and rejection quantities
  before one explicit Fetch Items call. The original method remains the fallback for every other case.
- The native Get Items button is hidden for every purpose and replaced by the app's Fetch Items buttons,
  which add the rejection row and route rejection and scrap to configured warehouses before rows reach
  the form. The native BOM fields (`from_bom`, `bom_no`, `use_multi_level_bom`, `fg_completed_qty`) and
  BOM section are shown only for Manufacture, multi-level BOM stays unchecked, and the native process-loss
  fields are hidden. Plain Repack, Material Transfer for Manufacture and Material Issue therefore have no
  BOM fetch on this site; production entries are single-level BOM stamping operations.
- Switching the Stock Entry Type between the joint type and any other type clears the BOM-derived header
  fields and the Items table. Native handlers never clear rows; the app does because rows fetched in one
  mode are invalid in the other and must be fetched again.
- Joint and rework fields depend on the client-only markers `doc.__pea_joint_stock_entry_type` and
  `doc.__pea_rework_stock_entry_type`, resolved by an async lookup after the form loads. Visibility and
  client mandatory rules are form-only. Server validation (`_validate_joint_header`,
  `_validate_rework_fields`) is authoritative, and print formats or report views do not evaluate the
  markers.

## Joint Production rows and valuation

- Fetch Items for a joint entry does not call native `get_items()`. The app materialises the rows: one
  raw-material row from the additive LH and RH BOM share, LH and RH good and rejection rows, and every
  BOM scrap row (CONTEXT.md "BOM Sheet Capacity", "Whole-number Scrap Boundary"). Rows use the stock UOM
  with conversion factor 1. Native BOM explosion cannot express one raw-material row feeding two BOMs.
- Native Repack prices several finished items at one uniform per-unit rate and requires manual rates
  when more than one finished item is present. The app marks its output rows `set_basic_rate_manually`
  and sets the rates in its `validate` hook, which Frappe runs after the ERPNext controller's
  `validate()`: scrap rows carry the BOM scrap rate; LH and RH rows share the net consumed value (raw
  material minus scrap) weighted by BOM unit cost; then `calculate_rate_and_amount(reset_outgoing_rate=False)`
  lets native code derive amounts, valuation rates, additional-cost distribution and ledgers (#89).
- Save and submit validate the existing rows against the recalculated plan by role and aggregate stock
  quantity, so split, reordered, batched or serialised rows survive while missing, surplus or stale rows
  are rejected with guidance to run Fetch Items again (#82, #89, #90). Ad-hoc rows cannot be added to a
  joint entry.
- Scrap rows carry the native marker of the installed version (`is_scrap_item` on 15,
  `secondary_item_type` on 16), and native classification is preserved (ADR 0001).

## Stock Entry Type flags and the shipped joint type

- Two app Check fields on Stock Entry Type mark the joint (Repack) and rework (Material Transfer) types.
  A `validate` hook on Stock Entry Type enforces the purpose per flag, forbids both flags on one type and
  allows only one joint-flagged type per site, so operational validation and reports classify entries
  from the type alone (CONTEXT.md "Joint Production").
- The app ships the canonical type "Joint LH RH Production" as a fixture. Frappe fixture import deletes
  and re-inserts the record with validation on during every migrate, so edits to the shipped record are
  reset by migrate and flagging a second type makes migrate fail.

## Rework hooks and pool locking

- `before_validate` defaults blank rework sources from the Company/Branch rejection warehouse and rebuilds
  the single app-owned additional-cost row before native validation distributes it (ADR 0002). A hidden
  Check on the shared child DocType Landed Cost Taxes and Charges marks that row.
- `before_submit` validates the route and the Pending Rework Pool inside the submit transaction after
  taking sorted `SELECT ... FOR UPDATE` locks on the affected Item rows and a locking read of the consumed
  side, so concurrent rework submits for one item serialise and cannot over-draw the pool. Native Stock
  Entry submit takes no Item locks. The locking read joins Stock Entry Type, so every rework submit also
  serialises on that row.

## Warehouse and branch defaults

- Fetch Items for direct Manufacture (no Work Order) and for joint entries fills blank header warehouses
  from the Shift or Company/Branch WIP default and routes scrap rows to the configured Scrap Warehouse
  instead of the BOM or Manufacturing Settings scrap warehouse. Work Order flows keep native warehouses
  (CONTEXT.md "Warehouse defaults"). Issue #87 lists warehouse overrides as out of scope; the maintainer
  accepted this bounded exception during PR #79 review.
- Selecting a Shift copies its branch into the host-owned `Stock Entry.branch` only when that field exists
  (CONTEXT.md "Branch Ownership Handoff").

## Lifecycle

- `after_sync` and `after_migrate` move the app-owned Rework Details section behind the installed
  version's opening Stock Entry section by rewriting the Custom Field's `insert_after` directly and
  clearing the DocType cache, because the anchor field differs between ERPNext 15 and 16.
- `Item.custom_pea_strokes_per_unit` was removed without a patch; the die-tool counter adds Total Press
  Strokes directly (#88).

## Considered Options

- Replace the Stock Entry form or add a Joint Production DocType. Rejected (#80, #87): the native
  lifecycle, permissions, batch and serial handling must stay available.
- Drive joint rows through native `get_items()` and BOM explosion. Rejected: one raw-material row must feed
  two BOMs with the additive share, and each scrap item must aggregate across both BOMs before rounding.
- Accept native uniform Repack pricing. Rejected (#89): outputs must follow BOM cost weighting.
- Persist a joint checkbox on Stock Entry. Rejected by the maintainer (PR #79 Round 18): the Stock Entry
  Type flag is the single source of truth.

## Consequences

- App hooks assume Frappe's order: controller `validate()`, then the app `validate` hook, then
  `before_submit`. On ERPNext 16 the controller stamps app scrap rows `valuation_type = "Valuation Rate"`
  and clears `set_basic_rate_manually` before the app hook restores the manual BOM rate. Declaring
  `valuation_type = "Manual"` on those rows is the native channel that makes the controller keep the rate.
- Only one joint-flagged Stock Entry Type may exist. Administrators flag that record rather than create a
  second one, and a site that wants another name changes the fixture, not the record.
- Rework submits contend on Item rows and on the flagged Stock Entry Type row; high rework volume across
  many items still serialises.
- Native BOM fetch is unavailable for non-Manufacture purposes on this site by design.
- Client-only visibility markers mean print formats and report views show app fields regardless of type.
