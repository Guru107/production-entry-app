# Native-Alignment Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink the app's interception of Frappe/ERPNext internals (Stock Entry class override, global `frappe.client.delete` override, `fg_completed_qty` monkey-patch, E2E APIs in production module) and add a v15/v16 regression net, without changing the rejection-as-quarantined-FG domain behavior.

**Architecture:** Two shippable PRs. **PR A (Phase 1)** is mechanical/safe cleanup with no behavior change. **PR B (Phase 2)** is gated by a spike that decides whether the Stock Entry class override is *deleted* or *hardened*, then lands the regression suite, the narrowed JS patch, the delete-override removal, and the late-entry audit. Phase 3 (branch isolation) is a separate future spec and out of scope here.

**Tech Stack:** Frappe/ERPNext v15 + v16 (Python 3.10+, tabs, 110-col), Frappe test runner (`FrappeTestCase`), Playwright E2E, `frappe.qb`.

## Global Constraints

- TDD mandatory: failing test first, then implementation. Coverage stays **≥ 90%**.
- **Tabs** for indentation (Python + JS). Python line length **110**. Type hints on all Python params + returns.
- All user-visible strings wrapped in `_()` (Python) / `__()` (JS).
- Every `frappe.call()` needs an `error:` callback.
- Run `pre-commit run --all-files` before declaring a task done; fix, then stage → commit.
- **Execution environment: cloud Linux env.** Bench targets (site names differ per bench here):
  - `bench16` → `cd /root/workspace/bench16`, site **`frappe16.localhost`**, served on **:8002** (v16 — primary target for JS/override/E2E work).
  - `bench15` → `cd /root/workspace/bench15`, site **`development.localhost`**, served on **:8000** (v15 — Python regression parity only).
