# AI-SLOP High/Critical Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove or explicitly justify every high/critical AI-SLOP finding without changing application behavior.

**Architecture:** This is a behavior-preserving extraction refactor. Keep public APIs, report contracts, query semantics, validation order, mutation order, and returned payloads unchanged while moving complex branches into focused local helpers. Work proceeds in independently verifiable batches, each with characterization-before-refactor, targeted tests, AI-SLOP scan, pre-commit, and a dedicated commit.

**Tech Stack:** Frappe/ERPNext app, Python 3.10+, Frappe query builder, JavaScript client tests, bench15 (`development.localhost`), bench16 (`frappe16.localhost`), AI-SLOP detector, pre-commit, ruff, eslint, prettier.

---

## Source Documents

- Spec: `docs/superpowers/specs/2026-04-28-ai-slop-high-critical-cleanup-design.md`
- Detector report: `reports/ai-slop-report.json`
- Detector command: `scripts/check_ai_slop.sh`

## Global Rules

- Do not change application behavior.
- Do not change public function names, whitelisted API names, report `execute()` signatures, report columns, report row schemas, chart payloads, precision behavior, query filters, query aliases, query grouping, query ordering, Stock Entry validation order, or Stock Entry mutation order.
- Prefer local helper extraction over new shared abstractions.
- Add characterization tests before production refactors when branch coverage is missing.
- Commit each task independently.
- If a high/critical finding cannot be safely removed, stop and request reviewer/user approval before final completion. Record approved retained/skipped findings in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`.

## Files Expected To Change

- `production_entry_app/production_entry_app/api.py`: E2E cleanup and fixture helper extraction.
- `production_entry_app/production_entry_app/test_api.py`: characterization for API/E2E helper behavior if gaps exist.
- `production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py`: OEE grouping and availability helper extraction.
- `production_entry_app/production_entry_app/report/test_reports.py`: characterization for OEE/report behavior if gaps exist.
- `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`: Stock Entry validation and mutation helper extraction.
- `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`: characterization for hook order/error/mutation behavior if gaps exist.
- `scripts/print_ai_slop_file_findings.js`: small detector-report inspection utility if missing.
- `production_entry_app/production_entry_app/report/*/*.py`: report `_get_rows` helper extraction by report family.
- `production_entry_app/production_entry_app/doctype/shift/shift.py`: Shift summary and planned-loss helper extraction.
- `production_entry_app/production_entry_app/doctype/shift/test_shift.py`: characterization for Shift summary/planned-loss behavior if gaps exist.
- `production_entry_app/production_entry_app/api_timeline.py`: timeline response helper extraction.
- `production_entry_app/production_entry_app/test_api_timeline.py`: characterization for timeline response behavior if gaps exist.
- `production_entry_app/production_entry_app/report/report_benchmark.py`: benchmark loop helper extraction.
- `production_entry_app/production_entry_app/report/test_report_benchmark.py`: benchmark characterization if gaps exist.
- `production_entry_app/production_entry_app/write_benchmark.py`: write benchmark case helper extraction.
- `production_entry_app/production_entry_app/test_write_benchmark.py`: write benchmark characterization if gaps exist.
- `production_entry_app/production_entry_app/report/report_utils.py`: quantity/stroke helper extraction.
- `production_entry_app/production_entry_app/utils/loss_time.py`: loss interval helper extraction.
- `production_entry_app/production_entry_app/utils/test_loss_time.py`: loss-time characterization if gaps exist.
- `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`: retained/skipped finding notes and approval evidence if any finding cannot be safely removed.

## Shared Verification Commands

Run these from `/Users/gurudattkulkarni/Workspace/production-entry-app` unless a command starts with `cd`:

```bash
scripts/check_ai_slop.sh
pre-commit run --all-files
```

Expected for both commands: exit code `0`.

---

### Task 0: Baseline And Utility Setup

**Files:**
- Create: `scripts/print_ai_slop_file_findings.js` only if missing
- Modify: none otherwise
- Test: manual JSON parse check

- [ ] **Step 1: Confirm clean worktree**

Run:

```bash
git status --short --branch
```

Expected: branch `feature/alternative-item-selection-manufacturing-entry`; no uncommitted application changes except plan docs if still uncommitted.

- [ ] **Step 2: Regenerate the detector report**

Run:

```bash
mkdir -p reports
uvx --from 'ai-slop-detector[js]==3.6.0' slop-detector --project . --config .slopconfig.yaml --js --json --no-history > reports/ai-slop-report.json || true
```

Expected: `reports/ai-slop-report.json` exists. The command may append JS summary text after JSON; parsing must trim from `\n[JS/TS Analysis]` when present.

- [ ] **Step 3: Create the file-finding inspection utility if missing**

If `scripts/print_ai_slop_file_findings.js` does not exist, create it with this behavior:

```javascript
#!/usr/bin/env node
const fs = require("fs");
const target = process.argv[2];
if (!target) {
	console.error("Usage: node scripts/print_ai_slop_file_findings.js <path-fragment>");
	process.exit(2);
}
const raw = fs.readFileSync("reports/ai-slop-report.json", "utf8");
const end = raw.lastIndexOf("\n[JS/TS Analysis]");
const report = JSON.parse((end >= 0 ? raw.slice(0, end) : raw).trim());
const files = [...(report.file_results || []), ...(report.js_file_results || [])];
const match = files.find((file) => String(file.file_path || file.file || "").includes(target));
if (!match) {
	console.log(JSON.stringify({ found: false, target }, null, 2));
	process.exit(0);
}
console.log(JSON.stringify(match, null, 2));
```

- [ ] **Step 4: Verify lifecycle gate utility**

Run:

```bash
node scripts/print_ai_slop_file_findings.js production_entry_app/production_entry_app/lifecycle.py
```

Expected: JSON for `lifecycle.py` or `{ "found": false, ... }`; no parse error.

- [ ] **Step 5: Commit utility if created**

Run only if `scripts/print_ai_slop_file_findings.js` was created:

```bash
git add scripts/print_ai_slop_file_findings.js
git commit -m "chore: add ai slop report file inspector"
```

Expected: one utility-only commit.

---

### Task 1: Refactor `api.py` High/Critical Findings

**Files:**
- Modify: `production_entry_app/production_entry_app/api.py`
- Test: `production_entry_app/production_entry_app/test_api.py`

Targets:
- `_cleanup_e2e_context`
- `_apply_direct_manufacture_alternative_flags`
- `create_e2e_full_shift_stock_entries`

- [ ] **Step 1: Inspect current tests for API helper behavior**

Run:

```bash
rg -n "cleanup_e2e|bootstrap_e2e|create_e2e_full_shift|alternative" production_entry_app/production_entry_app/test_api.py tests/e2e -g '*.*'
```

Expected: identify existing coverage for cleanup payloads, bootstrap payloads, and alternative item flags.

- [ ] **Step 2: Add characterization tests before refactor if coverage is missing**

Add tests in `production_entry_app/production_entry_app/test_api.py` only for uncovered behavior. Required assertions for touched paths:

```python
# Keep exact expected keys based on current implementation.
assert set(result).issuperset({"shift", "stock_entries"})
assert result["shift"]
assert isinstance(result["stock_entries"], list)
```

For cleanup paths, assert current result keys/count semantics and that repeated cleanup remains safe.

- [ ] **Step 3: Run API tests before production changes**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected: pass before production refactor. If it fails before editing, stop and record the unrelated baseline failure.

- [ ] **Step 4: Extract `_apply_direct_manufacture_alternative_flags` helpers**

In `api.py`, extract local helpers without changing mutation order:

```python
def _get_direct_manufacture_alternative_item_rows(doc: Document) -> list:
	return [row for row in doc.get("items", []) if row.get("allow_alternative_item")]


def _apply_direct_manufacture_alternative_flag(row) -> None:
	row.is_alternative = 1
```

Then rewrite `_apply_direct_manufacture_alternative_flags` to call helpers while preserving current conditions and row order.

- [ ] **Step 5: Extract `_cleanup_e2e_context` stages**

Use local helpers with explicit inputs/outputs. Suggested helper names:

```python
def _get_e2e_cleanup_targets(prefix: str) -> dict[str, object]: ...
def _cleanup_e2e_stock_entries(targets: dict[str, object], result: dict[str, object]) -> None: ...
def _cleanup_e2e_shifts(prefix: str, result: dict[str, object]) -> None: ...
def _cleanup_e2e_master_data(prefix: str, result: dict[str, object]) -> None: ...
def _finalize_e2e_cleanup(prefix: str, result: dict[str, object]) -> dict[str, object]: ...
```

Do not change exception swallowing, delete/cancel order, result key names, or cache/settings restore order.

- [ ] **Step 6: Extract `create_e2e_full_shift_stock_entries` only where sequence stays identical**

Allowed helpers:

```python
def _build_e2e_full_shift_entry_payloads(ctx: dict) -> list[dict]: ...
def _insert_e2e_full_shift_stock_entry(payload: dict) -> str: ...
```

Do not change fixture creation sequence, names, returned payload keys, or cache invalidation timing.

- [ ] **Step 7: Run API tests after refactor on bench15 and bench16**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected: both pass.

- [ ] **Step 8: Run detector and pre-commit**

Run:

```bash
scripts/check_ai_slop.sh
pre-commit run --all-files
```

Expected: both pass; the targeted `api.py` high/critical findings are gone. If any target remains, stop for approval and document it in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`.

- [ ] **Step 9: Commit API refactor**

Run:

```bash
git status --short
git add production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/test_api.py
git commit -m "refactor: simplify e2e api cleanup helpers"
```

Expected: commit only API/test changes.

---

### Task 2: Refactor `production_oee_report.py`

**Files:**
- Modify: `production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py`
- Test: `production_entry_app/production_entry_app/report/test_reports.py`

Targets:
- `_get_stock_entry_groups`
- `_get_availability_hours_by_group`
- `_apply_loss_buckets_for_chunk`

- [ ] **Step 1: Identify OEE tests that must remain green**

Run:

```bash
rg -n "production_oee_report" production_entry_app/production_entry_app/report/test_reports.py
```

Expected: identify tests covering schema, metrics, aggregation, shift split, cross-midnight loss, unmapped losses, linked-shift availability, and raw runtime values.

- [ ] **Step 2: Run OEE/report tests before refactor**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
```

Expected: pass before production refactor.

- [ ] **Step 3: Add characterization tests only for uncovered OEE behavior**

If existing tests do not prove selected fields/aliases/filter effects for the touched query path, add assertions to existing OEE tests. Use output characterization, not internal implementation coupling. Assert representative row keys, row order, group key behavior, availability hours, loss buckets, and chart payload if touched.

- [ ] **Step 4: Record query preservation proof path**

Choose one proof path before editing:

```text
Proof path: output characterization through existing OEE tests covering selected fields, aliases, filters, grouping, ordering, and precision.
```

If practical, also capture query-builder SQL locally in implementation notes. Do not add test-only production hooks.

- [ ] **Step 5: Extract stock-entry query and row normalization helpers**

Suggested helpers:

```python
def _get_stock_entry_group_rows(filters: dict) -> list[dict]: ...
def _get_stock_entry_group_key(row: dict) -> tuple[str, str]: ...
def _update_stock_entry_group(group: dict, row: dict) -> None: ...
def _finalize_stock_entry_groups(groups: dict[tuple[str, str], dict]) -> list[dict]: ...
```

Move code without changing selected fields, aliases, filters, grouping, sorting, standard SPM selection, or numeric calculations.

- [ ] **Step 6: Extract availability helpers**

Suggested helpers:

```python
def _get_group_linked_shift_names(group: dict) -> set[str]: ...
def _get_shift_availability_hours(shift_row: dict) -> float: ...
def _apply_shift_availability_to_groups(groups: dict, shift_row: dict) -> None: ...
```

Preserve linked-shift scoping and planned-loss deduction behavior.

- [ ] **Step 7: Extract loss bucket helpers**

Suggested helpers:

```python
def _get_loss_chunk_overlap_minutes(chunk_start, chunk_end, loss_start, loss_end) -> float: ...
def _add_loss_bucket_minutes(group: dict, loss_reason: str, minutes: float) -> None: ...
```

Preserve cross-midnight clipping and unmapped loss behavior.

- [ ] **Step 8: Run report tests on bench15 and bench16**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
```

Expected: both pass.

- [ ] **Step 9: Run detector and pre-commit**

Run:

```bash
scripts/check_ai_slop.sh
pre-commit run --all-files
```

Expected: both pass; the targeted OEE high/critical findings are gone. If any target remains, stop for approval and document it in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`.

- [ ] **Step 10: Commit OEE refactor**

Run:

```bash
git add production_entry_app/production_entry_app/report/production_oee_report/production_oee_report.py production_entry_app/production_entry_app/report/test_reports.py
git commit -m "refactor: simplify production oee report aggregation"
```

Expected: commit only OEE/report-test changes.

---

### Task 3: Refactor `stock_entry_hooks.py`

**Files:**
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Test: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`

Targets:
- `_validate_actual_times`
- `_validate_unplanned_losses_within_actual_window`
- `_validate_direct_manufacture_alternative_items`
- `_validate_rejection_breakup`
- `_apply_rejection_entries`
- `_get_deducted_loss_minutes_for_entry`

- [ ] **Step 1: Identify Stock Entry hook coverage**

Run:

```bash
rg -n "actual|unplanned|alternative|rejection|deducted|planned_loss" production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
```

Expected: identify tests for each target function.

- [ ] **Step 2: Run hook tests before refactor**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

Expected: pass before production refactor.

- [ ] **Step 3: Add characterization tests for missing hook behavior**

If missing, add tests that assert:

```python
# Error message/order contract
with pytest.raises(frappe.ValidationError, match="expected current message"):
	validate_stock_entry(doc)

# Mutation contract
before_items = [row.as_dict() for row in doc.items]
_apply_rejection_entries(doc)
after_items = [row.as_dict() for row in doc.items]
assert [row["item_code"] for row in after_items] == expected_item_order
```

Use the existing test framework style; if tests use `FrappeTestCase`, follow that style instead of raw `pytest.raises`.

- [ ] **Step 4: Extract actual-time validation helpers**

Suggested helpers:

```python
def _get_actual_time_values(doc) -> tuple[datetime.datetime | None, datetime.datetime | None]: ...
def _throw_invalid_actual_time(message: str) -> None: ...
```

Preserve validation order and messages.

- [ ] **Step 5: Extract unplanned-loss window helpers**

Suggested helpers:

```python
def _iter_unplanned_loss_rows(doc: Document): ...
def _validate_unplanned_loss_row_within_window(row, actual_start, actual_end) -> None: ...
```

Preserve row iteration order and first error raised.

- [ ] **Step 6: Extract alternative-item validation helpers**

Suggested helpers:

```python
def _get_direct_manufacture_source_rows(doc: Document) -> list: ...
def _validate_alternative_item_row(row, original_item: str) -> None: ...
```

Preserve configured alternative lookup behavior.

- [ ] **Step 7: Extract rejection quantity and mutation helpers**

Suggested helpers:

```python
def _get_rejection_breakup_totals(doc) -> dict[str, float]: ...
def _validate_rejection_total_matches_doc(doc, totals: dict[str, float]) -> None: ...
def _build_rejection_stock_item_rows(doc, fg_row, rejection_warehouse: str) -> list[dict]: ...
def _append_rejection_stock_item_rows(doc, rows: list[dict]) -> None: ...
```

Do not change removal-before-append behavior or target warehouse resolution.

- [ ] **Step 8: Extract deducted planned-loss helpers**

Suggested helpers:

```python
def _get_entry_actual_window(doc) -> tuple[datetime.datetime | None, datetime.datetime | None]: ...
def _get_planned_loss_overlap_minutes(entry_start, entry_end, loss_row) -> float: ...
```

Preserve time clipping and summation behavior.

- [ ] **Step 9: Run hook tests on bench15 and bench16**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

Expected: both pass.

- [ ] **Step 10: Run JS unit tests, detector, and pre-commit**

Run:

```bash
npm run test:unit:js
scripts/check_ai_slop.sh
pre-commit run --all-files
```

Expected: all pass; the targeted `stock_entry_hooks.py` high findings are gone. If any target remains, stop for approval and document it in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`.

- [ ] **Step 11: Commit hook refactor**

Run:

```bash
git add production_entry_app/production_entry_app/overrides/stock_entry_hooks.py production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "refactor: simplify stock entry hook validations"
```

Expected: commit only hook/test changes.

---

### Task 4: Lifecycle Detector Gate

**Files:**
- Modify: none unless high/critical finding is confirmed
- Test: `production_entry_app/production_entry_app/test_lifecycle.py` only if code changes

- [ ] **Step 1: Run project-level detector report**

Run:

```bash
mkdir -p reports
uvx --from 'ai-slop-detector[js]==3.6.0' slop-detector --project . --config .slopconfig.yaml --js --json --no-history > reports/ai-slop-report.json || true
node scripts/print_ai_slop_file_findings.js production_entry_app/production_entry_app/lifecycle.py
```

Expected: output for `lifecycle.py`.

- [ ] **Step 2: Decide based on output**

If no high/critical finding exists, skip code changes and record in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`:

```text
lifecycle.py skipped: detector marks file suspicious due low logic density only; no high/critical finding in current report.
```

If high/critical finding exists, add a local extraction subplan before editing.

- [ ] **Step 3: If lifecycle code changed, run tests**

Run only if code changed:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_lifecycle
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_lifecycle
scripts/check_ai_slop.sh
pre-commit run --all-files
```

Expected: all pass.

- [ ] **Step 4: Commit only if code or utility changed**

Run only if files changed:

```bash
git add production_entry_app/production_entry_app/lifecycle.py production_entry_app/production_entry_app/test_lifecycle.py scripts/print_ai_slop_file_findings.js
git commit -m "refactor: simplify lifecycle quality findings"
```

Expected: no commit if lifecycle was skipped and utility was already committed.

---

### Report-Family Task Gate Template

Every report-family task from Task 5 through Task 11 must include these blocking gates before production refactor:

- [ ] **Gate A: Confirm direct tests for every touched report branch**

Use `rg` and the existing `test_reports.py` cases to map each touched `_get_rows` branch to a test. If a branch is not directly covered, add or update a characterization test before editing production code.

- [ ] **Gate B: Run characterization before production changes**

Run bench15 report tests before touching production code. Expected: pass. If tests fail before edits, stop and record the baseline failure.

- [ ] **Gate C: Record query proof path before production changes**

For every query-heavy function touched in the task, record one proof path in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md` or the task commit body:

```text
Query proof for <file>::<function>: output characterization covers selected fields, aliases, filters, grouping, ordering, and precision via <test names>.
```

If output characterization is insufficient, add SQL/query-builder selected-field assertions or a local SQL snapshot comparison before refactoring.

- [ ] **Gate D: Target detector closure**

After refactor, the task's target high/critical findings must be gone. If any target remains, stop, document attempted safe extraction and behavior risk in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`, and get reviewer/user approval before proceeding.

---

### Task 5: Refactor Pareto And PPM Reports

**Files:**
- Modify: `production_entry_app/production_entry_app/report/rejection_pareto_report/rejection_pareto_report.py`
- Modify: `production_entry_app/production_entry_app/report/rework_pareto_report/rework_pareto_report.py`
- Modify: `production_entry_app/production_entry_app/report/rejection_ppm_report/rejection_ppm_report.py`
- Modify: `production_entry_app/production_entry_app/report/rework_ppm_report/rework_ppm_report.py`
- Test: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] **Step 1: Locate report tests**

Run:

```bash
rg -n "pareto|ppm" production_entry_app/production_entry_app/report/test_reports.py
```

Expected: tests exist for rejection/rework pareto and ppm reports.

- [ ] **Step 2: Run report tests before refactor**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
```

Expected: pass.

- [ ] **Step 3: Complete report-family gates before production changes**

Complete Gate A, Gate B, and Gate C from the Report-Family Task Gate Template for the Pareto/PPM reports. Add characterization tests first if any touched branch lacks direct coverage.

- [ ] **Step 4: Extract local helpers in each report**

Use local helper names matching each module's behavior:

```python
def _aggregate_reason_rows(rows: list[dict]) -> dict[str, dict]: ...
def _finalize_pareto_rows(aggregates: dict[str, dict]) -> list[dict]: ...
def _get_parent_quantity_for_ppm(row: dict) -> float: ...
def _build_ppm_row(row: dict) -> dict: ...
```

Preserve filters, sorting, cumulative percentages, ppm calculations, chart payloads, and empty result behavior.

- [ ] **Step 6: Run report tests on bench15 and bench16**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
```

Expected: both pass.

- [ ] **Step 7: Run detector and pre-commit**

Run:

```bash
scripts/check_ai_slop.sh
pre-commit run --all-files
```

Expected: both pass.

- [ ] **Step 7: Commit report batch**

Run:

```bash
git add production_entry_app/production_entry_app/report/rejection_pareto_report/rejection_pareto_report.py production_entry_app/production_entry_app/report/rework_pareto_report/rework_pareto_report.py production_entry_app/production_entry_app/report/rejection_ppm_report/rejection_ppm_report.py production_entry_app/production_entry_app/report/rework_ppm_report/rework_ppm_report.py production_entry_app/production_entry_app/report/test_reports.py
git commit -m "refactor: simplify pareto and ppm reports"
```

Expected: one report-family commit.

---

### Task 6: Refactor Trend Reports

**Files:**
- Modify: `production_entry_app/production_entry_app/report/rejection_trend_report/rejection_trend_report.py`
- Modify: `production_entry_app/production_entry_app/report/rework_trend_report/rework_trend_report.py`
- Test: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] **Step 1: Locate trend tests**

Run:

```bash
rg -n "trend_report|weekly|monthly|daily_aggregation" production_entry_app/production_entry_app/report/test_reports.py
```

Expected: tests exist for daily, weekly, and monthly trend behavior.

- [ ] **Step 2: Run report tests before refactor**

Run bench15 report tests. Expected: pass.

- [ ] **Step 3: Complete report-family gates before production changes**

Complete Gate A, Gate B, and Gate C from the Report-Family Task Gate Template for trend reports. Add characterization tests first if any touched branch lacks direct coverage.

- [ ] **Step 4: Extract period aggregation helpers**

Suggested helpers per module:

```python
def _aggregate_period_rows(rows: list[dict], time_grain: str) -> dict[tuple, dict]: ...
def _finalize_trend_rows(aggregates: dict[tuple, dict]) -> list[dict]: ...
```

Preserve period keys, sorting, chart labels, and rejection/rework quantity split.

- [ ] **Step 6: Run report tests on bench15 and bench16**

Run same commands as Task 5 Step 4. Expected: both pass.

- [ ] **Step 7: Run detector and pre-commit**

Run shared verification commands. Expected: pass.

- [ ] **Step 7: Commit trend report batch**

Run:

```bash
git add production_entry_app/production_entry_app/report/rejection_trend_report/rejection_trend_report.py production_entry_app/production_entry_app/report/rework_trend_report/rework_trend_report.py production_entry_app/production_entry_app/report/test_reports.py
git commit -m "refactor: simplify trend reports"
```

Expected: one trend-report commit.

---

### Task 7: Refactor Matrix Reports

**Files:**
- Modify: `production_entry_app/production_entry_app/report/workstation_rejection_reason_matrix/workstation_rejection_reason_matrix.py`
- Modify: `production_entry_app/production_entry_app/report/workstation_rework_reason_matrix/workstation_rework_reason_matrix.py`
- Test: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] **Step 1: Locate matrix tests**

Run:

```bash
rg -n "reason_matrix|top_reasons|unassigned" production_entry_app/production_entry_app/report/test_reports.py
```

Expected: tests cover top reasons, filters, and unassigned fallback.

- [ ] **Step 2: Run report tests before refactor**

Run bench15 report tests. Expected: pass.

- [ ] **Step 3: Complete report-family gates before production changes**

Complete Gate A, Gate B, and Gate C from the Report-Family Task Gate Template for matrix reports. Add characterization tests first if any touched branch lacks direct coverage.

- [ ] **Step 4: Extract top-reason helpers**

Suggested helpers:

```python
def _collect_reason_totals(rows: list[dict]) -> dict[str, float]: ...
def _select_top_reasons(reason_totals: dict[str, float], top_n: int) -> list[str]: ...
def _build_matrix_rows(rows: list[dict], reason_order: list[str]) -> list[dict]: ...
```

Preserve sanitized field names, top-N order, filters, and unassigned labels.

- [ ] **Step 5: Run report tests on bench15 and bench16**

Run same commands as Task 5 Step 4. Expected: both pass.

- [ ] **Step 6: Run detector and pre-commit**

Run shared verification commands. Expected: pass.

- [ ] **Step 7: Commit matrix report batch**

Run:

```bash
git add production_entry_app/production_entry_app/report/workstation_rejection_reason_matrix/workstation_rejection_reason_matrix.py production_entry_app/production_entry_app/report/workstation_rework_reason_matrix/workstation_rework_reason_matrix.py production_entry_app/production_entry_app/report/test_reports.py
git commit -m "refactor: simplify reason matrix reports"
```

Expected: one matrix-report commit.

---

### Task 8: Refactor Item/BOM Hotspot Reports

**Files:**
- Modify: `production_entry_app/production_entry_app/report/item_bom_rejection_hotspots/item_bom_rejection_hotspots.py`
- Modify: `production_entry_app/production_entry_app/report/item_bom_rework_hotspots/item_bom_rework_hotspots.py`
- Test: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] **Step 1: Locate hotspot tests**

Run:

```bash
rg -n "item_bom_.*hotspots|hotspots" production_entry_app/production_entry_app/report/test_reports.py
```

Expected: tests cover aggregation, sorting, and item filters.

- [ ] **Step 2: Run report tests before refactor**

Run bench15 report tests. Expected: pass.

- [ ] **Step 3: Complete report-family gates before production changes**

Complete Gate A, Gate B, and Gate C from the Report-Family Task Gate Template for item/BOM hotspot reports. Add characterization tests first if any touched branch lacks direct coverage.

- [ ] **Step 4: Extract item/BOM aggregation helpers**

Suggested helpers:

```python
def _aggregate_item_bom_rows(rows: list[dict]) -> dict[tuple[str, str], dict]: ...
def _update_item_bom_aggregate(aggregate: dict, row: dict) -> None: ...
def _finalize_item_bom_rows(aggregates: dict[tuple[str, str], dict]) -> list[dict]: ...
```

Preserve group keys, sorting, filters, and quantity/rate calculations.

- [ ] **Step 5: Run report tests on bench15 and bench16**

Run same commands as Task 5 Step 4. Expected: both pass.

- [ ] **Step 6: Run detector and pre-commit**

Run shared verification commands. Expected: pass.

- [ ] **Step 7: Commit hotspot report batch**

Run:

```bash
git add production_entry_app/production_entry_app/report/item_bom_rejection_hotspots/item_bom_rejection_hotspots.py production_entry_app/production_entry_app/report/item_bom_rework_hotspots/item_bom_rework_hotspots.py production_entry_app/production_entry_app/report/test_reports.py
git commit -m "refactor: simplify item bom hotspot reports"
```

Expected: one hotspot-report commit.

---

### Task 9: Refactor Operator Performance Reports

**Files:**
- Modify: `production_entry_app/production_entry_app/report/operator_rejection_performance/operator_rejection_performance.py`
- Modify: `production_entry_app/production_entry_app/report/operator_rework_performance/operator_rework_performance.py`
- Test: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] **Step 1: Locate operator performance tests**

Run:

```bash
rg -n "operator_(rejection|rework)_performance" production_entry_app/production_entry_app/report/test_reports.py
```

Expected: tests cover metrics, rate preservation, string summaries, and filters.

- [ ] **Step 2: Run report tests before refactor**

Run bench15 report tests. Expected: pass.

- [ ] **Step 3: Complete report-family gates before production changes**

Complete Gate A, Gate B, and Gate C from the Report-Family Task Gate Template for operator performance reports. Add characterization tests first if any touched branch lacks direct coverage.

- [ ] **Step 4: Extract operator aggregation helpers**

Suggested helpers:

```python
def _aggregate_operator_rows(rows: list[dict]) -> dict[str, dict]: ...
def _update_operator_aggregate(aggregate: dict, row: dict) -> None: ...
def _finalize_operator_performance_rows(aggregates: dict[str, dict]) -> list[dict]: ...
```

Preserve raw rates, string summary contract, filters, and sorting.

- [ ] **Step 5: Run report tests on bench15 and bench16**

Run same commands as Task 5 Step 4. Expected: both pass.

- [ ] **Step 6: Run detector and pre-commit**

Run shared verification commands. Expected: pass.

- [ ] **Step 7: Commit operator performance batch**

Run:

```bash
git add production_entry_app/production_entry_app/report/operator_rejection_performance/operator_rejection_performance.py production_entry_app/production_entry_app/report/operator_rework_performance/operator_rework_performance.py production_entry_app/production_entry_app/report/test_reports.py
git commit -m "refactor: simplify operator performance reports"
```

Expected: one operator-performance commit.

---

### Task 10: Refactor Efficiency Reports And Shared Report Utils

**Files:**
- Modify: `production_entry_app/production_entry_app/report/workstation_efficiency_report/workstation_efficiency_report.py`
- Modify: `production_entry_app/production_entry_app/report/operator_efficiency_report/operator_efficiency_report.py`
- Modify: `production_entry_app/production_entry_app/report/report_utils.py`
- Test: `production_entry_app/production_entry_app/report/test_reports.py`
- Test: `production_entry_app/production_entry_app/report/test_report_utils_performance.py`

- [ ] **Step 1: Locate efficiency and utility tests**

Run:

```bash
rg -n "efficiency|parent_quantity|get_entry_total_strokes|report_utils" production_entry_app/production_entry_app/report/test_reports.py production_entry_app/production_entry_app/report/test_report_utils_performance.py
```

Expected: tests cover efficiency grouping, raw duration, standard SPM, rejection/rework split, and stroke totals.

- [ ] **Step 2: Run tests before refactor**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_report_utils_performance
```

Expected: pass before production refactor.

- [ ] **Step 3: Complete report-family gates before production changes**

Complete Gate A, Gate B, and Gate C from the Report-Family Task Gate Template for efficiency reports and shared report utilities. Add characterization tests first if any touched branch lacks direct coverage.

- [ ] **Step 4: Extract report utility helpers**

Suggested helpers:

```python
def _get_parent_quantity_source(entry: dict) -> dict[str, float]: ...
def _split_rejection_and_rework_quantities(entry: dict) -> tuple[float, float]: ...
def _get_item_row_strokes(row: dict) -> float: ...
def _get_entry_stroke_fallback(entry: dict) -> float: ...
```

Preserve zero handling, fallback order, and raw numeric values.

- [ ] **Step 5: Extract efficiency aggregation helpers**

Suggested helpers:

```python
def _aggregate_efficiency_rows(rows: list[dict], group_field: str) -> dict[str, dict]: ...
def _finalize_efficiency_rows(aggregates: dict[str, dict]) -> list[dict]: ...
```

Preserve grouping, setup/loss subtraction, standard SPM selection, and unassigned behavior.

- [ ] **Step 5: Run report tests on bench15 and bench16**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_report_utils_performance
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_report_utils_performance
```

Expected: all pass.

- [ ] **Step 6: Run detector and pre-commit**

Run shared verification commands. Expected: pass.

- [ ] **Step 8: Commit efficiency/report utils batch**

Run:

```bash
git add production_entry_app/production_entry_app/report/workstation_efficiency_report/workstation_efficiency_report.py production_entry_app/production_entry_app/report/operator_efficiency_report/operator_efficiency_report.py production_entry_app/production_entry_app/report/report_utils.py production_entry_app/production_entry_app/report/test_reports.py production_entry_app/production_entry_app/report/test_report_utils_performance.py
git commit -m "refactor: simplify efficiency report helpers"
```

Expected: one efficiency/utils commit.

---

### Task 11: Refactor Daily SPM Reports

**Files:**
- Modify: `production_entry_app/production_entry_app/report/daily_strokes_spm_monitor/daily_strokes_spm_monitor.py`
- Modify: `production_entry_app/production_entry_app/report/operator_daily_spm_report/operator_daily_spm_report.py`
- Test: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] **Step 1: Locate daily SPM tests**

Run:

```bash
rg -n "daily_strokes_spm|operator_daily_spm|fiscal_year|totals_row" production_entry_app/production_entry_app/report/test_reports.py
```

Expected: tests cover columns, data, raw group values, totals, empty results, and fiscal-year ranges.

- [ ] **Step 2: Run report tests before refactor**

Run bench15 report tests. Expected: pass.

- [ ] **Step 3: Complete report-family gates before production changes**

Complete Gate A, Gate B, and Gate C from the Report-Family Task Gate Template for daily SPM reports. Add characterization tests first if any touched branch lacks direct coverage.

- [ ] **Step 4: Extract fiscal-year date range helpers**

Suggested helpers:

```python
def _get_fiscal_year_bounds(fiscal_year: str) -> tuple[datetime.date, datetime.date]: ...
def _resolve_daily_report_date_range(filters: dict) -> tuple[datetime.date, datetime.date]: ...
```

Preserve validation errors and cross-year support.

- [ ] **Step 5: Extract daily row aggregation helpers**

Suggested helpers:

```python
def _aggregate_daily_spm_rows(rows: list[dict]) -> dict[tuple, dict]: ...
def _build_daily_spm_totals_row(rows: list[dict]) -> dict | None: ...
def _finalize_daily_spm_rows(aggregates: dict[tuple, dict]) -> list[dict]: ...
```

Preserve totals row, raw values, grouping, and sorting.

- [ ] **Step 5: Run report tests on bench15 and bench16**

Run same commands as Task 5 Step 4. Expected: both pass.

- [ ] **Step 6: Run detector and pre-commit**

Run shared verification commands. Expected: pass.

- [ ] **Step 8: Commit daily SPM batch**

Run:

```bash
git add production_entry_app/production_entry_app/report/daily_strokes_spm_monitor/daily_strokes_spm_monitor.py production_entry_app/production_entry_app/report/operator_daily_spm_report/operator_daily_spm_report.py production_entry_app/production_entry_app/report/test_reports.py
git commit -m "refactor: simplify daily spm reports"
```

Expected: one daily-SPM commit.

---

### Task 12: Refactor Shift Summary Findings

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Test: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`

Targets:
- `_build_workstation_summary_rows`
- `get_shift_summary`
- `get_shift_aggregate_production_entries`
- `_planned_losses_changed`
- `_populate_planned_losses`

- [ ] **Step 1: Locate Shift tests**

Run:

```bash
rg -n "summary|aggregate|planned_losses|populate|field_locking" production_entry_app/production_entry_app/doctype/shift/test_shift.py
```

Expected: identify tests for summary payloads, aggregate entries, planned losses, and shift-duration behavior.

- [ ] **Step 2: Run Shift tests before refactor**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
```

Expected: pass before refactor. If known unrelated permission failures appear, stop and document baseline before editing.

- [ ] **Step 3: Add characterization tests if summary/planned-loss branches are missing**

Required coverage if missing:

```python
summary = get_shift_summary(shift.name)
assert set(summary).issuperset({"production_entries", "workstations", "item_boms"})
assert isinstance(summary["production_entries"], list)
```

For planned losses, assert same child-row values before and after duration-driven population.

- [ ] **Step 4: Extract workstation summary helpers**

Suggested helpers:

```python
def _accumulate_workstation_summary(entries: list[dict]) -> dict[str, dict]: ...
def _finalize_workstation_summary_rows(workstations: dict[str, dict]) -> list[dict]: ...
def _get_workstation_extreme_rows(rows: list[dict]) -> dict | None: ...
```

Preserve ranking, percentages, and fallback labels.

- [ ] **Step 5: Extract shift summary sections**

Suggested helpers:

```python
def _get_shift_summary_base(shift_name: str) -> tuple[dict, datetime.datetime, datetime.datetime]: ...
def _get_shift_summary_production_section(shift_name: str) -> dict: ...
def _get_shift_summary_loss_section(shift_name: str) -> dict: ...
def _assemble_shift_summary(sections: dict[str, object]) -> dict: ...
```

Preserve cache behavior, precision conversion, and returned keys.

- [ ] **Step 6: Extract planned-loss helpers**

Suggested helpers:

```python
def _get_comparable_planned_loss_rows(rows) -> list[tuple]: ...
def _get_planned_loss_templates_for_duration(duration_hours: int) -> list[tuple[str, int, int]]: ...
def _append_planned_loss_rows(self, templates: list[tuple[str, int, int]]) -> None: ...
```

Preserve child row content, order, and duration behavior.

- [ ] **Step 7: Run Shift tests on bench15 and bench16**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
```

Expected: both pass or only documented unrelated baseline failures remain.

- [ ] **Step 8: Run detector and pre-commit**

Run shared verification commands. Expected: pass; the targeted `shift.py` high findings are gone. If any target remains, stop for approval and document it in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`.

- [ ] **Step 9: Commit Shift refactor**

Run:

```bash
git add production_entry_app/production_entry_app/doctype/shift/shift.py production_entry_app/production_entry_app/doctype/shift/test_shift.py
git commit -m "refactor: simplify shift summary helpers"
```

Expected: one Shift commit.

---

### Task 13: Refactor Timeline API

**Files:**
- Modify: `production_entry_app/production_entry_app/api_timeline.py`
- Test: `production_entry_app/production_entry_app/test_api_timeline.py`

- [ ] **Step 1: Locate timeline tests**

Run:

```bash
rg -n "timeline|get_shift_timeline_data|interval|loss" production_entry_app/production_entry_app/test_api_timeline.py tests/e2e
```

Expected: identify response-shape and interval behavior tests.

- [ ] **Step 2: Run timeline tests before refactor**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline
```

Expected: pass.

- [ ] **Step 3: Add characterization tests before refactor if timeline coverage is missing**

If response-shape, interval sorting, label, timestamp, or loss/downtime branches lack direct tests, add characterization assertions in `production_entry_app/production_entry_app/test_api_timeline.py` before editing `api_timeline.py`. Rerun the bench15 timeline test command and expect pass before production changes.

- [ ] **Step 4: Extract timeline helpers**

Suggested helpers:

```python
def _load_timeline_source_data(shift_name: str) -> dict[str, object]: ...
def _build_timeline_intervals(source: dict[str, object]) -> list[dict]: ...
def _build_timeline_response(source: dict[str, object], intervals: list[dict]) -> dict: ...
```

Preserve response keys, interval sorting, labels, and timestamps.

- [ ] **Step 5: Run timeline tests on bench15 and bench16**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline
```

Expected: both pass.

- [ ] **Step 6: Run detector and pre-commit**

Run shared verification commands. Expected: pass; the targeted `api_timeline.py` high findings are gone. If any target remains, stop for approval and document it in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`.

- [ ] **Step 7: Commit timeline refactor**

Run:

```bash
git add production_entry_app/production_entry_app/api_timeline.py production_entry_app/production_entry_app/test_api_timeline.py
git commit -m "refactor: simplify shift timeline api"
```

Expected: one timeline commit.

---

### Task 14: Refactor Benchmark Helpers

**Files:**
- Modify: `production_entry_app/production_entry_app/report/report_benchmark.py`
- Modify: `production_entry_app/production_entry_app/write_benchmark.py`
- Test: `production_entry_app/production_entry_app/report/test_report_benchmark.py`
- Test: `production_entry_app/production_entry_app/test_write_benchmark.py`

- [ ] **Step 1: Run benchmark tests before refactor**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_report_benchmark
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_write_benchmark
```

Expected: pass.

- [ ] **Step 2: Add characterization tests before refactor if benchmark coverage is missing**

If benchmark output keys, retry behavior, exception handling, or timing result shape lacks direct tests, add characterization tests in `production_entry_app/production_entry_app/report/test_report_benchmark.py` or `production_entry_app/production_entry_app/test_write_benchmark.py` before editing production benchmark code. Rerun the bench15 benchmark test commands and expect pass before production changes.

- [ ] **Step 3: Extract report benchmark loop helpers**

Suggested helpers:

```python
def _iter_benchmark_report_cases() -> list[tuple[str, callable]]: ...
def _time_report_execution(report_name: str, execute_fn, date_range: dict[str, str]) -> dict[str, float | int]: ...
def _record_benchmark_result(results: dict, report_name: str, metrics: dict) -> None: ...
```

Preserve benchmark result keys and timing behavior.

- [ ] **Step 4: Extract write benchmark case helpers**

Suggested helpers:

```python
def _execute_write_case_attempt(case: dict) -> dict[str, object]: ...
def _record_write_case_timing(result: dict[str, object], started_at: float) -> dict[str, object]: ...
```

Preserve retry/exception behavior and output keys.

- [ ] **Step 5: Run benchmark tests**

Run same commands as Step 1. Expected: pass.

- [ ] **Step 6: Run detector and pre-commit**

Run shared verification commands. Expected: pass; the targeted benchmark high/critical findings are gone. If any target remains, stop for approval and document it in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`.

- [ ] **Step 7: Commit benchmark refactor**

Run:

```bash
git add production_entry_app/production_entry_app/report/report_benchmark.py production_entry_app/production_entry_app/write_benchmark.py production_entry_app/production_entry_app/report/test_report_benchmark.py production_entry_app/production_entry_app/test_write_benchmark.py
git commit -m "refactor: simplify benchmark helpers"
```

Expected: one benchmark commit.

---

### Task 15: Refactor Loss-Time Utility

**Files:**
- Modify: `production_entry_app/production_entry_app/utils/loss_time.py`
- Test: `production_entry_app/production_entry_app/utils/test_loss_time.py`

- [ ] **Step 1: Run loss-time tests before refactor**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_loss_time
```

Expected: pass.

- [ ] **Step 2: Add edge-case characterization if missing**

Ensure tests cover empty inputs, boundary timestamps, cross-midnight windows, no overlap, full overlap, and invalid intervals.

- [ ] **Step 3: Extract interval helpers**

Suggested helpers:

```python
def _normalize_interval_start_end(start, end) -> tuple[datetime.datetime, datetime.datetime]: ...
def _clip_interval_to_window(start, end, window_start, window_end) -> tuple[datetime.datetime, datetime.datetime] | None: ...
def _get_interval_duration_minutes(start, end) -> float: ...
```

Preserve returned values, `None` behavior, and boundary handling.

- [ ] **Step 4: Run loss-time tests on bench15 and bench16**

Run:

```bash
cd /Users/gurudattkulkarni/Workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_loss_time
cd /Users/gurudattkulkarni/Workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_loss_time
```

Expected: both pass.

- [ ] **Step 5: Run detector and pre-commit**

Run shared verification commands. Expected: pass; the targeted `utils/loss_time.py` high finding is gone. If the target remains, stop for approval and document it in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`.

- [ ] **Step 6: Commit loss-time refactor**

Run:

```bash
git add production_entry_app/production_entry_app/utils/loss_time.py production_entry_app/production_entry_app/utils/test_loss_time.py
git commit -m "refactor: simplify loss time interval handling"
```

Expected: one utility commit.

---

### Task 16: Final Detector Closure And PR Update

**Files:**
- Modify: `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md` only if findings are retained/skipped

- [ ] **Step 1: Run final AI-SLOP scan with JSON report**

Run:

```bash
scripts/check_ai_slop.sh
mkdir -p reports
uvx --from 'ai-slop-detector[js]==3.6.0' slop-detector --project . --config .slopconfig.yaml --js --json --no-history > reports/ai-slop-report.json || true
```

Expected: detector passes in soft mode; target high/critical findings are gone. Any retained high/critical finding has approval and is documented in `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md`.

- [ ] **Step 2: Parse final finding summary**

Run:

```bash
node - <<'NODE'
const fs = require('fs');
const raw = fs.readFileSync('reports/ai-slop-report.json', 'utf8');
const end = raw.lastIndexOf('\n[JS/TS Analysis]');
const report = JSON.parse((end >= 0 ? raw.slice(0, end) : raw).trim());
const files = [...(report.file_results || []), ...(report.js_file_results || [])];
console.log(JSON.stringify({
	total_files: report.total_files,
	deficit_files: report.deficit_files,
	clean_files: report.clean_files,
	avg_deficit_score: Number(report.avg_deficit_score).toFixed(2),
	weighted_deficit_score: Number(report.weighted_deficit_score).toFixed(2),
	overall_status: report.overall_status,
}, null, 2));
for (const file of files.filter((f) => (f.deficit_score || 0) > 0)) {
	const issues = [...(file.pattern_issues || []), ...(file.warnings || [])]
		.filter((issue) => ["critical", "high"].includes(String(issue.severity || issue.level || "").toLowerCase()));
	if (!issues.length) continue;
	console.log(`\n${file.status}\t${Number(file.deficit_score).toFixed(1)}\t${String(file.file_path || file.file).replace(process.cwd() + "/", "")}`);
	for (const issue of issues) console.log(`  - ${issue.severity || issue.level}: ${issue.message || issue.description || String(issue)}`);
}
NODE
```

Expected: final high/critical list is empty or approved retained findings are known.

- [ ] **Step 3: Run final full pre-commit**

Run:

```bash
pre-commit run --all-files
```

Expected: pass.

- [ ] **Step 4: Commit retained/skipped finding notes if present**

Run only if `docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md` exists or changed:

```bash
git add docs/superpowers/notes/2026-04-28-ai-slop-retained-findings.md
git commit -m "docs: record ai slop retained findings"
```

Expected: notes are committed separately from implementation changes.

- [ ] **Step 5: Check final worktree**

Run:

```bash
git status --short --branch
```

Expected: clean worktree after final commit, branch ahead of origin if not yet pushed.

- [ ] **Step 6: Push branch**

Run:

```bash
git push
```

Expected: branch pushed to GitHub.

