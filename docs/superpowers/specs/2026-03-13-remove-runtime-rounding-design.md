# Remove Runtime Rounding Design

## Goal

Remove application-owned numeric rounding from runtime code paths and let Frappe handle display precision.

This change applies to core application behavior and user-facing data generation. Benchmark-only output is out of
scope.

## Scope

### In scope

- Report modules under `production_entry_app/production_entry_app/report/`
- Shared report helpers in `production_entry_app/production_entry_app/report/report_utils.py`
- Timeline and API helpers such as `production_entry_app/production_entry_app/api_timeline.py`
- Shift runtime and metrics helpers in `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Stock Entry runtime hooks in `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Utility math helpers in `production_entry_app/production_entry_app/utils/loss_time.py`
- Tests that assert rounded values from the above code paths

### Out of scope

- Benchmark output in:
  - `production_entry_app/production_entry_app/write_benchmark.py`
  - `production_entry_app/production_entry_app/report/report_benchmark.py`
- Column metadata precision changes, unless a specific field still hardcodes a backend-rounded value contract

## Design Rules

### 1. Remove explicit runtime rounding

Application code must stop owning precision in computed numeric values.

Allowed:

- `flt(value)` for coercion
- raw arithmetic expressions
- integer/count semantics where the source value is inherently integral

Disallowed in runtime paths:

- `flt(value, 2)`
- `flt(value, 3)`
- `round(value, 2)`
- `round(value, 3)`
- rounded chart payloads that diverge from row data

### 2. Preserve behavior, change precision ownership

The formulas do not change. Only explicit rounding is removed.

Examples:

- rejection rate still uses `rejection_qty / total_qty * 100`
- OEE still uses the existing business formula
- efficiency and SPM calculations remain unchanged

Sorting and grouping should operate on raw values unless a current implementation sorts a value only after rounding.
In that case, sorting should use the unrounded value.

### 3. Preserve numeric types

Returned values stay numeric.

- No string formatting in Python or JS data builders
- No backend formatting like `"99.50%"`
- Frappe remains responsible for visible precision in reports/forms

### 4. Keep chart and totals math aligned

Charts, totals rows, and summary values must use the same unrounded numeric values as the main report rows.

This avoids cases where:

- the table shows a raw value
- the chart shows a separately rounded variant
- totals are based on rounded intermediates

## Target Areas

## Reports

The following report families currently own numeric rounding and must move to raw values:

- `production_oee_report`
- `daily_strokes_spm_monitor`
- `operator_daily_spm_report`
- `operator_efficiency_report`
- `workstation_efficiency_report`
- `operator_rejection_performance`
- `operator_rework_performance`
- `item_bom_rejection_hotspots`
- `item_bom_rework_hotspots`
- `rejection_trend_report`
- `rework_trend_report`
- `rejection_pareto_report`
- `rework_pareto_report`
- `rejection_ppm_report`
- `rework_ppm_report`
- `workstation_rejection_reason_matrix`
- `workstation_rework_reason_matrix`
- `die_tool_stroke_and_maintenance_report`

Shared helper behavior in `report_utils.py` must also be updated because multiple reports inherit its rounded
intermediates.

## Runtime helpers outside reports

- `api_timeline.py`
- `doctype/shift/shift.py`
- `overrides/stock_entry_hooks.py`
- `utils/loss_time.py`

These paths affect application state, downstream report inputs, and API payloads. Leaving rounding here would
continue to leak rounded values into higher layers.

## Testing Strategy

## Test changes

Tests that currently encode rounded values must be updated.

Rules:

- Use exact equality when the value should remain integral or directly sourced
- Use approximate assertions when floating-point math is involved
- Prefer built-in unittest assertions such as `assertAlmostEqual`

Primary test surfaces:

- `production_entry_app/production_entry_app/report/test_reports.py`
- `production_entry_app/production_entry_app/doctype/shift/test_shift.py`
- `production_entry_app/production_entry_app/test_api_timeline.py`
- `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`

Additional tests should be adjusted wherever current expectations explicitly depend on `flt(..., n)` or rounded
chart/totals outputs.

## Verification

Minimum verification after implementation:

- Focused Python test modules for each touched area
- `pre-commit run --all-files`
- A real report spot check on `development.localhost`

Suggested report spot check:

- `Production OEE Report`

## Trade-offs

### Benefits

- More numerically correct results because intermediate values are no longer rounded step-by-step
- Consistent ownership boundary: backend computes, Frappe formats
- Less hidden precision loss in shared helpers and chart payloads

### Costs

- Larger diff because rounding is spread across many modules
- Significant test churn
- Visible values may show more decimals than before until report/UI formatting is adjusted separately
- Raw floating-point tails may appear in backend payloads where Frappe does not format them before display

## Non-goals

- Reworking report column precision metadata across the app
- Changing benchmark output
- Refactoring unrelated business logic while touching these files
