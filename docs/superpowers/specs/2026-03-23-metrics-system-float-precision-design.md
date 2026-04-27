# Metrics System Float Precision Design

**Date:** 2026-03-23

**Goal:** Make all user-visible metrics in the application consistent with `System Settings.float_precision` while keeping internal calculations raw until display.

## Problem

The app currently has multiple user-visible metric surfaces:

- custom form widgets and HTML summaries
- DocType fields populated by server-side hooks
- script reports rendered inside ERPNext
- API payloads that feed UI widgets

Some paths already respect system float precision, such as parts of the Shift summary, while other paths likely rely on implicit defaults, field metadata, or raw float stringification. That creates a risk of mixed formatting across the UI.

## Scope

### In Scope

- Custom form metrics and HTML summaries listed below
- User-visible metric DocFields written onto documents
- Script reports rendered inside ERPNext
- API payloads that directly feed custom UI rendering

### Explicit Surface Inventory

The implementation plan must cover these exact user-visible metric surfaces.

#### Custom HTML And Form Widgets

- `Shift` summary widget in `production_entry_app/production_entry_app/doctype/shift/shift.js`
  - snapshot metrics: `entry_count`, `total_qty`, `ok_qty`, `rejection_qty`, `rejection_pct`,
	`recorded_production_mins`, `overall_throughput_spm`, `overall_ok_spm`,
	`target_coverage_pct`, `overall_shift_efficiency_pct`
  - losses metrics: `planned_shift_mins`, `planned_loss_mins`, `planned_usable_mins`,
	`unplanned_loss_mins`
  - logged downtime metrics: `entry_count`, `total_mins`, `top_reasons[].mins`
  - exception metrics: `unplanned_loss_reasons[].mins`, `workstations[].efficiency_pct`,
	`workstations[].throughput_spm`, `item_boms[].rejection_qty`
  - positive-signal metrics: `efficiency_pct`, `throughput_spm`
- `Shift` aggregate production entries table in
  `production_entry_app/production_entry_app/doctype/shift/shift.js`
  backed by `get_shift_aggregate_production_entries`
  - row metrics: `total_qty`, `total_ok_qty`, `total_reject_qty`, `avg_spm`

#### User-Visible DocField Metrics

