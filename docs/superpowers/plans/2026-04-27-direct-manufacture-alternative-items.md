# Direct Manufacture Alternative Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable ERPNext alternative raw-material selection for direct `Stock Entry` manufacture entries fetched from BOM without changing Work Order behavior.

**Architecture:** Reuse ERPNext's native Stock Entry alternative-item fields and dialog. The app's custom fetch API will preserve `allow_alternative_item` on direct Manufacture RM rows, and the Stock Entry validation hook will reject direct manual substitutions that are not allowed by the BOM and `Item Alternative` records.

**Tech Stack:** Frappe/ERPNext v15/v16, Python hooks and whitelisted API, ERPNext `Stock Entry Detail.allow_alternative_item` and `original_item`, Frappe integration tests through `bench run-tests`, existing app `pre-commit`.

---

## File Structure

- Modify `production_entry_app/production_entry_app/api.py`
  - Add a focused helper that enriches direct Manufacture RM rows after `se.get_items()` and before rejection rows are applied.
  - Keep the whitelisted API contract unchanged: input is serialized Stock Entry doc, output is a list of child-row dictionaries.
- Modify `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
  - Add direct Manufacture alternative validation early in `validate_stock_entry()` before rejection-row mutation.
  - Keep Work Order Stock Entries untouched by scoping validation to `purpose = Manufacture`, `from_bom = 1`, and no `work_order`.
- Modify `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
  - Add test data helpers for BOMs that allow/disallow alternatives.
  - Add fetch API tests and validation tests in the existing Stock Entry hook/API test module.

No schema, fixture, or JavaScript changes are planned because ERPNext already shows the native `Alternate Item` button when rows contain `allow_alternative_item = 1`.

---

### Task 1: Add Failing Fetch Tests For BOM Alternative Flags

**Files:**

- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- [x] **Step 1: Extend the BOM helper to accept alternative permission**

Change the helper signature and BOM row dict at `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py:297`:

```python
def _get_or_create_bom(
	fg_item: str,
	rm_item: str,
	company: str,
	rm_qty: float = 1,
	allow_alternative_item: int = 0,
) -> str:
	existing = frappe.db.get_value(
		"BOM", {"item": fg_item, "is_active": 1, "is_default": 1, "docstatus": 1}, "name"
	)
	if existing:
		return existing

	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"item": fg_item,
			"company": company,
			"quantity": 1,
			"is_active": 1,
			"is_default": 1,
			"items": [
				{
					"item_code": rm_item,
					"qty": rm_qty,
					"rate": 50,
					"allow_alternative_item": allow_alternative_item,
				}
			],
		}
	)
	bom.insert(ignore_permissions=True)
	bom.submit()
	return bom.name
```

- [x] **Step 2: Add unique alternative BOM setup helpers inside `TestGetItemsWithRejection`**

Add these methods inside `class TestGetItemsWithRejection`, after `_call_api()`:

```python
	def _make_alternative_bom_context(self, suffix: str, allow_alternative_item: int = 1) -> dict:
		fg_item = _get_or_create_item(f"_Test FG Alt Direct {suffix}")
		rm_item = _get_or_create_item(f"_Test RM Alt Direct {suffix}")
		alt_item = _get_or_create_item(f"_Test RM Alt Direct Substitute {suffix}")
		frappe.db.set_value("Item", rm_item, "allow_alternative_item", 1)
		frappe.db.set_value("Item", alt_item, "allow_alternative_item", 1)
		if not frappe.db.exists(
			"Item Alternative",
			{"item_code": rm_item, "alternative_item_code": alt_item},
		):
			frappe.get_doc(
				{
					"doctype": "Item Alternative",
					"item_code": rm_item,
					"alternative_item_code": alt_item,
					"two_way": 1,
				}
			).insert(ignore_permissions=True)
		bom_no = _get_or_create_bom(
			fg_item,
			rm_item,
			self.company,
			rm_qty=1,
			allow_alternative_item=allow_alternative_item,
		)
		return {"fg_item": fg_item, "rm_item": rm_item, "alt_item": alt_item, "bom_no": bom_no}
```

- [x] **Step 3: Add failing test for permitted alternative flag**

Add this test inside `TestGetItemsWithRejection` after `test_get_items_with_rejection_returns_bom_items`:

```python
	def test_get_items_with_rejection_marks_bom_rm_as_alternative_allowed(self) -> None:
		context = self._make_alternative_bom_context("Allowed", allow_alternative_item=1)

		items = self._call_api(bom_no=context["bom_no"])

		rm_rows = [row for row in items if row.get("item_code") == context["rm_item"]]
		self.assertEqual(len(rm_rows), 1)
		self.assertEqual(rm_rows[0].get("allow_alternative_item"), 1)
```

