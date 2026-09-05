from __future__ import annotations

import unittest
from unittest.mock import Mock, call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import lifecycle


class TestReworkDetailsLayout(unittest.TestCase):
	def test_rework_details_section_follows_the_opening_section_across_versions(self) -> None:
		for version, fields, expected_anchor in (
			(
				"v15",
				[
					frappe._dict(fieldname="stock_entry_details_tab", fieldtype="Tab Break"),
					frappe._dict(fieldname="naming_series", fieldtype="Select"),
					frappe._dict(fieldname="stock_entry_type", fieldtype="Link"),
					frappe._dict(fieldname="apply_putaway_rule", fieldtype="Check"),
					frappe._dict(
						fieldname="custom_pea_rework_details_section",
						fieldtype="Section Break",
						is_custom_field=1,
					),
					frappe._dict(fieldname="custom_pea_rework_type", fieldtype="Link", is_custom_field=1),
					frappe._dict(fieldname="bom_info_section", fieldtype="Section Break"),
				],
				"apply_putaway_rule",
			),
			(
				"v16",
				[
					frappe._dict(fieldname="stock_entry_type", fieldtype="Link"),
					frappe._dict(fieldname="posting_time", fieldtype="Time"),
					frappe._dict(fieldname="branch", fieldtype="Link", is_custom_field=1),
					frappe._dict(fieldname="reference_section", fieldtype="Section Break"),
					frappe._dict(
						fieldname="custom_pea_rework_details_section",
						fieldtype="Section Break",
						is_custom_field=1,
					),
					frappe._dict(fieldname="apply_putaway_rule", fieldtype="Check"),
				],
				"branch",
			),
		):
			fake_frappe = Mock()
			fake_frappe.db.get_value.return_value = "stock_entry_type"
			fake_frappe.get_meta.return_value = frappe._dict(fields=fields)
			with self.subTest(version=version), patch.object(lifecycle, "frappe", fake_frappe):
				lifecycle.ensure_rework_details_layout()

			fake_frappe.db.set_value.assert_called_once_with(
				"Custom Field",
				"Stock Entry-custom_pea_rework_details_section",
				"insert_after",
				expected_anchor,
				update_modified=False,
			)
			fake_frappe.clear_cache.assert_called_once_with(doctype="Stock Entry")

	def test_rework_details_layout_is_idempotent(self) -> None:
		fields = [
			frappe._dict(fieldname="stock_entry_type", fieldtype="Link"),
			frappe._dict(fieldname="apply_putaway_rule", fieldtype="Check"),
			frappe._dict(fieldname="bom_info_section", fieldtype="Section Break"),
		]
		fake_frappe = Mock()
		fake_frappe.db.get_value.return_value = "apply_putaway_rule"
		fake_frappe.get_meta.return_value = frappe._dict(fields=fields)
		with patch.object(lifecycle, "frappe", fake_frappe):
			lifecycle.ensure_rework_details_layout()

		fake_frappe.db.set_value.assert_not_called()
		fake_frappe.clear_cache.assert_not_called()

	def test_rework_details_layout_stops_at_any_external_layout_boundary(self) -> None:
		for boundary in (
			frappe._dict(
				fieldname="third_party_section",
				fieldtype="Section Break",
				is_custom_field=1,
			),
			frappe._dict(fieldname="other_tab", fieldtype="Tab Break"),
		):
			fields = [
				frappe._dict(fieldname="stock_entry_type", fieldtype="Link"),
				frappe._dict(fieldname="opening_custom_field", fieldtype="Data", is_custom_field=1),
				boundary,
				frappe._dict(fieldname="later_field", fieldtype="Data"),
			]
			fake_frappe = Mock()
			fake_frappe.db.get_value.return_value = "wrong_anchor"
			fake_frappe.get_meta.return_value = frappe._dict(fields=fields)
			with self.subTest(boundary=boundary.fieldtype), patch.object(lifecycle, "frappe", fake_frappe):
				lifecycle.ensure_rework_details_layout()

			fake_frappe.db.set_value.assert_called_once_with(
				"Custom Field",
				"Stock Entry-custom_pea_rework_details_section",
				"insert_after",
				"opening_custom_field",
				update_modified=False,
			)

	def test_rework_details_layout_returns_before_fixture_exists(self) -> None:
		fake_frappe = Mock()
		fake_frappe.db.get_value.return_value = None
		with patch.object(lifecycle, "frappe", fake_frappe):
			lifecycle.ensure_rework_details_layout()

		fake_frappe.get_meta.assert_not_called()
		fake_frappe.db.set_value.assert_not_called()

	def test_rework_details_layout_returns_without_an_external_boundary(self) -> None:
		fake_frappe = Mock()
		fake_frappe.db.get_value.return_value = "wrong_anchor"
		fake_frappe.get_meta.return_value = frappe._dict(
			fields=[
				frappe._dict(fieldname="stock_entry_type", fieldtype="Link"),
				frappe._dict(fieldname="opening_field", fieldtype="Data"),
			]
		)
		with patch.object(lifecycle, "frappe", fake_frappe):
			lifecycle.ensure_rework_details_layout()

		fake_frappe.db.set_value.assert_not_called()
		fake_frappe.clear_cache.assert_not_called()