- **E2E prerequisite (executor-provided, one-time):** before any `npx playwright test` step, a bench dev server for **`frappe16.localhost` must be listening on `localhost:8002`** (Playwright's default `baseURL`; override with `PLAYWRIGHT_BASE_URL`). Confirm `developer_mode` and `allow_e2e_tests` are on for that site. The plan does not start/stop the server itself.
- **Branch strategy:** the `codex/fix-bench16` fix is now merged to `develop`. Branch **`feat/native-alignment-phase-1`** off the updated `develop` for PR A; branch **`feat/native-alignment-phase-2`** off `develop` (after PR A merges) for PR B. Do not build on the old feature branch.
- App under development: **no backward-compat shims** — update call sites directly.
- Only **direct manufacture-from-BOM** is in scope. No Work Order / Job Card / serial-batch / process-loss tests (tripwire notes only).

---

## PR A — Phase 1 (safe hardening, no behavior change)

### Task 1: Declare ERPNext dependency (Audit #9)

**Files:**
- Modify: `production_entry_app/hooks.py:11`
- Modify: `README.md` (add "Supported versions")
- Test: `production_entry_app/production_entry_app/test_doctype_metadata.py`

**Interfaces:**
- Produces: `hooks.required_apps == ["erpnext"]`

- [ ] **Step 1: Write the failing test**

Add to `test_doctype_metadata.py`:

```python
def test_required_apps_declares_erpnext() -> None:
	from production_entry_app import hooks

	assert getattr(hooks, "required_apps", None) == ["erpnext"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata`
Expected: FAIL — `required_apps` is currently a comment.

- [ ] **Step 3: Implement**

In `hooks.py`, replace line 11 `# required_apps = []` with:

```python
required_apps = ["erpnext"]
```

- [ ] **Step 4: Add README section**

Under a new `## Supported versions` heading in `README.md`:

```markdown
## Supported versions

Tested against Frappe/ERPNext **v15.110+** and **v16.20 / 16.21+**.
ERPNext is a required dependency (`required_apps = ["erpnext"]`).
```

- [ ] **Step 5: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add production_entry_app/hooks.py README.md production_entry_app/production_entry_app/test_doctype_metadata.py
git commit -m "feat: declare erpnext as required app"
```

---

### Task 2: `Rejection Reason` rename stability (Audit #13)

**Files:**
- Modify: `production_entry_app/production_entry_app/doctype/rejection_reason/rejection_reason.json`
- Test: `production_entry_app/production_entry_app/test_doctype_metadata.py`

- [ ] **Step 1: Write the failing test**

Extend the existing `test_master_data_doctypes_do_not_allow_rename` in `test_doctype_metadata.py`:

```python
def test_master_data_doctypes_do_not_allow_rename() -> None:
	assert assert_doctype_json("Operator")["allow_rename"] == 0
	assert assert_doctype_json("Downtime Reason")["allow_rename"] == 0
	assert assert_doctype_json("Rejection Reason")["allow_rename"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata`
Expected: FAIL — `Rejection Reason` has no `allow_rename: 0`.

- [ ] **Step 3: Implement**

In `rejection_reason.json`, add the top-level key (alongside `"allow_import"`, etc.):

```json
 "allow_rename": 0,
```

- [ ] **Step 4: Migrate + run test to verify it passes**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost migrate && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/doctype/rejection_reason/rejection_reason.json production_entry_app/production_entry_app/test_doctype_metadata.py
git commit -m "feat: lock Rejection Reason against rename"
```

---

### Task 3: Fix `frappe_in_test()` compat helper (Audit #12)

**Files:**
- Modify: `production_entry_app/production_entry_app/compat/utils.py:12-21`
- Test: `production_entry_app/production_entry_app/tests/compat/test_version_compat.py`

- [ ] **Step 1: Write the failing test**

Add to `test_version_compat.py`:

```python
def test_frappe_in_test_true_via_flags(self) -> None:
	from production_entry_app.production_entry_app.compat import utils

	with patch.object(frappe.flags, "in_test", True, create=True):
		assert utils.frappe_in_test() is True
```

(Ensure `from unittest.mock import patch` and `import frappe` are imported in the file.)

- [ ] **Step 2: Run test to verify it fails or is fragile**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.tests.compat.test_version_compat`
Expected: On v16 the current code reads `frappe.in_test` and ignores `frappe.flags.in_test`, so the flags-only path is not covered.

- [ ] **Step 3: Implement**

Replace the body of `frappe_in_test` in `compat/utils.py`:

```python
def frappe_in_test() -> bool:
	"""Check if Frappe is running in test mode.

	Works across v15 (frappe.flags.in_test) and v16+ (frappe.in_test) by
	honoring whichever marker is set.
	"""
	return bool(getattr(frappe.flags, "in_test", False) or getattr(frappe, "in_test", False))
```

Delete the now-unused `IS_V16_OR_GREATER` import if nothing else in the file uses it (check first with grep).

- [ ] **Step 4: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/compat/utils.py production_entry_app/production_entry_app/tests/compat/test_version_compat.py
git commit -m "fix: make frappe_in_test honor either version marker"
```

---

### Task 4: Remove app-invented unused permission params (Audit #6a)

**Files:**
- Modify: `production_entry_app/production_entry_app/access_control.py` (`assert_app_access`, `assert_app_read_access`, `assert_app_write_access`, `_can_read`, `_can_write`)
- Modify call sites: `production_entry_app/production_entry_app/doctype/shift/shift.py`, `production_entry_app/production_entry_app/api.py`, `production_entry_app/production_entry_app/api_timeline.py` (grep to confirm the full set)
- Test: `production_entry_app/production_entry_app/test_access_control.py`

**Interfaces:**
- Produces: `assert_app_read_access()` / `assert_app_write_access()` / `assert_app_access()` take **no** keyword args. `has_gated_doctype_permission(doc, ptype, user, debug)` signature is **unchanged**.

- [ ] **Step 1: Write the failing test**

Add to `test_access_control.py`:

```python
def test_assert_helpers_take_no_context_kwargs(self) -> None:
	import inspect

	from production_entry_app.production_entry_app import access_control

	for fn_name in ("assert_app_read_access", "assert_app_write_access", "assert_app_access"):
		sig = inspect.signature(getattr(access_control, fn_name))
		assert not sig.parameters, f"{fn_name} should take no params, got {list(sig.parameters)}"


def test_gated_doctype_permission_keeps_hook_signature(self) -> None:
	import inspect

	from production_entry_app.production_entry_app import access_control

	params = list(inspect.signature(access_control.has_gated_doctype_permission).parameters)
	assert params == ["doc", "ptype", "user", "debug"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control`
Expected: FAIL — helpers currently accept `doctype`/`docname`/`branch`.

- [ ] **Step 3: Find every call site**

Run: `cd /root/workspace/production-entry-app && grep -rn "assert_app_read_access(\|assert_app_write_access(\|assert_app_access(\|_can_read(\|_can_write(" --include=*.py production_entry_app | grep -v "def "`
Note each file:line that passes `doctype=`/`docname=`/`branch=`.

- [ ] **Step 4: Implement — access_control.py**

Change the three helper signatures to take no params and drop the `del` line. Example for `assert_app_read_access`:

```python
def assert_app_read_access() -> None:
	"""Raise if the current session user cannot read Production Entry App.

	Access is evaluated by role only.
	"""
	effective_user = _resolve_user(None)
	try:
		if _can_read(effective_user):
			return
	except Exception:
		_log_access_error("Unable to evaluate Production Entry App access.", effective_user)
		if _is_system_manager(effective_user):
			return
	frappe.throw(_("You do not have access to Production Entry App."), frappe.PermissionError)
```

Apply the same shape to `assert_app_write_access()` and `assert_app_access()` (the alias becomes `def assert_app_access() -> None: assert_app_write_access()`). Change `_can_read(self, user)` / `_can_write(user)` to drop the `branch` param and its `del branch` line:

```python
def _can_read(user: str) -> bool:
	config = _get_access_configuration()
	...
```

Leave `has_gated_doctype_permission(doc, ptype, user, debug)` exactly as-is (keep `del doc, debug`).

- [ ] **Step 5: Implement — update call sites**

For every hit from Step 3, drop the kwargs. Known sites:
- `shift.py` `get_shift_summary`: `access_control.assert_app_read_access(doctype="Shift", docname=shift_name)` → `access_control.assert_app_read_access()`
- `api.py` `get_shift_details_for_stock_entry`: `access_control.assert_app_read_access(doctype="Shift", docname=shift_name)` → `access_control.assert_app_read_access()`
- `api.py` `delete`: `access_control.assert_app_write_access(doctype="Shift", docname=name)` → `access_control.assert_app_write_access()`

Update any additional sites grep found identically.

- [ ] **Step 6: Run tests to verify pass**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_access_control`
Then the broader access suite: `--module production_entry_app.production_entry_app.test_access_control_whitelisted_api`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add production_entry_app/production_entry_app/access_control.py production_entry_app/production_entry_app/doctype/shift/shift.py production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/test_access_control.py
git commit -m "refactor: drop unused context params from app access helpers"
```

---

### Task 5: Create the app Workspace + fix `/app` route strings (Audit #10 / #11)

**Files:**
- Create: `production_entry_app/production_entry_app/workspace/production_entry_app/production_entry_app.json`
- Modify: `production_entry_app/hooks.py` (`add_to_apps_screen` route)
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.js:385`
- Test: `production_entry_app/production_entry_app/test_doctype_metadata.py`

**Interfaces:**
- Produces: a public `Workspace` named `Production Entry App` (route slug `production-entry-app`) with a **Forms** card, a **Reports** card, and a **Production Entry Settings** shortcut.

- [ ] **Step 1: Fix the hardcoded downtime link (shift.js)**

Replace the hardcoded anchor at `shift.js:385`:

```javascript
<a href="${frappe.utils.get_form_link("Downtime Entry", d.name || "")}">
```

(Keep the existing link text/children unchanged.)

- [ ] **Step 2: Create the Workspace definition**

Create `workspace/production_entry_app/production_entry_app.json`. The `content` cards' `card_name` must match the `Card Break` labels exactly. `link_count` on each Card Break must equal the number of `Link` rows under it (Forms = 7, Reports = 18).

```json
{
 "doctype": "Workspace",
 "name": "Production Entry App",
 "label": "Production Entry App",
 "title": "Production Entry App",
 "module": "Production Entry App",
 "public": 1,
 "is_hidden": 0,
 "icon": "tool",
 "sequence_id": 100.0,
 "content": "[{\"id\":\"pea_header\",\"type\":\"header\",\"data\":{\"text\":\"<span class=\\\"h4\\\">Production Entry App</span>\",\"col\":12}},{\"id\":\"pea_forms\",\"type\":\"card\",\"data\":{\"card_name\":\"Forms\",\"col\":4}},{\"id\":\"pea_reports\",\"type\":\"card\",\"data\":{\"card_name\":\"Reports\",\"col\":8}}]",
 "shortcuts": [
  {"type": "DocType", "label": "Production Entry Settings", "link_to": "Production Entry Settings", "color": "Grey"}
 ],
 "links": [
  {"type": "Card Break", "label": "Forms", "hidden": 0, "onboard": 0, "link_count": 7},
  {"type": "Link", "label": "Stock Entry", "link_type": "DocType", "link_to": "Stock Entry", "hidden": 0, "onboard": 0, "is_query_report": 0},
  {"type": "Link", "label": "Shift", "link_type": "DocType", "link_to": "Shift", "hidden": 0, "onboard": 0, "is_query_report": 0},
  {"type": "Link", "label": "Operator", "link_type": "DocType", "link_to": "Operator", "hidden": 0, "onboard": 0, "is_query_report": 0},
  {"type": "Link", "label": "Die Tool Counter", "link_type": "DocType", "link_to": "Die Tool Counter", "hidden": 0, "onboard": 0, "is_query_report": 0},
  {"type": "Link", "label": "Die Tool Maintenance Log", "link_type": "DocType", "link_to": "Die Tool Maintenance Log", "hidden": 0, "onboard": 0, "is_query_report": 0},
  {"type": "Link", "label": "Rejection Reason", "link_type": "DocType", "link_to": "Rejection Reason", "hidden": 0, "onboard": 0, "is_query_report": 0},
  {"type": "Link", "label": "Downtime Reason", "link_type": "DocType", "link_to": "Downtime Reason", "hidden": 0, "onboard": 0, "is_query_report": 0},
  {"type": "Card Break", "label": "Reports", "hidden": 0, "onboard": 0, "link_count": 18},
  {"type": "Link", "label": "Production OEE Report", "link_type": "Report", "link_to": "Production OEE Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Workstation Efficiency Report", "link_type": "Report", "link_to": "Workstation Efficiency Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Operator Efficiency Report", "link_type": "Report", "link_to": "Operator Efficiency Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Operator Daily SPM Report", "link_type": "Report", "link_to": "Operator Daily SPM Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Daily Strokes SPM Monitor", "link_type": "Report", "link_to": "Daily Strokes SPM Monitor", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Rejection Pareto Report", "link_type": "Report", "link_to": "Rejection Pareto Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Rejection PPM Report", "link_type": "Report", "link_to": "Rejection PPM Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Rejection Trend Report", "link_type": "Report", "link_to": "Rejection Trend Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Workstation Rejection Reason Matrix", "link_type": "Report", "link_to": "Workstation Rejection Reason Matrix", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Operator Rejection Performance", "link_type": "Report", "link_to": "Operator Rejection Performance", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Item BOM Rejection Hotspots", "link_type": "Report", "link_to": "Item BOM Rejection Hotspots", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Rework Pareto Report", "link_type": "Report", "link_to": "Rework Pareto Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Rework PPM Report", "link_type": "Report", "link_to": "Rework PPM Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Rework Trend Report", "link_type": "Report", "link_to": "Rework Trend Report", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Workstation Rework Reason Matrix", "link_type": "Report", "link_to": "Workstation Rework Reason Matrix", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Operator Rework Performance", "link_type": "Report", "link_to": "Operator Rework Performance", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Item BOM Rework Hotspots", "link_type": "Report", "link_to": "Item BOM Rework Hotspots", "hidden": 0, "onboard": 0, "is_query_report": 1},
  {"type": "Link", "label": "Die Tool Stroke and Maintenance Report", "link_type": "Report", "link_to": "Die Tool Stroke and Maintenance Report", "hidden": 0, "onboard": 0, "is_query_report": 1}
 ]
}
```

- [ ] **Step 3: Point the apps-screen route at the workspace (hooks.py)**

In `add_to_apps_screen`, change `"route": "/app"` to:

```python
		"route": "/app/production-entry-app",
```

- [ ] **Step 4: Migrate + write the metadata test**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost migrate`

Then add to `test_doctype_metadata.py`:

```python
def test_workspace_has_forms_and_reports_cards() -> None:
	import frappe

	ws = frappe.get_doc("Workspace", "Production Entry App")
	card_labels = [row.label for row in ws.links if row.type == "Card Break"]
	assert card_labels == ["Forms", "Reports"]
	report_links = [row.link_to for row in ws.links if row.link_type == "Report"]
	assert "Production OEE Report" in report_links
	assert len(report_links) == 18
```

- [ ] **Step 5: Run the metadata test to verify it passes**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_doctype_metadata`
Expected: PASS. If the workspace failed to import, the `frappe.get_doc` raises `DoesNotExistError` — fix the JSON (most likely a `card_name`/`Card Break` label mismatch or a bad `link_count`) and re-migrate.

- [ ] **Step 6: Build assets + smoke test the downtime link + workspace route**

Run: `cd /root/workspace/bench16 && bench build --app production_entry_app`
Then run the Shift E2E spec that renders downtime links: `cd /root/workspace/production-entry-app && npx playwright test specs/shift-batch2.spec.js`
Expected: PASS (downtime link resolves; app icon opens `/app/production-entry-app`).

- [ ] **Step 7: Commit**

```bash
git add production_entry_app/production_entry_app/workspace/ production_entry_app/hooks.py production_entry_app/production_entry_app/doctype/shift/shift.js production_entry_app/production_entry_app/test_doctype_metadata.py
git commit -m "feat: add Production Entry App workspace (Forms + Reports) and fix desk routes"
```

---

### Task 6: Log DocPerm changes during migrate (Audit #7)

**Files:**
- Modify: `production_entry_app/production_entry_app/lifecycle.py`
- Modify: `README.md` (admin note)
- Test: `production_entry_app/production_entry_app/test_lifecycle.py`

**Interfaces:**
- Produces: `_setup_app()` emits a `frappe.logger("production_entry_app").info(...)` summary line after running.

- [ ] **Step 1: Write the failing test**

Add to `test_lifecycle.py`:

```python
def test_setup_app_logs_summary(self) -> None:
	from production_entry_app.production_entry_app import lifecycle

	with patch("frappe.logger") as mock_logger:
		lifecycle._setup_app()
		mock_logger.assert_called_with("production_entry_app")
		assert mock_logger.return_value.info.called
```

(Ensure `from unittest.mock import patch` is imported.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_lifecycle`
Expected: FAIL — no logger call today.

- [ ] **Step 3: Implement**

In `lifecycle.py`, update `_setup_app`:

```python
def _setup_app() -> None:
	access_control.ensure_access_roles_and_settings()
	field_permissions.ensure_pea_field_permissions()
	performance_indexes.ensure_performance_indexes_with_recovery()
	frappe.logger("production_entry_app").info(
		"Production Entry App setup ran: access roles, field permissions (permlevel 9), "
		"and performance indexes were reconciled during sync/migrate."
	)
```

- [ ] **Step 4: Add README admin note**

Under a `## Admin notes` heading in `README.md`:

```markdown
## Admin notes

On every `bench migrate` / app sync, this app reconciles its own DocType and
permlevel-9 field permissions (see `lifecycle._setup_app`). Manual changes to
those app-owned permissions via Role Permission Manager may be overwritten on
migrate. Each run logs a summary to the `production_entry_app` logger.
```

- [ ] **Step 5: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add production_entry_app/production_entry_app/lifecycle.py README.md production_entry_app/production_entry_app/test_lifecycle.py
git commit -m "feat: log app permission reconciliation on migrate"
```

---

### Task 7: Relocate E2E APIs out of the production module (Audit #8)

**Files:**
- Create: `production_entry_app/production_entry_app/e2e_api.py`
- Modify: `production_entry_app/production_entry_app/api.py` (remove moved code)
- Modify: `production_entry_app/production_entry_app/lifecycle.py` (`after_migrate` warning)
- Modify E2E specs + fixtures referencing the old paths (see Step 4 list)
- Modify Python test imports: `production_entry_app/production_entry_app/test_api.py` (and any other test importing moved helpers)
- Test: `production_entry_app/production_entry_app/test_api.py`

**Interfaces:**
- Produces: E2E endpoints now at `production_entry_app.production_entry_app.e2e_api.<name>`. Production `api.py` retains `get_die_tool_counter`, `reset_die_tool_counter`, `get_access_control_state`, `get_shift_details_for_stock_entry`, `get_items_with_rejection`, `delete`, `_cleanup_orphan_stock_entry_loss_links`.

- [ ] **Step 1: Write the failing test**

Add to `test_api.py`:

```python
def test_production_api_module_has_no_e2e_helpers(self) -> None:
	import production_entry_app.production_entry_app.api as api

	for name in (
		"bootstrap_e2e_context",
		"cleanup_e2e_context",
		"cleanup_reserved_e2e_artifacts",
		"create_e2e_submitted_stock_entry",
		"create_e2e_full_shift_stock_entries",
		"create_e2e_downtime_entry",
		"set_e2e_access_control",
		"set_e2e_system_float_precision",
	):
		assert not hasattr(api, name), f"{name} must live in e2e_api, not api"


def test_e2e_api_module_exposes_helpers(self) -> None:
	import production_entry_app.production_entry_app.e2e_api as e2e_api

	assert callable(e2e_api.bootstrap_e2e_context)
	assert callable(e2e_api.cleanup_e2e_context)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api`
Expected: FAIL — helpers still in `api.py`, `e2e_api` does not exist.

- [ ] **Step 3: Implement the module move**

Create `e2e_api.py` and move these whitelisted endpoints **and their private helpers** verbatim from `api.py`: `set_e2e_access_control`, `bootstrap_e2e_context`, `set_e2e_system_float_precision`, `cleanup_e2e_context`, `cleanup_reserved_e2e_artifacts`, `create_e2e_submitted_stock_entry`, `create_e2e_full_shift_stock_entries`, `create_e2e_downtime_entry`, plus every `_e2e_*` / `_cleanup_e2e_*` / `_get_or_create_e2e_*` / `_build_e2e_*` / `_finalize_e2e_*` / `_restore_*` / `_cache_e2e_*` / `_assert_e2e_api_allowed` / `_is_developer_mode_enabled` / `_is_allow_e2e_tests_enabled` / `_ensure_e2e_settings_fields_loaded` / `_get_*_snapshot` / `_collect_reserved_e2e_prefixes` / `_safe_force_delete` / `_safe_cancel_and_delete` / `_stock_entry_matches_cleanup_target` / `_get_candidate_e2e_stock_entries` / `_item_has_live_stock_entry_references` / `_clear_timeline_cache_for_context` helper used only by them. Move the E2E-only module constants (`_E2E_*`). Keep the module imports each moved function needs.

`_cleanup_orphan_stock_entry_loss_links` is used by both `api.delete` (production) **and** E2E cleanup — **keep it in `api.py`** and import it into `e2e_api.py` (`from production_entry_app.production_entry_app.api import _cleanup_orphan_stock_entry_loss_links`).

Leave in `api.py`: `get_access_control_state`, `get_shift_details_for_stock_entry`, `get_items_with_rejection`, `get_die_tool_counter`, `_empty_die_tool_payload`, `reset_die_tool_counter`, `delete`, `_cleanup_orphan_stock_entry_loss_links`, `_ALLOWED_STOCK_ENTRY_SHIFT_STATUSES`, `_APP_GATED_DOCTYPES`. Remove now-unused imports from `api.py` (run `pre-commit` / ruff to catch them).

- [ ] **Step 4: Update every JS/Python call site to the new path**

Run: `cd /root/workspace/production-entry-app && grep -rln "production_entry_app.production_entry_app.api.\(bootstrap_e2e_context\|cleanup_e2e_context\|cleanup_reserved_e2e_artifacts\|create_e2e_submitted_stock_entry\|create_e2e_full_shift_stock_entries\|create_e2e_downtime_entry\|set_e2e_access_control\|set_e2e_system_float_precision\)" tests/`

Then replace `...api.<e2e_method>` → `...e2e_api.<e2e_method>` in each file. Known files: `tests/e2e/global-teardown.js`, `tests/e2e/fixtures/test-data.js`, `tests/e2e/specs/permissions.spec.js`, `tests/e2e/specs/access-control-role-branch.spec.js`, `tests/e2e/specs/die-tool-metrics.spec.js`, `tests/e2e/specs/reports.spec.js`, `tests/e2e/specs/shift-batch2.spec.js`. Do **not** rewrite non-E2E methods (`get_die_tool_counter`, `get_access_control_state`, `api_timeline.*`) — they stay on their current paths.

Also update Python test imports: `grep -rln "from production_entry_app.production_entry_app.api import .*e2e\|api import bootstrap_e2e" production_entry_app` and point them at `e2e_api`.

- [ ] **Step 5: Add the non-test-site warning (lifecycle.after_migrate)**

In `lifecycle.py`, add:

```python
def _warn_if_e2e_enabled_on_non_test_site() -> None:
	if not frappe.conf.get("allow_e2e_tests"):
		return
	site = frappe.local.site or ""
	if not any(marker in site for marker in ("test", "dev", "localhost")):
		frappe.logger("production_entry_app").warning(
			f"allow_e2e_tests=1 is set on site '{site}', which does not look like a "
			"test/dev site. E2E APIs perform force-deletes and permission changes."
		)
```

Call it from `after_migrate` (not `after_sync`):

```python
def after_migrate() -> None:
	_setup_app()
	_warn_if_e2e_enabled_on_non_test_site()
```

- [ ] **Step 6: Run Python tests to verify pass**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api`
Then the timeline + lifecycle modules to catch import breakage.
Expected: PASS.

- [ ] **Step 7: Run the E2E suite to verify the path rewrites**

Run: `cd /root/workspace/production-entry-app && npx playwright test`
Expected: PASS (all specs resolve the new `e2e_api` method paths).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: move E2E APIs into dedicated e2e_api module"
```

---

**PR A boundary:** open PR with Tasks 1–7. Merge before starting PR B.

---

## PR B — Phase 2 (spike-gated override work + regression net + audit)

### Task 8: SPIKE — can the Stock Entry class override be deleted? (Audit #1)

**Files:**
- Create (throwaway): `docs/superpowers/spikes/2026-07-01-rejection-row-is-finished-item.md` (records the decision)

**Interfaces:**
- Produces: a recorded PASS/FAIL decision that gates Task 10.

- [ ] **Step 1: Run the spike on bench16**

`cd /root/workspace/bench16 && bench --site frappe16.localhost console`, then build a direct manufacture-from-BOM Stock Entry where the rejection row has `t_warehouse` = rejected warehouse and `is_finished_item = 0` (temporarily patch `_append_rejection_item_row` in a console session or construct the doc manually). Submit it. Record:
  1. Did it validate + submit without error?
  2. `frappe.get_all("Stock Ledger Entry", filters={"voucher_no": se.name}, fields=["warehouse","actual_qty","stock_value_difference"])` — FG warehouse qty = `fg_completed_qty − rejection_qty`? Rejected warehouse qty = `rejection_qty`? RM consumed from WIP? Rejection valued same as FG?
  3. `se.get_finished_item_row().item_code` — is it the real FG row (not the rejection row)?
  4. Cancel: do all SLEs reverse?

- [ ] **Step 2: Repeat on bench15**

`cd /root/workspace/bench15 && bench --site development.localhost console` — same procedure.

- [ ] **Step 3: Record the decision**

Write the spike doc with the four answers per bench and the verdict:
- **All four PASS on both benches** → verdict `DELETE_OVERRIDE`. Task 10 deletes the override.
- **Any FAIL on either bench** → verdict `KEEP_OVERRIDE`. Task 10 hardens it.

- [ ] **Step 4: Commit the spike record**

```bash
git add docs/superpowers/spikes/2026-07-01-rejection-row-is-finished-item.md
git commit -m "docs: record rejection-row is_finished_item spike outcome"
```

---

### Task 9: Regression net — direct manufacture + rejection SLEs (Audit #1 safety)

**Files:**
- Create: `production_entry_app/production_entry_app/tests/support/manufacture_builders.py` (shared test builders, reused by Tasks 9, 11, 14)
- Create: `production_entry_app/production_entry_app/tests/support/__init__.py` (empty)
- Test: `production_entry_app/production_entry_app/overrides/test_stock_entry_override.py`

**Interfaces:**
- Consumes: existing `utils/test_bootstrap` `ensure_*` helpers (`ensure_item`, `ensure_warehouse`, `ensure_default_bom`, `ensure_stock`, `resolve_test_company`, etc.).
- Produces shared builders used by later tasks:
  - `bootstrap_manufacture_masters() -> dict` — creates company/warehouses/items/BOM/stock, returns keys `company, bom, wip_warehouse, fg_warehouse, rejection_warehouse, fg_item, rm_item`.
  - `make_running_shift(masters: dict) -> Document`
  - `make_completed_shift(masters: dict) -> Document`
  - `make_direct_manufacture_entry(masters: dict, *, shift: str, fg_qty: float, rejection_qty: float) -> Document` (returns an inserted-but-not-submitted Stock Entry)
- Produces tests: `test_manufacture_with_rejection_posts_expected_sles`, `test_manufacture_with_rejection_cancels_cleanly` — the permanent upgrade tripwire, must pass regardless of Task 10's direction.

- [ ] **Step 1: Create the shared builders module**

Create `tests/support/manufacture_builders.py` with the four functions above, built from the existing `utils/test_bootstrap` `ensure_*` helpers (mirror the doc shape used in `e2e_api._finalize_e2e_submitted_stock_entry`, but without submitting, and without any `_assert_e2e_api_allowed` gating — these run inside `FrappeTestCase`). `make_direct_manufacture_entry` must set `custom_pea_shift`, `from_bom=1`, `bom_no`, `fg_completed_qty`, warehouses, `custom_pea_actual_start_date`/`custom_pea_actual_end_date` inside the shift window, call `get_items()`, append a `custom_pea_rejection_breakup` row when `rejection_qty > 0`, and `insert(ignore_permissions=True)`.

- [ ] **Step 2: Write the failing tests**

Add to `test_stock_entry_override.py`, importing the shared builders (`from production_entry_app.production_entry_app.tests.support.manufacture_builders import bootstrap_manufacture_masters, make_direct_manufacture_entry`). Store `self.masters = bootstrap_manufacture_masters()` in `setUp`:

```python
def test_manufacture_with_rejection_posts_expected_sles(self) -> None:
	shift = make_running_shift(self.masters)
	se = make_direct_manufacture_entry(
		self.masters, shift=shift.name, fg_qty=100, rejection_qty=10
	)
	se.submit()

	sles = frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_no": se.name},
		fields=["warehouse", "actual_qty"],
	)
	by_wh = {row["warehouse"]: row["actual_qty"] for row in sles}
	assert by_wh[self.masters["fg_warehouse"]] == 90
	assert by_wh[self.masters["rejection_warehouse"]] == 10


def test_manufacture_with_rejection_cancels_cleanly(self) -> None:
	shift = make_running_shift(self.masters)
	se = make_direct_manufacture_entry(
		self.masters, shift=shift.name, fg_qty=100, rejection_qty=10
	)
	se.submit()
	se.cancel()

	net = frappe.db.sql(
		"select coalesce(sum(actual_qty),0) from `tabStock Ledger Entry` where voucher_no=%s",
		se.name,
	)[0][0]
	assert net == 0
```

(Import `make_running_shift` alongside the other builders.)

- [ ] **Step 3: Run tests to verify they pass on the current override (characterization)**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_override`
Expected: these are characterization tests — they should PASS against the *current* override behavior, establishing the baseline before Task 10 changes anything. If they fail, fix the test setup (not the app) until they green on the current code.

- [ ] **Step 4: Run the same on bench15**

Run: `cd /root/workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_override`
Expected: PASS on both benches.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/tests/support/ production_entry_app/production_entry_app/overrides/test_stock_entry_override.py
git commit -m "test: pin manufacture+rejection SLE behavior on v15/v16"
```

---

### Task 10: Apply the spike verdict to the class override (Audit #1)

**Files (verdict = DELETE_OVERRIDE):**
- Modify: `production_entry_app/hooks.py` (remove `override_doctype_class`)
- Delete: `production_entry_app/production_entry_app/overrides/stock_entry.py`
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py` (`_append_rejection_item_row`)

**Files (verdict = KEEP_OVERRIDE):**
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry.py` (add version-pinned comment only)

- [ ] **Step 1 (DELETE path): drop the `is_finished_item` flag on the rejection row**

In `stock_entry_hooks.py` `_append_rejection_item_row`, change line 642 `rejection_row.is_finished_item = 1` to:

```python
	rejection_row.is_finished_item = 0
```

- [ ] **Step 2 (DELETE path): remove the override registration + class**

In `hooks.py` delete the `override_doctype_class = {...}` block. Then `git rm production_entry_app/production_entry_app/overrides/stock_entry.py`. Update `overrides/test_stock_entry_override.py` if it imports the deleted class directly (switch assertions to native `frappe.get_doc("Stock Entry", ...).get_finished_item_row()`).

- [ ] **Step 3 (DELETE path): verify regression net still green on both benches**

Run Task 9's module on bench16 **and** bench15. Expected: PASS — native selection now returns the real FG row and SLEs are unchanged.

- [ ] **Step 1 (KEEP path): pin the override with a version comment**

If the verdict was KEEP, instead add above `get_finished_item_row` in `overrides/stock_entry.py`:

```python
	# Native get_finished_item_row picks the LAST is_finished_item row
	# (v15 stock_entry.py:1673, v16 stock_entry.py:1834). Our rejection row is
	# also is_finished_item, so we skip it here. If ERPNext changes multi-FG /
	# bundle selection, the regression tests in test_stock_entry_override.py
	# (manufacture+rejection SLEs) will fail — do not silence them.
```

- [ ] **Step 4: Migrate, build, run tests**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost migrate && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_override` (repeat on bench15).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: <delete stock entry class override | pin override> per spike verdict"
```

---

### Task 11: Pin `get_items_with_rejection` against native `get_items` (Audit #4)

**Files:**
- Test: `production_entry_app/production_entry_app/test_api.py`

- [ ] **Step 1: Write the failing test**

Add to `test_api.py`:

Add a `direct_manufacture_doc_dict(masters, *, fg_qty, rejection_qty) -> dict` function to the shared `tests/support/manufacture_builders.py` module (returns the minimal dict `get_items_with_rejection` consumes: `company`, `bom_no`, `fg_completed_qty`, `from_warehouse`, `to_warehouse`, `purpose="Manufacture"`, `stock_entry_type="Manufacture"`, `custom_pea_rejection_qty`, `use_multi_level_bom=0`). Then:

```python
import json

def test_get_items_with_rejection_base_rows_match_native(self) -> None:
	from production_entry_app.production_entry_app import api
	from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
		bootstrap_manufacture_masters,
		direct_manufacture_doc_dict,
	)

	masters = bootstrap_manufacture_masters()
	doc_dict = direct_manufacture_doc_dict(masters, fg_qty=100, rejection_qty=0)

	native = frappe.new_doc("Stock Entry")
	native.update({k: v for k, v in doc_dict.items() if k != "custom_pea_rejection_qty"})
	native.from_bom = 1
	native.get_items()
	native_codes = sorted(r.item_code for r in native.items)

	api_rows = api.get_items_with_rejection(json.dumps(doc_dict))
	api_codes = sorted(r["item_code"] for r in api_rows)

	assert api_codes == native_codes  # rejection_qty=0 → no extra row
```

- [ ] **Step 2: Run test to verify it passes (characterization)**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api` and on bench15.
Expected: PASS — proves the API's base rows equal native `get_items()` for direct manufacture. If it fails, the API has drifted from native and that is a real finding to raise, not a test to weaken.

- [ ] **Step 3: Commit**

```bash
git add production_entry_app/production_entry_app/test_api.py production_entry_app/production_entry_app/tests/support/manufacture_builders.py
git commit -m "test: pin get_items_with_rejection base rows to native get_items"
```

---

### Task 12: Narrow the `fg_completed_qty` monkey-patch (Audit #2)

**Files:**
- Modify: `production_entry_app/public/js/stock_entry.js:178-181`

- [ ] **Step 1: Implement the narrowed guard**

Replace the inner condition in the patched `fg_completed_qty` (currently `if (_is_manufacture_doc(this.frm.doc) && this.frm.doc.from_bom) {`):

```javascript
			if (
				_is_manufacture_doc(this.frm.doc) &&
				this.frm.doc.from_bom &&
				this.frm.doc.custom_pea_shift &&
				!this.frm.doc.job_card
			) {
				// Shift-linked direct manufacture: item fetch is handled by
				// the PEA "Fetch Items" button. Preserve v16's native Job Card
				// guard and native behavior for non-Shift entries.
				return;
			}
```

- [ ] **Step 2: Build assets**

Run: `cd /root/workspace/bench16 && bench build --app production_entry_app`
Expected: build succeeds.

- [ ] **Step 3: Run the Stock Entry E2E spec**

Run: `cd /root/workspace/production-entry-app && npx playwright test specs/stock-entry-and-die-tool.spec.js`
Expected: PASS — Shift-linked manufacture still suppresses native auto-fetch and Fetch Items populates rows.

- [ ] **Step 4: Commit**

```bash
git add production_entry_app/public/js/stock_entry.js
git commit -m "fix: narrow fg_completed_qty override to shift-linked non-jobcard entries"
```

---

### Task 13: Remove the global `frappe.client.delete` override (Audit #3)

**Files:**
- Modify: `production_entry_app/hooks.py` (remove `override_whitelisted_methods`; register Shift `on_trash`)
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py` (add `cleanup_orphan_stock_entry_loss_links` handler)
- Modify: `production_entry_app/production_entry_app/api.py` (remove `delete`; keep `_cleanup_orphan_stock_entry_loss_links` or move it into shift.py — see Step 3)
- Test: `production_entry_app/production_entry_app/test_api.py`

- [ ] **Step 1: Write the failing test**

Add to `test_api.py`:

```python
def test_deleting_shift_cleans_orphan_stock_entry_loss_links(self) -> None:
	from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
		bootstrap_manufacture_masters,
		make_running_shift,
	)

	masters = bootstrap_manufacture_masters()
	shift = make_running_shift(masters)
	# Simulate an orphan Loss Entry row pointing at a since-deleted Stock Entry parent.
	frappe.get_doc({
		"doctype": "Loss Entry",
		"parenttype": "Stock Entry",
		"parent": "SE-DELETED-0001",
		"parentfield": "custom_pea_unplanned_losses",
		"shift": shift.name,
		"downtime_reason": frappe.db.get_value("Downtime Reason", {}, "name"),
		"start_time": shift.planned_start_time,
		"end_time": shift.planned_start_time,
	}).insert(ignore_permissions=True)
	shift.db_set("status", "Draft")
	frappe.delete_doc("Shift", shift.name, force=True)
	assert not frappe.db.exists("Loss Entry", {"shift": shift.name, "parenttype": "Stock Entry"})


