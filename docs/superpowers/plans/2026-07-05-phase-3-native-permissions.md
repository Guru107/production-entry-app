# Phase 3 — Native Permissions & Branch Isolation Implementation Plan

> **Superseded for PR #79.** This July plan proposed app-owned creation of `Stock Entry.branch`.
> That is no longer the contract. Production Entry App owns `Shift.branch` only; the production
> ERPNext instance owns `Stock Entry.branch`, `Stock Entry Detail.branch`, and branch accounting
> dimensions. The app only performs a guarded Shift-to-Stock Entry branch handoff when the host
> field already exists. See `CONTEXT.md` ("Branch Ownership Handoff").

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Frappe own all access control — add a persisted `branch` field to Stock Entry so native User Permissions isolate branches, and delete the app's custom access-control/role-management layer in favor of native Roles, DocPerms, and User Permissions.

**Architecture:** Two shippable PRs. **PR 1 (Part A)** adds the Stock Entry `branch` field + native branch isolation — additive, low risk. **PR 2 (Part B/C)** drops permlevel-9 (fields → permlevel 0) and ships Role fixtures *first*, then deletes the custom layer, so native DocPerms govern the moment the gate is removed — no window without access control. Reports/timeline stay cross-branch by design.

**Tech Stack:** Frappe/ERPNext v15 + v16 (Python 3.10+, tabs, 110-col), `FrappeTestCase`, Playwright E2E, native Frappe permission APIs.

## Global Constraints

- TDD mandatory: failing test first, then implementation. Coverage stays **≥ 90%**.
- **Tabs** for indentation. Python line length **110**. Type hints on all params + returns. User-visible strings in `_()`/`__()`.
- **No custom permission logic.** Use native Frappe mechanisms only (Roles, DocPerms, User Permissions, `frappe.has_permission`). The app never auto-assigns roles.
- Bench targets (cloud Linux env): `bench16` → `cd /root/workspace/bench16`, site **`frappe16.localhost`**, served :8002 (v16, primary). `bench15` → `cd /root/workspace/bench15`, site **`development.localhost`**, served :8000 (v15, parity).
- E2E prerequisite (executor-provided): a dev server for `frappe16.localhost` listening on `localhost:8002` before any `npx playwright test`; `developer_mode` + `allow_e2e_tests` on for that site.
- **Branch strategy:** branch off `develop`. Part A → `feat/native-alignment-phase-3` (this branch; spec already committed here). Part B/C → keep on the same branch or a follow-up `feat/native-permissions-cleanup` off `develop` after PR 1 merges.
- App under development: **no backward-compat shims** — update/delete call sites directly.
- Role names are fixed: write role `PEA User`, read role `PEA Read Only`.

---

## PR 1 — Part A: Stock Entry branch field + native branch isolation

### Task 1: Idempotent `ensure_stock_entry_branch_field()`

**Files:**
- Modify: `production_entry_app/production_entry_app/lifecycle.py`
- Test: `production_entry_app/production_entry_app/test_lifecycle.py`

**Interfaces:**
- Produces: `lifecycle.ensure_stock_entry_branch_field() -> None` — creates Custom Field `branch` (Link→Branch) on Stock Entry only if no `branch` field exists; called from `_setup_app()`.

- [ ] **Step 1: Write the failing tests**

Add to `test_lifecycle.py`:

```python
def test_ensure_branch_field_creates_when_absent(self) -> None:
	from production_entry_app.production_entry_app import lifecycle

	if frappe.get_meta("Stock Entry", cached=True).has_field("branch"):
		self.skipTest("site already has a Stock Entry branch field")
	lifecycle.ensure_stock_entry_branch_field()
	frappe.clear_cache(doctype="Stock Entry")
	df = frappe.get_meta("Stock Entry", cached=True).get_field("branch")
	assert df is not None
	assert df.fieldtype == "Link" and df.options == "Branch"


def test_ensure_branch_field_is_idempotent(self) -> None:
	from production_entry_app.production_entry_app import lifecycle

	lifecycle.ensure_stock_entry_branch_field()
	lifecycle.ensure_stock_entry_branch_field()  # second call must not raise or duplicate
	frappe.clear_cache(doctype="Stock Entry")
	fields = [f for f in frappe.get_meta("Stock Entry", cached=True).fields if f.fieldname == "branch"]
	assert len(fields) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_lifecycle`
