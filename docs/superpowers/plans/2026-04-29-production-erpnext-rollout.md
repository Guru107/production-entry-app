# Production ERPNext Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden Production Entry App for a one-shot Frappe Cloud rollout on the production ERPNext site.

**Architecture:** Keep production-owned customizations owned by production, especially `Stock Entry.branch` and `Downtime Reason`. Add app-side compatibility, native Frappe role/permlevel access, document-level Stock Entry activation, and read-only preflight checks before release. Use local `bench15` production-replica rehearsal to prove the exact holiday cutover order.

**Tech Stack:** Frappe/ERPNext v15, Python 3.10, Frappe DocType JSON/fixtures/hooks, Frappe tests, Playwright E2E, JS form controllers.

---

## Spec Reference
- Design spec: `docs/superpowers/specs/2026-04-29-production-erpnext-rollout-design.md`
- Source analysis: `docs/production-erpnext-readonly-impact-analysis.md`
- Project guidance: `CLAUDE.md`

## File Structure

Expected files to modify:
- `production_entry_app/hooks.py` - fixtures, gated doctypes, reports/roles, Stock Entry hooks remain registered.
- `production_entry_app/install.py` - create default roles and safe production-owned master data.
- `production_entry_app/production_entry_app/access_control.py` - split read/write access model.
- `production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.json` - replace single required role with read/write roles.
- `production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.py` - cache invalidation and defaults.
- `production_entry_app/fixtures/custom_field.json` - remove `Stock Entry-branch`, add permlevels to app-generated fields.
- `production_entry_app/fixtures/property_setter.json` - review for Stock Entry assumptions.
- `production_entry_app/fixtures/downtime_reason.json` - remove or replace fixture-driven ownership.
- `production_entry_app/production_entry_app/doctype/downtime_reason/**` - delete app-owned DocType files so the app no longer syncs this DocType.
- `production_entry_app/production_entry_app/doctype/loss_entry/loss_entry.json` - keep link to production-owned `Downtime Reason`.
- `production_entry_app/production_entry_app/doctype/shift/shift.py` - downtime reason schema compatibility, branch correction API if implemented here.
- `production_entry_app/production_entry_app/api.py` - cleanup/test helper compatibility and preflight endpoint.
- `production_entry_app/production_entry_app/utils/test_bootstrap.py` - test data setup compatibility with production-owned `Downtime Reason`.
- `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py` - `custom_pea_shift` activation guard and branch behavior.
- `production_entry_app/production_entry_app/overrides/stock_entry.py` - keep current override, add guard tests if needed.
- `production_entry_app/public/js/*.js` - keep UI behavior, reduce access hiding to UX-only where native permlevels apply.
- `production_entry_app/public/js/generated_access_control_field_map.js` and generator script if present - update after fixture changes.
- `production_entry_app/production_entry_app/preflight.py` - create read-only preflight module.
- `production_entry_app/production_entry_app/api.py` - expose System Manager-gated preflight endpoint if needed for Frappe Cloud.
- `production_entry_app/production_entry_app/test_*.py`, `production_entry_app/production_entry_app/overrides/test_*.py`, `production_entry_app/production_entry_app/doctype/shift/test_shift.py` - unit/integration tests.
- `tests/e2e/specs/*.spec.js`, `tests/e2e/pages/*.js`, `tests/unit/*.test.js` - E2E and JS tests.
- `docs/production-erpnext-cutover-runbook.md` - create final operator runbook.

Do not modify:
- Production-owned `Warehouse.is_rejected_warehouse`.
- Production-owned `Stock Entry.branch` metadata in app fixtures.
- `docs/production-erpnext-readonly-impact-analysis.md` unless explicitly requested.

## Task 1: Access Roles And Settings

**Files:**
- Modify: `production_entry_app/production_entry_app/access_control.py`
- Modify: `production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.json`
- Modify: `production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.py`
- Modify: `production_entry_app/install.py`
- Test: `production_entry_app/production_entry_app/test_access_control.py`
- Test: `production_entry_app/production_entry_app/test_access_control_doctypes.py`
- Test: `production_entry_app/production_entry_app/test_access_control_whitelisted_api.py`

