# Production Entry App Enhancement - Complete Specification

## Context

The Production Entry App currently manages Shifts with planned losses, warehouse defaults, and downtime tracking. This enhancement integrates the Shift document with ERPNext's Stock Entry to enable a supervisor-driven production entry workflow: create a manufacturing Stock Entry directly from a Shift, auto-populate warehouse/date/operation fields, track unplanned losses, and handle rejection quantities.

### Assumptions & Corrections
- Requirements list `custom_planned_start_date` twice in Operation Details; the second is `custom_planned_end_date` (based on description "Shift Planned end date time")
- `custom_planned_start_date` and `custom_planned_end_date` on Stock Entry are stated as "already available" but don't exist in the current Stock Entry schema or this app's fixtures - we will create them as custom fields
- ERPNext Workstation has no SPM field - we will add `custom_standard_spm` as a custom field on Workstation

---

## Phase 1: Downtime Reason DocType & Loss Entry Refactor

**Goal**: Replace Loss Type with Downtime Reason, update Loss Entry child table, update all references.

### 1.1 Create Downtime Reason DocType

**Directory**: `production_entry_app/production_entry_app/doctype/downtime_reason/`

**Files**: `__init__.py`, `downtime_reason.json`, `downtime_reason.py`, `test_downtime_reason.py`

**Schema (`downtime_reason.json`)**:
| Field | Type | Properties |
|-------|------|------------|
| `downtime_reason_name` | Data | required, unique, in_list_view, title_field |

- `autoname`: `field:downtime_reason_name`
- `allow_rename`: true
- Permissions: System Manager, Manufacturing User, Manufacturing Manager (full CRUD)

### 1.2 Modify Loss Entry Child Table

**File**: `production_entry_app/production_entry_app/doctype/loss_entry/loss_entry.json`

**Changes**:
- Rename field `loss_type` → `downtime_reason`, change options from `Loss Type` → `Downtime Reason`, update label to `Downtime Reason`
- Add field `remark` (Small Text, optional, in_list_view)

**Updated field_order**: `["downtime_reason", "start_time", "end_time", "remark"]`

### 1.3 Update Shift Controller (`shift.py`)

- `_populate_planned_losses()`: Change `"loss_type"` keys to `"downtime_reason"` in all entry dicts
- `get_planned_losses_for_duration()`: Change return dict key from `loss_type` to `downtime_reason`
- `_planned_losses_changed()`: Change `getattr(row, "loss_type", None)` to `getattr(row, "downtime_reason", None)`

### 1.4 Update Fixtures

- **Delete** `fixtures/loss_type.json`
- **Create** `fixtures/downtime_reason.json`:
  ```json
  [
    {"doctype": "Downtime Reason", "downtime_reason_name": "Tea Break"},
    {"doctype": "Downtime Reason", "downtime_reason_name": "Lunch Break"}
  ]
  ```
- **Update** `hooks.py`: Replace `"Loss Type"` with `"Downtime Reason"` in fixtures list

### 1.5 Delete Loss Type DocType

**Remove entire directory**: `production_entry_app/production_entry_app/doctype/loss_type/`

### 1.6 Update Tests

**`test_shift.py`**:
- Rename `_ensure_loss_types()` → `_ensure_downtime_reasons()`, create Downtime Reason records instead
- Update all assertions: `tea.loss_type` → `tea.downtime_reason`, `lunch.loss_type` → `lunch.downtime_reason`
- Rename `test_manufacturing_user_can_crud_loss_type` → `test_manufacturing_user_can_crud_downtime_reason`

**`test_downtime_reason.py`** (new):
- `test_mandatory_fields` - downtime_reason_name required
- `test_autoname_uses_downtime_reason_name` - name equals field value
- `test_duplicate_name_rejected` - unique constraint enforced

---

## Phase 2: Operator DocType

**Directory**: `production_entry_app/production_entry_app/doctype/operator/`

**Files**: `__init__.py`, `operator.json`, `operator.py`, `test_operator.py`