Expected: FAIL — `ensure_stock_entry_branch_field` does not exist.

- [ ] **Step 3: Implement**

In `lifecycle.py`:

```python
def ensure_stock_entry_branch_field() -> None:
	"""Add a persisted `branch` Link field to Stock Entry only if none exists.

	Native Frappe User Permissions on Branch then isolate Stock Entry by branch.
	Reuses an existing `branch` field (native or from another app) — never duplicates.
	"""
	if frappe.get_meta("Stock Entry", cached=True).has_field("branch"):
		return
	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Stock Entry",
			"fieldname": "branch",
			"label": "Branch",
			"fieldtype": "Link",
			"options": "Branch",
			"insert_after": "company",
			"module": "Production Entry App",
			"read_only": 1,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="Stock Entry")
```

Add the call inside `_setup_app()` (before `performance_indexes`):

```python
def _setup_app() -> None:
	ensure_stock_entry_branch_field()
	access_control.ensure_access_roles_and_settings()
	field_permissions.ensure_pea_field_permissions()
	performance_indexes.ensure_performance_indexes_with_recovery()
	...
```

(The `access_control` / `field_permissions` calls are removed in PR 2; leave them for now so PR 1 is independent.)

- [ ] **Step 4: Run tests to verify they pass**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/lifecycle.py production_entry_app/production_entry_app/test_lifecycle.py
git commit -m "feat: idempotently add persisted branch field to Stock Entry"
```

### Task 2: Persist `doc.branch = shift.branch`

**Files:**
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py:163`
- Test: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`

**Interfaces:**
- Consumes: the `branch` field from Task 1.

- [ ] **Step 1: Write the failing test**

Add to `test_stock_entry_hooks.py` (uses the shared builders from Phase 2):

```python
def test_stock_entry_branch_is_populated_from_shift(self) -> None:
	from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
		bootstrap_manufacture_masters,
		make_running_shift,
		make_direct_manufacture_entry,
	)

	masters = bootstrap_manufacture_masters()
	shift = make_running_shift(masters)
	branch = frappe.db.get_value("Shift", shift.name, "branch")
	se = make_direct_manufacture_entry(masters, shift=shift.name, fg_qty=100, rejection_qty=0)
	assert se.branch == branch
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks`
Expected: FAIL — `se.branch` is empty (phantom attribute, or field just added but assignment unguarded).

- [ ] **Step 3: Implement**

In `stock_entry_hooks.py` `_apply_shift_defaults`, guard the existing assignment (around line 163):

```python
	if frappe.get_meta("Stock Entry", cached=True).has_field("branch") and shift.branch:
		doc.branch = shift.branch
```

- [ ] **Step 4: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/overrides/stock_entry_hooks.py production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "feat: persist Stock Entry branch from linked Shift"
```

### Task 3: Branch-isolation E2E

**Files:**
- Test: `tests/e2e/specs/branch-isolation.spec.js` (create)
- Modify (if needed): `production_entry_app/production_entry_app/e2e_api.py` (a helper to assign a Branch User Permission to the E2E user)

**Interfaces:**
- Consumes: Tasks 1–2.

- [ ] **Step 1: Add an E2E helper to grant a Branch User Permission**

In `e2e_api.py`, add (gated by `_assert_e2e_api_allowed`):

```python
@frappe.whitelist()
def set_e2e_branch_user_permission(user: str, branch: str) -> dict:
	"""Assign a native Branch User Permission to a user for branch-isolation E2E."""
	_assert_e2e_api_allowed()
	existing = frappe.get_all(
		"User Permission", filters={"user": user, "allow": "Branch", "for_value": branch}, pluck="name"
	)
	if not existing:
		frappe.get_doc(
			{"doctype": "User Permission", "user": user, "allow": "Branch", "for_value": branch}
		).insert(ignore_permissions=True)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit - E2E setup must persist
	return {"user": user, "branch": branch}
```

- [ ] **Step 2: Write the E2E spec**

