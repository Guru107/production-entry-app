from __future__ import annotations

import json
from typing import ClassVar

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase


def _ensure_downtime_reasons() -> None:
	"""Ensure Tea Break and Lunch Break Downtime Reasons exist."""
	for name in ("Tea Break", "Lunch Break"):
		if not frappe.db.exists("Downtime Reason", name):
			frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()


def _ensure_rejection_breakup_doctype() -> None:
	if not frappe.db.exists("DocType", "Rejection Breakup"):
		frappe.reload_doc("production_entry_app", "doctype", "rejection_breakup")


def _ensure_rejection_reason_doctype() -> None:
	if not frappe.db.exists("DocType", "Rejection Reason"):
		frappe.reload_doc("production_entry_app", "doctype", "rejection_reason")


def _ensure_rejection_reasons() -> None:
	for name in ("Burr", "Crack"):
		if not frappe.db.exists("Rejection Reason", name):
			frappe.get_doc({"doctype": "Rejection Reason", "rejection_reason_name": name}).insert()


def _ensure_rejection_breakup_custom_field() -> None:
	if frappe.db.exists("Custom Field", "Stock Entry-custom_rejection_breakup"):
		return
	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "Stock Entry",
			"fieldname": "custom_rejection_breakup",
			"fieldtype": "Table",
			"label": "Rejection Breakup",
			"options": "Rejection Breakup",
			"insert_after": "custom_fetch_items",
			"depends_on": "eval:doc.custom_rejection_qty > 0",
			"mandatory_depends_on": "eval:doc.custom_rejection_qty > 0",
			"module": "Production Entry App",
		}
	).insert(ignore_permissions=True)


def _ensure_die_tool_counter_doctype() -> None:
	if not frappe.db.exists("DocType", "Die Tool Counter"):
		frappe.reload_doc("production_entry_app", "doctype", "die_tool_counter")


def _ensure_item_die_tool_fields() -> None:
	if not frappe.db.exists("Custom Field", "Item-custom_strokes_per_unit"):
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Item",
				"fieldname": "custom_strokes_per_unit",
				"fieldtype": "Float",
				"label": "Strokes Per Unit",
				"insert_after": "item_name",
				"module": "Production Entry App",
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Custom Field", "Item-custom_stroke_capacity"):
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Item",
				"fieldname": "custom_stroke_capacity",
				"fieldtype": "Float",
				"label": "Stroke Capacity",
				"insert_after": "custom_strokes_per_unit",
				"module": "Production Entry App",
			}
		).insert(ignore_permissions=True)


def _append_rejection_breakup_rows(doc, rows: list[dict]) -> None:
	for row in rows:
		doc.append("custom_rejection_breakup", row)


def _get_or_create_warehouse(name: str, company: str) -> str:
	"""Return warehouse name, creating it if needed."""
	if frappe.db.exists("Warehouse", name):
		return name
	wh = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": name.split(" - ")[0],
			"company": company,
		}
	)
	wh.insert(ignore_permissions=True)
	return wh.name


def _get_or_create_item(item_code: str) -> str:
	"""Return item_code, creating the item if needed."""
	if frappe.db.exists("Item", item_code):
		return item_code
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"valuation_rate": 100,
			"item_group": "Products",
		}
	)
	item.insert(ignore_permissions=True)
	return item.name


def _set_item_die_tool_fields(item_code: str, strokes_per_unit: float, stroke_capacity: float) -> None:
	frappe.db.set_value("Item", item_code, "custom_strokes_per_unit", strokes_per_unit)
	frappe.db.set_value("Item", item_code, "custom_stroke_capacity", stroke_capacity)


def _create_test_shift(
	shift_date: str = "2026-04-10",
	shift_label: str = "1",
	planned_start_time: str = "08:00:00",
	branch: str | None = None,
	wip_warehouse: str | None = None,
	rejection_warehouse: str | None = None,
) -> frappe.Document:
	"""Create and return a test Shift."""
	_ensure_downtime_reasons()
	# End any stale Running shifts so start_shift() is not blocked
	for sn in frappe.get_all("Shift", filters={"status": "Running"}, pluck="name"):
		frappe.db.set_value("Shift", sn, "status", "Completed", update_modified=False)
	name = f"SHIFT-{shift_date}.Shift-{shift_label}"
	if frappe.db.exists("Shift", name):
		frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)

	doc_data = {
		"doctype": "Shift",
		"shift_label": shift_label,
		"shift_duration": "8",
		"shift_date": shift_date,
		"planned_start_time": planned_start_time,
	}
	if branch:
		doc_data["branch"] = branch
	if wip_warehouse:
		doc_data["work_in_progress_warehouse"] = wip_warehouse
	if rejection_warehouse:
		doc_data["rejection_warehouse"] = rejection_warehouse

	shift = frappe.get_doc(doc_data).insert()
	# Start the shift to set status to "Running" so it appears in custom_shift filter
	shift.start_shift()
	return shift


