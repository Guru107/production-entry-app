# Design: Phased Simplification & Native Alignment — Production Entry App

Date: 2026-07-01
Author: brainstorming session (Guru107)
Source audit: `docs/frappe-erpnext-best-practices-audit.md`

## Purpose

Reduce the surface area where this app intercepts Frappe framework and ERPNext
Stock Entry internals, so the app is easier to maintain and safer to upgrade across
Frappe/ERPNext v15 and v16 — **without** rewriting validated domain behavior (the
Shift workflow and the rejection-as-quarantined-finished-goods model).

"Stay close to native" here means: shrink and pin the *necessary* interceptions,
and remove or relocate the *incidental* ones. It does **not** mean rebuilding the
rejection model.

## Locked product decisions (from brainstorming)

1. **Appetite: hybrid / phased.** Ship safe hardening first; only remove High-risk
   override surfaces behind a regression test net.
2. **Rejection model: rejected units are quarantined finished goods.** They carry
   full FG valuation and move to a rejected warehouse. Therefore rejection rows
   **must remain `is_finished_item` stock-ledger rows**. Consequence: the
   `ProductionEntryAppStockEntry` class override and `get_items_with_rejection()`
   are **kept and hardened**, not removed.
3. **Completed shifts keep accepting Stock Entries, but late entries are audited.**
   Post-completion entry stays a supported workflow; the gap to close is the
   *silent* mutation of a "closed" shift.

## Non-goals

- Rebuilding rejection as native scrap / quality-inspection flows.
- Removing the Shift status machine or the Shift-as-shop-floor-hub model.
- Any data migration/backfill (greenfield app; no historical data to preserve).

## Guiding principle for each finding

For every deviation the audit flagged, classify it:

- **Necessary domain interception** (rejection FG-row selection, item fetch,
  fg_completed_qty UX) → keep, but make it as narrow as possible, pin native
  v15/v16 behavior with regression tests, and document the exact upstream
  dependency (source file + line + version).
- **Incidental interception** (global `frappe.client.delete` override, misleading
  permission parameters, E2E helpers living in the production API module) → remove
  or relocate.

Rejected alternative: the big-bang re-architecture (model rejection natively as
scrap). Ruled out by decision #2 — rejected units must carry FG valuation, which
native scrap handling does not preserve.

---

## Phase 1 — Safe hardening & cleanup

No behavior or UX change. Independently shippable. Each item is TDD'd (failing test
first) per CLAUDE.md.

### 1.1 (Audit #8) Relocate E2E APIs out of the production API module

**Problem:** `production_entry_app/production_entry_app/api.py` is ~1223 lines and
roughly 70% E2E helpers (`bootstrap_e2e_context`, `cleanup_e2e_context`,
`cleanup_reserved_e2e_artifacts`, `create_e2e_submitted_stock_entry`,
`create_e2e_full_shift_stock_entries`, `create_e2e_downtime_entry`,
`set_e2e_access_control`, `set_e2e_system_float_precision`, and their private
helpers). These force-delete, manually commit, and mutate permissions, yet ship in
the same module the UI imports.

**Change:**
- Create `production_entry_app/production_entry_app/e2e_api.py` and move all
  E2E-only whitelisted endpoints + their private helpers there.
- Keep the existing double gate (`_assert_e2e_api_allowed`) with each endpoint.
- Preserve any import paths the Playwright specs / Python tests depend on by
  re-exporting from `e2e_api` (verify against `tests/e2e` and `test_api.py` first;
  update call sites rather than leaving shims if the app-under-development rule
  allows — no compatibility required).
- Add a boot-time (or `after_migrate`) warning logged when `allow_e2e_tests=1` is
  set on a site whose name does not look like a test/dev site.

**Tests:** existing E2E + Python suites must pass unchanged against the new module
path; add a test asserting the production `api.py` no longer imports E2E helpers.

### 1.2 (Audit #9) Declare ERPNext dependency