- [ ] **Step 1: Write failing tests for read/write role model**

Add tests covering:
- `System Manager` can read and write.
- `PEA User` can read and write.
- `PEA Read Only` can read but not write.
- non-PEA user cannot read/write PEA app surfaces when access control is enabled.
- `PEA User` implies read access without also assigning `PEA Read Only`.
- disabled access control behavior remains intentionally defined for development.

Suggested test shape in `test_access_control.py`:

```python
def test_pea_user_has_read_and_write_access(self) -> None:
	config = access_control.AccessConfiguration(
		enabled=True,
		write_role="PEA User",
		read_role="PEA Read Only",
	)
	with patch.object(access_control, "_get_access_configuration", return_value=config), patch.object(
		access_control.frappe, "get_roles", return_value=["PEA User"]
	):
		self.assertTrue(access_control.can_read_production_entry_app("test@example.com"))
		self.assertTrue(access_control.can_write_production_entry_app("test@example.com"))
```

- [ ] **Step 2: Run access-control tests and verify failure**

Run from `/Users/gurudattkulkarni/Workspace/bench15`:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_access_control
```

Expected: FAIL because `write_role`, `read_role`, and read/write access helpers do not exist.

- [ ] **Step 3: Implement `AccessConfiguration` read/write roles**

Update `access_control.py`:
- keep `DEFAULT_REQUIRED_ROLE` temporarily only if needed for migration compatibility.
- add constants:

```python
DEFAULT_WRITE_ROLE: str = "PEA User"
DEFAULT_READ_ROLE: str = "PEA Read Only"
```

- change dataclass to:

```python
@dataclass(frozen=True)
class AccessConfiguration:
	enabled: bool
	write_role: str
	read_role: str
```

- add:

```python
def can_read_production_entry_app(user: str | None = None) -> bool: ...
def can_write_production_entry_app(user: str | None = None) -> bool: ...
def assert_app_read_access(...) -> None: ...
def assert_app_write_access(...) -> None: ...
```

Keep `can_use_production_entry_app()` as a compatibility alias for write access unless a caller clearly needs read access.

- [ ] **Step 4: Update settings DocType**

In `production_entry_settings.json`:
- replace or deprecate `required_role`.
- add `write_role` Link Role default `PEA User`.
- add `read_role` Link Role default `PEA Read Only`.
- keep `enable_access_control`.

In `production_entry_settings.py`, keep cache invalidation on update.

- [ ] **Step 5: Create both roles on install**

Update `install.py` to idempotently create:
- `PEA User`
- `PEA Read Only`

Use a small helper:

```python
def _ensure_role(role_name: str) -> None:
	if not frappe.db.exists("Role", role_name):
		frappe.get_doc({"doctype": "Role", "role_name": role_name}).insert()
```

- [ ] **Step 6: Update permission gates**

Use read access for app visibility and read-only surfaces. Use write access for mutation APIs and write actions.

Review and update:
- `has_app_permission()`
- `has_gated_doctype_permission()`
- any API calls using `assert_app_access()`

- [ ] **Step 7: Run targeted access tests**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_access_control
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_access_control_doctypes
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_access_control_whitelisted_api
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add production_entry_app/install.py \
  production_entry_app/production_entry_app/access_control.py \
  production_entry_app/production_entry_app/doctype/production_entry_settings \
  production_entry_app/production_entry_app/test_access_control.py \
  production_entry_app/production_entry_app/test_access_control_doctypes.py \
  production_entry_app/production_entry_app/test_access_control_whitelisted_api.py
git commit -m "feat: split PEA read and write access roles"
```

## Task 2: Native Field Permissions For App-Generated Fields

**Files:**
- Modify: `production_entry_app/fixtures/custom_field.json`
- Modify: `production_entry_app/hooks.py`
- Modify: `production_entry_app/production_entry_app/lifecycle.py`
- Create: `production_entry_app/production_entry_app/field_permissions.py`
- Modify: `production_entry_app/public/js/custom_field_visibility.js`
- Modify: `production_entry_app/public/js/generated_access_control_field_map.js`
- Modify/create generator script if available.
- Test: `production_entry_app/production_entry_app/test_access_control_field_map.py`
- Test: `tests/unit/stock-entry-visibility.test.js`

