# Report Two-Decimal Precision Design

## Goal

Make all numeric values displayed by the app's reports render with exactly `2` decimal places.

This applies to the script reports under `production_entry_app/production_entry_app/report/` and must preserve:

- numeric sorting
- report totals
- exports
- chart/report-summary math

## Current State

The reports currently define numeric columns directly inside each report module. Many columns use:

- `fieldtype: "Float"`
- `fieldtype: "Percent"`
- `fieldtype: "Currency"`

Most of those columns do not declare `precision`, so the rendered decimal behavior depends on Frappe defaults or per-report overrides.

There is already at least one explicit override in `production_oee_report.py` where `OEE` uses `precision: 0`, which means the app already has inconsistent numeric formatting across reports.

## Requirements

1. All report columns with `Float`, `Percent`, or `Currency` fieldtypes must use `precision: 2`.
2. Underlying data rows must remain numeric, not preformatted strings.
3. Existing report calculations must not be rounded before computation.
4. Any report summary blocks that explicitly return numeric metrics should also render to `2` decimal places where the summary API supports it.
5. Count-style columns that are intentionally integral should remain unchanged if they are not defined as decimal-oriented numeric fields.

## Recommended Approach

Use column metadata as the source of truth and enforce `precision: 2` at the column-definition layer.

### Why this approach

This is the safest way to change display precision without breaking:

- numeric sorting
- report aggregations
- CSV/XLS exports
- chart inputs
- downstream report consumers

It also fits the current codebase because report columns are already declared explicitly in each module.

## Rejected Approaches

### 1. Convert numeric row values to formatted strings

Rejected because it would break sorting, totals, charts, and any consumer expecting numbers.

### 2. Round all computed values to 2 decimals before returning rows

Rejected because it mixes presentation with calculation and can introduce avoidable numeric drift in derived metrics.

### 3. Add a generic formatting hook only on the frontend

Rejected because the app’s reports are primarily controlled by Python column metadata today, and a frontend-only solution would be less explicit and harder to verify report-by-report.

## Implementation Design

### Column updates

Each report module will be updated so any column declared with:

- `Float`
- `Percent`
- `Currency`

also includes:

```python
"precision": 2
```

This includes reports such as:

- `daily_strokes_spm_monitor`
- `die_tool_stroke_and_maintenance_report`
- `item_bom_rejection_hotspots`
- `item_bom_rework_hotspots`
- `operator_daily_spm_report`
- `operator_efficiency_report`
- `operator_rejection_performance`
- `operator_rework_performance`
- `production_oee_report`
- `rejection_pareto_report`
- `rejection_ppm_report`
- `rejection_trend_report`
- `rework_pareto_report`
- `rework_ppm_report`
- `rework_trend_report`
- `workstation_efficiency_report`
- `workstation_rejection_reason_matrix`
- `workstation_rework_reason_matrix`

### Shared helper

If the report modules already follow a sufficiently uniform column-building pattern, a small shared helper may be introduced in `report_utils.py` to reduce duplication. The helper must stay simple and explicit, for example:

- input: list of column dicts
- behavior: add `precision: 2` to numeric columns that do not already define precision

This helper is optional, not mandatory. If a helper makes the code less clear, the implementation should prefer direct per-report edits.

### Special-case overrides

Any existing numeric columns with a different precision, including `precision: 0`, will be normalized to `2` unless there is a documented reason not to. Based on the current request, the default assumption is that visual consistency takes priority.

## Testing Strategy

Add or extend tests in `production_entry_app/production_entry_app/report/test_reports.py` so they verify:

1. Numeric report columns use `precision: 2`.
2. Row values remain numeric.
3. Existing report calculations and schemas still pass.

The tests should focus on representative modules and any reports with known overrides, especially:

- `production_oee_report`
- trend reports
- pareto reports
- matrix reports
- efficiency reports

If a shared helper is introduced, add direct unit coverage for that helper as well.

## Risks and Trade-offs

### Longer edit surface

Touching many report modules increases the chance of a missed file. The mitigation is explicit test coverage over column metadata.

### Visual behavior changes

Some reports that currently display whole numbers or Frappe-default precision will now show trailing decimals like `12.00`. This is intentional per the requirement.

### Precision only affects presentation

The design does not round underlying computations to `2` decimals. This keeps calculations accurate, but users may still see rounded display values that differ slightly from raw intermediate math.

## Success Criteria

- All numeric columns across app reports display with `2` decimal places.
- Numeric sorting and totals still work.
- Existing report tests remain green.
- Added tests fail if a future report column is introduced without the required numeric precision.
