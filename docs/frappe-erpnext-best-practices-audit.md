# Frappe / ERPNext Best-Practices Audit — Production Entry App

Date: 2026-07-01  
Scope: `/root/workspace/production-entry-app` against local benches:

- Frappe/ERPNext v15: `/root/workspace/bench15` — Frappe `15.110.0`, ERPNext `15.110.0`
- Frappe/ERPNext v16: `/root/workspace/bench16` — Frappe `16.20.0`, ERPNext `16.21.1`

Reference material consulted:

- Karpathy LLM wiki: `frappe-best-practices`, `frappe-hooks-system`, `frappe-permissions-and-roles-deep`, `frappe-v15-to-v16-migration`, `erpnext-best-practices`, `erpnext-manufacturing`, `erpnext-manufacturing-work-orders-and-job-cards`
- Native source in both benches: `frappe/frappe/client.py`, `erpnext/stock/doctype/stock_entry/stock_entry.py`, `erpnext/stock/doctype/stock_entry/stock_entry.js`
- App source: hooks, API, Stock Entry override/hooks, access control, lifecycle, fixtures, DocTypes, JS assets

## Executive summary

The app is not a thin Frappe/ERPNext extension. It deliberately changes native Stock Entry manufacturing behaviour to support a shop-floor Shift workflow, rejection quantity split, die-tool counters, operator/workstation tracking, planned/unplanned losses, and E2E automation. Some of that is valid domain customisation. The main risks are concentrated around **native Stock Entry override surfaces**, **global API override of `frappe.client.delete`**, **custom permission gates that can diverge from native row-level/user-permission behaviour**, and **test/E2E APIs living in production import paths**.

No raw SQL anti-pattern was found in production app code. The app generally uses `frappe.qb`, DocPerms, server-side validation, translation wrappers, and explicit JS error callbacks. So the base engineering hygiene is decent. The deviations below are the upgrade/behaviour-risk items worth fixing or consciously accepting.

Severity key:

- **High** — can break native ERPNext behaviour, security semantics, upgrades, or data integrity.
- **Medium** — maintainability or compatibility risk; likely to bite during v16+ upgrades or real permission setups.
- **Low** — cleanup / convention gap.

---

## Findings

### 1. High — Full `override_doctype_class` on `Stock Entry` changes ERPNext’s core stock ledger path

**App code**

- `production_entry_app/hooks.py:161-163`

```python
override_doctype_class = {
	"Stock Entry": "production_entry_app.production_entry_app.overrides.stock_entry.ProductionEntryAppStockEntry"
}
```

- `production_entry_app/production_entry_app/overrides/stock_entry.py:7-15`

```python
class ProductionEntryAppStockEntry(StockEntry):
	"""Keep custom rejection rows out of ERPNext's primary FG-row selection."""

	def get_finished_item_row(self) -> StockEntryDetail | None:
		if self.purpose in ("Manufacture", "Repack"):
			for row in self.get("items"):
				if row.is_finished_item and not row.get("custom_pea_is_rejection_item"):
					return row

		return super().get_finished_item_row()
```

**Native v15/v16 behaviour**

Both v15 and v16 native ERPNext select the **last** row where `is_finished_item` is true:

- v15 `stock_entry.py:1673-1680`
- v16 `stock_entry.py:1834-1841`

```python
def get_finished_item_row(self):
	finished_item_row = None
	if self.purpose in ("Manufacture", "Repack"):
		for d in self.get("items"):
			if d.is_finished_item:
				finished_item_row = d

	return finished_item_row
```

**Deviation**

The app selects the **first non-rejection FG row** instead of the native last FG row. That is intentional for the app’s rejection-row model, but this method feeds the stock ledger generation path (`update_stock_ledger` calls `get_finished_item_row`). This is therefore a core valuation / ledger coupling point, not just display logic.

**Why it matters**

