# CLAUDE.md

Guidance for Claude Code and developers working in this repository.

---

## Development Philosophy

- **Test-Driven Development is mandatory.** Write a failing test first; then write the
  implementation that makes it pass. No feature or bug-fix ships without tests.
- **Coverage must stay above 90%** at all times.
- **Always add E2E (Playwright) tests** for every user-facing flow. Run them after every change.
- Avoid code duplication. Extract shared logic; don't copy-paste.
- Keep solutions simple. Don't add error-handling, helpers, or abstractions for scenarios that
  don't exist yet.

---

## Project Overview

A Frappe Framework (v15) application for ERPNext that simplifies production entries through a
**Shift** document. The Shift is a central hub for supervisors: planned losses, downtime entries,
warehouse defaults, and linked Stock Entries all flow through it.

Bench root: `/Users/gurudattkulkarni/Workspace/production-entry-app/`
App root: `apps/production_entry_app/production_entry_app/`
Site: `development.localhost`
Sibling apps in bench: `frappe/`, `erpnext/`

### DocTypes

All DocTypes live under `production_entry_app/production_entry_app/doctype/`:

| DocType | Role |
|---------|------|
| **Shift** | Main document. Status-managed (Draft→Running→Completed/Cancelled). Non-submittable. |
| **Loss Entry** | Child table of Shift. Auto-populated by duration/start time. Locked once Running. |
| **Downtime Reason** | Master data (Tea Break, Lunch Break). Installed via fixtures. |
| **Operator** | Master data. `is_active` flag for soft-deletion. |
| **Die Tool Counter** | Tracks stroke count per item. Updated atomically on Stock Entry submit. |
| **Die Tool Maintenance Log** | Submittable log. Submission resets the counter. |
| **Rejection Reason** | Master data for rejection classification. |
| **Rejection Breakup** | Child table on Stock Entry for per-reason rejection quantities. |

### Naming Convention

Shifts: `SHIFT-YYYY.MM.DD.Shift-{N}` (e.g., `SHIFT-2026.02.03.Shift-1`)

---

## Commands

All `bench` commands run from the bench root, not from inside the app directory.

```bash
# Run all tests
bench --site development.localhost run-tests --app production_entry_app

# Run a single test file
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.doctype.shift.test_shift

# Run a single test case
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.doctype.shift.test_shift \
  --test TestShift.test_defaults_are_populated_on_insert

# Build JS/CSS assets
bench build --app production_entry_app

# Start dev server
bench start

# Lint (run from apps/production_entry_app/)
pre-commit run --all-files

# Playwright E2E tests
npx playwright test
npx playwright test --headed   # visual
npx playwright test --debug    # step-through
```

---

## Code Style

- **Tabs** for indentation in Python and JavaScript (never spaces).
- Python line length: **110 characters**.
- Python target: **3.10+** (use `match`, `X | Y` unions, `str | None` type hints).
- All Python functions must have **type hints** on parameters and return type.
- `ruff format` for Python, `prettier` for JS/JSON. Run `pre-commit run --all-files` before
  every commit.

---

## Python — Frappe Best Practices

### Validation Errors

```python
# CORRECT — frappe.throw() takes a message and an optional exception CLASS
frappe.throw(_("Shift Duration must be 8, 10, or 12 hours."))
frappe.throw(_("Cannot start a cancelled shift."), frappe.PermissionError)

# WRONG — never pass an exception instance as exc=
# frappe.throw(_("Invalid value."), exc=e)   ← BAD

# WRONG — never raise bare exceptions for user-facing errors
# raise ValueError("bad input")              ← BAD
```

### Database Queries

