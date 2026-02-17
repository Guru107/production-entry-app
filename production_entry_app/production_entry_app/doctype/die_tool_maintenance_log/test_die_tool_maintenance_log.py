# Copyright (c) 2026, Gurudatt Kulkarni and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.doctype.die_tool_maintenance_log.die_tool_maintenance_log import (
	_sanitize_item_code,
)


class TestDieToolMaintenanceLog(FrappeTestCase):
	item_code = "_Test Die Tool Maintenance FG"

	def tearDown(self) -> None:
		frappe.db.rollback()

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		if not frappe.db.exists("DocType", "Die Tool Counter"):
			frappe.reload_doc("production_entry_app", "doctype", "die_tool_counter")

	def setUp(self) -> None:
		self._ensure_item(self.item_code)

	@classmethod
	def tearDownClass(cls) -> None:
		for name in frappe.get_all(
			"Die Tool Maintenance Log", filters={"die_tool_item": cls.item_code}, pluck="name"
		):
			frappe.db.set_value("Die Tool Maintenance Log", name, "docstatus", 0, update_modified=False)
			frappe.delete_doc("Die Tool Maintenance Log", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Die Tool Counter", cls.item_code):
			frappe.delete_doc("Die Tool Counter", cls.item_code, force=True, ignore_permissions=True)
		super().tearDownClass()

	@staticmethod
	def _ensure_item(item_code: str) -> str:
		if frappe.db.exists("Item", item_code):
			return item_code
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
		return item_code

	def test_sanitize_item_code_replaces_special_characters(self) -> None:
		self.assertEqual(_sanitize_item_code("FG 1 (A)&$"), "FG-1--A---")
		self.assertEqual(_sanitize_item_code("FG_1-OK"), "FG_1-OK")

	def test_autoname_uses_item_and_date_prefix(self) -> None:
		sanitized_item = _sanitize_item_code(self.item_code)
		doc = frappe.get_doc(
			{
				"doctype": "Die Tool Maintenance Log",
				"die_tool_item": self.item_code,
				"maintenance_date": "2026-02-11 12:30:00",
				"remarks": "Autoname test",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith(f"DTML-{sanitized_item}-2026-02-11."))

	def test_submit_resets_die_tool_counter(self) -> None:
		counter = frappe.get_doc(
			{
				"doctype": "Die Tool Counter",
				"die_tool_item": self.item_code,
				"current_stroke_count": 321,
				"stroke_capacity": 1000,
				"warning_threshold_pct": 90,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(float(counter.current_stroke_count), 321.0)

		log = frappe.get_doc(
			{
				"doctype": "Die Tool Maintenance Log",
				"die_tool_item": self.item_code,
				"maintenance_date": "2026-02-12 08:00:00",
				"remarks": "Reset test",
			}
		).insert(ignore_permissions=True)
		log.submit()

		counter.reload()
		self.assertEqual(float(counter.current_stroke_count), 0.0)
		self.assertEqual(str(counter.last_reset_on), "2026-02-12 08:00:00")