ERPNext best practice is to prefer extension points over replacing core class behaviour. `override_doctype_class` is valid Frappe API, but for ERPNext stock ledgers it is high blast-radius. Any upstream change in `get_finished_item_row`, SLE dependency wiring, multi-FG validation, serial/batch bundle handling, process loss, or landed-cost integration can be bypassed or subtly altered.

**v15/v16 status**

- v15 and v16 native method body is currently equivalent for this method.
- v16 `update_stock_ledger` signature adds `via_landed_cost_voucher`; the app override does not touch this directly, but it still changes the row passed into v16’s native ledger logic.

**Recommendation**

Keep this override only if rejection rows must be stock-ledger rows marked `is_finished_item`. Otherwise prefer one of these lower-risk designs:

1. Model rejection as a separate transfer/scrap/material-receipt row that does **not** compete with native FG row selection.
2. Avoid marking rejection row as `is_finished_item` if native validation/valuation allows it.
3. If override remains, add explicit upgrade tests around:
   - v15/v16 stock ledger entries for manufacture with rejection row
   - process loss
   - serial/batch bundles
   - work order manufacture
   - landed cost voucher path in v16
   - cancellation reversal

---

### 2. High — Client-side monkey patch suppresses native `fg_completed_qty()` behaviour and partially ignores v16’s Job Card guard

**App code**

- `production_entry_app/public/js/stock_entry.js:163-185`

```javascript
// Suppress ERPNext's auto-populate on fg_completed_qty change for Manufacture
// entries so the user can set both Qty to Manufacture and Rejection Qty before
// explicitly clicking "Fetch Items".
// Depends on ERPNext v15/v16 `erpnext.stock.StockEntry.prototype.fg_completed_qty`
...
erpnext.stock.StockEntry.prototype.fg_completed_qty = function () {
	if (!_should_override_fg_completed_qty()) {
		return originalFgCompletedQty.call(this);
	}
	if (_is_manufacture_doc(this.frm.doc) && this.frm.doc.from_bom) {
		// Skip the standard get_items() call for Manufacture; handled by Fetch Items.
		return;
	}
	return originalFgCompletedQty.call(this);
};
```

**Native behaviour**

- v15 `stock_entry.js:1360-1362`:

```javascript
fg_completed_qty() {
	this.get_items();
}
```

- v16 `stock_entry.js:1415-1419`:

```javascript
fg_completed_qty() {
	if (!this.frm.doc.job_card) {
		this.get_items();
	}
}
```

**Deviation**

The app globally modifies the ERPNext `StockEntry` prototype for all loaded Stock Entry forms. It suppresses native `get_items()` for manufacture + BOM and replaces it with the app’s explicit `custom_pea_fetch_items` flow.

This is a known intentional deviation, but v16 added a native `job_card` guard. The app’s override does not preserve the exact v16 condition when `_should_override_fg_completed_qty()` is true; it returns early for manufacture/from_bom regardless of `job_card` state.

**Why it matters**

Prototype monkey-patching is one of the most fragile frontend extension patterns. It depends on ERPNext internals, load order, method names, and semantic stability. It also changes user expectations: native Qty to Manufacture no longer auto-refreshes BOM items.

**Recommendation**

- Keep the override behind a very narrow predicate: Shift-linked + app-enabled + no `job_card`, not just manufacture/from_bom.
- Add a v16-specific E2E/unit test asserting Job Card Stock Entry behaviour is not changed.
- Consider replacing monkey patch with a form event handler or custom button-only flow that does not replace the native prototype.
- Keep the comment, but expand it with exact upstream source line/version expectations and a failure-mode note.

---

### 3. High — Global override of `frappe.client.delete` changes a framework API for all doctypes

**App code**

- `production_entry_app/hooks.py:203-205`

```python
override_whitelisted_methods = {
	"frappe.client.delete": "production_entry_app.production_entry_app.api.delete",
}
```

- `production_entry_app/production_entry_app/api.py:149-158`