def _get_or_create_bom(fg_item: str, rm_item: str, company: str, rm_qty: float = 1) -> str:
	"""Return BOM name for fg_item, creating and submitting one if needed."""
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
				}
			],
		}
	)
	bom.insert(ignore_permissions=True)
	bom.submit()
	return bom.name


def _create_bom_stock_entry(
	company: str,
	bom_no: str,
	fg_completed_qty: float = 100,
	custom_rejection_qty: float = 0,
	custom_shift: str | None = None,
	from_warehouse: str | None = None,
	to_warehouse: str | None = None,
) -> frappe.Document:
	"""Create a Manufacture Stock Entry with from_bom=1 and call get_items()."""
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"purpose": "Manufacture",
			"stock_entry_type": "Manufacture",
			"company": company,
			"from_bom": 1,
			"bom_no": bom_no,
			"fg_completed_qty": fg_completed_qty,
			"custom_rejection_qty": custom_rejection_qty,
			"posting_date": frappe.utils.nowdate(),
			"posting_time": frappe.utils.nowtime(),
		}
	)
	if custom_shift:
		se.custom_shift = custom_shift
	if from_warehouse:
		se.from_warehouse = from_warehouse
	if to_warehouse:
		se.to_warehouse = to_warehouse
	se.get_items()
	return se


def _create_manufacture_stock_entry(
	company: str,
	fg_item: str,
	rm_item: str,
	fg_qty: float = 100,
	rm_qty: float = 100,
	custom_shift: str | None = None,
	custom_rejection_qty: float = 0,
	fg_warehouse: str | None = None,
	rm_warehouse: str | None = None,
) -> frappe.Document:
	"""Create a Manufacture Stock Entry with raw material and finished good rows."""
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"purpose": "Manufacture",
			"stock_entry_type": "Manufacture",
			"company": company,
		}
	)

	if custom_shift:
		se.custom_shift = custom_shift
	if custom_rejection_qty:
		se.custom_rejection_qty = custom_rejection_qty

	# Raw material row
	se.append(
		"items",
		{
			"item_code": rm_item,
			"qty": rm_qty,
			"basic_rate": 50,
			"s_warehouse": rm_warehouse,
		},
	)

	# Finished good row
	se.append(
		"items",
		{
			"item_code": fg_item,
			"qty": fg_qty,
			"t_warehouse": fg_warehouse,
			"is_finished_item": 1,
		},
	)

	return se


def _set_shift_buffers(start_mins: int = 60, end_mins: int = 60) -> None:
	frappe.db.set_single_value("Manufacturing Settings", "shift_start_buffer_mins", start_mins)
	frappe.db.set_single_value("Manufacturing Settings", "shift_end_buffer_mins", end_mins)