Create `tests/e2e/specs/branch-isolation.spec.js`: bootstrap two shifts in two different branches (extend the bootstrap or create a second-branch shift via the API), create a non-admin PEA user, grant it a Branch User Permission for branch A via `set_e2e_branch_user_permission`, then as that user open the Shift list and assert only branch-A shifts appear and branch-B shifts do not. Include `error` callbacks on all `frappe.call`s and `__()` on any visible strings.

- [ ] **Step 3: Run the E2E spec**

Run: `cd /root/workspace/production-entry-app && npx playwright test specs/branch-isolation.spec.js`
Expected: PASS — branch-A user sees only branch-A Shifts.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/specs/branch-isolation.spec.js production_entry_app/production_entry_app/e2e_api.py
git commit -m "test: e2e branch isolation via native User Permissions"
```

**PR 1 boundary:** open PR with Tasks 1–3 into `develop`. Merge before PR 2.

---

## PR 2 — Part B/C: delete the custom access-control layer

### Task 4: Drop permlevel-9 — set the 43 custom fields to permlevel 0

**Files:**
- Modify: `production_entry_app/fixtures/custom_field.json`
- Test: `production_entry_app/production_entry_app/test_doctype_metadata.py`

**Interfaces:**
- Produces: no app custom field remains at permlevel 9. The stale permlevel-9 `DocPerm`
  rows the deleted sync injected are wiped by Frappe's standard-doctype reload on migrate.

- [ ] **Step 1: Write the failing test**

Add to `test_doctype_metadata.py`:

```python
def test_no_app_custom_field_uses_permlevel_9() -> None:
	import json, os

	from production_entry_app import __file__ as pkg
	path = os.path.join(os.path.dirname(os.path.dirname(pkg)), "fixtures", "custom_field.json")
	fields = json.load(open(path))
	offenders = [f["name"] for f in fields if f.get("permlevel")]
	assert offenders == [], f"custom fields still at a nonzero permlevel: {offenders}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata`
Expected: FAIL — 43 fields carry `"permlevel": 9`.

- [ ] **Step 3: Implement**

In `fixtures/custom_field.json`, set `permlevel` to `0` for every field that has
`"permlevel": 9` (43 fields across Stock Entry ×35, Item ×3, Workstation ×3,
Downtime Entry ×1, Stock Entry Detail ×1). Then re-export:

```bash
cd /root/workspace/bench16 && bench --site frappe16.localhost migrate && bench export-fixtures --app production_entry_app
```

Verify no spurious churn: `git diff --stat production_entry_app/fixtures/custom_field.json` should show only the permlevel changes.

- [ ] **Step 4: Migrate + run test to verify it passes**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost migrate && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata`
Expected: PASS. Also confirm in a console that the fields now render for a non-PEA user (permlevel 0).

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/fixtures/custom_field.json production_entry_app/production_entry_app/test_doctype_metadata.py
git commit -m "refactor: drop permlevel-9 on app custom fields (permlevel 0, native)"
```

### Task 5: Ship Role fixtures for `PEA User` / `PEA Read Only`

**Files:**
- Create: `production_entry_app/production_entry_app/fixtures/` role JSON via export, OR add to `fixtures` in `hooks.py`
- Modify: `production_entry_app/hooks.py` (`fixtures` list)
- Test: `production_entry_app/production_entry_app/test_doctype_metadata.py`

- [ ] **Step 1: Write the failing test**

Add to `test_doctype_metadata.py`:

```python
def test_pea_roles_are_shipped() -> None:
	import frappe

	assert frappe.db.exists("Role", "PEA User")
	assert frappe.db.exists("Role", "PEA Read Only")
```

- [ ] **Step 2: Run test to verify it fails on a fresh state**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata`
Expected: PASS today only because the deleted `_ensure_role` still runs; after Task 7 removes it, the fixture must guarantee the roles. To prove the fixture works, delete the roles in a console, `bench migrate`, and confirm they reappear.

- [ ] **Step 3: Implement**

Add `Role` to `hooks.py` `fixtures`, filtered to the two role names:

```python
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Production Entry App"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "Production Entry App"]]},
	{"dt": "Role", "filters": [["name", "in", ["PEA User", "PEA Read Only"]]]},
	"Downtime Reason",
	"Rejection Reason",
]
```

Ensure both roles exist, then `cd /root/workspace/bench16 && bench --site frappe16.localhost export-fixtures --app production_entry_app`.

- [ ] **Step 4: Verify reinstall**

In console delete both roles, then `bench --site frappe16.localhost migrate`, then re-run the test. Expected: PASS (roles restored from fixture).

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/hooks.py production_entry_app/production_entry_app/fixtures/ production_entry_app/production_entry_app/test_doctype_metadata.py
git commit -m "feat: ship PEA User / PEA Read Only role fixtures"
```

