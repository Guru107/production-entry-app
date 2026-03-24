# Metrics System Float Precision Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** make every in-scope user-visible metric follow `System Settings.float_precision` without rounding internal calculations early.

**Architecture:** implement this in layers. First add one narrow Python precision source and lock additive API contracts around it. Then update the custom UI boundaries that currently stringify raw floats, including the Shift aggregate table and the timeline renderer. Finish by aligning report column metadata to system precision, verifying Stock Entry DocField behavior, and running a verification matrix that covers every non-report surface plus each report family.

**Tech Stack:** Frappe, ERPNext, Python unittest, JavaScript, Playwright

---

## File Map

- Create: `production_entry_app/production_entry_app/utils/system_precision.py`
  - Returns the effective system float precision as an integer without formatting values.
- Create: `production_entry_app/production_entry_app/utils/test_system_precision.py`
  - Unit coverage for missing, invalid, and valid `System Settings.float_precision` values.
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`
  - Reuse the shared precision helper in summary and aggregate payloads.
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.js`
  - Route every summary and aggregate-table metric through one precision-aware formatter.
- Modify: `production_entry_app/public/js/timeline_renderer.js`
  - Format timeline label and tooltip quantities with system precision instead of raw coercion.
- Modify: `production_entry_app/production_entry_app/api.py`
  - Add additive `float_precision` metadata to `get_die_tool_counter`.
- Modify: `production_entry_app/production_entry_app/api_timeline.py`
  - Add additive `float_precision` metadata to `get_shift_timeline_data`.
- Modify: `production_entry_app/production_entry_app/test_api.py`
  - Lock the die-tool payload contract: numeric values stay raw, `float_precision` is additive.
- Modify: `production_entry_app/production_entry_app/test_api_timeline.py`
  - Lock the timeline payload contract: quantities stay numeric, `float_precision` is additive.
- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`
  - Lock the Shift aggregate and summary payload precision contract.
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
  - Verify hook-produced metric values stay numeric and do not gain local rounding.
- Modify: `production_entry_app/production_entry_app/report/report_utils.py`
  - Keep existing string-summary formatting helper aligned with Frappe display formatting if touched.
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`
  - Add report-column precision regression coverage for all in-scope report families.
- Modify: `production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py`
- Modify: `production_entry_app/production_entry_app/report/operator_efficiency_report/operator_efficiency_report.py`
- Modify: `production_entry_app/production_entry_app/report/workstation_efficiency_report/workstation_efficiency_report.py`
- Modify: `production_entry_app/production_entry_app/report/rejection_pareto_report/rejection_pareto_report.py`
- Modify: `production_entry_app/production_entry_app/report/rework_pareto_report/rework_pareto_report.py`
- Modify: `production_entry_app/production_entry_app/report/rejection_ppm_report/rejection_ppm_report.py`
- Modify: `production_entry_app/production_entry_app/report/rework_ppm_report/rework_ppm_report.py`
- Modify: `production_entry_app/production_entry_app/report/rejection_trend_report/rejection_trend_report.py`
- Modify: `production_entry_app/production_entry_app/report/rework_trend_report/rework_trend_report.py`
- Modify: `production_entry_app/production_entry_app/report/item_bom_rejection_hotspots/item_bom_rejection_hotspots.py`
- Modify: `production_entry_app/production_entry_app/report/item_bom_rework_hotspots/item_bom_rework_hotspots.py`
- Modify: `production_entry_app/production_entry_app/report/operator_rejection_performance/operator_rejection_performance.py`
- Modify: `production_entry_app/production_entry_app/report/operator_rework_performance/operator_rework_performance.py`
- Modify: `production_entry_app/production_entry_app/report/daily_strokes_spm_monitor/daily_strokes_spm_monitor.py`
- Modify: `production_entry_app/production_entry_app/report/operator_daily_spm_report/operator_daily_spm_report.py`
- Modify: `production_entry_app/production_entry_app/report/die_tool_stroke_and_maintenance_report/die_tool_stroke_and_maintenance_report.py`
- Modify: `production_entry_app/production_entry_app/report/workstation_rejection_reason_matrix/workstation_rejection_reason_matrix.py`
- Modify: `production_entry_app/production_entry_app/report/workstation_rework_reason_matrix/workstation_rework_reason_matrix.py`
  - Align in-scope report columns to system precision while keeping row values numeric.
- Modify if needed after manual verification only: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
  - No behavior change is expected; touch only if a real mismatch with DocField rendering is proven.
