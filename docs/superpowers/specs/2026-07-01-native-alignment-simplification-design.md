# Design: Phased Simplification & Native Alignment — Production Entry App

Date: 2026-07-01
Author: brainstorming + grilling session (Guru107)
Source audit: `docs/frappe-erpnext-best-practices-audit.md`

## Purpose

Reduce the surface area where this app intercepts Frappe framework and ERPNext
Stock Entry internals, so the app is easier to maintain and safer to upgrade across
Frappe/ERPNext v15 and v16 — **without** rewriting validated domain behavior (the
Shift workflow and the rejection-as-quarantined-finished-goods model).

"Stay close to native" here means: shrink and pin the *necessary* interceptions,
and remove or relocate the *incidental* ones. It does **not** mean rebuilding the
rejection model.

## Scope of this spec

**Phase 1 + Phase 2 only.** Phase 3 (native-aware row-level branch permissions) is
extracted into a **separate follow-up spec** — see "Phase 3 (deferred)" stub at the
end. It is the only behavior-changing, security-sensitive part and deserves its own
review and permission E2E test.

## Locked decisions (brainstorming + grilling)

1. **Appetite: hybrid / phased.** Ship safe hardening first; remove High-risk
   override surfaces only behind a regression test net.
2. **Rejected units are quarantined finished goods** carrying full FG valuation,
   routed to a rejected warehouse. **Valuation does not require the
   `is_finished_item` flag** — a row posts to the ledger and is valued because it
   has a target warehouse. Whether the rejection row keeps `is_finished_item = 1`
   (and therefore whether the class override survives) is decided by a **spike**
   (see 2.1).
3. **Completed shifts keep accepting Stock Entries, but late entries are audited**
   via a stamped, queryable flag.
4. **Only direct manufacture-from-BOM is in scope.** No Work Order, Job Card,
   serial/batch, or process-loss flows are used today. Those get documented
   tripwire notes, not tests.
5. **Multi-branch deployment with per-branch data isolation is required** — handled
   in the deferred Phase 3 spec.

## Non-goals

- Rebuilding rejection as native scrap / quality-inspection flows.
- Removing the Shift status machine or the Shift-as-shop-floor-hub model.
- Any data migration/backfill (greenfield app; no historical data; no compat
  required).
- Regression tests for manufacturing flows not in use (serial/batch, process loss,
  Work Order, Job Card).

## Guiding principle for each finding

Classify each audited deviation:

- **Necessary domain interception** → keep, make as narrow as possible, pin native
  v15/v16 behavior with regression tests, document the exact upstream dependency
  (source file + line + version).
- **Incidental interception** → remove or relocate.

Rejected alternative: big-bang re-architecture (rejection as native scrap). Ruled
out by decision #2 — rejected units must carry FG valuation.

---

## Phase 1 — Safe hardening & cleanup

No behavior or UX change. Independently shippable. TDD per CLAUDE.md (failing test
first).

### 1.1 (Audit #8) Relocate E2E APIs out of the production API module

**Problem:** `api.py` (~1223 lines) is ~70% E2E helpers that force-delete, manually
commit, and mutate permissions, yet ship in the module the UI imports.

**Change:**
- Create `production_entry_app/production_entry_app/e2e_api.py`; move only the
  `_assert_e2e_api_allowed`-gated endpoints + their private helpers:
  `bootstrap_e2e_context`, `cleanup_e2e_context`, `cleanup_reserved_e2e_artifacts`,
  `create_e2e_submitted_stock_entry`, `create_e2e_full_shift_stock_entries`,
  `create_e2e_downtime_entry`, `set_e2e_access_control`,
  `set_e2e_system_float_precision`.
- **Keep in `api.py`** the genuine production APIs: `get_die_tool_counter`,
  `reset_die_tool_counter`, `get_access_control_state`,
  `get_shift_details_for_stock_entry`, `get_items_with_rejection`, `delete`
  (pending 2.4).
- **Update every call-site path** (no compat shims — app under development):
  ~10 Playwright specs, `tests/e2e/global-teardown.js`, `tests/e2e/fixtures/
  test-data.js`, and any Python test imports that reference
  `...api.<e2e_method>` → `...e2e_api.<e2e_method>`.
- Log a warning during `after_migrate` (or boot) when `allow_e2e_tests=1` on a site
  whose name does not look like a test/dev site.

**Tests:** full E2E + Python suites pass against the new paths; a test asserts
production `api.py` no longer imports E2E helpers.

### 1.2 (Audit #9) Declare ERPNext dependency

- `required_apps = ["erpnext"]` in `hooks.py`.
- README "Supported versions": Frappe/ERPNext v15.110+ and v16.20/16.21+.

**Test:** assert `hooks.required_apps == ["erpnext"]`.

### 1.3 (Audit #6a) Remove only app-invented unused permission params

