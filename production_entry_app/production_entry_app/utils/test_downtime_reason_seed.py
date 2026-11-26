from __future__ import annotations

from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app.utils.downtime_reason_seed import (
	STANDARD_DOWNTIME_REASONS,
	ensure_downtime_reason,
	seed_standard_downtime_reasons,
)


def _reason_rows() -> list[dict]:
	return frappe.get_all(
		"Downtime Reason",
		fields=["name", "code", "description", "is_active", "modified"],
		order_by="name",
	)


class TestDowntimeReasonSeed(FrappeTestCase):
	def test_seed_creates_all_standard_masters_active_with_standard_descriptions(self) -> None:
		frappe.db.delete("Downtime Reason")

		seed_standard_downtime_reasons()

		rows = {row["name"]: row for row in _reason_rows()}
		self.assertEqual(set(rows), set(STANDARD_DOWNTIME_REASONS))
		for code, description in STANDARD_DOWNTIME_REASONS.items():
			self.assertEqual(rows[code]["code"], code)
			self.assertEqual(rows[code]["description"], description)
			self.assertTrue(rows[code]["is_active"])

	def test_seed_twice_is_a_noop_on_the_second_run(self) -> None:
		frappe.db.delete("Downtime Reason")
		seed_standard_downtime_reasons()

		before = _reason_rows()
		seed_standard_downtime_reasons()

		self.assertEqual(_reason_rows(), before)

	def test_seed_leaves_an_inactive_standard_master_inactive(self) -> None:
		ensure_downtime_reason("05")
		frappe.db.set_value("Downtime Reason", "05", "is_active", 0, update_modified=False)

		seed_standard_downtime_reasons()

		self.assertFalse(frappe.db.get_value("Downtime Reason", "05", "is_active"))

	def test_seed_preserves_an_edited_description(self) -> None:
		ensure_downtime_reason("01")
		frappe.db.set_value("Downtime Reason", "01", "description", "Die Change", update_modified=False)

		seed_standard_downtime_reasons()

		self.assertEqual(frappe.db.get_value("Downtime Reason", "01", "description"), "Die Change")

	def test_seed_leaves_non_standard_masters_untouched(self) -> None:
		frappe.get_doc(
			{"doctype": "Downtime Reason", "code": "77", "description": "Plant Specific", "is_active": 0}
		).insert(ignore_permissions=True)

		seed_standard_downtime_reasons()

		row = frappe.db.get_value("Downtime Reason", "77", ["description", "is_active"], as_dict=True)
		self.assertEqual(row.description, "Plant Specific")
		self.assertFalse(row.is_active)
		self.assertFalse(frappe.db.exists("Downtime Reason", "99"))

	def test_downtime_reasons_are_seeded_not_shipped_as_a_fixture(self) -> None:
		from production_entry_app import hooks

		fixtures_path = Path(frappe.get_app_path("production_entry_app")) / "fixtures"

		self.assertNotIn("Downtime Reason", hooks.fixtures)
		self.assertFalse((fixtures_path / "downtime_reason.json").exists())
