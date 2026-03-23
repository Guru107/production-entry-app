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

- Custom form metrics and HTML summaries
- User-visible metric fields written onto documents
- Script reports and query-report style outputs rendered in ERPNext
- API payloads that directly feed custom UI rendering

### Out of Scope

- Internal intermediate calculations used only for aggregation or validation
- Validation/tolerance precision rules that are about correctness rather than display
- Non-numeric explanatory text such as `metrics_note`
- Benchmarks and raw-value assertions that intentionally verify unrounded internals

## Source Of Truth

The display rule for this project is:

- all user-visible metrics should follow `System Settings.float_precision`
- internal calculations should remain raw until they cross a presentation boundary

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

- audit every displayed metric in the Shift summary and workstation tables
- ensure all custom HTML rendering paths use the same resolved system precision
- keep summary calculations raw in Python
- ensure summary payloads include `float_precision` anywhere the client renders custom metric HTML

### 2. Stock Entry User-Visible Metrics

File:

- `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`

Plan:

- audit user-visible metric fields populated by hook logic, including:
  - actual SPM
  - operator efficiency %
  - die tool utilization %
  - die tool maintenance due
- determine whether field metadata already gives consistent display formatting
- only add explicit precision-aware handling where values bypass normal Frappe field rendering

### 3. UI-Facing APIs

Files:

- `production_entry_app/production_entry_app/api.py`
- any other endpoint returning metric payloads for custom UI

Plan:

- audit endpoints such as die tool and shift/timeline-related payloads
- where the consumer is a custom widget, include `float_precision` metadata if not already available
- avoid server-side blanket rounding unless the payload is display-only and has no downstream computational use

### 4. Reports

Directory:

- `production_entry_app/production_entry_app/report/`

Plan:

- audit report column definitions for user-visible metrics such as:
  - SPM
  - efficiency %
  - OEE %
  - PPM
  - utilization %
  - rejection/rework performance rates
- add explicit `precision` to metric columns where missing
- standardize report metric columns to inherit the resolved system precision
- avoid altering raw aggregation helpers unless they currently format or truncate values prematurely

## Helper Strategy

### Python

Add a small shared helper under `production_entry_app/production_entry_app/utils/` to:

- resolve `System Settings.float_precision`
- provide a reusable display precision value for reports and API payloads

This helper should be lightweight and narrowly scoped. It should not become a broad formatting abstraction.

### JavaScript

Add or reuse a small utility for custom widget rendering that:

- resolves system precision from payload metadata first
- falls back to `frappe.boot.sysdefaults.float_precision`
- applies consistent rendering for custom HTML/cards/widgets

## Precision Policy Details

### Reports And Frappe Fields

For normal report columns and DocField-backed rendering:

- prefer numeric values plus explicit `precision`
- let Frappe render the display according to the configured precision

### Custom HTML Widgets

For custom HTML surfaces:

- do not rely on raw JavaScript string coercion
- use the resolved system precision explicitly when rendering

### API Payloads

For UI-facing APIs:

- prefer returning raw numeric values plus `float_precision`
- let the consumer apply the display rule

This keeps API payloads usable while still making display consistent.

## Verification Strategy

Verification must prove both correctness and consistency.

### Automated Checks

- add or update unit tests for the new precision helper(s)
- add/update tests for shift summary rendering or payload precision behavior
- add/update representative report tests covering:
  - SPM reports
  - efficiency and OEE reports
  - PPM/rejection/rework rate reports
  - die tool metrics

### Test Policy

- preserve existing tests that intentionally verify raw values in internal calculations
- add separate assertions for user-visible precision configuration and display-facing payload behavior

### Manual Checks

At least one manual verification pass should confirm that changing `System Settings.float_precision` changes the UI display consistently in:

- one custom form/widget path
- one report path

## Success Criteria

- Changing `System Settings.float_precision` changes user-visible metric display consistently across audited surfaces.
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