```python
@frappe.whitelist(methods=["DELETE", "POST"])
def delete(doctype: str, name: str) -> None:
	"""Delete wrapper that cleans orphan Shift loss links before link validation."""
	if doctype == "Shift":
		access_control.assert_app_write_access(doctype="Shift", docname=name)
	elif doctype in _APP_GATED_DOCTYPES:
		access_control.assert_app_write_access()
	if doctype == "Shift":
		_cleanup_orphan_stock_entry_loss_links(name)
	frappe_client_delete_doc(doctype, name)
```

**Native v15/v16 behaviour**

Both v15 and v16 `frappe.client.delete_doc` handle child-table deletion through the parent and otherwise call `frappe.delete_doc(doctype, name, ignore_missing=False)`.

**Deviation**

The implementation delegates to native delete after app-specific cleanup, so the functional delta is narrow. But the override is global: every client delete call for every DocType now passes through app code. This is higher blast radius than a DocType-specific delete button/hook.

**Why it matters**

Frappe best practice is to use targeted hooks where possible. Global whitelisted method overrides can conflict with other apps, depend on app ordering, and surprise future maintainers. If another app also overrides `frappe.client.delete`, only one wins.

**Recommendation**

Prefer a targeted cleanup strategy:

- `Shift.on_trash` / `before_trash` style cleanup if link validation timing allows it.
- A dedicated Shift delete API/button only for Shift UI.
- A scheduled/maintenance cleanup for orphan `Loss Entry` rows if they are purely derived.

If the global override remains, document the app-order dependency and add a compatibility test verifying non-PEA DocType deletion still exactly delegates to native semantics.

---

### 4. High — `get_items_with_rejection()` duplicates ERPNext Stock Entry item-fetch flow and bypasses native client expectations

**App code**

- `production_entry_app/production_entry_app/api.py:209-248`

The API accepts a browser doc, creates a clean `Stock Entry`, calls `se.get_items()`, then applies PEA rejection rows and returns stripped child-row data.

**Deviation**

Native ERPNext client calls the document method `get_items()` through `this.frm.call({ doc: me.frm.doc, method: "get_items" ... })`. The app replaces this with a separate whitelisted API and a reconstructed document.

**Why it matters**

The reconstructed document may miss fields that upstream ERPNext later expects. v15 and v16 already differ in Stock Entry client/server flows around Job Cards and other manufacturing additions. This also means upstream `get_items()` client callback behaviour is bypassed except for what the app reimplements.

**Recommendation**

- Treat this as an intentional fork of the Stock Entry item-fetch UX.
- Add a compatibility test that compares native `frm.call/get_items` output vs `get_items_with_rejection()` base rows before rejection mutation for both v15 and v16.
- Add explicit coverage for Work Order, Job Card, process loss, multi-level BOM, alternative items, serial/batch bundle items, and subcontracting-related fields if those flows are in scope.

---

### 5. Medium — Shift allows linking Stock Entries to `Completed` shifts, deviating from live execution semantics

**App code**

- `production_entry_app/production_entry_app/api.py:58` and `overrides/stock_entry_hooks.py:47` use:

```python
_ALLOWED_STOCK_ENTRY_SHIFT_STATUSES = ("Running", "Completed")
```

- `stock_entry.js:205-209` filters Shift link choices to Running or Completed.

**Deviation**

This is an app-level post-facto-entry design, not native ERPNext behaviour. ERPNext manufacturing typically models execution through Work Orders / Job Cards / Stock Entries without a custom Shift state machine. Allowing Completed shifts to accept entries may be operationally useful, but it weakens the semantic meaning of Completed unless tightly audited.

**Why it matters**

Completed usually means closed for mutation. Post-completion Stock Entries can alter shift summary, OEE, rejection totals, die-tool strokes, and reports after supervisors believe a shift is closed.

**Recommendation**

- If post-facto entries are required, add an explicit `allow_post_completion_entries` setting, reason/comment requirement, and audit trail.
- Consider restricting normal users to Running only and allowing Completed only to Manufacturing Manager/System Manager.
- Report any late entries visibly in Shift summary.

---

### 6. Medium — Custom permission gate ignores document context / branch parameters and may diverge from native User Permissions

