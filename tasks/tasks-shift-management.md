# Tasks: Shift Management Module

## Relevant Files

- `production_entry_app/production_entry_app/doctype/loss_type/loss_type.json` - Loss Type DocType definition
- `production_entry_app/production_entry_app/doctype/loss_type/loss_type.py` - Loss Type controller
- `production_entry_app/production_entry_app/doctype/loss_type/test_loss_type.py` - Unit tests for Loss Type
- `production_entry_app/production_entry_app/doctype/shift_planned_loss/shift_planned_loss.json` - Shift Planned Loss child table DocType definition
- `production_entry_app/production_entry_app/doctype/shift_planned_loss/shift_planned_loss.py` - Shift Planned Loss controller
- `production_entry_app/production_entry_app/doctype/shift/shift.json` - Shift DocType definition
- `production_entry_app/production_entry_app/doctype/shift/shift.py` - Shift controller with business logic
- `production_entry_app/production_entry_app/doctype/shift/shift.js` - Shift client-side scripts
- `production_entry_app/production_entry_app/doctype/shift/test_shift.py` - Unit tests for Shift
- `production_entry_app/fixtures/custom_field.json` - Custom fields for Manufacturing Settings and Downtime Entry
- `production_entry_app/fixtures/loss_type.json` - Default Loss Type records (Tea Break, Lunch Break)
- `production_entry_app/hooks.py` - App hooks including fixtures configuration

### Notes

- Unit tests should be placed in `production_entry_app/production_entry_app/doctype/<doctype_name>/test_<doctype_name>.py`
- Use `bench run-tests --app production_entry_app` to run all tests
- Use `bench run-tests --app production_entry_app --doctype "Shift"` to run tests for a specific DocType
- Follow TDD approach: write tests first, then implement

## Instructions for Completing Tasks

**IMPORTANT:** As you complete each task, you must check it off in this markdown file by changing `- [ ]` to `- [x]`. This helps track progress and ensures you don't skip any steps.

Example:
- `- [ ] 1.1 Read file` → `- [x] 1.1 Read file` (after completing)

Update the file after completing each sub-task, not just after completing an entire parent task.

## Tasks

- [x] 0.0 Create feature branch
  - [x] 0.1 Create and checkout a new branch `feature/shift-management` from develop branch

- [x] 1.0 Create Loss Type Master DocType
  - [x] 1.1 Write unit tests for Loss Type DocType (test creation, required fields, default duration validation)
  - [x] 1.2 Create Loss Type DocType JSON with fields: loss_type_name (Data, required), default_duration (Int)
  - [x] 1.3 Create Loss Type controller (loss_type.py) with basic document class
  - [x] 1.4 Set naming rule to use loss_type_name as the document name
  - [x] 1.5 Run tests to verify Loss Type DocType works correctly
    - [x] 1.5.1 Investigate `ImplicitCommitError` during `bench --site development.localhost run-tests ...` (fails at `START TRANSACTION`)

- [ ] 2.0 Create Shift Planned Loss Child Table DocType
  - [ ] 2.1 Create Shift Planned Loss DocType JSON with istable=1 and fields: loss_type (Link to Loss Type), start_time (Time), end_time (Time)
  - [ ] 2.2 Create Shift Planned Loss controller (shift_planned_loss.py) with basic document class
  - [ ] 2.3 Verify child table can be added to parent DocType

- [ ] 3.0 Create Shift DocType with core fields and warehouses
  - [ ] 3.1 Write unit tests for Shift DocType creation and default value population
  - [ ] 3.2 Create Shift DocType JSON with core fields: shift_label (Select: Shift 1, Shift 2), shift_duration (Select: 8, 10, 12), shift_date (Date), shift_end_date (Date), planned_start_time (Time), planned_end_time (Time, read_only), supervisor (Link to User)
  - [ ] 3.3 Add warehouse fields to Shift DocType: raw_material_warehouse, work_in_progress_warehouse, rejection_warehouse, scrap_warehouse (all Link to Warehouse)
  - [ ] 3.4 Add planned_losses child table field (Table: Shift Planned Loss)
  - [ ] 3.5 Add status field (Select: Draft, Running, Completed, Cancelled) with default "Draft"
  - [ ] 3.6 Configure naming series: SHIFT-.YYYY..MM..DD.-Shift-{shift_label}-.#
  - [ ] 3.7 Create Shift controller (shift.py) with before_insert hook to auto-populate: shift_date (today), planned_start_time (now), supervisor (current user)
  - [ ] 3.8 Implement logic to copy warehouse defaults from Manufacturing Settings on new document creation
  - [ ] 3.9 Implement planned_end_time calculation (planned_start_time + shift_duration hours)
  - [ ] 3.10 Implement shift_end_date calculation for midnight-crossing shifts
  - [ ] 3.11 Run tests to verify default value population and calculations