class TestStockEntryHooks(FrappeTestCase):
	# Shift dates used by tests in this class (April 10-17, 2026)
	_SHIFT_DATES: ClassVar[list[str]] = [f"2026-04-{d}" for d in range(10, 18)]

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or "_Test Company"
		abbr = frappe.db.get_value("Company", cls.company, "abbr") or "_TC"
		cls.wip_warehouse = _get_or_create_warehouse(f"WIP Test - {abbr}", cls.company)
		cls.rm_warehouse = _get_or_create_warehouse(f"RM Test - {abbr}", cls.company)
		cls.rejection_warehouse = _get_or_create_warehouse(f"Rejection Test - {abbr}", cls.company)
		cls.fg_warehouse = _get_or_create_warehouse(f"FG Test - {abbr}", cls.company)
		cls.fg_item = _get_or_create_item("_Test FG Item For Shift")
		cls.rm_item = _get_or_create_item("_Test RM Item For Shift")

	@classmethod
	def tearDownClass(cls) -> None:
		"""End all Running shifts created by this test class to prevent leakage."""
		for shift_date in cls._SHIFT_DATES:
			for label in ("1", "2"):
				name = f"SHIFT-{shift_date}.Shift-{label}"
				if frappe.db.exists("Shift", name):
					frappe.db.set_value("Shift", name, "status", "Completed", update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed to persist cleanup
		super().tearDownClass()

	def test_shift_reference_auto_fills_branch(self) -> None:
		if not frappe.db.exists("Branch", "Test Branch SE"):
			frappe.get_doc({"doctype": "Branch", "branch": "Test Branch SE"}).insert(ignore_permissions=True)

		shift = _create_test_shift(
			shift_date="2026-04-10",
			branch="Test Branch SE",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertEqual(se.branch, "Test Branch SE")

	def test_shift_reference_auto_fills_planned_dates(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-11",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertIn("2026-04-11", str(se.custom_planned_start_date))
		self.assertIn("08:00:00", str(se.custom_planned_start_date))
		self.assertIn("16:00:00", str(se.custom_planned_end_date))

	def test_rejection_breakup_required_when_rejection_qty_positive(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-12",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_breakup_total_exceeds_rejection_qty_throws(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-13",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 3, "remark": "Surface crack"},
			],
		)

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_breakup_total_less_than_rejection_qty_throws(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-14",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 1, "remark": "Surface crack"},
			],
		)

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_breakup_reason_required(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-15",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(se, [{"qty": 5, "remark": "Missing reason"}])

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_breakup_valid_allows_save(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 2, "remark": "Surface crack"},
			],
		)

		se.save()

		self.assertEqual(len(se.custom_rejection_breakup), 2)

	def test_actual_times_within_buffer_pass(self) -> None:
		_set_shift_buffers()
		shift = _create_test_shift(
			shift_date="2026-04-12",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_actual_start_date = "2026-04-12 07:30:00"
		se.custom_actual_end_date = "2026-04-12 16:30:00"
		se.save()

		self.assertEqual(str(se.custom_actual_start_date), "2026-04-12 07:30:00")
		self.assertEqual(str(se.custom_actual_end_date), "2026-04-12 16:30:00")

	def test_actual_start_before_allowed_range_throws(self) -> None:
		_set_shift_buffers()
		shift = _create_test_shift(
			shift_date="2026-04-13",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_actual_start_date = "2026-04-13 06:59:00"
		se.custom_actual_end_date = "2026-04-13 16:00:00"

		with self.assertRaises(ValidationError):
			se.save()

	def test_actual_end_after_allowed_range_throws(self) -> None:
		_set_shift_buffers()
		shift = _create_test_shift(
			shift_date="2026-04-14",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_actual_start_date = "2026-04-14 08:00:00"
		se.custom_actual_end_date = "2026-04-14 17:01:00"

		with self.assertRaises(ValidationError):
			se.save()

	def test_actual_end_before_start_throws(self) -> None:
		_set_shift_buffers()
		shift = _create_test_shift(
			shift_date="2026-04-15",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_actual_start_date = "2026-04-15 09:00:00"
		se.custom_actual_end_date = "2026-04-15 08:59:00"

		with self.assertRaises(ValidationError):
			se.save()

	def test_shift_reference_planned_dates_for_evening_shift_label_2(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-20",
			shift_label="2",
			planned_start_time="16:00:00",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertIn("2026-04-20", str(se.custom_planned_start_date))
		self.assertIn("16:00:00", str(se.custom_planned_start_date))
		self.assertIn("2026-04-21", str(se.custom_planned_end_date))
		self.assertIn("00:00:00", str(se.custom_planned_end_date))

	def test_shift_reference_planned_end_rolls_over_when_shift_end_date_missing(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-15",
			planned_start_time="20:00:00",
			wip_warehouse=self.wip_warehouse,
		)
		frappe.db.set_value("Shift", shift.name, "shift_end_date", None, update_modified=False)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertIn("2026-04-16", str(se.custom_planned_end_date))
		self.assertIn("04:00:00", str(se.custom_planned_end_date))

	def test_shift_reference_auto_fills_warehouses(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-12",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			custom_shift=shift.name,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		self.assertEqual(se.from_warehouse, self.wip_warehouse)
		self.assertEqual(se.to_warehouse, self.wip_warehouse)

	def test_rejection_qty_deducts_from_finished_good(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-13",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 2, "remark": "Surface crack"},
			],
		)
		se.save()

		# Find the FG row (is_finished_item=1)
		fg_rows = [r for r in se.items if r.is_finished_item]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(fg_rows[0].qty, 95)

	def test_rejection_qty_creates_rejection_row(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-14",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 3, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 2, "remark": "Surface crack"},
			],
		)
		se.save()

		rejection_rows = [r for r in se.items if r.custom_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].qty, 5)
		self.assertEqual(rejection_rows[0].item_code, self.fg_item)
		self.assertEqual(rejection_rows[0].t_warehouse, self.rejection_warehouse)

	def test_rejection_qty_exceeding_fg_throws_error(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-15",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=150,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 150, "remark": "Over rejection"},
			],
		)

		with self.assertRaises(ValidationError):
			se.save()

	def test_rejection_row_is_idempotent_on_resave(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-16",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 4, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 6, "remark": "Surface crack"},
			],
		)
		se.save()

		# First save: 3 items (RM, FG@90, Rejection@10)
		self.assertEqual(len(se.items), 3)
		fg_rows = [r for r in se.items if r.is_finished_item]
		self.assertEqual(fg_rows[0].qty, 90)

		# Re-save should produce the same result
		se.save()
		self.assertEqual(len(se.items), 3)
		fg_rows = [r for r in se.items if r.is_finished_item]
		rejection_rows = [r for r in se.items if r.custom_is_rejection_item]
		self.assertEqual(fg_rows[0].qty, 90)
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].qty, 10)

	def test_rejection_qty_zero_produces_no_rejection_row(self) -> None:
		shift = _create_test_shift(
			shift_date="2026-04-17",
			wip_warehouse=self.wip_warehouse,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=0,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.save()

		rejection_rows = [r for r in se.items if r.get("custom_is_rejection_item")]
		self.assertEqual(len(rejection_rows), 0)

	def test_unplanned_losses_can_be_added_to_stock_entry(self) -> None:
		_ensure_downtime_reasons()

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)

		se.append(
			"custom_unplanned_losses",
			{
				"downtime_reason": "Tea Break",
				"start_time": "10:00:00",
				"end_time": "10:15:00",
			},
		)
		se.save()

		self.assertEqual(len(se.custom_unplanned_losses), 1)
		self.assertEqual(se.custom_unplanned_losses[0].downtime_reason, "Tea Break")


