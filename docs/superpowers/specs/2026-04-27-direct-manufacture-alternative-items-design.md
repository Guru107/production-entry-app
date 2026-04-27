# Direct Manufacture Alternative Items Design

## Goal

Allow users to select an ERPNext-configured alternative raw material directly on a `Stock Entry` with `purpose = Manufacture` and `from_bom = 1`, without creating a Work Order.

The feature should match ERPNext Work Order behavior where feasible:

- A BOM raw-material row controls whether alternatives are allowed.
- A selected alternative replaces the Stock Entry Detail `item_code`.
- The original BOM item is preserved in `original_item`.
- The row quantity stays unchanged and remains user-editable.
- Existing ERPNext item-alternative configuration is the source of truth.

## Scope

In scope:

- Direct Manufacture Stock Entries fetched from BOM through this app's `custom_fetch_items` flow.
- Raw-material rows only.
- ERPNext v15 and v16 compatibility.
- Reuse of ERPNext's existing `Alternate Item` dialog and item metadata refresh behavior.
- Server-side validation to prevent unauthorized/manual item substitution.
- Tests for fetch behavior and validation behavior.

Out of scope:

- Work Order behavior changes.
- Automatic sheet-dimension or area-based quantity conversion.
- New custom DocTypes or app-specific alternative-item configuration.
- Multi-level BOM alternative selection beyond whatever ERPNext already returns for direct Stock Entry item fetch.

## Current Behavior

ERPNext already supports alternative selection on Stock Entry when item rows have `allow_alternative_item = 1`. The stock entry client adds an `Alternate Item` button and calls `erpnext.utils.select_alternate_items()`.

That utility:

- Lists eligible child rows.
- Lets the user pick an `Item Alternative`.
- Sets the row `item_code` to the alternative item.
- Sets `original_item` to the previous item.
- Keeps the same `qty`.
- Triggers the normal `item_code` handler.

For Work Orders, ERPNext carries `allow_alternative_item` from Work Order required items and uses submitted material-transfer entries to carry selected alternatives into manufacture entries.

This app replaces the standard direct Manufacture fetch button with `production_entry_app.production_entry_app.api.get_items_with_rejection()`. That server method builds a clean Stock Entry, calls ERPNext `get_items()`, applies rejection-row logic, and returns child rows to the browser. Direct Manufacture support should be added at this seam.

## Proposed Design

### Fetch Flow

`get_items_with_rejection()` should preserve ERPNext's alternative-item fields for BOM RM rows:

- `allow_alternative_item`
- `original_item`
- item metadata fields already returned by ERPNext

If ERPNext returns BOM rows with `allow_alternative_item`, the app should pass it through unchanged. If the app's clean-doc fetch path drops or fails to expose that value for direct Manufacture rows, add a small helper that enriches RM rows from the selected BOM's `BOM Item.allow_alternative_item` values.

The helper should be conservative:

- Run only for direct `purpose = Manufacture`, `from_bom = 1`, and no `work_order`.
- Skip finished-good, scrap, and app-created rejection rows.
- Match rows by BOM raw material item code before any alternative is selected.
- Do not override an existing truthy `allow_alternative_item`.

### Client Flow

Reuse ERPNext's native Stock Entry button/dialog.

No custom alternative-item UI should be introduced unless the native button cannot be made reliable for direct Manufacture. If needed, the app can trigger `frm.refresh()` or refresh item rows after `custom_fetch_items` so ERPNext's normal refresh handler sees eligible rows and shows the button.

The app should not fork `erpnext.utils.select_alternate_items()`.

### Validation

Add server-side validation for direct Manufacture Stock Entry rows with alternatives.

For each raw-material row where `original_item` exists and differs from `item_code`:

- Validate the Stock Entry is direct Manufacture (`purpose = Manufacture`, `from_bom = 1`, no `work_order`).
- Validate the original item is present in the selected BOM raw materials.
- Validate the BOM row allows alternative items.
- Validate `Item Alternative` permits the selected item for the original item. Respect ERPNext's two-way alternative behavior by using the same lookup path as ERPNext's `get_alternative_items` query or an equivalent explicit query.
- Throw a translated `frappe.throw()` message if validation fails.

This validation is needed because users can edit child rows directly or API clients can submit modified rows without using the dialog.

### Quantity Behavior

Keep the same row quantity after alternative selection, matching ERPNext Work Order behavior.

Trade-off: sheet-size substitutions may require a different consumed quantity in real production. Automatic dimensional conversion is not implemented because item dimensions and yield rules are not currently modeled in this app. Users can manually edit `qty` after selecting an alternative.

### Rejection Rows

Rejection row logic should remain unchanged.

The finished-good rejection row is not an RM row and must not be marked as alternative-selectable. Validation should ignore app-created rejection rows, identified by existing rejection-row flags.

### Compatibility

The implementation should avoid relying on ERPNext internals that differ heavily between v15 and v16. The durable fields already exist in both versions:

- `Stock Entry Detail.allow_alternative_item`
- `Stock Entry Detail.original_item`
- `BOM Item.allow_alternative_item`
- `Item Alternative`

Tests should run against bench16 first and then bench15 for compatibility.

## Testing Plan

Unit/integration tests:

- `get_items_with_rejection()` returns direct Manufacture RM rows with `allow_alternative_item = 1` when the BOM item permits alternatives.
- Rows without BOM alternative permission are not marked selectable.
- A direct Manufacture Stock Entry with a valid alternative item and `original_item` saves or validates successfully.
- A direct Manufacture Stock Entry with an alternative item but BOM row not allowing alternatives fails validation.
- A direct Manufacture Stock Entry with an item not configured in `Item Alternative` fails validation.
- Rejection rows are not considered alternative RM rows.

Client/unit tests where practical:

- After custom fetch returns an eligible RM row, the row has the field state required for ERPNext's native `Alternate Item` button.

Manual/E2E smoke:

- Create BOM with RM where alternative is allowed.
- Configure `Item Alternative`.
- Create direct Manufacture Stock Entry from BOM.
- Click Fetch Items.
- Use Alternate Item dialog to select substitute RM.
- Confirm row `item_code` changes, `original_item` is retained, qty remains unchanged, and save/submit succeeds when stock is available.

## Risks And Trade-offs

- Reusing ERPNext's native dialog minimizes maintenance but limits UX customization.
- Keeping quantity unchanged matches Work Order behavior but does not solve dimensional conversion automatically.
- Server-side validation adds safety but must avoid rejecting legitimate native Work Order flows; therefore it is scoped to direct Manufacture only.
- Enriching fetched rows from BOM introduces an extra lookup, but the dataset is limited to one BOM and is acceptable for an interactive fetch operation.

## Implementation Boundary

The implementation should be limited to:

- `production_entry_app/production_entry_app/api.py`
- Stock Entry validation hook code if direct validation belongs there
- Existing Stock Entry JS only if the native button does not appear after fetch
- Tests under existing Stock Entry hook/API test modules and JS unit tests if needed

No schema migration or new custom fields should be required.