- [ ] 4.0 Implement planned losses auto-population logic
  - [ ] 4.1 Write unit tests for planned losses auto-population based on shift duration
  - [ ] 4.2 Implement server-side logic in shift.py to auto-populate planned losses when shift_duration changes
  - [ ] 4.3 For 8-hour shifts: add Tea Break at +2 hours (15 min), Lunch Break at +4 hours (30 min)
  - [ ] 4.4 For 10/12-hour shifts: add Tea Break at +2h (15 min), Lunch Break at +4h (30 min), Tea Break at +6h (15 min)
  - [ ] 4.5 Create client-side script (shift.js) to trigger auto-population on shift_duration field change
  - [ ] 4.6 Run tests to verify planned losses populate correctly for each duration

- [ ] 5.0 Implement workflow and state management
  - [ ] 5.1 Write unit tests for state transitions (Draft→Running, Running→Completed, Draft→Cancelled)
  - [ ] 5.2 Create "Start Shift" button in shift.js, visible only when status is "Draft"
  - [ ] 5.3 Create "End Shift" button in shift.js, visible only when status is "Running"
  - [ ] 5.4 Implement start_shift method in shift.py to change status to "Running"
  - [ ] 5.5 Implement end_shift method in shift.py to change status to "Completed"
  - [ ] 5.6 Implement cancel_shift method in shift.py to change status to "Cancelled" (only from Draft)
  - [ ] 5.7 Implement field locking logic: lock planned_losses in Running state, lock entire doc in Completed/Cancelled
  - [ ] 5.8 Add @frappe.whitelist() decorators to state transition methods
  - [ ] 5.9 Run tests to verify state transitions and field locking work correctly

- [ ] 6.0 Implement validation rules
  - [ ] 6.1 Write unit tests for overlap prevention validation
  - [ ] 6.2 Write unit tests for unique shift label per date validation
  - [ ] 6.3 Implement validate method in shift.py to check for overlapping shift time periods
  - [ ] 6.4 Implement validation to enforce unique shift_label per shift_date (only one "Shift 1" per date)
  - [ ] 6.5 Add proper error messages using frappe.throw() with translatable strings
  - [ ] 6.6 Run tests to verify validation rules prevent invalid data

- [ ] 7.0 Add custom fields to Manufacturing Settings and Downtime Entry
  - [ ] 7.1 Create custom_field.json fixture with "Shift Settings" section break for Manufacturing Settings
  - [ ] 7.2 Add custom fields to Manufacturing Settings: shift_raw_material_warehouse, shift_wip_warehouse, shift_rejection_warehouse, shift_scrap_warehouse (all Link to Warehouse)
  - [ ] 7.3 Add custom "shift" link field to Downtime Entry DocType (optional field)
  - [ ] 7.4 Update shift.py to read warehouse defaults from Manufacturing Settings custom fields
  - [ ] 7.5 Add HTML field or virtual field in Shift to display linked Downtime Entries
  - [ ] 7.6 Create client-side script to fetch and display linked Downtime Entries in Shift form

- [ ] 8.0 Implement notifications and conflict warnings
  - [ ] 8.1 Write unit tests for notification creation on state transitions
  - [ ] 8.2 Implement notification on shift start (Running state) - notify relevant users
  - [ ] 8.3 Implement notification on shift end (Completed state) - notify relevant users
  - [ ] 8.4 Write unit test for running shift conflict warning
  - [ ] 8.5 Implement warning check in start_shift method: warn if another shift is currently Running
  - [ ] 8.6 Display warning dialog in client-side before starting shift if conflict exists
  - [ ] 8.7 Run tests to verify notifications and warnings work correctly

- [ ] 9.0 Configure permissions
  - [ ] 9.1 Add permissions in Loss Type DocType JSON for Manufacturing User and Manufacturing Manager (CRUD)
  - [ ] 9.2 Add permissions in Shift DocType JSON for Manufacturing User (Create, Read, Write, Delete)
  - [ ] 9.3 Add permissions in Shift DocType JSON for Manufacturing Manager (Create, Read, Write, Delete)
  - [ ] 9.4 Write permission tests to verify role-based access control

- [ ] 10.0 Create fixtures for default data
  - [ ] 10.1 Create loss_type.json fixture with default records: Tea Break (15 min), Lunch Break (30 min)
  - [ ] 10.2 Update hooks.py to include fixtures list: ["Custom Field", "Loss Type"]
  - [ ] 10.3 Export custom fields to custom_field.json fixture file
  - [ ] 10.4 Run `bench migrate` to verify fixtures load correctly
  - [ ] 10.5 Run full test suite to ensure all functionality works end-to-end
