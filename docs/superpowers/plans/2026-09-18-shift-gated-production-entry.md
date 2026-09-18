# Shift-Gated vs Stock-Only Production Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Manufacture and Joint Production Entries submit stock without a Shift, while selecting Shift reveals and requires production-capture fields (except Total Press Strokes, which stays optional for assembly).

**Architecture:** Gate PEA capture UI and server validations on `custom_pea_shift` via `is_shift_based_production_entry(doc)`. Stock/BOM/fetch stays available either way. Clearing Shift clears gated fields on client and server. No new checkbox or Stock Entry Type.

**Tech Stack:** Frappe/ERPNext Stock Entry hooks (Python), Desk form script (`stock_entry.js`), Node unit tests, Playwright E2E, `CONTEXT.md` domain language.

## Global Constraints

- Tabs for indentation; Python line length 110; typed annotations on all Python functions.
- TDD: failing test first, then minimal implementation.
- Never edit core Frappe/ERPNext.
- Total Press Strokes must **not** be required > 0 (assembly may be zero); do not coerce empty/zero to `fg_completed_qty`.
- Rework behavior unchanged.
- Spec: `docs/superpowers/specs/2026-09-18-shift-gated-production-entry-design.md`

---

## File Structure

- Modify: `CONTEXT.md` — add Shift-based / Stock-only Production Entry terms
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py` — gate helper, mandatory checks, clear gated fields, SPM/strokes behavior
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py` — pure-helper + hook tests
- Modify: `production_entry_app/public/js/stock_entry.js` — field lists, visibility, reqd, clear-on-clear, stop FG stroke inventing without intent
- Modify: `tests/unit/stock-entry-visibility.test.js` — visibility / reqd / clear tests
- Modify: `tests/e2e/pages/stock-entry-page.js` — stock-only fill helper
- Modify: `tests/e2e/specs/stock-entry-and-die-tool.spec.js` (or new sibling) — stock-only smoke path

Local bench for Python tests: `/root/workspace/bench16` site `frappe16.localhost`.

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks \
  --test TestStockEntryHookPureHelpers.test_NAME
```

JS unit tests from app root:

```bash
cd /root/workspace/production-entry-app
npm run test:unit:js -- tests/unit/stock-entry-visibility.test.js
```

---

### Task 1: Domain language + `is_shift_based_production_entry` + gate Standard SPM

**Files:**
- Modify: `CONTEXT.md`
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`

**Interfaces:**
- Produces: `is_shift_based_production_entry(doc: Document) -> bool`
- Consumes: existing `is_production_overlap_entry(doc)`

- [ ] **Step 1: Add failing tests for the gate and SPM skip without Shift**

In `TestStockEntryHookPureHelpers`, add:

```python
def test_is_shift_based_production_entry_requires_shift_and_production(self) -> None:
	self.assertFalse(
		stock_entry_hooks.is_shift_based_production_entry(
			frappe._dict({"purpose": "Manufacture", "custom_pea_shift": ""})
		)
	)
	with patch.object(stock_entry_hooks, "is_production_overlap_entry", return_value=True):
		self.assertTrue(
			stock_entry_hooks.is_shift_based_production_entry(
				frappe._dict({"purpose": "Manufacture", "custom_pea_shift": "SHIFT-1"})
			)
		)
	with patch.object(stock_entry_hooks, "is_production_overlap_entry", return_value=False):
		self.assertFalse(
			stock_entry_hooks.is_shift_based_production_entry(
				frappe._dict({"purpose": "Material Transfer", "custom_pea_shift": "SHIFT-1"})
			)
		)


def test_validate_standard_spm_skips_stock_only_manufacture(self) -> None:
	doc = frappe._dict(
		{
			"purpose": "Manufacture",
			"custom_pea_shift": "",
			"custom_pea_standard_spm": 0,
			"custom_pea_workstation": "",
		}
	)
	with patch.object(stock_entry_hooks, "is_shift_based_production_entry", return_value=False):
		stock_entry_hooks._validate_standard_spm(doc)
```

Update existing SPM rejection tests (`test_validate_standard_spm_rejects_zero_on_manufacture`, joint twin, sync tests) so they set `custom_pea_shift` to a non-empty value **and** patch `is_shift_based_production_entry` to `True` (or rely on the real helper once implemented). Prefer calling the real helper with `custom_pea_shift` set and `is_production_overlap_entry` patched True.