- [x] **Step 4: Add failing test for non-permitted BOM rows**

Add this test immediately after the permitted-flag test:

```python
	def test_get_items_with_rejection_does_not_mark_bom_rm_when_alternative_not_allowed(self) -> None:
		context = self._make_alternative_bom_context("NotAllowed", allow_alternative_item=0)

		items = self._call_api(bom_no=context["bom_no"])

		rm_rows = [row for row in items if row.get("item_code") == context["rm_item"]]
		self.assertEqual(len(rm_rows), 1)
		self.assertNotEqual(rm_rows[0].get("allow_alternative_item"), 1)
```

- [x] **Step 5: Run the new tests and verify they fail before implementation**

Run from bench16:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks \
  --test TestGetItemsWithRejection.test_get_items_with_rejection_marks_bom_rm_as_alternative_allowed \
  --test TestGetItemsWithRejection.test_get_items_with_rejection_does_not_mark_bom_rm_when_alternative_not_allowed
```

Expected before implementation: the first test fails because the fetched RM row does not reliably carry `allow_alternative_item = 1` for direct Manufacture custom fetch.

- [x] **Step 6: Commit failing tests**

```bash
git add production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "test: cover direct manufacture alternative fetch flags"
```

---

### Task 2: Preserve BOM Alternative Flags In Custom Fetch API

**Files:**

- Modify: `production_entry_app/production_entry_app/api.py`
- Test: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- [x] **Step 1: Add helper call after `se.get_items()`**

Change `get_items_with_rejection()` in `production_entry_app/production_entry_app/api.py` so the fetch section reads:

```python
	se.get_items()
	_apply_direct_manufacture_alternative_flags(se)
	_apply_rejection_entries(se)
```

- [x] **Step 2: Add the direct Manufacture scope helper**

Add this function below `get_items_with_rejection()` and above `get_die_tool_counter()`:

```python
def _apply_direct_manufacture_alternative_flags(doc) -> None:
	if doc.get("purpose") != "Manufacture" or not doc.get("from_bom") or doc.get("work_order"):
		return
	if not doc.get("bom_no"):
		return

	allowed_items = _get_bom_alternative_allowed_items(doc.get("bom_no"))
	if not allowed_items:
		return

	for row in doc.get("items") or []:
		if row.get("is_finished_item") or row.get("is_scrap_item") or row.get("custom_is_rejection_item"):
			continue
		item_code = row.get("original_item") or row.get("item_code")
		if item_code in allowed_items and not row.get("allow_alternative_item"):
			row.allow_alternative_item = 1
```

- [x] **Step 3: Add BOM lookup helper**

Add this function below `_apply_direct_manufacture_alternative_flags()`:

```python
def _get_bom_alternative_allowed_items(bom_no: str) -> set[str]:
	rows = frappe.get_all(
		"BOM Item",
		filters={"parent": bom_no, "allow_alternative_item": 1},
		pluck="item_code",
	)
	return {item_code for item_code in rows if item_code}
```

- [x] **Step 4: Run the fetch tests**

Run from bench16:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks \
  --test TestGetItemsWithRejection.test_get_items_with_rejection_marks_bom_rm_as_alternative_allowed \
  --test TestGetItemsWithRejection.test_get_items_with_rejection_does_not_mark_bom_rm_when_alternative_not_allowed
```

Expected after implementation: both tests pass.

- [x] **Step 5: Commit fetch implementation**

```bash
git add production_entry_app/production_entry_app/api.py production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "feat: preserve alternative flags for direct manufacture fetch"
```

---

### Task 3: Add Failing Validation Tests For Manual Substitution

**Files:**

- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- [ ] **Step 1: Add helper for direct Manufacture Stock Entry with substituted RM**

Add this method inside `TestGetItemsWithRejection`, after `_make_alternative_bom_context()`:

```python
	def _make_direct_manufacture_entry_with_alternative(self, context: dict) -> frappe.Document:
		se = _create_bom_stock_entry(
			company=self.company,
			bom_no=context["bom_no"],
			fg_completed_qty=100,
			from_warehouse=self.rm_warehouse,
			to_warehouse=self.fg_warehouse,
		)
		for row in se.items:
			if row.item_code == context["rm_item"]:
				row.item_code = context["alt_item"]
				row.original_item = context["rm_item"]
				row.allow_alternative_item = 1
				break
		return se
```

- [ ] **Step 2: Add test for valid direct alternative**

Add this test after the fetch flag tests:

```python
	def test_direct_manufacture_valid_alternative_item_validates(self) -> None:
		context = self._make_alternative_bom_context("Valid", allow_alternative_item=1)
		se = self._make_direct_manufacture_entry_with_alternative(context)

		se.run_method("validate")

		rm_rows = [row for row in se.items if row.get("original_item") == context["rm_item"]]
		self.assertEqual(len(rm_rows), 1)
		self.assertEqual(rm_rows[0].item_code, context["alt_item"])
```

- [ ] **Step 3: Add test for BOM row not allowing alternatives**

Add this test after the valid alternative test:

```python
	def test_direct_manufacture_alternative_requires_bom_row_permission(self) -> None:
		context = self._make_alternative_bom_context("BomDenied", allow_alternative_item=0)
		se = self._make_direct_manufacture_entry_with_alternative(context)

		with self.assertRaises(ValidationError):
			se.run_method("validate")
```

- [ ] **Step 4: Add test for missing Item Alternative record**

Add this test after the BOM permission test:

```python
	def test_direct_manufacture_alternative_requires_item_alternative_record(self) -> None:
		context = self._make_alternative_bom_context("MissingAlternative", allow_alternative_item=1)
		frappe.delete_doc(
			"Item Alternative",
			frappe.db.get_value(
				"Item Alternative",
				{"item_code": context["rm_item"], "alternative_item_code": context["alt_item"]},
				"name",
			),
			ignore_permissions=True,
		)
		se = self._make_direct_manufacture_entry_with_alternative(context)

		with self.assertRaises(ValidationError):
			se.run_method("validate")
```

- [ ] **Step 5: Run validation tests and verify the invalid tests fail before implementation**

Run from bench16:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks \
  --test TestGetItemsWithRejection.test_direct_manufacture_valid_alternative_item_validates \
  --test TestGetItemsWithRejection.test_direct_manufacture_alternative_requires_bom_row_permission \
  --test TestGetItemsWithRejection.test_direct_manufacture_alternative_requires_item_alternative_record
```

Expected before implementation: invalid-substitution tests fail because direct Manufacture validation does not yet reject these rows.

- [ ] **Step 6: Commit failing validation tests**

```bash
git add production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "test: cover direct manufacture alternative validation"
```

---

### Task 4: Validate Direct Manufacture Alternative Rows Server-Side

**Files:**

- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Test: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- [ ] **Step 1: Call validation before rejection row mutation**

Change `validate_stock_entry()` in `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py` so the validation sequence includes the new call before `_apply_rejection_entries(doc)`:

```python
	_validate_rejection_breakup(doc)
	_validate_direct_manufacture_alternative_items(doc)
	_apply_rejection_entries(doc)
```

- [ ] **Step 2: Add direct Manufacture validation helper**

Add this function above `_validate_rejection_breakup(doc)`:

```python
def _validate_direct_manufacture_alternative_items(doc) -> None:
	if doc.get("purpose") != "Manufacture" or not doc.get("from_bom") or doc.get("work_order"):
		return
	if not doc.get("bom_no"):
		return

	bom_allowed_items = _get_bom_alternative_allowed_items(doc.get("bom_no"))
	for row in doc.get("items") or []:
		if row.get("is_finished_item") or row.get("is_scrap_item") or row.get("custom_is_rejection_item"):
			continue
		original_item = row.get("original_item")
		item_code = row.get("item_code")
		if not original_item or original_item == item_code:
			continue
		if original_item not in bom_allowed_items:
			frappe.throw(
				_("Row {0}: BOM item {1} does not allow alternative items.").format(
					row.idx,
					frappe.bold(original_item),
				),
				ValidationError,
			)
		if not _is_configured_item_alternative(original_item, item_code):
			frappe.throw(
				_("Row {0}: Item {1} is not configured as an alternative for BOM item {2}.").format(
					row.idx,
					frappe.bold(item_code),
					frappe.bold(original_item),
				),
				ValidationError,
			)
```

- [ ] **Step 3: Add BOM permission lookup helper**

Add this function below `_validate_direct_manufacture_alternative_items()`:

```python
def _get_bom_alternative_allowed_items(bom_no: str) -> set[str]:
	rows = frappe.get_all(
		"BOM Item",
		filters={"parent": bom_no, "allow_alternative_item": 1},
		pluck="item_code",
	)
	return {item_code for item_code in rows if item_code}
```

- [ ] **Step 4: Add Item Alternative lookup helper**

Add this function below `_get_bom_alternative_allowed_items()`:

```python
def _is_configured_item_alternative(original_item: str, alternative_item: str) -> bool:
	if not original_item or not alternative_item:
		return False
	if frappe.db.exists(
		"Item Alternative",
		{"item_code": original_item, "alternative_item_code": alternative_item},
	):
		return True
	return bool(
		frappe.db.exists(
			"Item Alternative",
			{"item_code": alternative_item, "alternative_item_code": original_item, "two_way": 1},
		)
	)
