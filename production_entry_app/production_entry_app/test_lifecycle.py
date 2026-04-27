from __future__ import annotations

from unittest.mock import call, patch

from frappe.tests.utils import FrappeTestCase

from production_entry_app.production_entry_app import lifecycle


class TestLifecycle(FrappeTestCase):
	def test_after_sync_runs_idempotent_setup(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.lifecycle.access_control.invalidate_access_control_cache"
			) as invalidate_cache,
			patch(
				"production_entry_app.production_entry_app.lifecycle.performance_indexes.ensure_performance_indexes_with_recovery"
			) as ensure_indexes,
		):
			lifecycle.after_sync()

		invalidate_cache.assert_called_once_with()
		ensure_indexes.assert_called_once_with()

	def test_after_migrate_runs_idempotent_setup(self) -> None:
		with (
			patch(
				"production_entry_app.production_entry_app.lifecycle.access_control.invalidate_access_control_cache"
			) as invalidate_cache,
			patch(
				"production_entry_app.production_entry_app.lifecycle.performance_indexes.ensure_performance_indexes_with_recovery"
			) as ensure_indexes,
		):
			lifecycle.after_migrate()

		invalidate_cache.assert_called_once_with()
		ensure_indexes.assert_called_once_with()

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
