# CLAUDE.md

## Stack
- Frappe: `v15 + v16` | ERPNext: `v15 + v16` | Other apps: `hrms, india_compliance`
- App: `production_entry_app` | Bench: `/root/workspace/bench15 (v15) / /root/workspace/bench16 (v16)` | Dev site: `development.localhost (v15) / frappe16.localhost (v16)` | Test site: `development.localhost / frappe16.localhost (dev sites double as test sites)` | Prod: `live on a separate host — never run bench commands or writes against it; investigate read-only and fix in the app`
- Python `3.10+ (benches run 3.13 / 3.14)`, Node `v24`
- Use only APIs that exist in the version above. Unsure? Read `apps/frappe` / `apps/erpnext`. Don't guess.

## Commands
```bash
bench --site <site> migrate                 # always pass --site
bench build --app production_entry_app
bench --site <site> run-tests --app production_entry_app
bench --site <site> run-tests --doctype "<DocType>"
bench --site <site> run-tests --module <dotted.path.test_x> --test <test_name>
bench --site <site> export-fixtures --app production_entry_app
pre-commit run --files <changed files>
npx playwright test            # E2E; --headed / --debug for visual / step-through
```
- Run `bench` from the bench root (`cd /root/workspace/bench15` or `bench16`), not from inside the app. Both benches symlink this repo into `apps/`.
- Tests only on the two sites above (needs `bench --site <site> set-config allow_tests true` once per site).
- Ask before `reinstall`, `drop-site`, `restore` or any `--force`. Never run anything on a production site.
- `bench start` only in the background, and only if not already running.