def test_client_delete_override_is_removed(self) -> None:
	from production_entry_app import hooks

	assert "frappe.client.delete" not in getattr(hooks, "override_whitelisted_methods", {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api`
Expected: FAIL — override still registered; cleanup only runs through the `api.delete` wrapper.

- [ ] **Step 3: Implement — move cleanup to Shift.on_trash**

In `shift.py`, add a module-level handler (reusing the existing orphan-cleanup logic; import `_cleanup_orphan_stock_entry_loss_links` from `api.py`, or move that helper into `shift.py` and import it back into `api.py` — pick one home and keep a single copy):

```python
def cleanup_orphan_stock_entry_loss_links(doc, method: str | None = None) -> None:
	"""Delete Loss Entry rows orphaned by deleted Stock Entry parents before the
	Shift delete runs Frappe's link-validation (on_trash fires before that check)."""
	from production_entry_app.production_entry_app.api import _cleanup_orphan_stock_entry_loss_links

	_cleanup_orphan_stock_entry_loss_links(doc.name)
```

In `hooks.py`, make the Shift `on_trash` value a list (it currently maps to the summary-invalidation function):

```python
	"Shift": {
		"on_update": "production_entry_app.production_entry_app.doctype.shift.shift.invalidate_shift_summary_for_shift",
		"on_trash": [
			"production_entry_app.production_entry_app.doctype.shift.shift.cleanup_orphan_stock_entry_loss_links",
			"production_entry_app.production_entry_app.doctype.shift.shift.invalidate_shift_summary_for_shift",
		],
	},
```

- [ ] **Step 4: Implement — delete the override + wrapper**

In `hooks.py` remove the `override_whitelisted_methods = {...}` block entirely. In `api.py` delete the `delete` function (keep `_cleanup_orphan_stock_entry_loss_links` wherever you homed it in Step 3). Remove the now-unused `frappe_client_delete_doc` import.

- [ ] **Step 5: Run tests to verify pass**

Run: same as Step 2, plus `--module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks` (deletes touch loss links).
Expected: PASS. Also confirm gated-doctype delete permission still enforced (native `has_gated_doctype_permission` covers `ptype="delete"`).

- [ ] **Step 6: Migrate + run E2E teardown path**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost migrate` then `cd /root/workspace/production-entry-app && npx playwright test specs/shift-batch2.spec.js` (exercises Shift creation/teardown).
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: replace global client.delete override with Shift on_trash cleanup"
```

---

### Task 14: Late-entry flag + summary count (Audit #5)

**Files:**
- Modify: `production_entry_app/fixtures/custom_field.json` (add `Stock Entry-custom_pea_is_late_entry`)
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py` (`validate_stock_entry` → stamp)
- Modify: `production_entry_app/production_entry_app/doctype/shift/shift.py` (`get_shift_summary` snapshot)
- Test: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`, `production_entry_app/production_entry_app/doctype/shift/test_shift.py`

**Interfaces:**
- Produces: field `custom_pea_is_late_entry` (Check, read-only) on Stock Entry; `get_shift_summary(...)["snapshot"]["late_entry_count"]`.

- [ ] **Step 1: Add the custom field fixture**

Append to `production_entry_app/fixtures/custom_field.json` (keep the array valid, match sibling formatting/tabs):

```json
 {
  "dt": "Stock Entry",
  "fieldname": "custom_pea_is_late_entry",
  "fieldtype": "Check",
  "label": "Late Entry (Post-Completion)",
  "insert_after": "custom_pea_rejection_qty",
  "read_only": 1,
  "module": "Production Entry App",
  "name": "Stock Entry-custom_pea_is_late_entry"
 }
```

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost migrate` to install the field.

- [ ] **Step 2: Write the failing stamp test**

Add to `overrides/test_stock_entry_hooks.py` (import the shared builders and store `self.masters = bootstrap_manufacture_masters()` in `setUp`):

```python
def test_entry_against_completed_shift_is_flagged_late(self) -> None:
	shift = make_completed_shift(self.masters)
	se = make_direct_manufacture_entry(
		self.masters, shift=shift.name, fg_qty=100, rejection_qty=0
	)
	se.submit()
	assert se.custom_pea_is_late_entry == 1


def test_entry_against_running_shift_is_not_flagged_late(self) -> None:
	shift = make_running_shift(self.masters)
	se = make_direct_manufacture_entry(
		self.masters, shift=shift.name, fg_qty=100, rejection_qty=0
	)
	se.submit()
	assert not se.custom_pea_is_late_entry
```

- [ ] **Step 3: Run stamp test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks`
Expected: FAIL — nothing sets the flag.

- [ ] **Step 4: Implement the stamp**

In `stock_entry_hooks.py`, add a helper and call it from `validate_stock_entry` (after the shift-can-accept check):

```python
def _stamp_late_entry_flag(doc) -> None:
	"""Flag entries submitted against a Completed shift (status-at-submit)."""
	meta = frappe.get_meta("Stock Entry", cached=True)
	if not meta.has_field("custom_pea_is_late_entry"):
		return
	shift_name = doc.get("custom_pea_shift")
	is_late = 0
	if doc.docstatus == 1 and shift_name:
		if frappe.db.get_value("Shift", shift_name, "status") == "Completed":
			is_late = 1
	doc.custom_pea_is_late_entry = is_late
```

Call it inside `validate_stock_entry`, right after `_validate_linked_shift_can_accept_stock_entry(doc)` / `_apply_shift_defaults(doc)`:

```python
	if doc.get("custom_pea_shift"):
		_validate_linked_shift_can_accept_stock_entry(doc)
		_apply_shift_defaults(doc)
	_stamp_late_entry_flag(doc)
```

- [ ] **Step 5: Run stamp test to verify it passes**

Run: same as Step 3. Expected: PASS.

- [ ] **Step 6: Write the failing summary test**

Add to `doctype/shift/test_shift.py`:

```python
def test_shift_summary_counts_late_entries(self) -> None:
	from production_entry_app.production_entry_app.doctype.shift.shift import (
		_get_shift_summary_cache_key,
		get_shift_summary,
	)
	from production_entry_app.production_entry_app.tests.support.manufacture_builders import (
		bootstrap_manufacture_masters,
		make_completed_shift,
		make_direct_manufacture_entry,
	)

	masters = bootstrap_manufacture_masters()
	shift = make_completed_shift(masters)
	make_direct_manufacture_entry(masters, shift=shift.name, fg_qty=100, rejection_qty=0).submit()
	frappe.cache().delete_value(_get_shift_summary_cache_key(shift.name))

	summary = get_shift_summary(shift.name)
	assert summary["snapshot"]["late_entry_count"] == 1
```

- [ ] **Step 7: Run summary test to verify it fails**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.doctype.shift.test_shift`
Expected: FAIL — `late_entry_count` key absent.

- [ ] **Step 8: Implement the summary count**

In `shift.py` `get_shift_summary`, add `"custom_pea_is_late_entry"` to the `entry_rows` `fields=[...]` list, compute after the entry loop:

```python
	late_entry_count = sum(1 for row in entry_rows if row.get("custom_pea_is_late_entry"))
```

Add to the `snapshot` dict:

```python
			"late_entry_count": late_entry_count,
```

Also add `"late_entry_count": 0` to the `snapshot` block in `_empty_shift_summary()` so the shape is consistent.

- [ ] **Step 9: Run summary test to verify it passes**

Run: same as Step 7. Expected: PASS.

- [ ] **Step 10: Add the E2E happy/validation spec**

Add a spec (or extend `specs/shift-batch2.spec.js`) that: bootstraps context, completes the shift, creates a submitted entry via `e2e_api.create_e2e_submitted_stock_entry`, opens the Shift summary, and asserts the late-entries count shows `1`. Include an `error:` callback on any `frappe.call`.

Run: `cd /root/workspace/production-entry-app && npx playwright test specs/shift-batch2.spec.js`
Expected: PASS.

- [ ] **Step 11: Export fixtures + commit**

```bash
cd /root/workspace/bench16 && bench export-fixtures --app production_entry_app
cd /root/workspace/production-entry-app
git add -A
git commit -m "feat: flag and surface post-completion (late) stock entries"
```

---

### Task 15: Full-suite verification + coverage gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full Python suite with coverage on v16**

Run: `cd /root/workspace/bench16 && bench --site frappe16.localhost run-tests --app production_entry_app --with-coverage`
Expected: all pass; coverage **≥ 90%**. If below, add tests for the uncovered new code (not asserts-on-asserts).

Note on the E2E-helper move (Task 7): those helpers are exercised by Playwright, not the Python unit run, so they read as uncovered lines. Moving them from `api.py` to `e2e_api.py` does not change the covered/uncovered ratio (same lines, new file). If — and only if — the coverage number regresses because of the relocation, add a `.coveragerc` `omit = */e2e_api.py` at the app root rather than writing unit tests for E2E-only fixtures. Do not omit anything else.

- [ ] **Step 2: Run the full Python suite on v15**

Run: `cd /root/workspace/bench15 && bench --site development.localhost run-tests --app production_entry_app`
Expected: all pass.

- [ ] **Step 3: Run the full E2E suite**

Run: `cd /root/workspace/production-entry-app && npx playwright test`
Expected: all pass.

- [ ] **Step 4: Lint**

Run: `cd /root/workspace/production-entry-app && pre-commit run --all-files`
Expected: clean (fix + re-run if not).

- [ ] **Step 5: Open PR B**

Push the branch and open the PR referencing this plan and the spike record.

---

## Tripwire notes (documented, NOT implemented here)

Add these to `README.md` under `## Known limits / future work`:
- If Work Order, Job Card, serial/batch, or process-loss manufacture flows are adopted, add regression tests before relying on them — the rejection/FG-selection and `get_items_with_rejection` logic sit on the ledger path and are only tested for direct manufacture-from-BOM.
- Phase 3 (per-branch data isolation via a shared `get_permitted_branches` helper + explicit `WHERE branch IN (...)` in `qb`/`get_all` aggregate queries) is a separate future spec.