- [ ] **Step 2: Run tests — expect fail**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks \
  --test TestStockEntryHookPureHelpers.test_is_shift_based_production_entry_requires_shift_and_production
```

Expected: FAIL — `is_shift_based_production_entry` missing or SPM still throws without Shift.

- [ ] **Step 3: Implement helper and gate SPM**

In `stock_entry_hooks.py` next to `is_production_overlap_entry`:

```python
def is_shift_based_production_entry(doc: Document) -> bool:
	return bool(doc.get("custom_pea_shift") and is_production_overlap_entry(doc))
```

Change `_validate_standard_spm` guard from `is_production_overlap_entry` to `is_shift_based_production_entry`.

Add to `CONTEXT.md` Language section (after Production Entry):

```markdown
**Shift-based Production Entry**:
A Manufacture or Joint Production Entry with `custom_pea_shift` set. Captures time,
resources, losses, rejection, strokes, and metrics in addition to stock.
_Avoid_: Full production entry, supervised entry

**Stock-only Production Entry**:
A Manufacture or Joint Production Entry with no Shift. Records inventory from BOM(s)
and fetch-items only. Excluded from Shift summaries and Production Date Range.
_Avoid_: Non-shift manufacturing entry, simple stock manufacture
```

- [ ] **Step 4: Re-run SPM / gate tests — expect pass**

- [ ] **Step 5: Commit**

```bash
git add CONTEXT.md \
  production_entry_app/production_entry_app/overrides/stock_entry_hooks.py \
  production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py
git commit -m "$(cat <<'EOF'
Gate Standard SPM on Shift-based Production Entries.

Stock-only Manufacture/Joint entries must not require SPM.
EOF
)"
```

---

### Task 2: Clear gated fields without Shift + require capture fields with Shift

**Files:**
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`

**Interfaces:**
- Consumes: `is_shift_based_production_entry`
- Produces: `_clear_shift_gated_capture_fields(doc)`, `_validate_shift_based_required_fields(doc)`

Gated scalar/table fieldnames (server clear list — keep in sync with client):

```python
_SHIFT_GATED_SCALAR_FIELDS: tuple[str, ...] = (
	"custom_pea_planned_start_date",
	"custom_pea_planned_end_date",
	"custom_pea_actual_start_date",
	"custom_pea_actual_end_date",
	"custom_pea_actual_start_date_input",
	"custom_pea_actual_start_time_input",
	"custom_pea_actual_end_date_input",
	"custom_pea_actual_end_time_input",
	"custom_pea_workstation",
	"custom_pea_operator",
	"custom_pea_standard_spm",
	"custom_pea_rejection_qty",
	"custom_pea_rework_qty",
	"custom_pea_ok_qty",
	"custom_pea_total_strokes",
	"custom_pea_die_tool_item",
	"custom_pea_lh_rejection_qty",
	"custom_pea_rh_rejection_qty",
	"custom_pea_actual_duration_mins",
	"custom_pea_production_time_mins",
	"custom_pea_actual_spm",
	"custom_pea_cycle_time_sec",
	"custom_pea_operator_efficiency_pct",
	"custom_pea_metrics_note",
	"custom_pea_die_tool_utilization_pct",
	"custom_pea_die_tool_maintenance_due",
)
_SHIFT_GATED_TABLE_FIELDS: tuple[str, ...] = (
	"custom_pea_unplanned_losses",
	"custom_pea_rejection_breakup",
)
```

Do **not** clear Joint LH/RH BOMs, gross qtys, or operation — those are stock-only Joint inputs.

- [ ] **Step 1: Write failing tests**