**Schema (`operator.json`)**:
| Field | Type | Properties |
|-------|------|------------|
| `operator_name` | Data | required, unique, in_list_view, title_field |
| `is_active` | Check | default: 1, in_list_view |

- `autoname`: `field:operator_name`
- `allow_rename`: true
- Permissions: System Manager, Manufacturing User, Manufacturing Manager (full CRUD)

**Tests (`test_operator.py`)**:
- `test_mandatory_fields` - operator_name required
- `test_autoname_uses_operator_name` - name matches field
- `test_is_active_defaults_to_true` - default check value
- `test_duplicate_name_rejected` - unique constraint

---

## Phase 3: Add Branch Field to Shift

**File**: `production_entry_app/production_entry_app/doctype/shift/shift.json`

Add `branch` field (Link to `Branch` DocType) after `supervisor` in the Warehouse Defaults section.

| Field | Type | Properties |
|-------|------|------------|
| `branch` | Link | options: Branch, optional |

**Tests** (in `test_shift.py`):
- `test_branch_field_can_be_set` - create shift with branch, verify persistence
- `test_branch_field_is_optional` - create shift without branch, no error

---

## Phase 4: Custom Fields on Stock Entry, Stock Entry Detail, and Workstation

All custom fields defined in `fixtures/custom_field.json`, following existing naming pattern `{DocType}-{fieldname}`.

### 4.1 Stock Entry Custom Fields

**Shift Reference (after `stock_entry_type`)**:
| Field | Type | Properties |
|-------|------|------------|
| `custom_shift` | Link | options: Shift, after stock_entry_type, optional, editable |

**Operation Details Tab (new tab on Stock Entry form)**:
| Field | Type | Properties |
|-------|------|------------|
| `custom_operation_details_tab` | Tab Break | label: "Operation Details" |
| `custom_operation_details_section` | Section Break | label: "Planned & Actual Dates" |
| `custom_planned_start_date` | Datetime | label: "Planned Start Date", read_only |
| `custom_planned_end_date` | Datetime | label: "Planned End Date", read_only |
| `custom_operation_details_col_break` | Column Break | - |
| `custom_actual_start_date` | Datetime | label: "Actual Start Date" |
| `custom_actual_end_date` | Datetime | label: "Actual End Date" |
| `custom_workstation_operator_section` | Section Break | label: "Workstation & Operator" |
| `custom_workstation` | Link | options: Workstation |
| `custom_standard_spm` | Float | label: "Standard SPM", read_only, fetch_from: custom_workstation.custom_standard_spm |
| `custom_workstation_operator_col_break` | Column Break | - |
| `custom_operator` | Link | options: Operator |

**Unplanned Loss Section (in the Operation Details tab)**:
| Field | Type | Properties |
|-------|------|------------|
| `custom_unplanned_losses_section` | Section Break | label: "Unplanned Losses" |
| `custom_unplanned_losses` | Table | options: Loss Entry |

**Rejection Quantity (after `fg_completed_qty`)**:
| Field | Type | Properties |
|-------|------|------------|
| `custom_rejection_qty` | Float | label: "Rejection Quantity", description: "Deducted from FG qty; moved to rejection warehouse" |

### 4.2 Stock Entry Detail Custom Field

| Field | Type | Properties |
|-------|------|------------|
| `custom_is_rejection_item` | Check | hidden, read_only, after is_scrap_item |

Used internally to mark rejection rows for idempotent re-save handling.

### 4.3 Workstation Custom Field

| Field | Type | Properties |
|-------|------|------------|
| `custom_standard_spm` | Float | label: "Standard SPM", after hour_rate |

---

## Phase 5: Server-Side Hooks

### 5.1 Whitelisted API

**File**: `production_entry_app/production_entry_app/api.py` (new)

