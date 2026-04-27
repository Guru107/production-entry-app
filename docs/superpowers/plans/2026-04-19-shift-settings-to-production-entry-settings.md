# Shift Settings Move to Production Entry Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Shift Settings from ERPNext `Manufacturing Settings` custom fields to `Production Entry Settings` so Production Entry module settings are centralized.

**Architecture:** Add shift-related fields to `Production Entry Settings`, remove Manufacturing Settings custom-field dependency, and refactor all read/write call sites to use a single settings source. Keep behavior intact with no migration/backfill.

**Tech Stack:** Frappe/ERPNext (Python), DocType JSON/fixtures, JS unit tests, Playwright E2E.

---

## Task 1: Add Shift Fields to Production Entry Settings

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.json`
- Modify: `production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.py`
- Test: `production_entry_app/production_entry_app/test_access_control.py`

- [ ] **Step 1: Write failing metadata tests**
- [ ] **Step 2: Run focused test to confirm failure**
- [ ] **Step 3: Add settings fields** (`shift_raw_material_warehouse`, `shift_wip_warehouse`, `shift_rejection_warehouse`, `shift_scrap_warehouse`, `shift_start_buffer_mins`, `shift_end_buffer_mins`)
- [ ] **Step 4: Keep validation coherent** (`required_role` + access-control validation unaffected)
- [ ] **Step 5: Run focused tests and commit**

## Task 2: Remove Manufacturing Settings Shift Custom Fields

**Files:**
- Modify: `production_entry_app/fixtures/custom_field.json`
- Test: `production_entry_app/production_entry_app/test_access_control_field_map.py`

- [ ] **Step 1: Remove Shift Settings tab/section/field entries under `Manufacturing Settings`**
- [ ] **Step 2: Validate fixture JSON integrity**
- [ ] **Step 3: Run affected fixture/field-map tests and commit**

## Task 3: Refactor Backend Reads/Writes to Production Entry Settings

**Files:**
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Modify: `production_entry_app/production_entry_app/api.py`
- Modify: `production_entry_app/production_entry_app/utils/test_bootstrap.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_override.py`
- Modify: `production_entry_app/production_entry_app/utils/test_test_bootstrap.py`

- [ ] **Step 1: Write failing tests for settings source expectations**
- [ ] **Step 2: Replace `Manufacturing Settings` get/set single-value calls with `Production Entry Settings` equivalents**
- [ ] **Step 3: Update user-facing text references to `Production Entry Settings`**
- [ ] **Step 4: Run targeted Python modules and commit**

## Task 4: Update Frontend Visibility Field Map and Related JS Expectations

**Files:**
- Modify: `scripts/build_access_control_field_map.py`
- Modify: `production_entry_app/public/js/generated_access_control_field_map.js`
- Modify (if needed): `production_entry_app/public/js/custom_field_visibility.js`
- Modify (if needed): `production_entry_app/public/js/stock_entry.js`
- Test: `tests/unit/stock-entry-visibility.test.js`

- [ ] **Step 1: Update generator source mapping to new doctype ownership**
- [ ] **Step 2: Regenerate map artifact**
- [ ] **Step 3: Update JS tests/assertions as needed**
- [ ] **Step 4: Run JS unit tests and commit**

## Task 5: Update E2E Setup and Runtime Settings Mutation

**Files:**
- Modify: `tests/e2e/specs/access-control-role-branch.spec.js`
- Modify (if needed): `tests/e2e/fixtures/frappe.js`
- Modify (if needed): `tests/e2e/fixtures/test-data.js`

- [ ] **Step 1: Replace any `Manufacturing Settings` shift-field mutations with `Production Entry Settings`**
- [ ] **Step 2: Keep role-only access flow coverage intact**
- [ ] **Step 3: Run targeted Playwright spec (or capture precise environment blocker) and commit**

## Task 6: Full Verification and Bench Rollout Sanity

**Files:**
- No feature files; verification + possible small follow-up fixes.

- [ ] **Step 1: Run `pre-commit --all-files`**
- [ ] **Step 2: Run focused Python test modules**
- [ ] **Step 3: Run JS unit tests + targeted E2E**
- [ ] **Step 4: Run `bench migrate` on bench15 and bench16, then verify shifted settings exist and are used**
- [ ] **Step 5: Commit any verification follow-up fixes**

## Verification Commands
```bash
pre-commit run --all-files

cd $BENCH_DIR
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_override
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_test_bootstrap

cd $APP_DIR
node --test tests/unit/stock-entry-visibility.test.js
npx playwright test tests/e2e/specs/access-control-role-branch.spec.js
```

## Completion Criteria
- Shift settings are stored and managed only via `Production Entry Settings`.
- No runtime path depends on `Manufacturing Settings` shift custom fields.
- Field map and visibility logic reflect the new doctype ownership.
- Focused test suites pass, or blockers are explicitly documented with exact root cause.
