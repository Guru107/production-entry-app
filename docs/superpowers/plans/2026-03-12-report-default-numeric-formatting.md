# Report Default Numeric Formatting Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove report-owned numeric rounding overrides so app reports use Frappe's default numeric formatting.

**Architecture:** Keep the change narrow and explicit. Audit report column metadata for app-defined numeric `precision` overrides, remove only the overrides that force rounded rendering, and verify through report tests that schemas and numeric outputs remain intact.

**Tech Stack:** Frappe Script Reports, Python 3.11, ERPNext/Frappe test runner

---

## File Map

- Modify: `production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py`
  - Removes explicit `precision: 0` on percent columns so Frappe defaults render them.
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`
  - Adds regression coverage that the OEE report column metadata no longer forces rounded precision.
- Reference: `docs/superpowers/specs/2026-03-12-report-default-numeric-formatting-design.md`
  - Source design for scope and trade-offs.

## Chunk 1: Remove Report-Owned Rounding Overrides

### Task 1: Add a failing regression test for report column metadata

**Files:**
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] **Step 1: Write the failing test**

Add a test near the existing OEE report schema tests that loads `get_columns()` from `production_oee_report` and asserts the percent fields no longer define `precision`.

```python
def test_production_oee_report_percent_columns_use_frappe_defaults(self) -> None:
	from production_entry_app.production_entry_app.report.production_oee_report.production_oee_report import (
		get_columns,
	)

	percent_fieldnames = {
		"productivity_pct",
		"quality_pct",
		"availability_pct",
		"oee",
		"oee_mult_pct",
	}
	columns = {column["fieldname"]: column for column in get_columns()}
	for fieldname in percent_fieldnames:
		self.assertEqual(columns[fieldname]["fieldtype"], "Percent")
		self.assertNotIn("precision", columns[fieldname])
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.report.test_reports \
  --test TestReportOutputs.test_production_oee_report_percent_columns_use_frappe_defaults
```

Expected: FAIL because the OEE percent columns still define `precision: 0`.

- [ ] **Step 3: Write the minimal implementation**

Edit `production_oee_report.py` and remove the `precision: 0` key from:

- `productivity_pct`
- `quality_pct`
- `availability_pct`
- `oee`
- `oee_mult_pct`

Keep:

- `fieldtype: "Percent"`
- existing `fieldname`
- existing labels
- existing widths

Do not change:

- row calculations
- returned numeric values
- any non-report logic

- [ ] **Step 4: Run the focused test to verify it passes**

Run the same command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py \
        production_entry_app/production_entry_app/report/test_reports.py
git commit -m "Use Frappe defaults for OEE report precision"
```

## Chunk 2: Verify Report Behavior Stays Stable

### Task 2: Run existing report regression coverage

**Files:**
- Verify: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] **Step 1: Run the OEE schema and metrics coverage**

Run:

```bash
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.report.test_reports
```

Expected: PASS, including the existing OEE schema and metric tests.

- [ ] **Step 2: Sanity-check no other report-owned precision overrides remain**

Run:

```bash
rg -n '"precision"\\s*:' production_entry_app/production_entry_app/report -g '*.py'
```

Expected:

- no remaining hits in report column definitions, or
- only intentionally retained non-report metadata if any are discovered and explicitly reviewed

- [ ] **Step 3: Run lint if the test module or report file formatting changed**

Run:

```bash
pre-commit run --files \
  production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py \
  production_entry_app/production_entry_app/report/test_reports.py
```

Expected: PASS.

- [ ] **Step 4: Commit any lint fallout**

```bash
git add production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py \
        production_entry_app/production_entry_app/report/test_reports.py
git commit -m "Polish report default-formatting cleanup"
```

## Execution Notes

- Keep the scope narrow. The approved design is to trust Frappe defaults, not to add `precision: 2` everywhere.
- Do not stringify report values.
- Do not round calculations before returning rows.
- If the `rg` audit finds more explicit `precision` overrides in report modules than currently known, stop and confirm whether they should also be removed in the same pass or handled in a follow-up spec.