- [ ] **Step 1: Write failing fixture/permission tests**

Add tests that load `fixtures/custom_field.json` and assert:
- every Custom Field with `"module": "Production Entry App"` has `permlevel: 9`.
- `Stock Entry-branch` is absent.
- no permission changes are expected for `Warehouse.is_rejected_warehouse`.

Example:

```python
def test_app_generated_custom_fields_use_pea_permlevel(self) -> None:
	fields = _load_custom_field_fixture()
	for field in fields:
		if field.get("module") == "Production Entry App":
			self.assertEqual(field.get("permlevel"), 9, field["name"])
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_access_control_field_map
```

Expected: FAIL because fixtures do not yet consistently set `permlevel`.

- [ ] **Step 3: Update Custom Field fixtures**

In `production_entry_app/fixtures/custom_field.json`:
- remove the `Stock Entry-branch` fixture object entirely.
- add `"permlevel": 9` to every app-generated field object.
- do not add or change `Warehouse.is_rejected_warehouse`.

- [ ] **Step 4: Add Role Permission fixtures or install setup**

Use an install/migrate setup helper, not fixtures. This repo has no existing DocPerm fixture convention,
and an idempotent helper is easier to verify across local replica and Frappe Cloud.

Required behavior:
- `PEA User`: read/write at permlevel 9.
- `PEA Read Only`: read at permlevel 9.
- normal roles: no permlevel 9 access.

Create `production_entry_app/production_entry_app/field_permissions.py` and call it from
`production_entry_app/production_entry_app/lifecycle.py` inside `_setup_app()`, which already runs
from `after_sync` and `after_migrate`.

The helper must:
- discover standard DocTypes that have app-generated Custom Fields with `permlevel = 9`.
- ensure Custom DocPerm rows for `PEA User` and `PEA Read Only` at permlevel 9.
- not modify production-owned fields such as `Stock Entry.branch`.
- not modify non-app-generated fields such as `Warehouse.is_rejected_warehouse`.
- be idempotent and safe to run repeatedly.

- [ ] **Step 5: Keep JS visibility as UX only**

Update `custom_field_visibility.js` only if needed so it does not fight native permissions. Keep purpose-based show/hide behavior in `stock_entry.js`.

- [ ] **Step 6: Run targeted tests**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_access_control_field_map
npm test -- tests/unit/stock-entry-visibility.test.js
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add production_entry_app/fixtures/custom_field.json \
  production_entry_app/hooks.py \
  production_entry_app/production_entry_app/lifecycle.py \
  production_entry_app/production_entry_app/field_permissions.py \
  production_entry_app/public/js \
  production_entry_app/production_entry_app/test_access_control_field_map.py \
  tests/unit/stock-entry-visibility.test.js
git commit -m "feat: protect PEA custom fields with permlevels"
```

## Task 3: Production-Owned Downtime Reason Compatibility

**Files:**
- Modify: `production_entry_app/hooks.py`
- Modify: `production_entry_app/install.py`
- Modify/remove: `production_entry_app/fixtures/downtime_reason.json`
- Delete: `production_entry_app/production_entry_app/doctype/downtime_reason/downtime_reason.json`
- Delete: `production_entry_app/production_entry_app/doctype/downtime_reason/downtime_reason.py`
- Delete: `production_entry_app/production_entry_app/doctype/downtime_reason/test_downtime_reason.py`
- Delete if empty: `production_entry_app/production_entry_app/doctype/downtime_reason/__init__.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Modify: `production_entry_app/production_entry_app/doctype/loss_entry/loss_entry.json`
- Test: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`
- Test: `production_entry_app/production_entry_app/report/test_reports.py`
- Test: `production_entry_app/production_entry_app/test_api.py`
- Test: `production_entry_app/production_entry_app/test_access_control_doctypes.py`
- Test: `production_entry_app/production_entry_app/tests/compat/test_v16_permission_hooks.py`

- [ ] **Step 1: Write failing tests for production schema**

Add tests that simulate a `Downtime Reason` DocType with:
- field `downtime_issue`
- no `downtime_reason_name`
- no `is_active`
- submitted records as the normal selectable state

Cover:
- planned loss generation uses existing reasons.
- missing default reason seeding checks uniqueness by `downtime_issue`.
- app does not require `is_active`.
- app does not gate `Downtime Reason` as an app-owned DocType.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.doctype.shift.test_shift
```