- `Stock Entry` metrics written by
  `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
  - `custom_pea_ok_qty`
  - `custom_pea_actual_duration_mins`
  - `custom_pea_production_time_mins`
  - `custom_pea_actual_spm`
  - `custom_pea_cycle_time_sec`
  - `custom_pea_operator_efficiency_pct`
  - `custom_pea_die_tool_utilization_pct`
  - `custom_pea_die_tool_maintenance_due`

#### UI-Facing API Payloads

- `production_entry_app.production_entry_app.doctype.shift.shift.get_shift_summary`
- `production_entry_app.production_entry_app.doctype.shift.shift.get_shift_aggregate_production_entries`
- `production_entry_app.production_entry_app.api.get_die_tool_counter`
- `production_entry_app.production_entry_app.api_timeline.get_shift_timeline_data`
  consumed by `production_entry_app/public/js/timeline_renderer.js`
  - production entry metrics: `fg_qty`, `rejection_qty`, `ok_qty`

#### Reports

- `operator_efficiency_report`
- `workstation_efficiency_report`
- `production_oee_report`
- `rejection_pareto_report`
- `rework_pareto_report`
- `rejection_ppm_report`
- `rework_ppm_report`
- `rejection_trend_report`
- `rework_trend_report`
- `item_bom_rejection_hotspots`
- `item_bom_rework_hotspots`
- `operator_rejection_performance`
- `operator_rework_performance`
- `daily_strokes_spm_monitor`
- `operator_daily_spm_report`
- `die_tool_stroke_and_maintenance_report`
- `workstation_rejection_reason_matrix`
- `workstation_rework_reason_matrix`

The report implementation plan must explicitly cover user-visible metric columns in these families:

- quantity metrics
- SPM metrics
- percentage/rate metrics
- PPM metrics
- float time metrics shown as hours or minutes

### Out of Scope

- Internal intermediate calculations used only for aggregation or validation
- Validation/tolerance precision rules that are about correctness rather than display
- Non-numeric explanatory text such as `metrics_note`
- Benchmarks and raw-value assertions that intentionally verify unrounded internals

## Source Of Truth

The display rule for this project is:

- all user-visible metrics should follow `System Settings.float_precision`
- internal calculations should remain raw until they cross a presentation boundary
- `System Settings.float_precision` is authoritative even when the current field or report
  path would otherwise rely on implicit Frappe defaults

### Policy Resolution

This spec intentionally resolves the ambiguity between system precision and existing field/report
rendering.

- For metric DocFields and report columns in scope, the implementation must align their rendered
  precision with `System Settings.float_precision`
- Existing field metadata or report defaults may still be used as the rendering mechanism, but the
  resulting display must match system precision
- No user-visible metric in scope may keep a separate hard-coded precision policy unless a
  documented correctness rule requires it
- Correctness-oriented validation or tolerance math remains out of scope

This makes system precision the default display policy for metrics, instead of per-metric ad hoc rounding.

## Recommended Approach

Use a presentation-boundary precision policy.

That means:

- keep Python and JavaScript calculations raw
- apply precision consistently only where values become user-visible
- centralize precision lookup and formatting policy so forms, reports, and custom widgets follow the same rule

### Why This Approach

- It minimizes regression risk in business logic.
- It avoids double-rounding and loss of fidelity during aggregation.
- It aligns directly with the requirement that display be consistent with system settings.
- It keeps the distinction between “value used for computation” and “value shown to a user” explicit.

### Rejected Alternatives

#### Round Early In Server Logic

Trade-offs:

- simpler payloads
- higher risk of rounded values leaking back into downstream calculations
- mixes business logic with display policy

#### Hybrid Per-Layer Rules

Trade-offs:

- may reduce immediate work
- creates two or more formatting policies to maintain
- high chance of future inconsistency

## Change Areas

### 1. Shift Summary UI

Files:

- `production_entry_app/production_entry_app/doctype/shift/shift.js`
- `production_entry_app/production_entry_app/doctype/shift/shift.py`

Plan:

- keep `get_shift_summary` numeric payload fields raw
- keep `float_precision` in the summary payload as the display contract for custom HTML rendering
- ensure every Shift summary metric listed in the scope inventory is rendered through one
  precision-aware JS formatter
- ensure workstation, item BOM, top-reason, and positive-signal rows do not stringify raw floats
- leave Python calculations raw until the payload is consumed by the widget

### 2. Stock Entry User-Visible Metrics

File:

- `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`

Plan:

- keep `_set_entry_metrics()` and `_set_die_tool_health_metrics()` calculations raw
- verify the affected metric DocFields render with system precision in the `Stock Entry` form
- where current DocField definitions do not guarantee system-precision display, align the rendered
  precision with `System Settings.float_precision`
- do not convert stored numeric values to preformatted strings

### 3. UI-Facing APIs

Files:

- `production_entry_app/production_entry_app/api.py`
- `production_entry_app/production_entry_app/api_timeline.py`

Plan:

- keep existing numeric keys numeric
- make only additive payload changes
- `get_shift_summary` continues to expose `float_precision`
- `get_shift_aggregate_production_entries` may add `float_precision` without changing row shape
- `get_die_tool_counter` may add `float_precision` without renaming existing keys
- `get_shift_timeline_data` should expose `float_precision` because
  `production_entry_app/public/js/timeline_renderer.js` renders `fg_qty`, `rejection_qty`, and
  `ok_qty` inside custom timeline labels and tooltips rather than through DocField rendering
- do not convert API numeric values into formatted strings

### 4. Reports

Directory:

- `production_entry_app/production_entry_app/report/`

Plan:

- keep report row values numeric
- add or align explicit report-column `precision` for all in-scope metric columns
- ensure representative columns across quantity, SPM, percentage/rate, PPM, and float-time reports
  render with system precision
- keep report aggregation helpers raw unless they are incorrectly formatting display text inline

## Helper Strategy

### Python

Add a small shared helper under `production_entry_app/production_entry_app/utils/` to:

- resolve `System Settings.float_precision`
- provide a reusable display precision value for reports and API payloads

This helper should be lightweight and narrowly scoped. It should not become a broad formatting abstraction.

Proposed interface:

```python
def get_system_float_precision() -> int:
	"""Return a non-negative system float precision, defaulting to 3."""