**App code**

- `access_control.assert_app_read_access()` and `assert_app_write_access()` accept `doctype`, `docname`, and `branch` but delete them:

```python
del doctype, docname, branch
```

- `has_gated_doctype_permission()` also deletes `doc` and `debug`, then checks only app read/write roles.

**Deviation**

Frappe permission best practice is to use native roles and User Permissions for row-level filtering where possible. The app’s custom gate is role-level only; it does not incorporate branch, document ownership, user permissions, or document-specific state.

The wiki reference explicitly notes controller hooks should usually deny based on context and let RBAC grant access. This hook can deny non-PEA users, but it does not apply any document-level business restrictions despite accepting the parameters.

**Why it matters**

In a real multi-branch setup, a user with PEA role may be able to access app surfaces across branches unless native DocPerm/User Permission filters also cover every relevant linked DocType and API query. The API checks Frappe permission in some places (`frappe.has_permission("Shift", "read", shift_name)`) but not uniformly for all aggregate/report APIs.

**v16 angle**

v16 has stricter User Permissions behaviour. Any custom query/API that uses role-only gates and `frappe.get_all`/query builder can bypass expected row-level constraints unless conditions are explicitly applied.

**Recommendation**

- Either remove unused `doctype/docname/branch` parameters or implement them.
- Use native User Permissions for Branch/Department where possible.
- For APIs returning lists/aggregates, explicitly apply permission query conditions or use `frappe.get_list` where user filtering is required.
- Add tests with a non-Administrator user restricted to one Branch.

---

### 7. Medium — App-managed DocPerm mutation in lifecycle hooks is powerful but non-standard operationally

**App code**

- `lifecycle.py:25-28` runs on both `after_sync` and `after_migrate`:

```python
def _setup_app() -> None:
	access_control.ensure_access_roles_and_settings()
	field_permissions.ensure_pea_field_permissions()
	performance_indexes.ensure_performance_indexes_with_recovery()
```

- `access_control.py` and `field_permissions.py` create/update/delete `DocPerm` rows programmatically.

**Deviation**

Frappe supports DocPerms, but continuously rewriting them during app sync/migrate can surprise site admins who expect Role Permission Manager to be the source of truth. The field-permission code is careful to only manage permlevel 9 app-owned fields and to avoid overwriting non-matching DocPerm templates, which is good. The DocType-level sync is broader.

**Why it matters**

- Manual permission changes to app DocTypes may be overwritten on migrate.
- App upgrades can modify site permissions without an explicit admin action.
- Multiple apps managing DocPerm rows can conflict.

**Recommendation**

Document this clearly in README/admin docs. Consider adding a setting: `manage_native_permissions = 1` defaulting on for fresh installs, with explicit admin opt-out. At minimum, log what was changed during migrate.

---

### 8. Medium — E2E/test helper APIs are whitelisted in production modules

**App code**

`api.py` contains many E2E helpers, e.g. `set_e2e_access_control`, `bootstrap_e2e_context`, cleanup/bootstrap methods. They are gated by:

```python
frappe.only_for("Administrator")
if not frappe.conf.get("developer_mode"): throw
if not frappe.conf.get("allow_e2e_tests"): throw
```

**Good**

The double gate matches the project’s own CLAUDE.md best practice and is better than leaving helper endpoints open.

**Deviation / risk**

These endpoints still ship in the same module as production API and include force deletes, manual commits, fixture creation, and permission changes. If `developer_mode` and `allow_e2e_tests` are accidentally enabled in a non-test site, the blast radius is high.

**Recommendation**

- Move E2E APIs to a clearly named module such as `production_entry_app.production_entry_app.e2e_api` and keep them out of normal UI imports.
- Add a boot-time/admin warning if `allow_e2e_tests=1` is enabled on a non-test site.
- Consider requiring site name / environment marker to match a test prefix.

---

### 9. Medium — Package metadata does not declare ERPNext as a required app

**App code**