### Task 6: Delete the custom access-control layer

**Files:**
- Delete: `access_control.py`, `field_permissions.py`, `access_control_field_map.py`, `scripts/build_access_control_field_map.py`, `public/js/access_control.js`, `public/js/custom_field_visibility.js`, `public/js/generated_access_control_field_map.js`
- Modify: `hooks.py` (remove `has_permission` map, app-screen `has_permission`, the 3 JS/CSS includes), `lifecycle.py` (`_setup_app` slim), `api.py` (remove `get_access_control_state`), `report_utils.py` (remove `assert_report_read_access`), all ~20 report `execute()`s, `api_timeline.py`, `shift.py` (remove `Shift.has_permission` + asserts), `overrides/stock_entry_hooks.py` (remove `can_use/can_write` guards)

**Interfaces:**
- Consumes: the permlevel-0 fields (Task 4) and Role fixtures (Task 5) — must be in
  place first so native DocPerms govern access the moment the custom gate is removed.

- [ ] **Step 1: Slim `_setup_app()`**

`lifecycle._setup_app()` becomes (keeping only the Task 1 branch-field call + indexes):

```python
def _setup_app() -> None:
	ensure_stock_entry_branch_field()
	performance_indexes.ensure_performance_indexes_with_recovery()
```

Remove the `access_control`/`field_permissions` imports and the Phase 1 DocPerm-reconciliation log line.

- [ ] **Step 2: Remove the hooks**

In `hooks.py`: delete the entire `has_permission = {...}` map; change `add_to_apps_screen[0]` to drop the `"has_permission"` key; remove `access_control.js`, `custom_field_visibility.js`, `generated_access_control_field_map.js` from `app_include_js` and the access-control CSS from `app_include_css` (keep `time_entry_fields.*` and `report_filter_utils.js`, `timeline_renderer.js`).

- [ ] **Step 3: Remove report asserts (bulk)**

For each report under `production_entry_app/production_entry_app/report/*/`: delete the `assert_report_read_access,` name from the `report_utils` import and delete the `assert_report_read_access()` call line in `execute()`. Then remove `assert_report_read_access` from `report_utils.py`.

Run: `grep -rln "assert_report_read_access" production_entry_app` to confirm zero matches when done.

- [ ] **Step 4: Remove API/controller asserts + get_access_control_state**

- `api.py`: delete `get_access_control_state`; delete `access_control` import and every `assert_app_read_access()` / `assert_app_write_access()` call (endpoint gating is handled in Task 8).
- `api_timeline.py`: delete the `assert_app_read_access()` calls (native `has_permission` added in Task 8).
- `shift.py`: delete the `Shift.has_permission` method (lines ~1018-1020) and every `assert_app_*` call in the whitelisted methods.
- `overrides/stock_entry_hooks.py`: remove the `can_use_production_entry_app()` early-return guard (line ~65) and the `can_write_production_entry_app` / `assert_app_write_access` calls — the validate hook runs for all Stock Entries regardless; native DocPerms gate writes.
- `e2e_api.py`: delete the whole `set_e2e_access_control` function; remove the `access_control, field_permissions` import (line 10); remove all 7 `access_control.assert_app_write_access()` calls (the endpoints are already gated by `_assert_e2e_api_allowed`). Replace any `sync_configured_access_roles` usage with native role assignment (`frappe.get_doc("User", user).add_roles("PEA User")`).

- [ ] **Step 5: Delete the modules + JS**

```bash
git rm production_entry_app/production_entry_app/access_control.py \
       production_entry_app/production_entry_app/field_permissions.py \
       production_entry_app/production_entry_app/access_control_field_map.py \
       scripts/build_access_control_field_map.py \
       production_entry_app/public/js/access_control.js \
       production_entry_app/public/js/custom_field_visibility.js \
       production_entry_app/public/js/generated_access_control_field_map.js
```

