from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.model.rename_doc import rename_doc
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.downtime_reason_conversion import (
	EXTRA_DOWNTIME_REASON_CODES,
	LEGACY_DOWNTIME_REASON_CODES,
	convert_legacy_downtime_reasons,
)

_CONVERSION_MODULE = "production_entry_app.production_entry_app.utils.downtime_reason_conversion"


def _delete_all_downtime_reasons() -> None:
	frappe.db.delete("Downtime Reason")


def _insert_legacy_master(legacy_name: str, scratch_code: str) -> None:
	"""Insert a pre-migration style master whose document name is the legacy description.

	The doctype validates ``code`` as a two-digit number, so the master is inserted
	under a scratch coded name and force-renamed to the legacy description, mirroring
	the pre-migration state where the document name was the reason description.
	"""
	frappe.get_doc(
		{
			"doctype": "Downtime Reason",
			"code": scratch_code,
			"description": legacy_name,
			"is_active": 1,
		}
	).insert(ignore_permissions=True)
	rename_doc("Downtime Reason", scratch_code, legacy_name, force=True, show_alert=False)


class TestDowntimeReasonConversion(FrappeTestCase):
	def test_conversion_merges_a_legacy_master_into_the_seeded_coded_master(self) -> None:
		_delete_all_downtime_reasons()
		_insert_legacy_master("Tea Break", "14")

		convert_legacy_downtime_reasons()

		self.assertFalse(frappe.db.exists("Downtime Reason", "Tea Break"))
		row = frappe.db.get_value("Downtime Reason", "14", ["code", "description", "is_active"], as_dict=True)
		self.assertEqual(row.code, "14")
		self.assertEqual(row.description, "Tea Break")
		self.assertTrue(row.is_active)

	def test_conversion_is_a_noop_on_rerun(self) -> None:
		_delete_all_downtime_reasons()
		_insert_legacy_master("Lunch Break", "19")

		convert_legacy_downtime_reasons()
		before = frappe.get_all(
			"Downtime Reason", fields=["name", "code", "description", "is_active"], order_by="name"
		)

		convert_legacy_downtime_reasons()

		self.assertEqual(
			frappe.get_all(
				"Downtime Reason", fields=["name", "code", "description", "is_active"], order_by="name"
			),
			before,
		)
		self.assertTrue(frappe.db.exists("Downtime Reason", "19"))

	def test_conversion_retargets_orphaned_loss_entry_references_when_master_is_absent(self) -> None:
		with (
			patch(f"{_CONVERSION_MODULE}.seed_standard_downtime_reasons"),
			patch(f"{_CONVERSION_MODULE}.frappe.db.exists", return_value=False),
			patch(f"{_CONVERSION_MODULE}.rename_doc") as rename_doc,
			patch(f"{_CONVERSION_MODULE}.frappe.db.set_value") as set_value,
		):
			convert_legacy_downtime_reasons()

		rename_doc.assert_not_called()
		self.assertEqual(set_value.call_count, len(LEGACY_DOWNTIME_REASON_CODES))
		for legacy_name, code in LEGACY_DOWNTIME_REASON_CODES.items():
			set_value.assert_any_call(
				"Loss Entry",
				{"downtime_reason": legacy_name},
				"downtime_reason",
				code,
				update_modified=False,
			)

	def test_conversion_renames_instead_of_retargeting_when_master_exists(self) -> None:
		with (
			patch(f"{_CONVERSION_MODULE}.seed_standard_downtime_reasons"),
			patch(
				f"{_CONVERSION_MODULE}.frappe.db.exists",
				side_effect=lambda doctype, name=None: name == "Power Off",
			),
			patch(f"{_CONVERSION_MODULE}.rename_doc") as rename_doc,
			patch(f"{_CONVERSION_MODULE}.frappe.db.set_value") as set_value,
		):
			convert_legacy_downtime_reasons()

		rename_doc.assert_called_once_with(
			"Downtime Reason", "Power Off", "11", merge=True, force=True, show_alert=False
		)
		self.assertEqual(set_value.call_count, len(LEGACY_DOWNTIME_REASON_CODES) - 1)
		self.assertFalse(
			any(call.args[1] == {"downtime_reason": "Power Off"} for call in set_value.call_args_list)
		)


