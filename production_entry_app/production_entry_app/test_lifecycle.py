from __future__ import annotations

from unittest.mock import call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import lifecycle


class TestLifecycle(FrappeTestCase):
	def test_ensure_branch_field_creates_when_absent(self) -> None:
		if frappe.get_meta("Stock Entry", cached=True).has_field("branch"):
			self.skipTest("site already has a Stock Entry branch field")

		from production_entry_app.production_entry_app import lifecycle

		lifecycle.ensure_stock_entry_branch_field()
		frappe.clear_cache(doctype="Stock Entry")
		df = frappe.get_meta("Stock Entry", cached=True).get_field("branch")
		assert df is not None
		assert df.fieldtype == "Link" and df.options == "Branch"

	def test_ensure_branch_field_is_idempotent(self) -> None:
		from production_entry_app.production_entry_app import lifecycle

		lifecycle.ensure_stock_entry_branch_field()
		lifecycle.ensure_stock_entry_branch_field()  # second call must not raise or duplicate
		frappe.clear_cache(doctype="Stock Entry")
		fields = [f for f in frappe.get_meta("Stock Entry", cached=True).fields if f.fieldname == "branch"]
		assert len(fields) == 1

	def test_after_sync_runs_idempotent_setup(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.lifecycle.access_control.ensure_access_roles_and_settings"
			) as setup_access,
			patch(
				"production_entry_app.production_entry_app.lifecycle.field_permissions.ensure_pea_field_permissions"
			) as ensure_field_permissions,
			patch(
				"production_entry_app.production_entry_app.lifecycle.ensure_stock_entry_branch_field"
			) as ensure_branch_field,
			patch(
				"production_entry_app.production_entry_app.lifecycle.performance_indexes.ensure_performance_indexes_with_recovery"
			) as ensure_indexes,
		):
			lifecycle.after_sync()

		setup_access.assert_called_once_with()
		ensure_branch_field.assert_called_once_with()
		ensure_field_permissions.assert_called_once_with()
		ensure_indexes.assert_called_once_with()

	def test_after_migrate_runs_idempotent_setup(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.lifecycle.access_control.ensure_access_roles_and_settings"
			) as setup_access,
			patch(
				"production_entry_app.production_entry_app.lifecycle.field_permissions.ensure_pea_field_permissions"
			) as ensure_field_permissions,
			patch(
				"production_entry_app.production_entry_app.lifecycle.ensure_stock_entry_branch_field"
			) as ensure_branch_field,
			patch(
				"production_entry_app.production_entry_app.lifecycle.performance_indexes.ensure_performance_indexes_with_recovery"
			) as ensure_indexes,
		):
			lifecycle.after_migrate()

		setup_access.assert_called_once_with()
		ensure_branch_field.assert_called_once_with()
		ensure_field_permissions.assert_called_once_with()
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