```python
# Prefer frappe.qb for anything more than a single-field lookup
from frappe.query_builder import DocType

Shift = DocType("Shift")
result = (
	frappe.qb.from_(Shift)
	.select(Shift.name, Shift.status)
	.where(Shift.shift_date == today())
	.where(Shift.status != "Cancelled")
	.run(as_dict=True)
)

# Use frappe.db.get_value() for simple single-field reads
status = frappe.db.get_value("Shift", shift_name, "status")

# AVOID raw SQL — use frappe.qb or frappe.db helpers instead
# frappe.db.sql("SELECT ...")   ← only when qb cannot express it
```

### Atomic Updates for Accumulators

When a field is an accumulator (counter, running total) that multiple concurrent requests
may update, **never** do read-modify-write via `frappe.get_doc()` → mutate → `doc.save()`.
Use a single atomic `UPDATE` via `frappe.qb`:

```python
from frappe.query_builder import DocType

DTC = DocType("Die Tool Counter")
frappe.qb.update(DTC).set(
	DTC.current_stroke_count, DTC.current_stroke_count + stroke_delta
).where(DTC.name == counter_name).run()
```

This maps to `UPDATE tabDie Tool Counter SET current_stroke_count = current_stroke_count + N WHERE name = X`
which MariaDB/MySQL executes under a row-level lock — safe for concurrent requests.

### Overlap / Existence Checks — Avoid N+1

Do NOT fetch a large result set and compare in Python. Push the overlap condition into the DB:

```python
from frappe.query_builder.functions import CustomFunction

Timestamp = CustomFunction("TIMESTAMP", ["date_col", "time_col"])
conflict = (
	frappe.qb.from_(Shift)
	.select(Shift.name)
	.where(Shift.status != "Cancelled")
	.where(Timestamp(Shift.shift_date, Shift.planned_start_time) < my_end)
	.where(Timestamp(Shift.shift_end_date, Shift.planned_end_time) > my_start)
	.where(Shift.name != self.name)
	.limit(1)
	.run(as_dict=True)
)
if conflict:
	frappe.throw(...)
```

### Caching

- Use **user-agnostic cache keys** for aggregate data: `f"pea:shift_metrics:{shift_name}"`.
  Per-user keys make invalidation impossible.
- **Always invalidate** the cache in `on_submit` / `on_cancel` hooks of documents that
  contribute to the cached value. Never rely solely on TTL expiry.
- Define TTLs as module-level constants: `METRICS_CACHE_TTL_SEC: int = 30`.

```python
# Invalidate
frappe.cache().delete_value(f"pea:shift_metrics:{shift_name}")

# Set with TTL
frappe.cache().set_value(key, value, expires_in_sec=METRICS_CACHE_TTL_SEC)
```

### Status Transitions

Status on the Shift DocType is controlled exclusively via `_transition_status()`. Direct field
edits are rejected in `_validate_status()`. Every transition must:
1. Set `self.flags.allow_status_change = True` before `self.save()`.
2. Add an audit comment after save:

```python
self.add_comment(
	"Info",
	_("Status changed to {0} by {1}").format(
		frappe.bold(to_status), frappe.bold(frappe.session.user)
	),
)
```

### Magic Numbers → Module Constants

Every business-rule value must be a named constant at the top of the module:

```python
VALID_SHIFT_DURATIONS: frozenset[int] = frozenset({8, 10, 12})
METRICS_CACHE_TTL_SEC: int = 30
WARNING_THRESHOLD_PCT_DEFAULT: float = 90.0
_DEFAULT_BUFFER_MINS: int = 60
_MAX_BUFFER_MINS: int = 480
```

### `validate()` Performance

Use `self.get_doc_before_save()` to access the pre-save state instead of issuing an extra
`frappe.db.get_value()`. Frappe v15 always populates this for existing documents during
`validate()`:

```python
before = self.get_doc_before_save()
prev_status = (before.status if before else None) or frappe.db.get_value("Shift", self.name, "status")
```

### Translation

Every user-visible string must use `_()`:

```python
frappe.throw(_("Shift {0} is already Running.").format(frappe.bold(self.name)))
frappe.msgprint(_("Shift started successfully."))
```

