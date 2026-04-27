# Production Entry PEA Role Access Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace role+branch gating with role-only gating (`PEA User` by default), while preserving existing denied-user runtime behavior.

**Architecture:** Keep the same hook/API entry points and simplify access resolution internals to `enable_access_control + required_role`. Remove branch/rule-table evaluation logic. Preserve `System Manager` bypass and Stock Entry native passthrough for denied users.

**Tech Stack:** Frappe/ERPNext (Python), DocType JSON metadata, Playwright/Jest/Python tests.

---

### Task 1: Simplify Settings Schema

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.json`
- Modify: `production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.py`
- Modify: `production_entry_app/production_entry_app/doctype/production_entry_access_rule/production_entry_access_rule.json` (deprecate/remove references as needed)
- Test: `production_entry_app/production_entry_app/test_access_control.py`

- [ ] **Step 1: Write failing metadata test**
```python
def test_settings_has_required_role_field(self):
    settings = frappe.get_meta("Production Entry Settings")
    assert settings.has_field("required_role")
```

- [ ] **Step 2: Run test and confirm failure**
Run: `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control --test test_settings_has_required_role_field`
Expected: FAIL (`required_role` missing).

- [ ] **Step 3: Update doctype metadata minimally**
```json
{"fieldname": "required_role", "fieldtype": "Link", "options": "Role", "default": "PEA User"}
```

- [ ] **Step 4: Run targeted tests**
Run same test; expected PASS.

- [ ] **Step 5: Commit**
```bash
git add production_entry_app/production_entry_app/doctype/production_entry_settings/production_entry_settings.json \
        production_entry_app/production_entry_app/test_access_control.py
git commit -m "feat: add required_role config for access control"
```

### Task 2: Refactor Access Resolution to Role-Only

**Files:**
- Modify: `production_entry_app/production_entry_app/access_control.py`
- Test: `production_entry_app/production_entry_app/test_access_control.py`

- [ ] **Step 1: Write failing unit tests for role-only logic**
```python
def test_enabled_allows_when_user_has_required_role(self): ...
def test_enabled_denies_when_user_missing_required_role(self): ...
def test_enabled_denies_when_required_role_blank(self): ...
```

- [ ] **Step 2: Run targeted tests and confirm failure**
Run: `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control`
Expected: FAIL on new tests.

- [ ] **Step 3: Implement minimal role-only resolver**
```python
@dataclass(frozen=True)
class AccessConfiguration:
    enabled: bool
    required_role: str

if _is_system_manager(user):
    return True
if not config.enabled:
    return True
return bool(config.required_role) and config.required_role in set(frappe.get_roles(user))
```
Remove branch/default/user-permission lookup code and related cache keys.

- [ ] **Step 4: Re-run module tests**
Expected: PASS for updated access-control tests.

- [ ] **Step 5: Commit**
```bash
git add production_entry_app/production_entry_app/access_control.py \
        production_entry_app/production_entry_app/test_access_control.py
git commit -m "refactor: switch access control to required-role model"
```

### Task 3: Keep Hook/API Contracts Stable

**Files:**
- Verify/modify only if needed: `production_entry_app/hooks.py`
- Verify/modify only if needed: `production_entry_app/production_entry_app/api.py`
- Verify/modify only if needed: `production_entry_app/production_entry_app/api_timeline.py`
- Verify/modify only if needed: `production_entry_app/production_entry_app/doctype/shift/shift.py`
- Test: `production_entry_app/production_entry_app/test_access_control_whitelisted_api.py`
- Test: `production_entry_app/tests/compat/test_v16_permission_hooks.py`

- [ ] **Step 1: Add failing regression tests for unchanged contracts**
```python
def test_get_access_control_state_returns_enabled_flag(self): ...
def test_gated_api_denies_without_required_role(self): ...
```

- [ ] **Step 2: Run targeted tests and confirm failure**
Run related modules and confirm contract regression points.

- [ ] **Step 3: Apply minimal code edits**
Ensure no branch-dependent assumptions remain in access assertions; keep function signatures unchanged.

- [ ] **Step 4: Re-run targeted API/hook tests**
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add production_entry_app/hooks.py \
        production_entry_app/production_entry_app/api.py \
        production_entry_app/production_entry_app/api_timeline.py \
        production_entry_app/production_entry_app/doctype/shift/shift.py \
        production_entry_app/production_entry_app/test_access_control_whitelisted_api.py \
        production_entry_app/tests/compat/test_v16_permission_hooks.py
git commit -m "test: preserve access-control hook and api contracts"
```

