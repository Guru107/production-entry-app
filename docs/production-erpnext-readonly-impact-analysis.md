# Production ERPNext Read-Only Impact Analysis

Date: 2026-04-28

Target host: `trikayacoatings.frappe.cloud`

Scope: read-only production metadata review using ERPNext REST `GET` requests and local repository inspection. No production writes, installs, migrations, saves, deletes, or mutation endpoints were run.

## Environment Observed

- Frappe: `15.106.0`
- ERPNext: `15.105.0`
- Installed apps observed include `hrms`, `india_compliance`, `trikaya`, `lms`, `helpdesk`, `insights`, `drive`, and other site apps.
- Production metadata scan found:
  - 143 custom fields on impacted doctypes
  - 58 property setters on impacted doctypes
  - 13 client scripts on impacted doctypes
  - 2 server scripts on impacted doctypes

## DocTypes Impacted By The Module

Existing ERPNext DocTypes impacted:

- `Stock Entry`: custom fields, client script, validation hooks, submit/cancel/trash hooks, and global class override.
- `Stock Entry Detail`: rejection-row marker field.
- `Item`: die-tool metadata fields.
- `Workstation`: standard SPM and shift timeline fields/client script.
- `Downtime Entry`: shift link and workstation overlap checks.
- `Warehouse`: rejection warehouse validation through `is_rejected_warehouse`.
- `BOM`, `BOM Item`, `Item Alternative`: alternative item validation.
- `Branch`, `Company`, `Department`, `Warehouse`: linked from Shift and Stock Entry flows.

New app DocTypes introduced by the module:

- `Shift`
- `Loss Entry`
- `Operator`
- `Downtime Reason`
- `Rejection Reason`
- `Rejection Breakup`
- `Die Tool Counter`
- `Die Tool Maintenance Log`
- `Production Entry Settings`
- `Production Entry Access Rule`

## Key Findings

### 1. Hard Conflict: `Downtime Reason` Already Exists

Production already has a custom DocType named `Downtime Reason`.

Observed production metadata:

- Module: `Manufacturing`
- Custom: `1`
- Submittable: `1`
- Autoname: `field:downtime_issue`
- Main field: `downtime_issue`
- Existing records observed include `Trial`, `Tool Break`, `Setup Time`, `Power Off`, and similar downtime reasons.

The app also ships a DocType named `Downtime Reason`, but with a different schema:

- Module: `Production Entry App`
- Autoname: `field:downtime_reason_name`
- Fields: `downtime_reason_name`, `is_active`

Risk: installing as-is can fail or create DocType ownership/schema drift. This is the main install blocker.

### 2. High Risk: Existing `Stock Entry-branch` Field Would Be Overwritten

Production already has:

- Custom Field: `Stock Entry-branch`
- Type: Link to `Branch`
- Inserted after: `dimension_col_break`
- Read only: `0`

The module fixture also defines `Stock Entry-branch`:

- Inserted after: `custom_pea_shift`
- Read only: `1`
- Module: `Production Entry App`

Production also has a property setter:

- `Stock Entry-branch-reqd = 1`

Risk: after install, `branch` may become required and read-only. Non-PEA Stock Entry workflows can be blocked unless another defaulting script fills the field reliably.

### 3. Existing Production Workflow Overlaps PEA Stock Entry Fields

Production already has Stock Entry custom fields for similar concepts:

- `custom_planned_start_date`
- `custom_planned_end_date`
- `custom_actual_start_date`
- `custom_actual_end_date`
- `custom_workstation`
- `custom_standard_spm`
- `custom_time_logs`
- `custom_loss_time_details`
- `custom_total_actual_time`
- `custom_total_loss_time`
- `custom_stock_entry_purpose`

The module adds parallel `custom_pea_*` fields. There is no direct fieldname collision, but there is a workflow split risk: existing scripts update the older fields, while this module validates and reports using the PEA fields.

### 4. Existing Client Scripts Can Conflict Behaviorally

Enabled Stock Entry client scripts observed:

- `Actual & Loss Time Calculation`
- `BOM`
- `Branch Fetching Stock Entry`
- `Stock Auto Time`
- `Stock Entry Type`

Relevant behavior:

- `BOM` changes `stock_entry_type` based on BOM `custom_operation`.
- `Stock Entry Type` sets department based on stock entry type.
- `Branch Fetching Stock Entry` propagates parent `branch` into child rows.
- Existing time scripts calculate non-PEA actual/loss time fields.

Risk: these scripts may not block installation, but they can create confusing or inconsistent UI behavior once PEA Stock Entry scripts also run.

### 5. Existing Server Script Updates Submitted Stock Entries

Active server script observed:

- Name: `SE Branch Update`
- Reference DocType: `Stock Entry`
- Event: `After Save (Submitted Document)`
- Behavior: updates `Stock Entry.branch`, `Stock Entry Detail.branch`, and `GL Entry.branch`.

Risk: PEA sets Stock Entry branch from linked Shift during validation, but this server script can change branch after submit through `custom_updated_branch`. That can make branch values diverge from the linked Shift after submission.

### 6. Global Stock Entry Override

The app overrides the ERPNext `Stock Entry` class:

```python
override_doctype_class = {
	"Stock Entry": "production_entry_app.production_entry_app.overrides.stock_entry.ProductionEntryAppStockEntry"
}
```

The override is small: it changes finished-good row selection to ignore PEA rejection rows. However, the override is global. If another installed app, such as `trikaya`, also overrides `Stock Entry`, Frappe can only cleanly honor one override.

### 7. Validation Hooks Can Affect Normal Stock Entry Saves

The Stock Entry validate hook returns early only when `can_use_production_entry_app()` returns false.

With PEA access control disabled, that function returns true for all users, so PEA validations can run broadly. Most validations require PEA fields such as `custom_pea_shift`, actual start/end, workstation, operator, or rejection quantity, but accidental partial entry can still produce validation errors on regular Stock Entry saves.

### 8. Rejection Warehouse Validation Has Production Data Support

Production has `Warehouse.is_rejected_warehouse`, and at least three active warehouses are marked as rejected warehouses.

Risk is manageable, but PEA rejection flows need correct Shift or Production Entry Settings defaults. Otherwise Stock Entry validation can fail when a rejection quantity is entered.

## Regression Assessment

Installing this module on the observed production instance as-is is not low risk.

Main blockers:

- `Downtime Reason` DocType name collision in production.
- `Stock Entry-branch` would likely be overwritten to read-only while still required.
- Current Stock Entry scripts and fields already implement a parallel production-time workflow that PEA does not automatically migrate or synchronize.

## Recommendation

Do not install as-is on this production instance.

Recommended sequence before production installation:

1. Resolve the `Downtime Reason` DocType conflict. Either rename the app DocType or intentionally migrate the production DocType and records to the app schema.
2. Remove or change the module fixture for `Stock Entry-branch`; do not overwrite production's existing branch field behavior.
3. Decide whether PEA should reuse existing production fields like `custom_actual_start_date`, `custom_workstation`, and related time fields, or keep separate `custom_pea_*` fields with an explicit migration/sync plan.
4. Check whether installed custom apps, especially `trikaya`, also override `Stock Entry`.
5. Test installation on a production clone before touching production.

## Trade-Offs

Keeping PEA isolated with `custom_pea_*` fields reduces direct field collisions, but increases duplicated UI and workflow complexity.

Reusing existing production fields reduces user confusion, but requires more careful code changes, migration logic, and regression testing.

Renaming app-owned `Downtime Reason` avoids the hardest install conflict, but requires updating links, fixtures, reports, tests, and any user-facing labels that assume the current DocType name.
