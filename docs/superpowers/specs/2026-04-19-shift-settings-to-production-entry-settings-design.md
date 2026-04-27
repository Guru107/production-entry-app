# Move Shift Settings From Manufacturing Settings to Production Entry Settings

Date: 2026-04-19
Status: Proposed

## Objective
Move all Production Entry module settings currently stored under ERPNext `Manufacturing Settings` (Shift Settings tab/custom fields) into `Production Entry Settings` so module configuration is centralized in one place.

## Scope
In scope:
- Shift settings data model move from `Manufacturing Settings` custom fields to native fields in `Production Entry Settings`.
- Runtime read/write updates to use `Production Entry Settings` only.
- Fixture, generated-map, and tests updates.

Out of scope:
- Backfill/migration scripts for existing values.
- Compatibility fallback reads from old fields.

User-confirmed constraint:
- No value migration/backfill required (app under development).

## Decision
Use a hard move with no fallback.

## Data Model Changes
Add Shift Settings fields directly on `Production Entry Settings`:
- `shift_raw_material_warehouse` (Link: Warehouse)
- `shift_wip_warehouse` (Link: Warehouse)
- `shift_rejection_warehouse` (Link: Warehouse)
- `shift_scrap_warehouse` (Link: Warehouse, if still referenced)
- `shift_start_buffer_mins` (Int)
- `shift_end_buffer_mins` (Int)

Remove Shift Settings custom fields/tab/section entries from `Manufacturing Settings` in fixture definitions.

## Runtime Changes
Update all reads/writes to `Production Entry Settings`:
- Stock Entry buffer minutes resolver logic.
- Rejection warehouse fallback logic.
- Shift default-warehouse resolution logic.
- API methods used by E2E/bootstrap that currently seed/snapshot settings values.

Update user-facing error/help text that currently says `Manufacturing Settings` to `Production Entry Settings`.

## Testing and Generated Artifacts
- Update Python tests that set/get shift settings values.
- Update E2E setup/helpers that currently mutate `Manufacturing Settings` fields.
- Update generated access-control field map to include moved settings under `Production Entry Settings`.
- Regenerate and validate generated files.

Targeted verification:
- access-control tests
- stock-entry hooks/access tests
- shift defaults tests
- unit visibility tests
- e2e access-control flow (environment permitting)

## Trade-offs
Pros:
- Single configuration location for module settings.
- Less cognitive overhead and cleaner support workflows.
- Removes dependence on foreign doctype custom-field layout for app settings.

Cons:
- Existing bench values in Manufacturing Settings will no longer be read.
- Requires touching many call sites/tests in one change set.

## Rollout Notes
- After deploy/migrate, set required shift settings in `Production Entry Settings` manually.
- Keep `Manufacturing Settings` shift custom fields removed to avoid split-brain configuration.
