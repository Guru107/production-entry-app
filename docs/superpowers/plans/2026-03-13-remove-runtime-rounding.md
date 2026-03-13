# Remove Runtime Rounding Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** remove application-owned rounding from runtime and user-facing paths, keep numeric coercion, and update tests so backend math returns raw values while Frappe owns display precision.

**Architecture:** make the change in layers. First remove rounded intermediates from shared report/runtime helpers so downstream code stops inheriting rounded values. Then update report modules, die-tool/runtime APIs, hooks, tasks, and JS display code that still own precision decisions. Finish by aligning Python and Playwright coverage to the new raw-value contract and running full verification.

**Tech Stack:** Frappe, ERPNext, Python unittest, Playwright, JavaScript

---

## Chunk 1: Shared Numeric Helper Contracts

### Task 1: Lock failing tests around shared helper rounding

**Files:**
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`
- Modify: `production_entry_app/production_entry_app/test_api_timeline.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`
- Modify: `production_entry_app/production_entry_app/utils/test_loss_time.py`

- [ ] Add or update focused failing tests that currently expect rounded helper outputs from shared report/runtime paths.
- [ ] Use raw expected values for report aggregates, timeline payloads, shift metrics, and loss-time math.
- [ ] For floating-point math, use `assertAlmostEqual(..., delta=derived_abs_tol)` instead of exact equality.
- [ ] Run the touched focused Python modules and confirm they fail for outdated rounded expectations.

### Task 2: Remove explicit rounding from shared helper layers

**Files:**
- Modify: `production_entry_app/production_entry_app/report/report_utils.py`
- Modify: `production_entry_app/production_entry_app/api_timeline.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Modify: `production_entry_app/production_entry_app/utils/loss_time.py`

- [ ] Replace `flt(..., 2|3)` with `flt(...)` or raw arithmetic where only coercion is needed.
- [ ] Remove rounded totals/intermediate values so helper outputs stay numeric and unrounded.
- [ ] Keep formulas and grouping behavior unchanged except where sorting currently depends on rounded values.
- [ ] Run the focused helper test modules again and make them pass.
- [ ] Commit the shared-helper change set.

## Chunk 2: Report Builders, Charts, and String Summaries

### Task 3: Add failing report coverage for report-specific rounding behavior

**Files:**
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] Add failing assertions for representative reports that still round in report-specific code.
- [ ] Cover at least one chart-heavy report, one text-summary report, one pareto report, and one OEE/efficiency-style report.
- [ ] Add explicit failing coverage for `die_tool_stroke_and_maintenance_report`, including the current
  `warning_threshold_pct` precision-owned path.
- [ ] Add coverage for Pareto cumulative behavior: raw running sum with final row hard-clamped to `100.0`.
- [ ] Add coverage for string-summary fields to keep their string contract while removing local numeric rounding decisions.
- [ ] Run from the bench root:
  `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports`
  and verify the new expectations fail before implementation.

### Task 4: Remove explicit rounding from report modules

**Files:**
- Modify: `production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py`
- Modify: `production_entry_app/production_entry_app/report/daily_strokes_spm_monitor/daily_strokes_spm_monitor.py`
- Modify: `production_entry_app/production_entry_app/report/operator_daily_spm_report/operator_daily_spm_report.py`
- Modify: `production_entry_app/production_entry_app/report/operator_efficiency_report/operator_efficiency_report.py`
- Modify: `production_entry_app/production_entry_app/report/workstation_efficiency_report/workstation_efficiency_report.py`
- Modify: `production_entry_app/production_entry_app/report/operator_rejection_performance/operator_rejection_performance.py`
- Modify: `production_entry_app/production_entry_app/report/operator_rework_performance/operator_rework_performance.py`
- Modify: `production_entry_app/production_entry_app/report/item_bom_rejection_hotspots/item_bom_rejection_hotspots.py`
- Modify: `production_entry_app/production_entry_app/report/item_bom_rework_hotspots/item_bom_rework_hotspots.py`
- Modify: `production_entry_app/production_entry_app/report/rejection_trend_report/rejection_trend_report.py`
- Modify: `production_entry_app/production_entry_app/report/rework_trend_report/rework_trend_report.py`
- Modify: `production_entry_app/production_entry_app/report/rejection_pareto_report/rejection_pareto_report.py`
- Modify: `production_entry_app/production_entry_app/report/rework_pareto_report/rework_pareto_report.py`
- Modify: `production_entry_app/production_entry_app/report/rejection_ppm_report/rejection_ppm_report.py`
- Modify: `production_entry_app/production_entry_app/report/rework_ppm_report/rework_ppm_report.py`
- Modify: `production_entry_app/production_entry_app/report/workstation_rejection_reason_matrix/workstation_rejection_reason_matrix.py`
- Modify: `production_entry_app/production_entry_app/report/workstation_rework_reason_matrix/workstation_rework_reason_matrix.py`
- Modify: `production_entry_app/production_entry_app/report/die_tool_stroke_and_maintenance_report/die_tool_stroke_and_maintenance_report.py`

- [ ] Remove report-local `flt(..., n)` and `round(..., n)` calls from row builders, totals, and chart payloads.
- [ ] Keep string-only summary fields as strings, but route embedded numeric fragments through
  `frappe.format_value(...)` with Frappe-default field formatting instead of local rounding.
