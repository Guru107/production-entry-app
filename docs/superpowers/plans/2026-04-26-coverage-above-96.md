# Coverage Above 96 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise verified test coverage above 96% for the Production Entry App test suite while keeping unit, integration, and E2E coverage meaningful.

**Architecture:** Define an explicit production coverage gate, fix Frappe test discovery gaps, then add focused tests for the highest-miss modules. Treat Playwright E2E as a separate pass/fail gate because current E2E runs do not instrument Python server line coverage.

**Tech Stack:** Frappe bench test runner, coverage.py, Python `FrappeTestCase`, Playwright E2E, pre-commit.

---

## Current Baseline

Measured on bench16 from `/Users/gurudattkulkarni/Workspace/bench16`:

```bash
bench --site frappe16.localhost run-tests --app production_entry_app --coverage
```

Current result after top-level discovery shims:

- Overall XML coverage: `91.79%` (`9257/10085` lines)
- Production source coverage excluding tests and benchmark helper modules: `89%` (`3709` statements, `424` missed)
- Full test result: `516` tests, `OK`

Main remaining missed production areas:

- `production_entry_app/production_entry_app/api.py`: `152` misses, mainly E2E bootstrap/cleanup data builders
- `production_entry_app/production_entry_app/doctype/shift/shift.py`: `77` misses, status/summary/timeline edge branches
- `production_entry_app/production_entry_app/report/report_utils.py`: `52` misses, chunking, quantity maps, precision, duration helpers
- `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`: `27` misses, edge validation and rejection-row branches
- Report modules: smaller branch misses across pareto/trend/matrix/OEE reports

## Trade-Offs

- Excluding `test_*.py` from the coverage gate is correct because test files should not inflate production coverage.
- Excluding `report_benchmark.py` and `write_benchmark.py` is acceptable because they are developer benchmarking tools, not runtime product code.
- Excluding `api.py` E2E bootstrap helpers would make the number easier to reach but weakens the gate because those APIs are security-sensitive test-only entry points. Prefer testing them with mocks instead.
- Instrumenting Playwright-driven server coverage would be more accurate for E2E but requires extra harness work around Frappe/coverage process startup. Keep this as a later improvement unless Python coverage remains below target after unit/integration additions.

---

### Task 1: Make Nested Tests Discoverable

**Files:**

- Create: `production_entry_app/production_entry_app/test_reports.py`
- Create: `production_entry_app/production_entry_app/test_doctypes.py`
- Create: `production_entry_app/production_entry_app/test_utils.py`

- [ ] **Step 1: Add discovery shims**

Import nested `Test*` classes from report, doctype, and utility test modules into top-level app test files so `bench --app production_entry_app` discovers them.

- [ ] **Step 2: Verify each shim directly**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_reports
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctypes
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_utils
```

Expected: all three module runs pass. Run them sequentially; parallel Frappe setup can collide on `Administrator` modified timestamps.

- [ ] **Step 3: Commit**

```bash
git add production_entry_app/production_entry_app/test_reports.py production_entry_app/production_entry_app/test_doctypes.py production_entry_app/production_entry_app/test_utils.py
git commit -m "test: discover nested app test modules"
```

---

### Task 2: Add An Explicit Coverage Gate

**Files:**

- Create: `.coveragerc`
- Modify: `.github/workflows/*.yml` only if CI needs to call the explicit gate

- [ ] **Step 1: Add `.coveragerc`**

```ini
[run]
source =
	production_entry_app

omit =
	*/test_*.py
	*/tests/*
	*/__pycache__/*
	*/report/report_benchmark.py
	*/write_benchmark.py
	setup.py

[report]
fail_under = 96
show_missing = True
skip_covered = False
precision = 2
```

- [ ] **Step 2: Verify the config is honored from bench root**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
coverage report --data-file sites/.coverage --rcfile /Users/gurudattkulkarni/Workspace/production-entry-app/.coveragerc -m
```

Expected now: fail under 96 until Tasks 3-7 are complete.

- [ ] **Step 3: Add CI command if needed**

If GitHub Actions only runs `bench ... --coverage`, add a post-step that runs coverage with the repo `.coveragerc` from the bench root.

---

### Task 3: Cover `report_utils.py` Utility Branches

**Files:**