class TestGetItemsWithRejection(FrappeTestCase):
	"""Tests for the get_items_with_rejection API."""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		_ensure_rejection_breakup_doctype()
		_ensure_rejection_reason_doctype()
		_ensure_rejection_reasons()
		_ensure_rejection_breakup_custom_field()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or "_Test Company"
		abbr = frappe.db.get_value("Company", cls.company, "abbr") or "_TC"
		cls.wip_warehouse = _get_or_create_warehouse(f"WIP Test - {abbr}", cls.company)
		cls.rm_warehouse = _get_or_create_warehouse(f"RM Test - {abbr}", cls.company)
		cls.rejection_warehouse = _get_or_create_warehouse(f"Rejection Test - {abbr}", cls.company)
		cls.fg_warehouse = _get_or_create_warehouse(f"FG Test - {abbr}", cls.company)
		cls.fg_item = _get_or_create_item("_Test FG Item For Shift")
		cls.rm_item = _get_or_create_item("_Test RM Item For Shift")
		cls.bom_no = _get_or_create_bom(cls.fg_item, cls.rm_item, cls.company)

	def _call_api(self, **overrides) -> list[dict]:
		"""Build a Stock Entry doc dict, serialize it, and call get_items_with_rejection."""
		from production_entry_app.production_entry_app.api import get_items_with_rejection

		doc_dict = {
			"doctype": "Stock Entry",
			"purpose": "Manufacture",
			"stock_entry_type": "Manufacture",
			"company": self.company,
			"from_bom": 1,
			"bom_no": self.bom_no,
			"fg_completed_qty": 100,
			"custom_rejection_qty": 0,
			"from_warehouse": self.rm_warehouse,
			"to_warehouse": self.fg_warehouse,
		}
		doc_dict.update(overrides)
		return get_items_with_rejection(json.dumps(doc_dict))

	def test_get_items_with_rejection_returns_bom_items(self) -> None:
		"""API should return at least RM + FG rows from BOM."""
		items = self._call_api()
		item_codes = [r["item_code"] for r in items]
		self.assertIn(self.rm_item, item_codes)
		self.assertIn(self.fg_item, item_codes)

	def test_get_items_with_rejection_deducts_from_fg(self) -> None:
		"""FG row qty should be reduced by rejection qty."""
		shift = _create_test_shift(
			shift_date="2026-04-20",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		items = self._call_api(
			custom_rejection_qty=10,
			custom_shift=shift.name,
		)
		fg_rows = [r for r in items if r.get("is_finished_item")]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(fg_rows[0]["qty"], 90)

	def test_get_items_with_rejection_adds_rejection_row(self) -> None:
		"""Rejection row must have is_scrap_item=1, correct qty, rejection warehouse, and same basic_rate as FG."""
		shift = _create_test_shift(
			shift_date="2026-04-21",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		items = self._call_api(
			custom_rejection_qty=10,
			custom_shift=shift.name,
		)
		fg_rows = [r for r in items if r.get("is_finished_item")]
		rejection_rows = [r for r in items if r.get("custom_is_rejection_item")]
		self.assertEqual(len(rejection_rows), 1)
		rr = rejection_rows[0]
		self.assertEqual(rr["qty"], 10)
		self.assertEqual(rr["item_code"], self.fg_item)
		self.assertEqual(rr["t_warehouse"], self.rejection_warehouse)
		self.assertTrue(rr.get("is_scrap_item"), "rejection row must have is_scrap_item=1")
		# basic_rate must match FG row
		fg_rate = fg_rows[0].get("basic_rate", 0)
		self.assertGreater(fg_rate, 0, "FG row must have a basic_rate")
		self.assertEqual(rr.get("basic_rate"), fg_rate, "rejection basic_rate must equal FG basic_rate")

	def test_rejection_row_basic_rate_matches_fg_on_save(self) -> None:
		"""Rejection row basic_rate must match FG row basic_rate when saved via validate hook."""
		shift = _create_test_shift(
			shift_date="2026-04-23",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=100,
			custom_shift=shift.name,
			custom_rejection_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		_append_rejection_breakup_rows(
			se,
			[
				{"rejection_reason": "Burr", "qty": 6, "remark": "Edge burr"},
				{"rejection_reason": "Crack", "qty": 4, "remark": "Surface crack"},
			],
		)
		# Set a known basic_rate on the FG row before save
		for row in se.items:
			if row.is_finished_item:
				row.basic_rate = 200
		se.save()

		fg_rows = [r for r in se.items if r.is_finished_item]
		rejection_rows = [r for r in se.items if r.custom_is_rejection_item]
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0].basic_rate, fg_rows[0].basic_rate)

	def test_custom_is_rejection_item_field_is_visible(self) -> None:
		"""The custom_is_rejection_item Custom Field must not be hidden."""
		hidden = frappe.db.get_value("Custom Field", "Stock Entry Detail-custom_is_rejection_item", "hidden")
		self.assertFalse(hidden, "custom_is_rejection_item must be visible (hidden=0)")

	def test_get_items_with_rejection_zero_rejection(self) -> None:
		"""No rejection row when rejection_qty is 0."""
		items = self._call_api(custom_rejection_qty=0)
		rejection_rows = [r for r in items if r.get("custom_is_rejection_item")]
		self.assertEqual(len(rejection_rows), 0)

	def test_get_items_with_rejection_mirrors_browser_flow(self) -> None:
		"""Simulate browser: doc already has items from prior get_items() call."""
		shift = _create_test_shift(
			shift_date="2026-04-22",
			wip_warehouse=self.wip_warehouse,
			rejection_warehouse=self.rejection_warehouse,
		)
		# First, build a SE with BOM items (like ERPNext auto-populate on fg_completed_qty change)
		se = _create_bom_stock_entry(
			company=self.company,
			bom_no=self.bom_no,
			fg_completed_qty=100,
			from_warehouse=self.rm_warehouse,
			to_warehouse=self.fg_warehouse,
		)
		# Now build the dict the browser would send (includes existing items)
		doc_dict = se.as_dict()
		doc_dict["custom_rejection_qty"] = 15
		doc_dict["custom_shift"] = shift.name

		from production_entry_app.production_entry_app.api import get_items_with_rejection

		items = get_items_with_rejection(json.dumps(doc_dict, default=str))

		fg_rows = [r for r in items if r.get("is_finished_item")]
		rejection_rows = [r for r in items if r.get("custom_is_rejection_item")]
		self.assertEqual(len(fg_rows), 1)
		self.assertEqual(fg_rows[0]["qty"], 85)
		self.assertEqual(len(rejection_rows), 1)
		self.assertEqual(rejection_rows[0]["qty"], 15)
		self.assertTrue(rejection_rows[0].get("is_scrap_item"))
		self.assertEqual(rejection_rows[0]["t_warehouse"], self.rejection_warehouse)

	def test_rejection_qty_field_depends_on_from_bom(self) -> None:
		"""The custom_rejection_qty Custom Field should have depends_on set."""
		depends_on = frappe.db.get_value("Custom Field", "Stock Entry-custom_rejection_qty", "depends_on")
		self.assertEqual(depends_on, "eval:doc.from_bom")

	@classmethod
	def tearDownClass(cls) -> None:
		# Clean up any Running shifts used in this class
		for day in ("20", "21", "22", "23"):
			name = f"SHIFT-2026-04-{day}.Shift-1"
			if frappe.db.exists("Shift", name):
				frappe.db.set_value("Shift", name, "status", "Completed", update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit - needed to persist cleanup
		super().tearDownClass()


class TestDieToolCounter(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		_ensure_die_tool_counter_doctype()
		_ensure_item_die_tool_fields()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or "_Test Company"
		abbr = frappe.db.get_value("Company", cls.company, "abbr") or "_TC"
		cls.rm_warehouse = _get_or_create_warehouse(f"DT RM Test - {abbr}", cls.company)
		cls.fg_warehouse = _get_or_create_warehouse(f"DT FG Test - {abbr}", cls.company)
		cls.rm_item = _get_or_create_item("_Test Die Tool RM")
		cls.fg_item = _get_or_create_item("_Test Die Tool FG")
		_set_item_die_tool_fields(cls.fg_item, strokes_per_unit=12, stroke_capacity=1000)

	def test_die_tool_counter_increments_on_submit(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			on_submit_stock_entry,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=10,
			rm_qty=10,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_rejection_qty = 2

		on_submit_stock_entry(se, "on_submit")

		counter = frappe.get_doc("Die Tool Counter", self.fg_item)
		self.assertEqual(counter.current_stroke_count, 144)
		self.assertEqual(counter.stroke_capacity, 1000)

	def test_die_tool_counter_decrements_on_cancel(self) -> None:
		from production_entry_app.production_entry_app.overrides.stock_entry_hooks import (
			on_cancel_stock_entry,
			on_submit_stock_entry,
		)

		se = _create_manufacture_stock_entry(
			company=self.company,
			fg_item=self.fg_item,
			rm_item=self.rm_item,
			fg_qty=5,
			rm_qty=5,
			fg_warehouse=self.fg_warehouse,
			rm_warehouse=self.rm_warehouse,
		)
		se.custom_rejection_qty = 1

		on_submit_stock_entry(se, "on_submit")
		on_cancel_stock_entry(se, "on_cancel")

		counter = frappe.get_doc("Die Tool Counter", self.fg_item)
		self.assertEqual(counter.current_stroke_count, 0)

	def test_die_tool_counter_reset(self) -> None:
		from production_entry_app.production_entry_app.api import reset_die_tool_counter

		if frappe.db.exists("Die Tool Counter", self.fg_item):
			frappe.db.set_value(
				"Die Tool Counter",
				self.fg_item,
				{
					"current_stroke_count": 250,
					"stroke_capacity": 1000,
				},
			)
		else:
			counter = frappe.get_doc(
				{
					"doctype": "Die Tool Counter",
					"die_tool_item": self.fg_item,
					"current_stroke_count": 250,
					"stroke_capacity": 1000,
				}
			)
			counter.insert(ignore_permissions=True)

		reset = reset_die_tool_counter(self.fg_item)
		updated = frappe.get_doc("Die Tool Counter", self.fg_item)
		self.assertEqual(updated.current_stroke_count, 0)
		self.assertEqual(reset["current_stroke_count"], 0)
		self.assertEqual(updated.last_reset_by, frappe.session.user)