Expected: FAIL on old assumptions around `downtime_reason_name` or `is_active`.

- [ ] **Step 3: Remove app-owned Downtime Reason DocType from sync scope**

Update `hooks.py`:
- remove `"Downtime Reason"` from `has_permission`.
- remove `"Downtime Reason"` from `fixtures`.

Remove or neutralize `production_entry_app/fixtures/downtime_reason.json` so fixture sync does not overwrite production records.

Delete the app-owned DocType files:
- `production_entry_app/production_entry_app/doctype/downtime_reason/downtime_reason.json`
- `production_entry_app/production_entry_app/doctype/downtime_reason/downtime_reason.py`
- `production_entry_app/production_entry_app/doctype/downtime_reason/test_downtime_reason.py`
- `production_entry_app/production_entry_app/doctype/downtime_reason/__init__.py` if the directory is otherwise empty

Do not delete or modify production's existing `Downtime Reason` DocType on the target site.
Local `bench15` rehearsal must provide the production-owned `Downtime Reason` metadata before PEA
install/migrate.

After deletion, run a local migrate on the disposable replica and verify Frappe does not try to
create an app-owned `Downtime Reason` DocType. The only acceptable `Downtime Reason` metadata is
the production-owned custom DocType with `downtime_issue`.

- [ ] **Step 4: Audit and update all Downtime Reason references**

Run:

```bash
rg -n "Downtime Reason|downtime_reason_name|downtime_issue|is_active" production_entry_app tests docs \
  -g '!docs/production-erpnext-readonly-impact-analysis.md'
```

Every hit must be classified and handled:
- production-compatible reference to DocType name: keep.
- old app-owned field `downtime_reason_name`: replace with `downtime_issue` or a schema-aware helper.
- old app-owned field `is_active`: remove or replace with submitted-record logic.
- app-owned permission/gating references: remove for `Downtime Reason`.
- E2E/test cleanup references: update to avoid deleting production-owned reasons except reserved test records.

Files that must be reviewed include:
- `production_entry_app/production_entry_app/api.py`
- `production_entry_app/production_entry_app/utils/test_bootstrap.py`
- `production_entry_app/production_entry_app/test_api.py`
- `production_entry_app/production_entry_app/test_access_control_doctypes.py`
- `production_entry_app/production_entry_app/tests/compat/test_v16_permission_hooks.py`
- all reports and report tests.

Expected after implementation:

```bash
rg -n "downtime_reason_name|is_active" production_entry_app tests \
  -g '!production_entry_app/production_entry_app/doctype/operator/**' \
  -g '!production_entry_app/production_entry_app/doctype/rejection_reason/**'
```

returns no `Downtime Reason`-related old-schema references.

- [ ] **Step 5: Add idempotent seeding helper**

In `install.py` or a focused helper module, add:

```python
DEFAULT_DOWNTIME_ISSUES: tuple[str, ...] = (
	"Setup Time",
	"Trial",
	"Mtrl Handl",
	"No Operator",
	"No Mtrl",
	"Maint",
	"P. Maint",
	"Tool Break",
	"Other",
	"No Helper",
	"Power Off",
	"Tea Break",
	"Lunch Break",
	"Shift Start Up",
	"JH Activity",
	"Dinner",
)
```

Implement:
- check meta has `downtime_issue`.
- find existing record by `downtime_issue`.
- do not overwrite existing records.
- create missing records with `downtime_issue`.
- match existing docstatus pattern: if existing normal records are submitted, submit new records.

- [ ] **Step 6: Update Shift reason filtering**

In `shift.py`:
- replace `is_active` logic with schema-aware submitted-record logic.
- if production schema has `docstatus`, filter/select submitted reasons when submitted records are normal.
- do not assume `downtime_reason_name`.

- [ ] **Step 7: Update tests and report helpers**

Replace test document creation like:

```python
frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": reason}).insert()
```

with a helper that uses production-compatible schema:

```python
frappe.get_doc({"doctype": "Downtime Reason", "downtime_issue": reason}).insert()
```

Submit if the test schema is submittable.

- [ ] **Step 8: Run targeted tests**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.doctype.shift.test_shift
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.report.test_reports
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_access_control_doctypes
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.tests.compat.test_v16_permission_hooks
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add production_entry_app/hooks.py production_entry_app/install.py \
  production_entry_app/fixtures/downtime_reason.json \
  production_entry_app/production_entry_app/doctype/downtime_reason \
  production_entry_app/production_entry_app/doctype/shift/shift.py \
  production_entry_app/production_entry_app/api.py \
  production_entry_app/production_entry_app/utils/test_bootstrap.py \
  production_entry_app/production_entry_app/doctype/shift/test_shift.py \
  production_entry_app/production_entry_app/report/test_reports.py \
  production_entry_app/production_entry_app/test_api.py \
  production_entry_app/production_entry_app/test_access_control_doctypes.py \
  production_entry_app/production_entry_app/tests/compat/test_v16_permission_hooks.py
git commit -m "feat: adapt downtime reasons to production schema"
```

## Task 4: Stock Entry Branch And Activation Guard

**Files:**
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_access_control.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Test: `tests/e2e/specs/stock-entry-validations.spec.js`
- Test: `tests/e2e/specs/shift-to-stock-entry.spec.js`

- [ ] **Step 1: Write failing tests for document-level activation**

Add tests:
- PEA user saving plain Material Transfer with no `custom_pea_shift` does not run PEA validation/mutation.
- PEA user saving plain Manufacture with no `custom_pea_shift` does not run PEA validation/mutation.
- submit/cancel with no `custom_pea_shift` does not update die tool counters or invalidate shift metrics.
- submit/cancel with `custom_pea_shift` still runs PEA side effects.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_access_control
```

Expected: FAIL because submit/cancel currently run side effects without a document-level guard.

- [ ] **Step 3: Add guard helper**

In `stock_entry_hooks.py`:

```python
def is_pea_stock_entry(doc: Document) -> bool:
	return bool(doc.get("custom_pea_shift"))
```

Use it at the start of:
- `validate_stock_entry`
- `on_submit_stock_entry`
- `on_cancel_stock_entry`
- any delete/cache/die-tool behavior that should only apply to PEA-linked Stock Entries

Keep validate role guard:
- if user cannot write PEA, return early or reject only when `custom_pea_shift` is set, based on existing access-control semantics.

- [ ] **Step 4: Preserve branch behavior**

Keep `_apply_shift_defaults()` setting `doc.branch = shift.branch` for PEA-linked Stock Entries. Do not recreate the `Stock Entry.branch` fixture.

- [ ] **Step 5: Add controlled Shift branch correction surface**

Implement the minimal correction path required by spec:
- authorized role: `System Manager` only for the initial rollout.
- action must add an audit comment.
- action must not be a silent normal save hook.
- action updates `Shift.branch` only; it does not update linked submitted `Stock Entry.branch`.
- response must report linked submitted Stock Entries whose `branch` differs from the corrected
  `Shift.branch` so the operator can decide whether to use the existing `SE Branch Update` process.

Prefer a small whitelisted method on `shift.py`, for example:

```python
@frappe.whitelist()
def correct_shift_branch(shift_name: str, branch: str, reason: str) -> None:
	frappe.only_for("System Manager")
	...
```

Validate:
- target branch exists.
- reason is non-empty.
- shift exists.
- add an audit comment to the Shift with old branch, new branch, reason, and actor.
- return a structured payload:

```python
{
	"shift": shift_name,
	"old_branch": old_branch,
	"new_branch": branch,
	"linked_submitted_stock_entries": [...],
	"mismatched_submitted_stock_entries": [...],
}
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.doctype.shift.test_shift
```

Expected: PASS.

- [ ] **Step 7: Update E2E tests**

Add or update E2E cases:
- PEA supervisor can submit/cancel PEA-linked Stock Entry.
- PEA supervisor can create plain Manufacture without `custom_pea_shift`.
- normal user can create non-production Stock Entry.

Run:

```bash
npx playwright test tests/e2e/specs/stock-entry-validations.spec.js \
  tests/e2e/specs/shift-to-stock-entry.spec.js
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add production_entry_app/production_entry_app/overrides/stock_entry_hooks.py \
  production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py \
  production_entry_app/production_entry_app/overrides/test_stock_entry_access_control.py \
  production_entry_app/production_entry_app/doctype/shift/shift.py \
  production_entry_app/production_entry_app/doctype/shift/test_shift.py \
  tests/e2e/specs/stock-entry-validations.spec.js \
  tests/e2e/specs/shift-to-stock-entry.spec.js
git commit -m "feat: activate PEA stock entry logic only with shift"
```

## Task 5: Read-Only Preflight Tooling

**Files:**
- Create: `production_entry_app/production_entry_app/preflight.py`
- Modify: `production_entry_app/production_entry_app/api.py`
- Create: `production_entry_app/production_entry_app/test_preflight.py`

- [ ] **Step 1: Write failing preflight tests**

Cover:
- reports existing DocType name collisions with app DocTypes.
- reports Custom Field collisions, including same name with non-PEA module ownership.
- reports Property Setter collisions on impacted DocTypes.
- reports active Client Scripts on impacted DocTypes.
- reports active Server Scripts on impacted DocTypes.
- reports references to removal-candidate fields in Client Scripts, Server Scripts, reports, and
  Print Formats.
- fails when `Stock Entry.branch` is missing.
- fails when `Stock Entry.branch` critical metadata differs.
- warns on cosmetic `insert_after` difference.
- fails when `Downtime Reason` lacks `downtime_issue`.
- reports missing default downtime reasons.
- reports Stock Entry override hook values.
- reports PEA permlevel/role setup.
- returns limited submitted Stock Entry branch sample.

- [ ] **Step 2: Run preflight tests and verify failure**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_preflight
```

Expected: FAIL because `preflight.py` does not exist.

- [ ] **Step 3: Implement preflight result model**

Create `preflight.py` with small functions:

```python
def run_preflight() -> dict:
	return {
		"status": "pass" | "fail",
		"errors": [],
		"warnings": [],
		"checks": {},
	}
```

Use focused helpers:
- `check_stock_entry_branch()`
- `check_downtime_reason_schema()`
- `check_stock_entry_override()`
- `check_pea_permlevels()`
- `check_doctype_name_collisions()`
- `check_custom_field_collisions()`
- `check_property_setter_collisions()`
- `check_active_client_scripts()`
- `check_active_server_scripts()`
- `check_removal_candidate_references()`
- `get_branch_sample(limit: int = 10)`
- `check_legacy_candidates()`

Keep all queries read-only and limited.

The result must be stable enough to compare local rehearsal and production:

```python
{
	"status": "pass" | "fail",
	"errors": [{"code": "...", "message": "...", "details": {...}}],
	"warnings": [{"code": "...", "message": "...", "details": {...}}],
	"checks": {
		"stock_entry_branch": {...},
		"downtime_reason": {...},
		"doctype_collisions": {...},
		"custom_field_collisions": {...},
		"property_setter_collisions": {...},
		"client_scripts": {...},
		"server_scripts": {...},
		"removal_candidate_references": {...},
		"stock_entry_override": {...},
		"pea_permlevels": {...},
		"branch_sample": {...},
	},
}
```

Use machine-readable `code` values so the runbook can compare local and production preflight
outputs without relying on free-text messages.

- [ ] **Step 4: Add System Manager-gated API endpoint**

In `api.py`:

```python
@frappe.whitelist()
def run_rollout_preflight() -> dict:
	frappe.only_for("System Manager")
	from production_entry_app.production_entry_app.preflight import run_preflight
	return run_preflight()
```

- [ ] **Step 5: Run targeted tests**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_preflight
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add production_entry_app/production_entry_app/preflight.py \
  production_entry_app/production_entry_app/api.py \
  production_entry_app/production_entry_app/test_preflight.py \
  production_entry_app/production_entry_app/test_api.py
git commit -m "feat: add production rollout preflight"
```

## Task 6: Report Roles And Read-Only UX

