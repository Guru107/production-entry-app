# AI-SLOP High/Critical Cleanup Design

Date: 2026-04-28
Branch: feature/alternative-item-selection-manufacturing-entry
Scan artifact: `reports/ai-slop-report.json` generated with `uvx --from 'ai-slop-detector[js]==3.6.0' slop-detector --project . --config .slopconfig.yaml --js --json --no-history`

## Goal

Reduce every high and critical AI-SLOP detector finding without changing application behavior.

The refactor must preserve public APIs, report contracts, database query semantics, Stock Entry mutation order, and existing E2E/test fixture behavior. Detector score improvement is secondary to regression safety.

## Detector Baseline And Semantics

Latest scan result:

- Files analyzed: 51
- Clean files: 47
- Suspicious files: 4
- Average deficit score: 6.69/100
- Weighted deficit score: 17.57/100
- Overall status: clean

The detector can report `overall_status: clean` while still marking individual files as `suspicious`. In this plan, success is not based only on `overall_status`. Success means every high and critical finding in the findings inventory is either removed by behavior-preserving extraction or explicitly retained with a documented behavior-risk trade-off.

## Findings Inventory

### Suspicious Files

| File | Function | Severity | Detector reason | Intended action | Leave unchanged only if |
| --- | --- | --- | --- | --- | --- |
| `api.py` | `_apply_direct_manufacture_alternative_flags` | high | complexity 14, limit 10 | Extract row selection and mutation helpers | Extraction changes row order, flag semantics, or returned document state |
| `api.py` | `_cleanup_e2e_context` | high/critical | 115 logic lines, complexity 37, deep nesting depth 4 | Extract cleanup stages into candidate collection, delete/cancel, settings restore, cache cleanup, result aggregation | Any helper boundary changes deletion order, ignored exception handling, or result payload |
| `api.py` | `create_e2e_full_shift_stock_entries` | high | 70 logic lines, complexity 14 | Extract fixture setup substeps without changing sequence | Existing tests depend on exact fixture creation ordering that cannot be preserved clearly |
| `production_oee_report.py` | `_get_stock_entry_groups` | high/critical | 94 logic lines, complexity 23, deep nesting depth 4 | Extract query, row normalization, group update, and finalization helpers | Query or aggregation equivalence cannot be demonstrated |
| `production_oee_report.py` | `_get_availability_hours_by_group` | high | 59 logic lines, complexity 12 | Extract shift collection, planned-loss deduction, and group-hour accumulation helpers | Numeric equivalence cannot be proven with existing OEE tests |
| `production_oee_report.py` | `_apply_loss_buckets_for_chunk` | high | complexity 19 | Extract interval clipping and bucket accumulation helpers | Cross-midnight/loss-bucket behavior becomes ambiguous |
| `stock_entry_hooks.py` | `_validate_actual_times` | high | complexity 12 | Extract guard and datetime validation helpers | Error message/order changes |
| `stock_entry_hooks.py` | `_validate_unplanned_losses_within_actual_window` | high | complexity 11 | Extract loss row interval validation helper | Error message/order changes |
| `stock_entry_hooks.py` | `_validate_direct_manufacture_alternative_items` | high | complexity 16 | Extract item-row checks and configured-alternative predicate use | Alternative item validation semantics change |
| `stock_entry_hooks.py` | `_validate_rejection_breakup` | high | complexity 11 | Extract quantity aggregation and tolerance comparison helpers | Rounding/tolerance behavior changes |
| `stock_entry_hooks.py` | `_apply_rejection_entries` | high | complexity 15 | Extract row building and warehouse resolution helpers | Stock Entry item mutation ordering changes |
| `stock_entry_hooks.py` | `_get_deducted_loss_minutes_for_entry` | high | complexity 12 | Extract planned-loss clipping and summation helpers | Shift planned-loss deduction changes |

### Suspicious File Without Confirmed High/Critical Finding

| File | Finding | Action gate |
| --- | --- | --- |
| `lifecycle.py` | suspicious due low logic density, no parsed high/critical finding | Run file-level detector. If no high/critical finding is present, skip this file and document it as out of high/critical scope. |

Required lifecycle gate:

```bash
uvx --from 'ai-slop-detector[js]==3.6.0' slop-detector --project production_entry_app/production_entry_app/lifecycle.py --config .slopconfig.yaml --json --no-history
```

Skipping `lifecycle.py` after this gate does not fail the goal, because the requested scope is high and critical findings.