**`get_shift_details_for_stock_entry(shift_name)`** - Returns:
```python
{
    "branch": shift.branch,
    "custom_planned_start_date": datetime(shift_date + planned_start_time),
    "custom_planned_end_date": datetime(shift_end_date + planned_end_time),
    "from_warehouse": shift.work_in_progress_warehouse,
    "to_warehouse": shift.work_in_progress_warehouse,
}
```

### 5.2 Stock Entry Validate Hook

**File**: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py` (new)

**`validate_stock_entry(doc, method)`**:
1. If `doc.custom_shift` is set → call `_apply_shift_defaults(doc)`:
   - Set `custom_branch` from shift.branch
   - Combine shift_date + planned_start_time → `custom_planned_start_date` (DateTime)
   - Combine shift_end_date + planned_end_time → `custom_planned_end_date` (DateTime)
   - Set `from_warehouse` and `to_warehouse` = shift.work_in_progress_warehouse

2. If `doc.custom_rejection_qty > 0` → call `_apply_rejection_entries(doc)`:
   - Remove any existing rows where `custom_is_rejection_item == 1`
   - Restore FG row original qty (FG qty + previously deducted rejection)
   - Validate rejection_qty <= FG qty
   - Deduct rejection_qty from FG row
   - Append new item row cloned from FG with:
     - `qty` = rejection_qty
     - `t_warehouse` = rejection warehouse (from shift or Manufacturing Settings)
     - `custom_is_rejection_item` = 1
     - `is_finished_item` = 0

### 5.3 hooks.py Updates

```python
doc_events = {
    "Stock Entry": {
        "validate": "production_entry_app.production_entry_app.overrides.stock_entry_hooks.validate_stock_entry",
    }
}

doctype_js = {
    "Stock Entry": "public/js/stock_entry.js"
}

fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "Production Entry App"]]},
    "Downtime Reason",
]
```

### 5.4 Tests

**File**: `production_entry_app/production_entry_app/tests/test_stock_entry_hooks.py` (new)

- `test_shift_reference_auto_fills_branch`
- `test_shift_reference_auto_fills_planned_dates`
- `test_shift_reference_auto_fills_warehouses`
- `test_rejection_qty_deducts_from_finished_good`
- `test_rejection_qty_creates_rejection_row`
- `test_rejection_qty_exceeding_fg_throws_error`
- `test_rejection_row_is_idempotent_on_resave`
- `test_rejection_qty_zero_produces_no_rejection_row`
- `test_unplanned_losses_can_be_added_to_stock_entry`

---

## Phase 6: Client-Side Script for Stock Entry

**File**: `production_entry_app/public/js/stock_entry.js` (new)

**Behavior on `custom_shift` change**:
- If set: Call `get_shift_details_for_stock_entry` API, populate `custom_branch`, `custom_planned_start_date`, `custom_planned_end_date`, `from_warehouse`, `to_warehouse`
- If cleared: Clear all auto-filled fields

**Registered via** `doctype_js` in hooks.py.

---

## Phase 7: "Create Production Entry" Button on Shift

**File**: `production_entry_app/production_entry_app/doctype/shift/shift.js`

Add to the `refresh` handler alongside existing "Downtime Entry" button:

```javascript
frm.add_custom_button(
    __("Production Entry"),
    function () {
        frappe.new_doc("Stock Entry", {
            stock_entry_type: "Manufacture",
            custom_shift: frm.doc.name,
        });
    },
    __("Create")
);
```

Only shown when document is saved (`!frm.doc.__islocal`).

---

## Phase 8: Rejection Mechanism (Detail)

### Flow
1. User creates Stock Entry (Manufacture), links Shift, sets BOM + `fg_completed_qty`
2. Clicks "Get Items" → items populated from BOM
3. User sets `custom_rejection_qty` (e.g., 5 out of 100)
4. On save → validate hook:
   - Finds finished good row (`is_finished_item == 1`)
   - Deducts: FG qty becomes 95
   - Adds rejection row: qty=5, t_warehouse=rejection_warehouse, `custom_is_rejection_item=1`

### Idempotency
On re-save, the hook first removes existing rejection rows (identified by `custom_is_rejection_item == 1`), restores FG qty, then re-applies. This prevents duplicate rows.

### Rejection Warehouse Resolution
1. First: linked Shift's `rejection_warehouse`
2. Fallback: Manufacturing Settings `shift_rejection_warehouse`
3. If neither set: `frappe.throw()` error

---

## Complete File Inventory

### Files to Create
| File | Purpose |
|------|---------|
| `doctype/downtime_reason/__init__.py` | Package init |
| `doctype/downtime_reason/downtime_reason.json` | DocType definition |
| `doctype/downtime_reason/downtime_reason.py` | Controller (stub) |
| `doctype/downtime_reason/test_downtime_reason.py` | Tests |
| `doctype/operator/__init__.py` | Package init |
| `doctype/operator/operator.json` | DocType definition |
| `doctype/operator/operator.py` | Controller (stub) |
| `doctype/operator/test_operator.py` | Tests |
| `overrides/__init__.py` | Package init |
| `overrides/stock_entry_hooks.py` | Stock Entry validate hook |
| `api.py` | Whitelisted API for shift details |
| `tests/__init__.py` | Package init |
| `tests/test_stock_entry_hooks.py` | Integration tests |
| `public/js/stock_entry.js` | Client script for Stock Entry |
| `fixtures/downtime_reason.json` | Fixture data |

All paths relative to `production_entry_app/production_entry_app/`.

### Files to Modify
| File | Changes |
|------|---------|
| `doctype/loss_entry/loss_entry.json` | Rename loss_type → downtime_reason, add remark |
| `doctype/shift/shift.json` | Add branch field |
| `doctype/shift/shift.py` | loss_type → downtime_reason in all refs |
| `doctype/shift/shift.js` | Add "Create Production Entry" button |
| `doctype/shift/test_shift.py` | Update all loss_type → downtime_reason, rename helper |
| `hooks.py` | Add doc_events, doctype_js, update fixtures |
| `fixtures/custom_field.json` | Add ~18 custom fields for Stock Entry, Stock Entry Detail, Workstation |

### Files to Delete
| File | Reason |
|------|--------|
| `doctype/loss_type/` (entire directory) | Replaced by Downtime Reason |
| `fixtures/loss_type.json` | Replaced by downtime_reason.json |

---

## Implementation Order

| Step | Phase | Dependency | Key Risk |
|------|-------|------------|----------|
| 1 | Phase 1: Downtime Reason + Loss Entry refactor | None | Loss Entry field rename = schema migration |
| 2 | Phase 2: Operator DocType | None | Low risk |
| 3 | Phase 3: Shift Branch field | None | Low risk |
| 4 | Phase 4: Custom Fields (fixtures) | Phases 1-3 | insert_after field names must match ERPNext version |
| 5 | Phase 5: Server-side hooks | Phase 4 | Rejection idempotency edge cases |
| 6 | Phase 6: Client script for Stock Entry | Phases 4-5 | Client/server sync for auto-fill |
| 7 | Phase 7: Shift "Create Production Entry" button | Phase 6 | Low risk |

Phases 1, 2, and 3 are independent and can be done in parallel. Phase 4 depends on all three. Phases 5-7 are sequential.

---

## Verification Plan

1. **Run all existing tests** to verify no regressions: `bench --site <site> run-tests --app production_entry_app`
2. **Run new tests** for each phase individually
3. **Manual E2E test**:
   - Create a Downtime Reason record
   - Create an Operator record
   - Create a Shift with branch set → verify planned losses use downtime_reason
   - Click "Create Production Entry" on Shift → verify Stock Entry opens with shift pre-filled
   - Set shift ref on Stock Entry → verify branch, dates, warehouses auto-fill
   - Set BOM, fg_completed_qty, Get Items → set rejection_qty → Save → verify rejection row
   - Add unplanned loss entries in the Loss Entry table on Stock Entry
4. **Verify coverage** remains above 80%