### E2E / Test-Only APIs

APIs that create or destroy test data must be gated by **both** conditions:

```python
def _assert_e2e_api_allowed() -> None:
	frappe.only_for("Administrator")
	if not frappe.conf.get("developer_mode"):
		frappe.throw(_("E2E APIs require developer_mode."), frappe.PermissionError)
	if not frappe.conf.get("allow_e2e_tests"):
		frappe.throw(_("E2E APIs require allow_e2e_tests=1 in site_config.json."), frappe.PermissionError)
```

Add `"allow_e2e_tests": 1` to `site_config.json` in development only. Never set this in
production.

### Permissions

- Check the minimum required permission — `read`, `write`, or a specific role.
- Child table permissions must **match the parent DocType** roles. A Manufacturing User who
  can create a Shift must also be able to read/write its `Loss Entry` child rows.
- Do not use `ignore_permissions=True` outside of test/E2E helpers.

---

## DocType Design Conventions

### Field Definitions

- Mark required fields with `"reqd": 1` in the DocType JSON — do not rely on Python-only
  validation for required fields.
- Add `"search_index": 1` to every field used in `filters` in `frappe.get_all()` /
  `frappe.qb` queries (e.g., `shift_date`, `status`, `supervisor`).
- Add `"min_value"` / `"max_value"` to numeric fields with known bounds (percentages 0–100,
  buffer minutes 0–480).
- Add `"is_active"` Check field (default 1) to all master-data DocTypes to enable soft-deletion
  without breaking historical links.
- Use `"allow_rename": 0` on master data that is referenced in fixture-installed records.

### Custom Fields

Custom fields are defined in `fixtures/custom_field.json`. After editing:
```bash
bench --site development.localhost migrate
```

### Fixtures

Fixture JSONs live in `production_entry_app/fixtures/`. The inner
`production_entry_app/production_entry_app/fixtures/` directory is a copy — keep both in sync.
Run `bench export-fixtures` after changing fixture data.

---

## JavaScript — Frappe Best Practices

### Every `frappe.call()` Must Have an `error:` Callback

Silent failures are unacceptable. Every API call must inform the user when something goes wrong:

```javascript
frappe.call({
	method: "...",
	args: { ... },
	callback(r) { /* success */ },
	error(err) {
		frappe.msgprint(__("Operation failed. Please retry or contact support."));
		console.error(err);
	},
});
```

### Debounce Repeated Triggers

When multiple field changes trigger the same server call, debounce to 300 ms to avoid
sending duplicate requests:

```javascript
let _timer = null;
function _my_handler(frm) {
	clearTimeout(_timer);
	_timer = setTimeout(() => _do_call(frm), 300);
}
```

### Last-Call-Wins for Rapid API Calls

When a user action can trigger multiple in-flight requests, use a request counter so stale
responses are discarded:

```javascript
let _reqId = 0;
function _fetch_metrics(frm) {
	const id = ++_reqId;
	frappe.call({
		...,
		callback(r) {
			if (id !== _reqId) return;   // stale — discard
			/* apply result */
		},
	});
}
```

### Animation Frame Cleanup

Always guard `requestAnimationFrame` loops with a `stopped` flag so orphaned frames cannot
re-queue themselves after a form unloads:

```javascript
const state = { stopped: false, animationFrame: null };

const animate = () => {
	if (state.stopped) return;   // checked first, every frame
	/* draw */
	state.animationFrame = requestAnimationFrame(animate);
};

// On cleanup:
state.stopped = true;
cancelAnimationFrame(state.animationFrame);
```

### i18n — All User-Visible Strings in `__()`

Every string a user can see must be wrapped in the translation function:

```javascript
// CORRECT
frappe.msgprint(__("Shift started successfully."));
ctx.fillText(__("No entries for this shift."), x, y);
`<th>${__("Workstation")}</th>`

// WRONG — hard-coded strings are not translatable
frappe.msgprint("Shift started successfully.");
```

