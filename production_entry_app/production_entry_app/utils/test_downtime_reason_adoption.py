from __future__ import annotations

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.tests.support import host_parity
from production_entry_app.production_entry_app.utils.downtime_reason_adoption import (
	adopt_host_downtime_reason,
	adopt_host_downtime_reason_schema,
)


class TestSchemaAdoptionNoop(FrappeTestCase):
	def setUp(self) -> None:
		host_parity.clear_adoption_export()
		self.addCleanup(host_parity.clear_adoption_export)
		self.addCleanup(host_parity.restore_app_downtime_reason)

	def test_schema_adoption_is_noop_when_doctype_is_app_owned(self) -> None:
		host_parity.restore_app_downtime_reason()
		before = host_parity.doctype_snapshot()

		adopt_host_downtime_reason_schema()

		self.assertEqual(host_parity.doctype_snapshot(), before)
		self.assertFalse(os.path.exists(host_parity.export_path()))

	def test_schema_adoption_is_noop_when_doctype_is_absent(self) -> None:
		host_parity.delete_downtime_reason_doctype()

		adopt_host_downtime_reason_schema()

		self.assertFalse(frappe.db.exists("DocType", "Downtime Reason"))
		self.assertFalse(os.path.exists(host_parity.export_path()))


class TestSchemaAdoptionReshape(FrappeTestCase):
	def setUp(self) -> None:
		host_parity.clear_adoption_export()
		self.addCleanup(host_parity.clear_adoption_export)
		self.addCleanup(host_parity.restore_app_downtime_reason)
		host_parity.restore_app_downtime_reason()
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype()
		host_parity.insert_host_downtime_reason("Setup Time", submit=True)
		host_parity.insert_host_downtime_reason("MATERIAL SHORT PART NO.84562")

	def test_schema_adoption_reshapes_the_host_doctype_in_place(self) -> None:
		adopt_host_downtime_reason_schema()

		snapshot = host_parity.doctype_snapshot()
		self.assertEqual(snapshot["module"], "Production Entry App")
		self.assertEqual(snapshot["custom"], 0)
		self.assertEqual(snapshot["autoname"], "field:code")
		self.assertEqual(snapshot["is_submittable"], 0)
		self.assertEqual(snapshot["fieldnames"], ("code", "description", "is_active"))
		self.assertEqual(frappe.get_value("DocType", "Downtime Reason", "naming_rule"), "By fieldname")

	def test_schema_adoption_preserves_rows_and_normalizes_them(self) -> None:
		adopt_host_downtime_reason_schema()

		rows = {
			row.name: row
			for row in frappe.get_all(
				"Downtime Reason", fields=["name", "description", "is_active", "docstatus"]
			)
		}
		self.assertEqual(set(rows), {"Setup Time", "MATERIAL SHORT PART NO.84562"})
		for name, row in rows.items():
			self.assertEqual(row.description, name)
			self.assertEqual(row.docstatus, 0)
			self.assertEqual(row.is_active, 1)

	def test_schema_adoption_writes_recovery_export_before_mutating(self) -> None:
		adopt_host_downtime_reason_schema()

		path = host_parity.export_path()
		self.assertTrue(os.path.exists(path))
		export = json.load(open(path))
		self.assertEqual(
			[reason["name"] for reason in export["reasons"]],
			["Setup Time", "MATERIAL SHORT PART NO.84562"],
		)
		self.assertEqual(export["reasons"][0]["docstatus"], 1)


