# Frappe Framework Compliance Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the branch with Frappe/ERPNext framework rules and repo conventions by removing migrate-time metadata churn, standardizing permission APIs, fixing DocType metadata, and making client/API behavior explicit and test-covered.

**Architecture:** Treat DocType, Report, Custom Field, and fixture metadata as source-controlled state, not runtime state that `migrate` rewrites. Keep runtime setup strict and idempotent, with no legacy fallbacks because this app is under development. Implement fixes in small TDD chunks so behavior changes, metadata changes, and client-side fixes can be reviewed and reverted independently.

**Tech Stack:** Frappe v15/v16, ERPNext v15/v16, Python 3.10+, JavaScript, Playwright, Node test runner, bench, pre-commit.

---

## Source Spec

- Spec source: branch-wide Frappe framework deviation audit from this conversation.
- Repo rules: `CLAUDE.md`.
- Project guidance: `AGENTS.md`, including CodeGraph-first structural exploration.
- Current branch: `feature/roll-out-plan`.

## CodeGraph Availability

Use the repo-local CodeGraph MCP tools documented in `AGENTS.md` when `.codegraph/` exists. If those tools are unavailable, run `codegraph init -i` from `$APP_ROOT` or use the fallback `rg`/`git` commands listed in the affected task.

## Scope

In scope:

- Stop `bench migrate` from regenerating Production Entry report JSON files.
- Remove runtime Report metadata sync and direct DB fallback writes.
- Normalize Frappe permission hook signatures for v15/v16 compatibility.
- Fix Shift status transition audit comments to include the acting user.
- Align DocType and Custom Field metadata with repo conventions.
- Make client-side `frappe.call()` failures visible to users.
- Document or simplify ERPNext prototype monkey patches.
- Remove legacy/development fallback APIs that conflict with the "app under development" rule.
- Verify with targeted tests, migrate checks, JS unit tests, E2E smoke/regression coverage, and pre-commit.

Out of scope:

- Product workflow redesign unless a test exposes a broken user-facing flow.
- Data migrations or backwards compatibility for prior app states.
- Broad CI workflow optimization unless it directly blocks this refactor.

## Global Rules

- Before each chunk, run `git status --short --branch` and do not overwrite unrelated unstaged work.
- Do not stage or revert existing source changes unless they are part of the current chunk.
- Ask the user before destructive actions such as `git checkout --`, `git restore`, `rm`, or resetting report JSON files to another branch.
- Use CodeGraph for structural lookups when `.codegraph/` and `codegraph_*` tools are available; otherwise use the listed `rg`/`git` fallback commands.
- Write or update failing tests before implementation changes.
- Keep Python and JavaScript indentation consistent with repo rules: tabs in code, not spaces.
- Keep commits small. Each chunk has its own commit step.
- Do not add compatibility/fallback handling for old Production Entry states.

## Bench Variables

Use these shell variables in command snippets when executing the plan:

```bash
APP_ROOT=${APP_ROOT:-$(git rev-parse --show-toplevel)}
WORKSPACE_ROOT=${WORKSPACE_ROOT:-$(dirname "$APP_ROOT")}
BENCH16=${BENCH16:-$WORKSPACE_ROOT/bench16}
BENCH15=${BENCH15:-$WORKSPACE_ROOT/bench15}
SITE16=${SITE16:-frappe16.localhost}
SITE15=${SITE15:-development.localhost}
```

If a local site name differs, set `SITE16` or `SITE15` explicitly before running commands.

## Files Expected To Change

