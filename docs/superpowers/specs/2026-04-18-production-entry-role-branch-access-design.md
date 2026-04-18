# Production Entry Role-Branch Access Control Design

Date: 2026-04-18
Branch: `feature/feature-flag-role`

## Goal

Enable Production Entry App only for explicitly allowed role+branch combinations. Example: users with role `Manufacturing User` and branch `Nashik` are allowed; others are denied.

Scope approved:

- hide/show app module entry in Desk navigation
- enforce DocType-level access blocking

Out of scope for this change:

- API-only feature flags not tied to module/DocType access
- per-feature granular toggles inside the app UI

## Finalized Decisions

- Configuration location: `Production Entry Settings` (Single DocType)
- Rule default: deny by default when no matching rule exists
- `System Manager`: always bypasses this gate

## Requirements

- Access policy must be admin-configurable without code deployment.
- Policy must evaluate both user role and branch.
- Users outside allowed role+branch rules must not see Production Entry module entry.
- Users outside allowed role+branch rules must be blocked from creating/reading/updating/deleting gated Production Entry doctypes.
- Enforcement must be server-side (UI hiding alone is insufficient).
- Permission hook return values must satisfy v16 strict bool semantics (`True` exactly for allow paths where applicable).

## Approaches Considered

### 1. Settings-driven runtime gate via hooks and permission hooks (recommended)

Summary:

- add settings-managed rule table for `(role, branch)`
- centralize decision logic in one service
- reuse same logic for Desk visibility and DocType access checks

Trade-offs:

- Pros: explicit and auditable policy, strong enforcement, minimal duplication
- Cons: adds one new settings doc and hook wiring, requires cache invalidation discipline

### 2. UI hiding and list filtering only

Summary:

- hide module/workspace and filter list views without strict backend enforcement

Trade-offs:

- Pros: low effort
- Cons: weak security; direct URL/API paths can still expose access unless separately blocked

### 3. ERPNext role permissions + branch user permissions only

Summary:

- rely on standard role permission manager and branch-level user permissions

Trade-offs:

- Pros: reduced custom app code
- Cons: cannot cleanly express module-specific role+branch gate behavior; lower operational clarity

## Recommended Architecture

Implement centralized policy service:

- module: `production_entry_app/production_entry_app/access_control.py`
- primary API: `can_use_production_entry_app(user: str | None = None) -> bool`

Use this API in two enforcement points:

1. App visibility enforcement
- enable `add_to_apps_screen` in `hooks.py`
- set `has_permission` to app permission hook that calls centralized policy service
- denied users do not see module entry

2. DocType permission enforcement
- add `has_permission` guards for gated app doctypes (starting with `Shift`, then other app doctypes in this module)
- each guard delegates to centralized policy service
- denied users are blocked on direct routes and CRUD

Design choice:

- server-side checks are authoritative
- any UI hiding is treated as convenience, not security boundary

## Configuration Model

Create `Production Entry Settings` (Single DocType) with:

- `enable_access_control` (Check, default `1`)
- `allowed_access_rules` (child table) with fields:
- `role` (Link `Role`, required)
- `branch` (Link `Branch`, required)
- optional `is_active` (Check, default `1`) for row-level toggling
- optional `notes` (Small Text)

Rule semantics:

- if user has `System Manager`, allow
- if `enable_access_control` is disabled, allow (ops safety switch)
- otherwise require at least one exact `(role, branch)` match
- no match => deny
- empty rules while enabled => deny all non-`System Manager`

## Branch Resolution Strategy

To evaluate `(role, branch)` robustly:

1. primary branch source: user default branch (`frappe.defaults.get_user_default("Branch", user=...)`)
2. fallback: branch from user permissions for `Branch` (if default missing)
3. unresolved branch for non-System Manager => deny

Rationale:

- keeps runtime checks deterministic and fast
- avoids ambiguous allow decisions when branch context is missing

Trade-off:

- fail-closed behavior can block users until branch defaults/permissions are fixed