## Skills
- Install from [frappe/skills](https://github.com/frappe/skills) and commit them to the repo:
  `npx skills add frappe/skills --skill frappe-app-dev --skill frappe-code-review --skill fix-issue --skill ship-it`
- `frappe-app-dev` for how-to. `frappe-code-review` before every PR. `/fix-issue` for bug tickets. `/ship-it` to get a branch to a merge-ready PR.
- Skills target recent Frappe. If one conflicts with this file or `v15 + v16`, this file wins.

## How to work
- Read how the app already does it first. Match existing patterns and style.
- Over ~3 files: plan first and confirm.
- Unsure about business logic or the client's process? Ask. Don't invent it.
- Bug: reproduce first, fix the cause not the symptom, smallest diff.
- Done = migrate clean + tests pass + pre-commit pass. Run them, don't assume.

## Golden rules
- Never edit, monkey-patch or copy core files. Use `doc_events`, `override_doctype_class` (sparingly), Custom Fields, Property Setters, fixtures.
- New doctype: write the JSON and let migrate create it. Don't `mkdir` doctype folders.
- Hand-edited doctype JSON: bump `modified`, or migrate skips it.
- Fixtures: always filtered by module or name. Never export all Custom Fields / Property Setters.
- Field and doctype changes sync through migrate. Existing data that must change needs a patch in `patches.txt`: new defaults on Single doctypes, field type changes, new mandatory or unique fields, renamed or moved data.
- Patches: idempotent, ordered after what they read, tested on a site with real data (empty tables always "pass").
- Small, focused diffs. Unrelated changes go in separate PRs.

## Queries: always Query Builder
- Every query beyond a simple ORM call goes through `frappe.qb`: selects, joins, aggregates, updates, deletes, subqueries.
- Use `frappe.qb.get_query(...)` where `v15 + v16` has it; otherwise `frappe.qb.DocType(...)`.
- qb skips permissions, and so do `get_all`, `get_value`, `exists` and `count`. In user-facing APIs, check permission first and read lists with `get_list` (or `get_query(..., ignore_permissions=False)` where supported).
- Simple ORM calls are fine: `get_doc`, `get_value`, `exists`, `count`, and `get_list` (`get_all` only in server-side logic).
- No new `frappe.db.sql`. Only when qb truly can't express it (e.g. a CTE), with `%s` params and a comment saying why.
- Raw SQL in lines you're already changing? Convert it to qb. Don't rewrite untouched code in the same PR.
- Functions from `frappe.query_builder.functions` (`Sum`, `Count`, `IfNull`, `Coalesce`) and `Case` from `frappe.query_builder`, not SQL strings. No raw strings in `.where()` and never user input in `Field()` / `DocType()`.

```python
from frappe.query_builder.functions import Sum
si = frappe.qb.DocType("Sales Invoice")
rows = (
    frappe.qb.from_(si)
    .select(si.customer, Sum(si.grand_total).as_("total"))
    .where((si.docstatus == 1) & (si.company == company))
    .groupby(si.customer)
).run(as_dict=True)
```

## Security (critical)
- No SQL built with `.format()`, f-strings or `+`. Ever.
- Every `@frappe.whitelist()`:
  - checks permission (`frappe.has_permission(..., throw=True)` / `doc.check_permission()`), ideally inside the controller method
  - has type hints on every arg (v15+ validates them; blocks filter-list injection like `{"key": ["!=", ""]}`). On older versions, also check with `isinstance`.
  - declares `methods=["GET"]` for reads or `["POST"]` for writes (GET doesn't commit)
  - reads lists with `get_list`, not `get_all` or plain qb (see Queries for what skips permissions)
- `allow_guest=True`: think 10 times. Return only fields a guest needs, validate input, rate-limit.
- `ignore_permissions=True`: never to bypass checks on data the caller asked for. Only for system-side records (logs, internal docs, jobs), with a comment why.
- No mass assignment: never `doc.update(frappe.form_dict)` or `**kwargs` from the client. Set only the fields you allow.
- `set_value` / `db.delete` with a name or filter that could be `None` or empty changes every row; `get_value` returns an arbitrary one. Guard it.
- No `eval` / `exec`. Never run a client-supplied method path. Secrets in Password fields, never in logs.
- JS calls must point to a real whitelisted method. No `frappe.client.*` from server code.
- XSS: escape user input right before putting it in HTML, Jinja or JS. Don't "fix" by stripping characters.
- User file paths: no traversal outside the site folder. Prefer the File doctype.

## Transactions & framework fit
- Don't call `frappe.db.commit()` or a full `frappe.db.rollback()`. Requests (POST/PUT), jobs and patches auto-commit at the end; uncaught errors auto-rollback.
- Why: a mid-way commit makes the work before it permanent. If a later step fails, you're left with half-saved data (e.g. a voucher without its GL entries).
- Never commit in: controllers, `doc_events`, `validate` / `on_submit` hooks, whitelisted methods, tests (it breaks test rollback).
- Writes in a GET request are lost. Fix with `methods=["POST"]`, not a commit.
- Job needs data written in this request? `enqueue(..., enqueue_after_commit=True)`, not a commit.
- Need to undo part of the work? `frappe.db.savepoint()` + `rollback(save_point=...)`, not a full rollback.
- Explicit commit or full rollback is allowed only in background jobs, patches and the entry-point handlers below, with a comment saying why:
  - Big batch work: commit every N records so one failure doesn't lose everything and locks stay short.
  - Before calling an external API that moves money or can't be undone (bank payments, e-invoice, GST): commit the "initiated" state first, and check it before sending, so a retry can't send it twice. So these calls run in a job, not in the request.
  - Wrap each batch in try/except: on failure `rollback()`, then `frappe.log_error()`, then continue or stop on purpose.
- Entry points are the only place for a broad `except Exception`:
  - Scheduler and enqueued jobs: `frappe.db.rollback()` first (a caught error is not auto-rolled back, so partial work would be committed), then `frappe.log_error()`.
  - `after_install` / `after_migrate`: catch, add context to the message, and re-raise so install or migrate fails loudly.
- Hooks: validation in `validate`, side effects in `on_submit` / `on_update`. In `validate` / `before_*` just set `self.field`. In `on_*` / `after_*` use `self.db_set()`. Never `doc.save()` inside its own hooks.
- `frappe.db.set_value` / `db_set` skip validation and hooks. Outside the doc's own post-save hooks, never use them for status or state changes; load the doc and save it.
- Errors: `frappe.throw(_("..."))` with a specific message naming the field, row and old → new value.
- Don't put `frappe.throw` inside `try/except Exception`; the except swallows it.
- `override_doctype_class`: inherit the original and call `super()`. Never replace a whole core controller.
- JS: call doc methods with `frm.call("method")`. Use `frappe.call` with a dotted path only for module-level functions.
- Long work: `frappe.enqueue(..., queue="long")` or `enqueue_doc`.
- Check-then-insert is a race. Use a unique constraint.
- Don't wrap a whitelisted doc method in a separate `api.py` function. Call it directly.

## ERPNext specifics
- Never insert GL Entry / Stock Ledger Entry / Payment Ledger Entry directly. Go through the standard vouchers.
- Use `flt(x, precision)`, `cint`, `getdate`, `nowdate`, `now_datetime`. Round currency with the field's precision; never compare raw floats. No `datetime.now()` (ignores the site time zone).
- Never hardcode company, accounts, warehouses, naming series. Respect company, currency, fiscal year.
- Silent ledger or stock corruption is the worst bug. Fail loudly over posting wrong entries.

## Performance
- Common reads < 100ms, writes < 5s, never > 10s in a request.
- No DB calls in loops in request code (`get_doc`, `get_value`, `set_value`, `sql`). Batch with `["in", names]` or one query. Background jobs may loop, in batches.
- One field? `frappe.db.get_value` (or `get_cached_value` for rarely changing masters), not `get_doc`.
- Delete one doc with `frappe.delete_doc`. Bulk delete with qb or `frappe.db.delete` only when the doctype has no `on_trash` / `after_delete` hooks, child tables or links to clean up (it skips all of them).
- Aggregate in the query (qb `Sum`, `Count`), not in Python. Bound scans on big tables.
- Use the `doc` passed into hooks; don't reload it.
- `doc_events` on busy core doctypes (Sales Invoice, Stock Entry, GL/Stock Ledger Entry, `"*"`) run on every save. Keep them light, no queries in loops; move heavy work to `enqueue`.
- Keep `validate` light: no queries in loops there either.
- Indexes on filtered fields, declared in code (`search_index` / patch), never added by hand.
- Cache with `@redis_cache` / `@request_cache` / `@site_cache` (check which exist in `v15 + v16`). Never hand-roll caches in `frappe.local` / `frappe.flags`.
- JS: no `frappe.call` / `frappe.db.get_value` in a loop.

## Code quality
- No commented-out code, unused imports/functions/classes, unreachable code.
- No `print()`; use `frappe.logger()` or `frappe.log_error()`.
- No copy-pasted logic blocks; extract a shared function.
- Don't shadow builtins (`list`, `filter`, `type`, `id`...).
- Never assume a DB read returned something. Handle `None` / empty before indexing.
- Naming: DocType names in Title Case, fieldnames in snake_case.
- No `global` or mutable class-level state. No `except: pass`. Catch specific errors and log (entry points: see Transactions).
- Max ~5 params; new params go last as keyword args with `None` defaults.
- Boring, readable code over clever one-liners. Type hints over describing types in docstrings.
- Strings: `"".join()` or lists, not `+=` in loops. User-facing strings in `_()` / `__()`.

## Tests
- Every new doctype gets real tests, not the empty stub: validation, permissions, submit/cancel.
- Base class per version: `IntegrationTestCase` / `UnitTestCase` (v16+), `FrappeTestCase` (v14, v15), `unittest.TestCase` (v13). Check `v15 + v16`.
- The test framework rolls back data on v14+; on v13 clean up in `tearDown`. Create data in `setUp`; don't depend on site data or other tests.
- Deterministic: no `random`, use `freeze_time` for dates.
- Non-trivial bug fix = regression test that fails without the fix (overrides `/fix-issue`, which asks for one on every fix).
- Had to change an existing test's assertion? That's a red flag. Explain why in the PR.

## Before PR
Run `frappe-code-review`. Quick check: qb not raw SQL | whitelist perms + type hints | get_all / qb in API | mass assignment | commit/rollback | ignore_permissions | None filters | loops / N+1 | patches | `modified` bumped | fixtures filtered | tests run | no dead code

## Git
- Branch `feat/<desc>` or `fix/<desc>`. Conventional commits: `fix: ...`, `feat: ...`.
- Never commit `site_config.json`, keys or `.env`.
- Never commit `human-input.md`, `PLAN.md` or `shift_losses.csv`.
- Releases: follow the `release` skill exactly; `develop` is branch-protected, nothing lands directly.
- Client-side JS: follow the `frappe-js-patterns` skill (error callbacks, debounce, last-call-wins, rAF cleanup, `__()`, escaping).

---

## Project context: Production Entry App

## Development Philosophy

- **Test-Driven Development is mandatory.** Write a failing test first; then write the
  implementation that makes it pass. No feature or bug-fix ships without tests.
- **Coverage must stay above 85%** at all times.
- **Always add E2E (Playwright) tests** for every user-facing flow. Run them after every change.
- Avoid code duplication. Extract shared logic; don't copy-paste.
- Keep solutions simple. Don't add error-handling, helpers, or abstractions for scenarios that
  don't exist yet.

---

## Project Overview
- LIVE IN PRODUCTION: changes must keep existing production data and documents working. Schema or data changes ship with an idempotent patch (see Golden rules).
A Frappe/ERPNext application that simplifies production entries through a **Shift** document.
The Shift is a central hub for supervisors: planned losses, downtime entries, warehouse defaults,
and linked Stock Entries all flow through it.

---

## Code Style

- All Python functions must have **type hints** on parameters and return type.
- Always run `pre-commit run --all-files` after implementation when you are ready to tell the human that changes are done. Fix the lint issues if fixable and stage -> commit -> push if its a git repository

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
production. The Playwright suite also requires `"ignore_csrf": 1` on any site it runs
against (set automatically for ephemeral sites by `scripts/run_ephemeral_e2e.sh`): E2E
helpers call whitelisted APIs without loading Desk, so no CSRF token is ever minted.

### Permissions

- Check the minimum required permission — `read`, `write`, or a specific role.
- Child table access must follow the parent DocType. Frappe v15/v16 checks child permissions
  through `has_child_permission()` on the parent; an empty child `permissions` array is valid.
  Do not duplicate parent roles on a child to implement access control.
- Do not use `ignore_permissions=True` outside of test/E2E helpers.
- Frappe permissions are additive: read-only users get `PEA Read Only` only — never `Stock User`/
  `Manufacturing User`. Close a missing read with a read/select `DocPerm` fixture row for that DocType,
  not a broader role.
- Use `DocPerm` fixtures, never `Custom DocPerm`: Custom DocPerm freezes a standard DocType's permission
  snapshot and stops tracking ERPNext upstream.

---

## DocType Design Conventions

### Field Definitions

- Mark required fields with `"reqd": 1` in the DocType JSON — do not rely on Python-only
  validation for required fields.
- Add `"search_index": 1` to every field used in `filters` in `frappe.get_all()` /
  `frappe.qb` queries (e.g., `shift_date`, `status`, `supervisor`).
- Add `"non_negative": 1` to numeric fields that cannot go below zero (quantities, stroke
  counts, durations). Frappe v15/v16 DocField has no `min_value` / `max_value` properties —
  upper bounds (percentages 0–100, buffer minutes 0–480) must be enforced in `validate()`
  with `frappe.throw()`, not in the DocType JSON.
- Add `"is_active"` Check field (default 1) to all master-data DocTypes to enable soft-deletion
  without breaking historical links.
- Use `"allow_rename": 0` on master data that is referenced in fixture-installed records.

### Custom Fields

Custom fields are defined in `fixtures/custom_field.json`. After editing:
```bash
bench --site <site> migrate
```

### Fixtures

Fixture JSONs live in `production_entry_app/fixtures/`.
Run `bench export-fixtures` after changing fixture data.

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
bench --site <site> run-tests --app production_entry_app --coverage
```
Coverage must not drop below **85%**.

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
Completed is terminal for status, but a Completed shift still accepts one field edit: a larger
`shift_duration`, validated against overlapping non-cancelled shifts in the same company, branch and
department (`_validate_completed_shift_edits`, `_validate_no_overlapping_shifts`).

### Stock Entry Hooks (`stock_entry_hooks.py`)

Registered in `hooks.py` for `validate`, `on_submit`, `on_cancel`. Key responsibilities:
- Validate that the linked Shift is Running (time-window check with configurable buffers).
- Apply rejection item rows idempotently (remove-then-rebuild, at the validate hook only). Stale rows
  after a `fg_completed_qty` edit without re-fetch are left to ERPNext 15.122+'s finished-qty guard.
- Default Total Press Strokes in `before_validate` so zero `fg_completed_qty` surfaces the app's
  press-strokes error instead of that guard's message.
- Increment the die tool stroke counter atomically on submit (nothing added when posted at or before
  `last_reset_on`); recompute it on cancel and on Maintenance Log submit/cancel.
- Invalidate shift metrics cache on submit and cancel.

---

## Application Specific Considerations

- `fg_completed_qty`  is the total production quantity. So by that we can come to a conclusion that `custom_pea_ok_qty` = `fg_completed_qty` - `custom_pea_rejection_qty`.
- User only enters `fg_completed_qty` and `custom_pea_rejection_qty` in the Stock Entry document when `from_bom` is checked.
- It is mandatory for the user to enter `fg_completed_qty` and `custom_pea_rejection_qty` if available for Manufacturing entries.
- The app is live, so migrations and backfills are real: a field type change, a new mandatory or
  unique field, or renamed/moved data needs a patch in `patches.txt` that is safe on production data.
  The original install migration (ADR 0005) adopted the production host's legacy Downtime Reason
  DocType and retired the legacy time-capture UI; it never backfilled historical data into
  `custom_pea_*` fields, so entries from before the go-live are outside the app's reports.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `Guru107/production-entry-app`, via the `gh` CLI. External PRs are not treated as a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix) — no overrides. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
