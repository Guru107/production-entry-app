# Report Default Numeric Formatting Design

## Goal

Stop forcing rounded numeric formatting in app reports and let Frappe's default numeric rendering handle report values.

This applies to the script reports under `production_entry_app/production_entry_app/report/`.

## Current State

The reports return numeric data through Python script reports. Most numeric columns already rely on Frappe defaults, but some report columns define explicit `precision` values.

Those overrides create inconsistent display behavior and are the likely reason some reports currently show rounded values instead of the default formatting the framework would normally apply.

One known example is `production_oee_report.py`, which currently defines an `OEE` column with `precision: 0`.

## Requirements

1. Reports should use Frappe's default display formatting for numeric values.
2. Report row values must remain numeric, not preformatted strings.
3. Existing report calculations must stay unchanged.
4. Only report-specific precision overrides that force rounding should be removed or relaxed.
5. Sorting, totals, exports, and charts must continue to operate on numeric values.

## Recommended Approach

Remove explicit numeric precision overrides from report column definitions and let Frappe defaults render the values.

### Why this approach

This is the smallest change that matches the new requirement:

- less code churn
- no framework-level formatting reimplementation
- no forced app-wide `precision: 2` policy
- preserves numeric data flow

It also aligns with the user's preference to trust framework defaults instead of stamping precision metadata onto every report column.

## Rejected Approaches

### 1. Add `precision: 2` to every numeric report column

Rejected because it makes the app own formatting behavior explicitly when the new direction is to trust Frappe defaults.

### 2. Convert numeric values to strings in report rows

Rejected because it would break sorting, totals, exports, and chart/report-summary math.

### 3. Round computed values before returning them

Rejected because it changes data semantics instead of just display semantics.

## Implementation Design

### Report audit

Audit report modules under `production_entry_app/production_entry_app/report/` for numeric columns that explicitly define `precision`.

Focus on numeric fieldtypes such as:

- `Float`
- `Percent`
- `Currency`

### Remove app-owned rounding overrides

Where a report column explicitly forces rounded output, remove that `precision` override so Frappe formats the numeric value using its own defaults.

This should be especially reviewed in:

- `production_oee_report`
- any trend, pareto, matrix, or efficiency report with explicit numeric precision

### Keep numeric values numeric

Do not:

- format values into strings
- round values before returning rows
- add custom frontend formatters

The Python report code should continue returning numeric values and standard column metadata, with fewer app-specific precision constraints.

## Testing Strategy

Add or update tests to verify:

1. Reports no longer carry the explicit precision overrides that were forcing rounding.
2. Numeric row values remain numeric.
3. Existing report schemas and calculations still pass.

The most important regression tests are for reports that currently contain explicit precision metadata, especially `production_oee_report`.

## Risks and Trade-offs

### Framework-owned behavior

Formatting becomes dependent on Frappe defaults. That is intentional, but it means future framework changes may alter numeric display without app code changes.

### Less explicit contract

The app will no longer state numeric display precision in report column metadata. This reduces code noise, but it also means the formatting contract is less explicit in the codebase.

### Potential mixed defaults across fieldtypes

If Frappe renders `Float`, `Percent`, and `Currency` with different default precision behaviors, the app will inherit that variation.

## Success Criteria

- Rounded report-specific precision overrides are removed.
- Reports display numeric values using Frappe defaults.
- Numeric sorting and totals still work.
- Existing report logic remains unchanged.