- Modify if needed: `tests/e2e/specs/reports.spec.js`
- Modify if needed: `tests/e2e/specs/die-tool-metrics.spec.js`
- Modify if needed: `tests/e2e/specs/shift-to-stock-entry.spec.js`
  - User-visible regression coverage for custom widgets, reports, and die-tool/timeline display.
- Reference: `docs/superpowers/specs/2026-03-23-metrics-system-float-precision-design.md`

## Chunk 1: Shared Precision Source And API Contracts

### Task 1: Add failing tests for the shared precision helper and additive payload contracts

**Files:**
- Create: `production_entry_app/production_entry_app/utils/test_system_precision.py`
- Modify: `production_entry_app/production_entry_app/test_api.py`
- Modify: `production_entry_app/production_entry_app/test_api_timeline.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`

- [ ] **Step 1: Write the failing helper tests**

Add a new test module that patches `frappe.db.get_single_value("System Settings", "float_precision")`
and asserts the helper returns a non-negative integer with a `3` fallback.

```python
def test_get_system_float_precision_returns_configured_value() -> None:
	with patch(
		"production_entry_app.production_entry_app.utils.system_precision.frappe.db.get_single_value",
		return_value="4",
	):
		self.assertEqual(get_system_float_precision(), 4)


def test_get_system_float_precision_falls_back_to_three_for_invalid_value() -> None:
	with patch(
		"production_entry_app.production_entry_app.utils.system_precision.frappe.db.get_single_value",
		return_value="bad",
	):
		self.assertEqual(get_system_float_precision(), 3)


def test_get_system_float_precision_falls_back_to_three_for_missing_value() -> None:
	with patch(
		"production_entry_app.production_entry_app.utils.system_precision.frappe.db.get_single_value",
		return_value=None,
	):
		self.assertEqual(get_system_float_precision(), 3)


def test_get_system_float_precision_clamps_negative_values_to_zero() -> None:
	with patch(
		"production_entry_app.production_entry_app.utils.system_precision.frappe.db.get_single_value",
		return_value="-2",
	):
		self.assertEqual(get_system_float_precision(), 0)
```

- [ ] **Step 2: Write the failing API payload tests**

Add focused regressions that assert:

- `get_die_tool_counter()` keeps `utilization_pct`, `warning_threshold_pct`, and stroke counts numeric
- `get_die_tool_counter()` now returns `float_precision`
- `get_shift_timeline_data()` now returns `float_precision`
- `get_shift_timeline_data()` keeps `fg_qty`, `rejection_qty`, and `ok_qty` numeric
- `get_shift_summary()` keeps `float_precision`
- `get_shift_summary()` keeps representative summary metrics numeric
- `get_shift_aggregate_production_entries()` returns additive `float_precision` alongside numeric rows
- `get_shift_aggregate_production_entries()` keeps row metrics numeric

Example assertions:

```python
self.assertEqual(result["float_precision"], 4)
self.assertIsInstance(result["utilization_pct"], float)
self.assertIsInstance(result["summary"]["overall_ok_spm"], float)
self.assertIsInstance(result["entries"][0]["fg_qty"], float)
self.assertIsInstance(result["entries"][0]["ok_qty"], float)
self.assertIsInstance(result["rows"][0]["avg_spm"], float)
```

- [ ] **Step 3: Run the focused tests and confirm they fail**

Run from the v15 bench root:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.utils.test_system_precision

bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api \
  --test TestE2EApi.test_get_die_tool_counter_includes_float_precision_without_rounding_payload

bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api_timeline \
  --test TestGetShiftTimelineData.test_returns_float_precision_for_custom_timeline_rendering

bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.doctype.shift.test_shift \
  --test TestShiftSummary.test_shift_aggregate_production_entries_include_float_precision

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.utils.test_system_precision

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api \
  --test TestE2EApi.test_get_die_tool_counter_includes_float_precision_without_rounding_payload

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api_timeline \
  --test TestGetShiftTimelineData.test_returns_float_precision_for_custom_timeline_rendering

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.doctype.shift.test_shift \
  --test TestShiftSummary.test_shift_aggregate_production_entries_include_float_precision
```

Expected:

- `utils.test_system_precision`: FAIL with import or module-not-found because `system_precision.py` does not exist yet
- `test_api`: FAIL because `get_die_tool_counter()` does not yet expose `float_precision`
- `test_api_timeline`: FAIL because `get_shift_timeline_data()` does not yet expose `float_precision`
- `test_shift`: FAIL because aggregate payloads do not yet expose `float_precision`

- [ ] **Step 4: Implement the minimal shared helper and additive payload changes**

Create `system_precision.py` with:

```python
def get_system_float_precision() -> int:
	try:
		value = int(frappe.db.get_single_value("System Settings", "float_precision") or 3)
	except (TypeError, ValueError):
		return 3
	return max(value, 0)