- `production_entry_app/production_entry_app/access_control.py`: remove runtime Report metadata mutation and legacy fallback behavior.
- `production_entry_app/production_entry_app/lifecycle.py`: keep `after_migrate` setup call, but rely on idempotent setup only.
- `production_entry_app/production_entry_app/test_access_control.py`: update strict/idempotent access-control tests.
- `production_entry_app/production_entry_app/report/test_reports.py`: add report JSON churn regression checks if missing.
- `production_entry_app/production_entry_app/report/*/*.json`: clean only intentional report metadata changes.
- `production_entry_app/production_entry_app/doctype/operator/operator.py`: normalize `has_permission` signature.
- `production_entry_app/production_entry_app/doctype/die_tool_counter/die_tool_counter.py`: normalize `has_permission` signature.
- `production_entry_app/production_entry_app/doctype/die_tool_maintenance_log/die_tool_maintenance_log.py`: normalize `has_permission` signature.
- `production_entry_app/production_entry_app/doctype/rejection_reason/rejection_reason.py`: normalize `has_permission` signature.
- `production_entry_app/production_entry_app/doctype/loss_entry/loss_entry.py`: verify or normalize `has_permission` signature.
- `production_entry_app/production_entry_app/doctype/rejection_breakup/rejection_breakup.py`: verify or normalize `has_permission` signature.
- `production_entry_app/production_entry_app/doctype/shift/shift.py`: fix status transition audit comment.
- `production_entry_app/production_entry_app/doctype/shift/test_shift.py`: add/adjust status audit tests.
- `production_entry_app/production_entry_app/test_permission_hooks.py`: create if no focused permission hook test module exists.
- `production_entry_app/production_entry_app/test_doctype_metadata.py`: create metadata convention tests.
- `production_entry_app/production_entry_app/doctype/operator/operator.json`: set master-data metadata.
- `production_entry_app/production_entry_app/doctype/downtime_reason/downtime_reason.json`: set master-data metadata.
- `production_entry_app/production_entry_app/doctype/shift/shift.json`: add missing `search_index` metadata where justified.
- `production_entry_app/fixtures/custom_field.json`: add missing custom-field index metadata where justified.
- `production_entry_app/production_entry_app/fixtures/custom_field.json`: keep in sync if this copy exists.
- `production_entry_app/production_entry_app/performance_indexes.py`: update index rationale only if a composite index replaces field-level `search_index`.
- `public/js/access_control.js`: make API failure visible and explicit.
- `public/js/stock_entry.js`: document ERPNext prototype dependency and keep original fallback explicit.
- `public/js/custom_field_visibility.js`: avoid global DocField mutation if tests confirm leakage.
- `tests/unit/access-control.test.js`: create focused JS unit tests for access-control fetch errors.
- `tests/unit/stock-entry-visibility.test.js`: update monkey-patch coverage if needed.
- `tests/unit/custom-field-visibility.test.js`: update per-form/per-row visibility leakage coverage.
- `production_entry_app/production_entry_app/api.py`: remove legacy E2E API parameters and optionally move E2E implementation to a focused module.
- `production_entry_app/production_entry_app/test_api.py`: remove legacy fallback tests and add strict dev-only API tests.
- `tests/e2e/fixtures/*.js`: update E2E helper calls if API parameters change.
- `tests/e2e/specs/access-control-role-branch.spec.js`: keep user-facing access-control coverage passing.

## Shared Verification Commands

Run from `$APP_ROOT` unless the command changes directory:

```bash
git status --short --branch
git diff --check
npm run test:unit:js
pre-commit run --all-files
```

Expected: exit code `0`.

---

## Chunk 1: Stop Migrate-Time Report Metadata Churn

### Task 1.1: Add regression tests for access-control setup not saving reports during migrate

**Files:**
- Modify: `production_entry_app/production_entry_app/test_access_control.py`
- Modify: `production_entry_app/production_entry_app/report/test_reports.py`

- [ ] **Step 1: Inspect current access-control setup tests**

Run:

```bash
cd "$APP_ROOT"
rg -n "migrate_report|report_access|persist_report|ensure_access_roles|required_role|Report" production_entry_app/production_entry_app/test_access_control.py production_entry_app/production_entry_app/report/test_reports.py
```

Expected: identify tests that still expect legacy report-role migration or fallback DB writes.

- [ ] **Step 2: Write failing tests for strict setup behavior**

Add tests with these assertions:

```python
def test_access_setup_does_not_sync_report_metadata_on_migrate_path():
	"""after_migrate setup must not save Report docs or rewrite report JSON."""
	# Patch report save paths and assert ensure_access_roles_and_settings() does not use them.


def test_report_access_metadata_is_source_controlled_not_runtime_synced():
	"""Report JSON should be the source of truth for report roles."""
	# Load report JSON files and assert their role metadata is explicit in JSON.
```

If exact function names differ, keep the behavior names above and implement with `unittest.mock.patch`.

- [ ] **Step 3: Run the failing tests**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
```

Expected before implementation: at least one new test fails because report metadata sync still runs or legacy expectations still exist.

### Task 1.2: Remove runtime Report metadata sync and fallback DB writes

**Files:**
- Modify: `production_entry_app/production_entry_app/access_control.py`
- Modify: `production_entry_app/production_entry_app/lifecycle.py` only if it directly calls report sync
- Modify: `production_entry_app/production_entry_app/test_access_control.py`

- [ ] **Step 1: Use CodeGraph to confirm call impact**

Use `codegraph_context` for `ensure_access_roles_and_settings` and `codegraph_impact` for `_migrate_report_access_metadata`.

Expected: impacted callers are limited to access-control setup and tests.

Fallback:

```bash
cd "$APP_ROOT"
rg -n "ensure_access_roles_and_settings|_migrate_report_access_metadata" production_entry_app tests
git diff -- production_entry_app/production_entry_app/access_control.py production_entry_app/production_entry_app/lifecycle.py
```

- [ ] **Step 2: Remove legacy migration paths**

Implement:

```python
def ensure_access_roles_and_settings() -> None:
	sync_configured_access_roles()
	# No Report metadata migration here. Report JSON is source-controlled state.