```python
def test_stock_only_validate_clears_shift_gated_capture_fields(self) -> None:
	doc = frappe._dict(
		custom_pea_shift="",
		purpose="Manufacture",
		stock_entry_type="Manufacture",
		custom_pea_workstation="WS-1",
		custom_pea_operator="OP-1",
		custom_pea_actual_start_date="2026-09-01 08:00:00",
		custom_pea_actual_end_date="2026-09-01 09:00:00",
		custom_pea_standard_spm=2,
		custom_pea_rejection_qty=3,
		custom_pea_unplanned_losses=[{"stop_reason": "Tea Break"}],
		custom_pea_rejection_breakup=[{"qty": 1}],
		flags=frappe._dict(),
		set=lambda self_or_field, value=None, *a, **k: None,  # replace with real set below
	)
	# Prefer a small FakeDoc with .get/.set and child tables like other tests in this file.

def test_shift_based_requires_workstation_operator_and_actual_times(self) -> None:
	doc = frappe._dict(
		{
			"purpose": "Manufacture",
			"custom_pea_shift": "SHIFT-1",
			"custom_pea_workstation": "",
			"custom_pea_operator": "",
			"custom_pea_actual_start_date": None,
			"custom_pea_actual_end_date": None,
			"custom_pea_standard_spm": 2,
		}
	)
	with (
		patch.object(stock_entry_hooks, "is_shift_based_production_entry", return_value=True),
		self.assertRaisesRegex(frappe.ValidationError, "Workstation"),
	):
		stock_entry_hooks._validate_shift_based_required_fields(doc)
```

Add focused tests that missing Operator / Actual Start / Actual End / Standard SPM each throw once prior fields are filled. One happy-path test with all required fields set does not throw.

Wire `validate_stock_entry` so that for non-rework:
- if not shift: call `_clear_shift_gated_capture_fields(doc)` before other capture validators
- if shift: call `_validate_shift_based_required_fields(doc)` (after shift defaults / before or with SPM)

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement clear + require helpers; call from `validate_stock_entry`**

```python
def _clear_shift_gated_capture_fields(doc: Document) -> None:
	if is_rework_stock_entry_type(doc) or doc.get("custom_pea_shift"):
		return
	if not is_production_overlap_entry(doc):
		return
	meta = frappe.get_meta("Stock Entry", cached=True)
	for fieldname in _SHIFT_GATED_SCALAR_FIELDS:
		if meta.has_field(fieldname):
			doc.set(fieldname, None if fieldname.endswith("_qty") or "spm" in fieldname or "mins" in fieldname or "pct" in fieldname or "strokes" in fieldname or "sec" in fieldname else None)
			# Simpler: always doc.set(fieldname, None) / 0 for numeric known fields —
			# match existing clear patterns in the file (empty string vs None).
	for fieldname in _SHIFT_GATED_TABLE_FIELDS:
		if meta.has_field(fieldname):
			doc.set(fieldname, [])


def _validate_shift_based_required_fields(doc: Document) -> None:
	if not is_shift_based_production_entry(doc):
		return
	if not doc.get("custom_pea_workstation"):
		frappe.throw(_("Workstation is required for Shift-based Production Entries."))
	if not doc.get("custom_pea_operator"):
		frappe.throw(_("Operator is required for Shift-based Production Entries."))
	if not doc.get("custom_pea_actual_start_date"):
		frappe.throw(_("Actual Start Date is required for Shift-based Production Entries."))
	if not doc.get("custom_pea_actual_end_date"):
		frappe.throw(_("Actual End Date is required for Shift-based Production Entries."))
```

Keep SPM validation as the > 0 check (already gated in Task 1). Do not require Total Press Strokes here.

Use concrete clear values consistent with the codebase (empty string for Link/Datetime, `0` or `None` for floats — inspect `_clear_shift_context` and child-table clears). Prefer:

```python
doc.set(fieldname, None)
```

for scalars when meta allows, and `doc.set(table, [])` for tables.

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
Require capture fields only on Shift-based Production Entries.

Clear gated capture fields when Shift is absent.
EOF
)"
```

---

### Task 3: Stop inventing Total Press Strokes from FG qty

**Files:**
- Modify: `production_entry_app/production_entry_app/overrides/stock_entry_hooks.py`
- Modify: `production_entry_app/production_entry_app/overrides/test_stock_entry_hooks.py`
- Modify: `production_entry_app/public/js/stock_entry.js` (only if client default still invents strokes — align in Task 4 if cleaner; preferred here for server)

**Interfaces:**
- Changes: `_default_total_strokes(doc) -> None`

- [ ] **Step 1: Failing tests**

```python
def test_default_total_strokes_skips_stock_only_manufacture(self) -> None:
	doc = frappe._dict(
		{
			"purpose": "Manufacture",
			"custom_pea_shift": "",
			"fg_completed_qty": 100,
			"custom_pea_total_strokes": 0,
		}
	)
	doc.set = lambda fieldname, value: doc.update({fieldname: value})
	with patch.object(stock_entry_hooks, "is_joint_lh_rh_production", return_value=False):
		stock_entry_hooks._default_total_strokes(doc)
	self.assertEqual(flt(doc.custom_pea_total_strokes), 0)


