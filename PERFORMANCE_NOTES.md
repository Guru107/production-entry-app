# Performance Notes

## Current defaults

- All Production Entry App reports now use Frappe `Prepared Report` mode by default.
- The interactive timeout guard in report code is only enforced when a report is explicitly opened with `ignore_prepared_report=1`.
- Standard report execution should therefore use the native Frappe background/prepared flow unless a developer or test deliberately opts into live execution.

## Local benchmark evidence

### Report-path benchmark dataset

- Dataset key: `PHASE2`
- Seed size used for main throughput validation: `10,000` Manufacture Stock Entries
- Harness: [report_benchmark.py](/Users/gurudattkulkarni/Workspace/production-entry-app/apps/production_entry_app/production_entry_app/production_entry_app/report/report_benchmark.py)

### A/B result against baseline

Measured on the same seeded `PHASE2` dataset:

- Current branch materially reduced peak Python memory:
  - `operator_efficiency`: about `61%` lower
  - `workstation_efficiency`: about `63%` lower
  - `production_oee`: about `58%` lower
- The initial chunking/keyset refactor improved survivability and bounded memory growth.
- It did not improve raw throughput by itself.

### Throughput follow-up result

After bundled parent aggregations, OEE single-pass refactor, and grouped breakup queries:

- `operator_efficiency`: `4986.62 ms`, `5838.05 KB`, `41 SQL`, `11` chunk fetches
- `workstation_efficiency`: `4990.67 ms`, `5650.80 KB`, `41 SQL`, `11` chunk fetches
- `production_oee`: `5243.05 ms`, `6095.68 KB`, `43 SQL`, `11` chunk fetches

Practical reading:

- Memory safety is retained.
- Throughput improved enough to offset much of the earlier chunking overhead.
- OEE especially benefited from removing the second Stock Entry traversal.

### Matrix / pareto / hotspot benchmark smoke

Measured on the same `PHASE2` dataset after grouped breakup refactors:

- `rejection_pareto`: `958.6 ms`
- `workstation_rejection_matrix`: `978.98 ms`
- `item_bom_rejection_hotspots`: `3378.09 ms`

These are smoke timings, not baseline A/B comparisons.

## Write-path benchmark evidence

Harness: [write_benchmark.py](/Users/gurudattkulkarni/Workspace/production-entry-app/apps/production_entry_app/production_entry_app/production_entry_app/write_benchmark.py)

Measured on `development.localhost` using the seeded `PHASE2` dataset with warmup iterations:

- `with_overlap_indexes`
  - avg save latency: `47.52 ms`
  - p95 save latency: `50.09 ms`
  - avg SQL count: `52`
- `without_overlap_indexes`
  - avg save latency: `117.26 ms`
  - p95 save latency: `117.44 ms`
  - avg SQL count: `52`

Conclusion:

- The overlap indexes are not speculative on the local benchmark dataset.
- The gain is from better access paths, not fewer queries.

## Index validation status

Planner validation on the local seeded dataset showed:

- workstation overlap query selects `idx_pea_ste_workstation_actual_window`
- operator overlap query selects `idx_pea_ste_operator_actual_window`
- downtime overlap query selects `idx_pea_dte_workstation_window`

Deferred item:

- Any redesign of the Stock Entry overlap indexes is deferred until future production-like evidence shows a better index order with no write regression.

## Rollout guidance for development

Because the app is still under development and not deployed:

- keep report JSON files with `prepared_report: 1`
- run `bench --site development.localhost migrate`
- if an existing local site keeps stale `tabReport.prepared_report = 0`, fix those rows once on the dev site and move on

The code intentionally does not include a permanent report-sync hook for this development-stage requirement.

## Checklist status

- The earlier `async fallback` checklist item was intentionally superseded by making all reports prepared reports by default.
- The earlier Frappe test bootstrap timestamp issue was fixed by making test setup idempotent in [test_setup.py](/Users/gurudattkulkarni/Workspace/production-entry-app/apps/production_entry_app/production_entry_app/production_entry_app/utils/test_setup.py).
- There are no known open checklist items from the performance plan on the current branch.

## Useful commands

```bash
# Report throughput benchmark
bench --site development.localhost execute \
  production_entry_app.production_entry_app.report.report_benchmark.run_report_benchmark \
  --kwargs '{"entry_count": 10000, "day_span": 20, "dataset_key": "PHASE2", "keep_data": 1}'

# Write-path benchmark
bench --site development.localhost execute \
  production_entry_app.production_entry_app.write_benchmark.run_stock_entry_write_benchmark \
  --kwargs '{"iterations": 3, "warmup_iterations": 1, "source_dataset_key": "PHASE2", "keep_data": 1}'
```