```

- [ ] **Step 5: Add missing import for `ValidationError`**

At the top of `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`, update imports to include:

```python
from frappe.exceptions import ValidationError
```

- [ ] **Step 6: Run validation tests**

Run from bench16:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks \
  --test TestGetItemsWithRejection.test_direct_manufacture_valid_alternative_item_validates \
  --test TestGetItemsWithRejection.test_direct_manufacture_alternative_requires_bom_row_permission \
  --test TestGetItemsWithRejection.test_direct_manufacture_alternative_requires_item_alternative_record
```

Expected after implementation: all three tests pass.

- [ ] **Step 7: Commit validation implementation**

```bash
git add production_entry_app/production_entry_app/overrides/stock_entry_hooks.py production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "feat: validate direct manufacture alternative items"
```

---

### Task 5: Verify Rejection Rows And Native Button Eligibility

**Files:**

- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- [ ] **Step 1: Add test that rejection rows are not alternative-selectable**

Add this test inside `TestGetItemsWithRejection`, after `test_get_items_with_rejection_adds_rejection_row`:

```python
	def test_get_items_with_rejection_does_not_mark_rejection_row_as_alternative_allowed(self) -> None:
		context = self._make_alternative_bom_context("RejectionRow", allow_alternative_item=1)
		shift = _create_test_shift(
			shift_date="2026-04-24",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		items = self._call_api(
			bom_no=context["bom_no"],
			custom_rejection_qty=10,
			custom_shift=shift.name,
		)

		rejection_rows = [row for row in items if row.get("custom_is_rejection_item")]
		self.assertEqual(len(rejection_rows), 1)
		self.assertNotEqual(rejection_rows[0].get("allow_alternative_item"), 1)
```

- [ ] **Step 2: Add test that fetched row has native dialog fields**

Add this test after the rejection-row test:

```python
	def test_get_items_with_rejection_returns_native_alternative_dialog_fields(self) -> None:
		context = self._make_alternative_bom_context("DialogFields", allow_alternative_item=1)

		items = self._call_api(bom_no=context["bom_no"])

		rm_row = next(row for row in items if row.get("item_code") == context["rm_item"])
		self.assertEqual(rm_row.get("allow_alternative_item"), 1)
		self.assertIn("s_warehouse", rm_row)
		self.assertIn("actual_qty", rm_row)
		self.assertIn("original_item", rm_row)
```

- [ ] **Step 3: Run the targeted fetch/API tests**

Run from bench16:

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks \
  --test TestGetItemsWithRejection.test_get_items_with_rejection_does_not_mark_rejection_row_as_alternative_allowed \
  --test TestGetItemsWithRejection.test_get_items_with_rejection_returns_native_alternative_dialog_fields
```

Expected: both tests pass.

- [ ] **Step 4: Commit coverage tests**

```bash
git add production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "test: cover alternative dialog row state"
```

---

### Task 6: Run Compatibility And Quality Gates

**Files:**

- No code changes expected.
- Modify implementation files only to fix failures found by these commands.
- [ ] **Step 1: Run full Stock Entry hook/API tests on v16**

```bash
cd /Users/gurudattkulkarni/Workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

Expected: all tests in the module pass.

- [ ] **Step 2: Run full Stock Entry hook/API tests on v15**

```bash
cd /Users/gurudattkulkarni/Workspace/bench15
bench --site development.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

Expected: all tests in the module pass on ERPNext v15.

- [ ] **Step 3: Run pre-commit**

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
pre-commit run --all-files
```

Expected: all hooks pass. If a formatter modifies files, rerun `pre-commit run --all-files` until it exits `0`.

- [ ] **Step 4: Check final git state**

```bash
cd /Users/gurudattkulkarni/Workspace/production-entry-app
git status --short --branch
```

Expected: branch is `feature/alternative-item-selection-manufacturing-entry` with no unstaged changes after the final commit.

- [ ] **Step 5: Commit final fixes if verification changed files**

Only run this if Step 1, Step 2, or Step 3 required code changes:

```bash
git add production_entry_app/production_entry_app/api.py \
  production_entry_app/production_entry_app/overrides/stock_entry_hooks.py \
  production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "fix: stabilize direct manufacture alternative items"
```

---

## Self-Review Notes

- Spec coverage: fetch preservation, native dialog eligibility, direct-only validation, Work Order non-interference, rejection row exclusion, v15/v16 verification, and unchanged quantity behavior are each mapped to a task.
- Implementation scope stays within `api.py`, `stock_entry_hooks.py`, and existing Stock Entry tests.
- No schema migration or custom UI is planned.