def test_default_total_strokes_leaves_zero_on_shift_based_assembly(self) -> None:
	doc = frappe._dict(
		{
			"purpose": "Manufacture",
			"custom_pea_shift": "SHIFT-1",
			"fg_completed_qty": 100,
			"custom_pea_total_strokes": 0,
		}
	)
	doc.set = lambda fieldname, value: doc.update({fieldname: value})
	with patch.object(stock_entry_hooks, "is_joint_lh_rh_production", return_value=False):
		stock_entry_hooks._default_total_strokes(doc)
	self.assertEqual(flt(doc.custom_pea_total_strokes), 0)


def test_default_total_strokes_rejects_negative(self) -> None:
	doc = frappe._dict(
		{
			"purpose": "Manufacture",
			"custom_pea_shift": "SHIFT-1",
			"custom_pea_total_strokes": -1,
		}
	)
	with (
		patch.object(stock_entry_hooks, "is_joint_lh_rh_production", return_value=False),
		self.assertRaisesRegex(frappe.ValidationError, "Total Press Strokes"),
	):
		stock_entry_hooks._default_total_strokes(doc)
```

- [ ] **Step 2: Run — expect fail** (current code coerces 0 → FG qty)

- [ ] **Step 3: Rewrite `_default_total_strokes`**

```python
def _default_total_strokes(doc: Document) -> None:
	if doc.get("purpose") != "Manufacture" or is_joint_lh_rh_production(doc):
		return
	if not is_shift_based_production_entry(doc):
		return
	total_strokes = doc.get("custom_pea_total_strokes")
	if total_strokes in (None, ""):
		return
	if flt(total_strokes) < 0:
		frappe.throw(_("Total Press Strokes cannot be negative."))
```

- [ ] **Step 4: Run — expect pass**. Grep tests for “Total Press Strokes must be greater than zero” / FG default expectations and update any that relied on auto-fill.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
Stop coercing Total Press Strokes from finished quantity.

Assembly and stock-only entries may keep zero strokes.
EOF
)"
```

---

### Task 4: Client visibility, reqd, clear-on-clear, stop FG stroke inventing

**Files:**
- Modify: `production_entry_app/public/js/stock_entry.js`
- Modify: `tests/unit/stock-entry-visibility.test.js`

**Interfaces:**
- Produces exported constants: `PEA_SHIFT_GATED_FIELDS`, `PEA_SHIFT_GATED_SECTIONS`, `SHIFT_BASED_REQUIRED_FIELDS`
- Changes: `_apply_manufacture_visibility`, `_handle_shift_change` / clear helper, `_default_total_strokes_from_fg`

- [ ] **Step 1: Write failing unit tests**

```javascript
test("shift-gated fields stay hidden until Shift is selected", () => {
	const calls = [];
	const frm = {
		fields_dict: {},
		layout: { sections: [] },
		doc: {
			custom_stock_entry_purpose: "Manufacture",
			custom_pea_shift: "",
		},
		toggle_display(fieldnames, visible) {
			calls.push(["display", fieldnames, visible]);
		},
		toggle_reqd(fieldname, required) {
			calls.push(["reqd", fieldname, required]);
		},
		refresh_fields() {},
	};
	_apply_manufacture_visibility(frm);
	assert.ok(
		calls.some(
			([kind, fieldnames, visible]) =>
				kind === "display" &&
				Array.isArray(fieldnames) &&
				fieldnames.includes("custom_pea_workstation") &&
				visible === false
		)
	);
	assert.ok(
		calls.some(
			([kind, fieldnames, visible]) =>
				kind === "display" &&
				Array.isArray(fieldnames) &&
				fieldnames.includes("custom_pea_shift") &&
				visible === true
		)
	);
});

test("selecting Shift shows gated fields and marks capture fields required", () => {
	// same harness with custom_pea_shift: "SHIFT-1"
	// expect workstation display true and toggle_reqd workstation/operator/actuals true
});

test("clearing Shift clears gated capture values", async () => {
	// drive _handle_shift_change with empty shift after doc had workstation/operator/times
	// assert those fields cleared (extend existing _handle_shift_change tests)
});
```

