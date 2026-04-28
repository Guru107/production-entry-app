# AI-SLOP High/Critical Cleanup Design

Date: 2026-04-28
Branch: feature/alternative-item-selection-manufacturing-entry

## Goal

Reduce every high and critical AI-SLOP detector finding without changing application behavior.

The refactor must preserve public APIs, report contracts, database query semantics, Stock Entry mutation order, and existing E2E/test fixture behavior. Detector score improvement is secondary to regression safety.

## Current Detector Baseline

Latest scan result:

- Files analyzed: 51
- Clean files: 47
- Suspicious files: 4
- Average deficit score: 6.69/100
- Overall status: clean

Suspicious files:

- `production_entry_app/production_entry_app/api.py`
- `production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py`
- `production_entry_app/production_entry_app/lifecycle.py`
- `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`

The detector also lists high and critical findings under files currently marked clean. Those are in scope, but lower priority than the suspicious files.

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

## Phase 1: Suspicious Files

### `api.py`

Targets:

- `_cleanup_e2e_context`
- `_apply_direct_manufacture_alternative_flags`
- `create_e2e_full_shift_stock_entries`

Plan:

- Split E2E cleanup into candidate collection, safe cancel/delete, cached settings restore, cached shift cleanup, and result aggregation helpers.
- Split alternative-item flag application into row selection and row mutation helpers.
- Split E2E stock-entry fixture creation only where setup sequence and returned payload stay identical.

Verification:

- Run `production_entry_app.production_entry_app.test_api` on bench15.
- Run targeted E2E bootstrap/cleanup tests if affected.

### `production_oee_report.py`

Targets:

- `_get_stock_entry_groups`
- `_get_availability_hours_by_group`
- `_apply_loss_buckets_for_chunk`

Plan:

- Split stock-entry grouping into query execution, row normalization, group mutation, and finalization helpers.
- Split availability calculations into linked-shift collection, loss deduction, and per-group hour aggregation helpers.
- Split loss bucket application into interval clipping and bucket accumulation helpers.

Verification:

- Run `production_entry_app.production_entry_app.report.test_reports` on bench15.
- Pay special attention to existing OEE tests for shift split, cross-midnight losses, linked-shift availability, unmapped loss reasons, raw runtime values, and running shift extension.

### `stock_entry_hooks.py`

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

Verification:

- Run `production_entry_app.production_entry_app.overrides.test_stock_entry_hooks` on bench15.
- Run relevant Stock Entry E2E tests if validation or visible behavior is touched.

### `lifecycle.py`

Current detector output reports this file as suspicious due low logic density, but no high or critical subfinding was reported in the parsed result.

Plan:

- Inspect the file in detail before editing.
- Do not refactor this file unless a high or critical finding is confirmed by a file-level detector run.

## Phase 2: Clean Files With High/Critical Report Findings

Targets include report modules with complex `_get_rows` functions:

- `daily_strokes_spm_monitor.py`
- `operator_daily_spm_report.py`
- `rejection_pareto_report.py`
- `rejection_ppm_report.py`
- `rejection_trend_report.py`
- `rework_pareto_report.py`
- `rework_ppm_report.py`
- `rework_trend_report.py`
- `item_bom_rejection_hotspots.py`
- `item_bom_rework_hotspots.py`
- `operator_rejection_performance.py`
- `operator_rework_performance.py`
- `workstation_rejection_reason_matrix.py`
- `workstation_rework_reason_matrix.py`
- `workstation_efficiency_report.py`
- `operator_efficiency_report.py`

Plan:

- Use local helper extraction around existing stages: build filters, fetch rows, aggregate, finalize, chart.
- Keep every report contract unchanged.
- Avoid creating a generic report framework during this cleanup.

Verification:

- Run `production_entry_app.production_entry_app.report.test_reports` after each report group or small batch.
- Run AI-SLOP detector after each batch.

## Phase 3: Remaining Clean-File High/Critical Findings

Targets:

- `shift.py`: summary assembly, aggregate production entries, planned-loss comparison and population.
- `api_timeline.py`: timeline data assembly.
- `report_benchmark.py`: benchmark loop structure.
- `write_benchmark.py`: write benchmark case execution.
- `report_utils.py`: quantity metric helpers.
- `utils/loss_time.py`: interval normalization and clipping logic.

Plan:

- Use small extraction commits per file.
- Preserve helper return shapes and numeric precision behavior.
- Prefer characterization tests for functions with complex numeric or time-window behavior.

Verification:

- Run targeted module tests for each touched file.
- Run report tests for report utility changes.
- Run Shift tests for `shift.py` changes.
- Run timeline tests for `api_timeline.py` changes.

## Verification Strategy

Each phase must include:

- AI-SLOP detector run.
- Targeted bench15 Frappe tests for touched modules.
- Bench16 targeted tests for compatibility-sensitive paths.
- `pre-commit run --all-files` before committing implementation changes.

Recommended commands:

```bash
scripts/check_ai_slop.sh
pre-commit run --all-files
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module <module>
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module <module>
```

## Commit Strategy

- Commit design separately.
- Commit implementation by subsystem or file group.
- Do not mix detector config changes with application refactors.
- Do not batch unrelated report, API, and Stock Entry changes together.

## Open Risk

Some detector findings may remain if removing them would require behavior-risky redesign. In that case, record the trade-off and leave the code unchanged rather than forcing a metric-only refactor.