class TestExtraDowntimeReasonConversion(FrappeTestCase):
	def test_curated_extra_merges_into_the_standard_code(self) -> None:
		_delete_all_downtime_reasons()
		_insert_legacy_master("Maintenance", "90")
		_insert_legacy_master("TEA TIME", "91")

		convert_legacy_downtime_reasons()

		self.assertFalse(frappe.db.exists("Downtime Reason", "Maintenance"))
		self.assertFalse(frappe.db.exists("Downtime Reason", "TEA TIME"))
		self.assertEqual(frappe.db.get_value("Downtime Reason", "05", "description"), "Maintenance")
		self.assertEqual(frappe.db.get_value("Downtime Reason", "14", "description"), "Tea Break")
		self.assertTrue(frappe.db.get_value("Downtime Reason", "05", "is_active"))

	def test_curated_extra_rolls_composite_free_text_into_other(self) -> None:
		_delete_all_downtime_reasons()
		_insert_legacy_master("lunch & puwer cut", "90")

		convert_legacy_downtime_reasons()

		self.assertFalse(frappe.db.exists("Downtime Reason", "lunch & puwer cut"))
		self.assertEqual(frappe.db.get_value("Downtime Reason", "00", "description"), "Other")

	def test_extra_map_retargets_orphaned_loss_entry_references_when_master_is_absent(self) -> None:
		with (
			patch(f"{_CONVERSION_MODULE}.seed_standard_downtime_reasons"),
			patch(f"{_CONVERSION_MODULE}.assign_codes_to_uncoded_downtime_reasons"),
			patch(f"{_CONVERSION_MODULE}.frappe.db.exists", return_value=False),
			patch(f"{_CONVERSION_MODULE}.rename_doc") as rename_doc,
			patch(f"{_CONVERSION_MODULE}.frappe.db.set_value") as set_value,
		):
			convert_legacy_downtime_reasons()

		rename_doc.assert_not_called()
		self.assertEqual(
			set_value.call_count, len(LEGACY_DOWNTIME_REASON_CODES) + len(EXTRA_DOWNTIME_REASON_CODES)
		)
		set_value.assert_any_call(
			"Loss Entry",
			{"downtime_reason": "Maintenance"},
			"downtime_reason",
			"05",
			update_modified=False,
		)

	def test_genuinely_custom_extra_gets_deterministic_free_code(self) -> None:
		_delete_all_downtime_reasons()
		_insert_legacy_master("MATERIAL SHORT PART NO.84562", "90")
		_insert_legacy_master("Development Die issue", "91")

		convert_legacy_downtime_reasons()

		self.assertFalse(frappe.db.exists("Downtime Reason", "MATERIAL SHORT PART NO.84562"))
		self.assertFalse(frappe.db.exists("Downtime Reason", "Development Die issue"))
		self.assertEqual(frappe.db.get_value("Downtime Reason", "23", "description"), "Development Die issue")
		self.assertEqual(
			frappe.db.get_value("Downtime Reason", "24", "description"), "MATERIAL SHORT PART NO.84562"
		)

	def test_uncoded_master_with_quirk_code_field_is_still_coded(self) -> None:
		_delete_all_downtime_reasons()
		_insert_legacy_master("Inventory", "90")
		frappe.db.set_value("Downtime Reason", "Inventory", "code", "Inventory", update_modified=False)

		convert_legacy_downtime_reasons()

		self.assertFalse(frappe.db.exists("Downtime Reason", "Inventory"))
		self.assertEqual(frappe.db.get_value("Downtime Reason", "23", "description"), "Inventory")

	def test_custom_code_assignment_skips_codes_taken_by_existing_coded_masters(self) -> None:
		_delete_all_downtime_reasons()
		frappe.get_doc(
			{
				"doctype": "Downtime Reason",
				"code": "23",
				"description": "Prior Custom",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		_insert_legacy_master("Inventory", "90")
		_insert_legacy_master("Shift Close", "91")

		convert_legacy_downtime_reasons()

		self.assertEqual(frappe.db.get_value("Downtime Reason", "23", "description"), "Prior Custom")
		self.assertEqual(frappe.db.get_value("Downtime Reason", "24", "description"), "Inventory")
		self.assertEqual(frappe.db.get_value("Downtime Reason", "25", "description"), "Shift Close")

	def test_uncoded_assignment_is_a_noop_on_rerun(self) -> None:
		_delete_all_downtime_reasons()
		_insert_legacy_master("Machine Breakdown", "90")

		convert_legacy_downtime_reasons()
		before = frappe.get_all(
			"Downtime Reason", fields=["name", "code", "description", "is_active"], order_by="name"
		)

		convert_legacy_downtime_reasons()

		self.assertEqual(
			frappe.get_all(
				"Downtime Reason", fields=["name", "code", "description", "is_active"], order_by="name"
			),
			before,
		)
