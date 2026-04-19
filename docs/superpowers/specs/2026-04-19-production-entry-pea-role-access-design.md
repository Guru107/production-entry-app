# Production Entry App Access Control Redesign (PEA User Role Only)

Date: 2026-04-19
Status: Proposed

## Objective
Replace the current role+branch access model with a role-only model so the app is enabled only for users with a dedicated role (`PEA User` by default), while preserving existing runtime behavior for denied users (app hidden/blocked, Stock Entry native flow intact).

## Scope
In scope:
- Access decision model change from role+branch rules to single required role.
- Keep admin toggle (`enable_access_control`).
- Keep all existing hook entry points and frontend gating contract.
- Update tests/docs to the new model.

Out of scope:
- Explicit migration patch scripts (app is still in development).
- Behavior changes to Stock Entry passthrough guarantees.

## Final Decision
Selected approach: keep `Production Entry Settings` and simplify to a configurable required role.

Config model:
- `enable_access_control` (Check)
- `required_role` (Link to `Role`, default `PEA User`)

Access rules:
1. `System Manager` always allowed.
2. If access control is disabled, allow all users.
3. If enabled, allow only users having `required_role`.
4. Else deny.

## Alternatives Considered
1. Hard-code `PEA User` in code only.
- Pros: minimal config surface.
- Cons: role name changes require code deploy.

2. Remove settings and always enforce role.
- Pros: minimal runtime branching.
- Cons: no fast rollback/operational toggle.

## Why this approach
- Significant complexity reduction versus role+branch rule-table logic.
- Keeps operational safety via toggle.
- Keeps flexibility via configurable role name.
- Minimizes integration churn by preserving existing function interfaces.

## Architecture Changes
### Data/config
- Update `Production Entry Settings` DocType fields:
  - keep `enable_access_control`
  - replace/remove `allowed_access_rules`
  - add `required_role` (default `PEA User`)

### Access service (`access_control.py`)
- Replace branch/rule-list configuration model with:
  - `enabled: bool`
  - `required_role: str`
- Remove branch resolution logic:
  - user default branch lookup
  - branch user-permission fallback
  - per-user branch cache keys
- Keep public interfaces unchanged:
  - `can_use_production_entry_app(user=None)`
  - `has_app_permission()`
  - `assert_app_access(...)`
  - `has_gated_doctype_permission(...)`

### Hooks/API/frontend contract
- No interface change for hooks or whitelisted APIs.
- `get_access_control_state()` remains `{ "enabled": <bool> }` meaning user access state.
- Client-side hiding/bypass behavior remains unchanged.

## Runtime Behavior Guarantees
For users without the required role:
- Production Entry App entry points remain hidden/blocked.
- Gated app doctypes and APIs remain denied.
- Stock Entry remains usable with native ERPNext behavior (custom app UX/logic bypassed).

For users with required role:
- Existing app behavior remains available.

## Error Handling
- If settings read fails unexpectedly, fallback behavior remains conservative and consistent with existing guardrails (System Manager preserved).
- Missing/blank `required_role` should be treated as deny when access control is enabled (except System Manager).

## Testing Strategy
### Unit tests
Update `test_access_control.py`:
- allow when disabled
- allow for System Manager
- allow when user has required role
- deny when user lacks required role
- support custom required role value
- normalize/default behavior for missing required role
- cache invalidation behavior

### Integration/API permission tests
Update access gate tests to role-only fixtures:
- user with `PEA User` -> allowed paths
- user without `PEA User` -> denied paths

### E2E
Update access-control E2E spec:
- grant/revoke `PEA User`
- verify app visibility and usability toggles accordingly
- keep denied Stock Entry native-flow assertions

## Trade-offs
- Pros:
  - Lower cognitive and runtime complexity.
  - Easier rollout and support.
  - Clear explicit app entitlement role.
- Cons:
  - Loses branch-level entitlement granularity.
  - Existing role+branch tests/fixtures need rewrite.

## Rollout Notes
- Set `required_role = PEA User` in `Production Entry Settings`.
- Grant `PEA User` only to approved users.
- Keep `enable_access_control = 1` in production rollout.
- Fast rollback remains `enable_access_control = 0`.