Remove `doctype` / `docname` / `branch` from `assert_app_read_access` /
`assert_app_write_access`, and the internal `branch` params — these are
app-invented and unused (`del`-ed today).

**Do NOT touch** `has_gated_doctype_permission(doc, ptype, user, debug)` — that is
the Frappe controller-hook signature (`has_controller_permissions` calls it as
`frappe.call(method, doc=doc, ptype=ptype, user=user, debug=debug)`), and `doc` is
the seam the deferred Phase 3 uses for per-document branch checks.

**Test:** call sites pass; `assert_app_*` signatures no longer accept the removed
args; `has_gated_doctype_permission` signature unchanged.

### 1.4 (Audit #7) Make DocPerm mutation on migrate observable

`lifecycle._setup_app()` rewrites DocPerms on every sync/migrate.
- Document in README/admin docs (Role Permission Manager is not the sole source of
  truth for app DocTypes).
- Log a summary of DocPerm rows created/updated/deleted during the run.
- Opt-out setting deferred unless requested.

**Test:** summary is logged when DocPerms change.

### 1.5 (Audit #10 / #11) Create the app Workspace + fix `/app` route strings

- Create a public `Workspace` named `Production Entry App` (route slug `production-entry-app`) with two card sections — **Forms** (Stock Entry, Shift, Operator, Die Tool Counter, Die Tool Maintenance Log, Rejection Reason, Downtime Reason) and **Reports** (all 18 Shift-referenced Script Reports, ordered Efficiency → Rejection → Rework → Die Tool) — plus a **Production Entry Settings** shortcut.
- `hooks.add_to_apps_screen[0].route` → `/app/production-entry-app` (now resolves to the new workspace).
- `shift.js:385` → `frappe.utils.get_form_link("Downtime Entry", d.name)`.

**Tests:** metadata test asserts the workspace has Forms + Reports cards and 18 report links; E2E link still resolves.

### 1.6 (Audit #12) Fix `frappe_in_test()`

`compat/utils.py`:
```python
return bool(getattr(frappe.flags, "in_test", False) or getattr(frappe, "in_test", False))
```
Correct the reversed comment.

**Test:** True under both `frappe.flags.in_test` and `frappe.in_test`.

### 1.7 (Audit #13) `Rejection Reason` rename stability

Add `"allow_rename": 0` to the `Rejection Reason` DocType JSON.

**Test:** metadata test asserts `allow_rename == 0`.

---

## Phase 2 — Override hardening / removal + regression safety net