Also assert `_default_total_strokes_from_fg` does nothing without Shift and does not overwrite `0` when Shift is set.

- [ ] **Step 2: Run**

```bash
cd /root/workspace/production-entry-app
npm run test:unit:js -- tests/unit/stock-entry-visibility.test.js
```

Expected: FAIL on new assertions.

- [ ] **Step 3: Implement client changes**

Split lists near top of `stock_entry.js`:

```javascript
const PEA_ALWAYS_VISIBLE_PRODUCTION_FIELDS = [
	"custom_pea_shift",
	"custom_pea_fetch_items",
];
const PEA_SHIFT_GATED_FIELDS = [
	"custom_pea_rejection_qty",
	"custom_pea_ok_qty",
	"custom_pea_rework_qty",
	"custom_pea_rejection_breakup",
	"custom_pea_planned_start_date",
	"custom_pea_planned_end_date",
	"custom_pea_operation_details_col_break",
	"custom_pea_actual_start_date_input",
	"custom_pea_actual_start_time_input",
	"custom_pea_actual_start_date",
	"custom_pea_actual_end_date_input",
	"custom_pea_actual_end_time_input",
	"custom_pea_actual_end_date",
	"custom_pea_workstation",
	"custom_pea_standard_spm",
	"custom_pea_workstation_operator_col_break",
	"custom_pea_operator",
	"custom_pea_unplanned_losses",
	"custom_pea_actual_duration_mins",
	"custom_pea_production_time_mins",
	"custom_pea_actual_spm",
	"custom_pea_cycle_time_sec",
	"custom_pea_metrics_col_break",
	"custom_pea_operator_efficiency_pct",
	"custom_pea_metrics_note",
	"custom_pea_die_tool_utilization_pct",
	"custom_pea_die_tool_maintenance_due",
	"custom_pea_total_strokes",
	"custom_pea_die_tool_item",
	"custom_pea_lh_rejection_qty",
	"custom_pea_rh_rejection_qty",
];
const PEA_SHIFT_GATED_SECTIONS = [
	"custom_pea_operation_details_section",
	"custom_pea_workstation_operator_section",
	"custom_pea_unplanned_losses_section",
	"custom_pea_rejection_section",
	"custom_pea_metrics_section",
];
const SHIFT_BASED_REQUIRED_FIELDS = [
	"custom_pea_workstation",
	"custom_pea_operator",
	"custom_pea_actual_start_date",
	"custom_pea_actual_end_date",
	"custom_pea_standard_spm",
];
```

Rebuild `PEA_MANUFACTURE_FIELDS` as `[...PEA_ALWAYS_VISIBLE_PRODUCTION_FIELDS, ...PEA_SHIFT_GATED_FIELDS]` so leave-manufacture clears stay complete.

In `_apply_manufacture_visibility`:

```javascript
const hasShift = Boolean(frm.doc?.custom_pea_shift);
frm.toggle_display(PEA_ALWAYS_VISIBLE_PRODUCTION_FIELDS, isProduction);
frm.toggle_display(PEA_SHIFT_GATED_FIELDS, isProduction && hasShift);
frm.toggle_display(PEA_SHIFT_GATED_SECTIONS, isProduction && hasShift);
// keep NORMAL_ONLY / JOINT_ONLY for stock fields; gate joint rejection qtys via PEA_SHIFT_GATED
for (const fieldname of SHIFT_BASED_REQUIRED_FIELDS) {
	frm.toggle_reqd?.(fieldname, isProduction && hasShift);
}
```

On Shift clear in `_handle_shift_change` / dedicated helper: clear all `PEA_SHIFT_GATED_FIELDS` scalars and clear gated tables (`custom_pea_unplanned_losses`, `custom_pea_rejection_breakup`). Keep existing planned-date clear behavior.

`_default_total_strokes_from_fg`: return immediately unless `_is_manufacture_doc && !_is_joint_doc && frm.doc.custom_pea_shift`. Do not overwrite when current strokes are `0` if that invents FG qty — match server: only leave user-entered values; safest is to no longer auto-set from FG at all (delete body to `return Promise.resolve()` or remove call sites). Prefer removing inventing behavior entirely so assembly stays at 0.

Export new constants from `module.exports`.

