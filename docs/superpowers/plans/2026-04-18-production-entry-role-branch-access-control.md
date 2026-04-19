# Production Entry Role-Branch Access Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce role+branch gated access so denied users experience Production Entry App as unavailable, while native ERPNext `Stock Entry` (including `Manufacture`) remains usable without app custom behavior.

**Architecture:** Add one centralized access-control service backed by `Production Entry Settings` allow rules. Reuse it across app visibility, DocType permissions (doc-level + doctype-level), whitelisted API guards, Stock Entry server passthrough, and client-side field hiding driven from fixture metadata.

**Tech Stack:** Frappe/ERPNext v15-v16, Python, JavaScript, Playwright, bench test runner, pre-commit

---

## File Map

- Create: `production_entry_app/production_entry_app/access_control.py`
- Create: `production_entry_app/production_entry_app/test_access_control.py`
- Create: `production_entry_app/production_entry_app/test_access_control_doctypes.py`
- Create: `production_entry_app/production_entry_app/test_access_control_whitelisted_api.py`
- Create: `production_entry_app/production_entry_app/test_access_control_field_map.py`
- Create: `production_entry_app/production_entry_app/doctype/production_entry_settings/`*
- Create: `production_entry_app/production_entry_app/doctype/production_entry_access_rule/*`
- Modify: `production_entry_app/hooks.py`
- Modify: `production_entry_app/production_entry_app/api.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Modify: `production_entry_app/production_entry_app/doctype/loss_entry/loss_entry.py`
- Modify: `production_entry_app/production_entry_app/doctype/downtime_reason/downtime_reason.py`
- Modify: `production_entry_app/production_entry_app/doctype/operator/operator.py`
- Modify: `production_entry_app/production_entry_app/doctype/die_tool_counter/die_tool_counter.py`
- Modify: `production_entry_app/production_entry_app/doctype/die_tool_maintenance_log/die_tool_maintenance_log.py`
- Modify: `production_entry_app/production_entry_app/doctype/rejection_reason/rejection_reason.py`
- Modify: `production_entry_app/production_entry_app/doctype/rejection_breakup/rejection_breakup.py`
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry.py`
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Create/Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_access_control.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- Create: `production_entry_app/public/js/access_control.js`
- Create: `production_entry_app/public/js/custom_field_visibility.js`
- Modify: `production_entry_app/public/js/stock_entry.js`
- Modify: `production_entry_app/public/js/workstation.js`
- Modify: `production_entry_app/public/js/operator.js`
- Modify: `production_entry_app/fixtures/custom_field.json`
- Create: `scripts/build_access_control_field_map.py`
- Create/Modify: `tests/e2e/specs/access-control-role-branch.spec.js`

## Task 1: Access-Control Core Service (TDD)

**Files:**

- Create: `production_entry_app/production_entry_app/test_access_control.py`
- Create: `production_entry_app/production_entry_app/access_control.py`
- **Step 1: Write failing tests**

Add tests:

```python
def test_system_manager_always_allowed() -> None: ...
def test_disabled_control_allows_non_manager() -> None: ...
def test_exact_role_branch_match_allows() -> None: ...
def test_role_match_branch_mismatch_denies() -> None: ...
def test_no_rules_enabled_denies_non_manager() -> None: ...
def test_branch_resolution_default_then_single_permission() -> None: ...
def test_branch_resolution_multiple_permissions_denies() -> None: ...
def test_missing_or_corrupt_settings_fail_closed_for_non_manager() -> None: ...
def test_missing_or_corrupt_settings_logs_error_and_allows_system_manager() -> None: ...
```

- **Step 2: Run and confirm failure**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control
```

Expected: FAIL.

- **Step 3: Implement minimal service**

Implement in `access_control.py`:

- `can_use_production_entry_app(user: str | None = None) -> bool`
- `has_app_permission() -> bool`
- `assert_app_access() -> None` for whitelisted APIs
- `has_gated_doctype_permission(doc=None, ptype: str = "read", user: str | None = None) -> bool`
- cache + deterministic branch resolution + fail-closed logging
- **Step 4: Re-run tests**

Run Step 2 command. Expected: PASS.

- **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/access_control.py production_entry_app/production_entry_app/test_access_control.py
git commit -m "feat: add centralized access control service"
```

## Task 2: Settings DocTypes + App Visibility Hook

**Files:**

- Create: `production_entry_app/production_entry_app/doctype/production_entry_settings/`*
- Create: `production_entry_app/production_entry_app/doctype/production_entry_access_rule/*`
- Modify: `production_entry_app/hooks.py`
- **Step 1: Write failing settings tests**

```python
def test_settings_default_enable_access_control_is_zero() -> None: ...
def test_settings_update_invalidates_access_cache() -> None: ...
def test_non_admin_cannot_modify_production_entry_settings() -> None: ...
```