```

Remove or stop using these runtime paths if present:

```python
_migrate_access_settings()
_migrate_report_access_metadata()
_persist_report_access_metadata_without_save()
_persist_report_access_metadata()
```

Do not add fallback `frappe.db.set_value`, `frappe.db.delete`, or child-table `db_insert()` paths for Report metadata.

- [ ] **Step 3: Keep role/settings sync strict and idempotent**

Keep only current-state setup:

```python
desired_roles = {"System Manager", write_role, read_role}
```

If the code still updates a non-Report settings document, update it only when current value differs from desired value and use normal Frappe document APIs.

- [ ] **Step 4: Remove tests that expect legacy `required_role` migration**

Delete or rewrite tests whose only purpose is to preserve earlier branch behavior, especially tests that mention:

```text
required_role
legacy_required_role
fallback
non-dev DB persistence
```

- [ ] **Step 5: Verify targeted tests pass**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
```

Expected: both modules pass.

### Task 1.3: Clean existing report JSON churn

**Files:**
- Modify: `production_entry_app/production_entry_app/report/*/*.json`

- [ ] **Step 1: Inventory report JSON diffs**

Run:

```bash
cd "$APP_ROOT"
git diff --name-only develop...HEAD -- 'production_entry_app/production_entry_app/report/**/*.json'
git diff --stat develop...HEAD -- 'production_entry_app/production_entry_app/report/**/*.json'
```

Expected: list the report JSON files changed by metadata churn.

- [ ] **Step 2: Classify each report JSON diff**

Run:

```bash
cd "$APP_ROOT"
git diff develop...HEAD -- 'production_entry_app/production_entry_app/report/**/*.json'
```

Expected:

- Keep intentional report schema, filter, column, role, or prepared-report behavior changes.
- Clean churn-only changes such as generated `modified`, role row order, and `prepared_report` flips that are not part of the product change.

- [ ] **Step 3: Ask before destructive cleanup**

If the fastest cleanup is restoring a file from `develop`, stop and ask the user before running any destructive checkout/restore command.

Safer non-destructive option: edit the JSON manually or with a targeted patch so only churn fields are reverted.

- [ ] **Step 4: Verify migrate no longer rewrites reports**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" migrate
cd "$APP_ROOT"
git diff -- 'production_entry_app/production_entry_app/report/**/*.json'
cd "$BENCH16"
bench --site "$SITE16" migrate
cd "$APP_ROOT"
git diff -- 'production_entry_app/production_entry_app/report/**/*.json'
```

Expected: no report JSON diff is introduced by either migrate run.

### Task 1.4: Commit report churn fix

- [ ] **Step 1: Review chunk diff**

Run:

```bash
cd "$APP_ROOT"
git diff -- production_entry_app/production_entry_app/access_control.py production_entry_app/production_entry_app/test_access_control.py production_entry_app/production_entry_app/report/test_reports.py 'production_entry_app/production_entry_app/report/**/*.json'
```

Expected: diff removes runtime report mutation/fallbacks and cleans only churn-only report JSON changes.

- [ ] **Step 2: Commit**

Run:

```bash
cd "$APP_ROOT"
git add production_entry_app/production_entry_app/access_control.py production_entry_app/production_entry_app/test_access_control.py production_entry_app/production_entry_app/report/test_reports.py production_entry_app/production_entry_app/report
git commit -m "fix: stop migrate from rewriting report metadata"
```

Expected: one focused commit.

Trade-off: Report metadata will no longer be auto-healed during migrate. Developers must update Report JSON intentionally when roles or report settings change.

---

## Chunk 2: Normalize Frappe Permission Hook APIs

### Task 2.1: Add compatibility tests for permission hook signatures

**Files:**
- Create: `production_entry_app/production_entry_app/test_permission_hooks.py`
- Modify: existing DocType tests only if a better focused test module already exists

- [ ] **Step 1: Use CodeGraph to list `has_permission` implementations**

Use `codegraph_context` for `has_permission` and `codegraph_explore` on the matching DocType controller symbols.

Expected: confirm all DocType permission hooks that need v15/v16 compatible signatures.

Fallback:

```bash
cd "$APP_ROOT"
rg -n "def has_permission" production_entry_app/production_entry_app/doctype --type=py
rg -n "has_permission =" production_entry_app/hooks.py
```

- [ ] **Step 2: Create failing signature tests**

Create tests that call each hook with the parameters Frappe may pass:

```python
from frappe.tests.utils import FrappeTestCase


class TestPermissionHookSignatures(FrappeTestCase):
	def test_permission_hooks_accept_user_and_debug_arguments(self) -> None:
		hooks = [
			("production_entry_app.production_entry_app.doctype.operator.operator", "Operator"),
			("production_entry_app.production_entry_app.doctype.die_tool_counter.die_tool_counter", "Die Tool Counter"),
			("production_entry_app.production_entry_app.doctype.die_tool_maintenance_log.die_tool_maintenance_log", "Die Tool Maintenance Log"),
			("production_entry_app.production_entry_app.doctype.rejection_reason.rejection_reason", "Rejection Reason"),
			("production_entry_app.production_entry_app.doctype.loss_entry.loss_entry", "Loss Entry"),
			("production_entry_app.production_entry_app.doctype.rejection_breakup.rejection_breakup", "Rejection Breakup"),
		]
		# Import each module, create a minimal unsaved doc, and assert no TypeError.