- Set `required_apps = ["erpnext"]` in `hooks.py`.
- Add a "Supported versions" section to README: Frappe/ERPNext v15.110+ and
  v16.20/16.21+ (as tested in the local benches).

**Test:** assert `hooks.required_apps == ["erpnext"]`.

### 1.3 (Audit #6a) Remove misleading unused permission parameters

`access_control.assert_app_read_access()`, `assert_app_write_access()`, and
`has_gated_doctype_permission()` accept `doctype` / `docname` / `branch` / `doc` /
`debug` and then `del` them. Remove the dead parameters and update call sites.
(Real row-level filtering is Phase 3; this is pure cleanup so the signatures stop
implying behavior that does not exist.)

**Test:** call-site tests still pass; signature no longer accepts the removed args.

### 1.4 (Audit #7) Make DocPerm mutation on migrate observable

`lifecycle._setup_app()` rewrites DocPerms on every `after_sync` / `after_migrate`.
- Document this clearly in README / admin docs (Role Permission Manager is not the
  sole source of truth for app DocTypes).
- Emit a `frappe.log` / info comment summarizing which DocPerm rows were
  created/updated/deleted during the run, so the change is not silent.
- (Opt-out setting `manage_native_permissions` is **deferred** unless requested.)

**Test:** assert the summary is logged when DocPerms change.

### 1.5 (Audit #10 / #11) Fix `/app` route strings

- `hooks.add_to_apps_screen[0].route`: point to the app's workspace/module route
  instead of generic `/app`.
- `shift.js:385`: replace the hardcoded
  `` `/app/downtime-entry/${...}` `` anchor with
  `frappe.utils.get_form_link("Downtime Entry", d.name)`.

**Tests:** JS unit/assertion where feasible; E2E link click still resolves.

### 1.6 (Audit #12) Fix `frappe_in_test()` helper

In `compat/utils.py`, use a version-agnostic fallback and correct the reversed
comment:

```python
return bool(getattr(frappe.flags, "in_test", False) or getattr(frappe, "in_test", False))
```

**Test:** helper returns True under both `frappe.flags.in_test` and `frappe.in_test`.

### 1.7 (Audit #13) `Rejection Reason` rename stability

Add `"allow_rename": 0` to the `Rejection Reason` DocType JSON, matching the other
fixture-installed master DocTypes.

**Test:** metadata test asserts `allow_rename == 0`.

---

## Phase 2 — Override hardening + regression safety net

The High-severity findings, made *safe* rather than removed. This phase's
regression suite is the permanent upgrade tripwire the audit asks for.

### 2.1 (Audit #1) Keep and pin the Stock Entry class override

`ProductionEntryAppStockEntry.get_finished_item_row()` stays — it is the minimal
correct mechanism to keep the real FG row (not the rejection row) winning native
selection, given decision #2.

**Changes:**
- Add a version-pinned comment citing native `get_finished_item_row`:
  v15 `stock_entry.py:1673`, v16 `stock_entry.py:1834`, and the failure mode if
  upstream changes (e.g. multi-FG or bundle handling).

**Regression tests (v15 AND v16), the centerpiece of the plan:**
1. Manufacture-from-BOM with rejection qty → expected Stock Ledger Entries.
2. Clean cancellation reversal of the same entry.
3. Process loss + rejection qty together.
4. Serial/batch-tracked FG item with rejection qty.
5. Work Order manufacture with rejection qty.

### 2.2 (Audit #4) Pin `get_items_with_rejection()` as an intentional fork

Keep the reconstructed-document item-fetch API. Add a compatibility test asserting
that native `Stock Entry.get_items()` base rows match the API's pre-rejection rows
(before `_apply_rejection_entries`) on both v15 and v16. Document it as an
intentional fork of the item-fetch UX.

### 2.3 (Audit #2) Narrow the `fg_completed_qty` monkey-patch