- [ ] Preserve existing field shapes and report formulas.
- [ ] Keep Pareto final cumulative rows clamped to `100.0`.
- [ ] Run from the bench root:
  `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports`
  and fix any fallout until it passes.
- [ ] Commit the report-module change set.

## Chunk 3: Runtime APIs, Hooks, Die-Tool Paths, and Frontend Messaging

### Task 5: Add failing runtime-path tests for non-report rounding

**Files:**
- Modify: `production_entry_app/production_entry_app/test_api.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/test_tasks.py`
- Modify: `production_entry_app/production_entry_app/utils/test_die_tool_counter.py`
- Modify if helper extracted: `tests/unit/stock-entry-visibility.test.js`
- Modify otherwise: `tests/e2e/specs/die-tool-metrics.spec.js`
- Modify otherwise: `tests/e2e/specs/stock-entry-and-die-tool.spec.js`

- [ ] Add failing tests for die-tool counter/API payloads that currently return rounded values.
- [ ] Add failing tests for maintenance task/email content that currently formats rounded numeric fragments.
- [ ] Add failing validation tests for stock-entry breakup comparison using precision-derived tolerance instead of rounded equality.
- [ ] Add failing frontend coverage for stock-entry dashboard messaging that should stop using local `.toFixed(...)`.
- [ ] If the stock entry dashboard formatting logic is not unit-testable in its current shape, move that assertion to the
  existing die-tool E2E specs instead of forcing a new JS extraction unless it stays small and local.
- [ ] Run the touched focused suites and confirm they fail for the expected precision-contract reasons:
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_tasks`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_die_tool_counter`
  - plus the chosen JS/E2E test command for the stock entry dashboard coverage

### Task 6: Remove runtime rounding from APIs, hooks, die-tool utilities, tasks, and JS

**Files:**
- Modify: `production_entry_app/production_entry_app/api.py`
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/utils/die_tool_counter.py`
- Modify: `production_entry_app/tasks.py`
- Modify: `production_entry_app/public/js/stock_entry.js`

- [ ] Remove explicit runtime rounding from die-tool health/API calculations and any precision arguments that force rounded outputs.
- [ ] In `stock_entry_hooks.py`, add a small local helper that derives `derived_abs_tol` from the effective precision of
  `doc.custom_rejection_qty` and child-row `custom_rejection_breakup.qty`, using the looser precision when they differ.
- [ ] Replace rounded float equality checks in hooks with `math.isclose(..., rel_tol=0.0, abs_tol=derived_abs_tol)`.
- [ ] In Python string assembly paths such as `production_entry_app/tasks.py`, use `frappe.format_value(...)` for
  embedded numeric fragments instead of `flt(..., n)`.
- [ ] In JS display paths such as `production_entry_app/public/js/stock_entry.js`, replace `.toFixed(...)` with
  `frappe.format(...)` so UI formatting stays Frappe-owned.
- [ ] Keep user-facing strings stable while delegating precision display to Frappe defaults.
- [ ] Run focused Python and JS tests again and make them pass:
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_tasks`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_die_tool_counter`
  - `npx playwright test tests/e2e/specs/die-tool-metrics.spec.js tests/e2e/specs/stock-entry-and-die-tool.spec.js tests/e2e/specs/stock-entry-validations.spec.js`
- [ ] Run `bench build --app production_entry_app` after any JS change and before browser-based verification.
- [ ] Commit the runtime-path change set.

## Chunk 4: End-to-End Verification and Site Checks

### Task 7: Run representative Python verification

**Files:**
- No code changes expected

- [ ] Run focused Python modules:
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_tasks`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_die_tool_counter`
  - `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_loss_time`
- [ ] Fix any remaining precision regressions before moving to E2E.

### Task 8: Run full user-facing verification

**Files:**
- Modify if needed: `tests/e2e/specs/reports.spec.js`
- Modify if needed: `tests/e2e/specs/die-tool-metrics.spec.js`
- Modify if needed: `tests/e2e/specs/stock-entry-and-die-tool.spec.js`
- Modify if needed: `tests/e2e/specs/stock-entry-validations.spec.js`
- Modify if needed: `tests/e2e/specs/shift-to-stock-entry.spec.js`
- Modify if needed: `tests/e2e/specs/shift-validations.spec.js`
- Modify if needed: `tests/e2e/specs/shift-lifecycle.spec.js`
- Modify if needed: `tests/e2e/specs/shift-batch2.spec.js`

- [ ] Run the full Playwright suite with `npx playwright test`.
- [ ] Fix any user-visible precision fallout in existing E2E assertions.
- [ ] Spot-check `Production OEE Report` on `development.localhost`.
- [ ] Spot-check one chart-heavy report such as `Rejection Pareto Report` or `Rework Pareto Report`.
- [ ] Spot-check one text-summary report such as `Operator Rejection Performance` or `Operator Rework Performance`.
- [ ] Spot-check one persisted-metric flow affected by stock-entry hooks.

### Task 9: Final repository verification and handoff

**Files:**
- No code changes expected

- [ ] Run `pre-commit run --all-files`.
- [ ] Review the final diff to ensure benchmark-only paths remain untouched.
- [ ] Prepare a concise change summary listing representative files, updated test surfaces, and any residual trade-offs.
