# Shift Duration Extension Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `Running` Shifts to revise `shift_duration`, regenerate planned losses including fixed `JH Activity`, and immediately recalculate all user-visible duration-derived metrics and report denominators.

**Architecture:** Keep Shift as the single source of truth for duration-driven scheduling. Recompute dependent fields and cached payloads on Shift save, keep submitted Stock Entry facts immutable, and verify report/API consumers read the updated Shift definition rather than stale copied values.

**Tech Stack:** Frappe/ERPNext v15/v16, Python, JavaScript, Playwright, bench test runner, pre-commit

---

## File Map

- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`
  - Running-shift lock relaxation, planned-loss generation rules, cache invalidation, overlap-safe duration recalculation
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.js`
  - keep duration editable during `Running`, refresh duration-derived UI after save
- Modify: `production_entry_app/production_entry_app/api_timeline.py`
  - ensure timeline payloads respond correctly to revised Shift windows
- Modify: `production_entry_app/production_entry_app/api.py`
  - keep Stock Entry form hydration endpoints aligned with updated Shift end details
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
  - verify draft/new Stock Entries use revised Shift defaults without rewriting submitted docs
- Modify: `production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py`
  - no formula redesign expected, but keep availability tied to current Shift duration/planned losses
- Modify: `production_entry_app/production_entry_app/report/operator_daily_spm_report/operator_daily_spm_report.py`
  - no formula redesign expected, but keep working hours tied to current Shift duration
- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`
  - core TDD coverage for duration change, fixed `JH Activity`, overnight edge cases, overlap rejection
- Modify: `production_entry_app/production_entry_app/test_api_timeline.py`
  - timeline end-boundary regression coverage
- Modify: `production_entry_app/production_entry_app/test_api.py`
  - Stock Entry API payload coverage for revised Shift details
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`
  - OEE and operator-daily denominator regression coverage
- Modify: `tests/e2e/specs/shift-to-stock-entry.spec.js`
  - end-to-end Shift page extension flow and visible recalculation checks

## Chunk 1: Shift Domain Rules

### Task 1: Add failing tests for Running-shift duration revision

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`

- [ ] **Step 1: Write failing tests for allowed Running-shift duration edits**

Add tests covering:

```python
def test_running_shift_allows_shift_duration_change_and_recomputes_end_fields(self) -> None:
	...

def test_running_shift_duration_change_regenerates_planned_losses(self) -> None:
	...

def test_jh_activity_is_fixed_at_10am_when_window_includes_it(self) -> None:
	...

def test_overnight_shift_does_not_generate_jh_activity_when_10am_is_outside_window(self) -> None:
	...

def test_running_shift_extension_rejects_overlap_with_another_shift(self) -> None:
	...
```

Also update existing planned-loss regression tests in the same module that currently assert the old relative `JH Activity` timing, including the auto-populate and repopulate cases, so they now expect the fixed `10:00:00-10:10:00` window when it overlaps the Shift.

- [ ] **Step 2: Run the targeted Shift test module to confirm failure**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
```

Expected:
- new tests fail because `Running` shifts are still effectively locked for duration edits or planned-loss rules still treat `JH Activity` relatively

- [ ] **Step 3: Implement the minimal Shift-domain changes**

Modify `production_entry_app/production_entry_app/doctype/shift/shift.py` to:

- allow `shift_duration`-driven recalculation on `Running` shifts while keeping other fields locked
- regenerate `planned_end_time`, `shift_end_date`, and `planned_losses` on duration change
- move `JH Activity` to fixed absolute scheduling at `10:00:00-10:10:00`
- ensure fixed losses are only created when they overlap the active Shift window
- keep overlap validation on the recomputed end boundary
- update existing planned-loss test fixtures and assertions that still encode relative `JH Activity`

- [ ] **Step 4: Run the targeted Shift tests again**

Run the same command from Step 2.

Expected:
- targeted Shift tests pass

- [ ] **Step 5: Commit the Shift-domain slice**

```bash
git add production_entry_app/production_entry_app/doctype/shift/shift.py production_entry_app/production_entry_app/doctype/shift/test_shift.py
git commit -m "feat: support running shift duration updates"
```

## Chunk 2: API and Stock Entry Integration

### Task 2: Lock API regressions before changing integration paths

**Files:**
- Modify: `production_entry_app/production_entry_app/test_api.py`
- Modify: `production_entry_app/production_entry_app/test_api_timeline.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/api.py`
- Modify: `production_entry_app/production_entry_app/api_timeline.py`
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`

- [ ] **Step 1: Add failing API tests**

Add tests for:

```python
def test_get_shift_details_for_stock_entry_returns_updated_planned_end_for_running_shift(self) -> None:
	...

def test_timeline_payload_uses_updated_shift_end_after_duration_change(self) -> None:
	...

def test_timeline_cache_is_invalidated_when_running_shift_duration_changes(self) -> None:
	...
```

Also add required hook-level regression tests in `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py` ensuring:

- draft/new Stock Entries rehydrate updated planned end from the linked Shift on validate/save
- submitted Stock Entries are not rewritten by the Shift duration change path

- [ ] **Step 2: Run the focused API test modules to confirm failure**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

Expected:
- new API assertions fail because cached or copied Shift-window details still reflect the old duration

- [ ] **Step 3: Implement minimal API and integration updates**

Update:

- `production_entry_app/production_entry_app/api.py`
  - ensure Stock Entry hydration endpoints read current Shift end fields after a duration change
- `production_entry_app/production_entry_app/api_timeline.py`
  - ensure timeline payload uses the updated Shift window and cache invalidation path
- `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
  - confirm draft/new Stock Entries use updated Shift defaults without rewriting submitted docs
