# Playwright E2E Expansion Plan for `production_entry_app`

## Implementation Status
- Phase 1: Completed
- Phase 2: Completed
- Phase 3: Completed
- Phase 4: Completed
- Phase 5: Completed
- Phase 6: Completed
- Phase 7: Completed

Phase 7 implementation file: `tests/e2e/specs/permissions.spec.js`.
Execution note: the `Downtime Reason` route is validated in browser and covered by an enforced permission scenario.

## Summary
Current E2E coverage is narrow (3 scenarios, mostly happy-path + API assertions). Unit tests cover many business rules that are not exercised through browser workflows.  
This plan adds missing Playwright E2E coverage with two tiers:

- `@smoke`: fast, high-signal PR checks.
- `@regression`: deeper validation/edge scenarios for nightly (and optional manual CI run).

## Coverage Gap Matrix (What’s Missing Today)
- **Shift UI/behavior gaps**
1. Cancel flow (`Draft -> Cancelled`) not tested in browser.
2. Start blocked when another shift is running not tested from UI.
3. Overlap and duplicate label/date validation not tested from form submission.
4. Planned losses auto-population/repopulation and lock-after-start not tested in UI.
5. Linked downtime rendering and “Create Downtime Entry” action not tested.
6. “Create Production Entry” action from Running shift not tested.
- **Stock Entry UI/behavior gaps**
1. `custom_shift` filter (`Running` only) not tested.
2. Shift auto-fill + clear behavior (branch/planned dates/warehouses) not tested via real field interactions.
3. Buffer validations for actual start/end ranges not tested via UI.
4. Rejection breakup negative validations (missing rows, sum mismatch, reason missing) not tested in browser.
5. `custom_fetch_items` precondition (qty required) message not tested.
6. Rejection row idempotency on resave not tested.
7. Die-tool warning headline + maintenance due flag behavior not tested in browser.
8. Unplanned losses table interaction not tested.
- **Reports gaps**
1. Current E2E calls report Python `execute` directly; query-report filter UI and refresh behavior are not truly tested.
2. UI filtering by shift/operator/workstation/FG item not tested end-to-end.
- **Permissions/role gaps**
1. Browser-level role permissions (`Manufacturing User/Manager` vs non-manufacturing) are not covered in Playwright.

## Public APIs / Interfaces / Types
No production API changes required for this plan.  
Test-only additions:

1. New Playwright specs under `tests/e2e/specs/`.
2. Expanded page objects:
   - `tests/e2e/pages/shift-page.js`
   - `tests/e2e/pages/stock-entry-page.js`
   - `tests/e2e/pages/reports-page.js`
3. Optional new fixture helpers:
   - `tests/e2e/fixtures/users.js` for role-scoped test users.
   - `tests/e2e/fixtures/assertions.js` for common Frappe toast/error assertions.
4. Tagging policy: all new tests explicitly marked `@smoke` or `@regression`.

## Implementation Phases

### Phase 1: Stabilize Test Infrastructure
1. Add deterministic per-test setup/cleanup wrappers for all new specs using existing prefix strategy.
2. Add utility to assert Frappe validation toasts/dialogs consistently.
3. Ensure each spec is data-isolated and never depends on another spec’s side effects.
4. Acceptance: repeated run of smoke suite is stable across 5 consecutive runs.

### Phase 2: Shift E2E Parity
Create `tests/e2e/specs/shift-validations.spec.js` and extend `shift-lifecycle.spec.js`.

Scenarios:
1. `@smoke` Draft shift can be cancelled; status becomes `Cancelled`.
2. `@regression` Starting second shift while one is Running is blocked with validation error.
3. `@regression` Overlap validation prevents save of overlapping shift.
4. `@regression` Unique shift label/date validation prevents duplicate.
5. `@regression` Planned losses auto-populate for 8/10/12 hour durations and repopulate when duration changes.
6. `@regression` Planned losses grid becomes non-editable once shift starts.
7. `@regression` Linked downtime section renders overlapping downtime entries.

### Phase 3: Shift → Stock Entry Integration E2E
Create `tests/e2e/specs/shift-to-stock-entry.spec.js`.