class TestFullAdoption(FrappeTestCase):
	def setUp(self) -> None:
		host_parity.clear_adoption_export()
		self.addCleanup(host_parity.clear_adoption_export)
		self.addCleanup(host_parity.restore_app_downtime_reason)
		host_parity.restore_app_downtime_reason()
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype()
		host_parity.insert_host_downtime_reason("Setup Time", submit=True)
		host_parity.insert_host_downtime_reason("Inventory")
		host_parity.install_host_loss_time()
		self.addCleanup(host_parity.remove_host_loss_time)
		self.stock_entry = host_parity.make_host_stock_entry_with_loss_times(["Setup Time", "Inventory"])

	def _reason_names(self) -> list[str]:
		return sorted(frappe.get_all("Downtime Reason", pluck="name"))

	def test_full_adoption_converts_all_masters_to_codes(self) -> None:
		adopt_host_downtime_reason()

		names = self._reason_names()
		self.assertTrue(names)
		for name in names:
			self.assertRegex(name, r"^\d{2}$")
		self.assertIn("01", names)
		self.assertEqual(frappe.db.get_value("Downtime Reason", "01", "description"), "Setup")
		self.assertEqual(frappe.db.get_value("Downtime Reason", "23", "description"), "Inventory")
		self.assertTrue(
			set(frappe.get_all("Downtime Reason", pluck="name")) >= {f"{i:02d}" for i in range(23)}
		)

	def test_full_adoption_rewrites_loss_time_links(self) -> None:
		self.assertEqual(
			sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["Inventory", "Setup Time"]
		)

		adopt_host_downtime_reason()

		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])

	def test_full_adoption_is_idempotent(self) -> None:
		adopt_host_downtime_reason()
		after_first = frappe.get_all(
			"Downtime Reason", fields=["name", "code", "description", "is_active"], order_by="name"
		)

		adopt_host_downtime_reason()

		self.assertEqual(
			frappe.get_all(
				"Downtime Reason",
				fields=["name", "code", "description", "is_active"],
				order_by="name",
			),
			after_first,
		)

	def test_full_adoption_leaves_host_owned_stock_entry_metadata_untouched(self) -> None:
		branch_reqd = frappe.db.get_value(
			"Property Setter",
			{"doc_type": "Stock Entry", "field_name": "branch", "property": "reqd"},
			"value",
		)
		se_fields_before = tuple(f.fieldname for f in frappe.get_meta("Stock Entry").fields)
		bom_has_operation = frappe.get_meta("BOM").get_field("custom_operation") is not None

		adopt_host_downtime_reason()

		self.assertEqual(
			frappe.db.get_value(
				"Property Setter",
				{"doc_type": "Stock Entry", "field_name": "branch", "property": "reqd"},
				"value",
			),
			branch_reqd,
		)
		self.assertEqual(tuple(f.fieldname for f in frappe.get_meta("Stock Entry").fields), se_fields_before)
		self.assertEqual(frappe.get_meta("BOM").get_field("custom_operation") is not None, bom_has_operation)


class TestAdoptionFailurePaths(FrappeTestCase):
	def setUp(self) -> None:
		host_parity.clear_adoption_export()
		self.addCleanup(host_parity.clear_adoption_export)
		self.addCleanup(host_parity.restore_app_downtime_reason)
		host_parity.restore_app_downtime_reason()
		host_parity.delete_downtime_reason_doctype()

	def test_schema_adoption_throws_on_unexpected_shape(self) -> None:
		host_parity.install_host_downtime_reason_doctype(
			extra_fields=({"fieldname": "code", "fieldtype": "Data"},)
		)
		host_parity.insert_host_downtime_reason("Setup Time")
		before = host_parity.doctype_snapshot()

		with self.assertRaises(frappe.ValidationError):
			adopt_host_downtime_reason_schema()

		self.assertEqual(host_parity.doctype_snapshot(), before)
		self.assertFalse(os.path.exists(host_parity.export_path()))
		self.assertTrue(frappe.db.exists("Downtime Reason", "Setup Time"))


class TestAdoptionRecovery(FrappeTestCase):
	def setUp(self) -> None:
		host_parity.clear_adoption_export()
		self.addCleanup(host_parity.clear_adoption_export)
		self.addCleanup(host_parity.restore_app_downtime_reason)
		host_parity.restore_app_downtime_reason()
		host_parity.delete_downtime_reason_doctype()
		host_parity.install_host_downtime_reason_doctype()
		host_parity.insert_host_downtime_reason("Setup Time", submit=True)
		host_parity.insert_host_downtime_reason("Inventory")
		host_parity.install_host_loss_time()
		self.addCleanup(host_parity.remove_host_loss_time)
		self.stock_entry = host_parity.make_host_stock_entry_with_loss_times(["Setup Time", "Inventory"])

	def test_verification_failure_throws_with_details(self) -> None:
		adopt_host_downtime_reason()
		frappe.db.set_value(
			"Loss Time",
			{"parent": self.stock_entry, "loss_type": "01"},
			"loss_type",
			"Setup Time",
			update_modified=False,
		)

		with self.assertRaises(frappe.ValidationError) as raised:
			adopt_host_downtime_reason()

		self.assertIn("verification failed", str(raised.exception))
		self.assertIn("Setup Time", str(raised.exception))

	def test_partial_adoption_converges_on_full_sequence_rerun(self) -> None:
		adopt_host_downtime_reason_schema()

		adopt_host_downtime_reason()

		names = sorted(frappe.get_all("Downtime Reason", pluck="name"))
		self.assertTrue(all(len(name) == 2 and name.isdigit() for name in names))
		self.assertEqual(sorted(host_parity.loss_time_reason_values(self.stock_entry)), ["01", "23"])