- Modify: `production_entry_app/production_entry_app/report/test_report_utils_performance.py`
- Test: `production_entry_app.production_entry_app.test_reports`

- [ ] **Step 1: Write focused unit tests**

Add tests for:

- `build_stock_entry_filters()` with only `from_date`
- `build_stock_entry_filters()` with only `to_date`
- `new_interactive_report_timeout_guard()` inside budget
- `get_stock_entries_for_fg_item()` overflow guard
- `_validate_stock_entry_chunk_fields()` missing `posting_date`
- `_fetch_stock_entry_chunk()` missing keyset fields
- `get_entry_qty_maps(..., include_fg_item=True)` mapping FG item rows
- `get_parent_quantity_metrics(..., include_rework=True)` rejection and rework splits
- `get_parent_breakup_reason_rows(..., is_rework=True/False)` filters
- `get_loss_time_maps()` setup vs non-setup loss split
- `get_entry_total_strokes()` fallback paths
- `get_entry_production_minutes()` negative custom duration clamp
- `apply_system_precision()` and cached `get_report_float_precision()`
- `build_efficiency_rows()` zero-duration average actual SPM path

- [ ] **Step 2: Run report tests**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_reports
```

Expected: pass. Target impact: reduce `report_utils.py` misses from `52` to under `10`.

- [ ] **Step 3: Commit**

```bash
git add production_entry_app/production_entry_app/report/test_report_utils_performance.py
git commit -m "test: cover report utility edge cases"
```

---

### Task 4: Cover `api.py` E2E Bootstrap And Cleanup Branches

**Files:**

- Modify: `production_entry_app/production_entry_app/test_api.py`
- Test: `production_entry_app.production_entry_app.test_api`

- [ ] **Step 1: Add mock-based tests for low-risk helpers**

Add tests for:

- `_ensure_e2e_settings_fields_loaded()` reload path
- `set_e2e_access_control()` normal path
- `_cache_e2e_settings_snapshot()` no-op when cache exists
- `_cache_e2e_shift_name()` empty and duplicate names
- `_restore_cached_e2e_settings()` legacy and modern snapshots
- `_complete_other_running_e2e_shifts()` no-op and filtered completion paths
- `_get_or_create_e2e_employee()` existing and insert paths
- `_safe_cancel_and_delete()` missing doc, submitted doc, and exception paths

- [ ] **Step 2: Add integration-style tests for E2E creation APIs using mocks**

Add tests for:

- `set_e2e_system_float_precision()` commits and returns normalized precision
- `create_e2e_submitted_stock_entry()` appends rejection breakup only when `rejection_qty > 0`
- `create_e2e_full_shift_stock_entries()` clamps invalid slot size to one minute
- `create_e2e_full_shift_stock_entries()` rejects invalid shift windows
- `create_e2e_downtime_entry()` normalizes unsupported stop reasons to `Other`
- `cleanup_reserved_e2e_artifacts()` whitelisted wrapper guard path

- [ ] **Step 3: Run API tests**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected: pass. Target impact: reduce `api.py` misses from `152` to under `35`.

- [ ] **Step 4: Commit**

```bash
git add production_entry_app/production_entry_app/test_api.py
git commit -m "test: cover e2e bootstrap api edge cases"
```

---

### Task 5: Cover `shift.py` Summary And Transition Edges

**Files:**

- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`
- Test: `production_entry_app.production_entry_app.test_doctypes`

- [ ] **Step 1: Add tests for status and notification branches**

Add tests for:

- Notification path with no recipients
- Direct status edit rejection with `get_doc_before_save()` state
- Cancelled/completed transition rejection branches
- Missing warehouse/default settings branches

- [ ] **Step 2: Add tests for summary/timeline edge branches**

Add tests for:

- Empty linked production entries returns zeroed summary
- Target coverage below threshold hides efficiency
- Timeline data handles missing workstation/operator filters
- Overlapping downtime entries are clamped to shift boundaries
- Cross-midnight planned end handling

- [ ] **Step 3: Run doctype tests**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctypes
```

Expected: pass. Target impact: reduce `shift.py` misses from `77` to under `20`.

- [ ] **Step 4: Commit**

```bash
git add production_entry_app/production_entry_app/doctype/shift/test_shift.py
git commit -m "test: cover shift edge branches"
```

---

### Task 6: Cover Stock Entry Hook Edge Branches

**Files:**

- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_override.py`
- Test: relevant override module

