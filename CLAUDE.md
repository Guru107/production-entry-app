# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code)/Codex when working with code in this repository.

## Development Philosophy
Always follow test driven development. Write tests first and then implement features to satisfy them.
The coverage must always be above 90%. Tests are the source of truth. No feature or code changes must be implemented without writing test cases first. Tests are the holy grail. The ultimate proof of application correctness.

## Project Overview

A Frappe Framework (v15) application for ERPNext that simplifies production entries through a **Shift** document. The Shift acts as a central hub for supervisors to manage shift-related information including planned losses, downtime entries, and warehouse defaults.

This app lives inside a standard Frappe bench at `apps/production_entry_app/`. The bench also contains `frappe/` and `erpnext/` as sibling apps.

## Commands

All bench commands must be run from the bench root (`/Users/gurudattkulkarni/Workspace/production-entry-app/`), not from within the app directory.

```bash
# Run all tests
bench --site <site_name> run-tests --app production_entry_app

# Run a single test file
bench --site <site_name> run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift

# Run a single test case
bench --site <site_name> run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift --test TestShift.test_defaults_are_populated_on_insert

# Dev server
bench start

# Build assets
bench build

# Linting (run from apps/production_entry_app/)
pre-commit run --all-files

# Individual linters
ruff check production_entry_app/
ruff format production_entry_app/
```

## Code Style

- **Tabs for indentation** in both Python and JavaScript
- Python line length: **110 characters**
- Python target: **3.10+**
- Formatting enforced via `ruff format` (Python) and `prettier` (JS)
- Linting via `ruff` (Python) and `eslint` (JS)
- Pre-commit hooks are configured; run `pre-commit install` after cloning
- Always run `pre-commit run --all-files` before commiting changes to git

## Architecture

### DocType Structure

All DocTypes live under `production_entry_app/production_entry_app/doctype/`:

- **Shift** — Main document. State-managed (Draft -> Running -> Completed/Cancelled). Non-submittable; status transitions happen via whitelisted methods (`start_shift`, `end_shift`, `cancel_shift`), not direct field edits. The `flags.allow_status_change` flag gates status transitions.
- **Loss Type** — Master data (Tea Break, Lunch Break). Installed via fixtures.
- **Loss Entry** — Child table of Shift for planned losses. Auto-populated based on shift duration/start time. Locked when shift is Running or beyond.
- **Shift Planned Loss** — Legacy name for Loss Entry child table rows.

### Key Patterns

**Status transitions are method-based, not field-based.** The `_validate_status` method rejects direct status edits. All transitions go through `_transition_status()` which sets `flags.allow_status_change = True` before saving.

**Whitelisted module-level APIs** in `shift.py` (called from client JS):
- `get_planned_losses_for_duration()` — Returns break schedule for a given duration/start time
- `get_linked_downtime_entries()` — Fetches Downtime Entries by time overlap (not by link field)
- `check_running_shift_conflict()` — Checks if another shift is already Running

**Fixtures** (`hooks.py` → `fixtures`): Custom Fields on Manufacturing Settings (warehouse defaults) and Downtime Entry (shift link), plus default Loss Type records. Fixture JSON files are in `production_entry_app/fixtures/`.
`property_setter.json` contains `Stock Entry-section_break_7qsm-hidden`; this targets the Stock Entry **Process Loss** section in ERPNext v15.

**Validations run in `validate()`:** overlap prevention, unique shift label per date, field locking by status, end time/date calculation for midnight-crossing shifts.

### Client-Side (`shift.js`)

Form script uses private helper functions prefixed with `_`. Key behaviors:
- Action buttons (Start/End/Cancel) rendered in `refresh` based on current status
- Break auto-population triggers on `shift_duration`, `planned_start_time`, or `shift_date` change via server call
- Linked Downtime Entries rendered as an HTML table in a virtual field

### Naming Convention

Shift names follow: `SHIFT-YYYY.MM.DD.Shift-{N}` (e.g., `SHIFT-2026.02.03.Shift-1`)

## Frappe-Specific Conventions

- Use `frappe.throw(_("..."))` for validation errors, never bare `raise`
- Use `frappe._()` / `__()` for all user-facing strings (translation)
- Use `frappe.get_doc()`, `frappe.get_list()`, `frappe.db.get_value()` for DB operations — avoid raw SQL
- Use `frappe.qb` (Query Builder) for complex queries
- Use `doc.flags` for temporary state, not instance attributes
- Tests extend `FrappeTestCase` from `frappe.tests.utils`
- Permissions: Manufacturing User and Manufacturing Manager roles have full CRUD on Shift

## Testing Approach

Tests use `FrappeTestCase`. The test suite covers defaults, time calculations (midnight crossing), status transitions, planned loss auto-population, overlap prevention, field locking, permissions, running shift conflicts, and notifications. Helper method `_ensure_loss_types()` creates fixture data within tests.
