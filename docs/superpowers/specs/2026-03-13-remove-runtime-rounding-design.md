# Remove Runtime Rounding Design

## Goal

Remove application-owned numeric rounding from runtime code paths and let Frappe handle display precision on
user-facing surfaces.

This change applies to core application behavior and user-facing data generation. Benchmark-only output is out of
scope.

## Scope

### In scope

- Report modules under `production_entry_app/production_entry_app/report/`
- Shared report helpers in `production_entry_app/production_entry_app/report/report_utils.py`
- Timeline and API helpers such as `production_entry_app/production_entry_app/api_timeline.py`
- Die-tool API helpers such as `production_entry_app/production_entry_app/api.py`
- Shift runtime and metrics helpers in `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Stock Entry runtime hooks in `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Die-tool runtime utilities in `production_entry_app/production_entry_app/utils/die_tool_counter.py`
- Utility math helpers in `production_entry_app/production_entry_app/utils/loss_time.py`
- User-facing JS formatting in `production_entry_app/production_entry_app/public/js/stock_entry.js`
- Maintenance alert/task formatting in `production_entry_app/production_entry_app/tasks.py`
- Tests that assert rounded values from the above code paths

### Out of scope

- Benchmark output in:
  - `production_entry_app/production_entry_app/write_benchmark.py`
  - `production_entry_app/production_entry_app/report/report_benchmark.py`
- New column metadata precision rules

Existing explicit column precision overrides may be removed if they are part of the current app-owned rounding
behavior. This pass does not add new precision metadata to compensate for backend rounding removal.

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

Pareto-specific rule:

- cumulative percentage should be computed from raw values without per-step rounding
- the final cumulative row may remain hard-clamped to `100.0` to preserve the expected Pareto endpoint contract

### 3. Preserve numeric types

Returned values stay numeric where the contract is numeric.

- No string formatting in Python or JS data builders
- No backend formatting like `"99.50%"`
- Frappe remains responsible for visible precision in reports/forms

For non-report user-facing string surfaces that must remain strings, Frappe formatting helpers may be used to render
numeric fragments with Frappe default precision. Raw Python float repr must not be exposed to users.

#### Existing text summary fields

Some current reports embed quantities inside text fields such as top-reason summaries or dominant-reason labels.

For this pass:

- keep those fields as strings
- remove ad hoc `round(...)` and `flt(..., n)` formatting inside the string assembly
- use Frappe formatting helpers with Frappe default precision when a number must still be embedded into a string
- do not change the field shape from string to object/list

This keeps the report contract stable while delegating precision display to Frappe instead of local rounding code.

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

- `api.py`
- `api_timeline.py`
- `doctype/shift/shift.py`
- `overrides/stock_entry_hooks.py`
- `public/js/stock_entry.js`
- `tasks.py`
- `utils/die_tool_counter.py`
- `utils/loss_time.py`

These paths affect application state, downstream report inputs, and API payloads. Leaving rounding here would
continue to leak rounded values into higher layers.

## Validation and comparison rules

Removing explicit rounding does not mean replacing it with brittle raw-float equality.

For validation paths:

- avoid direct equality checks on computed floating-point values
- compare using `math.isclose(..., rel_tol=0.0, abs_tol=NUMERIC_COMPARISON_ABS_TOLERANCE)`
  when the values are derived from arithmetic
- keep exact equality only for values that are already integral or directly stored without float math

For this change set:

- derive absolute tolerance from effective field precision instead of using a hardcoded universal constant
- use `abs_tol = 0.5 * 10 ** (-precision)` where `precision` is the effective precision of the compared quantity
- use the document field precision when available
- when two compared fields have different precisions, use the looser precision as the comparison source of truth
- if metadata lookup is not practical at that call site, use the existing business precision for that quantity path
  rather than inventing a stricter contract
- use absolute tolerance only; no relative tolerance

The intended replacement for rounded float equality contracts is tolerance-based comparison, not raw `==` on floats
and not continued `flt(..., n)` rounding before compare.

This applies to validation code such as rejection/rework quantity checks in stock entry hooks.

## Testing Strategy

## Test changes

Tests that currently encode rounded values must be updated.

Rules:

- Use exact equality when the value should remain integral or directly sourced
- Use `assertAlmostEqual` when floating-point math is involved
- Keep test expectations aligned with the new unrounded raw values rather than prior rounded snapshots

Primary test surfaces:

- `production_entry_app/production_entry_app/report/test_reports.py`
- `production_entry_app/production_entry_app/doctype/shift/test_shift.py`
- `production_entry_app/production_entry_app/test_api.py`
- `production_entry_app/production_entry_app/test_api_timeline.py`
- `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- `production_entry_app/production_entry_app/test_tasks.py`
- `production_entry_app/production_entry_app/utils/test_die_tool_counter.py`
- `production_entry_app/production_entry_app/utils/test_loss_time.py`
- `tests/unit/stock-entry*.test.js` or the closest existing frontend coverage for stock entry dashboard messaging

Additional tests should be adjusted wherever current expectations explicitly depend on `flt(..., n)` or rounded
chart/totals outputs.

## Verification

Minimum verification after implementation:

- Focused Python test modules for each touched area
- Full Playwright suite verification
- `pre-commit run --all-files`
- Representative real report checks on `development.localhost`

Minimum representative spot-check set:

- `Production OEE Report`
- one chart-heavy report such as `Rejection Pareto Report` or `Rework Pareto Report`
- one text-summary report such as `Operator Rejection Performance` or `Operator Rework Performance`
- one persisted-metric flow affected by runtime hooks, using the closest existing Shift/Stock Entry Playwright suite

## Trade-offs

### Benefits

- More numerically correct results because intermediate values are no longer rounded step-by-step
- Consistent ownership boundary: backend computes, Frappe formats
- Less hidden precision loss in shared helpers and chart payloads

### Costs

- Larger diff because rounding is spread across many modules
- Significant test churn
- Visible values may show more decimals than before until report/UI formatting is adjusted separately
- More care is needed for non-report string surfaces so raw Python float repr is not exposed

## Non-goals

- Reworking report column precision metadata across the app
- Changing benchmark output
- Refactoring unrelated business logic while touching these files