- [ ] **Step 4: Run unit JS — expect pass**. Fix any tests that assumed gated fields always display on Manufacture.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(cat <<'EOF'
Hide and require production capture fields based on Shift.

Stock-only Manufacture/Joint keep BOM and fetch UI only.
EOF
)"
```

---

### Task 5: E2E stock-only Manufacture path

**Files:**
- Modify: `tests/e2e/pages/stock-entry-page.js`
- Modify: `tests/e2e/specs/stock-entry-and-die-tool.spec.js`

- [ ] **Step 1: Add page helper**

```javascript
async fillStockOnlyManufactureEntry(ctx) {
	await setFieldValue(this.page, "stock_entry_type", "Manufacture");
	await this.waitForFieldValue("custom_stock_entry_purpose", "Manufacture");
	await setFieldValue(this.page, "company", ctx.company);
	await this.setPostingDate(ctx.shift_date);
	await setFieldValue(this.page, "from_bom", 1);
	await setFieldValue(this.page, "bom_no", ctx.bom);
	await setFieldValue(this.page, "from_warehouse", ctx.wip_warehouse);
	await setFieldValue(this.page, "to_warehouse", ctx.wip_warehouse);
	await setFieldValue(this.page, "fg_completed_qty", 100);
	// Do not set custom_pea_shift or capture fields.
}
```

- [ ] **Step 2: Add failing/red E2E until hooks+UI land** (if prior tasks done, this should pass once written)

```javascript
test("@smoke stock-only manufacture submits without Shift capture fields", async ({ page }) => {
	await page.goto(getRoute("/home"));
	const ctx = await bootstrapE2E(page, lifecycle.getPrefix());
	const stockEntryPage = new StockEntryPage(page);
	await stockEntryPage.openNew();
	await stockEntryPage.fillStockOnlyManufactureEntry(ctx);
	await stockEntryPage.fetchItems();
	await stockEntryPage.saveAndSubmit();
	const stockEntryName = await page.evaluate(() => cur_frm.doc.name);
	const stockEntry = await getDoc(page, "Stock Entry", stockEntryName);
	expect(stockEntry.docstatus).toBe(1);
	expect(stockEntry.custom_pea_shift).toBeFalsy();
	expect(stockEntry.custom_pea_workstation).toBeFalsy();
});
```

Assert workstation field is not visible before submit via Playwright locator `data-fieldname="custom_pea_workstation"` hidden/not visible when Shift empty.

- [ ] **Step 3: Run E2E against local bench** (when site is up):

```bash
cd /root/workspace/production-entry-app
npx playwright test tests/e2e/specs/stock-entry-and-die-tool.spec.js -g "stock-only manufacture"
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
Add E2E coverage for stock-only Manufacture without Shift.
EOF
)"
```

---

### Task 6: Full verification

- [ ] **Step 1: Python module tests**

```bash
cd /root/workspace/bench16
bench --site frappe16.localhost run-tests --app production_entry_app \
  --module production_entry_app.production_entry_app.overrides.test_stock_entry_hooks
```

- [ ] **Step 2: JS unit tests**

```bash
cd /root/workspace/production-entry-app
npm run test:unit:js
```

- [ ] **Step 3: pre-commit**

```bash
cd /root/workspace/production-entry-app
pre-commit run --all-files
```

- [ ] **Step 4: Fix any failures; commit only if hooks left dirty files**

---

## Spec coverage checklist

| Spec requirement | Task |
| --- | --- |
| Gate = `custom_pea_shift` | 1 |
| Hide capture fields without Shift | 4 |
| Manufacture + Joint scope | 1–4 (Joint stock fields stay; rejection gated) |
| Mandatory workstation/operator/actuals/SPM with Shift | 2, 4 |
| Strokes optional / zero allowed / no FG coerce | 3, 4 |
| Clear on Shift clear (client + server) | 2, 4 |
| CONTEXT terms | 1 |
| E2E stock-only Manufacture | 5 |
| Rework unchanged | no task (assert existing rework tests still pass in Task 6) |

## Placeholder / consistency self-review

- Helper name is consistently `is_shift_based_production_entry`.
- Required fields list matches spec (no Total Press Strokes).
- Clear lists omit Joint BOM/gross/operation stock inputs.
- Bench site named `frappe16.localhost` for this environment.