```

Expected: the test fails for hooks that only accept `ptype`.

- [ ] **Step 3: Run the failing tests on v16**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_permission_hooks
```

Expected before implementation: TypeError on incompatible hooks.

### Task 2.2: Normalize hook signatures and keep behavior unchanged

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/operator/operator.py`
- Modify: `production_entry_app/production_entry_app/doctype/die_tool_counter/die_tool_counter.py`
- Modify: `production_entry_app/production_entry_app/doctype/die_tool_maintenance_log/die_tool_maintenance_log.py`
- Modify: `production_entry_app/production_entry_app/doctype/rejection_reason/rejection_reason.py`
- Modify: `production_entry_app/production_entry_app/doctype/loss_entry/loss_entry.py`
- Modify: `production_entry_app/production_entry_app/doctype/rejection_breakup/rejection_breakup.py`

- [ ] **Step 1: Change every hook to the same signature**

Use this signature pattern:

```python
def has_permission(doc: "Document", ptype: str | None = None, user: str | None = None, debug: bool = False) -> bool | None:
	...
```

If the module does not import `Document`, use `TYPE_CHECKING` to avoid runtime import overhead:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from frappe.model.document import Document
```

- [ ] **Step 2: Preserve current role logic**

Keep existing access decisions unless a current test proves the decision violates the intended role model.

If a hook checks the session user, replace it with:

```python
resolved_user = user or frappe.session.user
```

Use `resolved_user` in role checks so explicit Frappe permission checks work correctly.

- [ ] **Step 3: Run targeted tests on v16 and v15**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_permission_hooks
cd "$BENCH15"
bench --site "$SITE15" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_permission_hooks
```

Expected: both pass.

### Task 2.3: Commit permission hook fix

- [ ] **Step 1: Review chunk diff**

Run:

```bash
cd "$APP_ROOT"
git diff -- production_entry_app/production_entry_app/doctype production_entry_app/production_entry_app/test_permission_hooks.py
```

Expected: only signature-compatible hook changes and focused tests.

- [ ] **Step 2: Commit**

Run:

```bash
cd "$APP_ROOT"
git add production_entry_app/production_entry_app/doctype production_entry_app/production_entry_app/test_permission_hooks.py
git commit -m "fix: normalize permission hook signatures"
```

Expected: one focused commit.

Trade-off: The hook signatures become slightly wider than some implementations need, but they match Frappe's calling contract and avoid version-specific TypeErrors.

---

## Chunk 3: Align DocType And Custom Field Metadata

### Task 3.1: Add metadata convention tests

**Files:**
- Create: `production_entry_app/production_entry_app/test_doctype_metadata.py`

- [ ] **Step 1: Write tests for master-data rename policy**

Create a JSON-backed test:

```python
def test_master_data_doctypes_do_not_allow_rename() -> None:
	assert_doctype_json("Operator")["allow_rename"] == 0
	assert_doctype_json("Downtime Reason")["allow_rename"] == 0
```

Expected before implementation: fails if either DocType still has `allow_rename: 1`.

- [ ] **Step 2: Write tests for known filtered fields**

Create a small allowlist of fields that must be indexed because repo rules say every field used in filters should either have `search_index: 1` or be covered by a documented composite index.

Start with:

```python
REQUIRED_SEARCH_INDEXES = {
	"Shift": {"branch", "shift_date", "status"},
}
```

For custom fields, start with fields that are heavily used in Stock Entry and report filters:

```python
REQUIRED_CUSTOM_FIELD_SEARCH_INDEXES = {
	"Stock Entry-custom_pea_shift",
	"Stock Entry-custom_pea_workstation",
	"Stock Entry-custom_pea_operator",
	"Stock Entry Detail-custom_pea_is_rejection_item",
}
```

If a field is intentionally covered only by a composite index, declare it in the test with the index name and require a comment in `performance_indexes.py`.

- [ ] **Step 3: Run the failing metadata test**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata
```

Expected before implementation: fails for current metadata gaps.

### Task 3.2: Update DocType JSON metadata

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/operator/operator.json`
- Modify: `production_entry_app/production_entry_app/doctype/downtime_reason/downtime_reason.json`
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.json`

- [ ] **Step 1: Disable rename for fixture/master data**

Set:

```json
"allow_rename": 0
```

for:

```text
Operator
Downtime Reason
```

- [ ] **Step 2: Add justified field indexes**

Set `search_index: 1` only for fields used in frequent filters and not adequately covered by composite indexes.

Minimum expected change:

```json
{
	"fieldname": "branch",
	"search_index": 1
}
```