- `hooks.py:11` leaves `required_apps = []` commented out.
- `setup.py` / `pyproject.toml` do not declare ERPNext dependency except a comment.
- Production code imports ERPNext directly, e.g. `overrides/stock_entry.py:3`:

```python
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
```

**Deviation**

For a Frappe app that directly imports ERPNext and customises ERPNext DocTypes, ERPNext is not optional. Frappe app best practice is to declare dependencies so install order and missing-app errors are explicit.

**Recommendation**

Set in `hooks.py`:

```python
required_apps = ["erpnext"]
```

Also update README with supported version matrix: Frappe/ERPNext v15.110+ and v16.20/16.21+ as tested here.

---

### 10. Medium — `add_to_apps_screen` route is `/app`, which is weak for v16 Desktop

**App code**

- `hooks.py:14-20`

```python
add_to_apps_screen = [
	{
		"name": "production_entry_app",
		"title": "Production Entry App",
		"route": "/app",
		"has_permission": "production_entry_app.production_entry_app.access_control.has_app_permission",
	}
]
```

**v16 reference**

The wiki notes v16 moved toward Desktop and `/desk`; custom app icons should define a meaningful route. Old `/app` redirects, but hardcoded `/app` URLs are migration-sensitive.

**Deviation**

The app icon route points to generic `/app`, not a workspace/module route for the app. This is not a functional bug, but it is not a polished v16-native desktop entry.

**Recommendation**

Route to the app’s workspace/module page, e.g. `/app/production-entry-app` if that route exists, or add a Workspace and point to it. Consider v16 `/desk` compatibility if/when targeting newer v16 UX.

---

### 11. Low — Hardcoded Desk URL `/app/downtime-entry/...` in Shift JS

**App code**

- `production_entry_app/production_entry_app/doctype/shift/shift.js:385`

```javascript
<a href="/app/downtime-entry/${encodeURIComponent(d.name || "")}">
```

**Deviation**

Frappe v16 migration notes warn about `/app` vs `/desk` route changes. `/app` may redirect today, but hardcoded route strings age badly.

**Recommendation**

Use `frappe.utils.get_form_link("Downtime Entry", d.name)` or `frappe.set_route`-based links where available, instead of raw `/app/...`.

---

### 12. Low — `frappe_in_test()` compatibility helper comment is reversed vs migration note

**App code**

- `compat/utils.py:13-21`

```python
"""Check if Frappe is running in test mode.

Replaces deprecated frappe.flags.in_test.
Works in both v15 (frappe.flags.in_test) and v16+ (frappe.in_test).
"""
if IS_V16_OR_GREATER:
	return frappe.in_test
return bool(frappe.flags.in_test)
```

**Reference**

The wiki migration page says `frappe.in_test` is deprecated and v16 should use `frappe.flags.in_test` or proper context. If the local v16 bench still has `frappe.in_test`, this code may work today, but the comment contradicts the migration note and may be future-fragile.

**Recommendation**

Verify against current Frappe v16 runtime. Prefer a safe fallback helper:

```python
return bool(getattr(frappe.flags, "in_test", False) or getattr(frappe, "in_test", False))
```

Then update the comment to avoid encoding the wrong direction.

---

### 13. Low — Some master DocTypes should consistently set `allow_rename = 0`

**App status**

Good:

- `Downtime Reason`: `allow_rename = 0`
- `Operator`: `allow_rename = 0`
- `Die Tool Counter`: `allow_rename = 0`

Gap:

- `Rejection Reason` is fixture/master-style data with `is_active`, but `allow_rename` is not set.

**Recommendation**

Set `allow_rename: 0` for `Rejection Reason` if fixture-installed or historically linked records should remain stable.

---

## Positive observations

These areas are aligned with Frappe/ERPNext best practices:

1. **No raw SQL found** in production app code. Queries use `frappe.qb`, `frappe.get_all`, `frappe.db.get_value`, etc.
2. **Custom field names use `custom_pea_` prefix**, which is the right namespace style for standard DocType customisation.
3. **Server-side validation exists** for the main Stock Entry and Shift rules; the app is not relying only on browser checks.
4. **JS `frappe.call()` usage generally includes `error` callbacks.** The scanned user-facing calls in Stock Entry, Shift, access control, timeline, and Die Tool Counter have error handling.
5. **Field permission design is cautious:** app-owned standard DocType fields use permlevel 9 and `field_permissions.py` validates it before syncing DocPerms.
6. **Performance awareness is present:** composite indexes are created for overlap/report paths, and missing-column recovery avoids hard migration failure.
7. **v15/v16 compatibility is tested deliberately:** there are compatibility tests and local symlinked benches for both versions.
8. **E2E APIs are gated** by Administrator + `developer_mode` + `allow_e2e_tests`, which is the right minimum if these endpoints remain whitelisted.

---

## Native behaviour deviations to consciously accept or redesign

These are not necessarily bugs; they are product decisions that differ from native ERPNext:

| Area | Native ERPNext behaviour | App behaviour | Risk |
|---|---|---|---|
| Manufacturing execution | Work Order / Job Card / Stock Entry are primary execution records | Shift becomes shop-floor hub and Stock Entry links to Shift | Medium; reporting and workflow semantics diverge |
| Qty to Manufacture | Changing `fg_completed_qty` auto-fetches BOM items | Native fetch is suppressed; user clicks PEA Fetch Items | High; core UX changed |
| Finished good row selection | Last `is_finished_item` row wins | First non-rejection FG row wins | High; stock ledger coupling |
| Rejections | ERPNext commonly uses quality/scrap/rejection stock flows | Rejection qty is deducted from FG and a custom rejection row is added | High; valuation/accounting needs audit |
| Completed state | Closed states are normally stable | Completed Shift can still accept Stock Entries | Medium; late mutation risk |
| Delete API | Framework global `frappe.client.delete` | App wrapper for all deletes | High blast radius, low current delta |

---

## Recommended remediation order

1. **Lock down Stock Entry override risk**
   - Add v15/v16 regression tests around manufacture + rejection rows + ledger entries.
   - Add v16 Job Card test for the JS `fg_completed_qty` override.
   - Decide whether rejection rows must be `is_finished_item` rows.

2. **Replace or justify global `frappe.client.delete` override**
   - Try moving orphan cleanup to Shift-specific lifecycle/API.
   - If retained, document app-order conflict and test non-Shift deletes.

3. **Make permission model truly native-aware**
   - Implement branch/document context or remove misleading parameters.
   - Add non-admin, branch-restricted tests for API/report data.

4. **Move E2E APIs out of production API module**
   - Keep gates, but reduce accidental production exposure.

5. **Declare ERPNext dependency**
   - Add `required_apps = ["erpnext"]`.
   - Document tested v15/v16 version bands.

6. **v16 route polish**
   - Replace hardcoded `/app` links where practical.
   - Improve `add_to_apps_screen` route.

---

## Suggested follow-up tests

Minimum high-value tests before relying on this in production:

1. v15 and v16: Stock Entry Manufacture from BOM with rejection qty creates expected SLEs and cancels cleanly.
2. v15 and v16: Same flow with Work Order.
3. v16: Same flow with Job Card; confirm native Job Card item-fetch semantics are not broken.
4. v15 and v16: Process loss + rejection qty together.
5. v15 and v16: Serial/batch item in BOM with rejection qty.
6. Permission test: PEA user restricted to one Branch cannot read/aggregate another Branch’s Shift/Stock Entry data through whitelisted APIs.
7. Delete test: deleting a non-PEA DocType via `frappe.client.delete` behaves exactly like native.

## Bottom line

The app is workable as a controlled custom production-entry layer, but it is not “native-only ERPNext configuration”. The riskiest parts are where it intercepts Stock Entry internals and framework delete APIs. If those are intentional, they need permanent compatibility tests for both v15 and v16. Without those tests, upgrades will be Mumbai traffic: moving, but nobody knows which lane is real.