Scenarios:
1. `@smoke` From Running shift, “Create > Production Entry” opens new Stock Entry with `custom_shift` prefilled.
2. `@regression` Selecting `custom_shift` auto-fills branch/planned dates/from_warehouse/to_warehouse.
3. `@regression` Clearing `custom_shift` clears those auto-filled fields.
4. `@regression` `custom_shift` link query shows only Running shifts.

### Phase 4: Stock Entry Validation Matrix E2E
Create `tests/e2e/specs/stock-entry-validations.spec.js`.

Scenarios:
1. `@smoke` `custom_fetch_items` requires qty and shows message when missing.
2. `@regression` Rejection qty > 0 with empty breakup blocks save.
3. `@regression` Breakup total mismatch blocks save.
4. `@regression` Breakup row without reason blocks save.
5. `@regression` Rejection qty > FG qty blocks save.
6. `@regression` Actual start/end outside buffer blocks save with range message.
7. `@regression` Actual end before actual start blocks save.
8. `@regression` Unplanned loss row can be added and persists after save.
9. `@regression` Re-save remains idempotent (single rejection row, FG qty remains adjusted).

### Phase 5: Metrics + Die Tool UI E2E
Create `tests/e2e/specs/die-tool-metrics.spec.js`.

Scenarios:
1. `@smoke` Submitted manufacture entry populates duration/SPM/cycle/efficiency fields.
2. `@regression` Missing actual end keeps metrics empty.
3. `@regression` Zero-duration clears metrics.
4. `@regression` High utilization shows maintenance-due field + dashboard warning.
5. `@regression` Validate die-tool counter increases on submit and decreases on cancel (via API checks after UI actions).

### Phase 6: True Query Report UI E2E
Replace API-only assertions in report tests with actual report UI filter interactions.

Work:
1. Extend `ReportsPage` with:
   - set filter by field label/fieldname.
   - click refresh.
   - wait for datatable rows.
   - extract first-row values for assertions.
2. Create/extend `tests/e2e/specs/reports-ui.spec.js`.

Scenarios:
1. `@smoke` OEE report shows seeded entry for date range.
2. `@regression` OEE report honors `fg_item` filter.
3. `@regression` Operator report honors operator + shift filters.
4. `@regression` Workstation report honors workstation + shift filters.
5. `@regression` Die Tool report honors item filter and shows maintenance columns.

### Phase 7: Browser Permission E2E
Create `tests/e2e/specs/permissions.spec.js`.

Scenarios:
1. `@regression` Manufacturing User can create/read/update/delete Shift in UI.
2. `@regression` Manufacturing Manager can perform same operations.
3. `@regression` Non-manufacturing user cannot access Shift list/form (permission error or redirect).
4. `@regression` Manufacturing user can CRUD Downtime Reason (if UI route available).

## Test Execution and CI Plan
1. Keep existing script:
   - `npm run test:e2e` => `@smoke` only.
2. Add/confirm regression script:
   - `npm run test:e2e:ci` (all tags) for nightly/full pipeline.
3. Tag distribution target:
   - Add ~6-8 new `@smoke` tests.
   - Add ~20-30 `@regression` tests for deep parity.
4. Add flaky-test guardrails:
   - avoid brittle text-only locators for Frappe dialogs.
   - assert via doc reload/API when UI state may lag.

## Acceptance Criteria
1. Every major rule currently validated in unit tests has at least one corresponding UI E2E assertion or an explicitly documented exclusion.
2. Smoke suite remains fast and deterministic for PR use.
3. Regression suite validates negative paths and edge cases end-to-end using real browser interactions.
4. No cross-test data coupling; each test independently bootstraps and cleans up.

## Assumptions and Defaults
1. Chosen depth: **Full parity** with unit-tested high-value behaviors.
2. Chosen CI strategy: **Two tiers** (`@smoke` for PR, `@regression` for nightly/full runs).
3. Existing E2E bootstrap APIs remain available and are the primary seed mechanism.
4. Playwright continues with `workers: 1` due to global running-shift constraint.