in `Shift` if branch is used in Shift overlap or access-control filters.

- [ ] **Step 3: Keep JSON formatting stable**

Run:

```bash
cd "$APP_ROOT"
pre-commit run prettier --files production_entry_app/production_entry_app/doctype/operator/operator.json production_entry_app/production_entry_app/doctype/downtime_reason/downtime_reason.json production_entry_app/production_entry_app/doctype/shift/shift.json
```

Expected: JSON formatting is stable.

### Task 3.3: Update Custom Field fixture metadata

**Files:**
- Modify: `production_entry_app/fixtures/custom_field.json`
- Modify: `production_entry_app/production_entry_app/fixtures/custom_field.json` if present
- Modify: `production_entry_app/production_entry_app/performance_indexes.py` only for documented composite-index exceptions

- [ ] **Step 1: Locate queried custom fields**

Use CodeGraph context for Stock Entry report filters and access-control queries, then confirm literal custom field IDs with:

```bash
cd "$APP_ROOT"
rg -n "custom_pea_(shift|workstation|operator|is_rejection_item|actual_start|actual_end)" production_entry_app tests
```

Expected: field usage is clear enough to choose field-level indexes or composite index documentation.

- [ ] **Step 2: Add `search_index` only where justified**

For each custom field in `REQUIRED_CUSTOM_FIELD_SEARCH_INDEXES`, set:

```json
"search_index": 1
```

Do not add indexes to every custom field. Extra indexes speed reads but slow writes and migrations.

- [ ] **Step 3: Keep fixture copies in sync**

If `production_entry_app/production_entry_app/fixtures/custom_field.json` exists, copy the same logical fixture changes there.

Run:

```bash
cd "$APP_ROOT"
python -m json.tool production_entry_app/fixtures/custom_field.json >/tmp/custom_field.root.json
if [ -f production_entry_app/production_entry_app/fixtures/custom_field.json ]; then python -m json.tool production_entry_app/production_entry_app/fixtures/custom_field.json >/tmp/custom_field.inner.json; fi
```

Expected: both commands succeed where files exist.

- [ ] **Step 4: Run metadata tests**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata
```

Expected: pass.

### Task 3.4: Verify metadata migration behavior

- [ ] **Step 1: Run migrate once on v16**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" migrate
cd "$APP_ROOT"
git diff -- production_entry_app/fixtures/custom_field.json production_entry_app/production_entry_app/doctype
```

Expected: only intentional metadata diffs remain.

- [ ] **Step 2: Run migrate a second time**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" migrate
cd "$APP_ROOT"
git diff -- production_entry_app/fixtures/custom_field.json production_entry_app/production_entry_app/doctype 'production_entry_app/production_entry_app/report/**/*.json'
```

Expected: no new churn appears after the second migrate.

### Task 3.5: Commit metadata fix

- [ ] **Step 1: Review chunk diff**

Run:

```bash
cd "$APP_ROOT"
git diff -- production_entry_app/production_entry_app/test_doctype_metadata.py production_entry_app/production_entry_app/doctype production_entry_app/fixtures/custom_field.json production_entry_app/production_entry_app/fixtures/custom_field.json production_entry_app/production_entry_app/performance_indexes.py
```

Expected: metadata changes are limited and tests explain the conventions.

- [ ] **Step 2: Commit**

Run:

```bash
cd "$APP_ROOT"
git add production_entry_app/production_entry_app/test_doctype_metadata.py production_entry_app/production_entry_app/doctype production_entry_app/fixtures/custom_field.json production_entry_app/production_entry_app/fixtures/custom_field.json production_entry_app/production_entry_app/performance_indexes.py
git commit -m "fix: align doctype metadata with frappe conventions"
```

Expected: one focused commit.

Trade-off: Additional indexes improve filtered lookups but increase write and migration cost. The test allowlist prevents broad indexing without a query-driven reason.

---

## Chunk 4: Fix Shift Status Audit Comments

### Task 4.1: Add a failing status audit test

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/shift/test_shift.py`

- [ ] **Step 1: Locate existing transition tests**

Run:

```bash
cd "$APP_ROOT"
rg -n "Status changed|add_comment|start_shift|end_shift|cancel_shift|_transition_status" production_entry_app/production_entry_app/doctype/shift/test_shift.py production_entry_app/production_entry_app/doctype/shift/shift.py
```

Expected: identify the best test class for transition comment assertions.

- [ ] **Step 2: Add a failing test**

Add or update a test like:

```python
def test_transition_comment_includes_status_and_user(self) -> None:
	shift = make_draft_shift()
	shift.start_shift()
	comments = frappe.get_all(
		"Comment",
		filters={"reference_doctype": "Shift", "reference_name": shift.name},
		fields=["content"],
		order_by="creation desc",
		limit=1,
	)
	assert comments
	assert "Status changed to" in comments[0].content
	assert frappe.session.user in comments[0].content
```

Expected before implementation: fails because the current comment omits the user.