Exceptions: CSS class names, HTML attribute names, API method paths, DocType names used as
identifiers (not displayed text), JS variable names.

### Monkey-Patching ERPNext Prototypes

When overriding a method on an ERPNext prototype (e.g., `erpnext.stock.StockEntry.prototype`),
always check that the original method exists and preserve a fallback:

```javascript
const _proto = erpnext.stock.StockEntry.prototype;
const _original = typeof _proto.some_method === "function" ? _proto.some_method : null;

_proto.some_method = function () {
	if (_should_override(this.frm.doc)) { /* custom logic */ return; }
	if (_original) return _original.call(this);
	console.warn("[production_entry_app] some_method original not found; ERPNext may have changed.");
};
```

Document the dependency with a comment referencing the ERPNext source file and version.

### HTML Construction

Prefer template literals over string concatenation. Always escape user-supplied values:

```javascript
const row = `
	<tr>
		<td>${frappe.utils.escape_html(entry.name)}</td>
		<td>${frappe.utils.escape_html(entry.workstation || "—")}</td>
	</tr>`;
```

---

## Testing Approach

### Unit Tests (Python)

- Extend `FrappeTestCase` from `frappe.tests.utils`.
- Helper `_ensure_loss_types()` creates Downtime Reason fixture data inside tests.
- Use `frappe.db.set_value()` for test cleanup — it bypasses validations.
- Avoid explicit `frappe.db.commit()` unless testing transaction isolation.
- Name tests `test_<what>_<expected_outcome>` (e.g., `test_overlap_validation_throws_for_same_time`).

### E2E Tests (Playwright)

- Location: `tests/e2e/specs/`
- Always add an E2E spec for every user-facing flow.
- Required scenarios per feature:
  - Happy path (success)
  - Validation path (user error → visible message)
  - Permission path (unauthorized user → blocked)
- Run after every code change: `npx playwright test`

### Coverage

Run the full suite and check coverage before every PR:
```bash
bench --site development.localhost run-tests --app production_entry_app --with-coverage
```
Coverage must not drop below **90%**.

---

## Architecture Notes

### Shift Status Machine

```
Draft ──start_shift()──► Running ──end_shift()──► Completed
  │                                                    │
  └────────────cancel_shift()──────────────────► Cancelled
```

All transitions go through `_transition_status()` which sets `flags.allow_status_change = True`.
`_validate_status()` rejects any direct field edit. Every transition writes an audit comment.

### Stock Entry Hooks (`stock_entry_hooks.py`)

Registered in `hooks.py` for `validate`, `on_submit`, `on_cancel`. Key responsibilities:
- Validate that the linked Shift is Running (time-window check with configurable buffers).
- Apply rejection item rows idempotently (remove-then-rebuild with guard for double-restoration).
- Update die tool stroke counter atomically on submit; reverse on cancel.
- Invalidate shift metrics cache on submit and cancel.

### Whitelisted APIs (`shift.py`, `api.py`)

| Method | Purpose |
|--------|---------|
| `get_planned_losses_for_duration()` | Break schedule for duration + start time |
| `get_linked_downtime_entries()` | Downtime Entries overlapping this shift's window |
| `check_running_shift_conflict()` | Is another shift already Running? |
| `get_shift_metrics()` | Aggregate production metrics (cached) |
| `get_shift_timeline_data()` | Canvas timeline data for Workstation/Operator forms |

### Fixtures

- `custom_field.json` — Custom fields on Stock Entry, Manufacturing Settings, Workstation, etc.
- `property_setter.json` — Hides/collapses standard ERPNext sections on Stock Entry.
- `downtime_reason.json` — Default Downtime Reason records (Tea Break, Lunch Break).

After changing fixtures: `bench export-fixtures --app production_entry_app`
After pulling fixture changes: `bench --site development.localhost migrate`

Never commit human-input.md and PLAN.md files to git