- [ ] **Step 6: Confirm no dangling references**

Run: `grep -rn "access_control\|field_permissions\|assert_app_\|assert_report_read_access\|has_gated_doctype_permission\|get_access_control_state" --include=*.py production_entry_app | grep -v test_`
Expected: zero production (non-test) matches. Remove any that remain.

- [ ] **Step 7: Verify the app imports + build**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost migrate && bench build --app production_entry_app`
Expected: no ImportError; assets build.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: delete custom access-control layer, rely on native Frappe perms"
```

### Task 7: Remove the Settings access-control fields

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.json`
- Test: `production_entry_app/production_entry_app/test_doctype_metadata.py`

- [ ] **Step 1: Write the failing test**

```python
def test_settings_has_no_access_control_fields() -> None:
	import frappe

	meta = frappe.get_meta("Production Entry Settings")
	for fieldname in (
		"enable_access_control",
		"write_role",
		"read_role",
		"last_synced_write_role",
		"last_synced_read_role",
	):
		assert not meta.has_field(fieldname), fieldname
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata`
Expected: FAIL — fields still present.

- [ ] **Step 3: Implement**

Remove those five field definitions (and any now-empty section break) from `production_entry_settings.json`.

- [ ] **Step 4: Migrate + run test**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost migrate && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.json production_entry_app/production_entry_app/test_doctype_metadata.py
git commit -m "refactor: remove runtime access-control fields from settings"
```

### Task 8: Endpoint gating (native best practice)

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`, `api.py`, `api_timeline.py`
- Test: `production_entry_app/production_entry_app/test_api.py`

**Interfaces:**
- Produces: document-scoped read endpoints gated by `frappe.has_permission`; `reset_die_tool_counter` gated by native DocPerm (no `ignore_permissions`).

- [ ] **Step 1: Write the failing tests**

Add to `test_api.py`:

```python
def test_get_shift_summary_denies_without_read_perm(self) -> None:
	from production_entry_app.production_entry_app.doctype.shift.shift import get_shift_summary
	from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
		bootstrap_manufacture_masters, make_running_shift,
	)

	shift = make_running_shift(bootstrap_manufacture_masters())
	user = "phase3-noperm@example.com"
	if not frappe.db.exists("User", user):
		frappe.get_doc({"doctype": "User", "email": user, "first_name": "NoPerm",
			"roles": [{"role": "Manufacturing User"}]}).insert(ignore_permissions=True)
	frappe.set_user(user)
	try:
		with self.assertRaises(frappe.PermissionError):
			get_shift_summary(shift.name)
	finally:
		frappe.set_user("Administrator")


def test_reset_die_tool_counter_denied_for_read_only(self) -> None:
	from production_entry_app.production_entry_app import api

	user = "phase3-readonly@example.com"
	if not frappe.db.exists("User", user):
		frappe.get_doc({"doctype": "User", "email": user, "first_name": "ReadOnly",
			"roles": [{"role": "PEA Read Only"}]}).insert(ignore_permissions=True)
	die_item = frappe.get_all("Die Tool Counter", limit=1, pluck="die_tool_item")
	die_code = die_item[0] if die_item else None
	self.assertIsNotNone(die_code, "seed a Die Tool Counter item in setUp")
	frappe.set_user(user)
	try:
		with self.assertRaises(frappe.PermissionError):
			api.reset_die_tool_counter(die_code)
	finally:
		frappe.set_user("Administrator")
```

(Seed a Die Tool Counter item in `setUp` via the shared builders / `ensure_item` + `is_die_tool_enabled` fixture so `die_code` is non-null.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api`
Expected: FAIL — after Task 7 the endpoints have no gate.

- [ ] **Step 3: Implement read gating**

Ensure each document-scoped reader retains/adds a native check. `get_shift_summary`, `get_shift_details_for_stock_entry` already have `if not frappe.has_permission("Shift", "read", shift_name): raise frappe.PermissionError` — keep it. Add the same to `get_shift_aggregate_production_entries`, `get_linked_downtime_entries` (gate on their `shift_name`), and `api_timeline.get_shift_timeline_data` (gate on the `docname`/its shift context). `get_die_tool_counter` stays open (trivial lookup).