### Clean Files With High/Critical Findings

| File | Function | Severity | Detector reason | Intended action |
| --- | --- | --- | --- | --- |
| `report/report_benchmark.py` | `_benchmark_reports` | high/critical | nesting depth 5, structural complexity composite | Extract report invocation loop and result measurement helpers |
| `doctype/shift/shift.py` | `_build_workstation_summary_rows` | high | 67 logic lines, complexity 14 | Extract row accumulation and ranking helpers |
| `doctype/shift/shift.py` | `get_shift_summary` | high | 182 logic lines, complexity 28 | Extract summary sections while preserving payload |
| `doctype/shift/shift.py` | `get_shift_aggregate_production_entries` | high | 75 logic lines, complexity 11 | Extract row shaping and totals helpers |
| `doctype/shift/shift.py` | `_planned_losses_changed` | high | complexity 11 | Extract comparable row normalization helper |
| `doctype/shift/shift.py` | `_populate_planned_losses` | high | 82 logic lines, complexity 12 | Extract loss-template selection and child-row append helpers |
| `report/daily_strokes_spm_monitor.py` | `_get_date_range` | high | complexity 12 | Extract fiscal year validation and range calculation helpers |
| `report/daily_strokes_spm_monitor.py` | `_get_rows` | high/critical | 110 logic lines, complexity 22, deep nesting depth 4 | Extract row query, aggregation, totals, and finalization helpers |
| `write_benchmark.py` | `_run_write_case` | critical | deep nesting depth 4, structural complexity composite | Extract per-attempt execution and timing helpers |
| `report/report_utils.py` | `get_parent_quantity_metrics` | high | 79 logic lines, complexity 12 | Extract quantity source and rejection/rework split helpers |
| `report/report_utils.py` | `get_entry_total_strokes` | high | complexity 13 | Extract fallback and item-row stroke helpers |
| `api_timeline.py` | `get_shift_timeline_data` | high | 140 logic lines, complexity 22 | Extract data loading, interval shaping, and response assembly helpers |
| `utils/loss_time.py` | `resolve_time_interval_in_window` | high | complexity 13 | Extract parsing, clipping, and validation helpers |
| `report/rejection_pareto_report.py` | `_get_rows` | high | complexity 14 | Extract aggregation and cumulative percentage helpers |
| `report/rejection_ppm_report.py` | `_get_rows` | high | 57 logic lines, complexity 16 | Extract parent quantity and ppm row helpers |
| `report/workstation_rework_reason_matrix.py` | `_get_rows` | high | 51 logic lines, complexity 15 | Extract top-reason aggregation helpers |
| `report/operator_daily_spm_report.py` | `_get_rows` | high | 99 logic lines, complexity 18 | Extract query, grouping, and final row helpers |
| `report/workstation_rejection_reason_matrix.py` | `_get_rows` | high | 51 logic lines, complexity 15 | Extract top-reason aggregation helpers |
| `report/rework_trend_report.py` | `_get_rows` | high | 60 logic lines, complexity 15 | Extract period aggregation helpers |
| `report/item_bom_rejection_hotspots.py` | `_get_rows` | high | 75 logic lines, complexity 22 | Extract item/BOM aggregation helpers |
| `report/rework_ppm_report.py` | `_get_rows` | high | complexity 14 | Extract ppm row helpers |
| `report/rejection_trend_report.py` | `_get_rows` | high | 52 logic lines, complexity 13 | Extract period aggregation helpers |
| `report/operator_rework_performance.py` | `_get_rows` | high | 82 logic lines, complexity 25 | Extract operator aggregation and ranking helpers |
| `report/item_bom_rework_hotspots.py` | `_get_rows` | high | 77 logic lines, complexity 24 | Extract item/BOM aggregation helpers |
| `report/workstation_efficiency_report.py` | `_get_rows` | high | 60 logic lines, complexity 12 | Extract workstation aggregation helpers |
| `report/operator_efficiency_report.py` | `_get_rows` | high | 61 logic lines, complexity 12 | Extract operator aggregation helpers |
| `report/operator_rejection_performance.py` | `_get_rows` | high | 97 logic lines, complexity 24 | Extract operator aggregation and ranking helpers |
| `report/rework_pareto_report.py` | `_get_rows` | high | complexity 14 | Extract aggregation and cumulative percentage helpers |

## Hard Constraints