- `production_entry_app/production_entry_app/doctype/shift/shift.py`
  - invalidate timeline cache on Shift duration updates so running timeline payloads do not stay stale

- [ ] **Step 4: Run focused API tests again**

Run the same commands from Step 2.

Expected:
- API and integration tests pass

- [ ] **Step 5: Commit the API/integration slice**

```bash
git add production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/api_timeline.py production_entry_app/production_entry_app/doctype/shift/shift.py production_entry_app/production_entry_app/overrides/stock_entry_hooks.py production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py production_entry_app/production_entry_app/test_api.py production_entry_app/production_entry_app/test_api_timeline.py
git commit -m "fix: refresh shift api windows after duration changes"
```

## Chunk 3: Report Denominators

### Task 3: Add report regressions for duration-derived metrics

**Files:**
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`
- Verify/modify: `production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py`
- Verify/modify: `production_entry_app/production_entry_app/report/operator_daily_spm_report/operator_daily_spm_report.py`

- [ ] **Step 1: Add failing report tests**

Add tests for:

```python
def test_production_oee_report_availability_changes_after_running_shift_extension(self) -> None:
	...

def test_operator_daily_spm_report_working_hours_change_after_running_shift_extension(self) -> None:
	...
```

Use one case where extending the Shift adds fixed planned-loss coverage so the denominator shift is explicit.

- [ ] **Step 2: Run the focused report test module to confirm failure**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
```

Expected:
- new report assertions fail until the revised Shift definition is reflected consistently in report calculations or setup fixtures

- [ ] **Step 3: Apply minimal report code changes if tests prove they are needed**

Keep this slice narrow:

- prefer fixture/setup/test changes first if reports already read live Shift data
- only change report code if a real stale-duration assumption is exposed

- [ ] **Step 4: Re-run the report test module**

Run the same command from Step 2.

Expected:
- report tests pass

- [ ] **Step 5: Commit the report slice**

```bash
git add production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py production_entry_app/production_entry_app/report/operator_daily_spm_report/operator_daily_spm_report.py production_entry_app/production_entry_app/report/test_reports.py
git commit -m "test: cover shift duration report recalculation"
```

## Chunk 4: Shift Page and End-to-End Flow

### Task 4: Add browser-level regression coverage before UI changes

**Files:**
- Modify: `tests/e2e/specs/shift-to-stock-entry.spec.js`
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.js`

- [ ] **Step 1: Add a failing E2E test**

Add a scenario covering:

- create and start a Shift
- change `shift_duration` while the Shift is `Running`
- save
- verify planned end time updates
- verify visible Shift summary metrics refresh
- verify Stock Entry creation path sees the revised planned end

- [ ] **Step 2: Run the focused E2E spec to confirm failure**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
npx playwright test tests/e2e/specs/shift-to-stock-entry.spec.js
```

Expected:
- the new flow fails because the Running Shift UI still prevents or mishandles duration changes

- [ ] **Step 3: Implement the minimal UI changes**

Update `production_entry_app/production_entry_app/doctype/shift/shift.js` to:

- keep `shift_duration` editable while `Running`
- keep `planned_losses` read-only
- refresh summary and aggregate sections after save/reload so the user sees recalculated metrics immediately

- [ ] **Step 4: Run the focused E2E spec again**

Run the same command from Step 2.

Expected:
- the focused E2E spec passes

- [ ] **Step 5: Commit the UI/E2E slice**

```bash
git add production_entry_app/production_entry_app/doctype/shift/shift.js tests/e2e/specs/shift-to-stock-entry.spec.js
git commit -m "feat: refresh shift ui after duration extension"
```

## Chunk 5: Full Verification and Finish

### Task 5: Run the complete verification set

**Files:**
- Verify all modified files from Chunks 1-4

- [ ] **Step 1: Run targeted v15 Python modules**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
```

Expected:
- all targeted v15 test modules pass

- [ ] **Step 2: Run representative v16 coverage**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift --lightmode
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api --lightmode
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline --lightmode
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks --lightmode
bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports --lightmode
```

Expected:
- representative v16 coverage passes, or any pre-existing environment blocker is documented with exact output

- [ ] **Step 3: Build assets and run E2E**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench build --app production_entry_app
cd /Users/gurudattkulkarni/Workspace/production-entry-app
npx playwright test tests/e2e/specs/shift-to-stock-entry.spec.js
```

Expected:
- assets build successfully
- focused Shift E2E coverage passes

- [ ] **Step 4: Run lint/format checks**

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
pre-commit run --all-files
```

Expected:
- hooks pass or only produce fixable issues that are then resolved

- [ ] **Step 5: Create the final implementation commit if needed**

```bash
git status --short
git commit -m "feat: support shift duration extension"
```

Only do this if the work from earlier chunks is not already fully committed in clean slices. If files remain, add the exact remaining modified files shown by `git status --short` before creating this wrap-up commit.
