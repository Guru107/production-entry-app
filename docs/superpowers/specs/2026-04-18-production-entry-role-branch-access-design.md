# Production Entry Role-Branch Access Control Design

Date: 2026-04-18
Branch: `feature/feature-flag-role`

## Goal

Enable Production Entry App only for explicitly allowed role+branch combinations. Example: users with role `Manufacturing User` and branch `Nashik` are allowed; others are denied.

Target denied-user behavior:

- app appears not installed
- app doctypes are not accessible
- ERPNext core flows remain usable as native ERPNext behavior
- `Stock Entry` remains usable including `Manufacture`, but without Production Entry App custom fields/logic

## Finalized Decisions

- Configuration location: `Production Entry Settings` (Single DocType)
- Rule default: deny by default when no matching rule exists
- `System Manager`: always bypasses this gate
- Denied users keep native `Stock Entry` experience; app customizations are suppressed
- Same field-hiding pattern applies to all app-added custom fields on core doctypes

## Requirements

- Access policy must be admin-configurable without code deployment.
- Policy must evaluate both user role and branch.
- Users outside allowed role+branch rules must not see Production Entry module/workspace entry points.
- Users outside allowed role+branch rules must be blocked from creating/reading/updating/deleting Production Entry App doctypes.
- For denied users, `Stock Entry` must work as native ERPNext (including `Manufacture`) with app-specific custom logic disabled.
- For denied users, app-added custom fields on ERPNext core doctypes must be hidden in UI.
- Enforcement must be server-side for app doctypes and `Stock Entry` app logic.
- Permission hook return values must satisfy v16 strict bool semantics.

## Approaches Considered

### 1. Settings-driven runtime gate with native passthrough for denied users (recommended)

Summary:

- add settings-managed `(role, branch)` policy
- centralize decision logic in one service
- enforce app visibility + app doctype access + stock-entry passthrough mode

Trade-offs:

- Pros: closest to “app not installed” behavior while preserving ERPNext core usability
- Cons: more integration points (hooks, JS guards, override guards, field visibility map)

### 2. Pure UI hiding only

Summary:

- hide app links and custom fields only

Trade-offs:

- Pros: lowest effort
- Cons: insufficient security; direct API/route paths can still execute app behavior

### 3. Full global write-block on all app custom fields now

Summary:

- add deep server-side write guards across all core doctypes immediately

Trade-offs:

- Pros: strongest strictness
- Cons: significantly higher complexity/risk; larger test matrix

Chosen now:

- implement approach 1
- include scoped server-side blocking now for app doctypes + `Stock Entry` app logic
- defer full global custom-field write-block across all core doctypes to a later phase

## Recommended Architecture

Implement centralized policy service:

- module: `production_entry_app/production_entry_app/access_control.py`
- primary API: `can_use_production_entry_app(user: str | None = None) -> bool`

Use this API in three enforcement points:

1. App visibility enforcement
- enable `add_to_apps_screen` in `hooks.py`
- hook function contract: `def has_app_permission() -> bool`
- must return explicit `True` or `False`

2. App doctype permission enforcement
- gated doctypes in this phase:
- `Shift`
- `Loss Entry`
- `Downtime Reason`
- `Operator`
- `Die Tool Counter`
- `Die Tool Maintenance Log`
- `Rejection Reason`
- `Rejection Breakup`
- each doctype permission path delegates to centralized policy service

3. `Stock Entry` native passthrough enforcement
- denied users bypass Production Entry App stock-entry behavior
- app JS custom logic does not run for denied users
- app stock-entry hooks short-circuit for denied users
- stock-entry override behavior falls back to native ERPNext semantics for denied users

Design choice:

- server-side checks are authoritative
- UI hiding is convenience on top of authoritative checks

## Configuration Model

Create `Production Entry Settings` (Single DocType) with:

- `enable_access_control` (Check, default `0`)
- `allowed_access_rules` (child table) with fields:
- `role` (Link `Role`, required)
- `branch` (Link `Branch`, required)
- optional `is_active` (Check, default `1`)
- optional `notes` (Small Text)

Rule semantics:

- if user has `System Manager`, allow
- if `enable_access_control` is disabled, allow
- otherwise require at least one exact `(role, branch)` match
- no match => deny
- empty rules while enabled => deny all non-`System Manager`

## Branch Resolution Strategy

To evaluate `(role, branch)` deterministically:

1. primary: user default branch (`frappe.defaults.get_user_default("Branch", user=...)`)
2. fallback: use user-permission branch only if exactly one branch exists
3. zero or multiple fallback branches => unresolved branch
4. unresolved branch for non-System Manager => deny

Trade-off:

- fail-closed behavior can block users until branch defaults/permissions are fixed

## Core DocType Field-Hiding Pattern

For denied users, hide app-added custom fields on core doctypes via reusable client utility.

Initial core doctypes to include:

- `Stock Entry`
- `Stock Entry Detail` (where relevant in grid rendering)
- `Item`
- `Workstation`
- `Manufacturing Settings`
- `Downtime Entry`

Field source of truth:

- derive from app fixtures (`fixtures/custom_field.json`) where `module = "Production Entry App"`
- maintain a generated/validated doctype->field map used by client scripts

Trade-off:

- strong UX isolation now
- server-side write-block for every listed field is deferred beyond current phase

## Data Flow

1. User enters Desk or opens a doctype form.
2. Hook/helper invokes `can_use_production_entry_app`.
3. Service fetches cached policy, resolves user roles and branch, evaluates rule membership.
4. System returns allow/deny.
5. Denied outcomes:
- app visibility hook returns `False` (no reason payload)
- doctype permission checks deny via standard Frappe permission path
- `Stock Entry` executes native ERPNext path without app logic

## Performance and Caching

- Cache policy snapshot under key such as `pea:access_rules:v1`.
- Store allowed pairs as `set[tuple[str, str]]` for constant-time matching.
- Invalidate cache in settings `on_update`.
- Optional request-level memoization to avoid repeated checks in one request.

## Error Handling and Observability

Expected deny behavior:

- app-visibility checks: boolean deny only (`False`), no reason string
- doctype checks: normal Frappe permission deny
- no noisy stack traces for expected denies

Operational logs:

- structured debug logging of user, resolved branch, matched role, and decision source

Failure mode:

- if settings are unavailable/corrupt, fail closed for non-System Manager and log error

## Concrete Change Plan

### Hooks and policy wiring

Files:

- `production_entry_app/hooks.py`
- `production_entry_app/production_entry_app/access_control.py` (new)
- `production_entry_app/production_entry_app/lifecycle.py` (if setup helpers needed)

Changes:

- enable app entry permission callback
- add centralized policy implementation and cache invalidation helpers

### Settings and schema

Files:

- `production_entry_app/production_entry_app/doctype/production_entry_settings/*` (new)
- `production_entry_app/production_entry_app/doctype/production_entry_access_rule/*` (new)

Changes:

- add admin-managed allowlist schema
- restrict edit permissions to admin-level roles

### App doctype permission integration

Files:

- `production_entry_app/production_entry_app/doctype/shift/shift.py`
- `production_entry_app/production_entry_app/doctype/loss_entry/loss_entry.py`
- `production_entry_app/production_entry_app/doctype/downtime_reason/downtime_reason.py`
- `production_entry_app/production_entry_app/doctype/operator/operator.py`
- `production_entry_app/production_entry_app/doctype/die_tool_counter/die_tool_counter.py`
- `production_entry_app/production_entry_app/doctype/die_tool_maintenance_log/die_tool_maintenance_log.py`
- `production_entry_app/production_entry_app/doctype/rejection_reason/rejection_reason.py`
- `production_entry_app/production_entry_app/doctype/rejection_breakup/rejection_breakup.py`

Changes:

- apply centralized permission gate in doctype permission paths
- preserve explicit bool semantics for v16

### Stock Entry native passthrough

Files:

- `production_entry_app/public/js/stock_entry.js`
- `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- `production_entry_app/production_entry_app/overrides/stock_entry.py`

Changes:

- short-circuit app JS behavior for denied users
- short-circuit app server hooks for denied users
- preserve native ERPNext manufacture/stock-entry behavior for denied users

### Core doctype custom field hiding

Files:

- client scripts/utilities under `production_entry_app/public/js/*`
- field map definition derived from fixtures

Changes:

- hide app-owned custom fields on designated core doctypes for denied users
- keep allowed-user behavior unchanged

## Test Strategy

### Unit tests

- policy service role+branch matrix
- branch-resolution deterministic fallback behavior
- cache invalidation on settings update

### Integration tests

- app visibility hook bool behavior
- all gated app doctypes deny/allow matrix
- stock-entry hook/override short-circuit for denied users

### E2E tests

- denied user cannot see app and cannot access app doctypes
- denied user can complete native `Stock Entry` manufacture flow
- denied user does not see app custom fields on core doctypes
- allowed user retains full current app behavior
- System Manager bypass works regardless of rules

## Rollout and Safety

- default install state: `enable_access_control=0`.
- rollout sequence:
- deploy
- configure allow rules
- validate with pilot allowed and denied users
- enable access control

Operational fallback:

- admin disables `enable_access_control` to restore unrestricted behavior immediately

## Risks and Mitigations

- Risk: incomplete core doctype field map can leak fields in UI
- Mitigation: derive map from fixtures and test per doctype/form

- Risk: passthrough misses one stock-entry app hook path
- Mitigation: centralized guard helper and deny-user regression tests for validate/submit/cancel

- Risk: cache staleness after settings update
- Mitigation: strict cache invalidation tests

- Risk: non-StockEntry API/import writes to app custom fields on core doctypes
- Mitigation: documented as deferred phase with explicit follow-up hardening story

## Non-Goals (Current Phase)

- full server-side write-block for every app custom field on every ERPNext core doctype
- dynamic per-session branch selector
- department/time-window policy dimensions


## Superseded

Superseded on 2026-04-19 by the role-only access design:
- `docs/superpowers/specs/2026-04-19-production-entry-pea-role-access-design.md`
- `docs/superpowers/plans/2026-04-19-production-entry-pea-role-access-control.md`
