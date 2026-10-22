from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.joint_production import JOINT_PRODUCTION_STOCK_ENTRY_TYPE
from production_entry_app.production_entry_app.utils.die_tool_item import (
	apply_bom_die_tool_item,
	prescribed_die_tool_item,
)
from production_entry_app.production_entry_app.utils.test_bootstrap import (
	ensure_default_bom,
	ensure_item,
	ensure_production_owned_joint_metadata,
)


class TestPrescribedDieToolItem(FrappeTestCase):
	def test_single_bom_die_tool_item_is_returned(self) -> None:
		self.assertEqual(prescribed_die_tool_item(["DIE-1", "", None, "DIE-1"]), "DIE-1")

	def test_blank_bom_die_tool_items_leave_the_entry_unset(self) -> None:
		self.assertEqual(prescribed_die_tool_item(["", None]), "")

	def test_different_bom_die_tool_items_leave_the_entry_selectable(self) -> None:
		self.assertEqual(prescribed_die_tool_item(["DIE-1", "DIE-2"]), "")


class TestApplyBomDieToolItem(FrappeTestCase):
	def setUp(self) -> None:
		ensure_production_owned_joint_metadata()
		_ensure_bom_die_tool_item_field()
		suffix = frappe.generate_hash(length=6)
		self.company = frappe.db.get_value("Company", {}, "name")
		self.fg_item = ensure_item(f"_Die Tool FG {suffix}")
		self.rm_item = ensure_item(f"_Die Tool RM {suffix}")
		self.die_item = ensure_item(f"_Die Tool Item {suffix}")
		self.die_other = ensure_item(f"_Die Tool Other {suffix}")
		self.bom = ensure_default_bom(self.fg_item, self.rm_item, self.company)
		self.bom_two = ensure_default_bom(
			ensure_item(f"_Die Tool FG2 {suffix}"),
			self.rm_item,
			self.company,
		)

	def test_shift_manufacture_copies_die_tool_item_from_bom(self) -> None:
		frappe.db.set_value("BOM", self.bom, "custom_pea_die_tool_item", self.die_item, update_modified=False)
		doc = frappe._dict(
			custom_pea_shift="SHIFT-1",
			purpose="Manufacture",
			from_bom=1,
			bom_no=self.bom,
			custom_pea_die_tool_item="USER-DIE",
		)
		doc.set = lambda fieldname, value: doc.update({fieldname: value})

		apply_bom_die_tool_item(doc)

		self.assertEqual(doc.custom_pea_die_tool_item, self.die_item)

	def test_shift_manufacture_keeps_selected_item_when_bom_has_no_die_tool(self) -> None:
		frappe.db.set_value("BOM", self.bom, "custom_pea_die_tool_item", None, update_modified=False)
		doc = frappe._dict(
			custom_pea_shift="SHIFT-1",
			purpose="Manufacture",
			from_bom=1,
			bom_no=self.bom,
			custom_pea_die_tool_item=self.die_item,
		)
		doc.set = lambda fieldname, value: doc.update({fieldname: value})

		apply_bom_die_tool_item(doc)

		self.assertEqual(doc.custom_pea_die_tool_item, self.die_item)

	def test_shift_manufacture_fills_die_tool_item_from_bom_when_entry_blank(self) -> None:
		frappe.db.set_value("BOM", self.bom, "custom_pea_die_tool_item", self.die_item, update_modified=False)
		doc = frappe._dict(
			custom_pea_shift="SHIFT-1",
			purpose="Manufacture",
			from_bom=1,
			bom_no=self.bom,
			custom_pea_die_tool_item="",
		)
		doc.set = lambda fieldname, value: doc.update({fieldname: value})

		apply_bom_die_tool_item(doc)

		self.assertEqual(doc.custom_pea_die_tool_item, self.die_item)

	def test_shift_manufacture_without_die_tool_item_anywhere_is_rejected(self) -> None:
		frappe.db.set_value("BOM", self.bom, "custom_pea_die_tool_item", None, update_modified=False)
		doc = frappe._dict(
			custom_pea_shift="SHIFT-1",
			purpose="Manufacture",
			from_bom=1,
			bom_no=self.bom,
			custom_pea_die_tool_item="",
		)
		doc.set = lambda fieldname, value: doc.update({fieldname: value})

		with self.assertRaisesRegex(frappe.ValidationError, "Set Die Tool Item on BOM"):
			apply_bom_die_tool_item(doc)

	def test_joint_production_lines_supply_bom_names_for_die_tool_item(self) -> None:
		frappe.db.set_value("BOM", self.bom, "custom_pea_die_tool_item", self.die_item, update_modified=False)
		doc = frappe._dict(
			custom_pea_shift="SHIFT-1",
			purpose="Repack",
			stock_entry_type=JOINT_PRODUCTION_STOCK_ENTRY_TYPE,
			custom_pea_joint_production_lines=[{"bom_no": self.bom, "gross_qty": 10, "rejection_qty": 0}],
			custom_pea_die_tool_item="",
		)
		doc.set = lambda fieldname, value: doc.update({fieldname: value})

		apply_bom_die_tool_item(doc)

		self.assertEqual(doc.custom_pea_die_tool_item, self.die_item)

	def test_joint_production_lines_apply_first_bom_die_tool_when_boms_disagree_and_entry_blank(
		self,
	) -> None:
		frappe.db.set_value("BOM", self.bom, "custom_pea_die_tool_item", self.die_item, update_modified=False)
		frappe.db.set_value(
			"BOM", self.bom_two, "custom_pea_die_tool_item", self.die_other, update_modified=False
		)
		doc = frappe._dict(
			custom_pea_shift="SHIFT-1",
			purpose="Repack",
			stock_entry_type=JOINT_PRODUCTION_STOCK_ENTRY_TYPE,
			custom_pea_joint_production_lines=[
				{"bom_no": self.bom, "gross_qty": 10, "rejection_qty": 0},
				{"bom_no": self.bom_two, "gross_qty": 10, "rejection_qty": 0},
			],
			custom_pea_die_tool_item="",
		)
		doc.set = lambda fieldname, value: doc.update({fieldname: value})

		apply_bom_die_tool_item(doc)

		self.assertEqual(doc.custom_pea_die_tool_item, self.die_item)

	def test_joint_production_lines_keep_operator_die_tool_when_boms_disagree(self) -> None:
		frappe.db.set_value("BOM", self.bom, "custom_pea_die_tool_item", self.die_item, update_modified=False)
		frappe.db.set_value(
			"BOM", self.bom_two, "custom_pea_die_tool_item", self.die_other, update_modified=False
		)
		doc = frappe._dict(
			custom_pea_shift="SHIFT-1",
			purpose="Repack",
			stock_entry_type=JOINT_PRODUCTION_STOCK_ENTRY_TYPE,
			custom_pea_joint_production_lines=[
				{"bom_no": self.bom, "gross_qty": 10, "rejection_qty": 0},
				{"bom_no": self.bom_two, "gross_qty": 10, "rejection_qty": 0},
			],
			custom_pea_die_tool_item=self.die_other,
		)
		doc.set = lambda fieldname, value: doc.update({fieldname: value})

		apply_bom_die_tool_item(doc)

		self.assertEqual(doc.custom_pea_die_tool_item, self.die_other)

	def test_stock_only_entry_does_not_copy_bom_die_tool_item(self) -> None:
		frappe.db.set_value("BOM", self.bom, "custom_pea_die_tool_item", self.die_item, update_modified=False)
		doc = frappe._dict(
			custom_pea_shift="",
			purpose="Manufacture",
			from_bom=1,
			bom_no=self.bom,
			custom_pea_die_tool_item="",
		)
		doc.set = lambda fieldname, value: doc.update({fieldname: value})

		apply_bom_die_tool_item(doc)

		self.assertEqual(doc.custom_pea_die_tool_item, "")

	def test_submitted_bom_accepts_a_die_tool_item_change(self) -> None:
		field = frappe.get_meta("BOM", cached=False).get_field("custom_pea_die_tool_item")
		self.assertEqual(int(field.allow_on_submit or 0), 1)
		bom = frappe.get_doc("BOM", self.bom)
		bom.custom_pea_die_tool_item = self.die_item
		bom.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("BOM", self.bom, "custom_pea_die_tool_item"), self.die_item)


def _ensure_bom_die_tool_item_field() -> None:
	if frappe.get_meta("BOM", cached=False).has_field("custom_pea_die_tool_item"):
		return
	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "BOM",
			"fieldname": "custom_pea_die_tool_item",
			"label": "Die Tool Item",
			"fieldtype": "Link",
			"options": "Item",
			"allow_on_submit": 1,
			"insert_after": "custom_operation",
			"module": "Production Entry App",
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="BOM")
