# Shift Department Display Name Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Shift names use the linked Department's `department_name` instead of the Department docname, while keeping all bootstrap, cleanup, and test helpers aligned.

**Architecture:** Add one shared helper in `shift.py` that resolves the Department naming source with fallback-to-docname behavior, and keep the existing sanitization logic as the single sanitization path. Update `Shift.autoname()` and all helper code that predicts Shift names to call those shared helpers instead of reconstructing naming rules inline.

**Tech Stack:** Python 3.11, Frappe/ERPNext DocTypes, FrappeTestCase, bench test runner

---

## Chunk 1: Shared Naming Helpers

### Task 1: Add failing unit coverage for Department display-name resolution

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`
- Modify: `production_entry_app/production_entry_app/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:

```python
def test_department_display_name_used_in_shift_name(self) -> None:
	department = ensure_department("Test Department")
	frappe.db.set_value("Department", department, "department_name", "Press Shop", update_modified=False)
	doc = frappe.get_doc(
		{
			"doctype": "Shift",
			"department": department,
			"shift_label": "1",
			"shift_duration": "8",
			"shift_date": "2026-05-20",
		}
	).insert()
	assert doc.name == "SHIFT-Press-Shop-2026-05-20.1"
```

```python
def test_bootstrap_e2e_context_uses_department_display_name_for_shift_name(self) -> None:
	# Mock ensure_department() -> "E2E Department - TC"
	# Mock Department.department_name -> "E2E Department"
	# Assert _get_or_create_e2e_shift receives SHIFT-E2E-Department-2099-01-20.1
```

- [ ] **Step 2: Run targeted tests to verify they fail**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected:
- New assertions fail because current code still derives names from Department docname

- [ ] **Step 3: Commit the red test state only if explicitly requested**

Do not commit failing tests unless the human explicitly asks for that workflow.

### Task 2: Implement one shared Department naming-source helper

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`

- [ ] **Step 1: Add a shared helper that resolves the naming source**

Implement a helper with this shape:

```python
def _resolve_department_name_for_shift_naming(department: str) -> str:
	if not department:
		frappe.throw(_("Department is required."))
	department_name = frappe.db.get_value("Department", department, "department_name")
	if department_name and str(department_name).strip():
		return str(department_name).strip()
	return department
```

Rules:
- `department` is the linked Department docname
- Use `department_name` when it is non-blank
- Fall back to the linked docname for `None`, empty string, or whitespace-only values
- Keep logic small and explicit

- [ ] **Step 2: Reuse the existing sanitization helper**

Do not add a second sanitization function. Keep `_sanitize_department_for_name(...)` as the single sanitization path.

- [ ] **Step 3: Update `Shift.autoname()` to use the new helper**

Implement:

```python
def autoname(self) -> None:
	if not self.department or not self.shift_date or not self.shift_label:
		return
	department_label = _resolve_department_name_for_shift_naming(self.department)
	sanitized = _sanitize_department_for_name(department_label)
	self.name = f"SHIFT-{sanitized}-{self.shift_date}.{self.shift_label}"
```

- [ ] **Step 4: Run the targeted Shift test module**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
```

Expected:
- The new Shift naming test passes
- No existing Shift test regresses

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/doctype/shift/shift.py production_entry_app/production_entry_app/doctype/shift/test_shift.py
git commit -m "Use department display name for shift naming"
```

## Chunk 2: Align API and Test Helpers

### Task 3: Route API helper naming through the same shared logic

**Files:**
- Modify: `production_entry_app/production_entry_app/api.py`
- Modify: `production_entry_app/production_entry_app/test_api.py`

- [ ] **Step 1: Write or tighten the failing API regression test**

Ensure the API test asserts that `_get_or_create_e2e_shift(...)` receives a Shift name derived from Department `department_name`, not from the Department docname.

- [ ] **Step 2: Update helper code to call shared naming logic**

Refactor `_build_e2e_shift_name(...)` to call the shared helper(s) from `shift.py` instead of duplicating naming decisions inline.

Target shape:

```python
from production_entry_app.production_entry_app.doctype.shift.shift import (
	_resolve_department_name_for_shift_naming,
	_sanitize_department_for_name,
)