**Files:**
- Modify: report JSON files under `production_entry_app/production_entry_app/report/**`
- Modify: `tests/e2e/specs/reports.spec.js`
- Modify: `tests/e2e/specs/permissions.spec.js`
- Modify: `tests/e2e/fixtures/users.js`

- [ ] **Step 1: Write failing tests for PEA Read Only**

E2E or integration tests:
- `PEA Read Only` can view PEA reports.
- `PEA Read Only` can view Shift and PEA fields.
- `PEA Read Only` cannot create/edit/submit Shift.
- `PEA Read Only` cannot edit PEA fields on Stock Entry.
- non-PEA user does not see PEA reports through normal Frappe report permissions.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
npx playwright test tests/e2e/specs/reports.spec.js tests/e2e/specs/permissions.spec.js
```

Expected: FAIL until report roles and users are updated.

- [ ] **Step 3: Update report roles**

For each PEA report JSON, ensure allowed roles include:
- `PEA User`
- `PEA Read Only`

Do not add custom report hiding unless E2E proves Frappe report role handling is insufficient.

- [ ] **Step 4: Update E2E user fixtures**

Add or update users:
- pilot supervisor: `PEA User`
- manager/reviewer: `PEA Read Only`
- normal Stock Entry user: no PEA roles

- [ ] **Step 5: Run E2E permission/report tests**

Run:

```bash
npx playwright test tests/e2e/specs/reports.spec.js tests/e2e/specs/permissions.spec.js
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add production_entry_app/production_entry_app/report \
  tests/e2e/specs/reports.spec.js \
  tests/e2e/specs/permissions.spec.js \
  tests/e2e/fixtures/users.js
