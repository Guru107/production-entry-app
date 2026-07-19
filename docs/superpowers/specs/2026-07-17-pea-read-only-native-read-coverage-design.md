# PEA Read Only Native Read Coverage

## Summary

`PEA Read Only` must be usable as a complete read-only production-entry role. A read-only user should be able to open the required Desk surfaces and inspect production-entry data without being assigned broad ERPNext roles such as `Stock User` or `Manufacturing User`.

The app will solve the current permission gaps with native Frappe role permissions. It will not add a custom deny layer for Stock Entry creation.

## Problem

`PEA Read Only` currently covers the app-owned doctypes, but it does not cover every standard Frappe or ERPNext doctype reached during read-only Desk usage. When a user has only `PEA Read Only`, they can hit errors such as missing access to `Page` or `Company`.

Assigning `Stock User` or `Manufacturing User` avoids those read errors, but those roles also grant create/write permissions on operational documents such as Stock Entry. Frappe permissions are additive, so `PEA Read Only` cannot subtract create permission that comes from another assigned role.

## Goals

- Make `PEA Read Only` sufficient for read-only production-entry operations.
- Allow read-only users to view required linked records and Desk pages.
- Prevent a user with only `PEA Read Only` from creating, saving, submitting, cancelling, or deleting Stock Entry documents, including Manufacturing Stock Entries.
- Keep permission behavior native to Frappe role permissions.
- Keep role assignment clear: read-only production users should not need `Stock User` or `Manufacturing User`.

## Non-Goals

- Do not add a custom Stock Entry permission deny hook.
- Do not change business logic for Stock Entry, Shift, reports, late-entry stamping, or manufacturing calculations.
- Do not auto-assign or auto-remove roles from users.
- Do not try to override permissions granted by unrelated roles assigned by an administrator.

## Design

Add app-owned `DocPerm` fixture rows for `PEA Read Only` on the standard doctypes required by the production-entry read flow.

Initial standard doctype coverage:

- `Page`
- `Company`
- `Stock Entry`
- `Stock Entry Detail`
- `BOM`
- `BOM Item`
- `Item`
- `Workstation`
- `Warehouse`
- `UOM`

The `PEA Read Only` rows will grant read-only access:

- `read = 1`
- `select = 1`
- `create = 0`
- `write = 0`
- `submit = 0`
- `cancel = 0`
- `delete = 0`
- `amend = 0`
- `permlevel = 0`

The fixture export should be scoped narrowly so the app owns only the PEA role permission rows it needs. Existing app-owned doctype permissions remain in their doctype JSON files.

## Role Policy

Read-only production users should be assigned `PEA Read Only` and should not be assigned broad ERPNext operational roles such as `Stock User` or `Manufacturing User`.

This is a deliberate tradeoff. The native-permission model stays simple and auditable, but it relies on role assignment discipline. If an administrator also assigns `Stock User` or `Manufacturing User`, Frappe will grant any create/write permissions from those roles because permissions are additive.

## Data Flow

1. `bench migrate` imports the app fixtures.
2. Frappe stores the PEA read-only `DocPerm` rows on the standard doctypes.
3. A user with only `PEA Read Only` opens Desk and production-entry records.
4. Frappe resolves access through native role permissions.
5. Read and select operations succeed for covered doctypes.
6. Create/write/submit/cancel/delete operations fail because `PEA Read Only` does not grant them.

## Error Handling

No new runtime error handling is needed. Permission failures should continue to use Frappe's native `PermissionError` behavior.

If a read-only user hits another missing read dependency, the fix is to add a read/select `DocPerm` row for that specific doctype instead of assigning a broad ERPNext role.

## Testing

Add focused permission coverage that verifies:

- A user with only `PEA Read Only` can read/select the required standard doctypes.
- A user with only `PEA Read Only` cannot create or save a Manufacturing Stock Entry.
- A `PEA User` keeps the existing intended operational access.

Verification should include:

- Focused server-side permission tests.
- `bench --site development.localhost migrate` on the target bench.
- Direct database verification that the imported `DocPerm` rows are at `permlevel = 0` and do not grant create/write/submit/cancel/delete.
- `pre-commit run --all-files`.

Playwright coverage is only needed if implementation changes a user-facing flow or if the existing read-only Desk flow lacks adequate coverage after the native permission rows are added.

## Tradeoffs

This design avoids custom deny logic and stays aligned with Frappe's native permission model. The cost is maintaining a precise list of standard read dependencies. That is preferable to assigning broad operational roles to read-only users, because broad roles silently grant write capabilities outside the PEA role model.
