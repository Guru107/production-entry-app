from __future__ import annotations

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase


def _ensure_downtime_reasons() -> None:
	"""Ensure Tea Break and Lunch Break Downtime Reasons exist."""
	for name in ("Tea Break", "Lunch Break"):
		if not frappe.db.exists("Downtime Reason", name):
			frappe.get_doc({"doctype": "Downtime Reason", "downtime_reason_name": name}).insert()


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


def _create_test_shift(
	shift_date: str = "2026-04-10",
	shift_label: str = "1",
	branch: str | None = None,
	wip_warehouse: str | None = None,
	rejection_warehouse: str | None = None,
) -> frappe.Document:
	"""Create and return a test Shift."""
	_ensure_downtime_reasons()
	name = f"SHIFT-{shift_date}.Shift-{shift_label}"
	if frappe.db.exists("Shift", name):
		frappe.delete_doc("Shift", name, force=True, ignore_permissions=True)

	doc_data = {
		"doctype": "Shift",
		"shift_label": shift_label,
		"shift_duration": "8",
		"shift_date": shift_date,
		"planned_start_time": "08:00:00",
	}
	if branch:
		doc_data["branch"] = branch
	if wip_warehouse:
		doc_data["work_in_progress_warehouse"] = wip_warehouse
	if rejection_warehouse:
		doc_data["rejection_warehouse"] = rejection_warehouse

	return frappe.get_doc(doc_data).insert()


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


class TestStockEntryHooks(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or "_Test Company"
		abbr = frappe.db.get_value("Company", cls.company, "abbr") or "_TC"
		cls.wip_warehouse = _get_or_create_warehouse(f"WIP Test - {abbr}", cls.company)
		cls.rm_warehouse = _get_or_create_warehouse(f"RM Test - {abbr}", cls.company)
		cls.rejection_warehouse = _get_or_create_warehouse(f"Rejection Test - {abbr}", cls.company)
		cls.fg_warehouse = _get_or_create_warehouse(f"FG Test - {abbr}", cls.company)
		cls.fg_item = _get_or_create_item("_Test FG Item For Shift")
		cls.rm_item = _get_or_create_item("_Test RM Item For Shift")

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

		self.assertEqual(se.custom_branch, "Test Branch SE")

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