```

Then wire it into:

- `shift.py` for summary and aggregate payloads
- `api.py` for `get_die_tool_counter`
- `api_timeline.py` for `get_shift_timeline_data`

Import path:

```python
from production_entry_app.production_entry_app.utils.system_precision import (
	get_system_float_precision,
)
```

Keep all existing numeric fields numeric. Do not preformat strings.

- [ ] **Step 5: Re-run the focused tests and commit**

Run the same commands from Step 3 on both benches and make them pass, then commit:

```bash
git add production_entry_app/production_entry_app/utils/system_precision.py \
        production_entry_app/production_entry_app/utils/test_system_precision.py \
        production_entry_app/production_entry_app/api.py \
        production_entry_app/production_entry_app/api_timeline.py \
        production_entry_app/production_entry_app/doctype/shift/shift.py \
        production_entry_app/production_entry_app/test_api.py \
        production_entry_app/production_entry_app/test_api_timeline.py \
        production_entry_app/production_entry_app/doctype/shift/test_shift.py
git commit -m "Add system precision contract for UI metric payloads"
```

## Chunk 2: Custom UI Rendering Boundaries

### Task 2: Add failing coverage for custom HTML surfaces and timeline rendering

**Files:**
- Modify: `tests/e2e/specs/die-tool-metrics.spec.js`
- Modify: `tests/e2e/specs/shift-to-stock-entry.spec.js`

- [ ] **Step 1: Add failing Playwright checks for rendered precision**

Add user-visible assertions for:

- Shift aggregate production entries table renders system-precision values instead of raw JavaScript coercion
- die-tool warning headline keeps the API precision contract and does not apply local `.toFixed(...)`
- Workstation or Operator timeline tooltips/labels show `fg_qty`, `rejection_qty`, and `ok_qty` with system precision

Use exact string expectations after setting `System Settings.float_precision` through the existing E2E bootstrap helper.

Example assertion shape:

```javascript
await expect(page.locator('[data-fieldname="aggregate_production_entries"]')).toContainText("33.333");
await expect(page.locator(".indicator-pill, .alert")).toContainText("90.12345%");
await expect(page.locator(".pea-timeline-tooltip")).toContainText("OK Qty: 94.500");
```

- [ ] **Step 2: Run the focused Playwright specs and confirm they fail**

Run:

```bash
npx playwright test \
  tests/e2e/specs/die-tool-metrics.spec.js \
  tests/e2e/specs/shift-to-stock-entry.spec.js
```

Expected: FAIL because the aggregate table and timeline renderer still stringify raw numeric values.
Also expect the die-tool warning headline assertion to fail if the UI still applies local `.toFixed(...)`
or otherwise truncates the API-provided precision.

- [ ] **Step 3: Implement the minimal frontend formatting change**

In `shift.js`:

- keep using the existing summary formatter for the summary widget
- extend the aggregate production entries table to format `total_qty`, `total_ok_qty`,
  `total_reject_qty`, and `avg_spm` through a shared local helper instead of `String(...)`
- use that helper for every aggregate-table metric cell so the rendering boundary stays explicit

In `timeline_renderer.js`:

- add a tiny local formatter pair that mirrors the approved spec:

```javascript
function getSystemFloatPrecision(rawPrecision) {}
function formatMetricDisplay(value, fieldtype = "Float", rawPrecision) {}
```

- use `data.float_precision` from `get_shift_timeline_data()`
- format label and tooltip quantities through `frappe.format(...)`

Trade-off: keep the JS helper local to the two rendering files unless a third consumer appears.
Do not add a new global asset just to remove a few lines of duplication.

- [ ] **Step 4: Re-run the focused Playwright specs and rebuild assets**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench build --app production_entry_app
npx playwright test \
  tests/e2e/specs/die-tool-metrics.spec.js \
  tests/e2e/specs/shift-to-stock-entry.spec.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/doctype/shift/shift.js \
        production_entry_app/public/js/timeline_renderer.js \
        tests/e2e/specs/die-tool-metrics.spec.js \
        tests/e2e/specs/shift-to-stock-entry.spec.js
git commit -m "Format custom UI metrics with system precision"
```

## Chunk 3: Reports And Stock Entry DocField Verification

### Task 3: Add failing report-column precision coverage and lock hook behavior