- [ ] **Step 3: Run the failing Shift test**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift --test TestShift.test_transition_comment_includes_status_and_user
```

Expected before implementation: assertion failure for missing user.

### Task 4.2: Update `_transition_status()` comment text

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py`

- [ ] **Step 1: Implement repo-standard comment**

Use the `CLAUDE.md` pattern:

```python
self.add_comment(
	"Info",
	_("Status changed to {0} by {1}").format(
		frappe.bold(to_status), frappe.bold(frappe.session.user)
	),
)
```

- [ ] **Step 2: Run Shift tests**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
```

Expected: pass.

- [ ] **Step 3: Run relevant E2E flow**

Run:

```bash
cd "$APP_ROOT"
npm run test:e2e:ci -- tests/e2e/specs/shift-lifecycle.spec.js
```

Expected: pass.

### Task 4.3: Commit Shift audit fix

- [ ] **Step 1: Review chunk diff**

Run:

```bash
cd "$APP_ROOT"
git diff -- production_entry_app/production_entry_app/doctype/shift/shift.py production_entry_app/production_entry_app/doctype/shift/test_shift.py
```

Expected: one behavior fix plus focused test.

- [ ] **Step 2: Commit**

Run:

```bash
cd "$APP_ROOT"
git add production_entry_app/production_entry_app/doctype/shift/shift.py production_entry_app/production_entry_app/doctype/shift/test_shift.py
git commit -m "fix: include user in shift status audit comments"
```

Expected: one focused commit.

Trade-off: Comment content changes. Any tests or downstream scripts that asserted the exact old comment text must be updated to the new audited format.

---

## Chunk 5: Fix Client-Side Frappe API Deviations

### Task 5.1: Add JS unit coverage for access-control fetch errors

**Files:**
- Create: `tests/unit/access-control.test.js`
- Modify: `public/js/access_control.js`

- [ ] **Step 1: Inspect existing JS test harness patterns**

Run:

```bash
cd "$APP_ROOT"
sed -n '1,220p' tests/unit/custom-field-visibility.test.js
sed -n '1,220p' tests/unit/stock-entry-visibility.test.js
```

Expected: identify how tests stub `frappe`, globals, and module loading.

- [ ] **Step 2: Write failing access-control error test**

Create a test that stubs `frappe.call` to invoke `error` and asserts:

```javascript
assert.equal(typeof frappe.msgprint, "function");
assert.equal(msgprintCalls.length, 1);
assert.match(msgprintCalls[0].message || msgprintCalls[0], /access/i);
```

Expected before implementation: no `frappe.msgprint` call occurs.

- [ ] **Step 3: Run the failing JS test**

Run:

```bash
cd "$APP_ROOT"
node --test tests/unit/access-control.test.js
```

Expected before implementation: fails because errors are only logged or silently defaulted.

### Task 5.2: Make access-control API errors visible

**Files:**
- Modify: `public/js/access_control.js`

- [ ] **Step 1: Implement user-visible error handling**

In the `frappe.call` error callback, add:

```javascript
frappe.msgprint({
	title: __("Access settings unavailable"),
	message: __("Could not load Production Entry access settings. Please refresh and try again."),
	indicator: "orange",
});
console.error("[production_entry_app] Failed to load access settings", error);
```

Keep a conservative state only if the rest of the code requires a state object to avoid breaking form rendering. Do not hide the failure from the user.

- [ ] **Step 2: Run JS unit tests**

Run:

```bash
cd "$APP_ROOT"
node --test tests/unit/access-control.test.js
npm run test:unit:js
```

Expected: pass.

### Task 5.3: Document and verify ERPNext Stock Entry prototype patch

**Files:**
- Modify: `public/js/stock_entry.js`
- Modify: `tests/unit/stock-entry-visibility.test.js` if coverage is missing

- [ ] **Step 1: Inspect current monkey patch**

Run:

```bash
cd "$APP_ROOT"
rg -n "prototype|fg_completed_qty|original|fallback|erpnext.stock.StockEntry" public/js/stock_entry.js tests/unit/stock-entry-visibility.test.js
```

Expected: identify whether original method fallback is already tested.

- [ ] **Step 2: Add or update test for fallback behavior**

Assert that when Production Entry conditions do not apply, the original ERPNext method is called.

Expected before implementation: fail only if fallback behavior is missing or untested.

- [ ] **Step 3: Add dependency comment**

Add a short comment near the patch:

```javascript
// Depends on ERPNext v15/v16 `erpnext.stock.StockEntry.prototype.fg_completed_qty`
// from erpnext/public/js/controllers/stock_controller.js. Keep the original
// method fallback so ERPNext changes fail visibly instead of replacing behavior globally.
```

If the actual ERPNext source file differs, use the file confirmed in local bench apps.

- [ ] **Step 4: Run JS tests**

Run:

```bash
cd "$APP_ROOT"
node --test tests/unit/stock-entry-visibility.test.js
npm run test:unit:js
```

Expected: pass.

### Task 5.4: Fix custom child-field visibility leakage if present

**Files:**
- Modify: `public/js/custom_field_visibility.js`
- Modify: `tests/unit/custom-field-visibility.test.js`

- [ ] **Step 1: Add leakage test**

Write or update a test that simulates two forms or two grid rows and asserts hidden state does not leak through a shared DocField object.

Expected before implementation: fails if `docfield.hidden` is mutated globally.

- [ ] **Step 2: Prefer grid/form APIs over shared DocField mutation**

Use row/form APIs such as `toggle_display`, grid row refresh, or scoped control properties. Avoid mutating the shared DocField definition unless Frappe offers no scoped alternative.

- [ ] **Step 3: Run tests**

Run:

```bash
cd "$APP_ROOT"
node --test tests/unit/custom-field-visibility.test.js
npm run test:unit:js
```

Expected: pass.

### Task 5.5: Run E2E coverage for affected UI flows

- [ ] **Step 1: Run access-control and Stock Entry flows**

Run:

```bash
cd "$APP_ROOT"
npm run test:e2e:ci -- tests/e2e/specs/access-control-role-branch.spec.js tests/e2e/specs/shift-to-stock-entry.spec.js tests/e2e/specs/stock-entry-validations.spec.js
```

Expected: pass.

### Task 5.6: Commit client-side fixes

- [ ] **Step 1: Review chunk diff**

Run:

```bash
cd "$APP_ROOT"
git diff -- public/js tests/unit tests/e2e/specs/access-control-role-branch.spec.js
```

Expected: explicit user-visible error handling, prototype dependency documentation, and scoped visibility behavior.

- [ ] **Step 2: Commit**

Run:

```bash
cd "$APP_ROOT"
git add public/js tests/unit tests/e2e/specs/access-control-role-branch.spec.js
git commit -m "fix: align client scripts with frappe api conventions"
```

Expected: one focused commit.

Trade-off: Showing access-control load failures may surface transient server issues to users. That is intentional because silent permission-state defaults hide real operational problems.

---

## Chunk 6: Remove Dev-Only Legacy API Behavior

### Task 6.1: Add strict API tests for E2E access-control helpers

**Files:**
- Modify: `production_entry_app/production_entry_app/test_api.py`
- Modify: `production_entry_app/production_entry_app/api.py`

- [ ] **Step 1: Locate legacy fallback tests and API parameters**

Run:

```bash
cd "$APP_ROOT"
rg -n "required_role|legacy|required role|fallback|set_e2e_access_control|bootstrap_e2e_context|create_e2e" production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/test_api.py tests/e2e
```

Expected: find all compatibility paths that contradict the dev-only rule.

- [ ] **Step 2: Replace legacy tests with strict tests**

Remove tests that assert legacy `required_role` behavior.

Add a strict test:

```python
def test_set_e2e_access_control_does_not_accept_legacy_required_role(self) -> None:
	with self.assertRaises(TypeError):
		set_e2e_access_control(required_role="Manufacturing User")