Only the direct-manufacture-from-BOM flow is exercised (decision #4). The regression
suite runs on **both** bench15 and bench16.

### 2.1 (Audit #1) SPIKE: can the Stock Entry class override be deleted?

The class override exists *only* because the rejection row carries
`is_finished_item = 1`, so native `get_finished_item_row()` (which picks the **last**
such row) would pick the rejection row. If the rejection row does not need that flag,
native picks the real FG row and the override can be deleted.

**Spike:** on bench15 AND bench16, submit a direct manufacture-from-BOM Stock Entry
with `rejection_qty > 0` where the rejection row has `t_warehouse` = rejected
warehouse and **`is_finished_item = 0`**.

**Acceptance (all four, on both benches):**
1. Validates and submits with no ERPNext error.
2. Correct SLEs: FG warehouse receives `fg_completed_qty − rejection_qty`; rejected
   warehouse receives `rejection_qty`; RM consumed from WIP; rejection qty valued
   **identically to good FG**.
3. Native `get_finished_item_row()` returns the real FG row.
4. Cancel fully reverses all SLEs.

**Outcome:**
- **Pass on both** → delete `ProductionEntryAppStockEntry` and the
  `override_doctype_class` hook; change `_append_rejection_item_row` to stop setting
  `is_finished_item = 1` on the rejection row; keep `custom_pea_is_rejection_item`
  as the detection key (removal/restore logic already keys off it and off the real
  FG row, so no other change needed).
- **Fail on either bench** (e.g. ERPNext rejects a non-finished/non-scrap produced
  row, or valuation/SLEs wrong) → keep the override; add a version-pinned comment
  citing native `get_finished_item_row` (v15 `stock_entry.py:1673`,
  v16 `:1834`) and its failure mode.

### 2.2 Regression tests (the centerpiece)

On v15 AND v16, for direct manufacture-from-BOM:
1. Manufacture-from-BOM with rejection qty → expected SLEs (FG split, rejected
   warehouse, RM consumption, valuation).
2. Clean cancellation reversal of the same entry.
3. Compatibility test (Audit #4): native `Stock Entry.get_items()` base rows equal
   `get_items_with_rejection()`'s rows **before** `_apply_rejection_entries`.

These pass regardless of the spike outcome and are the permanent upgrade tripwire.

**Tripwire notes (documented, not tested):** if serial/batch, process loss, Work
Order, or Job Card flows are ever adopted, add regression coverage before relying on
them — the rejection/FG-selection logic sits on the ledger path.

### 2.3 (Audit #2) Narrow the `fg_completed_qty` monkey-patch

Today the override fires for `manufacture + from_bom` whenever the app is enabled,
ignoring `job_card` and Shift linkage (`stock_entry.js:174-184`).

**Change** the inner guard to:
```js
if (_is_manufacture_doc(this.frm.doc)
    && this.frm.doc.from_bom
    && this.frm.doc.custom_pea_shift   // Shift-linked only
    && !this.frm.doc.job_card) {       // preserve v16 native Job Card guard
    return; // handled by Fetch Items
}
return originalFgCompletedQty.call(this);
```
Keep the `no job_card` clause even though Job Card is out of scope — it is free
insurance that preserves v16 native behavior. No dedicated Job Card test (YAGNI);
covered by a tripwire note.

**Test:** non-Shift manufacture entry keeps native auto-fetch; Shift-linked
manufacture entry suppresses it (existing Fetch Items flow still works).

### 2.4 (Audit #3) Remove the global `frappe.client.delete` override

**Feasible (verified):** in `frappe/model/delete_doc.py`, `on_trash` (line 165) runs
**before** `check_if_doc_is_linked` (line 172). Loss Entry links to Shift via a real
Link field, so cleaning orphan rows in `Shift.on_trash` runs early enough to unblock
the delete.

**Change:** move `_cleanup_orphan_stock_entry_loss_links` into `Shift.on_trash`
(register in `doc_events["Shift"]["on_trash"]`); delete the
`override_whitelisted_methods = {"frappe.client.delete": ...}` hook and the
`api.delete` wrapper.

**Fallback (only if the on_trash approach proves insufficient in practice):** keep
the override but add a compat test proving a non-PEA DocType delete delegates
byte-for-byte to native, plus an app-order note.

**Tests:** deleting a Shift with orphaned Stock Entry loss links still cleans up and
succeeds; deleting a non-PEA DocType behaves exactly like native.

### 2.5 (Audit #5) Audit late (post-completion) Stock Entries

Keep the `("Running", "Completed")` allow-list. Close the silent-mutation gap:
- Add a `custom_pea_is_late_entry` **Check** custom field (fixture,
  `custom_pea_` prefix) on Stock Entry.
- Stamp it `1` in `on_submit` when the linked shift's status is **`Completed` at
  submit time** (status-at-submit, independent of buffer windows).
- Surface a "late entries" count/line in the Shift summary (simple query on the
  flag).

**Tests:** entry submitted against a Completed shift is flagged and appears in the
summary; entry against a Running shift is not flagged.

---

## Consciously accepted deviations (documented, not changed)

- Shift as shop-floor hub with a custom status machine.
- Rejection modeled as an appended FG-valued row to a rejected warehouse (with or
  without `is_finished_item`, per spike).
- fg_completed_qty auto-fetch suppressed for Shift-linked manufacture in favor of
  explicit Fetch Items (now narrowed in 2.3).

Each gets a short "why" note in README.

## Testing & coverage

- TDD throughout; coverage stays ≥ 90%.
- Phase 2's v15/v16 regression suite must pass on both benches before any override
  change (delete or harden) is considered done.
- E2E specs (happy / validation) for the late-entry audit (2.5).

## Sequencing & shippability

- **PR A — Phase 1:** all mechanical/safe items together (no behavior risk).
- **Spike:** throwaway investigation on both benches; records the 2.1 outcome.
- **PR B — Phase 2:** override change (delete or harden per spike) + regression
  suite + 2.3 + 2.4 + 2.5, each behind its tests.
- **Later — Phase 3 spec/PR:** branch isolation (separate spec).

## Phase 3 (deferred — separate spec)

**Requirement:** multi-branch deployment; a user scoped to Branch A must not read or
aggregate Branch B's Shift/Stock Entry data. `branch` is a required field on both
Shift and Stock Entry, so filtering is reliable.

**Key constraint:** native `permission_query_conditions` / User Permissions only
auto-filter `frappe.get_list` and standard list views. This app's reports and
aggregate APIs use `frappe.qb` / `frappe.get_all`, which **bypass** them. So branch
isolation must be applied **explicitly** in each cross-branch aggregate/report/
timeline query.

**Planned shape:**
- Set Branch User Permissions on users (native data-model enforcement for list
  views and single-doc reads via the `has_gated_doctype_permission` `doc` seam).
- Add a shared `get_permitted_branches(user)` helper and apply
  `WHERE branch IN (...)` in every custom `qb`/`get_all` aggregate query
  (`report_utils.py`, `api_timeline.py`, whitelisted metric APIs).
- Keep the role gate as coarse allow/deny; layer branch filtering on top.
- Permission E2E test: Branch-A user cannot read Branch-B aggregates.

## Open items to confirm before implementation

- Exact wording/location of the Shift-summary "late entries" line (2.5).
- Confirm the spike outcome before finalizing PR B's override direction (2.1).