**Files:**
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`

- [ ] **Step 1: Add failing regression tests for report metadata**

Extend `test_reports.py` to assert representative in-scope columns carry explicit precision
derived from `System Settings.float_precision`.

Cover these families:

- quantity: `item_bom_rejection_hotspots` or `item_bom_rework_hotspots`
- SPM: `operator_daily_spm_report` or `daily_strokes_spm_monitor`
- percentage/rate: `production_oee_report`, `operator_efficiency_report`, or `workstation_efficiency_report`
- PPM: `rejection_ppm_report` or `rework_ppm_report`
- rejection/rework rate: `operator_rejection_performance` or `operator_rework_performance`
- float-time: `production_oee_report` or `operator_daily_spm_report`
- die-tool: `die_tool_stroke_and_maintenance_report`

Example assertion shape:

```python
with patch(
	"production_entry_app.production_entry_app.report.production_oee_report.production_oee_report.get_system_float_precision",
	return_value=4,
):
	columns, _rows = execute({})
	self.assertEqual(columns_by_field["oee_mult_pct"]["precision"], 4)
	self.assertEqual(columns_by_field["running_time"]["precision"], 4)
```

Also add a hook regression that keeps `custom_actual_spm` and `custom_operator_efficiency_pct`
raw numeric values, not preformatted strings.

- [ ] **Step 2: Run the focused Python modules and confirm they fail**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.report.test_reports

bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

Expected:

- `report.test_reports`: FAIL because the representative report columns do not yet align to
  system precision everywhere
- `overrides.test_stock_entry_hooks`: FAIL if any new regression proves hook values were converted
  to strings or locally rounded instead of remaining numeric

- [ ] **Step 3: Implement report precision alignment**

For each in-scope report module listed in the file map:

- import `get_system_float_precision`
- resolve `precision = get_system_float_precision()` once near column construction
- set `precision` on every in-scope numeric metric column that can render decimals, including the
  fieldtypes used for quantity, SPM, percentage/rate, PPM, float-time, and die-tool metrics in
  these reports
- keep rows numeric and formulas unchanged

Representative example:

```python
precision = get_system_float_precision()
{
	"label": _("Actual SPM"),
	"fieldname": "actual_spm",
	"fieldtype": "Float",
	"precision": precision,
}
```

If `test_stock_entry_hooks.py` proves the `Stock Entry` DocFields already render through system
precision, stop there and do not change `stock_entry_hooks.py`. Only touch hook production code if a
real mismatch is reproduced.

- [ ] **Step 4: Re-run the focused Python modules on v15 and a representative v16 pass**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.report.test_reports

bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks

cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.report.test_reports \
  --test TestProductionReports.test_production_oee_report_percent_columns_follow_system_precision

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/report/test_reports.py \
        production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py \
        production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py \
        production_entry_app/production_entry_app/report/operator_efficiency_report/operator_efficiency_report.py \
        production_entry_app/production_entry_app/report/workstation_efficiency_report/workstation_efficiency_report.py \
        production_entry_app/production_entry_app/report/rejection_pareto_report/rejection_pareto_report.py \
        production_entry_app/production_entry_app/report/rework_pareto_report/rework_pareto_report.py \
        production_entry_app/production_entry_app/report/rejection_ppm_report/rejection_ppm_report.py \
        production_entry_app/production_entry_app/report/rework_ppm_report/rework_ppm_report.py \
        production_entry_app/production_entry_app/report/rejection_trend_report/rejection_trend_report.py \
        production_entry_app/production_entry_app/report/rework_trend_report/rework_trend_report.py \
        production_entry_app/production_entry_app/report/item_bom_rejection_hotspots/item_bom_rejection_hotspots.py \
        production_entry_app/production_entry_app/report/item_bom_rework_hotspots/item_bom_rework_hotspots.py \
        production_entry_app/production_entry_app/report/operator_rejection_performance/operator_rejection_performance.py \
        production_entry_app/production_entry_app/report/operator_rework_performance/operator_rework_performance.py \
        production_entry_app/production_entry_app/report/daily_strokes_spm_monitor/daily_strokes_spm_monitor.py \
        production_entry_app/production_entry_app/report/operator_daily_spm_report/operator_daily_spm_report.py \
        production_entry_app/production_entry_app/report/die_tool_stroke_and_maintenance_report/die_tool_stroke_and_maintenance_report.py \
        production_entry_app/production_entry_app/report/workstation_rejection_reason_matrix/workstation_rejection_reason_matrix.py \
        production_entry_app/production_entry_app/report/workstation_rework_reason_matrix/workstation_rework_reason_matrix.py
git commit -m "Align report metrics with system float precision"
```

## Chunk 4: Verification Matrix And Final Handoff

### Task 4: Run the full verification matrix