`public/js/stock_entry.js` currently suppresses native `get_items()` for
manufacture + `from_bom` regardless of `job_card`, which does not preserve v16's
native Job Card guard.

**Change:** narrow `_should_override_fg_completed_qty()` so the override fires only
when the doc is **Shift-linked + app-enabled + has no `job_card`**. Otherwise
delegate to the native prototype method.

**Optional:** evaluate replacing the prototype patch with a form-event handler /
button-only flow; adopt **only** if genuinely cleaner, else keep the narrowed patch.

**Tests:** v16 Job Card Stock Entry test asserting native item-fetch is unchanged;
existing manufacture-fetch flow still works.

### 2.4 (Audit #3) Try to remove the global `frappe.client.delete` override

**Preferred:** move the orphan `Loss Entry` link cleanup
(`_cleanup_orphan_stock_entry_loss_links`) into `Shift.on_trash` (a
Stock-Entry-side `on_trash` cleanup already exists), and drop the
`override_whitelisted_methods` entry entirely.

**Fallback (only if link-validation timing makes on_trash cleanup impossible):**
keep the override but add a compatibility test proving a **non-PEA** DocType delete
delegates byte-for-byte to native `frappe.client.delete_doc`, plus an app-order
note in code + README.

**Tests:** deleting a Shift with orphaned Stock Entry loss links still cleans up;
deleting a non-PEA DocType behaves exactly like native.

### 2.5 (Audit #5) Audit late (post-completion) Stock Entries

Keep the `("Running", "Completed")` allow-list. Close the silent-mutation gap:
- Stamp/flag Stock Entries submitted against a **Completed** shift (e.g. a
  `custom_pea_is_late_entry` marker or a recorded timestamp/comment).
- Surface a "late entries" line/count in the Shift summary so supervisors see
  post-completion changes.

**Tests:** entry against a Completed shift is flagged and appears in the summary;
entry against a Running shift is not flagged.

---

## Phase 3 — Native-aware permissions (highest effort; do last)

### 3.1 (Audit #6b) Row-level filtering via native User Permissions

For whitelisted list/aggregate APIs, apply `permission_query_conditions` or use
`frappe.get_list` so native **User Permissions** (Branch/Department) perform
row-level filtering, instead of role-only gates. This is the most native-aligned
change and the most behavior-affecting, so it is isolated and sequenced last.

**Tests:** a non-admin user restricted to one Branch cannot read/aggregate another
Branch's Shift/Stock Entry data through the whitelisted APIs.

---

## Consciously accepted deviations (documented, not changed)

- Shift as shop-floor hub with a custom status machine (vs native Work
  Order/Job Card as primary execution records).
- Rejection modeled as an appended `is_finished_item` FG-valued row in a rejected
  warehouse.
- fg_completed_qty auto-fetch suppressed in favor of explicit Fetch Items (now
  narrowed in 2.3).

Each gets a short "why" note in README so future maintainers know these are product
decisions, not oversights.

## Testing & coverage

- TDD throughout: failing test first, then implementation (CLAUDE.md mandate).
- Coverage stays ≥ 90%.
- Phase 2's v15/v16 regression suite is the upgrade safety net; it must pass on both
  benches before any override change is considered done.
- E2E specs (happy / validation / permission) for the late-entry audit (2.5) and the
  permission change (3.1).

## Sequencing & shippability

Phase 1 → Phase 2 → Phase 3, each independently shippable. Phase 1 carries no
behavior risk. Phase 2 changes are each gated behind their regression tests. Phase 3
is separable and can be deferred without blocking Phases 1–2.

## Open items to confirm before implementation

- Exact marker mechanism for late entries in 2.5 (new custom field vs comment/log).
- Whether 2.3 adopts the form-event replacement or the narrowed monkey-patch
  (decided during implementation based on which is cleaner).
- Feasibility of the 2.4 preferred path (on_trash cleanup) vs the documented
  fallback.