class TestLifecycle(FrappeTestCase):
	def test_after_sync_runs_idempotent_setup(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.lifecycle.ensure_rework_details_layout"
			) as ensure_rework_layout,
			patch(
				"production_entry_app.production_entry_app.lifecycle.performance_indexes.ensure_performance_indexes_with_recovery"
			) as ensure_indexes,
		):
			lifecycle.after_sync()

		ensure_rework_layout.assert_called_once_with()
		ensure_indexes.assert_called_once_with()

	def test_after_migrate_runs_idempotent_setup(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.lifecycle.ensure_rework_details_layout"
			) as ensure_rework_layout,
			patch(
				"production_entry_app.production_entry_app.lifecycle.performance_indexes.ensure_performance_indexes_with_recovery"
			) as ensure_indexes,
		):
			lifecycle.after_migrate()

		ensure_rework_layout.assert_called_once_with()
		ensure_indexes.assert_called_once_with()

	def test_setup_app_logs_summary(self) -> None:
		from production_entry_app.production_entry_app import lifecycle

		with patch("frappe.logger") as mock_logger:
			lifecycle._setup_app()
			mock_logger.assert_called_with("production_entry_app")
			assert mock_logger.return_value.info.called

	def test_before_uninstall_drops_indexes_and_deletes_only_app_owned_customizations(self) -> None:
		def fake_get_all(doctype: str, filters: dict[str, str] | None = None, pluck: str | None = None):
			self.assertEqual(filters, {"module": lifecycle.APP_MODULE})
			self.assertEqual(pluck, "name")
			if doctype == "Property Setter":
				return ["Stock Entry-use_multi_level_bom-default"]
			if doctype == "Custom Field":
				return ["Stock Entry-custom_pea_shift", "Workstation-custom_pea_standard_spm"]
			return []

		with (
			patch(
				"production_entry_app.production_entry_app.lifecycle.performance_indexes.drop_performance_indexes_if_exists"
			) as drop_indexes,
			patch(
				"production_entry_app.production_entry_app.lifecycle.frappe.get_all",
				side_effect=fake_get_all,
			),
			patch("production_entry_app.production_entry_app.lifecycle.frappe.delete_doc") as delete_doc,
		):
			lifecycle.before_uninstall()

		drop_indexes.assert_called_once_with()
		delete_doc.assert_has_calls(
			[
				call(
					"Property Setter",
					"Stock Entry-use_multi_level_bom-default",
					ignore_permissions=True,
					force=True,
				),
				call(
					"Custom Field",
					"Stock Entry-custom_pea_shift",
					ignore_permissions=True,
					force=True,
				),
				call(
					"Custom Field",
					"Workstation-custom_pea_standard_spm",
					ignore_permissions=True,
					force=True,
				),
			]
		)

	def test_before_uninstall_is_idempotent_when_nothing_remains(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.lifecycle.performance_indexes.drop_performance_indexes_if_exists"
			) as drop_indexes,
			patch(
				"production_entry_app.production_entry_app.lifecycle.frappe.get_all",
				return_value=[],
			) as get_all,
			patch("production_entry_app.production_entry_app.lifecycle.frappe.delete_doc") as delete_doc,
		):
			lifecycle.before_uninstall()

		drop_indexes.assert_called_once_with()
		self.assertEqual(get_all.call_count, 2)
		delete_doc.assert_not_called()