- **Step 2: Run tests and confirm failure**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control
```

- **Step 3: Implement schema and hooks**
- add single doctype with `enable_access_control` default `0`
- add child table for `(role, branch, is_active)`
- add admin-only edit permissions
- add `on_update` cache invalidation
- enable `add_to_apps_screen` with `access_control.has_app_permission`
- **Step 4: Run migrate (schema sync)**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost migrate
```

- **Step 5: Re-run tests**

Run Step 2 command. Expected: PASS.

- **Step 6: Commit**

```bash
git add production_entry_app/hooks.py production_entry_app/production_entry_app/doctype/production_entry_settings production_entry_app/production_entry_app/doctype/production_entry_access_rule
git commit -m "feat: add access control settings doctypes"
```

## Task 3: Gate App DocTypes (Doc + Doctype Level)

**Files:**

- Modify: all listed app doctype controllers
- Modify: `production_entry_app/hooks.py`
- Create: `production_entry_app/production_entry_app/test_access_control_doctypes.py`
- Modify: `production_entry_app/production_entry_app/tests/compat/test_v16_permission_hooks.py`
- **Step 1: Write failing permission tests**

```python
def test_denied_user_cannot_access_all_gated_doctypes_doc_level() -> None: ...
def test_denied_user_cannot_access_list_or_create_for_gated_doctypes() -> None: ...
def test_allowed_user_can_access_gated_doctypes() -> None: ...
def test_system_manager_bypass_allows_all_gated_doctypes() -> None: ...
def test_permission_hooks_return_explicit_bool() -> None: ...
```

Covered doctypes:

- `Shift`, `Loss Entry`, `Downtime Reason`, `Operator`, `Die Tool Counter`, `Die Tool Maintenance Log`, `Rejection Reason`, `Rejection Breakup`
- **Step 2: Run tests and confirm failure**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control_doctypes
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.tests.compat.test_v16_permission_hooks
```

- **Step 3: Implement gates**
- add controller `has_permission(...) -> bool`
- add `hooks.py` `has_permission` mapping to `access_control.has_gated_doctype_permission` so `doc=None` (list/create) paths are also denied
- **Step 4: Re-run tests**

Run Step 2 commands. Expected: PASS.

- **Step 5: Commit**

```bash
git add production_entry_app/hooks.py production_entry_app/production_entry_app/doctype production_entry_app/production_entry_app/test_access_control_doctypes.py production_entry_app/production_entry_app/tests/compat/test_v16_permission_hooks.py
git commit -m "feat: enforce doctype access control for production entry doctypes"
```

## Task 4: Gate Whitelisted App APIs

**Files:**

- Modify: `production_entry_app/production_entry_app/api.py`
- Modify: app modules exposing `@frappe.whitelist` (including `shift.py`)
- Create: `production_entry_app/production_entry_app/test_access_control_whitelisted_api.py`
- **Step 1: Add failing API access tests**

```python
def test_denied_user_cannot_call_gated_whitelisted_apis() -> None: ...
def test_allowed_user_can_call_required_whitelisted_apis() -> None: ...
```

- **Step 2: Inventory all whitelisted APIs**

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
rg -n "@frappe\.whitelist" production_entry_app/production_entry_app -g'*.py'
```

- **Step 3: Implement API guard calls**
- call `assert_app_access()` at top of each gated whitelisted method
- keep explicit allowlist only for required test/bootstrap endpoints, documented in test file
- explicitly allowlist `production_entry_app.production_entry_app.api.get_access_control_state`
so denied users can fetch UI gating state
- record final allowlisted endpoints in test docs:
  - `production_entry_app.production_entry_app.api.get_access_control_state`
  - any test/bootstrap-only endpoints explicitly approved for denied-user execution
- **Step 4: Run tests**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control_whitelisted_api
```

Expected: PASS.

- **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/doctype/shift/shift.py production_entry_app/production_entry_app/test_access_control_whitelisted_api.py production_entry_app/production_entry_app/access_control.py
git commit -m "feat: enforce access control on whitelisted app apis"
```

## Task 5: Stock Entry Native Passthrough (Server)

**Files:**

- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry.py`
- Create/Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_access_control.py`
- **Step 1: Add failing passthrough tests**

```python
def test_denied_user_validate_hook_skips_app_logic() -> None: ...
def test_denied_user_submit_cancel_skip_app_side_effects() -> None: ...
def test_denied_user_finished_item_row_uses_native_behavior() -> None: ...
```

- **Step 2: Run tests and confirm failure**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_access_control
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

- **Step 3: Implement short-circuit logic**
- early return in stock-entry hooks for denied users
- fallback behavior in override class for denied users
- **Step 4: Re-run tests**

Run Step 2 commands. Expected: PASS.