git commit -m "feat: add PEA read-only report access"
```

## Task 7: Local Replica And Cutover Runbook

**Files:**
- Create: `docs/production-erpnext-cutover-runbook.md`
- Create: `docs/production-erpnext-local-rehearsal.md`
- Modify: `docs/superpowers/specs/2026-04-29-production-erpnext-rollout-design.md` only if implementation discoveries require spec correction.

- [ ] **Step 1: Draft local rehearsal runbook**

Document:
- create disposable `bench15` site.
- import production metadata.
- import small representative data slice.
- hide legacy fields.
- disable legacy scripts/reports.
- install/migrate PEA.
- keep `PEA User` unassigned.
- run non-PEA smoke checks.
- assign pilot supervisor.
- run PEA smoke checks.
- produce final legacy action list.

- [ ] **Step 2: Draft holiday cutover runbook with exact commands/actions**

Document exact operator sequence, commands, and manual UI actions:
- Stock Entry freeze.
- production preflight.
- go/no-go approval by Gurudatt.
- metadata snapshot for audit/reference.
- hide fields and disable scripts/reports.
- install/update app.
- non-PEA smoke checks.
- assign pilot supervisor `PEA User`.
- assign reviewers `PEA Read Only`.
- PEA smoke checks.
- reopen Stock Entry.
- two-hour troubleshooting rule with 30-minute checkpoints.

- [ ] **Step 3: Include smoke test checklist**

Checklist must include:
- Shift create/start/end/cancel.
- controlled PEA production entry using real pilot master data, tiny quantity, submit, cancel.
- one small rejection quantity if process uses rejection/rework.
- die tool counter submit/cancel behavior where the pilot item uses die tooling.
- downtime overlap validation using the pilot workstation.
- planned/unplanned loss row using existing/submitted downtime reason.
- non-PEA Material Transfer.
- plain Manufacture without `custom_pea_shift`.
- `PEA Read Only` view/no-write checks.
- error log review.

- [ ] **Step 4: Review docs for destructive actions**

Ensure every destructive or reversible production action says:
- who approves.
- what evidence is required.
- how to manually re-enable/unhide old workflow if install fails.

- [ ] **Step 5: Commit**

```bash
git add docs/production-erpnext-cutover-runbook.md docs/production-erpnext-local-rehearsal.md
git commit -m "docs: add production rollout runbooks"
```

## Task 8: Execute Local Replica Rehearsal And Record Evidence

**Files:**
- Create: `docs/production-erpnext-local-rehearsal-results.md`
- Modify: `docs/production-erpnext-cutover-runbook.md` if rehearsal changes exact steps.
- Modify: `docs/production-erpnext-local-rehearsal.md` if rehearsal exposes missing setup instructions.

- [ ] **Step 1: Create disposable bench15 production-replica site**

Follow `docs/production-erpnext-local-rehearsal.md`.

Required evidence to capture:
- site name
- Frappe/ERPNext versions
- installed app list
- production metadata import source/time
- representative data slice description

- [ ] **Step 2: Run local preflight before workflow changes**

Run:

```bash
bench --site <replica-site> execute production_entry_app.production_entry_app.preflight.run_preflight
```

Save the JSON output into `docs/production-erpnext-local-rehearsal-results.md`.

- [ ] **Step 3: Hide legacy fields and disable legacy scripts/reports**

Execute the local version of the cutover actions.

Record:
- exact Custom Fields hidden
- exact Client Scripts disabled
- exact Server Scripts disabled
- exact reports disabled
- confirmation that `Stock Entry.branch` was not changed

- [ ] **Step 4: Install/migrate PEA on the replica**

Run the same install/update/migrate sequence planned for Frappe Cloud as closely as local bench
allows.

Record:
- commands run
- migration result
- any errors and fixes

- [ ] **Step 5: Run non-PEA smoke checks with `PEA User` unassigned**

Record results for:
- normal non-PEA Stock Entry such as Material Transfer
- plain Manufacture without `custom_pea_shift`
- report visibility for non-PEA user
- `Stock Entry.branch` sample verification

- [ ] **Step 6: Assign pilot and read-only roles locally**

Assign:
- pilot supervisor: `PEA User`
- manager/reviewer: `PEA Read Only`

Record exact users/roles in the results doc.

- [ ] **Step 7: Run PEA smoke checks**

Record results for:
- Shift create/start/end/cancel
- controlled PEA production entry using real pilot master data where possible, tiny quantity,
  submit, and cancel
- one small rejection quantity if the pilot process uses rejection/rework
- planned/unplanned loss row using existing/submitted downtime reason
- downtime overlap validation
- die tool counter submit/cancel behavior where applicable
- `PEA Read Only` view/no-write checks
- error log review

- [ ] **Step 8: Run local preflight after rehearsal**

Run:

```bash
bench --site <replica-site> execute production_entry_app.production_entry_app.preflight.run_preflight
```

Save output into the results doc and compare with the pre-change output.

- [ ] **Step 9: Produce final legacy action list**

In `docs/production-erpnext-local-rehearsal-results.md`, include:
- final fields to hide
- final scripts to disable
- final reports to disable
- exact production preflight stop conditions
- approval evidence Gurudatt must review

- [ ] **Step 10: Commit rehearsal evidence**

```bash
git add docs/production-erpnext-local-rehearsal-results.md \
  docs/production-erpnext-cutover-runbook.md \
  docs/production-erpnext-local-rehearsal.md
git commit -m "docs: record production rollout rehearsal results"
```

## Task 9: Full Verification

**Files:**
- All changed files.

- [ ] **Step 1: Run Python unit/integration suite with coverage**

Run from `/Users/gurudattkulkarni/Workspace/bench15`:

```bash
bench --site development.localhost run-tests --app production_entry_app --with-coverage
```

Expected: PASS and coverage remains above 90%.

- [ ] **Step 2: Run Playwright E2E**

Run from app repo:

```bash
npx playwright test
```

Expected: PASS.

- [ ] **Step 3: Run JS unit tests**

Run:

```bash
npm test
```

Expected: PASS.

- [ ] **Step 4: Run lint/pre-commit**

Run from app repo:

```bash
pre-commit run --all-files
```

Expected: PASS.

- [ ] **Step 5: Run local preflight**

Run via bench execute or API after implementation:

```bash
bench --site development.localhost execute production_entry_app.production_entry_app.preflight.run_preflight
```

Expected: returns `status: pass` on the prepared local replica, or expected failures on a non-replica dev site documented in the output.

- [ ] **Step 6: Final git check**

Run:

```bash
git status --short
git log --oneline -n 10
```

Expected: clean worktree except explicitly user-owned untracked files, commits split by task.