## Data Flow

1. User enters Desk or opens gated DocType.
2. Hook invokes `can_use_production_entry_app`.
3. Service fetches cached settings payload, resolves user roles and branch, evaluates rule membership.
4. Hook returns allow/deny.
5. Denied request follows Frappe permission error path for DocTypes.

## Performance and Caching

- Cache parsed policy snapshot under app key, example: `pea:access_rules:v1`.
- Store allowed pairs as `set[tuple[str, str]]` for constant-time lookup.
- Invalidate cache in settings `on_update`.
- Avoid repeated DB calls in a single request by memoizing per-request decision (optional small optimization).

Trade-off:

- cache introduces staleness risk if invalidation is missed
- explicit invalidation keeps behavior correct with low runtime overhead

## Error Handling and Observability

Expected deny behavior:

- do not raise noisy stack traces for normal deny outcomes
- return permission deny with concise reason class (role/branch not enabled)

Operational logs:

- structured debug log with user, resolved branch, matched role, and final decision source

Failure mode:

- if settings doc is unavailable/corrupt, fail closed for non-System Manager and log error

Trade-off:

- fail-closed increases security
- temporary admin intervention may be required during misconfiguration

## Concrete Change Plan

### Hooks and policy wiring

Files:

- `production_entry_app/hooks.py`
- `production_entry_app/production_entry_app/access_control.py` (new)
- `production_entry_app/production_entry_app/lifecycle.py` (if setup/backfill hooks needed)

Changes:

- enable app entry permission callback via `add_to_apps_screen`
- add shared access policy implementation and cache helpers

### Settings and fixtures

Files:

- `production_entry_app/production_entry_app/doctype/production_entry_settings/*` (new)
- `production_entry_app/production_entry_app/doctype/production_entry_access_rule/*` (new child table doctype)
- fixture wiring if needed in `hooks.py`

Changes:

- create settings schema for admin-managed role+branch allowlist
- include permissions only for admin roles to edit settings

### DocType permission integration

Files:

- `production_entry_app/production_entry_app/doctype/shift/shift.py`
- additional gated doctypes in `production_entry_app/production_entry_app/doctype/*`

Changes:

- apply centralized permission gate in `has_permission` paths
- preserve explicit bool semantics required for v16

### Optional UI fallback messaging

Files:

- `production_entry_app/public/js/*` (only where needed)

Changes:

- avoid exposing action buttons for denied users where practical
- keep server enforcement as source of truth

## Test Strategy

### Unit tests (policy service)

- allow on exact `(role, branch)` match
- deny on role match but branch mismatch
- deny when rules empty and control enabled
- allow for `System Manager` bypass
- deny when branch unresolved (non-System Manager)
- cache invalidation on settings update

### Integration tests (permission hooks)

- app visibility hook returns expected bool across user matrices
- `Shift` create/read/write are allowed/denied per rule matrix

### E2E tests (Playwright)

- allowed user sees Production Entry app and can access Shift flow
- denied user does not see module entry and is blocked on direct Shift route
- `System Manager` retains access regardless of rules

## Rollout and Safety

- Default setting enabled with empty rules will deny all non-System Manager users.
- Rollout sequence:
- deploy with settings accessible to admins
- configure initial allow rules before enabling for business users
- verify with pilot users across at least one allowed and one denied branch

Operational fallback:

- admin can disable `enable_access_control` quickly to restore current behavior

## Risks and Mitigations

- Risk: branch resolution ambiguity for users lacking defaults
- Mitigation: explicit fallback chain + deterministic deny + admin setup checklist

- Risk: incomplete doctype coverage can leave gaps
- Mitigation: maintain explicit gated-doctype list and tests that verify each doctype path

- Risk: stale cache after rule changes
- Mitigation: mandatory cache invalidation in settings save hooks + test coverage

## Non-Goals

- dynamic per-session branch selector support
- department-based policy dimensions
- time-windowed policy rules

These can be layered later if needed, after baseline role+branch gate is stable.