```

If the API accepts `**kwargs`, assert `frappe.ValidationError` or `frappe.PermissionError` with a translated user-facing message instead of silent acceptance.

- [ ] **Step 3: Run the failing test**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected before implementation: strict test fails if the legacy parameter is still accepted.

### Task 6.2: Remove legacy parameters and optional fallback paths

**Files:**
- Modify: `production_entry_app/production_entry_app/api.py`
- Modify: `tests/e2e/fixtures/*.js`
- Modify: `tests/e2e/specs/*.js` only where helper call signatures change

- [ ] **Step 1: Remove `required_role` from current APIs**

Remove compatibility handling like:

```python
required_role: str | None = None
```

and any fallback mapping from `required_role` to current read/write role settings.

- [ ] **Step 2: Keep E2E APIs explicitly gated**

Preserve the repo-required gate:

```python
frappe.only_for("Administrator")
developer_mode
allow_e2e_tests
```

Do not weaken the gate while simplifying parameters.

- [ ] **Step 3: Update E2E helpers**

Update Playwright fixtures to call only current parameter names and current role model.

- [ ] **Step 4: Run API and E2E access tests**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
cd "$APP_ROOT"
npm run test:e2e:ci -- tests/e2e/specs/access-control-role-branch.spec.js tests/e2e/specs/permissions.spec.js
```

Expected: pass.

### Task 6.3: Optionally extract E2E-only API implementation

**Files:**
- Create: `production_entry_app/production_entry_app/e2e_api.py`
- Modify: `production_entry_app/production_entry_app/api.py`
- Modify: `production_entry_app/production_entry_app/test_api.py`

- [ ] **Step 1: Decide based on current diff size**

Proceed only if `api.py` still mixes large E2E-only helper implementations with product APIs after legacy cleanup.

Skip this extraction if it would create churn without simplifying the current change.

- [ ] **Step 2: Move implementations, keep whitelisted wrappers**

Keep public whitelisted API paths stable unless all tests and E2E helpers are updated in the same commit:

```python
@frappe.whitelist()
def bootstrap_e2e_context(...):
	from production_entry_app.production_entry_app.e2e_api import bootstrap_e2e_context as _bootstrap
	return _bootstrap(...)
```

- [ ] **Step 3: Run API tests**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected: pass.

### Task 6.4: Commit dev-only API cleanup

- [ ] **Step 1: Review chunk diff**

Run:

```bash
cd "$APP_ROOT"
git diff -- production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/e2e_api.py production_entry_app/production_entry_app/test_api.py tests/e2e
```

Expected: no legacy `required_role` behavior remains; E2E APIs remain gated.

- [ ] **Step 2: Commit**

Run:

```bash
cd "$APP_ROOT"
git add production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/e2e_api.py production_entry_app/production_entry_app/test_api.py tests/e2e
git commit -m "refactor: remove legacy e2e api fallbacks"
```

Expected: one focused commit. If `e2e_api.py` was not created, omit it from `git add`.

Trade-off: Removing legacy parameters can break old local scripts. That is acceptable for this app because the repo explicitly says it is under development and no compatibility/backfill behavior is required.

---

## Chunk 7: Final Verification And Branch Hygiene

### Task 7.1: Run full targeted backend verification on v16

- [ ] **Step 1: Run backend modules touched by this plan**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.report.test_reports
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_permission_hooks
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
bench --site "$SITE16" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected: all pass.

### Task 7.2: Run compatibility checks on v15

- [ ] **Step 1: Run tests most likely to catch v15/v16 API drift**

Run:

```bash
cd "$BENCH15"
bench --site "$SITE15" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_permission_hooks
bench --site "$SITE15" run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control
bench --site "$SITE15" run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift
```

Expected: all pass.

### Task 7.3: Run frontend and E2E verification

- [ ] **Step 1: Run JS unit tests**

Run:

```bash
cd "$APP_ROOT"
npm run test:unit:js
```

Expected: pass.

- [ ] **Step 2: Run impacted E2E specs**

Run:

```bash
cd "$APP_ROOT"
npm run test:e2e:ci -- tests/e2e/specs/access-control-role-branch.spec.js tests/e2e/specs/permissions.spec.js tests/e2e/specs/shift-lifecycle.spec.js tests/e2e/specs/shift-to-stock-entry.spec.js tests/e2e/specs/stock-entry-validations.spec.js
```

Expected: pass.

### Task 7.4: Verify migrate idempotence and no report JSON churn

- [ ] **Step 1: Run migrate twice**

Run:

```bash
cd "$BENCH16"
bench --site "$SITE16" migrate
bench --site "$SITE16" migrate
cd "$APP_ROOT"
git diff -- 'production_entry_app/production_entry_app/report/**/*.json'
```

Expected: no diff caused by migrate.

- [ ] **Step 2: Verify no accidental metadata churn outside intended files**

Run:

```bash
cd "$APP_ROOT"
git diff --name-only
git diff --stat
```

Expected: only intended files from completed chunks are modified.

### Task 7.5: Run pre-commit and final diff checks

- [ ] **Step 1: Run formatting and lint hooks**

Run:

```bash
cd "$APP_ROOT"
pre-commit run --all-files
```

Expected: pass. If hooks modify files, review the diff, rerun targeted tests for touched areas, then rerun pre-commit.

- [ ] **Step 2: Run final git checks**

Run:

```bash
cd "$APP_ROOT"
git diff --check
git status --short --branch
```

Expected: no whitespace errors. Worktree shows only expected changes if not committed, or is clean after final commit.

### Task 7.6: Final commit or PR update

- [ ] **Step 1: Commit any remaining verification-only changes**

Run only if pre-commit or verification produced additional intentional changes:

```bash
cd "$APP_ROOT"
git add <files>
git commit -m "chore: finish frappe compliance refactor"
```

Expected: final cleanup commit only if needed.

- [ ] **Step 2: Push branch when ready**

Run:

```bash
cd "$APP_ROOT"
git push
```

Expected: branch is pushed.

Trade-off: Full E2E verification is slower than targeted unit tests, but this branch touches permission and UI access-control behavior, so E2E coverage is necessary before claiming completion.

---

## Execution Notes

- If a chunk fails because existing unstaged work conflicts with the plan, stop and ask the user how to proceed.
- If a report JSON file contains both intentional schema changes and generated churn, preserve the schema changes and remove only churn fields.
- If a field is heavily filtered but covered by an existing composite index, document that in `performance_indexes.py` or the metadata test allowlist instead of adding a redundant index.
- If CodeGraph and literal search disagree, trust CodeGraph for structural relationships and use literal search only for JSON/string fields.
- This plan was not subagent-reviewed during creation because the current harness requires explicit user authorization before spawning subagents.