- [ ] **Step 1: Add tests for remaining hook guards**

Use existing Stock Entry fixture helpers where possible. Cover:

- Non-manufacture stock entry no-op paths
- Missing shift no-op path
- Rejection row restoration edge path
- Die-tool disabled item no-op path
- Cache invalidation on cancel for linked shift

- [ ] **Step 2: Run override tests**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_override
```

Expected: pass. Target impact: reduce `stock_entry_hooks.py` misses from `27` to under `8`.

- [ ] **Step 3: Commit**

```bash
git add production_entry_app/production_entry_app/overrides/test_stock_entry_override.py
git commit -m "test: cover stock entry hook edge cases"
```

---

### Task 7: Cover Remaining Report Branches

**Files:**

- Modify: `production_entry_app/production_entry_app/report/test_reports.py`
- Test: `production_entry_app.production_entry_app.test_reports`

- [ ] **Step 1: Add branch tests for report modules**

Focus on the remaining small misses in:

- `daily_strokes_spm_monitor.py`
- `item_bom_rejection_hotspots.py`
- `item_bom_rework_hotspots.py`
- `operator_rejection_performance.py`
- `operator_rework_performance.py`
- `production_oee_report.py`
- `rejection_pareto_report.py`
- `rejection_trend_report.py`
- `rework_pareto_report.py`
- `rework_ppm_report.py`
- `rework_trend_report.py`
- `workstation_rejection_reason_matrix.py`
- `workstation_rework_reason_matrix.py`

Prefer pure-function or mocked report utility tests over large fixture-heavy integration tests unless the branch depends on real Frappe query behavior.

- [ ] **Step 2: Run report tests**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_reports
```

Expected: pass. Target impact: reduce report module misses by at least `45` lines.

- [ ] **Step 3: Commit**

```bash
git add production_entry_app/production_entry_app/report/test_reports.py
git commit -m "test: cover report branch edge cases"
```

---

### Task 8: Verify Unit And Integration Coverage Above 96

**Files:** none unless failures require fixes.

- [ ] **Step 1: Run full bench coverage on v16**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app --coverage
coverage report --data-file sites/.coverage --rcfile /Users/gurudattkulkarni/Workspace/production-entry-app/.coveragerc -m
```

Expected:

- Tests pass with `0` failures/errors
- Coverage report total is `>= 96.00%`

- [ ] **Step 2: Run full bench tests on v15**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site frappe15.localhost run-tests --app production_entry_app
```

Expected: tests pass with `0` failures/errors.

- [ ] **Step 3: Commit any compatibility fixes**

```bash
git add <changed files>
git commit -m "test: maintain coverage gate compatibility"
```

---

### Task 9: Verify E2E Gate

**Files:**

- Modify or add Playwright specs only if an existing user-facing flow is untested.

- [ ] **Step 1: Run smoke E2E against local bench**

Use the existing repository script if bench/server state matches CI:

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
BENCH_ROOT=/Users/gurudattkulkarni/Workspace/bench16 scripts/run_ephemeral_e2e.sh smoke
```

Expected: Playwright smoke passes.

- [ ] **Step 2: Run full E2E regression if smoke is clean**

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
BENCH_ROOT=/Users/gurudattkulkarni/Workspace/bench16 scripts/run_ephemeral_e2e.sh ci
```

Expected: Playwright full suite passes.

- [ ] **Step 3: Optional future improvement**

If strict E2E line coverage is required, add a dedicated instrumented Frappe server startup that runs under coverage and combines `.coverage.*` files after Playwright completes. This is more accurate but higher complexity than the current pass/fail E2E gate.

---

### Task 10: Final Quality Gate, Commit, Push

**Files:** all changed files.

- [ ] **Step 1: Run pre-commit**

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
pre-commit run --all-files
```

Expected: all hooks pass.

- [ ] **Step 2: Run final coverage command again**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app --coverage
coverage report --data-file sites/.coverage --rcfile /Users/gurudattkulkarni/Workspace/production-entry-app/.coveragerc -m
```

Expected: total coverage `>= 96.00%`.

- [ ] **Step 3: Stage and commit final changes**

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
git status --short
git add <changed files>
git commit -m "test: raise coverage above 96 percent"
```

- [ ] **Step 4: Push**

```bash
git push
```
