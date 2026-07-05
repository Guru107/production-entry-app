# Design: Phase 3 — Native Permissions & Branch Isolation

Date: 2026-07-05
Author: brainstorming session (Guru107)
Predecessor: `docs/superpowers/specs/2026-07-01-native-alignment-simplification-design.md` (Phase 1 + Phase 2, merged)

## Purpose

Finish the native-alignment effort by making **Frappe own all access control**. Two
moves, both in the "stay native / delete custom logic" spirit of Phases 1–2:

1. **Branch isolation** via native Frappe **User Permissions** on Branch — no custom
   permission code.
2. **Delete the app's entire custom access-control / role-management layer** and rely
   on native Roles + DocPerms + permlevel field permissions + User Permissions.

The guiding rule: if Frappe already provides a mechanism, use it and delete the
app's parallel implementation.

## Locked decisions (from brainstorming)

1. **Branch on Stock Entry is a real, persisted field** — added idempotently, only if
   a `branch` field does not already exist (some sites already have one; reuse it).
2. **Native Frappe ACL semantics** — "unrestricted until restricted": a user with no
   Branch User Permission sees all branches; one or more Branch User Permissions
   restrict them to those. No deny-by-default, no custom logic.
3. **Reports and the timeline may stay cross-branch visible.** They use
   `frappe.qb` / `frappe.get_all`, which Frappe deliberately exempts from permissions
   (`get_all` docstring: *"Will not check for permissions"*). Isolating them would
   require custom filtering, which is explicitly **not wanted**. List views, forms,
   and single-doc reads are isolated for free by native User Permissions — that is
   sufficient.
4. **Fixed native roles, always gated.** Remove the runtime-configurable
   `write_role` / `read_role` and the `enable_access_control` toggle. Gating is the
   native DocPerms on `PEA User` / `PEA Read Only`. No "open to everyone" bypass.
5. **Keep permlevel-9 field hiding**, expressed as static native config (permlevel on
   the fields + static Custom DocPerm rows), not programmatic per-migrate sync.
6. **Follow Frappe best practice for endpoint gating, using native APIs only.**
   Read endpoints replace the custom assert with a native `frappe.has_permission`
   check where they return document-scoped data (trivial global lookups may stay
   open). Write endpoints are gated **natively** by document-operation DocPerm checks
   (drop the `ignore_permissions` that masks them). E2E helpers keep their existing
   double gate. Role assignment is a **manual admin/deployment step** — the app never
   auto-grants roles.

## Non-goals