**Files:**
- Modify if assertions need updates: `tests/e2e/specs/reports.spec.js`
- Modify if assertions need updates: `tests/e2e/specs/die-tool-metrics.spec.js`
- Modify if assertions need updates: `tests/e2e/specs/shift-to-stock-entry.spec.js`

- [ ] **Step 1: Run non-report Python verification**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.utils.test_system_precision

bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api

bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api_timeline

bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.doctype.shift.test_shift

bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

- [ ] **Step 2: Run report verification**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.report.test_reports
```

This must cover:

- quantity family
- SPM family
- percentage/rate family
- PPM family
- rejection/rework-rate family
- float-time family
- die-tool family

- [ ] **Step 3: Run representative v16 verification**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.utils.test_system_precision

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api \
  --test TestE2EApi.test_get_die_tool_counter_includes_float_precision_without_rounding_payload

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.test_api_timeline \
  --test TestGetShiftTimelineData.test_returns_float_precision_for_custom_timeline_rendering

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.doctype.shift.test_shift \
  --test TestShiftSummary.test_shift_aggregate_production_entries_include_float_precision

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks

bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.report.test_reports \
  --test TestProductionReports.test_production_oee_report_percent_columns_follow_system_precision
```

- [ ] **Step 4: Run browser verification and manual checks**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench build --app production_entry_app
npx playwright test \
  tests/e2e/specs/reports.spec.js \
  tests/e2e/specs/die-tool-metrics.spec.js \
  tests/e2e/specs/shift-to-stock-entry.spec.js
```

Then perform these manual checks after changing `System Settings.float_precision` once:

- Shift summary widget reflects the new precision
- Shift aggregate production entries table reflects the new precision
- Workstation or Operator timeline tooltip reflects the new precision
- die-tool warning UI reflects the API-provided precision without local truncation
- Stock Entry metric DocFields reflect the new precision
- one SPM report reflects the new precision
- one percentage/rate report reflects the new precision
- one rejection/rework-rate report reflects the new precision
- one PPM or quantity-heavy report reflects the new precision
- one float-time report reflects the new precision
- one die-tool report reflects the new precision

- [ ] **Step 5: Run repository-wide verification and prepare handoff**

Run:

```bash
pre-commit run --all-files
git status --short
git log --oneline --max-count=5
```

Prepare a concise final summary that includes:

- changed files by surface
- verification commands actually run
- whether `stock_entry_hooks.py` needed production changes or only verification
- residual trade-off: JS precision helper remains local to the two custom renderers to avoid a new global abstraction

## Verification Matrix

| Surface | Verification Type | Required Evidence |
| --- | --- | --- |
| `get_die_tool_counter` payload | Python test | additive `float_precision`, numeric values preserved |
| `get_shift_timeline_data` payload | Python test | additive `float_precision`, numeric quantities preserved |
| `get_shift_summary` payload | Python test | `float_precision` retained, representative summary metrics stay numeric |
| `get_shift_aggregate_production_entries` payload | Python test | additive `float_precision`, row values numeric |
| Shift summary widget | Playwright + manual | formatted display changes with system precision |
| Shift aggregate table | Playwright + manual | formatted display changes with system precision |
| Timeline renderer | Playwright + manual | tooltip/label quantities change with system precision |
| Die-tool warning UI | Playwright + manual | displayed utilization matches API precision contract |
| Stock Entry DocFields | Python verification + manual | stored values remain numeric, rendered values follow system precision |
| Quantity-family reports | report tests + manual | column precision aligned |
| SPM-family reports | report tests + manual | column precision aligned |
| Percentage/rate-family reports | report tests + manual | column precision aligned |
| PPM-family reports | report tests + manual | column precision aligned |
| Rejection/rework-rate-family reports | report tests + manual | column precision aligned |
| Float-time-family reports | report tests + manual | column precision aligned |
| Die-tool-family reports | report tests + manual | column precision aligned |

## Execution Notes

- Keep payloads backward compatible. Add `float_precision`; do not rename or stringify existing numeric keys.
- Keep calculations raw. Precision is a display-boundary concern, not a math helper concern.
- Avoid introducing a new globally shared frontend asset unless a third renderer appears. Two local helpers are the simpler, lower-risk trade-off here.
- If a report module already uses `fieldtype: "Percent"`, still set explicit `precision` so the display matches `System Settings.float_precision`.
- If a manual Stock Entry form check proves the existing DocField rendering already follows system precision, do not add production code just for symmetry.

Plan complete and saved to `docs/superpowers/plans/2026-03-23-metrics-system-float-precision.md`. Ready to execute?