### Task 4: Preserve Stock Entry Native Passthrough for Denied Users

**Files:**
- Modify if needed: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Modify if needed: `production_entry_app/public/js/stock_entry.js`
- Test: `production_entry_app/production_entry_app/overrides/test_stock_entry_access_control.py`
- Test: `tests/unit/stock-entry-visibility.test.js`
- Test: `tests/e2e/specs/access-control-role-branch.spec.js` (rename content semantics to role-only)

- [ ] **Step 1: Write failing denied-user passthrough tests with role-only setup**
```python
def test_validate_returns_early_without_required_role(self): ...
```

- [ ] **Step 2: Run focused tests and confirm failure**
Run Python/Jest cases for denied-user stock-entry path.

- [ ] **Step 3: Adjust only setup/auth assumptions**
Keep existing passthrough behavior; replace branch-based setup with role grant/revoke setup.

- [ ] **Step 4: Re-run focused stock-entry tests**
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add production_entry_app/production_entry_app/overrides/stock_entry_hooks.py \
        production_entry_app/public/js/stock_entry.js \
        production_entry_app/production_entry_app/overrides/test_stock_entry_access_control.py \
        tests/unit/stock-entry-visibility.test.js \
        tests/e2e/specs/access-control-role-branch.spec.js
git commit -m "test: move stock entry access scenarios to role-only setup"
```

### Task 5: Update Fixtures/Docs and Remove Branch-Rule Residue

**Files:**
- Modify: `docs/superpowers/specs/2026-04-18-production-entry-role-branch-access-design.md` (append superseded note)
- Modify: `docs/superpowers/plans/2026-04-18-production-entry-role-branch-access-control.md` (append superseded note)
- Modify: `README.md` (if access-control section exists)
- Verify cleanup by grep across repo.

- [ ] **Step 1: Add failing doc consistency check (manual checklist)**
Checklist: no active docs should instruct branch-rule setup for current model.

- [ ] **Step 2: Run residue scan**
Run: `rg -n "allowed_access_rules|role\+branch|Branch.*access" production_entry_app docs tests`
Expected: only intentional historical references remain.

- [ ] **Step 3: Update docs minimally**
Add “superseded by 2026-04-19 role-only design” notes.

- [ ] **Step 4: Re-run residue scan**
Expected: no stale operational instructions.

- [ ] **Step 5: Commit**
```bash
git add docs/superpowers/specs/2026-04-18-production-entry-role-branch-access-design.md \
        docs/superpowers/plans/2026-04-18-production-entry-role-branch-access-control.md \
        README.md
git commit -m "docs: mark branch-rule access design as superseded"
```

### Task 6: Full Verification and Rollout Validation

**Files:**
- No new product files; verification artifacts only.

- [ ] **Step 1: Run lint/format checks**
Run: `pre-commit run --all-files`
Expected: PASS.

- [ ] **Step 2: Run focused Python test suites**
Run:
```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control_whitelisted_api
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_access_control
```
Expected: PASS.

- [ ] **Step 3: Run JS/E2E checks**
Run:
```bash
npm test -- --runInBand tests/unit/stock-entry-visibility.test.js
npx playwright test tests/e2e/specs/access-control-role-branch.spec.js
```
Expected: PASS (or explicitly document environment blockers).

- [ ] **Step 4: Manual rollout validation on benches**
For both benches/sites, verify:
1. `required_role = PEA User`, `enable_access_control = 1`
2. user with role -> app enabled
3. user without role -> app hidden/blocked
4. denied user can still use native Stock Entry flow

- [ ] **Step 5: Final commit for any verification-related fixes**
```bash
git add -A
git commit -m "test: finalize role-only access control verification fixes"
```

## Plan Review Notes
- Intended reviewer loop: dispatch `plan-document-reviewer` subagent up to 3 iterations.
- Constraint in this session: no explicit user request for subagent delegation in this step; perform manual reviewer pass locally instead and proceed.

## Completion Criteria
- `allowed_access_rules` no longer drives access decisions.
- `required_role` drives access when `enable_access_control=1`.
- Hook/API contracts and denied-user stock-entry passthrough remain intact.
- Focused Python + JS + E2E tests pass or blockers are documented with exact causes.
- Bench15 and Bench16 manual checks confirm role-only rollout behavior.