```

Behavior:

- read `System Settings.float_precision`
- coerce to `int`
- fall back to `3` if missing or invalid
- keep the helper focused on returning precision, not formatting strings

### JavaScript

Add or reuse a small utility for custom widget rendering that:

- resolves system precision from payload metadata first
- falls back to `frappe.boot.sysdefaults.float_precision`
- applies consistent rendering for custom HTML/cards/widgets

Proposed interface:

```javascript
function getSystemFloatPrecision(rawPrecision) {}
function formatMetricDisplay(value, fieldtype = "Float", rawPrecision) {}
```

Behavior:

- use payload `float_precision` when present
- otherwise use `frappe.boot.sysdefaults.float_precision`
- otherwise use `frappe.defaults.get_default("float_precision")`
- otherwise fall back to `3`
- return formatted strings only at custom HTML presentation boundaries

## Precision Policy Details

### Reports And Frappe Fields

For normal report columns and DocField-backed rendering:

- prefer numeric values plus explicit `precision`
- let Frappe render the display according to the configured precision
- set that configured precision to the resolved system float precision for in-scope metrics

### Custom HTML Widgets

For custom HTML surfaces:

- do not rely on raw JavaScript string coercion
- use the resolved system precision explicitly when rendering

### API Payloads

For UI-facing APIs:

- prefer returning raw numeric values plus `float_precision`
- let the consumer apply the display rule
- preserve backward compatibility through additive-only payload changes
- do not rename numeric keys or replace numeric values with strings

This keeps API payloads usable while still making display consistent.

## Verification Strategy

Verification must prove both correctness and consistency.

### Automated Checks

- add unit tests for `get_system_float_precision()`
- add or update JS/unit tests for custom HTML formatter behavior where test infrastructure exists
- add or update tests for `get_shift_summary` and `get_shift_aggregate_production_entries`
  precision contracts
- add or update tests for `get_die_tool_counter` precision contract if the payload changes
- add or update tests for timeline payload precision behavior if that payload changes
- add or update representative report tests covering:
  - one SPM report
  - one efficiency or OEE report
  - one PPM report
  - one rejection/rework rate report
  - one die-tool report
  - one float-time report

### Test Policy

- preserve existing tests that intentionally verify raw values in internal calculations
- add separate assertions for user-visible precision configuration and display-facing payload behavior

### Manual Checks

At least one manual verification pass should confirm that changing `System Settings.float_precision`
changes the UI display consistently in each of these categories:

- one custom form/widget path
- one DocField-rendered metric path on `Stock Entry`
- one direct-display API consumer path
- one report path for each metric family:
  - SPM
  - percentage/rate
  - PPM or quantity-heavy pareto/trend
  - die-tool metrics
  - float-time metrics

### Verification Matrix Requirement

The implementation plan must include an explicit verification matrix.

- every non-report surface listed in the scope inventory must have a named automated or manual
  verification path
- reports may be verified by named family rather than by every single report file, but every report
  family listed in the scope section must be covered
- each verification row must state whether it proves payload contract, rendering precision, or both

## Success Criteria

- Changing `System Settings.float_precision` changes user-visible metric display consistently across
  every non-report surface listed in this spec and across every in-scope report family.
- Internal calculations remain raw unless a display boundary intentionally formats them.
- No screen/report shows mixed metric precision caused by raw float leakage.
- Existing validation/tolerance rules remain behaviorally unchanged.

## Risks

### Risk: Mixed Raw And Display Values In The Same Payload

Mitigation:

- document whether each payload value is raw-for-computation or display-ready
- prefer raw numeric payloads plus `float_precision` metadata for custom UI

### Risk: Over-Centralizing Formatting

Mitigation:

- keep helpers narrow
- centralize precision lookup and policy, not every numeric transformation

### Risk: Report Regressions

Mitigation:

- update report tests by category
- audit only user-visible metric columns instead of refactoring all report math

## Implementation Notes

- Do not blanket-round all server-side metric outputs.
- Do not change correctness-oriented precision logic in rejection/tolerance validation unless a real bug is found.
- Keep APIs small and behavior explicit.

## Next Step

After spec approval, create an implementation plan that:

- inventories all user-visible metric surfaces
- groups changes by presentation boundary
- uses TDD for each affected area
- includes verification commands for v15 and v16 where relevant