- Custom branch filtering of reports/timeline (decision #3).
- Any runtime-configurable permission behavior (decision #4).
- Data migration/backfill (greenfield app).
- Touching the Phase 1/2 behavior already merged.

---

## Part A — Branch isolation (native User Permissions)

### A.1 Persisted `branch` on Stock Entry (idempotent)

**Problem:** Stock Entry has no `branch` field or column (verified against the live
v16 meta). The existing `doc.branch = shift.branch` in
`overrides/stock_entry_hooks.py` writes to a phantom attribute that never persists.
Shift already has a reqd `branch` Link→Branch.

**Change:**
- Add `ensure_stock_entry_branch_field()` to `lifecycle.py`, called from
  `_setup_app()`. It checks `frappe.get_meta("Stock Entry").has_field("branch")` and
  creates a Custom Field `branch` (Link → Branch) on Stock Entry **only if absent** —
  so sites that already have a `branch` field (native or from another app) reuse it,
  no duplicate. Name is `branch` (not `custom_pea_branch`) so it coincides with any
  existing field and matches Shift + ERPNext's branch dimension.
- The population line becomes a real write, guarded by `meta.has_field("branch")` so
  it is safe on every site.
- Non-production Stock Entries (no linked Shift) get an empty `branch`; native User
  Permissions ignore empty Link fields, so those entries stay visible to everyone —
  isolation applies to production entries only, as intended.

**Tests:** `ensure_stock_entry_branch_field` is idempotent (no-op when a `branch`
field already exists; creates it when absent); a saved production Stock Entry has
`branch` == its Shift's branch.

### A.2 Native branch isolation

No app code. Once Branch User Permissions are assigned to a user, native Frappe
filters:
- **Shift** list/form/reports — via its native `branch` field.
- **Stock Entry** list/form — via the new `branch` field.
- Single-doc reads that already call `frappe.has_permission` (e.g.
  `get_shift_summary`) — respected automatically.

**Tests (E2E):** a user with a Branch-A User Permission sees only Branch-A Shifts and
Stock Entries in list views; Branch-B rows are hidden. A user with no Branch User
Permission sees all branches.

**Dependency (document, don't enforce):** this relies on System Settings
`apply_strict_user_permissions` being **OFF** (verified OFF on the bench). With it
OFF, Stock Entries with an empty `branch` (non-production entries — material
transfers, etc.) stay visible to branch-restricted users. If an admin turns strict
mode ON, those empty-branch entries would be hidden from restricted users — a native
Frappe consequence outside the app's control; note it in admin docs.

---

## Part B — Delete the custom access-control layer

The custom layer duplicates the role check the native DocPerms already encode. All 7
app doctype JSONs already carry complete DocPerms for `System Manager`, `PEA User`,
`PEA Read Only`.

### B.1 Remove (redundant with native)

- Modules: `production_entry_app/production_entry_app/access_control.py`,
  `field_permissions.py`, `access_control_field_map.py`,
  `scripts/build_access_control_field_map.py`.
- Hooks: the `has_permission` map for the 7 doctypes (`hooks.py`), and the
  app-screen tile `has_permission`.
- Controller: `Shift.has_permission`.
- API: `get_access_control_state` and its callers; `report_utils.assert_report_read_access`
  and its ~20 report call sites; every `assert_app_read_access` /
  `assert_app_write_access` / `assert_app_access` / `can_use_/can_write_/can_read_production_entry_app`
  call in `api.py`, `api_timeline.py`, `shift.py`, `overrides/stock_entry_hooks.py`.
- JS: `access_control.js`, `custom_field_visibility.js`,
  `generated_access_control_field_map.js`, and their `hooks.py`
  `app_include_js` / `app_include_css` entries.
- Lifecycle: strip `_setup_app()` to `performance_indexes.ensure_performance_indexes_with_recovery()`
  only (drop the role/DocPerm and permlevel-9 sync calls). Remove the Phase 1
  DocPerm-reconciliation log line — it describes the sync being deleted, so nothing
  is left to reconcile.
- Settings: remove `write_role`, `read_role`, `enable_access_control` (and any
  `last_synced_*_role`) fields from Production Entry Settings.

### B.2 Replace with native static config

- **Role fixtures:** ship `PEA User` and `PEA Read Only` as `Role` fixtures (they were
  auto-created by the deleted `_ensure_role`).
- **Doctype DocPerms:** already present in the 7 app doctype JSONs — no change.
- **Permlevel-9 field permissions:** keep permlevel 9 on the 43 custom fields and
  grant the permlevel access via a **native Frappe mechanism** (not a bespoke sync).
  Three permlevel-9 permission rows per affected standard doctype (Stock Entry,
  Stock Entry Detail, Item, Workstation, Downtime Entry):
  - `PEA User` — read **+ write** (enters/edits the fields),
  - `PEA Read Only` — read only (**sees** the fields, cannot edit),
  - `System Manager` — read + write (admin safety; without this row a fresh SM
    silently cannot see the app's custom fields — permlevels do not inherit to SM).

  Net effect: the fields are hidden only from users holding **none** of these roles.

**Permlevel mechanism (follow Frappe best practice, no custom permission code):**
prefer **`Custom DocPerm` fixtures** in `hooks.py`, scoped by filter
(`parent in (the 5 doctypes)` and `permlevel = 9`) so ERPNext's own Item permlevel-1
perms and other apps' rows are not swept in. **Spike this first** on both benches: if
the fixtures install/round-trip cleanly, use them (zero code). If they prove
unreliable across v15/v16, fall back to a one-time **declarative** setup step calling
Frappe's official `frappe.permissions.add_permission(doctype, role, permlevel=9)` API
(a static `{doctype, role, ptype}` table upserted in lifecycle). Both are native
Frappe mechanisms; neither is the runtime-configurable sync engine being deleted. Also
ship `Role` fixtures for `PEA User` / `PEA Read Only`.

---

## Part C — Endpoint gating

- **Read endpoints:** drop the *custom* `assert_app_read_access`, but follow Frappe
  best practice — a whitelisted method returning a specific document's data should
  gate on **native `frappe.has_permission(doctype, "read", name)`**:
  - Document-scoped readers (`get_shift_summary`, `get_shift_details_for_stock_entry`,
    `get_shift_aggregate_production_entries`, `get_linked_downtime_entries`,
    `get_shift_timeline_data`) → keep/add a native `frappe.has_permission` check. The
    first two already have it (just delete the redundant custom assert). This also
    keeps API reads consistent with Branch User Permission isolation (a Branch-A user
    can't pull a Branch-B shift's summary).
  - Trivial global lookups with no document-scoped permission to check
    (`get_die_tool_counter` by item code) → may stay open.
  - The 20 Script Reports → native Report `roles` already gate who can open them;
    delete `assert_report_read_access`, add nothing.
- **Write endpoints** (`reset_die_tool_counter`, and any mutating whitelisted
  method): drop the custom write assert and remove `ignore_permissions=True` from the
  production write path so the native DocPerm check on `insert`/`save`/`submit`/`delete`
  gates it (`PEA Read Only` blocked, `PEA User` allowed).
- **E2E helpers** (`e2e_api.py`): keep the `Administrator + developer_mode +
  allow_e2e_tests` gate. Rework any `sync_configured_access_roles` usage to assign
  native roles directly (`frappe`'s role add/remove) in test setup.

---

## Part D — Testing

- **Branch isolation (E2E):** Branch-A-restricted user sees only Branch-A Shifts +
  Stock Entries in list views; Branch-B hidden; unrestricted user sees all.
- **Branch field (unit):** `ensure_stock_entry_branch_field` idempotency (present →
  no-op; absent → created); production Stock Entry `branch` == Shift branch;
  non-production entry `branch` empty.
- **Native perms (unit/E2E):** `PEA User` can CRUD the 7 app doctypes; `PEA Read Only`
  can read but not write; permlevel-9 custom fields not visible/editable to
  `PEA Read Only`; write endpoint blocked for `PEA Read Only`, allowed for `PEA User`.
- **Regression:** full v15 + v16 suite green; coverage ≥ 90%. Rewrite the access-control
  test modules (`test_access_control*.py`, `test_field_permissions.py`,
  `test_permission_hooks.py`) — delete those covering removed custom logic; add tests
  asserting native DocPerms/User-Permissions enforce the same outcomes.

---

## Sequencing (PR boundaries)

Independent, each shippable:
- **PR 1 — Part A:** Stock Entry `branch` field + native branch isolation + tests.
  Low risk, additive.
- **PR 2 — Part B/C:** delete the custom access-control layer + native config + endpoint
  gating + test rewrite. Larger; lands only after its native-perm test suite is green
  on both benches.

Part A does not depend on Part B; do A first so branch isolation ships even if B needs
iteration.

## Consciously accepted outcomes

- Reports/timeline remain cross-branch visible (decision #3).
- The app is always role-gated; no "open to everyone" mode (decision #4).
- Gating roles are fixed (`PEA User` / `PEA Read Only`); re-pointing them is done in
  Role Permission Manager, not via Settings (decision #4).

## Rollout note (admin docs)

After this lands the app is **always role-gated** (no open mode). Assign `PEA User`
(create/edit) or `PEA Read Only` (view) to every user who needs the app; `System
Manager` retains full access via native DocPerms. The app does **not** auto-assign
roles. Greenfield app → no existing population to migrate; the only action is
"assign the role at setup." Dev/E2E bootstrap assigns roles explicitly.

## Open items to confirm before implementation

- Whether Custom DocPerm fixtures install cleanly on both benches, or the idempotent
  `ensure_permlevel_permissions()` fallback is needed (B.2).
- Exact list of write endpoints that carry `ignore_permissions=True` in production
  paths (enumerate during implementation; E2E paths keep it).