- [ ] **Step 4: Implement write gating**

In `api.py` `reset_die_tool_counter`, remove `ignore_permissions=True` from the `Die Tool Maintenance Log` `.insert(...)` and delete the `maintenance_log.flags.ignore_permissions = True` line (api.py:242-243) so native create/submit DocPerms gate it. **Do not** touch `utils/die_tool_counter.py:95` — that counter insert runs inside the Stock Entry submit hook (system path) and must keep `ignore_permissions`.

- [ ] **Step 5: Run tests to verify pass**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add production_entry_app/production_entry_app/doctype/shift/shift.py production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/api_timeline.py production_entry_app/production_entry_app/test_api.py
git commit -m "feat: gate endpoints with native has_permission / DocPerms"
```

### Task 9: Rewrite the access-control test suite

**Files:**
- Delete: `test_access_control.py`, `test_access_control_field_map.py`, `test_access_control_whitelisted_api.py`, `test_access_control_doctypes.py`, `test_field_permissions.py`, `test_permission_hooks.py`, `tests/compat/test_v16_permission_hooks.py`, and the E2E `specs/permissions.spec.js`, `specs/access-control-role-branch.spec.js` (they test deleted custom logic)
- Create: `test_native_permissions.py`
- Modify: `e2e_api.py` (drop `set_e2e_access_control` if now unused)

- [ ] **Step 1: Delete tests for removed logic**

```bash
git rm production_entry_app/production_entry_app/test_access_control.py \
       production_entry_app/production_entry_app/test_access_control_field_map.py \
       production_entry_app/production_entry_app/test_access_control_whitelisted_api.py \
       production_entry_app/production_entry_app/test_access_control_doctypes.py \
       production_entry_app/production_entry_app/test_field_permissions.py \
       production_entry_app/production_entry_app/test_permission_hooks.py \
       production_entry_app/production_entry_app/tests/compat/test_v16_permission_hooks.py \
       tests/e2e/specs/permissions.spec.js \
       tests/e2e/specs/access-control-role-branch.spec.js
```

- [ ] **Step 2: Write native-permission tests**

Create `test_native_permissions.py` asserting outcomes via native perms: a `PEA User` can create/read/write a Shift; a `PEA Read Only` can read but `frappe.has_permission("Shift", "write")` is False; a user with neither role has no read. Use `frappe.set_user` + role assignment; no reference to deleted modules.

- [ ] **Step 3: Run the new suite**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_native_permissions`
Expected: PASS.

- [ ] **Step 4: Remove now-unused E2E helpers**

If `set_e2e_access_control` / `sync_configured_access_roles` are no longer referenced by any spec (grep `tests/`), delete them from `e2e_api.py`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: replace custom access-control tests with native-permission tests"
```

### Task 10: Full verification + coverage gate

**Files:** none (verification only)

- [ ] **Step 1: Full Python suite + coverage on v16**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --with-coverage`
Expected: all pass; coverage ≥ 90%.

- [ ] **Step 2: Full Python suite on v15**

Run: `cd /root/workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app`
Expected: all pass.

- [ ] **Step 3: Full E2E suite**

Run: `cd /root/workspace/production-entry-app && npx playwright test`
Expected: all pass (including `branch-isolation.spec.js`).

- [ ] **Step 4: Lint**

Run: `pre-commit run --all-files`
Expected: clean.

- [ ] **Step 5: Rollout note in README**

Add under README admin notes: the app is always role-gated; assign `PEA User` / `PEA Read Only` to users who need it (`System Manager` retains full access); no open mode; branch isolation assumes System Settings `apply_strict_user_permissions` stays OFF (empty-branch Stock Entries stay visible to branch-restricted users otherwise).

- [ ] **Step 6: Open PR 2**

Push and open PR into `develop` referencing this plan and the spike record.

---

## Tripwire / accepted outcomes (document in README)

- Reports and the timeline remain cross-branch visible by design.
- The app is always role-gated; no open mode; roles are fixed (`PEA User` / `PEA Read Only`), re-pointed via Role Permission Manager.
- Role assignment is a manual admin step; the app never auto-grants roles.