def _build_e2e_shift_name(*, department: str, shift_date: str, shift_label: str) -> str:
	department_label = _resolve_department_name_for_shift_naming(department)
	sanitized_dept = _sanitize_department_for_name(department_label)
	return f"SHIFT-{sanitized_dept}-{shift_date}.{shift_label}"
```

- [ ] **Step 3: Keep cleanup precedence explicit**

Do not broaden cleanup logic. Preserve:
- actual created Shift name is primary when available
- predicted-name cleanup remains fallback / best-effort only

- [ ] **Step 4: Run targeted API tests**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected:
- New API regression test passes
- Existing API tests stay green

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/test_api.py
git commit -m "Align e2e shift naming with department display name"
```

### Task 4: Align remaining test helpers that predict Shift names

**Files:**
- Modify: `production_entry_app/production_entry_app/test_api_timeline.py`
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`
- Modify: `production_entry_app/production_entry_app/report/report_benchmark.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`

- [ ] **Step 1: Replace inline name derivation with shared helper calls**

Anywhere a test currently does this:

```python
sanitized = _sanitize_department_for_name(department)
name = f"SHIFT-{sanitized}-{shift_date}.{shift_label}"
```

replace it with a shared helper path, for example:

```python
from production_entry_app.production_entry_app.doctype.shift.shift import (
	_resolve_department_name_for_shift_naming,
	_sanitize_department_for_name,
)

department_label = _resolve_department_name_for_shift_naming(department)
sanitized = _sanitize_department_for_name(department_label)
name = f"SHIFT-{sanitized}-{shift_date}.{shift_label}"
```

If the same pattern appears repeatedly inside one test file, extract a small local helper in that test file rather than repeating imports and string construction.

Also update the runtime benchmark helper in `report/report_benchmark.py` so benchmark-created Shift names follow the same shared Department display-name rule instead of deriving from Department docname inline.

- [ ] **Step 2: Run the affected modules**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
```

Expected:
- All updated helpers use the same naming rule
- No regressions in Shift-linked tests

- [ ] **Step 3: Commit**

```bash
git add production_entry_app/production_entry_app/test_api_timeline.py production_entry_app/production_entry_app/report/test_reports.py production_entry_app/production_entry_app/report/report_benchmark.py production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py production_entry_app/production_entry_app/doctype/shift/test_shift.py
git commit -m "Reuse shared shift naming helpers in tests"
```

## Chunk 3: Final Verification

### Task 5: Run focused verification and repository checks

**Files:**
- Modify: `production_entry_app/production_entry_app/utils/test_test_bootstrap.py` only if needed for fallout
- Modify: `tests/e2e/specs/shift-to-stock-entry.spec.js` if the existing browser flow exposes the created Shift name

- [ ] **Step 1: Run the directly affected bootstrap test module**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_test_bootstrap
```

Expected:
- Company-aware Department lookup coverage still passes

- [ ] **Step 2: Evaluate whether an E2E assertion is required**

- Decision:
- Treat this as a user-facing naming change unless proven otherwise
- Check the existing Playwright flow first
- If `shift-to-stock-entry.spec.js` or another existing Shift flow can observe the created Shift name, add a failing assertion there first and keep it in the final change
- If no existing browser-visible flow exposes the created Shift name, record that limitation in the implementation summary, but still run the full Playwright suite per repo policy

- [ ] **Step 3: Run the relevant E2E check when applicable**

If Step 2 found an existing observable browser flow, run the focused spec first:

```bash
npx playwright test tests/e2e/specs/shift-to-stock-entry.spec.js
```

Expected:
- The existing flow still passes
- Any new Shift-name assertion proves the UI-observable path uses the display-name-based Shift name

- [ ] **Step 4: Run the full E2E suite**

Run:

```bash
npx playwright test
```

Expected:
- All Playwright specs pass after the naming change

- [ ] **Step 5: Run formatting/lint checks**

Run:

```bash
pre-commit run --all-files
```

Expected:
- All hooks pass

- [ ] **Step 6: Review working tree**

Run:

```bash
git status --short
git diff --stat
```

Expected:
- Only intended files changed

- [ ] **Step 7: Final commit if there are uncommitted verification fallout fixes**

```bash
git add <relevant files>
git commit -m "Polish shift display-name naming verification"
```