- **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/overrides/stock_entry_hooks.py production_entry_app/production_entry_app/overrides/stock_entry.py production_entry_app/production_entry_app/overrides/test_stock_entry_access_control.py production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "feat: preserve native stock entry behavior for denied users"
```

## Task 6: Client JS Guard + Fixture-Derived Field Hiding

**Files:**

- Create: `production_entry_app/public/js/access_control.js`
- Create: `production_entry_app/public/js/custom_field_visibility.js`
- Modify: `production_entry_app/public/js/stock_entry.js`
- Modify: `production_entry_app/public/js/workstation.js`
- Modify: `production_entry_app/public/js/operator.js`
- Modify: `production_entry_app/hooks.py`
- Modify: `production_entry_app/production_entry_app/api.py`
- Modify: `production_entry_app/fixtures/custom_field.json`
- Create: `scripts/build_access_control_field_map.py`
- Create: `production_entry_app/production_entry_app/test_access_control_field_map.py`
- Create/Modify: `tests/e2e/specs/access-control-role-branch.spec.js`
- **Step 1: Add failing E2E + field-map tests**

```python
def test_fixture_derived_field_map_matches_target_core_doctypes() -> None: ...
```

```js
test("denied user cannot see app module", async ({ page }) => { ... });
test("denied user cannot open production entry workspace/direct routes", async ({ page }) => { ... });
test("denied user sees native stock entry and hidden app fields", async ({ page }) => { ... });
test("allowed user retains production entry stock flow", async ({ page }) => { ... });
test("system manager bypass works", async ({ page }) => { ... });
```

- **Step 2: Run and confirm failure**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control_field_map
cd /Users/gurudattkulkarni/Workspace/production-entry-app
npx playwright test tests/e2e/specs/access-control-role-branch.spec.js --project=chromium
```

- **Step 3: Implement client contract and map generation**
- add whitelisted endpoint `production_entry_app.production_entry_app.api.get_access_control_state` returning `{"enabled": bool}`
- `access_control.js` caches that value per page session
- enforce direct workspace/route denial server-side via `hooks.py` `has_permission` mapping for
gated app doctypes (covers list/new routes) and whitelist guards for app page data APIs
- field-map contract:
input fixture: `production_entry_app/fixtures/custom_field.json`
generated artifact: `production_entry_app/public/js/generated_access_control_field_map.js`
load order: include generated artifact in `hooks.py` before `custom_field_visibility.js`
runtime consumer: `custom_field_visibility.js` reads generated map constant
- `build_access_control_field_map.py` derives map from fixture input for target core doctypes:
`Stock Entry`, `Stock Entry Detail`, `Item`, `Workstation`, `Manufacturing Settings`, `Downtime Entry`
- `custom_field_visibility.js` hides those fields for denied users
- `stock_entry.js` bypasses app JS for denied users
- run generator then check mode to prevent drift:

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
python scripts/build_access_control_field_map.py
python scripts/build_access_control_field_map.py --check
```

- **Step 4: Re-run tests**

Run Step 2 commands. Expected: PASS.

- **Step 5: Commit**

```bash
git add production_entry_app/public/js/access_control.js production_entry_app/public/js/custom_field_visibility.js production_entry_app/public/js/generated_access_control_field_map.js production_entry_app/public/js/stock_entry.js production_entry_app/public/js/workstation.js production_entry_app/public/js/operator.js production_entry_app/hooks.py production_entry_app/production_entry_app/api.py production_entry_app/fixtures/custom_field.json scripts/build_access_control_field_map.py production_entry_app/production_entry_app/test_access_control_field_map.py tests/e2e/specs/access-control-role-branch.spec.js
git commit -m "feat: hide app custom ui for denied users"
```

## Task 7: Full Verification Gate

- **Step 1: Migrate before full validation**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost migrate
```

- **Step 2: Run focused Python suites**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control_doctypes
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control_whitelisted_api
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control_field_map
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_access_control
```

- **Step 3: Run app-wide tests (time permitting)**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app
```

- **Step 4: Run access E2E suite**

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
npx playwright test tests/e2e/specs/access-control-role-branch.spec.js
```

- **Step 5: Validate v16 hook semantics**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.tests.compat.test_v16_permission_hooks
```

- **Step 6: Run lint/format checks**

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
pre-commit run --all-files
```

- **Step 7: Final residual commit**

```bash
git add -A
git commit -m "test: finalize role-branch access control regressions"
```

## Task 8: Manual Rollout Checklist

- Seed allow rules in `Production Entry Settings` (example: `Manufacturing User` + `Nashik`)
- Confirm denied user: module hidden, app routes blocked, native stock entry usable
- Confirm allowed user: current production entry behavior unchanged
- Confirm System Manager bypass
- Record rollback: set `enable_access_control = 0`

## Notes for Implementers

- Keep logic explicit and centralized in `access_control.py`.
- Do not delete schema custom fields in this phase.
- Fail closed for non-System Manager when branch/settings cannot be resolved.

## Superseded

Superseded on 2026-04-19 by the role-only access plan:
- `docs/superpowers/specs/2026-04-19-production-entry-pea-role-access-design.md`
- `docs/superpowers/plans/2026-04-19-production-entry-pea-role-access-control.md`