- No behavior changes from this refactor.
- Keep public function names and whitelisted API names unchanged.
- Keep report `execute()` signatures unchanged.
- Keep report columns, fieldnames, precision behavior, sorting, chart payloads, and row schemas unchanged.
- Keep query filters, joins, grouping, ordering, and aliases logically identical.
- Keep Stock Entry validation and mutation order unchanged.
- Avoid broad shared abstractions unless the existing code already has the same shape.
- Prefer local helper extraction over moving logic across modules.
- Commit by subsystem so regressions can be bisected.

## Behavior Characterization Requirements

Before editing a subsystem, capture its current behavior with tests or snapshots. After editing, compare the same behavior.

### Reports

For each report module touched:

- Run the existing report test cases that exercise the module.
- If a report has no direct test for a touched branch, add a characterization test before refactoring.
- Capture representative `execute(filters)` outputs in test assertions: columns, row count, key row values, sorting, chart payload where applicable, and precision-sensitive raw values.
- For query-heavy functions, compare the generated SQL or query-builder-selected fields before and after when feasible. If direct SQL extraction is not feasible, use tests that assert selected fields, aliases, grouping behavior, ordering, and filter effects through report output.

### API And E2E Helpers

For touched E2E helper APIs:

- Assert returned payload keys and values before and after refactor.
- Assert cleanup counts and ignored-error behavior where existing tests cover it.
- Preserve cache key usage and settings restore order.

### Stock Entry Hooks

For touched Stock Entry hooks:

- Assert validation error messages and ordering for invalid documents.
- Assert document snapshots before/after mutation for rejection entry application and alternative-item validation.
- Preserve item row order and warehouse selection behavior.

### Time And Numeric Helpers

For time-window and quantity helpers:

- Assert edge cases around empty inputs, boundary timestamps, cross-midnight windows, zero quantity, and precision/tolerance.
- Preserve raw numeric values where reports intentionally avoid early rounding.

## Approach Options Considered

### Option 1: Suspicious Files Only

Scope only the four suspicious files.

Trade-off: fastest detector-risk reduction, but leaves many high and critical findings in files marked clean. This does not satisfy the requested scope.

### Option 2: All High/Critical Findings In Risk Phases

Handle every high and critical finding, starting with suspicious files and then moving through clean files by subsystem risk.

Trade-off: more work and more verification, but safest for behavior preservation and best match for the requested scope.

Decision: use this approach.

### Option 3: Score-Driven Batch Refactor

Work down the highest detector scores regardless of subsystem.

Trade-off: improves the metric quickly, but mixes unrelated behavior areas and makes regression analysis harder.

## Design Principles

- Extract helpers only where inputs and outputs can remain identical.
- Use characterization tests where existing tests do not cover a touched path.
- Do not optimize queries or alter data structures unless required to preserve behavior after extraction.
- Do not consolidate report modules into a framework during this cleanup.
- Leave a finding in place if removing it would require a behavior-risky redesign.

## Phase 1: Suspicious High/Critical Files

### Batch 1A: `api.py`

Targets:

- `_cleanup_e2e_context`
- `_apply_direct_manufacture_alternative_flags`
- `create_e2e_full_shift_stock_entries`

Plan:

- Split E2E cleanup into candidate collection, safe cancel/delete, cached settings restore, cached shift cleanup, and result aggregation helpers.
- Split alternative-item flag application into row selection and row mutation helpers.
- Split E2E stock-entry fixture creation only where setup sequence and returned payload stay identical.

Required verification before commit:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
scripts/check_ai_slop.sh
pre-commit run --all-files
```

### Batch 1B: `production_oee_report.py`

Targets:

- `_get_stock_entry_groups`
- `_get_availability_hours_by_group`
- `_apply_loss_buckets_for_chunk`

Plan:

- Split stock-entry grouping into query execution, row normalization, group mutation, and finalization helpers.
- Split availability calculations into linked-shift collection, planned-loss deduction, and per-group hour aggregation helpers.
- Split loss bucket application into interval clipping and bucket accumulation helpers.

Required verification before commit:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
scripts/check_ai_slop.sh
pre-commit run --all-files
```

The existing OEE tests must remain green, especially shift split, cross-midnight losses, linked-shift availability, unmapped loss reasons, raw runtime values, and running shift extension.

### Batch 1C: `stock_entry_hooks.py`

Targets:

- `_validate_actual_times`
- `_validate_unplanned_losses_within_actual_window`
- `_validate_direct_manufacture_alternative_items`
- `_validate_rejection_breakup`
- `_apply_rejection_entries`
- `_get_deducted_loss_minutes_for_entry`

Plan:

- Split validators into guard checks, data extraction, predicate helpers, and throw helpers.
- Keep validation ordering unchanged.
- Keep document mutation ordering unchanged, especially for rejection row removal and insertion.

Required verification before commit:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
npm run test:unit:js
scripts/check_ai_slop.sh
pre-commit run --all-files
```

### Batch 1D: `lifecycle.py` Gate

Run the file-level detector command from the lifecycle gate section. If no high or critical finding exists, record the result in the implementation notes and skip code changes. If a high or critical finding exists, create a local extraction plan and run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_lifecycle
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_lifecycle
scripts/check_ai_slop.sh
pre-commit run --all-files
```

## Phase 2: Clean Report Files With High/Critical Findings

Batch reports by behavior family, not by score. Each batch gets its own implementation commit.

### Batch 2A: Pareto And PPM Reports

Files:

- `rejection_pareto_report.py`
- `rework_pareto_report.py`
- `rejection_ppm_report.py`
- `rework_ppm_report.py`

Required verification:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
scripts/check_ai_slop.sh
pre-commit run --all-files
```

### Batch 2B: Trend Reports

Files:

- `rejection_trend_report.py`
- `rework_trend_report.py`

Required verification: same as Batch 2A.

### Batch 2C: Matrix Reports

Files:

- `workstation_rejection_reason_matrix.py`
- `workstation_rework_reason_matrix.py`

Required verification: same as Batch 2A.

### Batch 2D: Item/BOM Hotspot Reports

Files:

- `item_bom_rejection_hotspots.py`
- `item_bom_rework_hotspots.py`

Required verification: same as Batch 2A.

### Batch 2E: Operator Performance Reports

Files:

- `operator_rejection_performance.py`
- `operator_rework_performance.py`

Required verification: same as Batch 2A.

### Batch 2F: Efficiency Reports And Shared Report Utils

Files:

- `workstation_efficiency_report.py`
- `operator_efficiency_report.py`
- `report_utils.py`

Required verification: same as Batch 2A. Run bench16 report tests if `report_utils.py` changes because it is shared.

### Batch 2G: Daily SPM Reports

Files:

- `daily_strokes_spm_monitor.py`
- `operator_daily_spm_report.py`

Required verification: same as Batch 2A. Include tests for fiscal-year date ranges and totals rows.

## Phase 3: Remaining Clean-File High/Critical Findings

### Batch 3A: Shift Summary

File:

- `shift.py`

Required verification:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
scripts/check_ai_slop.sh
pre-commit run --all-files
```

### Batch 3B: Timeline API

File:

- `api_timeline.py`

Required verification:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline
scripts/check_ai_slop.sh
pre-commit run --all-files
```

### Batch 3C: Benchmarks

Files:

- `report_benchmark.py`
- `write_benchmark.py`

Required verification:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_report_benchmark
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_write_benchmark
scripts/check_ai_slop.sh
pre-commit run --all-files
```

### Batch 3D: Loss-Time Utility

File:

- `utils/loss_time.py`

Required verification:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_loss_time
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_loss_time
scripts/check_ai_slop.sh
pre-commit run --all-files
```

## Per-Commit Acceptance Criteria

Before every implementation commit:

- `git status --short` shows only intended files changed.
- Touched code has targeted tests passing on bench15.
- Compatibility-sensitive code has targeted tests passing on bench16.
- `scripts/check_ai_slop.sh` passes and the finding count does not increase.
- `pre-commit run --all-files` passes.
- If a high/critical finding remains intentionally, the commit message or implementation note records why behavior-risk outweighed detector cleanup.

## Query Preservation Criteria

For report query refactors:

- Keep selected fields and aliases unchanged.
- Keep joins and child-table relationships unchanged.
- Keep filters and default filter handling unchanged.
- Keep grouping and sorting unchanged.
- Preserve query parameter values for representative filters.
- If query-builder SQL can be captured without large churn, compare before/after SQL in local notes. If not, use existing report tests plus targeted characterization assertions for the same filters.

## Commit Strategy

- Commit design separately.
- Commit implementation by batch.
- Do not mix detector config changes with application refactors.
- Do not batch unrelated report, API, and Stock Entry changes together.
- Do not amend existing commits unless explicitly requested.

## Open Risk

Some detector findings may remain if removing them would require behavior-risky redesign. In that case, record the trade-off and leave the code unchanged rather than forcing a metric-only refactor.
